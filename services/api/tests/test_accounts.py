import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import auth, store
from app.main import app
from tests.test_dashboard import env, measure, new_order  # noqa: F401  (fixture)


def signup(c, email="bisi@example.com", password="long enough pw", name="Bisi Ade", shop="Bisi Couture"):
    return c.post("/v1/auth/signup", json={"name": name, "shop_name": shop, "email": email, "password": password})


@pytest.fixture
def a(env):
    c = TestClient(app)
    assert signup(c).status_code == 200
    return c


@pytest.fixture
def b(env):
    c = TestClient(app)
    assert signup(c, email="kunle@example.com", name="Kunle O").status_code == 200
    return c


def db():
    return sqlite3.connect(store.db_path())


# ---------------- sign up and log in ----------------

def test_signup_logs_you_in_and_me_shows_the_account(env):
    c = TestClient(app)
    r = signup(c)
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    me = c.get("/v1/auth/me").json()
    assert me["logged_in"] and me["tailor"] == {"id": me["tailor"]["id"], "name": "Bisi Ade", "shop_name": "Bisi Couture",
                                                 "email": "bisi@example.com", "is_demo": False}
    assert c.get("/v1/orders").json() == []  # a new tailor starts empty


@pytest.mark.parametrize("body,code", [
    (dict(email="not-an-email"), 422), (dict(password="short"), 422), (dict(name="   "), 422)])
def test_signup_checks_its_input(env, body, code):
    assert signup(TestClient(app), **body).status_code == code


def test_one_account_per_email_whatever_the_case(env):
    assert signup(TestClient(app)).status_code == 200
    assert signup(TestClient(app), email="  BISI@Example.com ").status_code == 409


def test_signup_can_be_switched_off(env, monkeypatch):
    monkeypatch.setenv("ALLOW_SIGNUP", "0")
    assert signup(TestClient(app)).status_code == 403
    assert TestClient(app).get("/v1/auth/me").json()["signup_allowed"] is False


def test_login_ignores_email_case_and_rejects_wrong_passwords(a):
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"email": "Bisi@Example.COM", "password": "long enough pw"}).status_code == 200
    assert c.post("/v1/auth/login", json={"email": "bisi@example.com", "password": "nope nope"}).status_code == 401
    assert c.post("/v1/auth/login", json={"email": "nobody@example.com", "password": "long enough pw"}).status_code == 401


def test_too_many_wrong_passwords_lock_that_email_for_a_while(a):
    c = TestClient(app)
    for _ in range(auth.MAX_FAILS):
        c.post("/v1/auth/login", json={"email": "bisi@example.com", "password": "wrong pw!"})
    assert c.post("/v1/auth/login", json={"email": "bisi@example.com", "password": "long enough pw"}).status_code == 429


def test_passwords_and_session_tokens_are_never_stored_as_they_are(a):
    cookie = a.cookies.get(auth.COOKIE)
    con = db()
    hashes = [r[0] for r in con.execute("SELECT password_hash FROM tailors")]
    tokens = [r[0] for r in con.execute("SELECT token_hash FROM sessions")]
    con.close()
    assert hashes[0].startswith("scrypt$") and "long enough pw" not in hashes[0]
    assert cookie not in tokens and len(tokens) == 1


def test_sessions_survive_a_restart_but_not_a_logout(a):
    cookie = a.cookies.get(auth.COOKIE)
    auth.reset()  # what a restart clears
    assert a.get("/v1/orders").status_code == 200
    a.post("/v1/auth/logout")
    stolen = TestClient(app)
    stolen.cookies.set(auth.COOKIE, cookie)
    assert stolen.get("/v1/orders").status_code == 401  # the old cookie is dead on the server, not just deleted in the browser


def test_expired_sessions_are_refused(a):
    con = db()
    con.execute("UPDATE sessions SET expires_at = 1")
    con.commit()
    con.close()
    assert a.get("/v1/orders").status_code == 401


# ---------------- each tailor sees only their own customers ----------------

