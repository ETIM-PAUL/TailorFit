"""Returning customers: reuse an earlier order's numbers, and show what has changed since.

A repeat order starts out measured, with the customer's latest numbers (the tailor's tape values where there are
any). Nothing is re-estimated, so no accuracy is learned from it (see dashboard_api._record_tape). If the customer
sends new photos the sheet is replaced like any other retake, and `changes` then compares it with the order before.
"""
from datetime import datetime, timezone

from . import pipeline

STALE_DAYS = 180          # numbers older than this may no longer fit the body
CHECKED_CHANGE_CM = 1.5   # a change this big between two tape-checked numbers is real
UNBENCHMARKED_ERROR_CM = 4.0


def _age_days(iso: str | None) -> int | None:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).days if iso else None
    except ValueError:
        return None


def _date(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y").lstrip("0") if iso else "an earlier order"
    except ValueError:
        return "an earlier order"


def finals(o: dict) -> dict[str, dict]:
    """The numbers the tailor would cut from: tape/edited values over our estimates. name -> {cm, checked, score, label, reason}."""
    edits = o.get("edits") or {}
    out = {}
    for m in (o.get("sheet") or {}).get("measurements", []):
        out[m["name"]] = {"cm": edits.get(m["name"], m["value_cm"]), "checked": m["name"] in edits or bool(m.get("tape_checked")),
                          "score": m["confidence_score"], "label": m["confidence_label"], "reason": m["reason"]}
    return out


def can_carry(o: dict) -> bool:
    sheet = o.get("sheet")
    return bool(sheet) and not sheet.get("stub")


def carry_sheet(src: dict) -> dict:
    """A sheet for a new order, holding the source order's final numbers."""
    when, age = _date(src.get("measured_at")), _age_days(src.get("measured_at"))
    stale = age is not None and age >= STALE_DAYS
    items = []
    for name, f in finals(src).items():
        score, label = (0.9, "high") if f["checked"] else (f["score"], f["label"])
        reason = f"checked with a tape ({when})" if f["checked"] else f"{f['reason']}; carried from {when}"
        if stale:
            score = min(score, 0.6)
            label = "medium" if label == "high" else label
            reason += f"; measured {age // 30} months ago, the body may have changed"
        items.append({"name": name, "value_cm": round(f["cm"], 1), "value_in": round(f["cm"] / 2.54, 1), "confidence_score": score,
                      "confidence_label": label, "reason": reason, "tape_checked": f["checked"]})
    return {"request_id": f"carried_{src['id']}", "created_at": (src.get("sheet") or {}).get("created_at"), "stub": False, "measurements": items}


def latest_source(orders: list[dict]) -> dict | None:
    """The customer's most recent order that has real numbers."""
    return next((o for o in sorted(orders, key=lambda o: o["id"], reverse=True) if can_carry(o)), None)


def changes(current: dict, orders: list[dict]) -> dict:
    """How this order's numbers differ from the customer's previous order.

    Estimates are only good to a few cm, so a change is only reported when it is bigger than the usual error for that
    measurement, or bigger than 1.5 cm when both numbers were checked with a tape.
    """
    prev = latest_source([o for o in orders if o["id"] < current["id"]])
    if not prev or not can_carry(current):
        return {"previous_order_id": None, "previous_date": None, "items": []}
    typical = pipeline.measure2d.TYPICAL_ERROR_CM
    now, before = finals(current), finals(prev)
    items = []
    for name, f in now.items():
        b = before.get(name)
        if not b:
            continue
        delta = f["cm"] - b["cm"]
        threshold = CHECKED_CHANGE_CM if f["checked"] and b["checked"] else max(3.0, typical.get(name, UNBENCHMARKED_ERROR_CM))
        if abs(delta) >= threshold:
            items.append({"name": name, "previous_cm": round(b["cm"], 1), "current_cm": round(f["cm"], 1), "delta_cm": round(delta, 1),
                          "both_checked": f["checked"] and b["checked"]})
    items.sort(key=lambda i: -abs(i["delta_cm"]))
    return {"previous_order_id": prev["id"], "previous_date": prev.get("measured_at"), "items": items}
