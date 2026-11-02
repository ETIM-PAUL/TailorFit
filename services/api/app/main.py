import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from . import contract, stubs

app = FastAPI(title="TailorFit API")

MAX_PHOTO_BYTES = 15 * 1024 * 1024


def _photo(view: str, request_id: str, tilt: float | None) -> dict:
    photo = {"url": f"stub://{request_id}/{view}"}
    if tilt is not None:
        photo["tilt_degrees"] = tilt
    return photo


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/measurements")
async def create_measurements(
    front: UploadFile = File(...),
    side: UploadFile = File(...),
    height_cm: float = Form(...),
    consent: bool = Form(...),
    locale: str = Form("en"),
    front_tilt: float | None = Form(None),
    side_tilt: float | None = Form(None),
):
    """Photos + height in, measurement sheet out (stubbed until phases 5-9 land)."""
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    for upload in (front, side):
        data = await upload.read()
        if not data:
            raise HTTPException(422, f"{upload.filename or 'photo'} is empty")
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "photo too large")
    # Validate the request against the contract. Photo URLs are placeholders until storage exists.
    request = {
        "request_id": request_id, "height_cm": height_cm, "consent": consent, "locale": locale,
        "photos": {"front": _photo("front", request_id, front_tilt), "side": _photo("side", request_id, side_tilt)},
    }
    try:
        contract.validate("CaptureRequest", request)
    except Exception as e:
        raise HTTPException(422, getattr(e, "message", str(e)))
    sheet = stubs.build_sheet(request_id, locale, height_cm)
    contract.validate("MeasurementSheet", sheet)
    return sheet


# The capture page is served last so it never shadows the API routes.
_CAPTURE = Path(__file__).resolve().parents[3] / "apps" / "web" / "capture"
app.mount("/", StaticFiles(directory=_CAPTURE, html=True), name="capture")
