import base64
import json
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import contract, dashboard_api, images, learning, meta, pipeline, security, store, stubs, whatsapp
from .env import load_env

load_env()

app = FastAPI(title="TailorFit API")
app.include_router(dashboard_api.router)


@app.middleware("http")
async def protect(request: Request, call_next):
    if security.cross_site(request):
        resp = JSONResponse({"detail": "Cross-site request refused."}, status_code=403)
    else:
        resp = await call_next(request)
    security.security_headers(request, resp.headers)
    return resp


_FIELD_NAMES = {"height_cm": "your height", "consent": "your consent", "front": "the front photo", "side": "the side photo",
                "fabric": "the fabric photo", "frame": "the camera frame", "style_id": "the style"}


@app.exception_handler(RequestValidationError)
async def friendly_validation_error(request: Request, exc: RequestValidationError):
    """Plain sentences instead of FastAPI's technical error list, so the pages can show them as they are."""
    fields = list(dict.fromkeys(_FIELD_NAMES.get(str(e["loc"][-1]), str(e["loc"][-1])) for e in exc.errors()))
    return JSONResponse({"detail": "Please check " + ", ".join(fields) + "."}, status_code=422)

MAX_PHOTO_BYTES = 15 * 1024 * 1024


def _photo(view: str, request_id: str, tilt: float | None) -> dict:
    photo = {"url": f"stub://{request_id}/{view}"}
    if tilt is not None:
        photo["tilt_degrees"] = tilt
    return photo


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/v1/measurements", dependencies=[Depends(security.limit("measure", 15))])
async def create_measurements(
    front: UploadFile = File(...),
    side: UploadFile = File(...),
    height_cm: float = Form(...),
    consent: bool = Form(...),
    locale: str = Form("en"),
    front_tilt: float | None = Form(None),
    side_tilt: float | None = Form(None),
    order_token: str | None = Form(None),
    keep_photos: bool = Form(False),
    response: Response = None,
    background_tasks: BackgroundTasks = None,
):
    """Photos + height in, measurement sheet out. With an order link, the sheet is saved to that order."""
    order = None
    if order_token:
        order = store.get_by_token(order_token)
        if not order:
            raise HTTPException(404, "This link is not valid.")
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    photos = {}
    for view, upload in (("front", front), ("side", side)):
        data = await upload.read()
        if not data:
            raise HTTPException(422, f"The {view} photo is empty.")
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(413, f"The {view} photo is too large.")
        try:
            photos[view] = images.normalize(data, f"{view} photo")
        except images.ImageError as e:
            raise HTTPException(422, str(e))
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
    blurred = sheet.pop("_blurred", None)
    applied: dict = {}
    if order and not sheet.get("stub"):
        sheet["measurements"], applied = learning.apply(sheet["measurements"])  # this tailor's earlier tape values
    contract.validate("MeasurementSheet", sheet)
    kept = False
    if order:
        # Photos are only kept if the customer opted in, and only the face-blurred versions (never in stub mode).
        kept = bool(keep_photos and blurred)
        store.attach_sheet(order_token, sheet, height_cm, kept, applied)
        store.clear_files(order["id"])  # a retake replaces whatever was kept before, including an old preview
        store.set_preview_flag(order["id"], False)
        if kept:
            for view, data in blurred.items():
                store.save_file(order["id"], f"{view}-blurred.jpg", data)
    if order and background_tasks is not None and whatsapp.configured():
        background_tasks.add_task(whatsapp.notify_measured, order)  # best effort, after the response is sent
    if response is not None:
        response.headers["X-Photos-Kept"] = "true" if kept else "false"
    return sheet


@app.post("/v1/framing", dependencies=[Depends(security.limit("framing", 60))])
async def framing(frame: UploadFile = File(...)):
    """Live check while the customer lines up: is the whole body in view? Nothing is stored."""
    if not pipeline.enabled():
        raise HTTPException(503, "Live framing needs the Meta Model API key to be configured.")
    data = await frame.read()
    if not data:
        raise HTTPException(422, "empty frame")
    if len(data) > 3 * 1024 * 1024:
        raise HTTPException(413, "frame too large")
    try:
        data = images.normalize(data, "camera frame", max_side=640)
        return await run_in_threadpool(pipeline.framing, data)
    except images.ImageError as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    except meta.MetaAPIError:
        raise HTTPException(503, "The framing check is busy.")


@app.get("/v1/whatsapp/webhook", include_in_schema=False)
def whatsapp_verify(mode: str | None = Query(None, alias="hub.mode"), token: str | None = Query(None, alias="hub.verify_token"),
                    challenge: str | None = Query(None, alias="hub.challenge")):
    """Meta's one-time handshake when the webhook is registered: echo the challenge if the verify token matches."""
    if not whatsapp.configured():
        raise HTTPException(503, "WhatsApp is not set up on this server.")
    echo = whatsapp.verify_handshake(mode, token, challenge)
    if echo is None:
        raise HTTPException(403, "verification failed")
    return PlainTextResponse(echo)


