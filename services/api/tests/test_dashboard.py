import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import auth, pipeline, store
from app.main import app

SHEET_VALUES = dict(bust_chest=92, waist=76, hip=98, neck=37, arm_round=29, thigh=56, shoulder_width=42,
                    sleeve_length=60, top_length=70, trouser_length=102, inseam=78, back_length=41)
JPEG = b"\xff\xd8dummy"


def fake_sheet(blurred=True):
    s = {"request_id": "req_x", "created_at": "2026-11-02T10:00:00+00:00", "stub": False,
         "measurements": [{"name": n, "value_cm": v, "value_in": round(v / 2.54, 1), "confidence_score": 0.8,
                           "confidence_label": "high", "reason": "measured from clear masks"} for n, v in SHEET_VALUES.items()]}
    s["measurements"][1].update(confidence_label="low", confidence_score=0.3, reason="arms touching body")  # waist
    if blurred:
        s["_blurred"] = {"front": b"FRONTBLUR", "side": b"SIDEBLUR"}
    return s


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORFIT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("TAILORFIT_PHOTOS", str(tmp_path / "photos"))
    monkeypatch.setenv("TAILOR_USERNAME", "ada")
    monkeypatch.setenv("TAILOR_PASSWORD", "correct horse")
    auth.reset()
    return tmp_path


@pytest.fixture
def anon(env):
    return TestClient(app)


@pytest.fixture
def tailor(anon):
    assert anon.post("/v1/auth/login", json={"username": "ada", "password": "correct horse"}).status_code == 200
    return anon


def new_order(c, **kw):
    body = {"customer_name": "Ngozi Eze", "phone": "0803 000 0000", "style_id": "senator", **kw}
    r = c.post("/v1/orders", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def token_of(order):
    return order["capture_url"].split("=", 1)[1]


def measure(c, order, keep=False, monkeypatch=None, blurred=True):
    """Customer finishes capture. With a monkeypatch the real-pipeline path (which can keep photos) is simulated."""
    if monkeypatch:
        monkeypatch.setattr(pipeline, "enabled", lambda: True)
        monkeypatch.setattr(pipeline, "run", lambda *a, **k: fake_sheet(blurred))
    files = {"front": ("f.jpg", io.BytesIO(JPEG), "image/jpeg"), "side": ("s.jpg", io.BytesIO(JPEG), "image/jpeg")}
    return c.post("/v1/measurements", files=files, data={"height_cm": "170", "consent": "true", "order_token": token_of(order), "keep_photos": str(keep).lower()})


# ---------------- login ----------------

def test_dashboard_is_off_without_credentials(env, monkeypatch):
    monkeypatch.delenv("TAILOR_PASSWORD")
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"username": "ada", "password": "x"}).status_code == 503
    assert c.get("/v1/orders").status_code == 503
    assert c.get("/v1/auth/me").json() == {"logged_in": False, "configured": False}


