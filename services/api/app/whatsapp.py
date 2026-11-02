"""WhatsApp: click-to-chat links, automatic sending (Cloud API) and the webhook that answers customers.

Two layers, so the demo never depends on WhatsApp approval:

1. Click-to-chat (`wa.me`): needs nothing but the customer's number. The tailor taps a button and
   WhatsApp opens with the message already written.
2. Cloud API (needs WHATSAPP_* settings): sends messages itself and answers customers who message
   the business number.

Rules that shape this module (from Meta's Cloud API docs, read through third-party mirrors; check
developers.facebook.com before relying on the details):
- Free-form text can only be sent within 24 hours of the customer's last message. A business-first
  message must be an approved template.
- The webhook must answer the GET handshake with the raw `hub.challenge`, and every POST must be
  checked against X-Hub-Signature-256 (HMAC-SHA256 of the raw body with the app secret).
- Recipient numbers go in international format.

NOT yet exercised against a real WhatsApp account: no credentials were available. The request and
payload shapes below are covered by tests with a mock only.
"""
import hashlib
import hmac
import os
import re
from urllib.parse import quote

import httpx

from . import store

DEFAULT_API_VERSION = "v21.0"  # unconfirmed: set WHATSAPP_API_VERSION to the current one


class WhatsAppError(Exception):
    pass


# ---------------- settings ----------------

def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def configured() -> bool:
    """Everything needed to send and to receive safely (the signature check needs the app secret)."""
    return all(_env(n) for n in ("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET"))


def public_base_url() -> str:
    return _env("PUBLIC_BASE_URL").rstrip("/")


# ---------------- numbers and links ----------------

def normalize_phone(raw: str | None) -> str | None:
    """Digits in international format (no plus), or None if it can't be a phone number.

    '+234 803 000 0000' and '234 803 000 0000' are taken as international. A number starting with a single
    0 is local and gets WHATSAPP_DEFAULT_COUNTRY_CODE (default 234, Nigeria). '00' means international.
    """
    if not raw:
        return None
    s = raw.strip()
    digits = re.sub(r"\D", "", s)
    if not digits:
        return None
    if not s.startswith("+"):
        if digits.startswith("00"):
            digits = digits[2:]
        elif digits.startswith("0"):
            digits = _env("WHATSAPP_DEFAULT_COUNTRY_CODE", "234") + digits[1:]
    return digits if 8 <= len(digits) <= 15 else None


def click_to_chat_url(phone_digits: str, message: str) -> str:
    return f"https://wa.me/{phone_digits}?text={quote(message)}"


def capture_link(order: dict, base_url: str) -> str:
    return f"{base_url.rstrip('/')}/capture/?order={order['capture_token']}"


def first_name(order: dict) -> str:
    return (order.get("customer_name") or "").split()[0] if order.get("customer_name") else "there"


def invite_text(order: dict, link: str) -> str:
    style = (f" for your {order['style_id'].replace('_', ' ')}" if order.get("style_id") else "")
    return (f"Hi {first_name(order)}, please take two quick photos so I can get your measurements{style}. "
            f"Open this link on your phone: {link}")


# ---------------- sending (Cloud API) ----------------

