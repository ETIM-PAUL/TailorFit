"""Security layer: response headers, cross-site request refusal, per-address rate limits."""
import os
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import HTTPException, Request

# default-src 'self' blocks every outside script, image and connection. The pages use inline style
# attributes (set from JavaScript), so style needs 'unsafe-inline'; scripts are all external files.
CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


def security_headers(request: Request, headers) -> None:
    headers["X-Content-Type-Options"] = "nosniff"
    headers["X-Frame-Options"] = "DENY"
    headers["Referrer-Policy"] = "no-referrer"  # the customer link carries a secret token in its address
    headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=(), payment=()"
    headers["Content-Security-Policy"] = CSP
    if request.url.path.startswith("/v1/"):
        headers["Cache-Control"] = "no-store"
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        headers["Strict-Transport-Security"] = "max-age=31536000"


# ---- refuse cross-site requests that would change something ----

PROTECTED_PREFIXES = ("/v1/auth/", "/v1/orders")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def cross_site(request: Request) -> bool:
    """True if a state-changing request to a tailor endpoint comes from another website."""
    if request.method not in UNSAFE or not request.url.path.startswith(PROTECTED_PREFIXES):
        return False
    origin = request.headers.get("origin")
    if not origin:
        return False  # not a browser cross-site request (or an older client); cookies are SameSite=Lax anyway
    host = urlparse(origin).netloc
    allowed = {request.headers.get("host", "")}
    public = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if public:
        allowed.add(urlparse(public).netloc)
    return host not in allowed


# ---- rate limits (in memory; they stop one address running up the AI bill, they are not a DDoS shield) ----

_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """Real address. Behind our own tunnel or proxy every request arrives from loopback, so trust its forwarded header."""
    direct = request.client.host if request.client else "?"
    if direct in ("127.0.0.1", "::1"):
        fwd = request.headers.get("cf-connecting-ip") or (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if fwd:
            return fwd
    return direct


def reset_limits() -> None:
    _hits.clear()


def limit(bucket: str, count: int, seconds: int = 60):
    """FastAPI dependency: at most `count` calls per `seconds` per address. DISABLE_RATE_LIMITS=1 is for load tests only."""
    def check(request: Request) -> None:
        if os.environ.get("DISABLE_RATE_LIMITS") == "1":
            return
        now, q = time.time(), _hits[(bucket, client_ip(request))]
        while q and now - q[0] > seconds:
            q.popleft()
        if len(q) >= count:
            raise HTTPException(429, "Too many requests. Please wait a minute and try again.", headers={"Retry-After": str(seconds)})
        q.append(now)
    return check
