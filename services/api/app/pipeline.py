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
for _p in (_SERVICES / "segmentation", _SERVICES / "measurement", _SERVICES / "quality-gate", _SERVICES / "confidence", _SERVICES / "style-preview", _SERVICES / "fabric-calculator"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import calculator  # noqa: E402
import confidence  # noqa: E402
import gate  # noqa: E402
import measure2d  # noqa: E402
import preview  # noqa: E402
import segment  # noqa: E402
from styles import CATALOG  # noqa: E402

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


class PhotoRejected(Exception):
    """The quality gate refused one or both photos. `issues` is [{view, code, message}]."""

    def __init__(self, issues: list[dict]):
        super().__init__("photo rejected")
        self.issues = issues


def _gate(client, jpeg: bytes, view: str, locale: str, tilt: float | None) -> dict:
    """Quality check that never blocks the customer if the checker itself is down."""
    try:
        return gate.check_view(client, jpeg, view, locale, tilt)
    except meta.MetaAPIError:
        return {"view": view, "passed": True, "borderline": True, "issues": []}


def run(request_id: str, locale: str, height_cm: float, front_jpeg: bytes, side_jpeg: bytes,
        front_tilt: float | None = None, side_tilt: float | None = None) -> dict:
    client = _get_client()
    photos = {"front": (front_jpeg, front_tilt), "side": (side_jpeg, side_tilt)}
    with ThreadPoolExecutor(4) as pool:
        gates = {v: pool.submit(_gate, client, j, v, locale, t) for v, (j, t) in photos.items()}
        segs = {v: pool.submit(segment.segment_view, client, j) for v, (j, _) in photos.items()}
        verdicts = {v: f.result() for v, f in gates.items()}
        try:
            results = {v: f.result() for v, f in segs.items()}
        except segment.NoPersonFound:
            raise UserFacingError("We couldn't find a person in one of the photos. Stand in view, head to feet, and retake.")

    # The mask is a more reliable check for "head or feet cut off" than the model's opinion.
    for v, res in results.items():
        if any("cut off" in n for n in res.notes):
            gate.add_issue(verdicts[v], "not_full_body", locale)
    rejected = [{"view": v, "code": i["code"], "message": i["message"]}
                for v in ("front", "side") if not verdicts[v]["passed"] for i in verdicts[v]["issues"]]
    if rejected:
        raise PhotoRejected(rejected)

    borderline = any(v["borderline"] for v in verdicts.values())
    try:
        items = measure2d.measure_from_masks(results["front"].mask, results["side"].mask, height_cm,
                                             (results["front"].quality, results["side"].quality), borderline)
    except measure2d.MeasureError as e:
        raise UserFacingError(f"We couldn't read your body from the photos ({e}). Retake both photos, head to feet.")
    # Offsets from the pilot calibration (services/confidence/corrections.json); empty until the pilot says otherwise.
    items = confidence.apply_corrections(items, confidence.load_corrections())
    # "_blurred" is not part of the contract; the API pops it (only used if the customer chose to keep photos).
    return {"request_id": request_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "stub": False, "measurements": items, "_blurred": {v: r.blurred_jpeg for v, r in results.items()}}


def make_preview(customer_jpeg: bytes, fabric_jpeg: bytes, style_id: str | None, inspiration_jpeg: bytes | None) -> dict:
    return preview.make_preview(_get_client(), customer_jpeg, fabric_jpeg, style_id, inspiration_jpeg)


PreviewError = preview.PreviewError
