from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import validate_credentials as vc
from app.db.session import get_db


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code, self._payload, self.text = status_code, payload or {}, text

    def json(self):
        return self._payload


def make_client(monkeypatch, token_ok=True, resp=None):
    calls = {"audit": [], "failed": []}

    class FakeService:
        def __init__(self, db): pass
        def log_audit(self, action, **kw): calls["audit"].append((action, kw))
        def record_failed_call(self, *a, **kw): calls["failed"].append((a, kw))

    def fake_token():
        if not token_ok:
            raise vc.DocuSignAuthError("consent_required")
        return "tok"

    monkeypatch.setattr(vc, "JobService", FakeService)
    monkeypatch.setattr(vc.auth_client, "get_access_token", fake_token)
    monkeypatch.setattr(vc.httpx, "get", lambda *a, **k: resp)

    app = FastAPI()
    app.include_router(vc.router)
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app), calls


def test_valid_credentials(monkeypatch):
    client, calls = make_client(monkeypatch, resp=FakeResp(200, {"accountName": "Sandbox"}))
    body = client.post("/validate-credentials").json()
    assert body["valid"] is True and body["account_name"] == "Sandbox"
    assert calls["audit"][0][1]["details"]["valid"] is True


def test_token_failure(monkeypatch):
    client, calls = make_client(monkeypatch, token_ok=False)
    body = client.post("/validate-credentials").json()
    assert body["valid"] is False and body["stage"] == "token"
    assert len(calls["failed"]) == 1


def test_account_rejected(monkeypatch):
    client, calls = make_client(monkeypatch, resp=FakeResp(401, text="unauthorized"))
    body = client.post("/validate-credentials").json()
    assert body["valid"] is False and body["stage"] == "account"
    assert len(calls["failed"]) == 1