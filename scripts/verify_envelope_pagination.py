
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.docusign.auth_client import auth_client
from app.docusign.client import DocuSignClient
from app.docusign.envelopes import list_envelopes, iter_envelope_pages


EXPECTED_IDS = {
    "a69b2fc7-e174-8732-8198-7695aea41bda",
    "45d72d11-439d-8fd4-81de-cc8741af1b3d",
    "eba92921-8c70-865f-800e-8107ebaa1b5e",
    "a7dd2959-06ab-8528-8007-5fb5caa81b8e",
    "77042f80-d085-86de-8041-e3e654ad1b93",
    "d2d22486-427d-820e-8137-5eb591ad1bf0",
}


def main():
    settings = get_settings()

    # Search the last 7 days, through tomorrow, in UTC.
    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=7)
    to_date = now + timedelta(days=1)

    print(f"Date range: {from_date.isoformat()} to {to_date.isoformat()}")

    with DocuSignClient(
        auth=auth_client,
        base_url=settings.docusign_base_url,
        account_id=settings.docusign_account_id,
    ) as client:

        # Test 1: Date-range listing
        print("\n=== Test 1: Date-range listing ===")

        first_page = list_envelopes(
            client,
            from_date=from_date,
            to_date=to_date,
            start_position=0,
            count=100,
        )

        first_page_ids = {
            item["envelopeId"]
            for item in first_page.get("envelopes", [])
        }

        print("First-page results:", len(first_page_ids))
        print("DocuSign totalSetSize:", first_page.get("totalSetSize"))

        # Test 2: Offset pagination
        print("\n=== Test 2: Pagination (page_size=2) ===")

        retrieved_ids = []
        page_count = 0

        for page in iter_envelope_pages(
            client,
            from_date=from_date,
            to_date=to_date,
            page_size=2,
        ):
            page_count += 1
            envelopes = page.get("envelopes", [])
            page_ids = [item["envelopeId"] for item in envelopes]
            retrieved_ids.extend(page_ids)

            print(f"Page {page_count}: {len(page_ids)} envelopes")
            for envelope_id in page_ids:
                print("  ", envelope_id)

        retrieved_set = set(retrieved_ids)
        duplicates = len(retrieved_ids) - len(retrieved_set)
        missing = EXPECTED_IDS - retrieved_set

        print("\n=== Verification summary ===")
        print("Pages fetched:", page_count)
        print("Total envelopes retrieved:", len(retrieved_ids))
        print("Unique envelopes:", len(retrieved_set))
        print("Duplicate results:", duplicates)
        print("Expected test envelopes found:",
              len(EXPECTED_IDS & retrieved_set), "/ 6")

        if missing:
            print("Expected IDs not found in date range:")
            for envelope_id in sorted(missing):
                print("  ", envelope_id)
        else:
            print("All six expected test envelopes were found.")

        if duplicates == 0 and not missing:
            print("\nPASS: All six expected envelopes found without duplicates.")
        else:
            print("\nCHECK: Investigate the missing IDs or duplicate results.")


if __name__ == "__main__":
    main()
