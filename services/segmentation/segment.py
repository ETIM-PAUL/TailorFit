"""Phase 6: body masks and face blur from SAM 3.1.

`segment_view` takes one photo and returns a boolean full-frame body mask, a face-blurred
copy of the photo, and a quality score with reasons. The SAM client is passed in (see
services/api/app/meta.py) so this module has no network code of its own.

Mask decoding runs through Meta's @meta-sam/parser via decode.mjs (needs Node and
`npm install` in this folder).

Quality is a set of simple checks on the mask (cut-off at the frame edge, small in frame,
fragmentation, holes, multiple people, SAM's own confidence). It does not yet measure edge
sharpness or detect missing limbs; calibrate against the pilot photos before trusting it.
"""
import base64
import io
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

HERE = Path(__file__).resolve().parent
MAX_SIDE = 2048  # longest image side sent to SAM
SMALL_HOLE = 0.005  # holes smaller than this share of body area are filled


class SegmentationError(Exception):
    pass


class NoPersonFound(SegmentationError):
    pass


@dataclass
class ViewResult:
    mask: np.ndarray  # bool, full frame
    blurred_jpeg: bytes
    face_blurred: bool
    quality: float
    notes: list[str] = field(default_factory=list)
    confidence: float | None = None


def decode_masks(masks: list[dict]) -> list[np.ndarray]:
    """masks: [{encoding, payload, width, height}] -> list of (height, width) uint8 0/1 arrays."""
    if not masks:
        return []
    try:
        proc = subprocess.run(["node", str(HERE / "decode.mjs")], input=json.dumps(masks), capture_output=True,
                              text=True, timeout=60, cwd=HERE)
    except FileNotFoundError as e:
        raise SegmentationError("Node.js is required to decode SAM masks") from e
    if proc.returncode != 0:
        raise SegmentationError(f"mask decode failed: {proc.stderr.strip()[:300]}")
    out = []
    for m, b64 in zip(masks, json.loads(proc.stdout)):
        out.append(np.frombuffer(base64.b64decode(b64), np.uint8).reshape(m["height"], m["width"]))
    return out


def records_to_masks(records: list[dict], frame_w: int, frame_h: int) -> list[tuple[np.ndarray, dict]]:
    """Decode SAM records into full-frame boolean masks, paired with their box dicts."""
    rasters = decode_masks([{
        "encoding": "lossless" if r["mask"]["enc"] == "~" else "one_bit",
        "payload": r["mask"]["enc"] + r["mask"]["payload"],
        "width": r["mask"]["W"], "height": r["mask"]["H"],
    } for r in records])
    out = []
    for r, raster in zip(records, rasters):
        box = r["box"]
        # The raster covers the box but is capped at ~1024px on its long side, so it is
        # usually smaller than the box and must be scaled up to it (box edges are inclusive).
        box_w, box_h = box["x2"] - box["x1"] + 1, box["y2"] - box["y1"] + 1
        h, w = raster.shape
        if (w, h) != (box_w, box_h):
            im = Image.fromarray(raster * 255).resize((box_w, box_h), Image.BILINEAR)
            raster = (np.asarray(im) > 127).astype(np.uint8)
        full = np.zeros((frame_h, frame_w), bool)
        x0, y0 = box["x1"] + round(r["mask"]["x"] * box_w / w), box["y1"] + round(r["mask"]["y"] * box_h / h)
        x1, y1 = min(x0 + box_w, frame_w), min(y0 + box_h, frame_h)
        if x1 > x0 and y1 > y0:
            full[y0:y1, x0:x1] = raster[: y1 - y0, : x1 - x0].astype(bool)
        out.append((full, box))
    return out


def clean_mask(mask: np.ndarray) -> np.ndarray:
    """Keep the largest blob and fill small interior holes (big ones, like the gap between arm and torso, stay)."""
    labels, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, labels, range(1, n + 1))
        mask = labels == (1 + int(np.argmax(sizes)))
    area = int(mask.sum())
    holes = ndimage.binary_fill_holes(mask) & ~mask
    hl, hn = ndimage.label(holes)
    if hn:
        sizes = ndimage.sum(holes, hl, range(1, hn + 1))
        for i, size in enumerate(sizes, start=1):
            if size < SMALL_HOLE * area:
                mask = mask | (hl == i)
    return mask


def mask_quality(mask: np.ndarray, confidence: float | None, n_people: int) -> tuple[float, list[str]]:
    """Score 0-1 plus plain reasons. `mask` is the raw (uncleaned) chosen person mask."""
    notes: list[str] = []
    h, w = mask.shape
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return 0.0, ["no body found"]
    q = 1.0
    if rows[0] <= 1 or rows[-1] >= h - 2:
        q *= 0.5
        notes.append("head or feet cut off by the frame")
    if cols[0] <= 1 or cols[-1] >= w - 1 - 1:
        q *= 0.8
        notes.append("body touches the side of the frame")
    if (rows[-1] - rows[0] + 1) / h < 0.5:
        q *= 0.7
        notes.append("person is small in the frame")
    labels, n = ndimage.label(mask)
    if n > 1:
        sizes = ndimage.sum(mask, labels, range(1, n + 1))
        share = float(sizes.max() / sizes.sum())
        if share < 0.97:
            q *= share
            notes.append("mask is broken into pieces")
    filled = ndimage.binary_fill_holes(mask)
    hole_share = float((filled.sum() - mask.sum()) / max(filled.sum(), 1))
    if hole_share > 0.02:
        q *= max(0.3, 1 - hole_share * 5)
        notes.append("holes in the mask")
    if n_people > 1:
        q *= 0.7
        notes.append("more than one person in the photo")
    if confidence is not None:
        q *= 0.5 + 0.5 * confidence
    return round(max(0.0, min(1.0, q)), 2), notes


