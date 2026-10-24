import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditLog, FailedExternalCall, Job, JobCheckpoint, JobStatus


class JobService:
    def __init__(self, db: Session):
        self.db = db

    # --- jobs ---
    def create_job(self, job_type: str, params: dict | None = None) -> Job:
        job = Job(job_type=job_type, params=params or {})
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        self.log_audit("job_created", job_id=job.id, details={"job_type": job_type})
        return job

    def get_job(self, job_id: uuid.UUID) -> Job | None:
        return self.db.get(Job, job_id)

    def update_status(self, job_id: uuid.UUID, status: str, error: str | None = None, result: dict | None = None) -> Job:
        job = self.db.get(Job, job_id)
        job.status = status
        now = datetime.now(timezone.utc)
        if status == JobStatus.RUNNING and job.started_at is None:
            job.started_at = now
        if status in (JobStatus.COMPLETED, JobStatus.FAILED):
            job.completed_at = now
        if error:
            job.error_message = error
        if result is not None:
            job.result = result
        self.db.commit()
        self.log_audit("job_status_changed", job_id=job_id, details={"status": status})
        return job

    # --- checkpoints ---
    def save_checkpoint(self, job_id: uuid.UUID, resource_type: str, cursor: dict, items_processed: int) -> JobCheckpoint:
        cp = JobCheckpoint(job_id=job_id, resource_type=resource_type, cursor=cursor, items_processed=items_processed)
        self.db.add(cp)
        self.db.commit()
        return cp

    def get_latest_checkpoint(self, job_id: uuid.UUID, resource_type: str) -> JobCheckpoint | None:
        stmt = (
            select(JobCheckpoint)
            .where(JobCheckpoint.job_id == job_id, JobCheckpoint.resource_type == resource_type)
            .order_by(JobCheckpoint.id.desc())
            .limit(1)
        )
        return self.db.scalars(stmt).first()

    # --- audit + failures ---
    def log_audit(self, action: str, job_id: uuid.UUID | None = None, actor: str | None = None, details: dict | None = None) -> None:
        self.db.add(AuditLog(job_id=job_id, action=action, actor=actor, details=details or {}))
        self.db.commit()

    def record_failed_call(self, service: str, method: str, endpoint: str, status_code: int | None = None, error_message: str | None = None, job_id: uuid.UUID | None = None, retry_count: int = 0) -> None:
        self.db.add(FailedExternalCall(
            job_id=job_id, service=service, method=method, endpoint=endpoint,
            status_code=status_code, error_message=error_message, retry_count=retry_count,
        ))
        self.db.commit()