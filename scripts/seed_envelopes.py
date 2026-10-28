"""Create 6 varied test envelopes in the DocuSign sandbox. Run: python -m scripts.seed_envelopes"""
import base64
import os

from app.docusign.client import DocuSignClient
# ADAPT 1: import your real auth client
from app.docusign.auth_client import auth_client
from app.core.config import get_settings

TEXT = "Test agreement #{n} / doc {d}\n\nSigned: /sig/\n"


def build(n: int, signers: int, docs: int, status: str = "sent") -> dict:
    return {
        "emailSubject": f"Test envelope {n}",
        "status": status,  # "sent" or "created" (draft)
        "documents": [
            {
                "documentId": str(d),
                "name": f"Test doc {n}-{d}",
                "fileExtension": "txt",
                "documentBase64": base64.b64encode(TEXT.format(n=n, d=d).encode()).decode(),
            }
            for d in range(1, docs + 1)
        ],
        "recipients": {
            "signers": [
                {
                    "email": f"seed{n}.{s}@example.com",
                    "name": f"Seed Signer {n}-{s}",
                    "recipientId": str(s),
                    "routingOrder": str(s),
                    "tabs": {"signHereTabs": [{"anchorString": "/sig/", "anchorUnitsXOffset": "20"}]},
                }
                for s in range(1, signers + 1)
            ]
        },
    }


PLAN = [  # (signers, docs, status)
    (1, 1, "sent"),
    (1, 1, "sent"),
    (2, 1, "sent"),
    (2, 1, "sent"),
    (1, 2, "sent"),   # multi-document
    (1, 1, "created"),  # draft
]


if __name__ == "__main__":
    settings = get_settings()

    client = DocuSignClient(
        auth=auth_client,
        base_url=settings.docusign_base_url,
        account_id=settings.docusign_account_id,
    )

    with client:
        for i, (signers, docs, status) in enumerate(PLAN, 1):
            res = client.post(
                "/envelopes",
                json=build(i, signers, docs, status),
            )
            print(i, res.get("envelopeId"), res.get("status"))
