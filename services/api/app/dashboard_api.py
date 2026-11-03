"""Tailor dashboard API (login, orders, edits, cutting sheet) and the customer's own capture-link endpoints."""
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, Field

from . import auth, cutting_sheet, learning, pipeline, repeat, store, whatsapp

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
    yardage, finished, ease = None, None, None
    if measurements and o.get("style_id"):
        allow = pipeline.calculator.Allowances(**(o.get("allowances") or {}))
        try:
            yardage = pipeline.calculator.calculate(o["style_id"], o["fabric_width_in"], measurements, allow)
            finished = finished_view(o["style_id"], measurements, allow)
        except pipeline.calculator.CalcError as e:
            yardage = {"error": str(e)}
        defaults = pipeline.calculator.STYLE_EASE_IN[o["style_id"]]
        ease = {"defaults": defaults, "values": {part: allow.ease(o["style_id"], part) for part in defaults}}
    carried = o.get("carried_from")
    tape_first = tape_priority(measurements) if not (sheet or {}).get("stub") and not carried else []
    return {
        "tape_first": tape_first, "carried_from": {"order_id": carried, "measured_at": o.get("measured_at")} if carried else None,
        "id": o["id"], "status": o["status"], "customer": {"id": o["customer_id"], "name": o["customer_name"], "phone": o["customer_phone"]},
        "style": style_view(o.get("style_id")), "fabric_width_in": o["fabric_width_in"], "height_cm": o.get("height_cm"),
        "created_at": o["created_at"], "measured_at": o.get("measured_at"), "measurements": measurements,
        "stub": bool((sheet or {}).get("stub")), "yardage": yardage, "finished": finished, "ease": ease,
        "allowances": pipeline.calculator.asdict(pipeline.calculator.Allowances(**(o.get("allowances") or {}))),
        "notes": o.get("notes") or "", "has_preview": bool(o["has_preview"]),
        "photos_kept": store.order_dir(o["id"]).is_dir() and any(p.name.endswith("-blurred.jpg") for p in store.order_dir(o["id"]).iterdir()),
        "deletion_requested_at": o.get("deletion_requested_at"), "photos_deleted_at": o.get("photos_deleted_at"),
        "capture_url": f"/capture/?order={o['capture_token']}",
        "whatsapp": {"phone_digits": whatsapp.normalize_phone(o.get("customer_phone")), "auto": whatsapp.configured()},
        "low_confidence": sum(1 for m in measurements if m["confidence_label"] == "low" and not m["edited"]),
    }


TAPE_FIRST_COUNT = 3
RANK = {"high": 2, "medium": 1, "low": 0}


def finished_view(style_id: str, measurements: list[dict], allow) -> list[dict]:
    """Finished garment sizes, each carrying the weakest confidence among the body numbers it came from (a taped number counts as high)."""
    by_name = {m["name"]: m for m in measurements}
    rows = pipeline.calculator.finished_measurements(style_id, measurements, allow)
    for r in rows:
        labels = ["high" if by_name[n]["edited"] else by_name[n]["confidence_label"] for n in r["sources"]]
        r["confidence_label"] = min(labels, key=RANK.get)
        r["sources"] = [{"name": n, "label": l} for n, l in zip(r["sources"], labels)]
    return rows


def tape_priority(measurements: list[dict]) -> list[str]:
    """Which numbers to check with a tape first: the ones we trust least and that have the most room to be wrong.

    Unchecked numbers only. Ranked by confidence score, then by the typical benchmark error for that measurement
    (so chest comes before neck when both are low). Numbers we label high are never listed.
    """
    typical = pipeline.measure2d.TYPICAL_ERROR_CM
    todo = [m for m in measurements if not m["edited"] and m["confidence_label"] != "high"]
    todo.sort(key=lambda m: (m["confidence_score"], -typical.get(m["name"], 5.0)))
    return [m["name"] for m in todo[:TAPE_FIRST_COUNT]]


def full_view(o: dict) -> dict:
    """order_view plus what needs the customer's other orders (single-order screens only: it costs a query)."""
    orders = store.orders_for_customer(o["customer_id"])
    return order_view(o) | {"order_count": len(orders), "changes": repeat.changes(o, orders), "can_repeat": repeat.latest_source(orders) is not None}


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
    return full_view(store.create_order(body.customer_name.strip(), (body.phone or "").strip() or None, body.style_id, body.fabric_width_in))


