"""Day 15: EnvelopeNormalizer - one normalized row per envelope."""
from typing import Any

from app.normalizers.base import Normalizer, parse_dt, safe_get

def flatten_custom_fields(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Merge text and list custom fields into a flat dictionary.

    Example:
        {
            "textCustomFields": [
                {"name": "Department", "value": "Engineering"}
            ]
        }

    Output:
        {"Department": "Engineering"}
    """
    custom_fields = safe_get(raw, "customFields", default={})

    if not isinstance(custom_fields, dict):
        return {}

    flattened: dict[str, Any] = {}

    for key in ("textCustomFields", "listCustomFields"):
        fields = custom_fields.get(key) or []

        if not isinstance(fields, list):
            continue

        for field in fields:
            if not isinstance(field, dict):
                continue

            name = field.get("name")

            if name:
                flattened[str(name)] = field.get("value")

    return flattened


class EnvelopeNormalizer(Normalizer):
    """Normalize DocuSign envelope records."""

    table_name = "envelopes"

    def normalize(
        self,
        records: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:

        normalized: list[dict[str, Any]] = []

        for raw in records:
            if not isinstance(raw, dict):
                continue

            envelope_id = safe_get(raw, "envelopeId")

            # Envelope ID is required for record identification.
            if not envelope_id:
                continue

            row = {
                "envelope_id": str(envelope_id),
                "status": safe_get(raw, "status"),
                "email_subject": safe_get(raw, "emailSubject"),

                # Envelope timestamps
                "created_at": parse_dt(
                    safe_get(raw, "createdDateTime")
                ),
                "sent_at": parse_dt(
                    safe_get(raw, "sentDateTime")
                ),
                "delivered_at": parse_dt(
                    safe_get(raw, "deliveredDateTime")
                ),
                "completed_at": parse_dt(
                    safe_get(raw, "completedDateTime")
                ),
                "voided_at": parse_dt(
                    safe_get(raw, "voidedDateTime")
                ),
                "status_changed_at": parse_dt(
                    safe_get(raw, "statusChangedDateTime")
                ),

                "voided_reason": safe_get(raw, "voidedReason"),

                # Sender details
                "sender_user_id": safe_get(raw, "sender", "userId"),
                "sender_name": safe_get(raw, "sender", "userName"),
                "sender_email": safe_get(raw, "sender", "email"),

                # Flattened custom fields
                "custom_fields": flatten_custom_fields(raw),
            }

            normalized.append(row)

        return {
            self.table_name: normalized
        }
