import io
from fastapi.testclient import TestClient
from app.main import app
from app.contract import validate, MEASUREMENT_NAMES

client = TestClient(app)
PHOTO = ("p.jpg", io.BytesIO(b"\xff\xd8dummy"), "image/jpeg")


def post(**over):
    files = {"front": ("f.jpg", io.BytesIO(b"\xff\xd8dummy"), "image/jpeg"), "side": ("s.jpg", io.BytesIO(b"\xff\xd8dummy"), "image/jpeg")}
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


def test_capture_page_is_served():
    r = client.get("/")
    assert r.status_code == 200 and "TailorFit" in r.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/health").json() == {"ok": True}


def test_tilt_fields_accepted():
    assert post(front_tilt="1.5", side_tilt="2.0").status_code == 200


def photo_files(**extra):
    files = {"front": ("f.jpg", io.BytesIO(b"\xff\xd8dummy"), "image/jpeg"), "fabric": ("c.jpg", io.BytesIO(b"\xff\xd8dummy"), "image/jpeg")}
    files.update(extra)
    return files


def test_style_list():
    ids = [s["id"] for s in client.get("/v1/styles").json()]
    assert ids == ["senator", "kaftan", "gown", "iro_buba"]


def test_preview_needs_consent_and_exactly_one_style_source():
    assert client.post("/v1/previews", files=photo_files(), data={"consent": "false", "style_id": "gown"}).status_code == 422
    assert client.post("/v1/previews", files=photo_files(), data={"consent": "true"}).status_code == 422
    both = photo_files(inspiration=("i.jpg", io.BytesIO(b"\xff\xd8x"), "image/jpeg"))
    assert client.post("/v1/previews", files=both, data={"consent": "true", "style_id": "gown"}).status_code == 422
    assert client.post("/v1/previews", files=photo_files(), data={"consent": "true", "style_id": "toga"}).status_code == 422


def test_preview_without_a_key_is_a_clear_503():
    r = client.post("/v1/previews", files=photo_files(), data={"consent": "true", "style_id": "gown"})
    assert r.status_code == 503 and "Meta Model API key" in r.json()["detail"]