TOO_SMALL = 0.55   # body fills less than this share of the frame height: the person can step closer
EDGE = 0.012       # within this share of the frame edge counts as touching it


def classify_framing(mask: np.ndarray) -> dict:
    """Is the whole body in the frame, and is the person further away than they need to be?"""
    h, w = mask.shape
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        return {"status": "no_person", "height_fraction": 0.0}
    edge_y, edge_x = max(1, round(EDGE * h)), max(1, round(EDGE * w))
    head_cut, feet_cut = bool(rows[0] < edge_y), bool(rows[-1] >= h - edge_y)
    sides_cut = bool(cols[0] < edge_x or cols[-1] >= w - edge_x)
    frac = float((rows[-1] + 1 - rows[0]) / h)
    if head_cut and feet_cut:
        status = "both_cut"
    elif head_cut:
        status = "head_cut"
    elif feet_cut:
        status = "feet_cut"
    elif sides_cut:
        status = "sides_cut"
    elif frac < TOO_SMALL:
        status = "too_small"
    else:
        status = "ok"
    return {"status": status, "height_fraction": round(frac, 3)}


def framing(client, jpeg_bytes: bytes) -> dict:
    """One small SAM call to judge how a person is framed (used live while the customer lines up)."""
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        img.load()
    except Exception as e:
        raise ValueError("unreadable image") from e
    img = img.convert("RGB")
    img.thumbnail((640, 640))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    masks = records_to_masks(client.segment("person", url), *img.size)
    if not masks:
        return {"status": "no_person", "height_fraction": 0.0}
    return classify_framing(max((m for m, _ in masks), key=lambda m: m.sum()))


def blur_face(img: Image.Image, face_mask: np.ndarray) -> Image.Image:
    rows = np.flatnonzero(face_mask.any(axis=1))
    face_h = int(rows[-1] - rows[0] + 1)
    grow = max(3, face_h // 8)
    region = ndimage.binary_dilation(face_mask, iterations=grow)
    radius = max(12, face_h // 3)
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    return Image.composite(blurred, img, Image.fromarray((region * 255).astype(np.uint8)))


def segment_view(client, jpeg_bytes: bytes) -> ViewResult:
    """Segment one photo. Raises NoPersonFound if SAM sees nobody."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    scale = min(1.0, MAX_SIDE / max(img.size))
    if scale < 1.0:
        img = img.resize((round(img.width * scale), round(img.height * scale)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    w, h = img.size

    with ThreadPoolExecutor(2) as pool:
        person_f = pool.submit(client.segment, "person", url)
        face_f = pool.submit(client.segment, "face", url)
        person_recs, face_recs = person_f.result(), face_f.result()

    persons = records_to_masks(person_recs, w, h)
    if not persons:
        raise NoPersonFound("No person found in the photo")
    persons.sort(key=lambda p: p[0].sum(), reverse=True)
    raw, box = persons[0]
    n_people = 1 + sum(1 for m, _ in persons[1:] if m.sum() > 0.25 * raw.sum())
    quality, notes = mask_quality(raw, box.get("c"), n_people)

    # Blur every face that sits inside the person's box; if no face is found, say so and
    # lower quality so the photo is never shown unblurred without the flag being false.
    faces = [m for m, b in records_to_masks(face_recs, w, h)
             if (m & ndimage.binary_dilation(raw, iterations=10)).sum() > 0.5 * m.sum()]
    if faces:
        out = blur_face(img, np.logical_or.reduce(faces))
        face_blurred = True
    else:
        out, face_blurred = img, False
        notes.append("no face found to blur")
    ob = io.BytesIO()
    out.save(ob, "JPEG", quality=90)
    return ViewResult(mask=clean_mask(raw), blurred_jpeg=ob.getvalue(), face_blurred=face_blurred,
                      quality=quality, notes=notes, confidence=box.get("c"))


def save_view(result: ViewResult, out_dir: Path, view: str) -> dict:
    """Write the mask PNG and blurred photo; return a contract SegmentationOutput view entry."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mask_path, photo_path = out_dir / f"{view}-mask.png", out_dir / f"{view}-blurred.jpg"
    Image.fromarray((result.mask * 255).astype(np.uint8)).save(mask_path)
    photo_path.write_bytes(result.blurred_jpeg)
    return {"view": view, "mask_url": str(mask_path), "blurred_photo_url": str(photo_path),
            "face_blurred": result.face_blurred, "mask_quality": result.quality}
