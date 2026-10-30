
from app.db.models import JobStatus
from app.services.extraction_service import ExtractionService


class FakeClient:
    def __init__(self):
        self.env_starts = []

    def list_envelopes(self, from_date, start_position=0, count=100):
        self.env_starts.append(start_position)

        envelopes = [
            {"envelopeId": f"env-{i}"}
            for i in range(start_position, min(start_position + 2, 5))
        ]

        return {
            "envelopes": envelopes,
            "totalSetSize": 5,
        }

    def list_templates(self, start_position=0, count=100):
        templates = [
            {"templateId": "template-1"},
            {"templateId": "template-2"},
        ]

        return {
            "envelopeTemplates": templates[start_position:start_position + count],
            "totalSetSize": 2,
        }

    def get_envelope_recipients(self, envelope_id):
        return {
            "signers": [
                {"recipientId": "1", "email": f"{envelope_id}@example.com"}
            ]
        }

    def get_envelope_documents(self, envelope_id):
        return {
            "envelopeId": envelope_id,
            "envelopeDocuments": [
                {"documentId": "1", "name": "document.pdf"}
            ],
        }


def test_full_scan_completes(db, tmp_path):
    client = FakeClient()
    svc = ExtractionService(db, client, raw_base_dir=str(tmp_path))

    job = svc.start_scan({"from_date": "2024-01-01"})
    svc._execute_scan(job.id)

    db.refresh(job)

    assert job.status == JobStatus.COMPLETED
    assert job.updated_at is not None

    cp = svc.jobs.get_latest_checkpoint(job.id)

    assert cp is not None
    assert cp.resource_type == "completed"
    assert cp.cursor["_counts"] == {
        "envelopes": 5,
        "recipients": 5,
        "documents": 5,
        "templates": 2,
    }


def test_failure_then_resume_does_not_refetch_saved_pages(db, tmp_path):
    class FailingClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.fail_once = True

        def get_envelope_recipients(self, envelope_id):
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError("Temporary API failure")

            return super().get_envelope_recipients(envelope_id)

    client = FailingClient()
    svc = ExtractionService(db, client, raw_base_dir=str(tmp_path))

    job = svc.start_scan({"from_date": "2024-01-01"})

    svc._execute_scan(job.id)

    db.refresh(job)
    assert job.status == JobStatus.FAILED

    svc._execute_scan(job.id)

    db.refresh(job)
    assert job.status == JobStatus.COMPLETED

    # Previously saved envelope pages should not be fetched again.
    assert client.env_starts == [0, 2, 4]
