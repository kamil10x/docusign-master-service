"""HMAC request authentication.

Client sends:
    X-Timestamp: unix seconds
    X-Signature: hex(HMAC_SHA256(secret, f"{timestamp}.{METHOD}.{path}.{sha256(body)}"))
"""
import hashlib
import hmac
import time
import traceback

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings as app_settings
from app.core.config import get_settings

OPEN_PATHS = {"/api/health", "/docs", "/openapi.json", "/redoc"}


def compute_signature(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}.{method.upper()}.{path}.{body_hash}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


async def verify_hmac(request: Request) -> bool:
    """Verify HMAC authentication for FastAPI route dependencies."""
    key_id = request.headers.get("X-Key-Id", "core")
    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")

    if not timestamp or not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing HMAC authentication headers",
        )

    if key_id == "core":
        secret = app_settings.HMAC_SECRET_KEY_CORE
    elif key_id == "engineer":
        secret = app_settings.HMAC_SECRET_KEY_ENGINEER
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

    if abs(time.time() - ts) > app_settings.HMAC_SIGNATURE_MAX_AGE:
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
        print(f"DEBUG: HMAC middleware entered for {request.method} {request.url.path}", flush=True)

        if request.url.path in OPEN_PATHS:
            return await call_next(request)

        core_settings = get_settings()
        secret = core_settings.hmac_secret or app_settings.HMAC_SECRET_KEY_CORE
        max_skew = core_settings.hmac_max_skew_seconds or app_settings.HMAC_SIGNATURE_MAX_AGE

        if not secret:
            print("DEBUG: HMAC secret missing", flush=True)
            return JSONResponse(
                status_code=500,
                content={"detail": "HMAC secret is not configured"}
            )

        timestamp = request.headers.get("X-Timestamp")
        signature = request.headers.get("X-Signature")

        if not timestamp or not signature:
            print("DEBUG: HMAC headers missing", flush=True)
            return _unauthorized("Missing X-Timestamp or X-Signature header")

        try:
            ts = int(timestamp)
        except ValueError:
            print("DEBUG: Invalid timestamp", flush=True)
            return _unauthorized("Invalid X-Timestamp")

        if abs(time.time() - ts) > max_skew:
            print("DEBUG: Timestamp expired", flush=True)
            return _unauthorized("Timestamp outside allowed window")

        body = await request.body()
        print(f"DEBUG: Request body read ({len(body)} bytes)", flush=True)

        expected = compute_signature(
            secret,
            timestamp,
            request.method,
            request.url.path,
            body
        )

        if not hmac.compare_digest(expected, signature):
            print("DEBUG: Invalid signature", flush=True)
            return _unauthorized("Invalid signature")

        # Re-populate receive stream so BaseHTTPMiddleware doesn't starve downstream body parsing
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = receive

        print("DEBUG: HMAC verified; calling endpoint", flush=True)
        try:
            response = await call_next(request)
            print("DEBUG: Endpoint returned:", response.status_code, flush=True)
            return response
        except Exception as exc:
            print("ERROR: Unhandled exception in endpoint:", repr(exc), flush=True)
            traceback.print_exc()
            return JSONResponse(
                status_code=500,
                content={"detail": str(exc), "type": type(exc).__name__}
            )