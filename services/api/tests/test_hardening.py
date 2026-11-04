import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import auth, images, pipeline, security, store
from app.main import app
from tests.imgs import GOOD, jpeg

client = TestClient(app)


def post_photos(front, side=GOOD, c=client, **data):
    files = {"front": ("f.jpg", io.BytesIO(front), "image/jpeg"), "side": ("s.jpg", io.BytesIO(side), "image/jpeg")}
    return c.post("/v1/measurements", files=files, data={"height_cm": "170", "consent": "true", **data})


# ---------------- bad files ----------------

@pytest.mark.parametrize("bad,why", [
    (b"this is not an image", "couldn't read"), (b"", "empty"), (b"\xff\xd8\xff\xe0" + b"0" * 50, "couldn't read"),
    (jpeg()[:200], "couldn't read"),                         # a JPEG cut short
    (jpeg(60, 60), "too small"),
])
def test_unusable_photos_get_a_plain_message_not_a_crash(bad, why):
    r = post_photos(bad)
    assert r.status_code == 422 and why in r.json()["detail"], r.text
    assert "front photo" in r.json()["detail"]


def test_second_photo_is_checked_too():
    r = post_photos(GOOD, b"nope")
    assert r.status_code == 422 and "side photo" in r.json()["detail"]


def test_absurdly_large_images_are_refused_before_decoding():
    big = io.BytesIO()
    Image.new("L", (9000, 9000), 255).save(big, "PNG")   # 81 megapixels, but tiny on disk
    assert len(big.getvalue()) < 500_000
    r = post_photos(big.getvalue())
    assert r.status_code == 422 and "too large" in r.json()["detail"]


def test_png_webp_and_other_colour_modes_are_accepted():
    for mode, fmt in (("RGB", "PNG"), ("RGBA", "PNG"), ("L", "PNG"), ("P", "PNG"), ("CMYK", "JPEG"), ("RGB", "WEBP"), ("L", "JPEG")):
        b = io.BytesIO()
        Image.new(mode, (300, 400)).save(b, fmt)
        out = images.normalize(b.getvalue())
        assert Image.open(io.BytesIO(out)).format == "JPEG", (mode, fmt)


@pytest.mark.parametrize("fmt", ["TIFF", "GIF", "BMP", "ICO", "PPM"])
def test_unusual_image_formats_are_never_decoded(fmt):
    """Most of Pillow's published vulnerabilities live in rare formats, so only JPEG, PNG and WebP get through."""
    b = io.BytesIO()
    Image.new("RGB", (300, 400)).save(b, fmt)
    r = post_photos(b.getvalue())
    assert r.status_code == 422 and "JPEG or PNG" in r.json()["detail"]


def test_a_phone_jpeg_with_multi_picture_data_is_still_accepted():
    """Some phones write JPEGs that Pillow would label MPO; they must keep working."""
    b = io.BytesIO()
    Image.new("RGB", (300, 400), (50, 90, 130)).save(b, "MPO")
    assert Image.open(io.BytesIO(images.normalize(b.getvalue()))).size == (300, 400)


def test_previews_and_frames_check_images_too(monkeypatch):
    monkeypatch.setattr(pipeline, "enabled", lambda: True)
    files = {"front": ("f.jpg", io.BytesIO(b"junk"), "image/jpeg"), "fabric": ("c.jpg", io.BytesIO(GOOD), "image/jpeg")}
    r = client.post("/v1/previews", files=files, data={"consent": "true", "style_id": "gown"})
    assert r.status_code == 422 and "front photo" in r.json()["detail"]
    r = client.post("/v1/framing", files={"frame": ("f.jpg", io.BytesIO(b"junk"), "image/jpeg")})
    assert r.status_code == 422


def test_missing_fields_get_a_plain_sentence():
    r = client.post("/v1/measurements", files={"front": ("f.jpg", io.BytesIO(GOOD), "image/jpeg"), "side": ("s.jpg", io.BytesIO(GOOD), "image/jpeg")},
                    data={"consent": "true"})
    assert r.status_code == 422 and r.json() == {"detail": "Please check your height."}
    r = client.post("/v1/measurements", data={"height_cm": "170", "consent": "true"})
    assert r.json()["detail"] == "Please check the front photo, the side photo."


# ---------------- rotation and metadata ----------------

def exif_jpeg(orientation=6, gps=True, size=(300, 200)):
    ex = Image.Exif()
    ex[274] = orientation
    ex[271] = "SecretPhoneMaker"
    if gps:
        ex[0x8825] = {1: "N", 2: (6.0, 27.0, 0.0), 3: "E", 4: (3.0, 23.0, 0.0)}   # a GPS location in Lagos
    b = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(b, "JPEG", exif=ex)
    return b.getvalue()


