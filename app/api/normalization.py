"""Day 20: /api/normalization endpoints.

POST /api/normalization/{job_id}          run normalization + export to MinIO
GET  /api/normalization/{job_id}/status   job + normalization/export status
GET  /api/normalization/{job_id}/results  MinIO object paths per table

HMAC authentication is applied by HMACAuthMiddleware in app/main.py.
"""
import logging
import threading
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.job_service import JobService
from app.services.minio_client import MinioClient, minio_client
from app.services.normalization_service import (
    JobNotFoundError,
    JobNotReadyError,
    NormalizationService,
    RawDataMissingError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/normalization",
    tags=["Normalization"],
)

# Guards against two simultaneous runs of the same job inside this process.
_active_jobs: set[str] = set()
_active_lock = threading.Lock()


# ------------------------------------------------------------------ schemas
class NormalizationRunResponse(BaseModel):
    message: str
    job_id: str
    record_counts: dict[str, int]
    exports: dict[str, dict[str, str]]
    data: dict[str, Any] | None = None


class NormalizationStatusResponse(BaseModel):
    job_id: str
    job_status: str
    running: bool
    normalized: bool
    record_counts: dict[str, int]
    exports_ready: bool | None  # None -> storage could not be reached
    exports: dict[str, dict[str, str]] | None


class NormalizationResultsResponse(BaseModel):
    job_id: str
    bucket: str
    files: dict[str, dict[str, str]]


# ------------------------------------------------------------------ helpers
def _parse_job_id(job_id: str) -> str:
    try:
        return str(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="job_id must be a valid UUID")


def _acquire(job_id: str) -> bool:
    with _active_lock:
        if job_id in _active_jobs:
            return False
        _active_jobs.add(job_id)
        return True


def _release(job_id: str) -> None:
    with _active_lock:
        _active_jobs.discard(job_id)


def _is_running(job_id: str) -> bool:
    with _active_lock:
        return job_id in _active_jobs


def _record_counts(result: Any) -> dict[str, int]:
    if not isinstance(result, dict):
        return {}
    return {
        table: len(rows)
        for table, rows in result.items()
        if isinstance(rows, list)
    }


def _group_exports(job_id: str, names: list[str]) -> dict[str, dict[str, str]]:
    prefix = MinioClient.job_prefix(job_id)
    files: dict[str, dict[str, str]] = {}

    for name in names:
        if not name.startswith(prefix):
            continue
        table, _, fmt = name[len(prefix):].rpartition(".")
        if table and fmt in ("parquet", "json"):
            files.setdefault(table, {})[fmt] = name

    return dict(sorted(files.items()))


def _list_exports(job_id: str) -> dict[str, dict[str, str]]:
    names = minio_client.list_objects(MinioClient.job_prefix(job_id))
    return _group_exports(job_id, names)


def _get_job_or_404(db: Session, job_id: str):
    job = JobService(db).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


# ---------------------------------------------------------------- endpoints
@router.post(
    "/{job_id}",
    response_model=NormalizationRunResponse,
    response_model_exclude_none=True,
)
def normalize_job(
    job_id: str,
    include_data: bool = Query(
        False,
        description="Also return the full normalized rows (can be very large).",
    ),
    db: Session = Depends(get_db),
):
    job_id = _parse_job_id(job_id)

    if not _acquire(job_id):
        raise HTTPException(
            status_code=409,
            detail="Normalization is already running for this job",
        )

    try:
        outcome = NormalizationService(db).run(job_id)

    except JobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    except (JobNotReadyError, RawDataMissingError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    except Exception as exc:
        logger.exception("Normalization endpoint failed for job %s", job_id)
        raise HTTPException(
            status_code=500,
            detail=f"Normalization failed: {str(exc)}",
        )

    finally:
        _release(job_id)

    return NormalizationRunResponse(
        message="Normalization completed successfully",
        job_id=job_id,
        record_counts=outcome.record_counts,
        exports=outcome.exports,
        data=outcome.data if include_data else None,
    )


@router.get("/{job_id}/status", response_model=NormalizationStatusResponse)
def normalization_status(job_id: str, db: Session = Depends(get_db)):
    job_id = _parse_job_id(job_id)
    job = _get_job_or_404(db, job_id)

    record_counts = _record_counts(job.result)

    try:
        exports: dict[str, dict[str, str]] | None = _list_exports(job_id)
    except Exception:
        logger.exception("Could not list MinIO exports for job %s", job_id)
        exports = None

    return NormalizationStatusResponse(
        job_id=job_id,
        job_status=job.status,
        running=_is_running(job_id),
        normalized=bool(record_counts),
        record_counts=record_counts,
        exports_ready=None if exports is None else bool(exports),
        exports=exports,
    )


@router.get("/{job_id}/results", response_model=NormalizationResultsResponse)
def normalization_results(job_id: str, db: Session = Depends(get_db)):
    job_id = _parse_job_id(job_id)
    _get_job_or_404(db, job_id)

    try:
        files = _list_exports(job_id)
    except Exception:
        logger.exception("Could not list MinIO exports for job %s", job_id)
        raise HTTPException(status_code=503, detail="Object storage unavailable")

    if not files:
        raise HTTPException(
            status_code=404,
            detail="No normalized output for this job yet. Run normalization first.",
        )

    return NormalizationResultsResponse(
        job_id=job_id,
        bucket=minio_client.bucket,
        files=files,
    )