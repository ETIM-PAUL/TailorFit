"""Phase 10: dress the customer in a chosen style and fabric.

Flow: SAM isolates the fabric pattern -> style comes from the catalog or from Muse Spark describing
an inspiration photo -> Muse Image redraws the (face-blurred) customer photo in that style -> Muse
Spark checks the body wasn't distorted -> a visible "Preview, not the final garment" label is burned in.

If the body was distorted, or the face could not be blurred, a neutral faceless model is shown
instead (the plan's fallback), so a real face is never shown unblurred.
"""
import base64
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import segment
from styles import CATALOG

LABEL = "Preview, not the final garment"
SWATCH_SIDE = 768
MIN_FABRIC_SHARE = 0.10  # the fabric must fill at least this share of its photo


class PreviewError(Exception):
    """Something the customer can fix, with a plain message."""


class NoFabricFound(PreviewError):
    pass


DESCRIBE_PROMPT = ("Describe only the cut of the main garment in this photo, for a tailor, in one sentence of at most 40 words: "
                   "garment type, neckline, sleeve length and shape, silhouette, length and notable details. "
                   "Do not mention colours, patterns, fabric, the person or the background.")

JUDGE_PROMPT = """Image 1 is the original photo of a person. Image 2 is an edited version where the person was dressed in different clothes.
Check whether the person's BODY in image 2 matches image 1: same height and stature, same body width and build, same pose, same proportions, same position in the frame, and the figure still shown from head to the bottom of the frame. Ignore the clothes and the fabric pattern, which are meant to change. A long garment such as a gown or robe may legitimately cover the legs and feet; that is fine. Wide sleeves or a flared skirt are also fine. Only report a problem if the person's height, build, pose or position changed, or the person is cropped by the frame.
Reply with JSON only: {"body_matches": true or false, "problem": "one short sentence, empty if it matches"}"""


def _data_url(img: Image.Image, side: int = 1280) -> str:
    im = img.convert("RGB")
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def _open(jpeg_bytes: bytes) -> Image.Image:
    try:
        im = Image.open(io.BytesIO(jpeg_bytes))
        im.load()
    except Exception as e:
        raise PreviewError("We couldn't read one of the photos. Try another one.") from e
    return im.convert("RGB")


