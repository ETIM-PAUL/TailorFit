"""Real photo-to-measurements pipeline: SAM segmentation (phase 6) then 2D geometry (phase 8).

Quality gate (phase 5) is still a stub. Nothing is written to disk: photos live in memory
only for the length of the request.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

_SERVICES = Path(__file__).resolve().parents[2]
for _p in (_SERVICES / "segmentation", _SERVICES / "measurement"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import measure2d  # noqa: E402
import segment  # noqa: E402

from . import meta, stubs  # noqa: E402

_client: meta.MetaClient | None = None


def enabled() -> bool:
    """Real pipeline needs a Meta key; TAILORFIT_STUBS=1 forces the fake one."""
    if os.environ.get("TAILORFIT_STUBS") == "1":
        return False
    return bool(os.environ.get("MODEL_API_KEY") or os.environ.get("META_MODEL_API_KEY"))


def _get_client() -> meta.MetaClient:
    global _client
    if _client is None:
        _client = meta.MetaClient()
    return _client


class UserFacingError(Exception):
    """Something the customer can fix (bad photo), with a plain message."""


def run(request_id: str, locale: str, height_cm: float, front_jpeg: bytes, side_jpeg: bytes) -> dict:
    client = _get_client()
    try:
        with ThreadPoolExecutor(2) as pool:
            ff, sf = pool.submit(segment.segment_view, client, front_jpeg), pool.submit(segment.segment_view, client, side_jpeg)
            front, side = ff.result(), sf.result()
    except segment.NoPersonFound:
        raise UserFacingError("We couldn't find a person in one of the photos. Stand in view, head to feet, and retake.")
    verdicts = stubs.quality_gate(request_id, locale)
    borderline = any(v.get("borderline") for v in verdicts)
    try:
        items = measure2d.measure_from_masks(front.mask, side.mask, height_cm,
                                             (front.quality, side.quality), borderline)
    except measure2d.MeasureError as e:
        raise UserFacingError(f"We couldn't read your body from the photos ({e}). Retake both photos, head to feet.")
    return {"request_id": request_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "stub": False, "measurements": items}
