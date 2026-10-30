"""Fake versions of every pipeline stage, returning contract-shaped data.

Each function is replaced by the real service in its own phase. Keep signatures
and return shapes in line with packages/contract/contract.schema.json.
"""
from datetime import datetime, timezone

from .contract import MEASUREMENT_NAMES

_FAKE_CM = {
    "bust_chest": 92.0, "waist": 76.0, "hip": 98.0, "neck": 37.0, "arm_round": 29.0, "thigh": 56.0,
    "shoulder_width": 42.0, "sleeve_length": 60.0, "top_length": 70.0,
    "trouser_length": 102.0, "inseam": 78.0, "back_length": 41.0,
}


def quality_gate(request_id: str, locale: str) -> list[dict]:  # phase 5
    return [{"view": v, "passed": True, "borderline": False, "issues": []} for v in ("front", "side")]


def segmentation(request_id: str) -> dict:  # phase 6
    return {
        "request_id": request_id,
        "views": [
            {"view": v, "mask_url": f"stub://{request_id}/{v}-mask.png", "face_blurred": True, "mask_quality": 0.9}
            for v in ("front", "side")
        ],
    }


def body_fit(request_id: str, height_cm: float) -> dict:  # phase 7
    return {
        "request_id": request_id,
        "body_url": f"stub://{request_id}/body.obj",
        "fitted_height_cm": height_cm,
        "scale_source": "stated_height",
        "front_side_agreement": 0.9,
    }


def measure(body: dict) -> dict[str, float]:  # phase 8
    return dict(_FAKE_CM)


def confidence(name: str, verdicts: list[dict], seg: dict) -> tuple[float, str, str]:  # phase 9
    return 0.5, "medium", "stub value, not measured"


def build_sheet(request_id: str, locale: str, height_cm: float) -> dict:
    verdicts = quality_gate(request_id, locale)
    seg = segmentation(request_id)
    body = body_fit(request_id, height_cm)
    values = measure(body)
    items = []
    for name in MEASUREMENT_NAMES:
        score, label, reason = confidence(name, verdicts, seg)
        cm = values[name]
        items.append({
            "name": name, "value_cm": cm, "value_in": round(cm / 2.54, 1),
            "confidence_score": score, "confidence_label": label, "reason": reason,
        })
    return {
        "request_id": request_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stub": True,
        "measurements": items,
    }
