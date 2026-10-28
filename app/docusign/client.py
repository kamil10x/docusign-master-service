from __future__ import annotations

from typing import Any

import httpx
import asyncio


from app.utils.rate_limiter import RateLimiter
from app.utils.retry import retry_call


class DocuSignClient:
    """Authenticated, rate-limited, retrying client for the eSignature REST API."""

    def __init__(
        self,
        auth,                     # needs .get_access_token() -> str
        base_url: str,            # e.g. https://demo.docusign.net
        account_id: str,
        limiter: RateLimiter | None = None,
        timeout: float = 30.0,
        max_attempts: int = 5,
        http: httpx.Client | None = None,
    ):
        self._auth = auth
        self._root = f"{base_url.rstrip('/')}/restapi/v2.1/accounts/{account_id}"
        self._limiter = limiter or RateLimiter()
        self._max_attempts = max_attempts
        self._http = http or httpx.Client(timeout=timeout)

    def _send(self, method: str, path: str, params: dict | None, json: Any) -> dict:
        self._limiter.before_request()

        token = self._auth.get_access_token()

        # Support both synchronous and asynchronous auth clients.
        if asyncio.iscoroutine(token):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                token = asyncio.run(token)
            else:
                token.close()
                raise RuntimeError(
                    "DocuSignClient is synchronous and cannot be called "
                    "from a running asyncio event loop."
                )

        resp = self._http.request(
            method,
            f"{self._root}{path}",
            params=params,
            json=json,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

        self._limiter.check_response(resp)
        resp.raise_for_status()
        return resp.json() if resp.content else {}


    def request(self, method: str, path: str, *, params: dict | None = None, json: Any = None) -> dict:
        return retry_call(self._send, method, path, params, json, max_attempts=self._max_attempts)

    def get(self, path: str, params: dict | None = None) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any) -> dict:
        return self.request("POST", path, json=json)

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()