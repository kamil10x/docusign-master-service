
import json
from pathlib import Path

import httpx
import pytest
import respx

from app.docusign.client import DocuSignClient
from app.docusign.envelopes import (
    list_envelopes,
    iter_envelope_pages,
    iter_envelopes,
)
from app.utils.rate_limiter import RateLimiter
from app.utils import retry as retry_module
from app.docusign import client as client_module
from app.docusign.exceptions import DocuSignAPIError

# ---------------- CONFIG ----------------

BASE_URL = "https://demo.docusign.net"
ACCOUNT_ID = "test-account"
MAX_ATTEMPTS = 5

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


# ----------------------------------------


def load_fixture(filename):
    with open(FIXTURES / filename, encoding="utf-8") as file:
        return json.load(file)


class FakeAuth:
    def get_access_token(self):
        return "fake-access-token"


@pytest.fixture
def sleeps():
    return []


@pytest.fixture
def make_client(monkeypatch, sleeps):
    # Prevent actual exponential backoff delays.
    monkeypatch.setattr(
        retry_module,
        "compute_backoff",
        lambda *args, **kwargs: 0,
    )

    original_retry_call = retry_module.retry_call

    # Replace time.sleep with a recorder.
    def retry_with_fake_sleep(func, *args, **kwargs):
        kwargs["sleep"] = lambda seconds: sleeps.append(seconds)
        return original_retry_call(func, *args, **kwargs)

    monkeypatch.setattr(
        client_module,
        "retry_call",
        retry_with_fake_sleep,
    )

    def factory(max_attempts=MAX_ATTEMPTS):
        return DocuSignClient(
            auth=FakeAuth(),
            base_url=BASE_URL,
            account_id=ACCOUNT_ID,
            limiter=RateLimiter(),
            max_attempts=max_attempts,
        )

    return factory


def expand_page(template, count, start):
    page = dict(template)

    envelope_template = template["envelopes"][0]

    page["envelopes"] = [
        {
            **envelope_template,
            "envelopeId": f"env-{i:03d}",
        }
        for i in range(start, start + count)
    ]

    page["resultSetSize"] = count
    page["startPosition"] = str(start)

    return page


# ---------------- PAGINATION ----------------


@respx.mock
def test_paging_fetches_all_pages(make_client):
    page1 = expand_page(
        load_fixture("envelopes_page1.json"), 100, 0
    )
    page2 = expand_page(
        load_fixture("envelopes_page2.json"), 30, 100
    )

    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    client = make_client()

    try:
        pages = list(
            iter_envelope_pages(
                client=client,
                from_date="2026-10-01T00:00:00Z",
                page_size=100,
            )
        )

        envelopes = [
            envelope
            for page in pages
            for envelope in page["envelopes"]
        ]

        assert len(envelopes) == 130
        assert len(pages) == 2
        assert route.call_count == 2

        positions = [
            int(call.request.url.params["start_position"])
            for call in route.calls
        ]

        assert positions == [0, 100]

    finally:
        client.close()


@respx.mock
def test_single_page_makes_one_call(make_client):
    page = expand_page(
        load_fixture("envelopes_page1.json"), 5, 0
    )
    page["totalSetSize"] = 5

    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        return_value=httpx.Response(200, json=page)
    )

    client = make_client()

    try:
        envelopes = list(
            iter_envelopes(
                client,
                from_date="2026-10-01T00:00:00Z",
            )
        )

        assert len(envelopes) == 5
        assert route.call_count == 1

    finally:
        client.close()


@respx.mock
def test_empty_result(make_client):
    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "resultSetSize": "0",
                "totalSetSize": "0",
            },
        )
    )

    client = make_client()

    try:
        envelopes = list(
            iter_envelopes(
                client,
                from_date="2026-10-01T00:00:00Z",
            )
        )

        assert envelopes == []
        assert route.call_count == 1

    finally:
        client.close()


# ---------------- HTTP 429 ----------------


@respx.mock
def test_429_waits_retry_after_then_succeeds(make_client, sleeps):
    page = load_fixture("envelopes_page1.json")

    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        side_effect=[
            httpx.Response(
                429,
                headers={"Retry-After": "2"},
            ),
            httpx.Response(200, json=page),
        ]
    )

    client = make_client()

    try:
        result = list_envelopes(
            client,
            from_date="2026-10-01T00:00:00Z",
        )

        assert result["resultSetSize"] == 100
        assert route.call_count == 2
        assert len(sleeps) == 1
        assert sleeps[0] >= 2

    finally:
        client.close()


@respx.mock
def test_429_without_retry_after_still_retries(make_client, sleeps):
    page = load_fixture("envelopes_page1.json")

    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json=page),
        ]
    )

    client = make_client()

    try:
        result = list_envelopes(
            client,
            from_date="2026-10-01T00:00:00Z",
        )

        assert result["resultSetSize"] == 100
        assert route.call_count == 2
        assert len(sleeps) == 1

    finally:
        client.close()


# ---------------- HTTP 500 RETRIES ----------------


@respx.mock
def test_500_then_503_then_success(make_client):
    page = load_fixture("envelopes_page1.json")

    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(503),
            httpx.Response(200, json=page),
        ]
    )

    client = make_client()

    try:
        result = client.get("/envelopes")

        assert result["resultSetSize"] == 100
        assert route.call_count == 3

    finally:
        client.close()


@respx.mock
def test_persistent_500_raises_after_max_attempts(make_client):
    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        return_value=httpx.Response(500)
    )

    client = make_client()

    try:
        with pytest.raises(DocuSignAPIError):
            client.get("/envelopes")

        assert route.call_count == MAX_ATTEMPTS

    finally:
        client.close()


# ---------------- NON-RETRYABLE ERRORS ----------------


@pytest.mark.parametrize("status_code", [400, 401, 403])
@respx.mock
def test_client_errors_are_not_retried(status_code, make_client):
    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        return_value=httpx.Response(status_code)
    )

    client = make_client()

    try:
        with pytest.raises(DocuSignAPIError):
            client.get("/envelopes")

        assert route.call_count == 1

    finally:
        client.close()


# ---------------- NETWORK ERROR ----------------


@respx.mock
def test_network_error_is_retried(make_client):
    page = load_fixture("envelopes_page1.json")

    route = respx.get(
        url__regex=r".*/envelopes(?:\?.*)?$"
    ).mock(
        side_effect=[
            httpx.ConnectError("Connection failed"),
            httpx.Response(200, json=page),
        ]
    )

    client = make_client()

    try:
        result = client.get("/envelopes")

        assert result["resultSetSize"] == 100
        assert route.call_count == 2

    finally:
        client.close()
