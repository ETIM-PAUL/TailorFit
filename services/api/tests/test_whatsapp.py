import hashlib
import hmac
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import auth, store, whatsapp
from app.main import app

SECRET = "app-secret-123"
JPEG = b"\xff\xd8dummy"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TAILORFIT_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("TAILORFIT_PHOTOS", str(tmp_path / "photos"))
    monkeypatch.setenv("TAILOR_USERNAME", "ada")
    monkeypatch.setenv("TAILOR_PASSWORD", "pw-for-tests")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "TOKEN")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "PHONEID")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "verify-me")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    for k in ("WHATSAPP_TEMPLATE_NAME", "WHATSAPP_TEMPLATE_VARS", "WHATSAPP_DEFAULT_COUNTRY_CODE", "WHATSAPP_API_VERSION"):
        monkeypatch.delenv(k, raising=False)
    auth.reset()


@pytest.fixture
def sent(env, monkeypatch):
    """Capture every message the app would send, without touching the network."""
    calls = []
    monkeypatch.setattr(whatsapp, "_post", lambda payload: calls.append(payload) or {})
    return calls


@pytest.fixture
def tailor(env):
    c = TestClient(app)
    assert c.post("/v1/auth/login", json={"username": "ada", "password": "pw-for-tests"}).status_code == 200
    return c


def order(phone="0803 000 0000", name="Ngozi Eze", style="senator"):
    return store.create_order(name, phone, style)


