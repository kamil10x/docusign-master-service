"""Day 25: resume tests.
A scan that dies mid-run must be resumable from its last checkpoint:
  * no already-saved page / envelope is fetched again
  * no raw page is duplicated (file is written first, checkpoint second)
  * the DLQ rows and *_failed counters survive the resume
  * a worker that crashed while 'running' can be recovered, then resumed
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import maintenance
from app.db.models import AuditLog, FailedExternalCall
from app.db.session import get_db
from app.docusign.exceptions import DocuSignNotFoundError
from app.services.extraction_service import ExtractionService
from app.services.scan_stages import JobStatus
from app.utils.raw_storage import RawPageWriter

PARAMS = {"from_date": "2024-01-01"}
ENV_IDS = [f"env-{i}" for i in range(5)]
FULL_COUNTS = {"envelopes": 5, "recipients": 5, "documents": 5, "templates": 2}


class ResumableClient:
    """Fake DocuSign client. Each fail_* option raises ONCE, so a resume succeeds."""

    _max_attempts = 5

    def __init__(self, fail_envelopes_at=None, fail_recipients_on=None,
                fail_documents_on=None, not_found_recipient=None):
        self._fail_envelopes_at = fail_envelopes_at
        self._fail_recipients_on = fail_recipients_on
        self._fail_documents_on = fail_documents_on
        self._not_found_recipient = not_found_recipient  # always 404s (permanent)
        self.env_starts: list[int] = []
        self.recipient_calls: list[str] = []
        self.document_calls: list[str] = []

    def list_envelopes(self, from_date, start_position=0, count=100):
        self.env_starts.append(start_position)
        if self._fail_envelopes_at == start_position:
            self._fail_envelopes_at = None
            raise RuntimeError("boom: envelopes page")
        envs = [{"envelopeId": f"env-{i}"}
                for i in range(start_position, min(start_position + 2, 5))]
        return {"envelopes": envs, "totalSetSize": 5}

    def list_templates(self, start_position=0, count=100):
        items = [{"templateId": "t1"}, {"templateId": "t2"}]
        return {"envelopeTemplates": items[start_position:start_position + count],
                "totalSetSize": 2}

    def get_envelope_recipients(self, envelope_id):
        self.recipient_calls.append(envelope_id)
        if envelope_id == self._not_found_recipient:
            raise DocuSignNotFoundError(
                "gone", status_code=404,
                endpoint=f"/envelopes/{envelope_id}/recipients",
                envelope_id=envelope_id)
        if envelope_id == self._fail_recipients_on:
            self._fail_recipients_on = None
            raise RuntimeError("boom: recipients")
        return {"signers": [{"recipientId": "1", "email": f"{envelope_id}@x.com"}]}

    def get_envelope_documents(self, envelope_id):
        self.document_calls.append(envelope_id)
        if envelope_id == self._fail_documents_on:
            self._fail_documents_on = None
            raise RuntimeError("boom: documents")
        return {"envelopeDocuments": [{"documentId": "1"}]}


# ------------------------------------------------------------------ helpers
def _run(db, client, tmp_path, job=None):
    svc = ExtractionService(db, client, raw_base_dir=str(tmp_path))
    job = job or svc.start_scan(PARAMS)
    svc._execute_scan(job.id)
    db.refresh(job)
    return svc, job


def _checkpoint(svc, job):
    return svc.jobs.get_latest_checkpoint(job.id)


def _envelope_ids_on_disk(job, tmp_path):
    return ExtractionService._envelope_ids(RawPageWriter(job.id, str(tmp_path)))


@pytest.fixture
def maint_client(db):
    app = FastAPI()
    app.include_router(maintenance.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


# -------------------------------------------------------------------- tests
def test_failure_mid_envelopes_saves_checkpoint_at_failure_point(db, tmp_path):
    client = ResumableClient(fail_envelopes_at=2)

    svc, job = _run(db, client, tmp_path)

    assert job.status == JobStatus.FAILED
    cp = _checkpoint(svc, job)
    assert cp.resource_type == "envelopes"
    assert cp.cursor["start_position"] == 2  # page 0 (2 envelopes) was saved
    assert cp.cursor["page_number"] == 1
    assert cp.cursor["_counts"] == {"envelopes": 2}
    assert len(RawPageWriter(job.id, str(tmp_path)).list_pages("envelopes")) == 1


def test_resume_continues_from_checkpoint_without_refetching_pages(db, tmp_path):
    client = ResumableClient(fail_envelopes_at=2)
    _, job = _run(db, client, tmp_path)
    assert job.status == JobStatus.FAILED

    svc, job = _run(db, client, tmp_path, job=job)

    assert job.status == JobStatus.COMPLETED
    # first run: 0 then 2 (failed). resume: 2 then 4. Position 0 is never fetched twice.
    assert client.env_starts == [0, 2, 2, 4]
    assert client.env_starts.count(0) == 1
    assert _checkpoint(svc, job).cursor["_counts"] == FULL_COUNTS
    assert _envelope_ids_on_disk(job, tmp_path) == ENV_IDS  # no gaps, no duplicates


def test_resume_mid_recipients_only_fetches_remaining_envelopes(db, tmp_path):
    client = ResumableClient(fail_recipients_on="env-3")

    svc, job = _run(db, client, tmp_path)

    assert job.status == JobStatus.FAILED
    cp = _checkpoint(svc, job)
    assert cp.resource_type == "recipients"
    assert cp.cursor["index"] == 3  # env-0..2 done, env-3 is next
    assert cp.cursor["_counts"]["recipients"] == 3

    svc, job = _run(db, client, tmp_path, job=job)

    assert job.status == JobStatus.COMPLETED
    # first run called env-0..env-3 (env-3 failed); resume must only call env-3, env-4
    assert client.recipient_calls[:4] == ["env-0", "env-1", "env-2", "env-3"]
    assert client.recipient_calls[4:] == ["env-3", "env-4"]
    assert _checkpoint(svc, job).cursor["_counts"] == FULL_COUNTS


def test_resume_keeps_dlq_rows_and_failed_counters(db, tmp_path):
    # env-2 recipients 404 (skipped + recorded), later the documents stage crashes
    client = ResumableClient(not_found_recipient="env-2", fail_documents_on="env-4")

    svc, job = _run(db, client, tmp_path)
    assert job.status == JobStatus.FAILED
    assert db.query(FailedExternalCall).count() == 1

    svc, job = _run(db, client, tmp_path, job=job)

    assert job.status == JobStatus.COMPLETED
    # recipients stage is not re-run on resume, so the DLQ row is not duplicated
    assert client.recipient_calls == ENV_IDS
    assert db.query(FailedExternalCall).count() == 1
    counts = _checkpoint(svc, job).cursor["_counts"]
    assert counts["recipients"] == 4
    assert counts["recipients_failed"] == 1
    assert counts["documents"] == 5
    assert client.document_calls[5:] == ["env-4"]  # only the failed one is retried


def test_crash_between_page_write_and_checkpoint_creates_no_duplicates(db, tmp_path):
    """Pages are written first, checkpointed second. If we die in between,
    resume re-writes the same page number (overwrite) instead of adding a copy."""
    client = ResumableClient()
    svc = ExtractionService(db, client, raw_base_dir=str(tmp_path))
    job = svc.start_scan(PARAMS)

    real_save = svc.jobs.save_checkpoint
    calls = {"n": 0}

    def flaky_save(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:  # page_000001.json is already on disk by now
            raise RuntimeError("crash after page write, before checkpoint")
        return real_save(*args, **kwargs)

    svc.jobs.save_checkpoint = flaky_save
    svc._execute_scan(job.id)
    db.refresh(job)

    assert job.status == JobStatus.FAILED
    writer = RawPageWriter(job.id, str(tmp_path))
    assert len(writer.list_pages("envelopes")) == 2  # page 1 exists but is not checkpointed
    assert _checkpoint(svc, job).cursor["start_position"] == 2

    svc2, job = _run(db, client, tmp_path, job=job)  # fresh service, unpatched

    assert job.status == JobStatus.COMPLETED
    assert len(writer.list_pages("envelopes")) == 3  # page 1 overwritten, not duplicated
    assert _envelope_ids_on_disk(job, tmp_path) == ENV_IDS
    assert _checkpoint(svc2, job).cursor["_counts"]["envelopes"] == 5


def test_completed_job_is_not_rerun(db, tmp_path):
    client = ResumableClient()
    _, job = _run(db, client, tmp_path)
    assert job.status == JobStatus.COMPLETED
    calls_before = (list(client.env_starts), list(client.recipient_calls))

    _, job = _run(db, client, tmp_path, job=job)

    assert job.status == JobStatus.COMPLETED
    assert (client.env_starts, client.recipient_calls) == calls_before


def test_crashed_worker_is_recovered_then_resumed(db, tmp_path, maint_client):
    client = ResumableClient(fail_recipients_on="env-3")
    _, job = _run(db, client, tmp_path)
    assert job.status == JobStatus.FAILED

    # simulate a hard crash: the process died while 'running', nobody marked it failed
    job.status = JobStatus.RUNNING
    job.error_message = None
    job.updated_at = datetime.now(timezone.utc) - timedelta(days=3)
    db.commit()

    body = maint_client.post("/api/maintenance/recover-stale-jobs").json()

    assert body["job_ids"] == [str(job.id)]
    db.refresh(job)
    assert job.status == JobStatus.FAILED
    assert f"/api/scan/{job.id}/resume" in job.error_message

    svc, job = _run(db, client, tmp_path, job=job)

    assert job.status == JobStatus.COMPLETED
    assert client.recipient_calls[4:] == ["env-3", "env-4"]
    assert _checkpoint(svc, job).cursor["_counts"] == FULL_COUNTS
    actions = {a.action for a in db.query(AuditLog).filter_by(job_id=job.id)}
    assert {"scan_started", "job_recovered_stale", "scan_resumed", "scan_completed"} <= actions