def fabric_swatch(client, fabric_jpeg: bytes) -> Image.Image:
    """SAM finds the fabric; return a crop of just the cloth (edges trimmed so table or hands stay out)."""
    img = _open(fabric_jpeg)
    img.thumbnail((1600, 1600))
    masks = segment.records_to_masks(client.segment("fabric", _data_url(img, 1600)), *img.size)
    if not masks:
        raise NoFabricFound("We couldn't find the fabric in the photo. Lay it flat and fill the frame with it.")
    mask = max((m for m, _ in masks), key=lambda m: m.sum())
    if mask.mean() < MIN_FABRIC_SHARE:
        raise NoFabricFound("The fabric looks too small in the photo. Move closer so it fills the frame.")
    inner = ndimage.binary_erosion(mask, iterations=max(3, min(25, min(img.size) // 40)))
    if not inner.any():
        inner = mask
    ys, xs = np.nonzero(inner)
    swatch = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    swatch.thumbnail((SWATCH_SIDE, SWATCH_SIDE))
    return swatch


def describe_style(client, inspiration_jpeg: bytes) -> str:
    """Muse Spark turns an inspiration photo into a cut description for the image prompt."""
    text = client.check_photo(DESCRIBE_PROMPT, _data_url(_open(inspiration_jpeg))).strip().strip('"')
    if not text:
        raise PreviewError("We couldn't read the style from that photo. Try a clearer photo of the outfit.")
    return text[:400]


def _render_prompt(desc: str) -> str:
    return (f"Image 1 shows a person standing. Image 2 is a piece of printed fabric. Redraw the person in image 1 wearing {desc}, "
            "made entirely from the fabric in image 2, with the same print, colours and pattern. Keep the person's pose, body proportions, height, "
            "skin tone, blurred face and the plain background exactly as in image 1. Full body visible, photorealistic, well fitted.")


def _neutral_prompt(desc: str) -> str:
    return (f"Full-length studio photograph of a neutral, faceless mannequin standing front-on against a plain light background, wearing {desc}, "
            "made entirely from the fabric in the image provided, with the same print, colours and pattern. Full body visible, photorealistic.")


def _edit(client, prompt: str, images: list[str]) -> Image.Image:
    data = client.edit_image(prompt, images)["data"][0]
    if not data.get("b64_json"):
        raise PreviewError("The preview could not be drawn. Please try again.")
    return Image.open(io.BytesIO(base64.b64decode(data["b64_json"]))).convert("RGB")


def check_body(client, original: Image.Image, preview: Image.Image) -> tuple[bool, str]:
    """Muse Spark judge: same body, same proportions? Unreadable replies count as a pass, noted as unchecked."""
    text = client.compare_photos(JUDGE_PROMPT, [_data_url(original, 1024), _data_url(preview, 1024)])
    m = re.search(r"\{.*\}", text, re.S)
    try:
        verdict = json.loads(m.group(0)) if m else None
    except ValueError:
        verdict = None
    if not isinstance(verdict, dict) or not isinstance(verdict.get("body_matches"), bool):
        return True, "body check unavailable"
    return verdict["body_matches"], str(verdict.get("problem", ""))


def add_label(img: Image.Image, text: str = LABEL) -> Image.Image:
    """Burn the label into the pixels so it can't be cropped off by the page."""
    img = img.convert("RGB")
    size = max(16, img.width // 26)
    font = ImageFont.load_default(size=size)
    bar = size + size // 2
    out = img.copy()
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, out.height - bar, out.width, out.height], fill=(0, 0, 0, 170))
    d.text((out.width // 2, out.height - bar // 2), text, fill=(255, 255, 255, 255), font=font, anchor="mm")
    return Image.alpha_composite(out.convert("RGBA"), layer).convert("RGB")


def make_preview(client, customer_jpeg: bytes, fabric_jpeg: bytes, style_id: str | None = None,
                 inspiration_jpeg: bytes | None = None) -> dict:
    """Return {image_jpeg, mode, style_id, notes, label, seconds}. mode is 'customer' or 'neutral_model'."""
    if bool(style_id) == bool(inspiration_jpeg):
        raise ValueError("choose either a catalog style or an inspiration photo")
    if style_id and style_id not in CATALOG:
        raise ValueError(f"unknown style: {style_id}")
    start = time.perf_counter()

    with ThreadPoolExecutor(3) as pool:
        seg_f = pool.submit(segment.segment_view, client, customer_jpeg)
        fab_f = pool.submit(fabric_swatch, client, fabric_jpeg)
        desc_f = pool.submit(describe_style, client, inspiration_jpeg) if inspiration_jpeg else None
        try:
            seg = seg_f.result()
        except segment.NoPersonFound:
            raise PreviewError("We couldn't find a person in the photo. Stand in view, head to feet, and retake.")
        swatch = fab_f.result()
        desc = desc_f.result() if desc_f else CATALOG[style_id]["description"]

    notes: list[str] = []
    swatch_url = _data_url(swatch)
    original = _open(seg.blurred_jpeg)
    mode, image = "customer", None
    if not seg.face_blurred:
        notes.append("face could not be blurred, so a neutral model is shown")
        mode = "neutral_model"
    else:
        image = _edit(client, _render_prompt(desc), [_data_url(original), swatch_url])
        ok, problem = check_body(client, original, image)
        if not ok:
            notes.append(f"preview changed the body ({problem}), so a neutral model is shown")
            mode = "neutral_model"
        elif problem:
            notes.append(problem)
    if mode == "neutral_model":
        image = _edit(client, _neutral_prompt(desc), [swatch_url])

    out = io.BytesIO()
    add_label(image).save(out, "JPEG", quality=90)
    return {"image_jpeg": out.getvalue(), "mode": mode, "style_id": style_id or "inspiration",
            "notes": notes, "label": LABEL, "seconds": round(time.perf_counter() - start, 1)}
