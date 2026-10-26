"""/api/validate-credentials and /api/health routes."""
from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.docusign.auth_client import (
    ConsentRequiredError,
    DocuSignAuthClient,
    DocuSignAuthError,
)

router = APIRouter(prefix="/api")


def get_auth_client(settings: Settings = Depends(get_settings)) -> DocuSignAuthClient:
    return DocuSignAuthClient(
        integration_key=settings.docusign_integration_key,
        user_id=settings.docusign_user_id,
        private_key=settings.docusign_private_key,
        auth_host=settings.docusign_auth_host,
    )


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/validate-credentials")
async def validate_credentials(client: DocuSignAuthClient = Depends(get_auth_client)):
    try:
        account = await client.get_account_info(force_refresh=True)
    except ConsentRequiredError as exc:
        return {"valid": False, "error": "consent_required", "detail": str(exc)}
    except DocuSignAuthError as exc:
        return {"valid": False, "error": "auth_failed", "detail": str(exc)}

    return {
        "valid": True,
        "account_id": account.account_id,
        "account_name": account.account_name,
        "base_uri": account.base_uri,
    }