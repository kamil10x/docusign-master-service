
from pathlib import Path
from typing import Any
import logging

from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder

from app.services.job_service import JobService
from app.utils.raw_storage import RawPageWriter

from app.normalizers.envelope import EnvelopeNormalizer
from app.normalizers.recipient import RecipientNormalizer
from app.normalizers.document import DocumentNormalizer
from app.normalizers.template import TemplateNormalizer



logger = logging.getLogger(__name__)


class NormalizationService:
    def __init__(
        self,
        db: Session,
        raw_base_dir: str = "data/raw",
    ):
        self.db = db
        self.jobs = JobService(db)
        self.raw_base_dir = raw_base_dir

        self.normalizers = {
            "envelopes": EnvelopeNormalizer(),
            "recipients": RecipientNormalizer(),
            "documents": DocumentNormalizer(),
            "templates": TemplateNormalizer(),
        }

    def normalize_job(self, job_id: str) -> dict[str, Any]:
        """
        Read raw extraction pages and normalize all resources.
        The normalized result is stored in Job.result.
        """

        job = self.jobs.get_job(job_id)

        if not job:
            raise ValueError(f"Job not found: {job_id}")

        if job.status != "completed":
            raise ValueError(
                "Normalization can only run after extraction is completed."
            )

        writer = RawPageWriter(
            job_id=job_id,
            base_dir=self.raw_base_dir,
        )

        normalized_data = {}

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

            self.jobs.add_audit_log(
                job_id,
                "normalization_completed",
                {
                    "tables": list(normalized_data.keys()),
                    "record_counts": {
                        table: len(rows)
                        for table, rows in normalized_data.items()
                    },
                },
            )

            return normalized_data

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
