"""Phase 5: photo quality gate.

Muse Spark rates each photo on a few checks; this module turns the ratings into a contract
`QualityVerdict`: any "major" fault rejects the photo with a plain-language fix, "minor"
faults pass it but mark it borderline so phase 9 lowers confidence instead of rejecting.

Messages are fixed text (not model-written) so wording is predictable and translatable.
The Pidgin text is a first draft and needs a native speaker's review.
"""
import base64
import io
import json
import re

from PIL import Image

CODES = ["loose_clothing", "posture", "arms_touching_body", "lighting", "occlusion", "not_full_body", "tilted"]
LOCALES = ("en", "pcm")

MESSAGES = {
    "en": {
        "loose_clothing": "Your clothes look loose. Wear something fitted so we can see your shape.",
        "posture": "Stand straight with your feet slightly apart and look ahead.",
        "arms_touching_body": "Hold your arms a little away from your body, about a hand's width.",
        "lighting": "The light is too dim or uneven. Move to a bright, even spot.",
        "occlusion": "Something is blocking your body. Clear the space or stand in front of a plain wall.",
        "not_full_body": "We can't see you from head to feet. Step back so your whole body is in the frame.",
        "tilted": "The phone is tilted. Hold it upright and level.",
    },
    "pcm": {  # DRAFT: needs review by a native Pidgin speaker
        "loose_clothing": "Your cloth wide too much. Wear something wey fit your body well.",
        "posture": "Stand up straight, put your legs small apart, and look front.",
        "arms_touching_body": "Hold your hand small away from your body, like one hand width.",
        "lighting": "The light no too bright or e no even. Go where light dey clear.",
        "occlusion": "Something dey cover your body. Comot am or stand for front of plain wall.",
        "not_full_body": "We no fit see you from head reach leg. Step back make your whole body enter the picture.",
        "tilted": "Phone dey lean. Hold am straight up.",
    },
}

_RATINGS = """Rate each check as "ok", "minor" or "major":
- loose_clothing: baggy or loose clothes that hide the body shape (major = hoodie, robe, gown, very baggy; minor = slightly loose)
- posture: {posture}
{arms}- lighting: too dark, too bright, strong shadows or backlighting
- occlusion: furniture, objects, other people or bags blocking part of the body
- not_full_body: the whole body from the top of the head to the feet is not visible
Reply with JSON only, no other text, exactly like: {example}"""

_HEAD = "You check photos for a tailoring measurement app. The photo should show ONE person standing for body measurements, view: {view}.\n"

PROMPTS = {
    "front": _HEAD.format(view="FRONT (facing the camera)") + _RATINGS.format(
        posture="not standing straight, leaning, bent knees, head turned, feet crossed, or sitting",
        arms="- arms_touching_body: arms or hands pressed against the torso, hips or pockets so the body outline is hidden; arms should be a hand's width away from the body\n",
        example='{"loose_clothing":"ok","posture":"ok","arms_touching_body":"ok","lighting":"ok","occlusion":"ok","not_full_body":"ok"}'),
    # In the side view the arms hang at the sides, so touching the body is expected and not checked.
    "side": _HEAD.format(view="SIDE (a true side profile, the person turned a quarter turn)") + _RATINGS.format(
        posture="not a true side profile (facing the camera or turned three-quarters), not standing straight, leaning, bent knees, or sitting",
        arms="",
        example='{"loose_clothing":"ok","posture":"ok","lighting":"ok","occlusion":"ok","not_full_body":"ok"}'),
}

TILT_MINOR, TILT_MAJOR = 5.0, 10.0
_RANK = {"ok": 0, "minor": 1, "major": 2}


def _data_url(jpeg_bytes: bytes) -> str:
    im = Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")
    im.thumbnail((1280, 1280))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def parse_ratings(text: str) -> dict[str, str] | None:
    """Pull {check: ok|minor|major} out of the model's reply, or None if unusable."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        raw = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    return {k: v for k, v in raw.items() if k in CODES and v in _RANK}


def _message(code: str, locale: str) -> str:
    return MESSAGES.get(locale, MESSAGES["en"])[code]


def build_verdict(view: str, ratings: dict[str, str], locale: str = "en", tilt_degrees: float | None = None) -> dict:
    issues, worst = [], 0
    ratings = dict(ratings)
    if tilt_degrees is not None and abs(tilt_degrees) > TILT_MINOR:
        ratings["tilted"] = "major" if abs(tilt_degrees) > TILT_MAJOR else "minor"
    for code in CODES:
        level = ratings.get(code, "ok")
        if level != "ok":
            issues.append({"code": code, "message": _message(code, locale), "_level": level})
            worst = max(worst, _RANK[level])
    for i in issues:
        i.pop("_level")
    return {"view": view, "passed": worst < 2, "borderline": worst == 1, "issues": issues}


def check_view(client, jpeg_bytes: bytes, view: str, locale: str = "en", tilt_degrees: float | None = None) -> dict:
    """Rate one photo. If the model reply can't be read the photo is let through as borderline, not blocked."""
    text = client.check_photo(PROMPTS[view], _data_url(jpeg_bytes))
    ratings = parse_ratings(text)
    if ratings is None:
        return {"view": view, "passed": True, "borderline": True, "issues": []}
    return build_verdict(view, ratings, locale, tilt_degrees)


def add_issue(verdict: dict, code: str, locale: str = "en", major: bool = True) -> dict:
    """Add a fault found by another check (e.g. the mask shows the feet are cut off)."""
    if any(i["code"] == code for i in verdict["issues"]):
        return verdict
    verdict["issues"].append({"code": code, "message": _message(code, locale)})
    if major:
        verdict["passed"] = False
    else:
        verdict["borderline"] = True
    return verdict
