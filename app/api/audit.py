"""Day 24: /api/audit - read access to the audit trail.

GET /api/audit?job_id=&action=&actor=&since=&until=&limit=&offset=

HMAC authentication is applied by HMACAuthMiddleware in app/main.py.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.models import AuditLog
from app.db.session import get_db
from app.services.audit_service import AuditService

router = APIRouter(prefix="/api/audit", tags=["Audit"])


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _row(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "job_id": str(log.job_id) if log.job_id else None,
        "action": log.action,
        "actor": log.actor,
        "details": log.details,
        "created_at": log.created_at,
    }


@router.get("")
def list_audit_logs(
    job_id: str | None = None,
    action: str | None = None,
    actor: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    parsed_job_id = None
    if job_id:
        try:
            parsed_job_id = uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="job_id must be a valid UUID")

    since, until = _utc(since), _utc(until)
    if since and until and since > until:
        raise HTTPException(status_code=400, detail="since must be before until")

    total, rows = AuditService(db).query(
        job_id=parsed_job_id,
        action=action,
        actor=actor,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )
    return {
        "total": total,
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "logs": [_row(r) for r in rows],
    }