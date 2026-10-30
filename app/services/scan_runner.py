
"""Background entrypoint for DocuSign extraction scans."""

import asyncio
import logging

from app.db.session import SessionLocal
from app.docusign.auth_client import auth_client
from app.docusign.client import DocuSignClient
from app.services.extraction_service import ExtractionService
from app.services.job_service import JobService
from app.services.scan_stages import JobStatus

logger = logging.getLogger(__name__)


def run_scan_in_background(job_id: str) -> None:
    db = SessionLocal()
    client = None

    try:
        jobs = JobService(db)
        job = jobs.get_job(job_id)

        if job is None:
            logger.error("Job %s not found", job_id)
            return

        if job.status == JobStatus.CANCELLED:
            return

        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            return

        # Retrieve the default DocuSign account.
        account = asyncio.run(auth_client.get_account_info())

        # Initialize the existing synchronous API client.
        client = DocuSignClient(
            auth=auth_client,
            base_url=account.base_uri,
            account_id=account.account_id,
        )

        # Execute extraction.
        service = ExtractionService(db, client)
        service.run_scan(job_id)

    except Exception as exc:
        logger.exception(
            "Background scan crashed for job %s",
            job_id,
        )

        try:
            db.rollback()
            jobs = JobService(db)
            job = jobs.get_job(job_id)

            if job and job.status in (
                JobStatus.PENDING,
                JobStatus.RUNNING,
            ):
                jobs.mark_failed(job_id, str(exc))
                jobs.add_audit_log(
                    job_id,
                    "background_scan_failed",
                    {"error": str(exc)},
                )
        except Exception:
            db.rollback()
            logger.exception(
                "Could not record background failure for job %s",
                job_id,
            )

    finally:
        if client is not None:
            client.close()

        db.close()
