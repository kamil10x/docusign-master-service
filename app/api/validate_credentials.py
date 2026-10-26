import httpx
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db
from app.docusign.auth_client import DocuSignAuthError, auth_client
from app.services.job_service import JobService

router = APIRouter(tags=["credentials"])


@router.post("/validate-credentials")
def validate_credentials(request: Request, db: Session = Depends(get_db)):
    service = JobService(db)
    actor = getattr(request.state, "key_id", None)
    base = settings.DOCUSIGN_BASE_URL.rstrip("/")
    endpoint = f"{base}/restapi/v2.1/accounts/{settings.DOCUSIGN_ACCOUNT_ID}"

    # 1) get a token
    try:
        token = auth_client.get_access_token()
    except (DocuSignAuthError, OSError) as exc:
        service.record_failed_call("docusign", "POST", f"https://{settings.DOCUSIGN_AUTH_SERVER}/oauth/token",
                                    error_message=str(exc)[:500])
        service.log_audit("validate_credentials", actor=actor, details={"valid": False, "stage": "token"})
        return {"valid": False, "stage": "token", "detail": "Could not obtain an access token"}

    # 2) prove the token + account id work
    try:
        resp = httpx.get(endpoint, headers={"Authorization": f"Bearer {token}"},
                        timeout=settings.DOCUSIGN_REQUEST_TIMEOUT)
    except httpx.HTTPError as exc:
        service.record_failed_call("docusign", "GET", endpoint, error_message=str(exc)[:500])
        service.log_audit("validate_credentials", actor=actor, details={"valid": False, "stage": "account"})
        return {"valid": False, "stage": "account", "detail": "DocuSign API unreachable"}

    if resp.status_code != 200:
        service.record_failed_call("docusign", "GET", endpoint, status_code=resp.status_code, error_message=resp.text[:500])
        service.log_audit("validate_credentials", actor=actor, details={"valid": False, "stage": "account", "status_code": resp.status_code})
        return {"valid": False, "stage": "account", "detail": f"DocuSign returned {resp.status_code}"}

    data = resp.json()
    service.log_audit("validate_credentials", actor=actor, details={"valid": True})
    return {
        "valid": True,
        "account_name": data.get("accountName"),
        "account_id": settings.DOCUSIGN_ACCOUNT_ID,
    }