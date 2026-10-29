
from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

import httpx

from app.docusign.exceptions import (
    DocuSignAPIError,
    DocuSignRateLimitError,
)
from app.utils.rate_limiter import RateLimitError

logger = logging.getLogger(__name__)
T = TypeVar("T")

RETRYABLE_STATUS = {500, 502, 503, 504}


def is_retryable(exc: BaseException) -> bool:
    """Return whether an exception should trigger another attempt."""

    # Custom DocuSign 429 errors must be checked before their API-error parent.
    if isinstance(exc, (RateLimitError, DocuSignRateLimitError)):
        return True

    if isinstance(exc, httpx.TransportError):
        return True

    if isinstance(exc, httpx.HTTPStatusError):
        return 500 <= exc.response.status_code < 600

    if isinstance(exc, DocuSignAPIError):
        # None represents a network error; 5xx represents a server failure.
        return (
            exc.status_code is None
            or 500 <= exc.status_code < 600
        )

    # 400/401/403/404 and unexpected programming errors fail immediately.
    return False


def compute_backoff(
    attempt: int,
    base: float = 1.0,
    cap: float = 60.0,
) -> float:
    """Exponential backoff with full jitter. Attempt starts at zero."""
    return random.uniform(0, min(cap, base * (2 ** attempt)))


def retry_call(
    func: Callable[..., T],
    *args,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    max_retry_after: float = 300.0,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> T:
    """Retry transient failures, then re-raise the final exception."""

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)

        except Exception as exc:
            if attempt == max_attempts - 1 or not is_retryable(exc):
                raise

            retry_after = None
            if isinstance(exc, (RateLimitError, DocuSignRateLimitError)):
                retry_after = exc.retry_after

            if retry_after is not None:
                wait = min(max(0.0, retry_after), max_retry_after)
                wait += random.uniform(0, 0.5)
            else:
                wait = compute_backoff(attempt, base_delay, max_delay)

            logger.warning(
                "Retryable error (%s: %s); attempt %d/%d, sleeping %.2fs",
                type(exc).__name__,
                exc,
                attempt + 1,
                max_attempts,
                wait,
            )
            sleep(wait)

    raise RuntimeError("unreachable")  # pragma: no cover
