"""Day 24: audit trail - one place to write and query audit_logs."""
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.models import AuditLog

logger = logging.getLogger(__name__)


def _uuid(value: Any) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def log_event(
        self,
        action: str,
        *,
        job_id: Any = None,
        actor: Optional[str] = None,
        details: Optional[dict] = None,
        commit: bool = True,
    ) -> Optional[AuditLog]:
        """Write one audit row. Never raises: a logging failure must not break the real work."""
        try:
            row = AuditLog(
                job_id=_uuid(job_id) if job_id is not None else None,
                action=action[:100],
                actor=actor,
                details=jsonable_encoder(details or {}),
            )
            self.db.add(row)
            if commit:
                self.db.commit()
                self.db.refresh(row)
            return row
        except Exception:  # noqa: BLE001
            logger.exception("Could not write audit log %r", action)
            if commit:
                self.db.rollback()
            return None

    def query(
        self,
        *,
        job_id: Any = None,
        action: Optional[str] = None,
        actor: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[AuditLog]]:
        """Return (total_matching, page_of_rows), newest first."""
        conds = []
        if job_id is not None:
            conds.append(AuditLog.job_id == _uuid(job_id))
        if action:
            conds.append(AuditLog.action == action)
        if actor:
            conds.append(AuditLog.actor == actor)
        if since is not None:
            conds.append(AuditLog.created_at >= since)
        if until is not None:
            conds.append(AuditLog.created_at <= until)

        count_stmt = select(func.count()).select_from(AuditLog)
        rows_stmt = select(AuditLog)
        if conds:
            count_stmt = count_stmt.where(and_(*conds))
            rows_stmt = rows_stmt.where(and_(*conds))

        total = self.db.execute(count_stmt).scalar_one()
        rows = (
            self.db.execute(
                rows_stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return total, list(rows)