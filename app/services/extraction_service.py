"""Day 13: ExtractionService._execute_scan - stages, heartbeat, resume."""
import logging
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.job_service import JobService
from app.services.scan_stages import JobStatus, ScanStage, next_stage, stages_from
from app.utils.raw_storage import RawPageWriter

logger = logging.getLogger(__name__)

PAGE_SIZE = 100
HEARTBEAT_INTERVAL_S = 10
DEFAULT_FROM_DATE = "2000-01-01"


class ScanCancelled(Exception):
    pass


class ExtractionService:
    def __init__(self, db: Session, client: Any, raw_base_dir: str = "data/raw") -> None:
        self.db = db
        self.client = client
        self.jobs = JobService(db)
        self.raw_base_dir = raw_base_dir
        self._last_beat = 0.0

    # ---- public -----------------------------------------------------------
    def start_scan(self, params: dict):
        return self.jobs.create_job("scan", params)

    def run_scan(self, job_id: Any) -> None:
        self._execute_scan(job_id)

    # ---- the state machine --------------------------------------------------
    def _execute_scan(self, job_id: Any) -> None:
        job = self.jobs.get_job(job_id)
        if job is None:
            raise ValueError(f"job {job_id} not found")
        if job.status == JobStatus.COMPLETED:
            return

        params = job.params or {}
        writer = RawPageWriter(job_id, self.raw_base_dir)

        checkpoint = self.jobs.get_latest_checkpoint(job_id)
        stage = (
            ScanStage(checkpoint.resource_type)
            if checkpoint
            else ScanStage.ENVELOPES
        )

        cursor = dict(checkpoint.cursor or {}) if checkpoint else {}

        counts = cursor.pop("_counts", {}) if checkpoint else {}

        handlers: dict[ScanStage, Callable] = {
            ScanStage.ENVELOPES: self._scan_envelopes,
            ScanStage.RECIPIENTS: self._scan_recipients,
            ScanStage.DOCUMENTS: self._scan_documents,
            ScanStage.TEMPLATES: self._scan_templates,
        }

        self.jobs.mark_running(job_id)
        self.jobs.add_audit_log(job_id, "scan_resumed" if checkpoint else "scan_started",
                                {"stage": stage.value})
        self._beat(job_id, force=True)

        try:
            for current in stages_from(stage):
                logger.info("job %s: stage %s", job_id, current.value)
                handlers[current](job_id, params, writer, cursor, counts)
                # stage finished -> checkpoint points at the NEXT stage with a fresh cursor
                self.jobs.save_checkpoint(job_id, next_stage(current), {}, counts)
                cursor = {}
            self.jobs.mark_completed(job_id)
            self.jobs.add_audit_log(job_id, "scan_completed", {"counts": counts})
        except ScanCancelled:
            logger.info("job %s cancelled", job_id)
            self.jobs.add_audit_log(job_id, "scan_cancelled", {"counts": counts})
        except Exception as exc:  # noqa: BLE001
            logger.exception("job %s failed", job_id)
            self.db.rollback()
            self.jobs.mark_failed(job_id, str(exc))
            self.jobs.add_audit_log(job_id, "scan_failed", {"error": str(exc)})

    # ---- helpers ------------------------------------------------------------
    def _beat(self, job_id: Any, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_beat >= HEARTBEAT_INTERVAL_S:
            self.jobs.update_heartbeat(job_id)
            self._last_beat = now

    def _check_cancelled(self, job_id: Any) -> None:
        if self.jobs.get_status(job_id) == JobStatus.CANCELLED:
            raise ScanCancelled()

    # ---- paged stages (envelopes, templates) --------------------------------
    def _scan_paged(self, job_id, stage, resource, items_key, fetch, writer, cursor, counts) -> None:
        start = int(cursor.get("start_position", 0))
        page_number = int(cursor.get("page_number", 0))
        while True:
            self._check_cancelled(job_id)
            page = fetch(start_position=start, count=PAGE_SIZE)
            items = page.get(items_key) or []
            if not items:
                break
            # order matters: file first, checkpoint second
            writer.write_page(resource, page_number, page)
            counts[resource] = counts.get(resource, 0) + len(items)
            start += len(items)
            page_number += 1
            self.jobs.save_checkpoint(
                job_id, stage, {"start_position": start, "page_number": page_number}, counts)
            self._beat(job_id)

            total = int(page.get("totalSetSize") or 0)
            if total and start >= total:
                break
            if not total and len(items) < PAGE_SIZE:
                break

    def _scan_envelopes(self, job_id, params, writer, cursor, counts) -> None:
        from_date = params.get("from_date", DEFAULT_FROM_DATE)
        self._scan_paged(
            job_id, ScanStage.ENVELOPES, "envelopes", "envelopes",
            lambda start_position, count: self.client.list_envelopes(
                from_date=from_date, start_position=start_position, count=count),
            writer, cursor, counts)

    def _scan_templates(self, job_id, params, writer, cursor, counts) -> None:
        self._scan_paged(
            job_id, ScanStage.TEMPLATES, "templates", "envelopeTemplates",
            lambda start_position, count: self.client.list_templates(
                start_position=start_position, count=count),
            writer, cursor, counts)

    # ---- per-envelope stages (recipients, documents) ------------------------
    @staticmethod
    def _envelope_ids(writer: RawPageWriter) -> list[str]:
        ids: list[str] = []
        for path in writer.list_pages("envelopes"):
            data = writer.read_page(path)
            ids.extend(e["envelopeId"] for e in data.get("envelopes", []))
        return ids

    def _scan_per_envelope(self, job_id, stage, resource, fetch, writer, cursor, counts) -> None:
        ids = self._envelope_ids(writer)  # read from disk, so resume works
        index = int(cursor.get("index", 0))
        while index < len(ids):
            self._check_cancelled(job_id)
            envelope_id = ids[index]
            data = fetch(envelope_id)
            writer.write_page(resource, index, {"envelopeId": envelope_id, **data})
            counts[resource] = counts.get(resource, 0) + 1
            index += 1
            self.jobs.save_checkpoint(job_id, stage, {"index": index}, counts)
            self._beat(job_id)

    def _scan_recipients(self, job_id, params, writer, cursor, counts) -> None:
        self._scan_per_envelope(job_id, ScanStage.RECIPIENTS, "recipients",
                                self.client.get_envelope_recipients, writer, cursor, counts)

    def _scan_documents(self, job_id, params, writer, cursor, counts) -> None:
        self._scan_per_envelope(job_id, ScanStage.DOCUMENTS, "documents",
                                self.client.get_envelope_documents, writer, cursor, counts)