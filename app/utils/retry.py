from __future__ import annotations

import logging
import random
import time
from typing import Callable, TypeVar

import httpx

from app.utils.rate_limiter import RateLimitError

logger = logging.getLogger(__name__)
T = TypeVar("T")

RETRYABLE_STATUS = {500, 502, 503, 504}


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, httpx.TransportError):  # timeouts, connect/read errors
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS
    return False  # 400/401/403/404 and programming errors: fail fast


def compute_backoff(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """Exponential backoff with full jitter. attempt starts at 0."""
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
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            last = attempt == max_attempts - 1
            if last or not is_retryable(exc):
                raise
            if isinstance(exc, RateLimitError) and exc.retry_after is not None:
                wait = min(exc.retry_after, max_retry_after) + random.uniform(0, 0.5)
            else:
                wait = compute_backoff(attempt, base_delay, max_delay)
            logger.warning(
                "Retryable error (%s: %s); attempt %d/%d, sleeping %.2fs",
                type(exc).__name__, exc, attempt + 1, max_attempts, wait,
            )
            sleep(wait)
    raise RuntimeError("unreachable")  # pragma: no cover