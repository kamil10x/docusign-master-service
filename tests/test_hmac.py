import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.core.hmac_auth import compute_signature, verify_hmac


@pytest.fixture(autouse=True)
def _hmac_settings(monkeypatch):
    monkeypatch.setattr(settings, "HMAC_ENABLED", True)
    monkeypatch.setattr(settings, "HMAC_SECRET_KEY_CORE", "core-secret")
    monkeypatch.setattr(settings, "HMAC_SECRET_KEY_ENGINEER", "eng-secret")
    monkeypatch.setattr(settings, "HMAC_SIGNATURE_MAX_AGE", 300)


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/open")
    def open_route():
        return {"ok": True}

    @app.post("/secure", dependencies=[Depends(verify_hmac)])
    def secure_route(payload: dict):
        return {"ok": True}

    return TestClient(app)


def signed_headers(secret="core-secret", key_id="core", ts=None, body=b'{"a":1}', method="POST", path="/secure"):
    ts = str(ts if ts is not None else int(time.time()))
    return {
        "X-Key-Id": key_id,
        "X-Timestamp": ts,
        "X-Signature": compute_signature(secret, ts, method, path, body),
        "Content-Type": "application/json",
    }


def test_open_route_needs_no_auth(client):
    assert client.get("/open").status_code == 200


def test_valid_signature_passes(client):
    assert client.post("/secure", content=b'{"a":1}', headers=signed_headers()).status_code == 200


def test_both_keys_work(client):
    h = signed_headers(secret="eng-secret", key_id="engineer")
    assert client.post("/secure", content=b'{"a":1}', headers=h).status_code == 200


def test_missing_headers_rejected(client):
    assert client.post("/secure", json={"a": 1}).status_code == 401


def test_wrong_secret_rejected(client):
    h = signed_headers(secret="wrong")
    assert client.post("/secure", content=b'{"a":1}', headers=h).status_code == 401


def test_tampered_body_rejected(client):
    h = signed_headers(body=b'{"a":1}')
    assert client.post("/secure", content=b'{"a":2}', headers=h).status_code == 401


def test_expired_timestamp_rejected(client):
    h = signed_headers(ts=int(time.time()) - 1000)
    assert client.post("/secure", content=b'{"a":1}', headers=h).status_code == 401


def test_unknown_key_id_rejected(client):
    h = signed_headers(key_id="hacker")
    assert client.post("/secure", content=b'{"a":1}', headers=h).status_code == 401