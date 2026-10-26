"""DocuSign JWT Grant authentication with in-memory token caching."""
import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlencode

import httpx
import jwt  # PyJWT

JWT_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:jwt-bearer"
SCOPES = "signature impersonation"
JWT_LIFETIME_SECONDS = 3600  # DocuSign max is 1 hour
REFRESH_MARGIN_SECONDS = 300  # refresh 5 minutes before expiry
DEFAULT_CONSENT_REDIRECT_URI = "https://developers.docusign.com/platform/auth/consent"


class DocuSignAuthError(Exception):
    """Raised when we cannot obtain or use a DocuSign access token."""


class ConsentRequiredError(DocuSignAuthError):
    """User has not granted consent to the Integration Key."""

    def __init__(self, message: str, consent_url: Optional[str] = None):
        super().__init__(message)
        self.consent_url = consent_url


@dataclass
class AccountInfo:
    account_id: str
    base_uri: str  # e.g. https://demo.docusign.net
    account_name: str = ""

    @property
    def api_base_url(self) -> str:
        return f"{self.base_uri.rstrip('/')}/restapi/v2.1/accounts/{self.account_id}"


class DocuSignAuthClient:
    def __init__(
        self,
        integration_key: str,
        user_id: str,
        private_key: str,
        auth_host: str = "account-d.docusign.com",
        http_client: Optional[httpx.AsyncClient] = None,
        clock: Callable[[], float] = time.time,
    ):
        self._integration_key = integration_key
        self._user_id = user_id
        # Normalize escaped newlines in case key was loaded from a single-line env var
        self._private_key = private_key.replace("\\n", "\n").strip() if private_key else ""
        self._auth_host = auth_host
        self._http = http_client
        self._clock = clock

        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._account: Optional[AccountInfo] = None

        self._token_lock = asyncio.Lock()
        self._account_lock = asyncio.Lock()

    # ------------------------------------------------------------------ JWT
    def _build_assertion(self) -> str:
        if not (self._integration_key and self._user_id and self._private_key):
            raise DocuSignAuthError(
                "Missing DocuSign credentials (integration key, user id, or private key)"
            )
        now = int(self._clock())
        claims = {
            "iss": self._integration_key,
            "sub": self._user_id,
            "aud": self._auth_host,
            "iat": now,
            "exp": now + JWT_LIFETIME_SECONDS,
            "scope": SCOPES,
        }
        try:
            return jwt.encode(claims, self._private_key, algorithm="RS256")
        except Exception as exc:  # bad key format etc.
            raise DocuSignAuthError(f"Could not sign JWT assertion: {exc}") from exc

    def build_consent_url(
        self, redirect_uri: str = DEFAULT_CONSENT_REDIRECT_URI
    ) -> str:
        params = urlencode(
            {
                "response_type": "code",
                "scope": SCOPES,
                "client_id": self._integration_key,
                "redirect_uri": redirect_uri,
            }
        )
        return f"https://{self._auth_host}/oauth/auth?{params}"

    # ---------------------------------------------------------------- token
    def _token_is_valid(self) -> bool:
        return (
            self._token is not None
            and self._clock() < (self._token_expires_at - REFRESH_MARGIN_SECONDS)
        )

    async def get_access_token(self, force_refresh: bool = False) -> str:
        """Return a cached access token, fetching a new one when needed."""
        if not force_refresh and self._token_is_valid():
            return self._token  # type: ignore[return-value]

        async with self._token_lock:
            # Re-check after acquiring lock in case another coroutine just refreshed it
            if not force_refresh and self._token_is_valid():
                return self._token  # type: ignore[return-value]

            assertion = self._build_assertion()
            url = f"https://{self._auth_host}/oauth/token"
            data = {"grant_type": JWT_GRANT_TYPE, "assertion": assertion}

            resp = await self._post(url, data)

            if resp.status_code != 200:
                self._raise_for_token_error(resp)

            try:
                body = resp.json()
                token = body["access_token"]
            except (ValueError, KeyError) as exc:
                raise DocuSignAuthError(
                    f"Malformed token response from DocuSign: {resp.text}"
                ) from exc

            self._token = token
            self._token_expires_at = self._clock() + int(body.get("expires_in", 3600))
            return self._token

    def _raise_for_token_error(self, resp: httpx.Response) -> None:
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        error = payload.get("error", "")
        description = payload.get("error_description", resp.text)
        if error == "consent_required":
            consent_url = self.build_consent_url()
            raise ConsentRequiredError(
                f"Consent required: open {consent_url} for this Integration Key "
                "and user, grant consent, then retry.",
                consent_url=consent_url,
            )
        raise DocuSignAuthError(
            f"Token request failed ({resp.status_code}): {error} {description}".strip()
        )

    # ------------------------------------------------------------- userinfo
    async def get_account_info(self, force_refresh: bool = False) -> AccountInfo:
        """Return account_id and base_uri for the default account (cached)."""
        if self._account is not None and not force_refresh:
            return self._account

        async with self._account_lock:
            if self._account is not None and not force_refresh:
                return self._account

            token = await self.get_access_token(force_refresh=force_refresh)
            url = f"https://{self._auth_host}/oauth/userinfo"
            resp = await self._get(url, headers={"Authorization": f"Bearer {token}"})
            if resp.status_code != 200:
                raise DocuSignAuthError(
                    f"userinfo request failed ({resp.status_code}): {resp.text}"
                )

            try:
                accounts = resp.json().get("accounts", [])
            except ValueError as exc:
                raise DocuSignAuthError(
                    f"Malformed userinfo response from DocuSign: {resp.text}"
                ) from exc

            if not accounts:
                raise DocuSignAuthError("userinfo returned no accounts for this user")

            chosen = next((a for a in accounts if a.get("is_default")), accounts[0])
            self._account = AccountInfo(
                account_id=chosen["account_id"],
                base_uri=chosen["base_uri"],
                account_name=chosen.get("account_name", ""),
            )
            return self._account

    # ----------------------------------------------------------------- http
    async def _post(self, url: str, data: dict) -> httpx.Response:
        try:
            if self._http is not None:
                return await self._http.post(url, data=data)
            async with httpx.AsyncClient(timeout=30) as client:
                return await client.post(url, data=data)
        except httpx.HTTPError as exc:
            raise DocuSignAuthError(f"Network error calling DocuSign: {exc}") from exc

    async def _get(self, url: str, headers: dict) -> httpx.Response:
        try:
            if self._http is not None:
                return await self._http.get(url, headers=headers)
            async with httpx.AsyncClient(timeout=30) as client:
                return await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise DocuSignAuthError(f"Network error calling DocuSign: {exc}") from exc
        
from app.core.config import get_settings


_settings = get_settings()

auth_client = DocuSignAuthClient(
    integration_key=_settings.docusign_integration_key,
    user_id=_settings.docusign_user_id,
    private_key=_settings.docusign_private_key,
    auth_host=_settings.docusign_auth_host,
)