import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from . import contract, stubs

app = FastAPI(title="TailorFit API")

MAX_PHOTO_BYTES = 15 * 1024 * 1024


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
        "photos": {"front": {"url": f"stub://{request_id}/front"}, "side": {"url": f"stub://{request_id}/side"}},
    }
    try:
        contract.validate("CaptureRequest", request)
    except Exception as e:
        raise HTTPException(422, getattr(e, "message", str(e)))
    sheet = stubs.build_sheet(request_id, locale, height_cm)
    contract.validate("MeasurementSheet", sheet)
    return sheet
