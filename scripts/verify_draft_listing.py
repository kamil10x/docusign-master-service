
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.docusign.auth_client import auth_client
from app.docusign.client import DocuSignClient
from app.docusign.envelopes import list_envelopes

DRAFT_ID = "d2d22486-427d-820e-8137-5eb591ad1bf0"


def main():
    settings = get_settings()
    now = datetime.now(timezone.utc)

    with DocuSignClient(
        auth=auth_client,
        base_url=settings.docusign_base_url,
        account_id=settings.docusign_account_id,
    ) as client:
        for status in ("created", None):
            page = list_envelopes(
                client,
                from_date=now - timedelta(days=30),
                to_date=now + timedelta(days=1),
                count=100,
                status=status,
            )

            envelopes = page.get("envelopes", [])
            found = [
                e for e in envelopes
                if e.get("envelopeId") == DRAFT_ID
            ]

            print(f"\nStatus filter: {status!r}")
            print("Total reported:", page.get("totalSetSize"))
            print("Returned:", len(envelopes))
            print("Draft found:", bool(found))

            for envelope in found:
                print("ID:", envelope.get("envelopeId"))
                print("Status:", envelope.get("status"))


if __name__ == "__main__":
    main()
