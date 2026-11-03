"""A demo tailor account for judges and walk-throughs, with sample customers.

Created on the first login attempt when DEMO_PASSWORD is set (DEMO_EMAIL defaults to demo@tailorfit.app), so a fresh
deployment always has it. The sample numbers are made up and every sample order says so in its notes. The account's
password can't be changed from the app (see dashboard_api.change_password).
"""
import os
from datetime import datetime, timedelta, timezone

from . import store

SAMPLE_NOTE = "Sample customer for the demo. These numbers are made up, not measured from a real person."

# name, value_cm, confidence_score: shaped like a real sheet, with chest and waist the uncertain ones
_BASE = [("bust_chest", 96.0, 0.38), ("waist", 82.0, 0.5), ("hip", 101.0, 0.55), ("neck", 38.5, 0.45), ("arm_round", 31.0, 0.62),
         ("thigh", 57.5, 0.52), ("shoulder_width", 44.0, 0.55), ("sleeve_length", 61.0, 0.6), ("top_length", 71.0, 0.62),
         ("trouser_length", 103.0, 0.64), ("inseam", 79.0, 0.6), ("back_length", 42.0, 0.6)]
_REASONS = {"bust_chest": "chest is our least accurate number from photos", "waist": "loose clothing at the waist"}


def _label(score: float) -> str:
    return "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"


def sample_sheet(shift_cm: float = 0.0, days_ago: int = 0) -> dict:
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
    items = []
    for name, cm, score in _BASE:
        v = round(cm + (shift_cm if name in ("bust_chest", "waist", "hip", "thigh", "arm_round") else 0), 1)
        items.append({"name": name, "value_cm": v, "value_in": round(v / 2.54, 1), "confidence_score": score,
                      "confidence_label": _label(score), "reason": _REASONS.get(name, "measured from clear masks")})
    return {"request_id": "sample", "created_at": created, "stub": False, "measurements": items}


def ensure_demo_account(hash_password) -> None:
    pw = os.environ.get("DEMO_PASSWORD", "")
    if not pw:
        return
    email = (os.environ.get("DEMO_EMAIL") or "demo@tailorfit.app").strip().lower()
    if store.get_tailor_by_email(email):
        return
    t = store.create_tailor("Demo Tailor", "Demo Tailoring, Lagos", email, hash_password(pw), is_demo=True)
    if t is None:
        return
    tid = t["id"]
    # A measured customer with numbers to check, a returning customer, and one still waiting for photos.
    ngozi = store.create_order("Ngozi Eze (sample)", "0803 000 0001", "senator", 45, tailor_id=tid)
    store.attach_sheet(ngozi["capture_token"], sample_sheet(), 172, False)
    store.update_order(ngozi["id"], notes=SAMPLE_NOTE)
    funmi = store.create_order("Funmi Adeyemi (sample)", "0803 000 0002", "iro_buba", 45, tailor_id=tid)
    store.attach_sheet(funmi["capture_token"], sample_sheet(-8.0), 160, False)
    store.update_order(funmi["id"], notes=SAMPLE_NOTE)
    chidi = store.create_order("Chidi Okafor (sample)", "0803 000 0003", "kaftan", 60, tailor_id=tid)
    store.update_order(chidi["id"], notes=SAMPLE_NOTE)
