"""Tailor login. One account from the environment (TAILOR_USERNAME / TAILOR_PASSWORD).

There is no default password: if they are not set the dashboard is switched off, so a forgotten
config can never leave customer data open. Sessions live in memory (a restart logs everyone out).
"""
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request

COOKIE = "tf_session"
SESSION_SECONDS = 12 * 3600
MAX_FAILS, WINDOW = 5, 300

_sessions: dict[str, float] = {}
_fails: dict[str, list[float]] = {}


def configured() -> bool:
    return bool(os.environ.get("TAILOR_USERNAME") and os.environ.get("TAILOR_PASSWORD"))


def reset() -> None:
    _sessions.clear()
    _fails.clear()


def login(username: str, password: str, client: str) -> str:
    if not configured():
        raise HTTPException(503, "The tailor dashboard is not set up: set TAILOR_USERNAME and TAILOR_PASSWORD.")
    recent = [t for t in _fails.get(client, []) if time.time() - t < WINDOW]
    if len(recent) >= MAX_FAILS:
        raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    ok_user = hmac.compare_digest(username.encode(), os.environ["TAILOR_USERNAME"].encode())
    ok_pass = hmac.compare_digest(password.encode(), os.environ["TAILOR_PASSWORD"].encode())
    if not (ok_user and ok_pass):
        _fails[client] = recent + [time.time()]
        raise HTTPException(401, "Wrong username or password.")
    _fails.pop(client, None)
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_SECONDS
    return token


def logout(token: str | None) -> None:
    _sessions.pop(token or "", None)


def is_logged_in(request: Request) -> bool:
    token = request.cookies.get(COOKIE)
    exp = _sessions.get(token or "")
    if exp is None or exp < time.time():
        _sessions.pop(token or "", None)
        return False
    return True


def require_tailor(request: Request) -> None:
    if not configured():
        raise HTTPException(503, "The tailor dashboard is not set up: set TAILOR_USERNAME and TAILOR_PASSWORD.")
    if not is_logged_in(request):
        raise HTTPException(401, "Please log in.")