def test_sideways_phone_photos_are_turned_upright():
    out = Image.open(io.BytesIO(images.normalize(exif_jpeg(orientation=6))))
    assert out.size == (200, 300)  # stored 300x200 with a "rotate 90" tag


def test_location_and_device_details_are_stripped():
    original = exif_jpeg()
    assert b"SecretPhoneMaker" in original
    cleaned = images.normalize(original)
    assert b"SecretPhoneMaker" not in cleaned and not dict(Image.open(io.BytesIO(cleaned)).getexif())
    assert not any(b in cleaned for b in (b"Exif", b"GPS"))


def test_large_photos_are_shrunk():
    out = Image.open(io.BytesIO(images.normalize(jpeg(4000, 3000))))
    assert max(out.size) == images.MAX_SIDE


def test_pipeline_receives_the_cleaned_photo(monkeypatch):
    seen = {}
    monkeypatch.setattr(pipeline, "enabled", lambda: True)

    def run(request_id, locale, height, front, side, *a):
        seen["front"] = front
        from app import stubs
        return stubs.build_sheet(request_id, locale, height)
    monkeypatch.setattr(pipeline, "run", run)
    assert post_photos(exif_jpeg()).status_code == 200
    got = Image.open(io.BytesIO(seen["front"]))
    assert got.size == (200, 300) and not dict(got.getexif())


# ---------------- headers ----------------

@pytest.mark.parametrize("path", ["/", "/capture/", "/dashboard/", "/health", "/v1/styles"])
def test_security_headers_everywhere(path):
    h = client.get(path).headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer"
    assert "default-src 'self'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
    assert "camera=(self)" in h["permissions-policy"]


def test_api_answers_are_never_cached_and_hsts_only_over_https():
    assert client.get("/v1/styles").headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in client.get("/health").headers
    assert "max-age" in client.get("/health", headers={"X-Forwarded-Proto": "https"}).headers["strict-transport-security"]


def test_csp_blocks_outside_scripts_but_allows_what_the_pages_use():
    csp = client.get("/").headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-eval" not in csp and "script-src 'unsafe-inline'" not in csp
    assert "img-src 'self' data: blob:" in csp  # the preview is shown from a data: address, kept photos from blob:
    assert "<script>" not in client.get("/capture/").text and "<script>" not in client.get("/dashboard/").text.replace('<script src="app.js"></script>', "")


# ---------------- cross-site requests ----------------

@pytest.fixture
def tailor(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILOR_USERNAME", "ada"); monkeypatch.setenv("TAILOR_PASSWORD", "pw-for-tests")
    monkeypatch.setenv("TAILORFIT_DB", str(tmp_path / "t.db")); monkeypatch.setenv("TAILORFIT_PHOTOS", str(tmp_path / "p"))
    auth.reset()
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"email": "ada", "password": "pw-for-tests"}).status_code == 200
    return c


def test_requests_from_other_websites_are_refused(tailor):
    evil = {"Origin": "https://evil.example"}
    assert tailor.post("/v1/orders", json={"customer_name": "X"}, headers=evil).status_code == 403
    assert tailor.post("/v1/auth/logout", headers=evil).status_code == 403
    assert tailor.post("/v1/auth/login", json={"email": "a", "password": "b"}, headers=evil).status_code == 403
    assert tailor.get("/v1/orders", headers=evil).status_code == 200          # reading is not state-changing, and SameSite covers cookies


