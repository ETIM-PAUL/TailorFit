import sqlite3

from fastapi.testclient import TestClient

from app import store
from tests.test_dashboard import anon, env, measure, new_order, tailor  # noqa: F401  (fixtures)


def measured(c, monkeypatch):
    o = new_order(c)
    assert measure(c, o, monkeypatch=monkeypatch).status_code == 200
    return o["id"]


def tape(c, oid, **values):
    r = c.put(f"/v1/orders/{oid}/measurements", json={"edits": values})
    assert r.status_code == 200, r.text
    return r.json()


def test_tape_first_lists_only_low_confidence_unchecked(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)
    assert tailor.get(f"/v1/orders/{oid}").json()["tape_first"] == ["waist"]  # fake sheet: only waist is not 'high'
    assert tape(tailor, oid, waist=75.0)["tape_first"] == []  # once checked it drops off the list


def test_stub_numbers_are_never_tape_first_or_learned(tailor):
    o = new_order(tailor)
    assert measure(tailor, o).status_code == 200  # stub pipeline
    oid = o["id"]
    view = tailor.get(f"/v1/orders/{oid}").json()
    assert view["stub"] and view["tape_first"] == []
    tape(tailor, oid, bust_chest=90.0)
    assert tailor.get("/v1/accuracy").json()["measurements"] == []


def test_tape_values_feed_the_accuracy_page_and_undo_removes_them(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)
    assert tailor.get("/v1/accuracy").json() == {"orders": 0, "min_orders": 6, "measurements": []}
    tape(tailor, oid, bust_chest=89.0, waist=76.0)  # we said 92 and 76
    acc = {m["name"]: m for m in tailor.get("/v1/accuracy").json()["measurements"]}
    assert acc["bust_chest"]["mae_cm"] == 3.0 and acc["bust_chest"]["bias_cm"] == 3.0
    assert acc["waist"]["mae_cm"] == 0.0  # "tape agrees" counts as a data point
    tape(tailor, oid, bust_chest=None)
    assert [m["name"] for m in tailor.get("/v1/accuracy").json()["measurements"]] == ["waist"]


def test_accuracy_needs_login(anon):
    assert anon.get("/v1/accuracy").status_code == 401


def test_deleting_an_order_deletes_its_tape_values(tailor, monkeypatch):
    oid = measured(tailor, monkeypatch)
    tape(tailor, oid, bust_chest=89.0)
    assert tailor.delete(f"/v1/orders/{oid}").status_code == 200
    assert tailor.get("/v1/accuracy").json()["measurements"] == []


def test_tape_values_survive_a_retake(tailor, monkeypatch):
    o = new_order(tailor)
    measure(tailor, o, monkeypatch=monkeypatch)
    tape(tailor, o["id"], bust_chest=89.0)
    measure(tailor, o, monkeypatch=monkeypatch)  # customer retakes: edits cleared, history kept
    assert tailor.get(f"/v1/orders/{o['id']}").json()["measurements"][0]["edited"] is False
    assert tailor.get("/v1/accuracy").json()["measurements"][0]["n"] == 1


def test_offset_is_learned_only_after_enough_orders_and_is_not_double_counted(tailor, monkeypatch):
    # We always say bust 92 and the tape says about 89: a steady +3 bias.
    for i in range(5):
        tape(tailor, measured(tailor, monkeypatch), bust_chest=88.5 + 0.25 * i)
    nxt = measured(tailor, monkeypatch)
    assert tailor.get(f"/v1/orders/{nxt}").json()["measurements"][0]["value_cm"] == 92.0  # 5 orders: still just reporting
    assert tailor.get("/v1/accuracy").json()["measurements"][0]["offset_cm"] is None
    tape(tailor, nxt, bust_chest=89.0)  # sixth order

    after = measured(tailor, monkeypatch)
    bust = tailor.get(f"/v1/orders/{after}").json()["measurements"][0]
    assert 88.5 <= bust["original_cm"] <= 89.5 and "earlier tape values" in bust["reason"]
    assert tailor.get(f"/v1/orders/{after}").json()["measurements"][1]["original_cm"] == 76  # waist had no tape history: untouched
    # The log compares the tape with the RAW estimate (92), so the offset is not learned twice.
    tape(tailor, after, bust_chest=89.0)
    row = [r for r in store.list_tape() if r["order_id"] == after][0]
    assert row["raw_cm"] == 92.0 and row["predicted_cm"] == bust["original_cm"]


def test_typos_are_ignored_when_learning(tailor, monkeypatch):
    for i in range(7):
        tape(tailor, measured(tailor, monkeypatch), bust_chest=150.0 + i)  # 58+ cm off: a typo, not a body
    assert tailor.get("/v1/accuracy").json()["measurements"][0]["offset_cm"] is None


def test_older_database_gets_the_new_column(env):
    path = store.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE customers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, phone TEXT, created_at TEXT NOT NULL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL, capture_token TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'new', style_id TEXT, fabric_width_in INTEGER NOT NULL DEFAULT 45, height_cm REAL, sheet_json TEXT,
        edits_json TEXT NOT NULL DEFAULT '{}', allowances_json TEXT NOT NULL DEFAULT '{}', notes TEXT NOT NULL DEFAULT '',
        keep_photos INTEGER NOT NULL DEFAULT 0, has_preview INTEGER NOT NULL DEFAULT 0, deletion_requested_at TEXT, photos_deleted_at TEXT,
        created_at TEXT NOT NULL, measured_at TEXT);""")
    db.commit()
    db.close()
    assert store.create_order("Old", None, None)["applied"] == {}