def test_another_tailors_orders_are_invisible_and_untouchable(a, b, monkeypatch):
    o = new_order(a)
    measure(a, o, monkeypatch=monkeypatch)
    oid = o["id"]
    assert [x["id"] for x in a.get("/v1/orders").json()] == [oid]
    assert b.get("/v1/orders").json() == []
    for method, path, body in [("get", f"/v1/orders/{oid}", None), ("patch", f"/v1/orders/{oid}", {"notes": "mine now"}),
                               ("put", f"/v1/orders/{oid}/measurements", {"edits": {"waist": 70}}), ("post", f"/v1/orders/{oid}/repeat", {}),
                               ("get", f"/v1/orders/{oid}/cutting-sheet.pdf", None), ("get", f"/v1/orders/{oid}/preview.jpg", None),
                               ("post", f"/v1/orders/{oid}/send-whatsapp", None), ("delete", f"/v1/orders/{oid}/photos", None),
                               ("delete", f"/v1/orders/{oid}", None)]:
        kw = {"json": body} if body is not None else {}
        assert getattr(b, method)(path, **kw).status_code == 404, (method, path)  # "not found", so ids can't be probed
    v = a.get(f"/v1/orders/{oid}").json()
    assert v["notes"] == "" and not any(m["edited"] for m in v["measurements"])  # nothing b tried stuck


def test_accuracy_is_learned_from_each_tailors_own_tape(a, b, monkeypatch):
    o = new_order(a)
    measure(a, o, monkeypatch=monkeypatch)
    a.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"bust_chest": 89.0}})
    assert a.get("/v1/accuracy").json()["orders"] == 1
    assert b.get("/v1/accuracy").json()["orders"] == 0


# ---------------- account settings ----------------

def test_profile_can_be_updated(a):
    r = a.patch("/v1/auth/me", json={"shop_name": "Bisi Couture, Yaba"})
    assert r.status_code == 200 and r.json()["tailor"]["shop_name"] == "Bisi Couture, Yaba"
    assert a.patch("/v1/auth/me", json={"name": "  "}).status_code == 422


def test_changing_password_logs_out_other_devices_but_not_this_one(a):
    phone = TestClient(app)
    assert phone.post("/v1/auth/login", json={"email": "bisi@example.com", "password": "long enough pw"}).status_code == 200
    assert a.post("/v1/auth/password", json={"current_password": "wrong", "new_password": "brand new pw"}).status_code == 401
    assert a.post("/v1/auth/password", json={"current_password": "long enough pw", "new_password": "short"}).status_code == 422
    assert a.post("/v1/auth/password", json={"current_password": "long enough pw", "new_password": "brand new pw"}).status_code == 200
    assert a.get("/v1/orders").status_code == 200
    assert phone.get("/v1/orders").status_code == 401
    assert TestClient(app).post("/v1/auth/login", json={"email": "bisi@example.com", "password": "brand new pw"}).status_code == 200


def test_the_demo_accounts_password_is_fixed(env):
    t = store.create_tailor("Demo", "Demo shop", "demo@example.com", auth.hash_password("demo password"), is_demo=True)
    c = TestClient(app)
    c.post("/v1/auth/login", json={"email": "demo@example.com", "password": "demo password"})
    assert c.get("/v1/auth/me").json()["tailor"]["is_demo"] is True
    assert c.post("/v1/auth/password", json={"current_password": "demo password", "new_password": "hijacked pw"}).status_code == 403
    assert t is not None


def test_customers_from_before_accounts_go_to_the_env_account(env):
    old = store.create_order("Old Customer", None, "senator")  # no owner: created before accounts existed
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"email": "ada", "password": "correct horse"}).status_code == 200
    assert [o["id"] for o in c.get("/v1/orders").json()] == [old["id"]]
    other = TestClient(app)
    signup(other)
    assert other.get("/v1/orders").json() == []


def test_demo_account_appears_with_labelled_sample_customers(env, monkeypatch):
    monkeypatch.setenv("DEMO_PASSWORD", "judges-2026")
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"email": "demo@tailorfit.app", "password": "judges-2026"}).status_code == 200
    orders = c.get("/v1/orders").json()
    assert len(orders) == 3 and all("(sample)" in o["customer"]["name"] for o in orders)
    ngozi = next(o for o in orders if o["customer"]["name"].startswith("Ngozi"))
    v = c.get(f"/v1/orders/{ngozi['id']}").json()
    assert "made up" in v["notes"] and v["tape_first"][0] == "bust_chest" and v["finished"]
    c.post("/v1/auth/login", json={"email": "demo@tailorfit.app", "password": "judges-2026"})
    assert len(c.get("/v1/orders").json()) == 3  # created once, not on every login


def test_no_demo_account_without_a_demo_password(env):
    assert TestClient(app).post("/v1/auth/login", json={"email": "demo@tailorfit.app", "password": ""}).status_code == 401