@app.post("/v1/whatsapp/webhook", include_in_schema=False)
async def whatsapp_incoming(request: Request):
    """Messages from customers. Every request is checked against Meta's signature before it is read."""
    if not whatsapp.configured():
        raise HTTPException(503, "WhatsApp is not set up on this server.")
    raw = await request.body()
    if not whatsapp.signature_ok(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "bad signature")
    try:
        payload = json.loads(raw)
    except ValueError:
        return {"ok": True}  # signed but unreadable: nothing to do, and an error would only make Meta retry
    await run_in_threadpool(whatsapp.handle_webhook, payload)
    return {"ok": True}


@app.get("/v1/styles")
def list_styles():
    return [{"id": k, "name": v["name"]} for k, v in pipeline.CATALOG.items()]


@app.post("/v1/previews", dependencies=[Depends(security.limit("preview", 6))])
async def create_preview(
    front: UploadFile = File(...),
    fabric: UploadFile = File(...),
    consent: bool = Form(...),
    style_id: str | None = Form(None),
    inspiration: UploadFile | None = File(None),
    order_token: str | None = Form(None),
):
    """Customer photo + fabric photo + a catalog style (or an inspiration photo) in, preview image out.

    With an order link the (face-blurred, generated) preview is also sent to that order for the tailor.
    """
    order = None
    if order_token:
        order = store.get_by_token(order_token)
        if not order:
            raise HTTPException(404, "This link is not valid.")
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
            raise HTTPException(422, f"The {name} photo is empty.")
        if len(blob) > MAX_PHOTO_BYTES:
            raise HTTPException(413, f"The {name} photo is too large.")
        try:
            data[name] = images.normalize(blob, f"{name} photo")
        except images.ImageError as e:
            raise HTTPException(422, str(e))
    try:
        result = await run_in_threadpool(pipeline.make_preview, data["front"], data["fabric"], style_id, data.get("inspiration"))
    except (pipeline.PreviewError, ValueError) as e:
        raise HTTPException(422, str(e))
    except meta.MetaAPIError:
        raise HTTPException(503, "The preview service is busy. Please try again in a minute.")
    if order:
        store.save_file(order["id"], "preview.jpg", result["image_jpeg"])
        store.set_preview_flag(order["id"], True)
    return {"request_id": f"req_{uuid.uuid4().hex[:12]}", "style_id": result["style_id"], "mode": result["mode"],
            "label": result["label"], "notes": result["notes"], "seconds": result["seconds"],
            "media_type": "image/jpeg", "image_base64": base64.b64encode(result["image_jpeg"]).decode()}


class MeasurementIn(BaseModel):
    name: str
    value_cm: float
    confidence_label: str | None = None


class AllowancesIn(BaseModel):
    seam_in: float | None = None
    hem_in: float | None = None
    shrink_pct: float | None = None
    extra_pct: float | None = None
    pattern_match_pct: float | None = None
    round_to_yd: float | None = None


class YardageRequest(BaseModel):
    style_id: str
    fabric_width_in: int = 45
    measurements: list[MeasurementIn]
    allowances: AllowancesIn | None = None  # the tailor's settings; anything left out uses the default


@app.post("/v1/yardage")
def yardage(req: YardageRequest):
    """Yards of fabric a style needs, from the measurement sheet, the cloth width and the tailor's allowances."""
    allow = pipeline.calculator.Allowances(**req.allowances.model_dump(exclude_none=True)) if req.allowances else None
    try:
        return pipeline.calculator.calculate(req.style_id, req.fabric_width_in, [m.model_dump() for m in req.measurements], allow)
    except pipeline.calculator.CalcError as e:
        raise HTTPException(422, str(e))


# Static pages are served last so they never shadow the API routes.
_WEB = Path(__file__).resolve().parents[3] / "apps" / "web"


@app.get("/", include_in_schema=False)
def home(order: str | None = None):
    """Landing page. Links made before the capture page moved to /capture/ still work."""
    if order:
        return RedirectResponse(f"/capture/?order={quote(order)}")
    return FileResponse(_WEB / "landing" / "index.html")


app.mount("/dashboard", StaticFiles(directory=_WEB / "dashboard", html=True), name="dashboard")
app.mount("/capture", StaticFiles(directory=_WEB / "capture", html=True), name="capture")
app.mount("/", StaticFiles(directory=_WEB / "landing", html=True), name="landing")  # landing page assets