@router.get("/orders", dependencies=[tailor])
def list_orders():
    out = []
    for o in store.list_orders():
        v = order_view(o)
        out.append({k: v[k] for k in ("id", "status", "customer", "style", "created_at", "measured_at", "low_confidence", "capture_url", "stub", "carried_from")}
                    | {"yardage": v["yardage"]["display"] if v["yardage"] and "display" in v["yardage"] else None})
    return out


@router.get("/orders/{order_id}", dependencies=[tailor])
def get_order(order_id: int):
    return full_view(_get(order_id))


class RepeatOrder(BaseModel):
    style_id: str | None = None
    fabric_width_in: int | None = None


@router.post("/orders/{order_id}/repeat", dependencies=[tailor])
def repeat_order(order_id: int, body: RepeatOrder):
    """A new order for the same customer, starting from their latest numbers (no new photos needed)."""
    o = _get(order_id)
    src = repeat.latest_source(store.orders_for_customer(o["customer_id"]))
    if not src:
        raise HTTPException(409, "This customer has no measurements to reuse yet.")
    style = body.style_id if body.style_id is not None else o.get("style_id")
    if style and style not in pipeline.CATALOG:
        raise HTTPException(422, f"unknown style: {style}")
    width = body.fabric_width_in or o["fabric_width_in"]
    if width not in FABRIC_WIDTHS:
        raise HTTPException(422, "fabric width must be 36, 45 or 60 inches")
    new = store.create_order(o["customer_name"], o["customer_phone"], style or None, width, customer_id=o["customer_id"],
                             sheet=repeat.carry_sheet(src), height_cm=src.get("height_cm"), measured_at=src.get("measured_at"), carried_from=src["id"])
    return full_view(new)


class Patch(BaseModel):
    style_id: str | None = None
    fabric_width_in: int | None = None
    notes: str | None = Field(None, max_length=2000)
    allowances: dict[str, float | None] | None = None  # None puts an ease value back to the style's default
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
        merged = {**(o.get("allowances") or {})}
        for k, v in body.allowances.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        try:
            pipeline.calculator.Allowances(**merged).validate()
        except (TypeError, pipeline.calculator.CalcError) as e:
            raise HTTPException(422, str(e))
        fields["allowances"] = merged
    store.update_order(order_id, **fields)
    return full_view(_get(order_id))


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
    _record_tape(o, body.edits)
    return full_view(_get(order_id))


def _record_tape(o: dict, changed: dict[str, float | None]) -> None:
    """Every number the tailor types is taken as their tape value; keep it beside our raw estimate so accuracy can be tracked."""
    if (o["sheet"] or {}).get("stub") or o.get("carried_from"):
        return  # demo numbers are not estimates of anyone; carried numbers are not estimates made for this order
    by_name = {m["name"]: m for m in o["sheet"]["measurements"]}
    applied = o.get("applied") or {}
    rows: dict[str, dict | None] = {}
    for name, value in changed.items():
        m = by_name.get(name)
        if m is None:
            continue
        rows[name] = None if value is None else {"predicted_cm": m["value_cm"], "raw_cm": round(m["value_cm"] - applied.get(name, 0.0), 1),
                                                 "tape_cm": round(value, 1), "label": m["confidence_label"]}
    store.set_tape(o["id"], rows)


@router.get("/accuracy", dependencies=[tailor])
def accuracy():
    return learning.accuracy()


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
    return {"customer_first_name": o["customer_name"].split()[0], "style": style_view(o.get("style_id")), "measured": o["status"] == "measured" and not o.get("carried_from")}


@router.post("/capture/{token}/delete-request")
def customer_delete_request(token: str):
    """The customer asks for their photos to be deleted. Done immediately; the tailor keeps the measurements."""
    o = store.get_by_token(token)
    if not o:
        raise HTTPException(404, "This link is not valid.")
    return {"deleted_files": store.delete_photos(o["id"], requested_by_customer=True)}
