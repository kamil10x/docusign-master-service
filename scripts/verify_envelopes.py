
from app.core.config import get_settings
from app.docusign.auth_client import auth_client
from app.docusign.client import DocuSignClient

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
    results = []

    with DocuSignClient(
        auth=auth_client,
        base_url=settings.docusign_base_url,
        account_id=settings.docusign_account_id,
    ) as client:
        for envelope_id in ENVELOPE_IDS:
            try:
                envelope = client.get(f"/envelopes/{envelope_id}")
                result = {
                    "envelopeId": envelope.get("envelopeId"),
                    "status": envelope.get("status"),
                    "emailSubject": envelope.get("emailSubject"),
                }
                results.append(result)
                print(
                    f"FOUND | {result['envelopeId']} | "
                    f"{result['status']} | {result['emailSubject']}"
                )
            except Exception as exc:
                print(f"FAILED | {envelope_id} | {exc}")

    print(f"\nVerified: {len(results)}/{len(ENVELOPE_IDS)}")
    print("Expected statuses: five sent, one created.")


if __name__ == "__main__":
    main()
