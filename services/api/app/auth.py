"""Tailor accounts: sign up, log in, log out, change password.

- Passwords are stored as scrypt hashes (Python's hashlib, no extra dependency), never in plain text.
- A session is a random token in an HttpOnly cookie; only its SHA-256 is stored (sessions table), so a copy of the
  database can't be used to log in, and sessions survive a restart.
- Each tailor sees only their own customers (enforced in dashboard_api).
- TAILOR_USERNAME / TAILOR_PASSWORD, if set, keep working: that account is created on the first login (later password
  changes happen in the app), and it takes over any customers from before accounts existed.
- Sign-up can be switched off with ALLOW_SIGNUP=0.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time

from fastapi import HTTPException, Request

from . import demo, store

COOKIE = "tf_session"
SESSION_SECONDS = 14 * 24 * 3600   # tailors work from one phone; two weeks before logging in again
MAX_FAILS, WINDOW = 5, 300
MIN_PASSWORD = 8
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_fails: dict[str, list[float]] = {}


def reset() -> None:
    """Forget failed-login counters (tests)."""
    _fails.clear()


def signup_allowed() -> bool:
    return os.environ.get("ALLOW_SIGNUP", "1") != "0"


# ---------------- passwords ----------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **SCRYPT)
    return "scrypt${n}${r}${p}${salt}${dk}".format(**SCRYPT, salt=base64.b64encode(salt).decode(), dk=base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(dk))


_DUMMY = hash_password(secrets.token_hex(8))  # checked when the email is unknown, so timing doesn't reveal which emails exist


def check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, f"Use at least {MIN_PASSWORD} characters for your password.")
    if len(password) > 200:
        raise HTTPException(422, "That password is too long.")


def normalize_email(email: str) -> str:
    return email.strip().lower()


# ---------------- account from the environment (older setups) ----------------

def _bootstrap() -> None:
    demo.ensure_demo_account(hash_password)
    user, pw = os.environ.get("TAILOR_USERNAME", "").strip(), os.environ.get("TAILOR_PASSWORD", "")
    if not (user and pw):
        return
    email = normalize_email(user)
    t = store.get_tailor_by_email(email)
    if t is None:
        t = store.create_tailor(user, "", email, hash_password(pw))  # password set once; after that it is changed in the app
        if t is None:
            return
    store.claim_unowned(t["id"])


# ---------------- sign up, log in, sessions ----------------

def public(t: dict) -> dict:
    return {"id": t["id"], "name": t["name"], "shop_name": t["shop_name"], "email": t["email"], "is_demo": bool(t["is_demo"])}


def signup(name: str, shop_name: str, email: str, password: str) -> dict:
    if not signup_allowed():
        raise HTTPException(403, "New accounts are switched off on this server.")
    email = normalize_email(email)
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if not name.strip():
        raise HTTPException(422, "Enter your name.")
    check_new_password(password)
    t = store.create_tailor(name.strip(), shop_name.strip(), email, hash_password(password))
    if t is None:
        raise HTTPException(409, "There is already an account with this email. Log in instead.")
    return t


def start_session(tailor_id: int) -> str:
    token = secrets.token_urlsafe(32)
    store.add_session(_h(token), tailor_id, time.time() + SESSION_SECONDS)
    return token


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(email: str, password: str, client: str) -> str:
    email = normalize_email(email)
    key = f"{client}|{email}"
    recent = [t for t in _fails.get(key, []) if time.time() - t < WINDOW]
    if len(recent) >= MAX_FAILS:
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    _bootstrap()
    t = store.get_tailor_by_email(email)
    ok = verify_password(password, t["password_hash"] if t else _DUMMY) and t is not None
    if not ok:
        _fails[key] = recent + [time.time()]
        raise HTTPException(401, "Wrong email or password.")
    _fails.pop(key, None)
    return start_session(t["id"])


def logout(token: str | None) -> None:
    if token:
        store.delete_session(_h(token))


def current(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    return store.session_tailor(_h(token), time.time()) if token else None


def require_tailor(request: Request) -> dict:
    """FastAPI dependency: the logged-in tailor, or 401."""
    t = current(request)
    if t is None:
        raise HTTPException(401, "Please log in.")
    return t


def change_password(t: dict, current_password: str, new_password: str, keep_token: str | None) -> None:
    if not verify_password(current_password, t["password_hash"]):
        raise HTTPException(401, "Your current password is not right.")
    check_new_password(new_password)
    store.update_tailor(t["id"], password_hash=hash_password(new_password))
    store.delete_other_sessions(t["id"], _h(keep_token) if keep_token else None)  # log out every other device
