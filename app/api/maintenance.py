"""Day 22: /api/maintenance - housekeeping endpoints.

GET  /api/maintenance/jobs
POST /api/maintenance/recover-stale-jobs?dry_run=
GET  /api/maintenance/failed-calls
POST /api/maintenance/failed-calls/{call_id}/resolve
POST /api/maintenance/cleanup?older_than_days=&dry_run=&include_unnormalized=

HMAC authentication is applied by HMACAuthMiddleware in app/main.py.
"""
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AuditLog, FailedExternalCall, Job
from app.db.session import get_db
from app.services.scan_stages import JobStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/maintenance", tags=["Maintenance"])

RAW_BASE_DIR = Path("data/raw")
FINISHED_STATUSES = [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]


# ------------------------------------------------------------------ helpers
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _actor(request: Request) -> str | None:
    return getattr(request.state, "key_id", None)


def _audit(db: Session, action: str, actor: str | None, details: dict, job_id=None) -> None:
    db.add(AuditLog(job_id=job_id, action=action, actor=actor, details=details))


def _job_row(job: Job) -> dict:
    return {
        "job_id": str(job.id),
        "job_type": job.job_type,
        "status": job.status,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "error": job.error_message,
    }


def _call_row(call: FailedExternalCall) -> dict:
    return {
        "id": call.id,
        "job_id": str(call.job_id) if call.job_id else None,
        "service": call.service,
        "method": call.method,
        "endpoint": call.endpoint,
        "status_code": call.status_code,
        "error_message": call.error_message,
        "retry_count": call.retry_count,
        "resolved": call.resolved,
        "created_at": call.created_at,
    }


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# ---------------------------------------------------------------- endpoints
@router.get("/jobs")
def list_jobs(
    status: str | None = None,
    job_type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Job.status == status)
    if job_type:
        stmt = stmt.where(Job.job_type == job_type)

    jobs = db.execute(stmt).scalars().all()
    return {"count": len(jobs), "jobs": [_job_row(j) for j in jobs]}


@router.post("/recover-stale-jobs")
def recover_stale_jobs(
    request: Request,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
):
    minutes = settings.JOB_CRASH_TIMEOUT_MINUTES
    cutoff = _now() - timedelta(minutes=minutes)

    stale = (
        db.execute(
            select(Job).where(
                Job.status == JobStatus.RUNNING,
                Job.updated_at < cutoff,
            )
        )
        .scalars()
        .all()
    )

    ids = [str(j.id) for j in stale]

    if not dry_run:
        for job in stale:
            job.status = JobStatus.FAILED
            job.error_message = (
                f"Marked failed: no heartbeat for {minutes} minutes "
                f"(worker likely crashed). Resume with POST /api/scan/{job.id}/resume"
            )
            job.completed_at = _now()
            job.updated_at = _now()
            _audit(db, "job_recovered_stale", _actor(request),
                   {"timeout_minutes": minutes}, job_id=job.id)
        if stale:
            db.commit()
            logger.warning("Recovered %d stale job(s): %s", len(ids), ids)

    return {
        "dry_run": dry_run,
        "timeout_minutes": minutes,
        "count": len(ids),
        "job_ids": ids,
    }


@router.get("/failed-calls")
def list_failed_calls(
    resolved: bool | None = None,
    job_id: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(FailedExternalCall).order_by(FailedExternalCall.id.desc()).limit(limit)
    if resolved is not None:
        stmt = stmt.where(FailedExternalCall.resolved == resolved)
    if job_id:
        try:
            stmt = stmt.where(FailedExternalCall.job_id == uuid.UUID(job_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="job_id must be a valid UUID")

    calls = db.execute(stmt).scalars().all()
    return {"count": len(calls), "failed_calls": [_call_row(c) for c in calls]}


@router.post("/failed-calls/{call_id}/resolve")
def resolve_failed_call(call_id: int, request: Request, db: Session = Depends(get_db)):
    call = db.get(FailedExternalCall, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="failed call not found")

    if not call.resolved:
        call.resolved = True
        _audit(db, "failed_call_resolved", _actor(request),
               {"failed_call_id": call_id}, job_id=call.job_id)
        db.commit()
        db.refresh(call)

    return _call_row(call)


@router.post("/cleanup")
def cleanup_raw_data(
    request: Request,
    older_than_days: int = Query(7, ge=1),
    dry_run: bool = Query(True),
    include_unnormalized: bool = Query(
        False,
        description="Also delete raw data of completed scans that were never normalized.",
    ),
    db: Session = Depends(get_db),
):
    cutoff = _now() - timedelta(days=older_than_days)

    jobs = (
        db.execute(
            select(Job).where(
                Job.status.in_(FINISHED_STATUSES),
                Job.updated_at < cutoff,
            )
        )
        .scalars()
        .all()
    )

    removed: list[str] = []
    skipped: list[str] = []
    freed = 0

    for job in jobs:
        path = RAW_BASE_DIR / str(job.id)  # job.id is a UUID from the DB, so it is safe
        if not path.is_dir():
            continue

        never_normalized = (
            job.job_type == "scan"
            and job.status == JobStatus.COMPLETED
            and not job.result
        )
        if never_normalized and not include_unnormalized:
            skipped.append(str(job.id))
            continue

        freed += _dir_size(path)
        removed.append(str(job.id))
        if not dry_run:
            shutil.rmtree(path)
            _audit(db, "raw_data_cleaned", _actor(request),
                   {"older_than_days": older_than_days}, job_id=job.id)

    if not dry_run and removed:
        db.commit()
        logger.info("Cleanup removed raw data for %d job(s)", len(removed))

    return {
        "dry_run": dry_run,
        "older_than_days": older_than_days,
        "removed_jobs": removed,
        "skipped_unnormalized": skipped,
        "bytes_freed": freed,
    }