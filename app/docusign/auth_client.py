import threading
import time
from pathlib import Path

import httpx
import jwt

from app.config import settings

TOKEN_REFRESH_BUFFER_SECONDS = 300  # refresh 5 min before expiry


class DocuSignAuthError(Exception):
    pass


class DocuSignAuthClient:
    def __init__(self):
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._lock = threading.Lock()

    def _build_assertion(self) -> str:
        private_key = Path(settings.docusign_private_key_path).read_text()
        now = int(time.time())
        payload = {
            "iss": settings.docusign_integration_key,
            "sub": settings.docusign_user_id,
            "aud": settings.docusign_auth_server,
            "iat": now,
            "exp": now + 3600,
            "scope": "signature impersonation",
        }
        return jwt.encode(payload, private_key, algorithm="RS256")

    def _request_token(self) -> None:
        resp = httpx.post(
            f"https://{settings.docusign_auth_server}/oauth/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": self._build_assertion(),
            },
            timeout=15,
        )
        if resp.status_code != 200:
            raise DocuSignAuthError(f"Token request failed ({resp.status_code}): {resp.text}")
        data = resp.json()
        self._token = data["access_token"]
        self._expires_at = time.time() + data["expires_in"]

    def get_access_token(self) -> str:
        with self._lock:
            if self._token is None or time.time() >= self._expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
                self._request_token()
            return self._token


auth_client = DocuSignAuthClient()