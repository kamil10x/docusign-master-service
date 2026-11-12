import uuid
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import normalization_service as ns

JOB_ID = str(uuid.uuid4())


class FakeMinio:
    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail

    def upload_bytes(self, name, data, content_type="application/octet-stream"):
        if self.fail:
            raise RuntimeError("minio is down")
        self.store[name] = data
        return name


class FakeNormalizer:
    def __init__(self, result):
        self.result = result

    def normalize(self, records):
        return {table: list(rows) for table, rows in self.result.items()}


class FakeWriter:
    pages: dict = {}
    root = Path(".")  # exists, so the raw-data guard passes by default

    def __init__(self, job_id, base_dir):
        pass

    def list_pages(self, resource):
        return list(self.pages.get(resource, {}))

    def read_page(self, path):
        for pages in self.pages.values():
            if path in pages:
                return pages[path]


@pytest.fixture
def make_service(monkeypatch):
    def _make(job, minio):
        class FakeJobs:
            def __init__(self, db):
                self.logs = []

            def get_job(self, job_id):
                return job

            def add_audit_log(self, job_id, action, details):
                self.logs.append((action, details))

        monkeypatch.setattr(ns, "JobService", FakeJobs)
        monkeypatch.setattr(ns, "RawPageWriter", FakeWriter)
        db = MagicMock()
        service = ns.NormalizationService(db, minio=minio)
        service.normalizers = {
            "envelopes": FakeNormalizer({
                "envelopes": [{"envelope_id": "e1", "created": datetime(2026, 1, 1, tzinfo=timezone.utc)}],
            }),
            "recipients": FakeNormalizer({
                "recipients": [{"recipient_id": "r1"}],
                "recipient_extras": [{"x": 1}],
            }),
            "documents": FakeNormalizer({"documents": []}),
            "templates": FakeNormalizer({"templates": [{"template_id": "t1"}]}),
        }
        return service, db

    return _make


def _completed_job():
    return SimpleNamespace(status="completed", result=None)


def test_run_normalizes_stores_and_exports(make_service):
    job, minio = _completed_job(), FakeMinio()
    service, db = make_service(job, minio)

    outcome = service.run(JOB_ID)

    assert outcome.record_counts == {
        "envelopes": 1, "recipients": 1, "recipient_extras": 1, "documents": 0, "templates": 1,
    }
    # datetime became a JSON-safe string in Job.result (the old JSONB bug)
    assert isinstance(job.result["envelopes"][0]["created"], str)
    db.commit.assert_called_once()
    # empty "documents" table is not exported; every other table is, in both formats
    assert set(outcome.exports) == {"envelopes", "recipients", "recipient_extras", "templates"}
    assert f"normalized/{JOB_ID}/envelopes.parquet" in minio.store
    assert f"normalized/{JOB_ID}/envelopes.json" in minio.store

    action, details = service.jobs.logs[-1]
    assert action == "normalization_completed"
    assert details["exports"] == outcome.exports
    assert details["record_counts"]["templates"] == 1


def test_normalize_job_still_returns_plain_tables(make_service):
    service, _ = make_service(_completed_job(), FakeMinio())
    data = service.normalize_job(JOB_ID)
    assert set(data) == {"envelopes", "recipients", "recipient_extras", "documents", "templates"}


def test_unknown_job_raises_not_found(make_service):
    service, _ = make_service(None, FakeMinio())
    with pytest.raises(ns.JobNotFoundError):
        service.run(JOB_ID)


def test_unfinished_scan_raises_not_ready(make_service):
    service, _ = make_service(SimpleNamespace(status="running", result=None), FakeMinio())
    with pytest.raises(ns.JobNotReadyError):
        service.run(JOB_ID)


def test_errors_are_still_value_errors_for_old_callers():
    assert issubclass(ns.JobNotFoundError, ValueError)
    assert issubclass(ns.JobNotReadyError, ValueError)
    assert issubclass(ns.RawDataMissingError, ValueError)


def test_missing_raw_data_raises_instead_of_returning_zeros(make_service, monkeypatch):
    job, minio = _completed_job(), FakeMinio()
    service, db = make_service(job, minio)
    monkeypatch.setattr(FakeWriter, "root", Path("no-such-raw-dir-xyz"))

    with pytest.raises(ns.RawDataMissingError):
        service.run(JOB_ID)

    assert job.result is None
    assert minio.store == {}
    db.commit.assert_not_called()


def test_export_failure_is_audited_and_reraised(make_service):
    job = _completed_job()
    service, db = make_service(job, FakeMinio(fail=True))

    with pytest.raises(RuntimeError, match="minio is down"):
        service.run(JOB_ID)

    assert job.result is not None  # normalized data was committed before the export
    db.rollback.assert_called_once()
    action, details = service.jobs.logs[-1]
    assert action == "normalization_failed"
    assert "minio is down" in details["error"]


def test_read_resource_pages_extracts_records_per_resource(make_service):
    service, _ = make_service(_completed_job(), FakeMinio())
    FakeWriter.pages = {
        "envelopes": {"p1": {"envelopes": [{"envelopeId": "a"}, "junk"]}},
        "templates": {"p2": {"envelopeTemplates": [{"templateId": "t"}]}},
        "recipients": {"p3": {"envelopeId": "a", "signers": []}},
        "documents": {"p4": ["not-a-dict"]},
    }
    writer = ns.RawPageWriter(JOB_ID, "x")

    assert service._read_resource_pages(writer, "envelopes") == [{"envelopeId": "a"}]
    assert service._read_resource_pages(writer, "templates") == [{"templateId": "t"}]
    assert service._read_resource_pages(writer, "recipients") == [{"envelopeId": "a", "signers": []}]
    assert service._read_resource_pages(writer, "documents") == []
    assert service._read_resource_pages(writer, "unknown") == []
    FakeWriter.pages = {}