def test_own_site_and_non_browser_requests_still_work(tailor, monkeypatch):
    assert tailor.post("/v1/orders", json={"customer_name": "A"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert tailor.post("/v1/orders", json={"customer_name": "B"}).status_code == 200   # no Origin: curl, tests
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://tailor.example.com")
    assert tailor.post("/v1/orders", json={"customer_name": "C"}, headers={"Origin": "https://tailor.example.com"}).status_code == 200


def test_customer_endpoints_are_not_blocked_by_the_origin_check():
    r = client.post("/v1/capture/nope/delete-request", headers={"Origin": "https://anything.example"})
    assert r.status_code == 404  # reached the handler (bad token), not refused as cross-site


# ---------------- rate limits ----------------

def test_the_16th_measurement_in_a_minute_is_refused():
    codes = [post_photos(GOOD).status_code for _ in range(16)]
    assert codes[:15] == [200] * 15 and codes[15] == 429
    r = post_photos(GOOD)
    assert r.status_code == 429 and r.headers["retry-after"] == "60" and "wait a minute" in r.json()["detail"]


def test_spoofed_forwarding_headers_do_not_dodge_the_limit():
    for i in range(15):
        post_photos(GOOD)
    assert post_photos(GOOD, c=client).status_code == 429
    for i in range(3):  # a direct client claiming to be somebody else is still counted as itself
        r = client.post("/v1/measurements", files={"front": ("f.jpg", io.BytesIO(GOOD), "image/jpeg"), "side": ("s.jpg", io.BytesIO(GOOD), "image/jpeg")},
                        data={"height_cm": "170", "consent": "true"}, headers={"X-Forwarded-For": f"10.0.0.{i}"})
        assert r.status_code == 429


def test_behind_our_own_proxy_each_visitor_gets_their_own_allowance():
    proxy = TestClient(app, client=("127.0.0.1", 50000))
    for i in range(15):
        assert post_photos(GOOD, c=proxy).status_code == 200  # all from one visitor...
    # (same visitor: next one is refused) ...
    files = lambda: {"front": ("f.jpg", io.BytesIO(GOOD), "image/jpeg"), "side": ("s.jpg", io.BytesIO(GOOD), "image/jpeg")}
    data = {"height_cm": "170", "consent": "true"}
    assert proxy.post("/v1/measurements", files=files(), data=data).status_code == 429
    # ...while another visitor, as reported by the proxy, is unaffected
    assert proxy.post("/v1/measurements", files=files(), data=data, headers={"CF-Connecting-IP": "203.0.113.9"}).status_code == 200


def test_limits_can_be_switched_off_for_load_tests(monkeypatch):
    monkeypatch.setenv("DISABLE_RATE_LIMITS", "1")
    assert all(post_photos(GOOD).status_code == 200 for _ in range(20))


# ---------------- login cookie ----------------

def test_cookie_is_secure_over_https_or_when_forced(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILOR_USERNAME", "ada"); monkeypatch.setenv("TAILOR_PASSWORD", "pw-for-tests")
    body = {"email": "ada", "password": "pw-for-tests"}
    plain = TestClient(app).post("/v1/auth/login", json=body).headers["set-cookie"].lower()
    assert "httponly" in plain and "samesite=lax" in plain and "secure" not in plain.replace("samesite", "")
    auth.reset()
    tunnel = TestClient(app).post("/v1/auth/login", json=body, headers={"X-Forwarded-Proto": "https"}).headers["set-cookie"].lower()
    assert "; secure" in tunnel
    auth.reset(); monkeypatch.setenv("COOKIE_SECURE", "1")
    assert "; secure" in TestClient(app).post("/v1/auth/login", json=body).headers["set-cookie"].lower()


# ---------------- files and data ----------------

@pytest.mark.parametrize("path", ["/.env", "/capture/../../../.env", "/capture/%2e%2e/%2e%2e/.env", "/dashboard/..%2f..%2f.env",
                                  "/data/tailorfit.db", "/services/api/app/main.py", "/static/../.env"])
def test_secrets_and_source_are_not_served(path):
    r = client.get(path)
    assert r.status_code in (400, 404, 307) and b"MODEL_API_KEY" not in r.content and b"def " not in r.content[:2000]


def test_nothing_is_written_to_disk_without_opt_in(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORFIT_DB", str(tmp_path / "t.db")); monkeypatch.setenv("TAILORFIT_PHOTOS", str(tmp_path / "photos"))
    o = store.create_order("Ngozi Eze", "0803", "gown")
    r = post_photos(GOOD, order_token=o["capture_token"], keep_photos="false")
    assert r.status_code == 200 and r.headers["x-photos-kept"] == "false"
    assert not (tmp_path / "photos").exists() or not any((tmp_path / "photos").rglob("*"))


def test_pages_revalidate_so_updates_show_up_and_the_font_is_cached():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    for path in ("/", "/dashboard/", "/capture/", "/shared/base.css", "/dashboard/app.js"):
        r = c.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    font = c.get("/shared/fonts/atkinson-hyperlegible-next.woff2")
    assert font.status_code == 200 and "max-age" in font.headers["cache-control"]
    assert c.get("/health").headers["cache-control"] == "no-cache"
    assert c.get("/v1/styles").headers["cache-control"] == "no-store"


def test_behind_a_hosting_proxy_the_real_visitor_is_counted_and_cant_be_faked(monkeypatch):
    from starlette.requests import Request
    from app import security

    def req(xff, client="10.0.0.5"):
        return Request({"type": "http", "headers": [(b"x-forwarded-for", xff.encode())] if xff else [], "client": (client, 1234),
                        "method": "GET", "path": "/", "query_string": b"", "scheme": "http", "server": ("x", 80)})

    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "1")
    assert security.client_ip(req("41.58.1.2")) == "41.58.1.2"                 # what Render's proxy saw
    assert security.client_ip(req("1.2.3.4, 41.58.1.2")) == "41.58.1.2"       # a faked entry on the left is ignored
    assert security.client_ip(req("")) == "10.0.0.5"
    monkeypatch.delenv("TRUSTED_PROXY_HOPS")
    assert security.client_ip(req("41.58.1.2")) == "10.0.0.5"                 # without the setting, the header isn't trusted
