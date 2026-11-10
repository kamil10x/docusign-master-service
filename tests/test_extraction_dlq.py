import pytest

from app.db.models import FailedExternalCall, JobStatus
from app.docusign.exceptions import (
    DocuSignAPIError,
    DocuSignNotFoundError,
    DocuSignRateLimitError,
)
from app.services.extraction_service import ExtractionService


def _client(recipient_error=None):
    class Client:
        _max_attempts = 5

        def list_envelopes(self, from_date, start_position=0, count=100):
            envs = [
                {"envelopeId": f"env-{i}"}
                for i in range(start_position, min(start_position + 2, 5))
            ]
            return {"envelopes": envs, "totalSetSize": 5}

        def list_templates(self, start_position=0, count=100):
            items = [{"templateId": "t1"}] if start_position == 0 else []
            return {"envelopeTemplates": items, "totalSetSize": 1}

        def get_envelope_recipients(self, envelope_id):
            if recipient_error is not None and envelope_id == "env-2":
                raise recipient_error
            return {"signers": [{"recipientId": "1", "email": f"{envelope_id}@x.com"}]}

        def get_envelope_documents(self, envelope_id):
            return {"envelopeDocuments": [{"documentId": "1"}]}

    return Client()


EP = "/envelopes/env-2/recipients"


def test_404_is_skipped_recorded_and_job_completes(db, tmp_path):
    err = DocuSignNotFoundError("gone", status_code=404, endpoint=EP, envelope_id="env-2")
    svc = ExtractionService(db, _client(err), raw_base_dir=str(tmp_path))

    job = svc.start_scan({"from_date": "2024-01-01"})
    svc._execute_scan(job.id)
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED

    counts = svc.jobs.get_latest_checkpoint(job.id).cursor["_counts"]
    assert counts["recipients"] == 4
    assert counts["recipients_failed"] == 1
    assert counts["documents"] == 5

    rows = db.query(FailedExternalCall).all()
    assert len(rows) == 1
    assert rows[0].status_code == 404
    assert "env-2" in rows[0].endpoint
    assert str(rows[0].job_id) == str(job.id)
    assert rows[0].retry_count == 0


def test_rate_limit_exhausted_fails_job_then_resume_completes(db, tmp_path):
    err = DocuSignRateLimitError("slow down", retry_after=1, endpoint=EP, envelope_id="env-2")
    svc = ExtractionService(db, _client(err), raw_base_dir=str(tmp_path))

    job = svc.start_scan({"from_date": "2024-01-01"})
    svc._execute_scan(job.id)
    db.refresh(job)

    assert job.status == JobStatus.FAILED
    row = db.query(FailedExternalCall).one()
    assert row.status_code == 429
    assert row.retry_count == 4

    # DocuSign recovers; resume from the saved checkpoint
    svc2 = ExtractionService(db, _client(None), raw_base_dir=str(tmp_path))
    svc2._execute_scan(job.id)
    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    counts = svc2.jobs.get_latest_checkpoint(job.id).cursor["_counts"]
    assert counts["recipients"] == 5
    assert "recipients_failed" not in counts


def test_network_error_fails_job_and_is_recorded(db, tmp_path):
    err = DocuSignAPIError("network down", endpoint=EP, envelope_id="env-2")
    svc = ExtractionService(db, _client(err), raw_base_dir=str(tmp_path))

    job = svc.start_scan({"from_date": "2024-01-01"})
    svc._execute_scan(job.id)
    db.refresh(job)

    assert job.status == JobStatus.FAILED
    row = db.query(FailedExternalCall).one()
    assert row.status_code is None