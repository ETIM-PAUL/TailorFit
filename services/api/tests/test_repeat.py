import io
import sqlite3
from datetime import datetime, timedelta, timezone

from app import pipeline, store
from tests.imgs import GOOD
from tests.test_dashboard import anon, env, fake_sheet, measure, new_order, token_of, tailor  # noqa: F401  (fixtures)


def measured(c, monkeypatch, **overrides):
    """A new customer who has sent photos; `overrides` change the numbers our fake engine returns."""
    o = new_order(c)
    send_photos(c, o, monkeypatch, **overrides)
    return o


def send_photos(c, order, monkeypatch, **overrides):
    def run(*a, **k):
        s = fake_sheet(False)
        for m in s["measurements"]:
            if m["name"] in overrides:
                m["value_cm"] = overrides[m["name"]]
        return s
    monkeypatch.setattr(pipeline, "enabled", lambda: True)
    monkeypatch.setattr(pipeline, "run", run)
    files = {"front": ("f.jpg", io.BytesIO(GOOD), "image/jpeg"), "side": ("s.jpg", io.BytesIO(GOOD), "image/jpeg")}
    r = c.post("/v1/measurements", files=files, data={"height_cm": "170", "consent": "true", "order_token": token_of(order)})
    assert r.status_code == 200, r.text


def repeat(c, oid, **body):
    return c.post(f"/v1/orders/{oid}/repeat", json=body)


def by_name(view):
    return {m["name"]: m for m in view["measurements"]}


def backdate(order_id, days):
    db = sqlite3.connect(store.db_path())
    db.execute("UPDATE orders SET measured_at = ? WHERE id = ?", ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds"), order_id))
    db.commit()
    db.close()


def test_repeat_order_starts_measured_with_the_latest_numbers(tailor, monkeypatch):
    o = measured(tailor, monkeypatch)
    tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"waist": 78.0}})  # the tailor's tape said 78
    r = repeat(tailor, o["id"], style_id="kaftan")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["id"] != o["id"] and v["status"] == "measured" and v["style"]["id"] == "kaftan"
    assert v["customer"]["id"] == tailor.get(f"/v1/orders/{o['id']}").json()["customer"]["id"] and v["order_count"] == 2
    assert v["carried_from"]["order_id"] == o["id"]
    m = by_name(v)
    assert m["waist"]["original_cm"] == 78.0 and m["waist"]["confidence_label"] == "high" and "checked with a tape" in m["waist"]["reason"]
    assert m["bust_chest"]["original_cm"] == 92.0 and "carried from" in m["bust_chest"]["reason"]
    assert v["yardage"] and "display" in v["yardage"]  # the whole point: a repeat order can be priced straight away


def test_repeat_needs_numbers_to_reuse(tailor):
    o = new_order(tailor)
    assert repeat(tailor, o["id"]).status_code == 409  # waiting for photos
    measure(tailor, o)  # stub numbers are demo values, never reused
    assert repeat(tailor, o["id"]).status_code == 409


def test_repeat_requires_login_and_valid_choices(anon, tailor, monkeypatch):
    o = measured(tailor, monkeypatch)
    assert repeat(tailor, o["id"], style_id="nope").status_code == 422
    assert repeat(tailor, o["id"], fabric_width_in=50).status_code == 422
    assert repeat(tailor, 999).status_code == 404
    tailor.post("/v1/auth/logout")
    assert repeat(anon, o["id"]).status_code == 401


def test_carried_numbers_are_not_learned_from(tailor, monkeypatch):
    o = measured(tailor, monkeypatch)
    new = repeat(tailor, o["id"]).json()
    assert new["tape_first"] == []
    tailor.put(f"/v1/orders/{new['id']}/measurements", json={"edits": {"waist": 80.0}})
    assert tailor.get("/v1/accuracy").json()["measurements"] == []


def test_new_photos_replace_the_carried_numbers_and_show_what_changed(tailor, monkeypatch):
    o = measured(tailor, monkeypatch)  # waist 76 (an estimate)
    new = repeat(tailor, o["id"]).json()
    assert tailor.get(f"/v1/capture/{token_of_view(new)}").json()["measured"] is False  # their link still asks for photos
    send_photos(tailor, {"capture_url": new["capture_url"]}, monkeypatch, waist=88.0, hip=99.0)
    v = tailor.get(f"/v1/orders/{new['id']}").json()
    assert v["carried_from"] is None and by_name(v)["waist"]["original_cm"] == 88.0
    changed = {i["name"]: i for i in v["changes"]["items"]}
    assert changed["waist"]["delta_cm"] == 12.0 and changed["waist"]["previous_cm"] == 76.0
    assert "hip" not in changed  # +1 cm between two estimates is inside the usual error, so it is not reported


def token_of_view(view):
    return view["capture_url"].split("=", 1)[1]


def test_small_changes_count_when_both_numbers_were_taped(tailor, monkeypatch):
    o = measured(tailor, monkeypatch)
    tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"waist": 76.0, "hip": 98.0}})
    new = repeat(tailor, o["id"]).json()
    send_photos(tailor, {"capture_url": new["capture_url"]}, monkeypatch, waist=80.0)
    tailor.put(f"/v1/orders/{new['id']}/measurements", json={"edits": {"waist": 78.0}})  # taped again: +2 cm
    changed = {i["name"]: i for i in tailor.get(f"/v1/orders/{new['id']}").json()["changes"]["items"]}
    assert changed["waist"]["delta_cm"] == 2.0 and changed["waist"]["both_checked"] is True


def test_old_numbers_are_marked_as_possibly_out_of_date(tailor, monkeypatch):
    o = measured(tailor, monkeypatch)
    tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"waist": 78.0}})
    backdate(o["id"], 260)
    m = by_name(repeat(tailor, o["id"]).json())
    assert m["waist"]["confidence_label"] == "medium" and "body may have changed" in m["waist"]["reason"]  # even a taped number
    assert m["bust_chest"]["confidence_label"] == "medium"


def test_first_order_has_no_history(tailor, monkeypatch):
    o = measured(tailor, monkeypatch)
    v = tailor.get(f"/v1/orders/{o['id']}").json()
    assert v["order_count"] == 1 and v["changes"]["items"] == [] and v["can_repeat"] is True


def test_deleting_one_order_keeps_the_customers_other_orders(tailor, monkeypatch):
    o = measured(tailor, monkeypatch)
    new = repeat(tailor, o["id"]).json()
    assert tailor.delete(f"/v1/orders/{new['id']}").status_code == 200
    assert tailor.get(f"/v1/orders/{o['id']}").status_code == 200  # the first order survives
    assert tailor.delete(f"/v1/orders/{o['id']}").status_code == 200  # last one: the customer is forgotten too
    db = sqlite3.connect(store.db_path())
    assert db.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0
    db.close()
