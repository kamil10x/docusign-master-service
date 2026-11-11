from dataclasses import dataclass
from typing import Any
import logging

from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder

from app.services.job_service import JobService
from app.services.minio_client import MinioClient
from app.services.normalization_export import export_normalized_results
from app.services.scan_stages import JobStatus
from app.utils.raw_storage import RawPageWriter

from app.normalizers.envelope import EnvelopeNormalizer
from app.normalizers.recipient import RecipientNormalizer
from app.normalizers.document import DocumentNormalizer
from app.normalizers.template import TemplateNormalizer


logger = logging.getLogger(__name__)


class JobNotFoundError(ValueError):
    """No job with this id (subclass of ValueError for backward compatibility)."""


class JobNotReadyError(ValueError):
    """The scan has not completed, so there is nothing to normalize yet."""


class RawDataMissingError(ValueError):
    """The job is completed but its raw extraction files are not on disk."""


@dataclass
class NormalizationOutcome:
    data: dict[str, list[dict[str, Any]]]
    exports: dict[str, dict[str, str]]

    @property
    def record_counts(self) -> dict[str, int]:
        return {table: len(rows) for table, rows in self.data.items()}


class NormalizationService:
    def __init__(
        self,
        db: Session,
        raw_base_dir: str = "data/raw",
        minio: MinioClient | None = None,
    ):
        self.db = db
        self.jobs = JobService(db)
        self.raw_base_dir = raw_base_dir
        self.minio = minio  # None -> shared app-wide MinIO client

        self.normalizers = {
            "envelopes": EnvelopeNormalizer(),
            "recipients": RecipientNormalizer(),
            "documents": DocumentNormalizer(),
            "templates": TemplateNormalizer(),
        }

    def normalize_job(self, job_id: str) -> dict[str, Any]:
        """Backward-compatible entry point: returns only the normalized tables."""
        return self.run(job_id).data

    def run(self, job_id: str) -> NormalizationOutcome:
        """
        Read raw extraction pages, normalize every resource, store the result in
        Job.result and export each table to MinIO (Parquet + JSON).

        The DB result is committed before the export, so a MinIO failure is
        reported (audit log + exception) without losing the normalized data;
        re-running is safe because export paths are deterministic.
        """
        job = self.jobs.get_job(job_id)

        if not job:
            raise JobNotFoundError(f"Job not found: {job_id}")

        if job.status != JobStatus.COMPLETED:
            raise JobNotReadyError(
                "Normalization can only run after extraction is completed."
            )

        writer = RawPageWriter(
            job_id=job_id,
            base_dir=self.raw_base_dir,
        )

        if not writer.root.exists():
            raise RawDataMissingError(
                f"No raw extraction data found for job {job_id}. "
                "Run a new scan for this job's data first."
            )
            
        self.jobs.add_audit_log(job_id, "normalization_started", {})
        normalized_data: dict[str, list[dict[str, Any]]] = {}

        try:
            for resource, normalizer in self.normalizers.items():
                records = self._read_resource_pages(writer, resource)

                result = normalizer.normalize(records)

                normalized_data.update(result)

                logger.info(
                    "Normalized %s: %d records",
                    resource,
                    sum(len(rows) for rows in result.values()),
                )

            job.result = jsonable_encoder(normalized_data)
            self.db.commit()
            self.db.refresh(job)

            exports = export_normalized_results(
                job_id,
                normalized_data,
                minio=self.minio,
            )

            outcome = NormalizationOutcome(data=normalized_data, exports=exports)

            self.jobs.add_audit_log(
                job_id,
                "normalization_completed",
                {
                    "tables": list(normalized_data.keys()),
                    "record_counts": outcome.record_counts,
                    "exports": exports,
                },
            )

            return outcome

        except Exception as exc:
            self.db.rollback()

            self.jobs.add_audit_log(
                job_id,
                "normalization_failed",
                {"error": str(exc)},
            )

            logger.exception(
                "Normalization failed for job %s",
                job_id,
            )
            raise

    def _read_resource_pages(
        self,
        writer: RawPageWriter,
        resource: str,
    ) -> list[dict[str, Any]]:
        """
        Read all JSON pages for a resource.
        Each page contains the original API response.
        """

        records = []

        for page_path in writer.list_pages(resource):
            page_data = writer.read_page(page_path)

            if not isinstance(page_data, dict):
                continue

            # Envelope and template pages contain collections.
            if resource == "envelopes":
                items = page_data.get("envelopes", [])

            elif resource == "templates":
                items = page_data.get("envelopeTemplates", [])

            # Per-envelope pages contain one envelopeId and resource data.
            elif resource in ("recipients", "documents"):
                items = [page_data]

            else:
                items = []

            if isinstance(items, list):
                records.extend(
                    item for item in items
                    if isinstance(item, dict)
                )

        return records