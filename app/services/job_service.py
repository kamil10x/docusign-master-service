
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import AuditLog, FailedExternalCall, Job, JobCheckpoint
from app.services.scan_stages import JobStatus
from app.services.audit_service import AuditService


def _now() -> datetime:
    return datetime.now(timezone.utc)


ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


def _uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class JobService:
    def __init__(self, db: Session) -> None:
        self.db = db

    # ============================================================
    # JOB MANAGEMENT
    # ============================================================

    def create_job(
        self,
        job_type: str,
        params: Optional[dict] = None,
    ) -> Job:
        job = Job(
            job_type=job_type,
            status=JobStatus.PENDING,
            params=params or {},
        )

        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)

        return job

    def get_job(self, job_id: Any) -> Optional[Job]:
        return self.db.get(Job, _uuid(job_id))

    def _require_job(self, job_id: Any) -> Job:
        job = self.get_job(job_id)

        if job is None:
            raise ValueError(f"Job not found: {job_id}")

        return job

    def get_status(self, job_id: Any) -> Optional[str]:
        job = self.get_job(job_id)

        if job is None:
            return None

        self.db.refresh(job)
        return job.status

    def mark_running(self, job_id: Any) -> None:
        job = self._require_job(job_id)

        if job.status in (
            JobStatus.CANCELLED,
            JobStatus.COMPLETED,
        ):
            raise ValueError(
                f"Cannot run job in status: {job.status}"
            )

        job.status = JobStatus.RUNNING
        job.started_at = job.started_at or _now()
        job.error_message = None
        job.updated_at = _now()

        self.db.commit()

    def mark_completed(self, job_id: Any) -> None:
        job = self._require_job(job_id)

        if job.status != JobStatus.RUNNING:
            raise ValueError(
                f"Cannot complete job in status: {job.status}"
            )

        job.status = JobStatus.COMPLETED
        job.completed_at = _now()
        job.updated_at = _now()

        self.db.commit()

    def mark_failed(self, job_id: Any, error: str) -> None:
        job = self._require_job(job_id)

        if job.status == JobStatus.CANCELLED:
            return

        job.status = JobStatus.FAILED
        job.error_message = error[:2000]
        job.completed_at = _now()
        job.updated_at = _now()

        self.db.commit()

    def cancel_job(self, job_id: Any) -> Optional[Job]:
        job = self.get_job(job_id)

        if job is None:
            return None

        if job.status in (
            JobStatus.PENDING,
            JobStatus.RUNNING,
        ):
            job.status = JobStatus.CANCELLED
            job.completed_at = _now()
            job.updated_at = _now()

            self.db.commit()
            self.db.refresh(job)

        return job
    
    def is_active(self, job: Job) -> bool:
        return job.status in ACTIVE_STATUSES

    def delete_job(self, job_id: Any) -> dict:
        """
        Remove one run. Raises:
            LookupError - job id is malformed or the job does not exist
            ValueError  - job is still PENDING/RUNNING (cancel it first)

        Deletes the job's checkpoints and failed-call records, keeps its audit
        trail (job_id is detached, not deleted), then deletes the job row.
        All DB changes happen in one transaction.
        """
        try:
            jid = _uuid(job_id)
        except ValueError:
            raise LookupError(f"Job not found: {job_id}")

        job = self.db.get(Job, jid)
        if job is None:
            raise LookupError(f"Job not found: {job_id}")

        if self.is_active(job):
            raise ValueError(
                f"Cannot remove job in status {job.status}; cancel it first"
            )

        previous_status = job.status

        try:
            checkpoints = self.db.execute(
                delete(JobCheckpoint).where(JobCheckpoint.job_id == jid)
            ).rowcount
            failed_calls = self.db.execute(
                delete(FailedExternalCall).where(FailedExternalCall.job_id == jid)
            ).rowcount
            audit_detached = self.db.execute(
                update(AuditLog)
                .where(AuditLog.job_id == jid)
                .values(job_id=None)
            ).rowcount
            self.db.delete(job)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        result = {
            "job_id": str(jid),
            "removed": True,
            "previous_status": previous_status,
            "deleted": {
                "checkpoints": checkpoints,
                "failed_calls": failed_calls,
            },
            "audit_logs_retained": audit_detached,
        }

        AuditService(self.db).log_event(
            "scan_removed",
            job_id=None,
            details={"removed_job_id": str(jid), **result},
        )
        return result

    def update_heartbeat(self, job_id: Any) -> None:
        job = self._require_job(job_id)

        if job.status != JobStatus.RUNNING:
            return

        # updated_at doubles as the heartbeat timestamp.
        job.updated_at = _now()
        self.db.commit()

    # ============================================================
    # CHECKPOINT MANAGEMENT - DAY 12
    # ============================================================

    def save_checkpoint(
        self,
        job_id: Any,
        stage: str,
        cursor: Optional[dict] = None,
        counts: Optional[dict] = None,
    ) -> JobCheckpoint:

        job = self._require_job(job_id)

        if job.status in (
            JobStatus.COMPLETED,
            JobStatus.CANCELLED,
        ):
            raise ValueError(
                f"Cannot checkpoint job in status: {job.status}"
            )

        stage_value = getattr(stage, "value", stage)

        # Preserve the existing cursor while storing cumulative counts
        # in the existing JSONB column.
        checkpoint_cursor = dict(cursor or {})
        checkpoint_cursor["_counts"] = dict(counts or {})

        checkpoint = JobCheckpoint(
            job_id=_uuid(job_id),
            resource_type=stage_value,
            cursor=checkpoint_cursor,
            items_processed=sum(
                v for k, v in (counts or {}).items()
                if not k.endswith("_failed")
            ),
        )

        self.db.add(checkpoint)
        self.db.commit()
        self.db.refresh(checkpoint)

        return checkpoint

    def get_latest_checkpoint(
        self,
        job_id: Any,
        stage: Optional[str] = None,
    ) -> Optional[JobCheckpoint]:

        stmt = (
            select(JobCheckpoint)
            .where(
                JobCheckpoint.job_id == _uuid(job_id)
            )
        )

        if stage is not None:
            stage_value = getattr(stage, "value", stage)

            stmt = stmt.where(
                JobCheckpoint.resource_type == stage_value
            )

        stmt = (
            stmt
            .order_by(
                JobCheckpoint.created_at.desc(),
                JobCheckpoint.id.desc(),
            )
            .limit(1)
        )

        return self.db.execute(stmt).scalars().first()

    # ============================================================
    # AUDIT LOGGING
    # ============================================================

    def add_audit_log(
        self,
        job_id: Any,
        action: str,
        details: Optional[dict] = None,
        actor: Optional[str] = None,
    ) -> None:

        self._require_job(job_id)

        AuditService(self.db).log_event(
            action, job_id=job_id, actor=actor, details=details
        )

    # ============================================================
    # FAILED EXTERNAL CALLS (DLQ)
    # ============================================================

    def record_failed_call(
        self,
        service: str,
        method: str,
        endpoint: str,
        *,
        job_id: Any = None,
        status_code: Optional[int] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
    ) -> FailedExternalCall:
        row = FailedExternalCall(
            job_id=_uuid(job_id) if job_id is not None else None,
            service=service,
            method=method.upper(),
            endpoint=endpoint,
            status_code=status_code,
            error_message=(error_message or "")[:1000] or None,
            retry_count=retry_count,
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        AuditService(self.db).log_event(
            "failed_call_recorded",
            job_id=job_id,
            details={
                "failed_call_id": row.id,
                "service": service,
                "endpoint": endpoint,
                "status_code": status_code,
            },
        )
        return row