def _post(payload: dict) -> dict:
    url = f"https://graph.facebook.com/{_env('WHATSAPP_API_VERSION', DEFAULT_API_VERSION)}/{_env('WHATSAPP_PHONE_NUMBER_ID')}/messages"
    try:
        r = httpx.post(url, json=payload, headers={"Authorization": f"Bearer {_env('WHATSAPP_ACCESS_TOKEN')}"}, timeout=10)
    except httpx.HTTPError as e:
        raise WhatsAppError(f"Could not reach WhatsApp: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:200]
        raise WhatsAppError(f"WhatsApp refused the message ({r.status_code}): {msg}")
    return r.json()


def send_text(to_digits: str, body: str) -> dict:
    """Free-form text. Only works inside the 24-hour window after the customer last messaged."""
    return _post({"messaging_product": "whatsapp", "to": "+" + to_digits, "type": "text", "text": {"preview_url": True, "body": body}})


def send_template(to_digits: str, name: str, language: str, link: str | None) -> dict:
    """An approved template (the only kind of message a business may start a conversation with).

    The template is assumed to have one body variable, {{1}}, that receives the link; set
    WHATSAPP_TEMPLATE_VARS=0 for a template with no variables (such as Meta's sample hello_world).
    """
    template: dict = {"name": name, "language": {"code": language}}
    if _env("WHATSAPP_TEMPLATE_VARS", "1") != "0" and link:
        template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": link}]}]
    return _post({"messaging_product": "whatsapp", "to": "+" + to_digits, "type": "template", "template": template})


def send_invite(order: dict, base_url: str) -> str:
    """Send the capture link. Uses the approved template if one is configured, else free-form text
    (which only works if the customer has messaged the business number in the last 24 hours)."""
    to = normalize_phone(order.get("customer_phone"))
    if not to:
        raise WhatsAppError("This customer's phone number is missing or not valid. Add it with the country code.")
    link = capture_link(order, base_url)
    template = _env("WHATSAPP_TEMPLATE_NAME")
    if template:
        send_template(to, template, _env("WHATSAPP_TEMPLATE_LANG", "en"), link)
        return "template"
    send_text(to, invite_text(order, link))
    return "text"


def notify_measured(order: dict) -> None:
    """Best effort: tell the customer their photos arrived. Silent if WhatsApp is off or the window is closed."""
    if not configured():
        return
    to = normalize_phone(order.get("customer_phone"))
    if not to:
        return
    try:
        send_text(to, f"Thanks {first_name(order)}, your tailor has your measurements now. "
                      "They will check them before cutting. Reply here if you want to send new photos.")
    except WhatsAppError:
        pass  # outside the 24-hour window a free-form message is refused; nothing else to do


# ---------------- webhook ----------------

def verify_handshake(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """Meta's subscribe handshake: return the challenge to echo, or None to refuse."""
    expected = _env("WHATSAPP_VERIFY_TOKEN")
    if mode == "subscribe" and expected and token is not None and hmac.compare_digest(token.encode(), expected.encode()) and challenge is not None:
        return challenge
    return None


def signature_ok(raw_body: bytes, header: str | None) -> bool:
    secret = _env("WHATSAPP_APP_SECRET")
    if not secret or not header or not header.startswith("sha256="):
        return False
    good = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[len("sha256="):], good)


def inbound_messages(payload: dict) -> list[dict]:
    """Pull {id, from, type, text} out of a webhook payload; anything unexpected is skipped, never raised."""
    out = []
    try:
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                for m in (change.get("value") or {}).get("messages") or []:
                    out.append({"id": m.get("id"), "from": re.sub(r"\D", "", str(m.get("from") or "")), "type": m.get("type"),
                                "text": ((m.get("text") or {}).get("body") or "").strip()})
    except AttributeError:
        return []
    return out


def find_order(phone_digits: str) -> dict | None:
    """The customer's order for this number: the newest one still waiting for photos, else the newest."""
    mine = [o for o in store.list_orders() if normalize_phone(o.get("customer_phone")) == phone_digits]
    waiting = [o for o in mine if o["status"] == "new"]
    return (waiting or mine or [None])[0]


def reply_for(msg: dict) -> str | None:
    """What to say back to a customer who messaged the business number."""
    order = find_order(msg["from"])
    if not order:
        return "Hi! We couldn't find an order for this number. Please ask your tailor to add your phone number, then message us again."
    base = public_base_url()
    if not base:
        return None  # can't build a link; the tailor needs to set PUBLIC_BASE_URL
    link = capture_link(order, base)
    if msg["type"] != "text":
        return f"Thanks! Please use this link to send your photos: {link}"
    if order["status"] == "measured" and msg["text"].lower() not in ("retake", "new photos"):
        return (f"Hi {first_name(order)}, your tailor already has your measurements. "
                "If you want to send new photos, reply RETAKE.")
    return invite_text(order, link)


def handle_webhook(payload: dict) -> int:
    """Answer each new message once. Returns how many replies were sent. Never raises: Meta retries on errors."""
    sent = 0
    for msg in inbound_messages(payload):
        if not msg["id"] or not msg["from"] or not store.mark_message_seen(msg["id"]):
            continue  # unknown shape, or Meta delivered this one twice
        try:
            text = reply_for(msg)
            if text:
                send_text(msg["from"], text)
                sent += 1
        except WhatsAppError:
            pass
    return sent
