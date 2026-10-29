
from app.core.config import get_settings
from app.docusign.auth_client import auth_client
from app.docusign.client import DocuSignClient
from app.docusign.envelopes import (
    get_envelope_recipients,
    get_envelope_documents,
)
from app.docusign.templates import iter_templates


# Existing sandbox envelope IDs from your verification scripts.
ENVELOPE_IDS = [
    "a69b2fc7-e174-8732-8198-7695aea41bda",
    "45d72d11-439d-8fd4-81de-cc8741af1b3d",
    "eba92921-8c70-865f-800e-8107ebaa1b5e",
    "a7dd2959-06ab-8528-8007-5fb5caa81b8e",
    "77042f80-d085-86de-8041-e3e654ad1b93",
    "d2d22486-427d-820e-8137-5eb591ad1bf0",
]


def main():
    settings = get_settings()

    passed = 0
    failed = 0

    with DocuSignClient(
        auth=auth_client,
        base_url=settings.docusign_base_url,
        account_id=settings.docusign_account_id,
    ) as client:

        # Test 1: Recipients and documents for a real envelope.
        for envelope_id in ENVELOPE_IDS:
            print(f"\n=== Envelope: {envelope_id} ===")

            try:
                recipients = get_envelope_recipients(client, envelope_id)
                recipient_count = sum(
                    len(value)
                    for key, value in recipients.items()
                    if isinstance(value, list)
                )
                print(f"PASS: Recipients endpoint ({recipient_count} entries)")
                passed += 1
            except Exception as exc:
                print(f"FAIL: Recipients endpoint ({type(exc).__name__}: {exc})")
                failed += 1

            try:
                documents = get_envelope_documents(client, envelope_id)
                envelope_documents = documents.get("envelopeDocuments", [])
                print(
                    "PASS: Documents endpoint "
                    f"({len(envelope_documents)} documents)"
                )
                passed += 1
            except Exception as exc:
                print(f"FAIL: Documents endpoint ({type(exc).__name__}: {exc})")
                failed += 1

        # Test 2: Template listing and pagination.
        print("\n=== Template listing and pagination ===")

        try:
            template_count = 0

            for template in iter_templates(client, page_size=2):
                template_count += 1
                print(
                    f"Template {template_count}: "
                    f"{template.get('name', '(unnamed)')} "
                    f"[{template.get('templateId', 'no ID')}]"
                )

            print(f"PASS: Template iteration ({template_count} templates)")
            passed += 1
        except Exception as exc:
            print(f"FAIL: Template iteration ({type(exc).__name__}: {exc})")
            failed += 1

    print("\n=== Smoke-test summary ===")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
