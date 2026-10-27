import time

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.core import config
from app.core.hmac_auth import compute_signature
from app.docusign.auth_client import (
    ConsentRequiredError,
    DocuSignAuthClient,
    DocuSignAuthError,
)

TOKEN_URL = "https://account-d.docusign.com/oauth/token"
USERINFO_URL = "https://account-d.docusign.com/oauth/userinfo"


@pytest.fixture(scope="module")
def private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()


class FakeClock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def make_client(pem, clock=None):
    return DocuSignAuthClient(
        integration_key="ik-123",
        user_id="user-guid",
        private_key=pem,
        clock=clock or time.time,
    )


USERINFO_BODY = {
    "accounts": [
        {"account_id": "other", "is_default": False, "base_uri": "https://na9.docusign.net"},
        {
            "account_id": "acc-1",
            "is_default": True,
            "account_name": "Sandbox",
            "base_uri": "https://demo.docusign.net",
        },
    ]
}


# ------------------------------------------------------------ auth client
@pytest.mark.asyncio
@respx.mock
async def test_token_fetch_success(private_key_pem):
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok1", "expires_in": 3600})
    )
    token = await make_client(private_key_pem).get_access_token()
    assert token == "tok1"
    sent = route.calls.last.request.content.decode()
    assert "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer" in sent
    assert "assertion=" in sent


@pytest.mark.asyncio
@respx.mock
async def test_token_cache_hit(private_key_pem):
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok1", "expires_in": 3600})
    )
    client = make_client(private_key_pem)
    assert await client.get_access_token() == "tok1"
    assert await client.get_access_token() == "tok1"
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_token_refreshes_near_expiry(private_key_pem):
    route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "tok1", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "tok2", "expires_in": 3600}),
        ]
    )
    clock = FakeClock()
    client = make_client(private_key_pem, clock)
    assert await client.get_access_token() == "tok1"
    clock.now += 3600 - 60  # inside the 5-minute refresh margin
    assert await client.get_access_token() == "tok2"
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_consent_required(private_key_pem):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "consent_required"})
    )
    with pytest.raises(ConsentRequiredError):
        await make_client(private_key_pem).get_access_token()


@pytest.mark.asyncio
@respx.mock
async def test_invalid_grant_raises_auth_error(private_key_pem):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "bad user"}
        )
    )
    with pytest.raises(DocuSignAuthError) as exc:
        await make_client(private_key_pem).get_access_token()
    assert "invalid_grant" in str(exc.value)


@pytest.mark.asyncio
async def test_missing_credentials():
    client = DocuSignAuthClient("", "", "")
    with pytest.raises(DocuSignAuthError):
        await client.get_access_token()


@pytest.mark.asyncio
@respx.mock
async def test_account_info_picks_default(private_key_pem):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok1", "expires_in": 3600})
    )
    respx.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=USERINFO_BODY))
    info = await make_client(private_key_pem).get_account_info()
    assert info.account_id == "acc-1"
    assert info.base_uri == "https://demo.docusign.net"
    assert info.api_base_url == "https://demo.docusign.net/restapi/v2.1/accounts/acc-1"


# ---------------------------------------------------- HMAC + route (API)
@pytest.fixture
def api_client(monkeypatch, private_key_pem):
    monkeypatch.setenv("HMAC_SECRET_KEY_CORE", "s3cret")
    monkeypatch.setenv("DOCUSIGN_INTEGRATION_KEY", "ik-123")
    monkeypatch.setenv("DOCUSIGN_USER_ID", "user-guid")
    monkeypatch.setenv("DOCUSIGN_PRIVATE_KEY", private_key_pem)
    config.get_settings.cache_clear()
    from app.main import app

    yield TestClient(app)
    config.get_settings.cache_clear()


def signed_headers(method, path, body=b"", secret="s3cret", ts=None):
    ts = str(ts if ts is not None else int(time.time()))

    return {
        "X-Key-Id": "core",
        "X-Timestamp": ts,
        "X-Signature": compute_signature(
            secret,
            ts,
            method,
            path,
            body,
        ),
    }


def test_health_is_open(api_client):
    assert api_client.get("/api/health").status_code == 200


def test_missing_signature_rejected(api_client):
    assert api_client.post("/api/validate-credentials").status_code == 401


def test_bad_signature_rejected(api_client):
    headers = signed_headers("POST", "/api/validate-credentials", secret="wrong")
    assert api_client.post("/api/validate-credentials", headers=headers).status_code == 401


def test_stale_timestamp_rejected(api_client):
    headers = signed_headers("POST", "/api/validate-credentials", ts=int(time.time()) - 3600)
    assert api_client.post("/api/validate-credentials", headers=headers).status_code == 401


@respx.mock
def test_validate_credentials_success(api_client):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok1", "expires_in": 3600})
    )
    respx.get(USERINFO_URL).mock(return_value=httpx.Response(200, json=USERINFO_BODY))
    headers = signed_headers("POST", "/api/validate-credentials")
    resp = api_client.post("/api/validate-credentials", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["valid"] is True
    assert resp.json()["account_id"] == "acc-1"


@respx.mock
def test_validate_credentials_consent_required(api_client):
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "consent_required"})
    )
    headers = signed_headers("POST", "/api/validate-credentials")
    resp = api_client.post("/api/validate-credentials", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert resp.json()["error"] == "consent_required"