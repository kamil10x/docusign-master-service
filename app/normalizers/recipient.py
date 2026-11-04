
"""Day 16: RecipientNormalizer - one row per recipient, any recipient type."""

from typing import Any

from app.normalizers.base import Normalizer, parse_dt, safe_get


# DocuSign response key -> recipient_type stored in the table
RECIPIENT_TYPES = {
    "signers": "signer",
    "carbonCopies": "carbon_copy",
    "certifiedDeliveries": "certified_delivery",
    "agents": "agent",
    "editors": "editor",
    "intermediaries": "intermediary",
    "inPersonSigners": "in_person_signer",
    "seals": "seal",
    "witnesses": "witness",
    "notaries": "notary",
}


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RecipientNormalizer(Normalizer):
    table_name = "recipients"

    def normalize(
        self, records: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Normalize recipient responses from multiple envelopes."""

        rows: list[dict[str, Any]] = []

        for raw in records:
            if not isinstance(raw, dict):
                continue

            envelope_id = safe_get(raw, "envelopeId")

            for key, recipient_type in RECIPIENT_TYPES.items():
                recipients = raw.get(key) or []

                if not isinstance(recipients, list):
                    continue

                for recipient in recipients:
                    if not isinstance(recipient, dict):
                        continue

                    rows.append({
                        "envelope_id": envelope_id,
                        "recipient_id": safe_get(recipient, "recipientId"),
                        "recipient_type": recipient_type,
                        "name": safe_get(recipient, "name"),
                        "email": safe_get(recipient, "email"),
                        "status": safe_get(recipient, "status"),
                        "routing_order": _to_int(
                            safe_get(recipient, "routingOrder")
                        ),
                        "sent_at": parse_dt(
                            safe_get(recipient, "sentDateTime")
                        ),
                        "delivered_at": parse_dt(
                            safe_get(recipient, "deliveredDateTime")
                        ),
                        "signed_at": parse_dt(
                            safe_get(recipient, "signedDateTime")
                        ),
                        "declined_at": parse_dt(
                            safe_get(recipient, "declinedDateTime")
                        ),
                        "declined_reason": safe_get(
                            recipient, "declinedReason"
                        ),
                    })

        return {self.table_name: rows}