def test_login_logout_and_cookie_flags(anon):
    r = anon.post("/v1/auth/login", json={"username": "ada", "password": "correct horse"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert anon.get("/v1/auth/me").json()["logged_in"] is True
    anon.post("/v1/auth/logout")
    assert anon.get("/v1/auth/me").json()["logged_in"] is False
    assert anon.get("/v1/orders").status_code == 401


def test_wrong_password_and_lockout(anon):
    for _ in range(5):
        assert anon.post("/v1/auth/login", json={"username": "ada", "password": "nope"}).status_code == 401
    assert anon.post("/v1/auth/login", json={"username": "ada", "password": "correct horse"}).status_code == 429


@pytest.mark.parametrize("method,path", [
    ("get", "/v1/orders"), ("post", "/v1/orders"), ("get", "/v1/orders/1"), ("patch", "/v1/orders/1"),
    ("put", "/v1/orders/1/measurements"), ("get", "/v1/orders/1/preview.jpg"), ("get", "/v1/orders/1/cutting-sheet.pdf"),
    ("delete", "/v1/orders/1/photos"), ("delete", "/v1/orders/1")])
def test_every_tailor_endpoint_needs_login(anon, method, path):
    assert getattr(anon, method)(path).status_code == 401


# ---------------- orders and the customer's link ----------------

def test_create_and_list_orders(tailor):
    o = new_order(tailor)
    assert o["status"] == "new" and o["style"]["name"] == "Senator" and o["capture_url"].startswith("/capture/?order=")
    listing = tailor.get("/v1/orders").json()
    assert [x["id"] for x in listing] == [o["id"]] and listing[0]["customer"]["name"] == "Ngozi Eze"


def test_order_validation(tailor):
    assert tailor.post("/v1/orders", json={"customer_name": "", "style_id": "gown"}).status_code == 422
    assert tailor.post("/v1/orders", json={"customer_name": "A", "style_id": "toga"}).status_code == 422
    assert tailor.post("/v1/orders", json={"customer_name": "A", "fabric_width_in": 50}).status_code == 422


def test_capture_link_shows_only_first_name_and_style(tailor, anon):
    o = new_order(tailor, customer_name="Ngozi Eze")
    anon.cookies.clear()
    info = anon.get(f"/v1/capture/{token_of(o)}").json()
    assert info == {"customer_first_name": "Ngozi", "style": {"id": "senator", "name": "Senator"}, "measured": False}
    assert anon.get("/v1/capture/not-a-real-token").status_code == 404


def test_upload_attaches_to_order_and_unknown_link_is_refused(tailor, anon):
    o = new_order(tailor)
    assert measure(anon, {"capture_url": "/?order=bogus"}).status_code == 404
    assert measure(anon, o).status_code == 200
    d = tailor.get(f"/v1/orders/{o['id']}").json()
    assert d["status"] == "measured" and len(d["measurements"]) == 12 and d["height_cm"] == 170 and d["yardage"]["yards"] > 0


def test_stub_mode_never_keeps_photos(tailor, anon):
    o = new_order(tailor)
    r = measure(anon, o, keep=True)  # no real pipeline, so nothing is face-blurred
    assert r.headers["x-photos-kept"] == "false" and not tailor.get(f"/v1/orders/{o['id']}").json()["photos_kept"]


# ---------------- edits beside the original ----------------

def test_edits_are_saved_beside_the_original(tailor, anon):
    o = new_order(tailor); measure(anon, o)
    r = tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"waist": 80.5}})
    waist = next(m for m in r.json()["measurements"] if m["name"] == "waist")
    assert waist["value_cm"] == 80.5 and waist["original_cm"] == 76 and waist["edited"] is True
    assert waist["value_in"] == pytest.approx(31.7, abs=0.05)
    hip = next(m for m in r.json()["measurements"] if m["name"] == "hip")
    assert hip["edited"] is False and hip["value_cm"] == hip["original_cm"]
    # the stored sheet itself is untouched
    assert store.get_order(o["id"])["sheet"]["measurements"][1]["value_cm"] == 76


def test_edit_changes_yardage_and_clears_low_confidence_count(tailor, anon, monkeypatch):
    o = new_order(tailor, style_id="gown"); measure(anon, o, monkeypatch=monkeypatch)
    before = tailor.get(f"/v1/orders/{o['id']}").json()
    after = tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"back_length": 60, "trouser_length": 140, "waist": 76}}).json()
    assert after["yardage"]["yards_exact"] > before["yardage"]["yards_exact"]
    assert before["low_confidence"] == 1 and after["low_confidence"] == 0  # the tailor checked the waist


def test_edit_can_be_undone_and_is_validated(tailor, anon):
    o = new_order(tailor); measure(anon, o)
    tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"hip": 110}})
    back = tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"hip": None}}).json()
    assert next(m for m in back["measurements"] if m["name"] == "hip")["edited"] is False
    assert tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"elbow": 30}}).status_code == 422
    assert tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"hip": 4}}).status_code == 422
    assert tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"hip": 400}}).status_code == 422


def test_cannot_edit_before_the_customer_sends_photos(tailor):
    o = new_order(tailor)
    assert tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"hip": 100}}).status_code == 409


