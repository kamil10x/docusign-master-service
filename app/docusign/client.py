
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.docusign.exceptions import (
    DocuSignAPIError,
    DocuSignNotFoundError,
    DocuSignRateLimitError,
)
from app.utils.rate_limiter import RateLimiter, RateLimitError
from app.utils.retry import retry_call


class DocuSignClient:
    """Authenticated, rate-limited, retrying synchronous DocuSign client."""

    def __init__(
        self,
        auth,
        base_url: str,
        account_id: str,
        limiter: RateLimiter | None = None,
        timeout: float = 30.0,
        max_attempts: int = 5,
        http: httpx.Client | None = None,
    ):
        self._auth = auth
        self._root = (
            f"{base_url.rstrip('/')}/restapi/v2.1/accounts/{account_id}"
        )
        self._limiter = limiter or RateLimiter()
        self._max_attempts = max_attempts
        self._http = http or httpx.Client(timeout=timeout)

    @staticmethod
    def _envelope_id(path: str) -> str | None:
        parts = path.strip("/").split("/")
        try:
            index = parts.index("envelopes")
            return parts[index + 1]
        except (ValueError, IndexError):
            return None

    def _send(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json: Any = None,
    ) -> dict:
        self._limiter.before_request()

        token = self._auth.get_access_token()
        if asyncio.iscoroutine(token):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                token = asyncio.run(token)
            else:
                token.close()
                raise RuntimeError(
                    "Synchronous DocuSignClient cannot be called "
                    "from a running asyncio event loop."
                )

        response = self._http.request(
            method,
            f"{self._root}{path}",
            params=params,
            json=json,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )

        # Updates rate-limit headers and converts HTTP 429 into RateLimitError,
        # which retry_call already recognizes and retries using Retry-After.
        self._limiter.check_response(response)
        response.raise_for_status()

        return response.json() if response.content else {}

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
    ) -> dict:
        envelope_id = self._envelope_id(path)

        try:
            return retry_call(
                self._send,
                method,
                path,
                params,
                json,
                max_attempts=self._max_attempts,
            )
        except RateLimitError as exc:
            raise DocuSignRateLimitError(
                f"DocuSign rate limit exhausted for {path}",
                retry_after=exc.retry_after,
                endpoint=path,
                envelope_id=envelope_id,
            ) from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text

            if status == 404:
                raise DocuSignNotFoundError(
                    f"DocuSign resource not found at {path}",
                    status_code=status,
                    endpoint=path,
                    envelope_id=envelope_id,
                    body=body,
                ) from exc

            raise DocuSignAPIError(
                f"DocuSign returned HTTP {status} for {path}",
                status_code=status,
                endpoint=path,
                envelope_id=envelope_id,
                body=body,
            ) from exc
        except httpx.TransportError as exc:
            raise DocuSignAPIError(
                f"Network error calling {path}: {exc}",
                endpoint=path,
                envelope_id=envelope_id,
            ) from exc

    def get(self, path: str, params: dict | None = None) -> dict:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any) -> dict:
        return self.request("POST", path, json=json)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> DocuSignClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
