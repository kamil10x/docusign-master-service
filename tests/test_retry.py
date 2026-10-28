import httpx
import pytest

from app.utils.rate_limiter import RateLimitError, parse_retry_after
from app.utils.retry import compute_backoff, is_retryable, retry_call


def _status_error(code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "http://x")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(code, request=req))


def test_retries_then_succeeds_and_honors_retry_after():
    calls, sleeps = {"n": 0}, []

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RateLimitError(retry_after=0.1)
        return "ok"

    assert retry_call(flaky, sleep=sleeps.append) == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2 and all(s >= 0.1 for s in sleeps)


def test_non_retryable_fails_immediately():
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise _status_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        retry_call(bad, sleep=lambda s: None)
    assert calls["n"] == 1


def test_gives_up_after_max_attempts():
    calls = {"n": 0}

    def always():
        calls["n"] += 1
        raise _status_error(503)

    with pytest.raises(httpx.HTTPStatusError):
        retry_call(always, max_attempts=3, sleep=lambda s: None)
    assert calls["n"] == 3


@pytest.mark.parametrize("code,expected", [(500, True), (503, True), (400, False), (401, False), (404, False)])
def test_is_retryable_status(code, expected):
    assert is_retryable(_status_error(code)) is expected


def test_backoff_bounds():
    for attempt in range(10):
        assert 0 <= compute_backoff(attempt, base=1.0, cap=8.0) <= 8.0


def test_parse_retry_after():
    assert parse_retry_after({"Retry-After": "5"}) == 5.0
    assert parse_retry_after({}) is None
    assert parse_retry_after({"Retry-After": "garbage"}) is None