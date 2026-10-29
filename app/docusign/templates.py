
from __future__ import annotations

from typing import Any, Iterator

from app.docusign.client import DocuSignClient


def list_templates(
    client: DocuSignClient,
    start_position: int = 0,
    count: int = 100,
) -> dict[str, Any]:
    """Fetch one page of DocuSign templates."""
    return client.get(
        "/templates",
        params={
            "start_position": start_position,
            "count": count,
        },
    )



def iter_template_pages(
    client: DocuSignClient,
    page_size: int = 100,
    start_position: int = 0,
) -> Iterator[dict[str, Any]]:
    """Yield template pages until pagination is exhausted."""
    start = start_position

    while True:
        page = list_templates(
            client,
            start_position=start,
            count=page_size,
        )
        yield page

        templates = page.get("envelopeTemplates") or []
        size = len(templates)

        if size == 0:
            break

        result_size = int(page.get("resultSetSize", size) or 0)
        total = int(page.get("totalSetSize", 0) or 0)
        end_position = page.get("endPosition")
        next_uri = page.get("nextUri")

        if result_size == 0 or not next_uri:
            break

        if end_position is not None and total > 0:
            if int(end_position) + 1 >= total:
                break

        next_start = start + size
        if next_start <= start:
            break

        start = next_start


def iter_templates(
    client: DocuSignClient,
    *args: Any,
    **kwargs: Any,
) -> Iterator[dict[str, Any]]:
    """Yield individual templates across all pages."""
    for page in iter_template_pages(client, *args, **kwargs):
        yield from page.get("envelopeTemplates", [])
