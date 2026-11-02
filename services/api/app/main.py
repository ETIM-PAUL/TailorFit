import base64
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles

from . import contract, meta, pipeline, stubs
from .env import load_env

load_env()

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
    photos = {}
    for view, upload in (("front", front), ("side", side)):
        data = await upload.read()
        if not data:
            raise HTTPException(422, f"{upload.filename or 'photo'} is empty")
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, "photo too large")
        photos[view] = data
    # Validate the request against the contract. Photo URLs are placeholders until storage exists.
    request = {
        "request_id": request_id, "height_cm": height_cm, "consent": consent, "locale": locale,
        "photos": {"front": _photo("front", request_id, front_tilt), "side": _photo("side", request_id, side_tilt)},
    }
    try:
        contract.validate("CaptureRequest", request)
    except Exception as e:
        raise HTTPException(422, getattr(e, "message", str(e)))
    if pipeline.enabled():
        try:
            sheet = await run_in_threadpool(pipeline.run, request_id, locale, height_cm, photos["front"], photos["side"], front_tilt, side_tilt)
        except pipeline.PhotoRejected as e:
            raise HTTPException(422, {"error": "photo_rejected", "issues": e.issues})
        except pipeline.UserFacingError as e:
            raise HTTPException(422, str(e))
        except meta.MetaAPIError:
            raise HTTPException(503, "The measurement service is busy. Please try again in a minute.")
    else:
        sheet = stubs.build_sheet(request_id, locale, height_cm)
    contract.validate("MeasurementSheet", sheet)
    return sheet


@app.get("/v1/styles")
def list_styles():
    return [{"id": k, "name": v["name"]} for k, v in pipeline.CATALOG.items()]


@app.post("/v1/previews")
async def create_preview(
    front: UploadFile = File(...),
    fabric: UploadFile = File(...),
    consent: bool = Form(...),
    style_id: str | None = Form(None),
    inspiration: UploadFile | None = File(None),
):
    """Customer photo + fabric photo + a catalog style (or an inspiration photo) in, preview image out."""
    if not consent:
        raise HTTPException(422, "consent is required")
    if bool(style_id) == bool(inspiration):
        raise HTTPException(422, "choose either a style from the catalog or an inspiration photo")
    if style_id and style_id not in pipeline.CATALOG:
        raise HTTPException(422, f"unknown style: {style_id}")
    if not pipeline.enabled():
        raise HTTPException(503, "Style preview needs the Meta Model API key to be configured.")
    data = {}
    for name, upload in (("front", front), ("fabric", fabric), ("inspiration", inspiration)):
        if upload is None:
            continue
        blob = await upload.read()
        if not blob:
            raise HTTPException(422, f"{name} photo is empty")
        if len(blob) > MAX_PHOTO_BYTES:
            raise HTTPException(413, f"{name} photo too large")
        data[name] = blob
    try:
        result = await run_in_threadpool(pipeline.make_preview, data["front"], data["fabric"], style_id, data.get("inspiration"))
    except (pipeline.PreviewError, ValueError) as e:
        raise HTTPException(422, str(e))
    except meta.MetaAPIError:
        raise HTTPException(503, "The preview service is busy. Please try again in a minute.")
    return {"request_id": f"req_{uuid.uuid4().hex[:12]}", "style_id": result["style_id"], "mode": result["mode"],
            "label": result["label"], "notes": result["notes"], "seconds": result["seconds"],
            "media_type": "image/jpeg", "image_base64": base64.b64encode(result["image_jpeg"]).decode()}


# The capture page is served last so it never shadows the API routes.
_CAPTURE = Path(__file__).resolve().parents[3] / "apps" / "web" / "capture"
app.mount("/", StaticFiles(directory=_CAPTURE, html=True), name="capture")
