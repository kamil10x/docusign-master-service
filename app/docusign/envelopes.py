from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator

from app.docusign.client import DocuSignClient


def _iso(value: datetime | str) -> str:
    if isinstance(value, str):
        return value

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_envelopes(
    client: DocuSignClient,
    from_date: datetime | str,
    to_date: datetime | str | None = None,
    start_position: int = 0,
    count: int = 100,
    status: str | None = None,
) -> dict[str, Any]:
    """Fetch one page of envelopes (maximum count is 1000)."""
    params: dict[str, Any] = {
        "from_date": _iso(from_date),
        "start_position": start_position,
        "count": count,
        # Stable ordering for offset-based pagination.
        "order_by": "last_modified",
        "order": "asc",
    }

    if to_date is not None:
        params["to_date"] = _iso(to_date)

    if status:
        params["status"] = status

    return client.get("/envelopes", params=params)


def iter_envelope_pages(
    client: DocuSignClient,
    from_date: datetime | str,
    to_date: datetime | str | None = None,
    page_size: int = 100,
    start_position: int = 0,
    status: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield raw envelope pages until all results are exhausted."""
    start = start_position

    while True:
        page = list_envelopes(
            client=client,
            from_date=from_date,
            to_date=to_date,
            start_position=start,
            count=page_size,
            status=status,
        )

        yield page

        size = int(page.get("resultSetSize", 0))
        total = int(page.get("totalSetSize", 0))

        start += size

        if size == 0 or start >= total:
            break


def iter_envelopes(
    client: DocuSignClient,
    *args: Any,
    **kwargs: Any,
) -> Iterator[dict[str, Any]]:
    """Yield individual envelopes instead of raw pages."""
    for page in iter_envelope_pages(client, *args, **kwargs):
        yield from page.get("envelopes", [])