def signed(payload: dict, secret=SECRET):
    raw = json.dumps(payload).encode()
    return raw, {"X-Hub-Signature-256": "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


def message(text="Hi", sender="2348030000000", mid="wamid.1", mtype="text"):
    m = {"from": sender, "id": mid, "timestamp": "1", "type": mtype}
    if mtype == "text":
        m["text"] = {"body": text}
    return {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messaging_product": "whatsapp", "metadata": {"phone_number_id": "PHONEID"}, "messages": [m]}}]}]}


def post_hook(client, payload, **kw):
    raw, headers = signed(payload, **kw)
    return client.post("/v1/whatsapp/webhook", content=raw, headers=headers)


# ---------------- phone numbers and links ----------------

@pytest.mark.parametrize("raw,expected", [
    ("0803 000 0000", "2348030000000"), ("+234 803 000 0000", "2348030000000"), ("2348030000000", "2348030000000"),
    ("00234 803 000 0000", "2348030000000"), ("+1 (415) 555-0123", "14155550123"),
    ("", None), (None, None), ("abc", None), ("123", None), ("+1234567890123456", None)])
def test_normalize_phone(env, raw, expected):
    assert whatsapp.normalize_phone(raw) == expected


def test_default_country_code_is_configurable(env, monkeypatch):
    monkeypatch.setenv("WHATSAPP_DEFAULT_COUNTRY_CODE", "44")
    assert whatsapp.normalize_phone("07911 123456") == "447911123456"


def test_click_to_chat_url_encodes_the_message():
    url = whatsapp.click_to_chat_url("2348030000000", "Hi Ngozi, open https://x.test/?a=1&b=2")
    assert url.startswith("https://wa.me/2348030000000?text=Hi%20Ngozi") and "&b=2" not in url and "%26b%3D2" in url


def test_configured_needs_every_setting_including_the_app_secret(env, monkeypatch):
    assert whatsapp.configured()
    for name in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"):
        monkeypatch.delenv(name)
        assert not whatsapp.configured(), name
        monkeypatch.setenv(name, "x")


# ---------------- the request we send to WhatsApp ----------------

def test_request_shape_url_auth_and_body(env, monkeypatch):
    seen = {}

    def fake_post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

    monkeypatch.setattr(httpx, "post", fake_post)
    whatsapp.send_text("2348030000000", "hello")
    assert seen["url"] == "https://graph.facebook.com/v21.0/PHONEID/messages"
    assert seen["headers"]["Authorization"] == "Bearer TOKEN"
    assert seen["json"] == {"messaging_product": "whatsapp", "to": "+2348030000000", "type": "text", "text": {"preview_url": True, "body": "hello"}}


def test_api_version_is_configurable(env, monkeypatch):
    monkeypatch.setenv("WHATSAPP_API_VERSION", "v99.0")
    seen = {}
    monkeypatch.setattr(httpx, "post", lambda url, **k: seen.update(url=url) or httpx.Response(200, json={}))
    whatsapp.send_text("2348030000000", "x")
    assert "/v99.0/" in seen["url"]


def test_refusals_and_network_errors_become_readable_errors(env, monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(400, json={"error": {"message": "Re-engagement message required"}}))
    with pytest.raises(whatsapp.WhatsAppError, match="Re-engagement message required"):
        whatsapp.send_text("2348030000000", "x")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(500, text="boom"))
    with pytest.raises(whatsapp.WhatsAppError, match="500"):
        whatsapp.send_text("2348030000000", "x")

    def down(*a, **k):
        raise httpx.ConnectTimeout("slow")
    monkeypatch.setattr(httpx, "post", down)
    with pytest.raises(whatsapp.WhatsAppError, match="Could not reach"):
        whatsapp.send_text("2348030000000", "x")


def test_template_payload_carries_the_link(sent):
    whatsapp.send_template("2348030000000", "tailorfit_link", "en", "https://x.test/c")
    t = sent[0]["template"]
    assert sent[0]["type"] == "template" and t["name"] == "tailorfit_link" and t["language"] == {"code": "en"}
    assert t["components"] == [{"type": "body", "parameters": [{"type": "text", "text": "https://x.test/c"}]}]


def test_template_without_variables_sends_no_components(sent, monkeypatch):
    monkeypatch.setenv("WHATSAPP_TEMPLATE_VARS", "0")
    whatsapp.send_template("2348030000000", "hello_world", "en_US", "https://x.test/c")
    assert "components" not in sent[0]["template"]


# ---------------- the webhook handshake and signature ----------------

def test_handshake_echoes_the_raw_challenge(env):
    c = TestClient(app)
    r = c.get("/v1/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "12345"})
    assert r.status_code == 200 and r.text == "12345"  # raw, not JSON-wrapped


@pytest.mark.parametrize("params", [
    {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
    {"hub.mode": "unsubscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"},
    {"hub.mode": "subscribe", "hub.verify_token": "verify-me"},
    {}])
def test_handshake_refuses_bad_requests(env, params):
    assert TestClient(app).get("/v1/whatsapp/webhook", params=params).status_code == 403


def test_webhook_is_off_when_not_configured(env, monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET")
    c = TestClient(app)
    assert c.get("/v1/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1"}).status_code == 503
    assert c.post("/v1/whatsapp/webhook", json=message()).status_code == 503


def test_signature_check(env):
    raw, headers = signed(message())
    h = headers["X-Hub-Signature-256"]
    assert whatsapp.signature_ok(raw, h)
    assert not whatsapp.signature_ok(raw + b" ", h)               # body changed
    assert not whatsapp.signature_ok(raw, h[:-1] + ("0" if h[-1] != "0" else "1"))
    assert not whatsapp.signature_ok(raw, None) and not whatsapp.signature_ok(raw, h.replace("sha256=", "sha1="))


def test_unsigned_or_wrongly_signed_posts_are_refused_and_do_nothing(sent):
    order()
    c = TestClient(app)
    assert c.post("/v1/whatsapp/webhook", json=message()).status_code == 403
    assert post_hook(c, message(), secret="not-the-secret").status_code == 403
    assert sent == []


# ---------------- what customers get back ----------------

def test_customer_who_messages_gets_their_link(sent):
    o = order()
    r = post_hook(TestClient(app), message("Hi"))
    assert r.status_code == 200 and len(sent) == 1
    assert sent[0]["to"] == "+2348030000000" and sent[0]["type"] == "text"
    body = sent[0]["text"]["body"]
    assert f"https://example.test/capture/?order={o['capture_token']}" in body and "Hi Ngozi" in body and "senator" in body


def test_unknown_number_is_told_to_ask_the_tailor(sent):
    order()
    post_hook(TestClient(app), message(sender="2348099999999"))
    assert "couldn't find an order" in sent[0]["text"]["body"]


def test_measured_order_is_not_asked_for_photos_again_unless_retake(sent):
    o = order()
    store.attach_sheet(o["capture_token"], {"measurements": []}, 170, False)
    c = TestClient(app)
    post_hook(c, message("hello", mid="wamid.a"))
    assert "already has your measurements" in sent[0]["text"]["body"] and "capture/?order" not in sent[0]["text"]["body"]
    post_hook(c, message("RETAKE", mid="wamid.b"))
    assert f"capture/?order={o['capture_token']}" in sent[1]["text"]["body"]


def test_photo_sent_over_chat_gets_pointed_to_the_link(sent):
    o = order()
    post_hook(TestClient(app), message(mtype="image"))
    assert o["capture_token"] in sent[0]["text"]["body"]


def test_newest_waiting_order_wins_over_a_finished_one(sent):
    old = order(); store.attach_sheet(old["capture_token"], {"measurements": []}, 170, False)
    new = order(style="gown")
    post_hook(TestClient(app), message())
    assert new["capture_token"] in sent[0]["text"]["body"] and old["capture_token"] not in sent[0]["text"]["body"]


def test_redelivered_message_is_answered_once(sent):
    order()
    c = TestClient(app)
    post_hook(c, message(mid="wamid.same")); post_hook(c, message(mid="wamid.same"))
    assert len(sent) == 1


def test_no_public_url_means_no_link_and_no_crash(sent, monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL")
    order()
    assert post_hook(TestClient(app), message()).status_code == 200 and sent == []


def test_send_failure_never_breaks_the_webhook(env, monkeypatch):
    order()

    def boom(payload):
        raise whatsapp.WhatsAppError("window closed")
    monkeypatch.setattr(whatsapp, "_post", boom)
    assert post_hook(TestClient(app), message()).status_code == 200


@pytest.mark.parametrize("payload", [{}, {"entry": None}, {"entry": [{"changes": [{"value": {"statuses": [{"id": "x"}]}}]}]},
                                     {"entry": [{"changes": "nope"}]}, {"entry": [{"changes": [{"value": {"messages": [{"id": "m"}]}}]}]}])
def test_odd_payloads_are_ignored(sent, payload):
    assert post_hook(TestClient(app), payload).status_code == 200 and sent == []


def test_inbound_parser_reads_the_documented_shape():
    msgs = whatsapp.inbound_messages(message("Hello there", sender="2348030000000", mid="wamid.9"))
    assert msgs == [{"id": "wamid.9", "from": "2348030000000", "type": "text", "text": "Hello there"}]


# ---------------- the tailor's "send" button ----------------

def test_send_needs_login_and_setup(tailor, env, monkeypatch):
    o = order()
    assert TestClient(app).post(f"/v1/orders/{o['id']}/send-whatsapp").status_code == 401
    monkeypatch.delenv("WHATSAPP_APP_SECRET")
    assert tailor.post(f"/v1/orders/{o['id']}/send-whatsapp").status_code == 503


def test_send_text_invite(tailor, sent):
    o = order()
    r = tailor.post(f"/v1/orders/{o['id']}/send-whatsapp")
    assert r.json() == {"sent": "text"} and sent[0]["type"] == "text" and f"capture/?order={o['capture_token']}" in sent[0]["text"]["body"]


def test_send_uses_the_template_when_one_is_set(tailor, sent, monkeypatch):
    monkeypatch.setenv("WHATSAPP_TEMPLATE_NAME", "tailorfit_link")
    o = order()
    assert tailor.post(f"/v1/orders/{o['id']}/send-whatsapp").json() == {"sent": "template"}
    assert sent[0]["type"] == "template" and o["capture_token"] in sent[0]["template"]["components"][0]["parameters"][0]["text"]


def test_send_falls_back_to_the_page_origin_when_no_public_url(tailor, sent, monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL")
    o = order()
    assert tailor.post(f"/v1/orders/{o['id']}/send-whatsapp").status_code == 422
    r = tailor.post(f"/v1/orders/{o['id']}/send-whatsapp", headers={"Origin": "https://abc.trycloudflare.com"})
    assert r.status_code == 200 and "https://abc.trycloudflare.com/capture/?order=" in sent[0]["text"]["body"]


def test_send_explains_problems(tailor, env, monkeypatch):
    no_phone = order(phone=None)
    r = tailor.post(f"/v1/orders/{no_phone['id']}/send-whatsapp")
    assert r.status_code == 502 and "phone number" in r.json()["detail"]
    o = order()
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(400, json={"error": {"message": "Recipient not in allowed list"}}))
    r = tailor.post(f"/v1/orders/{o['id']}/send-whatsapp")
    assert r.status_code == 502 and "Recipient not in allowed list" in r.json()["detail"]


def test_order_view_tells_the_dashboard_what_whatsapp_can_do(tailor, env, monkeypatch):
    o = order()
    info = tailor.get(f"/v1/orders/{o['id']}").json()["whatsapp"]
    assert info == {"phone_digits": "2348030000000", "auto": True}
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN")
    assert tailor.get(f"/v1/orders/{o['id']}").json()["whatsapp"]["auto"] is False
    bad = order(phone="call me")
    assert tailor.get(f"/v1/orders/{bad['id']}").json()["whatsapp"]["phone_digits"] is None


# ---------------- confirmation when the photos arrive ----------------

def upload(o):
    files = {"front": ("f.jpg", io.BytesIO(JPEG), "image/jpeg"), "side": ("s.jpg", io.BytesIO(JPEG), "image/jpeg")}
    return TestClient(app).post("/v1/measurements", files=files, data={"height_cm": "170", "consent": "true", "order_token": o["capture_token"]})


def test_customer_is_thanked_on_whatsapp_when_photos_arrive(sent):
    o = order()
    assert upload(o).status_code == 200
    assert len(sent) == 1 and sent[0]["to"] == "+2348030000000" and "Thanks Ngozi" in sent[0]["text"]["body"]


def test_no_thanks_when_whatsapp_is_off_or_there_is_no_number(sent, monkeypatch):
    upload(order(phone=None))
    assert sent == []
    monkeypatch.delenv("WHATSAPP_APP_SECRET")
    upload(order())
    assert sent == []


def test_a_closed_window_does_not_break_the_upload(env, monkeypatch):
    o = order()

    def refuse(payload):
        raise whatsapp.WhatsAppError("outside the 24 hour window")
    monkeypatch.setattr(whatsapp, "_post", refuse)
    assert upload(o).status_code == 200 and store.get_order(o["id"])["status"] == "measured"