def test_retake_replaces_the_sheet_and_clears_edits(tailor, anon):
    o = new_order(tailor); measure(anon, o)
    tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"hip": 110}})
    measure(anon, o)
    assert not any(m["edited"] for m in tailor.get(f"/v1/orders/{o['id']}").json()["measurements"])


# ---------------- style, fabric, allowances ----------------

def test_patch_style_width_allowances_notes(tailor, anon):
    o = new_order(tailor, style_id=None); measure(anon, o)
    assert tailor.get(f"/v1/orders/{o['id']}").json()["yardage"] is None
    d = tailor.patch(f"/v1/orders/{o['id']}", json={"style_id": "kaftan", "fabric_width_in": 60, "notes": "Wants wide sleeves"}).json()
    assert d["style"]["id"] == "kaftan" and d["yardage"]["fabric_width_in"] == 60 and d["notes"] == "Wants wide sleeves"
    more = tailor.patch(f"/v1/orders/{o['id']}", json={"allowances": {"shrink_pct": 12}}).json()
    assert more["yardage"]["yards_exact"] > d["yardage"]["yards_exact"] and more["allowances"]["shrink_pct"] == 12
    assert more["allowances"]["seam_in"] == 0.75  # untouched settings keep their defaults


@pytest.mark.parametrize("body", [{"style_id": "toga"}, {"fabric_width_in": 50}, {"allowances": {"shrink_pct": 99}}, {"allowances": {"nonsense": 1}}])
def test_patch_validation(tailor, body):
    o = new_order(tailor)
    assert tailor.patch(f"/v1/orders/{o['id']}", json=body).status_code == 422


# ---------------- cutting sheet PDF ----------------

def pdf_text(resp):
    r = PdfReader(io.BytesIO(resp.content))
    return "\n".join(p.extract_text() for p in r.pages), r


def test_cutting_sheet_pdf_has_the_essentials(tailor, anon, monkeypatch):
    o = new_order(tailor); measure(anon, o, monkeypatch=monkeypatch)
    tailor.put(f"/v1/orders/{o['id']}/measurements", json={"edits": {"hip": 104}})
    tailor.patch(f"/v1/orders/{o['id']}", json={"notes": "Fitted sleeves please"})
    resp = tailor.get(f"/v1/orders/{o['id']}/cutting-sheet.pdf")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf" and resp.content[:4] == b"%PDF"
    text, _ = pdf_text(resp)
    for needle in ("Ngozi Eze", "Senator", "Hip", "104.0", "Edited by tailor", "was 98.0 cm", "Waist", "low", "arms touching body",
                   "yards", "Fitted sleeves please", "Confirm before cutting"):
        assert needle in text, needle
    assert "<b>" not in text and "&amp;" not in text  # our own formatting is applied, not printed


def test_cutting_sheet_includes_the_preview_image(tailor, anon):
    from PIL import Image
    o = new_order(tailor); measure(anon, o)
    b = io.BytesIO(); Image.new("RGB", (300, 450), (30, 90, 160)).save(b, "JPEG")
    store.save_file(o["id"], "preview.jpg", b.getvalue()); store.set_preview_flag(o["id"], True)
    assert tailor.get(f"/v1/orders/{o['id']}/preview.jpg").content == b.getvalue()
    text, reader = pdf_text(tailor.get(f"/v1/orders/{o['id']}/cutting-sheet.pdf"))
    assert "Preview, not the final garment" in text and sum(len(p.images) for p in reader.pages) == 1


def test_cutting_sheet_needs_a_sheet_and_handles_odd_names(tailor, anon):
    o = new_order(tailor, customer_name="Ada <b>&</b> Co")
    assert tailor.get(f"/v1/orders/{o['id']}/cutting-sheet.pdf").status_code == 409
    measure(anon, o)
    text, _ = pdf_text(tailor.get(f"/v1/orders/{o['id']}/cutting-sheet.pdf"))
    assert "Ada <b>&</b> Co" in text  # shown as typed, not interpreted as markup


def test_missing_preview_is_404(tailor):
    o = new_order(tailor)
    assert tailor.get(f"/v1/orders/{o['id']}/preview.jpg").status_code == 404


