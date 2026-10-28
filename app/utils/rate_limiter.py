from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Mapping

import httpx

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    """Raised on HTTP 429. `retry_after` is in seconds (None if the header is absent)."""

    def __init__(self, retry_after: float | None = None, message: str = "DocuSign rate limit hit (429)"):
        super().__init__(message)
        self.retry_after = retry_after


def parse_retry_after(headers: Mapping[str, str]) -> float | None:
    """Parse Retry-After as delta-seconds or an HTTP-date. Returns None if missing/invalid."""
    raw = headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


class RateLimiter:
    """
    Reactive: turns 429 into RateLimitError.
    Proactive: tracks X-RateLimit-Remaining / X-RateLimit-Reset and pauses
    before the budget is exhausted. Thread-safe.
    """

    def __init__(self, min_remaining: int = 2, max_proactive_wait: float = 30.0):
        self.min_remaining = min_remaining
        self.max_proactive_wait = max_proactive_wait
        self._remaining: int | None = None
        self._reset_at: float | None = None  # epoch seconds
        self._lock = threading.Lock()

    def before_request(self) -> None:
        with self._lock:
            remaining, reset_at = self._remaining, self._reset_at
        if remaining is None or reset_at is None or remaining > self.min_remaining:
            return
        wait = min(max(0.0, reset_at - time.time()), self.max_proactive_wait)
        if wait > 0:
            logger.warning("Rate limit budget low (%s left); sleeping %.1fs", remaining, wait)
            time.sleep(wait)

    def update(self, headers: Mapping[str, str]) -> None:
        try:
            remaining = int(headers["X-RateLimit-Remaining"])
            reset_at = float(headers["X-RateLimit-Reset"])
        except (KeyError, ValueError):
            return
        with self._lock:
            self._remaining, self._reset_at = remaining, reset_at

    def check_response(self, response: httpx.Response) -> None:
        self.update(response.headers)
        if response.status_code == 429:
            raise RateLimitError(retry_after=parse_retry_after(response.headers))