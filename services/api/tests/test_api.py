import io

from tests.imgs import GOOD
from fastapi.testclient import TestClient
from app import pipeline
from app.main import app
from app.contract import validate, MEASUREMENT_NAMES

client = TestClient(app)
PHOTO = ("p.jpg", io.BytesIO(GOOD), "image/jpeg")


def post(**over):
    files = {"front": ("f.jpg", io.BytesIO(GOOD), "image/jpeg"), "side": ("s.jpg", io.BytesIO(GOOD), "image/jpeg")}
    data = {"height_cm": "170", "consent": "true", **over}
    return client.post("/v1/measurements", files=files, data=data)


def test_dummy_photo_gives_fake_sheet():
    r = post()
    assert r.status_code == 200
    body = r.json()
    validate("MeasurementSheet", body)
    assert body["stub"] is True
    assert [m["name"] for m in body["measurements"]] == MEASUREMENT_NAMES


def test_no_consent_rejected():
    assert post(consent="false").status_code == 422


def test_bad_height_rejected():
    assert post(height_cm="50").status_code == 422


def test_missing_photo_rejected():
    r = client.post("/v1/measurements", data={"height_cm": "170", "consent": "true"})
    assert r.status_code == 422


def test_landing_page_links_to_dashboard_and_demo():
    r = client.get("/")
    assert r.status_code == 200 and "TailorFit" in r.text
    assert 'href="/dashboard/"' in r.text and 'href="/capture/"' in r.text
    assert client.get("/style.css").status_code == 200
    assert client.get("/health").json() == {"ok": True}


def test_capture_page_is_served_under_capture():
    r = client.get("/capture/")
    assert r.status_code == 200 and "TailorFit" in r.text and "consent-btn" in r.text
    assert client.get("/capture/app.js").status_code == 200 and client.get("/capture/logic.js").status_code == 200


def test_old_style_customer_links_redirect_to_the_capture_page():
    r = client.get("/?order=abc-123_X", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/capture/?order=abc-123_X"


def test_tilt_fields_accepted():
    assert post(front_tilt="1.5", side_tilt="2.0").status_code == 200


def photo_files(**extra):
    files = {"front": ("f.jpg", io.BytesIO(GOOD), "image/jpeg"), "fabric": ("c.jpg", io.BytesIO(GOOD), "image/jpeg")}
    files.update(extra)
    return files


def test_style_list():
    styles = client.get("/v1/styles").json()
    assert len(styles) == 13 and {"senator", "kaftan", "gown", "iro_buba", "agbada", "bubu"} <= {s["id"] for s in styles}
    assert {s["group"] for s in styles} == {"Men", "Women", "Anyone"}
    groups = [s["group"] for s in styles]
    assert groups == sorted(groups, key=["Men", "Women", "Anyone"].index)  # listed in picker order


def test_preview_needs_consent_and_exactly_one_style_source():
    assert client.post("/v1/previews", files=photo_files(), data={"consent": "false", "style_id": "gown"}).status_code == 422
    assert client.post("/v1/previews", files=photo_files(), data={"consent": "true"}).status_code == 422
    both = photo_files(inspiration=("i.jpg", io.BytesIO(GOOD), "image/jpeg"))
    assert client.post("/v1/previews", files=both, data={"consent": "true", "style_id": "gown"}).status_code == 422
    assert client.post("/v1/previews", files=photo_files(), data={"consent": "true", "style_id": "toga"}).status_code == 422


def test_preview_without_a_key_is_a_clear_503():
    r = client.post("/v1/previews", files=photo_files(), data={"consent": "true", "style_id": "gown"})
    assert r.status_code == 503 and "Meta Model API key" in r.json()["detail"]


SHEET = [{"name": n, "value_cm": v} for n, v in dict(
    bust_chest=92, waist=76, hip=98, neck=37, arm_round=29, thigh=56, shoulder_width=42,
    sleeve_length=60, top_length=70, trouser_length=102, inseam=78, back_length=41).items()]


def test_yardage_for_a_style():
    r = client.post("/v1/yardage", json={"style_id": "gown", "fabric_width_in": 45, "measurements": SHEET})
    assert r.status_code == 200
    body = r.json()
    assert body["yards"] > 0 and body["display"].endswith(("yard", "yards")) and set(body["yards_by_width"]) == {"36", "45", "60"}


def test_tailor_allowances_change_the_answer():
    base = client.post("/v1/yardage", json={"style_id": "senator", "measurements": SHEET}).json()["yards_exact"]
    more = client.post("/v1/yardage", json={"style_id": "senator", "measurements": SHEET, "allowances": {"shrink_pct": 10}}).json()
    assert more["yards_exact"] > base and more["allowances"]["shrink_pct"] == 10 and more["allowances"]["seam_in"] == 0.75


def test_yardage_errors_are_plain_422s():
    assert client.post("/v1/yardage", json={"style_id": "toga", "measurements": SHEET}).status_code == 422
    assert client.post("/v1/yardage", json={"style_id": "gown", "fabric_width_in": 50, "measurements": SHEET}).status_code == 422
    r = client.post("/v1/yardage", json={"style_id": "gown", "measurements": SHEET[:2]})
    assert r.status_code == 422 and "missing measurements" in r.json()["detail"]
    assert client.post("/v1/yardage", json={"style_id": "gown", "measurements": SHEET, "allowances": {"shrink_pct": 99}}).status_code == 422


def test_framing_endpoint_needs_the_key_in_stub_mode():
    r = client.post("/v1/framing", files={"frame": ("f.jpg", io.BytesIO(GOOD), "image/jpeg")})
    assert r.status_code == 503


def test_framing_endpoint_validates_and_returns_status(monkeypatch):
    monkeypatch.setattr(pipeline, "enabled", lambda: True)
    monkeypatch.setattr(pipeline, "framing", lambda b: {"status": "feet_cut", "height_fraction": 0.97})
    ok = client.post("/v1/framing", files={"frame": ("f.jpg", io.BytesIO(GOOD), "image/jpeg")})
    assert ok.status_code == 200 and ok.json() == {"status": "feet_cut", "height_fraction": 0.97}
    assert client.post("/v1/framing", files={"frame": ("f.jpg", io.BytesIO(b""), "image/jpeg")}).status_code == 422
    assert client.post("/v1/framing", files={"frame": ("f.jpg", io.BytesIO(b"x" * (3 * 1024 * 1024 + 1)), "image/jpeg")}).status_code == 413

    def bad(b):
        raise ValueError("unreadable image")
    monkeypatch.setattr(pipeline, "framing", bad)
    assert client.post("/v1/framing", files={"frame": ("f.jpg", io.BytesIO(b"x"), "image/jpeg")}).status_code == 422