# ---------------- photo retention and deletion ----------------

def test_photos_not_kept_unless_the_customer_opts_in(tailor, anon, monkeypatch):
    o = new_order(tailor)
    r = measure(anon, o, keep=False, monkeypatch=monkeypatch)
    assert r.headers["x-photos-kept"] == "false" and not store.order_dir(o["id"]).exists()
    assert "_blurred" not in r.json()


def test_opt_in_keeps_only_the_blurred_photos(tailor, anon, monkeypatch):
    o = new_order(tailor)
    r = measure(anon, o, keep=True, monkeypatch=monkeypatch)
    assert r.headers["x-photos-kept"] == "true"
    assert sorted(p.name for p in store.order_dir(o["id"]).iterdir()) == ["front-blurred.jpg", "side-blurred.jpg"]
    assert tailor.get(f"/v1/orders/{o['id']}").json()["photos_kept"] is True


def test_customer_can_delete_their_photos_from_their_link(tailor, anon, monkeypatch):
    o = new_order(tailor)
    measure(anon, o, keep=True, monkeypatch=monkeypatch)
    store.save_file(o["id"], "preview.jpg", b"PREVIEW"); store.set_preview_flag(o["id"], True)
    customer = TestClient(app)  # a different person: no tailor login
    assert customer.post(f"/v1/capture/{token_of(o)}/delete-request").json() == {"deleted_files": 3}
    assert not store.order_dir(o["id"]).exists()
    d = tailor.get(f"/v1/orders/{o['id']}").json()
    assert d["photos_kept"] is False and d["has_preview"] is False and d["deletion_requested_at"] and len(d["measurements"]) == 12
    assert customer.post("/v1/capture/bogus/delete-request").status_code == 404


def test_tailor_can_delete_photos_and_whole_orders(tailor, anon, monkeypatch):
    o = new_order(tailor)
    measure(anon, o, keep=True, monkeypatch=monkeypatch)
    assert tailor.delete(f"/v1/orders/{o['id']}/photos").json() == {"deleted_files": 2}
    measure(anon, o, keep=True, monkeypatch=monkeypatch)
    assert tailor.delete(f"/v1/orders/{o['id']}").status_code == 200
    assert tailor.get(f"/v1/orders/{o['id']}").status_code == 404 and not store.order_dir(o["id"]).exists()
    assert tailor.delete(f"/v1/orders/{o['id']}").status_code == 404


def test_retake_without_opt_in_removes_previously_kept_photos(tailor, anon, monkeypatch):
    o = new_order(tailor)
    measure(anon, o, keep=True, monkeypatch=monkeypatch)
    measure(anon, o, keep=False, monkeypatch=monkeypatch)
    assert not store.order_dir(o["id"]).exists()


# ---------------- previews attach to the order ----------------

def test_preview_with_order_link_is_saved_for_the_tailor(tailor, anon, monkeypatch):
    o = new_order(tailor)
    monkeypatch.setattr(pipeline, "enabled", lambda: True)
    monkeypatch.setattr(pipeline, "make_preview", lambda *a: {"image_jpeg": b"JPEGDATA", "mode": "customer", "style_id": "senator",
                                                               "notes": [], "label": "Preview, not the final garment", "seconds": 1.0})
    files = {"front": ("f.jpg", io.BytesIO(JPEG), "image/jpeg"), "fabric": ("c.jpg", io.BytesIO(JPEG), "image/jpeg")}
    r = anon.post("/v1/previews", files=files, data={"consent": "true", "style_id": "senator", "order_token": token_of(o)})
    assert r.status_code == 200 and store.read_file(o["id"], "preview.jpg") == b"JPEGDATA"
    assert tailor.get(f"/v1/orders/{o['id']}").json()["has_preview"] is True
    bad = anon.post("/v1/previews", files={"front": ("f.jpg", io.BytesIO(JPEG), "image/jpeg"), "fabric": ("c.jpg", io.BytesIO(JPEG), "image/jpeg")},
                    data={"consent": "true", "style_id": "senator", "order_token": "bogus"})
    assert bad.status_code == 404
