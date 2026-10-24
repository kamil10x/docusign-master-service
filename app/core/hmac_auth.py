import hashlib
import hmac
import time

from fastapi import HTTPException, Request, status

from app.config import settings


def _secrets() -> dict[str, str]:
    keys = {
        "core": settings.HMAC_SECRET_KEY_CORE,
        "engineer": settings.HMAC_SECRET_KEY_ENGINEER,
    }
    return {k: v for k, v in keys.items() if v}  # an empty secret is never valid


def compute_signature(secret: str, timestamp: str, method: str, path_with_query: str, body: bytes) -> str:
    body_hash = hashlib.sha256(body).hexdigest()
    message = f"{timestamp}\n{method.upper()}\n{path_with_query}\n{body_hash}"
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def _unauthorized(detail: str = "Invalid or missing signature") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def verify_hmac(request: Request) -> str:
    """FastAPI dependency. Returns the authenticated key id ('core' | 'engineer')."""
    if not settings.HMAC_ENABLED:
        return "disabled"

    key_id = request.headers.get("X-Key-Id")
    timestamp = request.headers.get("X-Timestamp")
    signature = request.headers.get("X-Signature")
    if not (key_id and timestamp and signature):
        raise _unauthorized()

    secret = _secrets().get(key_id)
    if secret is None:
        raise _unauthorized()  # same message as a bad signature, so key ids can't be probed

    try:
        ts = int(timestamp)
    except ValueError:
        raise _unauthorized()
    if abs(time.time() - ts) > settings.HMAC_SIGNATURE_MAX_AGE:
        raise _unauthorized("Request timestamp expired")

    body = await request.body()
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    expected = compute_signature(secret, timestamp, request.method, path, body)

    if not hmac.compare_digest(expected, signature):
        raise _unauthorized()

    request.state.key_id = key_id
    return key_id