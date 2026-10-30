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
