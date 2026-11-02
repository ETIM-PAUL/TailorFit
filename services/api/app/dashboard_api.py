"""Tailor dashboard API (login, orders, edits, cutting sheet) and the customer's own capture-link endpoints."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field

from . import auth, cutting_sheet, pipeline, store, whatsapp

router = APIRouter(prefix="/v1")
tailor = Depends(auth.require_tailor)

MEASUREMENT_NAMES = ["bust_chest", "waist", "hip", "neck", "arm_round", "thigh",
                     "shoulder_width", "sleeve_length", "top_length", "trouser_length", "inseam", "back_length"]
FABRIC_WIDTHS = (36, 45, 60)


def style_view(style_id: str | None) -> dict | None:
    if not style_id or style_id not in pipeline.CATALOG:
        return None
    return {"id": style_id, "name": pipeline.CATALOG[style_id]["name"]}


def order_view(o: dict) -> dict:
    """Everything the dashboard and the PDF need. Edits are shown beside the original, never over it."""
    sheet, edits = o.get("sheet"), o.get("edits") or {}
    measurements = []
    for m in (sheet or {}).get("measurements", []):
        cm = edits.get(m["name"], m["value_cm"])
        measurements.append({
            "name": m["name"], "original_cm": m["value_cm"], "value_cm": round(cm, 1), "value_in": round(cm / 2.54, 1),
            "edited": m["name"] in edits, "confidence_label": m["confidence_label"],
            "confidence_score": m["confidence_score"], "reason": m["reason"]})
    yardage = None
    if measurements and o.get("style_id"):
        allow = pipeline.calculator.Allowances(**(o.get("allowances") or {}))
        try:
            yardage = pipeline.calculator.calculate(o["style_id"], o["fabric_width_in"], measurements, allow)
        except pipeline.calculator.CalcError as e:
            yardage = {"error": str(e)}
    return {
        "id": o["id"], "status": o["status"], "customer": {"name": o["customer_name"], "phone": o["customer_phone"]},
        "style": style_view(o.get("style_id")), "fabric_width_in": o["fabric_width_in"], "height_cm": o.get("height_cm"),
        "created_at": o["created_at"], "measured_at": o.get("measured_at"), "measurements": measurements,
        "stub": bool((sheet or {}).get("stub")), "yardage": yardage,
        "allowances": pipeline.calculator.asdict(pipeline.calculator.Allowances(**(o.get("allowances") or {}))),
        "notes": o.get("notes") or "", "has_preview": bool(o["has_preview"]),
        "photos_kept": store.order_dir(o["id"]).is_dir() and any(p.name.endswith("-blurred.jpg") for p in store.order_dir(o["id"]).iterdir()),
        "deletion_requested_at": o.get("deletion_requested_at"), "photos_deleted_at": o.get("photos_deleted_at"),
        "capture_url": f"/capture/?order={o['capture_token']}",
        "whatsapp": {"phone_digits": whatsapp.normalize_phone(o.get("customer_phone")), "auto": whatsapp.configured()},
        "low_confidence": sum(1 for m in measurements if m["confidence_label"] == "low" and not m["edited"]),
    }


def _get(order_id: int) -> dict:
    o = store.get_order(order_id)
    if not o:
        raise HTTPException(404, "Order not found.")
    return o


# ---------------- tailor login ----------------

class Login(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response):
    token = auth.login(body.username, body.password, request.client.host if request.client else "?")
    response.set_cookie(auth.COOKIE, token, httponly=True, samesite="lax", max_age=auth.SESSION_SECONDS,
                        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
                        or os.environ.get("COOKIE_SECURE") == "1")
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    auth.logout(request.cookies.get(auth.COOKIE))
    response.delete_cookie(auth.COOKIE)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request):
    return {"logged_in": auth.is_logged_in(request), "configured": auth.configured()}


# ---------------- orders (tailor only) ----------------

class NewOrder(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(None, max_length=40)
    style_id: str | None = None
    fabric_width_in: int = 45


@router.post("/orders", dependencies=[tailor])
def create_order(body: NewOrder):
    if body.style_id and body.style_id not in pipeline.CATALOG:
        raise HTTPException(422, f"unknown style: {body.style_id}")
    if body.fabric_width_in not in FABRIC_WIDTHS:
        raise HTTPException(422, "fabric width must be 36, 45 or 60 inches")
    return order_view(store.create_order(body.customer_name.strip(), (body.phone or "").strip() or None, body.style_id, body.fabric_width_in))


@router.get("/orders", dependencies=[tailor])
def list_orders():
    out = []
    for o in store.list_orders():
        v = order_view(o)
        out.append({k: v[k] for k in ("id", "status", "customer", "style", "created_at", "measured_at", "low_confidence", "capture_url", "stub")}
                    | {"yardage": v["yardage"]["display"] if v["yardage"] and "display" in v["yardage"] else None})
    return out


@router.get("/orders/{order_id}", dependencies=[tailor])
def get_order(order_id: int):
    return order_view(_get(order_id))


class Patch(BaseModel):
    style_id: str | None = None
    fabric_width_in: int | None = None
    notes: str | None = Field(None, max_length=2000)
    allowances: dict[str, float] | None = None
    phone: str | None = Field(None, max_length=40)


@router.patch("/orders/{order_id}", dependencies=[tailor])
def patch_order(order_id: int, body: Patch):
    o = _get(order_id)
    fields = {}
    if body.style_id is not None:
        if body.style_id and body.style_id not in pipeline.CATALOG:
            raise HTTPException(422, f"unknown style: {body.style_id}")
        fields["style_id"] = body.style_id or None
    if body.fabric_width_in is not None:
        if body.fabric_width_in not in FABRIC_WIDTHS:
            raise HTTPException(422, "fabric width must be 36, 45 or 60 inches")
        fields["fabric_width_in"] = body.fabric_width_in
    if body.phone is not None:
        store.update_phone(order_id, body.phone.strip() or None)
    if body.notes is not None:
        fields["notes"] = body.notes
    if body.allowances is not None:
        merged = {**(o.get("allowances") or {}), **body.allowances}
        try:
            pipeline.calculator.Allowances(**merged).validate()
        except (TypeError, pipeline.calculator.CalcError) as e:
            raise HTTPException(422, str(e))
        fields["allowances"] = merged
    store.update_order(order_id, **fields)
    return order_view(_get(order_id))


class Edits(BaseModel):
    edits: dict[str, float | None]


@router.put("/orders/{order_id}/measurements", dependencies=[tailor])
def put_measurements(order_id: int, body: Edits):
    o = _get(order_id)
    if not o.get("sheet"):
        raise HTTPException(409, "This customer has not sent photos yet.")
    edits = dict(o.get("edits") or {})
    for name, value in body.edits.items():
        if name not in MEASUREMENT_NAMES:
            raise HTTPException(422, f"unknown measurement: {name}")
        if value is None:
            edits.pop(name, None)
        elif not 5 <= value <= 300:
            raise HTTPException(422, f"{name} must be between 5 and 300 cm")
        else:
            edits[name] = round(value, 1)
    store.update_order(order_id, edits=edits)
    return order_view(_get(order_id))


@router.get("/orders/{order_id}/preview.jpg", dependencies=[tailor])
def get_preview(order_id: int):
    _get(order_id)
    data = store.read_file(order_id, "preview.jpg")
    if data is None:
        raise HTTPException(404, "No preview for this order.")
    return RawResponse(data, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


@router.get("/orders/{order_id}/cutting-sheet.pdf", dependencies=[tailor])
def get_cutting_sheet(order_id: int):
    view = order_view(_get(order_id))
    if not view["measurements"]:
        raise HTTPException(409, "This customer has not sent photos yet.")
    pdf = cutting_sheet.build_pdf(view, store.read_file(order_id, "preview.jpg"))
    return RawResponse(pdf, media_type="application/pdf",
                       headers={"Content-Disposition": f'inline; filename="cutting-sheet-{order_id}.pdf"', "Cache-Control": "private, no-store"})


@router.post("/orders/{order_id}/send-whatsapp", dependencies=[tailor])
def send_whatsapp(order_id: int, request: Request):
    """Send the customer their capture link over WhatsApp (needs the Cloud API settings)."""
    o = _get(order_id)
    if not whatsapp.configured():
        raise HTTPException(503, "Automatic WhatsApp sending is not set up. Use the Open WhatsApp button instead.")
    base = whatsapp.public_base_url() or (request.headers.get("origin") or "").rstrip("/")
    if not base:
        raise HTTPException(422, "Set PUBLIC_BASE_URL so the link in the message can be opened from the customer's phone.")
    try:
        return {"sent": whatsapp.send_invite(o, base)}
    except whatsapp.WhatsAppError as e:
        raise HTTPException(502, str(e))


@router.delete("/orders/{order_id}/photos", dependencies=[tailor])
def delete_photos(order_id: int):
    _get(order_id)
    return {"deleted_files": store.delete_photos(order_id)}


@router.delete("/orders/{order_id}", dependencies=[tailor])
def delete_order(order_id: int):
    if not store.delete_order(order_id):
        raise HTTPException(404, "Order not found.")
    return {"ok": True}


# ---------------- customer's own link (no login; the token is the secret) ----------------

@router.get("/capture/{token}")
def capture_info(token: str):
    o = store.get_by_token(token)
    if not o:
        raise HTTPException(404, "This link is not valid.")
    return {"customer_first_name": o["customer_name"].split()[0], "style": style_view(o.get("style_id")), "measured": o["status"] == "measured"}


@router.post("/capture/{token}/delete-request")
def customer_delete_request(token: str):
    """The customer asks for their photos to be deleted. Done immediately; the tailor keeps the measurements."""
    o = store.get_by_token(token)
    if not o:
        raise HTTPException(404, "This link is not valid.")
    return {"deleted_files": store.delete_photos(o["id"], requested_by_customer=True)}
