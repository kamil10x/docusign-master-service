"""HMAC request authentication.

Client sends:
    X-Timestamp: unix seconds
    X-Signature: hex(HMAC_SHA256(secret, f"{timestamp}.{METHOD}.{path}.{sha256(body)}"))
"""
import hashlib
import hmac
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings

OPEN_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}


def compute_signature(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}.{method.upper()}.{path}.{body_hash}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


async def verify_hmac(request: Request) -> bool:
    """Verify HMAC authentication for FastAPI route dependencies."""

    from app.config import settings

    key_id = request.headers.get("X-Key-Id")
    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")

    if not key_id or not timestamp or not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing HMAC authentication headers",
        )

    if key_id == "core":
        secret = settings.HMAC_SECRET_KEY_CORE
    elif key_id == "engineer":
        secret = settings.HMAC_SECRET_KEY_ENGINEER
    else:
        raise HTTPException(
            status_code=401,
            detail="Unknown key ID",
        )

    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid timestamp",
        )

    if abs(time.time() - ts) > settings.HMAC_SIGNATURE_MAX_AGE:
        raise HTTPException(
            status_code=401,
            detail="Timestamp outside allowed window",
        )

    body = await request.body()

    expected = compute_signature(
        secret=secret,
        timestamp=timestamp,
        method=request.method,
        path=request.url.path,
        body=body,
    )

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid signature",
        )

    return True


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(status_code=401, content={"detail": detail})


class HMACAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in OPEN_PATHS:
            return await call_next(request)

        settings = get_settings()
        if not settings.hmac_secret:
            return JSONResponse(
                status_code=500, content={"detail": "HMAC secret is not configured"}
            )

        timestamp = request.headers.get("X-Timestamp")
        signature = request.headers.get("X-Signature")
        if not timestamp or not signature:
            return _unauthorized("Missing X-Timestamp or X-Signature header")

        try:
            ts = int(timestamp)
        except ValueError:
            return _unauthorized("Invalid X-Timestamp")
        if abs(time.time() - ts) > settings.hmac_max_skew_seconds:
            return _unauthorized("Timestamp outside allowed window")

        body = await request.body()
        expected = compute_signature(
            settings.hmac_secret, timestamp, request.method, request.url.path, body
        )
        if not hmac.compare_digest(expected, signature):
            return _unauthorized("Invalid signature")

        return await call_next(request)