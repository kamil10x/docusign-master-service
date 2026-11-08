
"""Day 17: DocumentNormalizer - one row per envelope document."""

from typing import Any

from app.normalizers.base import Normalizer, safe_get


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class DocumentNormalizer(Normalizer):
    table_name = "documents"

    def normalize(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Normalize documents belonging to multiple envelopes."""

        rows: list[dict[str, Any]] = []

        for raw in records:
            if not isinstance(raw, dict):
                continue

            envelope_id = safe_get(raw, "envelopeId")

            documents = raw.get("envelopeDocuments") or []

            if not isinstance(documents, list):
                continue

            for document in documents:
                if not isinstance(document, dict):
                    continue

                document_id = safe_get(document, "documentId")

                # Document ID is required for identification.
                if not document_id:
                    continue

                rows.append({
                    "envelope_id": envelope_id,
                    "document_id": str(document_id),
                    "name": safe_get(document, "name"),
                    "type": safe_get(document, "type"),
                    "pages": _to_int(safe_get(document, "pages")),
                    "order": _to_int(safe_get(document, "order")),
                })

        return {self.table_name: rows}
