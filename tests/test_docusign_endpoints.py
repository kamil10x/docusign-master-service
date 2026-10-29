
import pytest
import httpx
import app.docusign.client as client_module

from app.docusign.envelopes import (
    get_envelope_documents,
    get_envelope_recipients,
)
from app.docusign.templates import iter_templates, list_templates


def test_recipients_returns_raw_json():
    class FakeClient:
        def get(self, path, params=None):
            assert path == "/envelopes/env-1/recipients"
            assert params == {"include_tabs": "false"}
            return {"signers": [{"recipientId": "1"}]}

    result = get_envelope_recipients(FakeClient(), "env-1")
    assert result["signers"][0]["recipientId"] == "1"


def test_documents_returns_metadata():
    class FakeClient:
        def get(self, path, params=None):
            assert path == "/envelopes/env-1/documents"
            return {
                "envelopeDocuments": [
                    {"documentId": "1", "name": "contract.pdf", "pages": "2"}
                ]
            }

    result = get_envelope_documents(FakeClient(), "env-1")
    assert result["envelopeDocuments"][0]["name"] == "contract.pdf"


def test_list_templates_fetches_one_page():
    class FakeClient:
        def get(self, path, params=None):
            assert path == "/templates"
            assert params == {"start_position": 0, "count": 1}
            return {"envelopeTemplates": [{"templateId": "t1"}]}

    assert list_templates(FakeClient(), count=1)["envelopeTemplates"][0]["templateId"] == "t1"


def test_template_pagination_returns_three_items_once():
    class FakeClient:
        def __init__(self):
            self.starts = []

        def get(self, path, params=None):
            start = params["start_position"]
            self.starts.append(start)

            pages = {
                0: {
                    "envelopeTemplates": [{"templateId": "t1"}],
                    "resultSetSize": 1,
                    "totalSetSize": 3,
                    "endPosition": "0",
                    "nextUri": "/templates?start_position=1",
                },
                1: {
                    "envelopeTemplates": [{"templateId": "t2"}],
                    "resultSetSize": 1,
                    "totalSetSize": 3,
                    "endPosition": "1",
                    "nextUri": "/templates?start_position=2",
                },
                2: {
                    "envelopeTemplates": [{"templateId": "t3"}],
                    "resultSetSize": 1,
                    "totalSetSize": 3,
                    "endPosition": "2",
                    "nextUri": "",
                },
            }
            return pages[start]

    client = FakeClient()
    items = list(iter_templates(client, page_size=1))

    assert [item["templateId"] for item in items] == ["t1", "t2", "t3"]
    assert client.starts == [0, 1, 2]


def test_recipients_retries_429_then_succeeds(monkeypatch):
    """A 429 response should respect Retry-After and retry successfully."""
    attempts = []
    sleeps = []

    def handler(request):
        attempts.append(request)
        if len(attempts) == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "2"},
                json={"message": "Rate limit exceeded"},
            )

        return httpx.Response(
            200,
            json={"signers": [{"recipientId": "1"}]},
        )

    real_retry_call = client_module.retry_call

    def retry_with_recorded_sleep(func, *args, **kwargs):
        kwargs["sleep"] = sleeps.append
        return real_retry_call(func, *args, **kwargs)

    monkeypatch.setattr(
        client_module, "retry_call", retry_with_recorded_sleep
    )

    http = httpx.Client(transport=httpx.MockTransport(handler))

    class FakeAuth:
        def get_access_token(self):
            return "test-token"

    client = client_module.DocuSignClient(
        auth=FakeAuth(),
        base_url="https://example.test",
        account_id="account-1",
        http=http,
        max_attempts=3,
    )

    try:
        result = client.get("/envelopes/env-1/recipients")

        assert result == {"signers": [{"recipientId": "1"}]}
        assert len(attempts) == 2
        assert len(sleeps) == 1
        assert 2 <= sleeps[0] <= 2.5
    finally:
        client.close()


def test_recipients_retries_503_then_succeeds(monkeypatch):
    """A temporary 503 response should be retried."""
    attempts = []
    sleeps = []

    def handler(request):
        attempts.append(request)

        if len(attempts) == 1:
            return httpx.Response(
                503,
                json={"message": "Service unavailable"},
            )

        return httpx.Response(
            200,
            json={"signers": [{"recipientId": "1"}]},
        )

    real_retry_call = client_module.retry_call

    def retry_with_recorded_sleep(func, *args, **kwargs):
        kwargs["sleep"] = sleeps.append
        kwargs["base_delay"] = 0
        return real_retry_call(func, *args, **kwargs)

    monkeypatch.setattr(
        client_module, "retry_call", retry_with_recorded_sleep
    )

    http = httpx.Client(transport=httpx.MockTransport(handler))

    class FakeAuth:
        def get_access_token(self):
            return "test-token"

    client = client_module.DocuSignClient(
        auth=FakeAuth(),
        base_url="https://example.test",
        account_id="account-1",
        http=http,
        max_attempts=3,
    )

    try:
        result = client.get("/envelopes/env-1/recipients")

        assert result == {"signers": [{"recipientId": "1"}]}
        assert len(attempts) == 2
        assert len(sleeps) == 1
    finally:
        client.close()
