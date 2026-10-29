
from app.core.config import get_settings
from app.docusign.auth_client import auth_client
from app.docusign.client import DocuSignClient


def main():
    settings = get_settings()

    with DocuSignClient(
        auth=auth_client,
        base_url=settings.docusign_base_url,
        account_id=settings.docusign_account_id,
    ) as client:
        response = client.get(
            "/templates",
            params={"start_position": 0, "count": 2},
        )

        print("Response keys:", list(response.keys()))
        print("resultSetSize:", response.get("resultSetSize"))
        print("totalSetSize:", response.get("totalSetSize"))
        print("endPosition:", response.get("endPosition"))
        print("nextUri:", response.get("nextUri"))
        print("envelopeTemplates count:",
                len(response.get("envelopeTemplates") or []))
        print("templates count:",
                len(response.get("templates") or []))


if __name__ == "__main__":
    main()
