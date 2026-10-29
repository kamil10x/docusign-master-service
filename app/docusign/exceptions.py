from __future__ import annotations


class DocuSignAPIError(Exception):
    """Any failed DocuSign call. status_code is None for network errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        endpoint: str | None = None,
        envelope_id: str | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.envelope_id = envelope_id
        self.body = body


class DocuSignNotFoundError(DocuSignAPIError):
    """404: envelope or resource doesn't exist. Not retryable."""


class DocuSignRateLimitError(DocuSignAPIError):
    """429: retryable. retry_after is in seconds, if DocuSign sent it."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kw) -> None:
        super().__init__(message, status_code=429, **kw)
        self.retry_after = retry_after