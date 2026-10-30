from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.job_service import JobService
from app.services.scan_runner import run_scan_in_background

router = APIRouter(prefix="/api/scan", tags=["scan"])


class ScanRequest(BaseModel):
    from_date: Optional[str] = None  # e.g. "2024-01-01"


def _job_view(job, checkpoint=None) -> dict:
    return {
        "job_id": str(job.id),
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.completed_at,
        "heartbeat_at": job.updated_at,
        "error": job.error_message,
        "stage": checkpoint.stage if checkpoint else None,
        "counts": checkpoint.counts if checkpoint else {},
    }


@router.post("", status_code=202)
def start_scan(req: ScanRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    params = {k: v for k, v in req.model_dump().items() if v is not None}
    job = JobService(db).create_job("scan", params)
    background_tasks.add_task(run_scan_in_background, str(job.id))  # sync fn -> runs in threadpool
    return {"job_id": str(job.id), "status": job.status}


@router.get("/{job_id}")
def scan_status(job_id: str, db: Session = Depends(get_db)):
    jobs = JobService(db)
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return _job_view(job, jobs.get_latest_checkpoint(job_id))


@router.post("/{job_id}/resume", status_code=202)
def resume_scan(job_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    job = JobService(db).get_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    background_tasks.add_task(run_scan_in_background, job_id)
    return {"job_id": job_id, "status": "resuming"}


@router.post("/{job_id}/cancel")
def cancel_scan(job_id: str, db: Session = Depends(get_db)):
    job = JobService(db).cancel_job(job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return {"job_id": job_id, "status": job.status}