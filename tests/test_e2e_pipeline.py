"""End-to-end pipeline tests: scan -> normalize -> export to MinIO -> validate.

Everything runs for real (ExtractionService, raw pages on disk, normalizers,
NormalizationService, export, audit trail, normalization API) except the two
outside systems, which are faked:
  * DocuSign  -> E2EClient (deterministic fake data)
  * MinIO     -> InMemoryMinio (a dict instead of a server)
"""
import io
import json
import shutil

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import normalization
from app.db.session import get_db
from app.services.audit_service import AuditService
from app.services.extraction_service import ExtractionService
from app.services.job_service import JobService
from app.services.minio_client import MinioClient
from app.services.normalization_service import (
    JobNotReadyError,
    NormalizationService,
    RawDataMissingError,
)
from app.services.scan_stages import JobStatus

PARAMS = {"from_date": "2024-01-01"}
TABLES = ("envelopes", "recipients", "documents", "templates")

# What the fake DocuSign account contains
#   5 envelopes; env-0 has 1 signer + 2 CCs, the rest 1 signer  -> 7 recipient rows
#   env-0 has 3 documents, the rest 1                           -> 7 document rows
#   2 templates
EXPECTED_ROWS = {"envelopes": 5, "recipients": 7, "documents": 7, "templates": 2}
# The scan counts API *calls/pages' items*, not normalized rows, so it differs
EXPECTED_SCAN_COUNTS = {"envelopes": 5, "recipients": 5, "documents": 5, "templates": 2}


# ---------------------------------------------------------------- fakes
class E2EClient:
    """Fake DocuSign client. fail_recipients_on raises ONCE (to test resume)."""

    _max_attempts = 3

    def __init__(self, fail_recipients_on=None):
        self._fail_recipients_on = fail_recipients_on

    def list_envelopes(self, from_date, start_position=0, count=100):
        envs = [
            {
                "envelopeId": f"env-{i}",
                "status": "completed",
                "emailSubject": f"Contract {i}",
                "createdDateTime": "2024-02-01T09:00:00.0000000Z",
                "sentDateTime": "2024-02-01T10:00:00.0000000Z",
                "completedDateTime": "2024-02-02T11:30:00.0000000Z",
                "customFields": {
                    "textCustomFields": [{"name": "department", "value": "legal"}],
                    "listCustomFields": [],
                },
            }
            for i in range(start_position, min(start_position + 2, 5))
        ]
        return {"envelopes": envs, "totalSetSize": 5}

    def list_templates(self, start_position=0, count=100):
        items = [
            {"templateId": "tpl-1", "name": "NDA", "description": "Standard NDA"},
            {"templateId": "tpl-2", "name": "MSA", "description": "Master agreement"},
        ]
        return {"envelopeTemplates": items[start_position:start_position + count],
                "totalSetSize": 2}

    def get_envelope_recipients(self, envelope_id):
        if envelope_id == self._fail_recipients_on:
            self._fail_recipients_on = None
            raise RuntimeError("boom: recipients")
        data = {
            "signers": [{
                "recipientId": "1",
                "name": f"Signer {envelope_id}",
                "email": f"{envelope_id}@example.com",
                "status": "completed",
                "routingOrder": "1",
            }],
            "carbonCopies": [],
        }
        if envelope_id == "env-0":
            data["carbonCopies"] = [
                {"recipientId": str(n), "name": f"CC {n}", "email": f"cc{n}@example.com",
                 "status": "completed", "routingOrder": str(n)}
                for n in (2, 3)
            ]
        return data

    def get_envelope_documents(self, envelope_id):
        n_docs = 3 if envelope_id == "env-0" else 1
        return {
            "envelopeId": envelope_id,
            "envelopeDocuments": [
                {"documentId": str(n), "name": f"doc{n}.pdf", "type": "content",
                 "pages": "2", "order": str(n)}
                for n in range(1, n_docs + 1)
            ],
        }


class InMemoryMinio(MinioClient):
    """MinioClient with a dict as storage. Path helpers are inherited, so paths are the real ones."""

    def __init__(self):
        self.client = None
        self.bucket = "test-bucket"
        self._bucket_ready = True
        self.objects: dict[str, bytes] = {}

    def upload_bytes(self, object_name, data, content_type="application/octet-stream"):
        self.objects[object_name] = data
        return object_name

    def download_bytes(self, object_name):
        return self.objects[object_name]

    def object_exists(self, object_name):
        return object_name in self.objects

    def list_objects(self, prefix):
        return sorted(n for n in self.objects if n.startswith(prefix))


@pytest.fixture
def fake_minio():
    return InMemoryMinio()


@pytest.fixture
def api(db, fake_minio, monkeypatch):
    monkeypatch.setattr(normalization, "minio_client", fake_minio)
    app = FastAPI()
    app.include_router(normalization.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


# -------------------------------------------------------------- helpers
def _scan(db, client, tmp_path, job=None):
    svc = ExtractionService(db, client, raw_base_dir=str(tmp_path))
    job = job or svc.start_scan(PARAMS)
    svc._execute_scan(job.id)
    db.refresh(job)
    return svc, job


def _normalize(db, job, tmp_path, minio):
    return NormalizationService(db, raw_base_dir=str(tmp_path), minio=minio).run(str(job.id))


def _audit_actions(db, job):
    _, rows = AuditService(db).query(job_id=job.id, limit=200)
    return [r.action for r in reversed(rows)]  # query() is newest-first


def _parquet_rows(raw: bytes) -> int:
    pq = pytest.importorskip("pyarrow.parquet")
    return pq.read_table(io.BytesIO(raw)).num_rows


def _json_rows(raw: bytes):
    payload = json.loads(raw)  # must be valid JSON
    return len(payload) if isinstance(payload, list) else None


# ----------------------------------------------------------------- tests
def test_full_pipeline_scan_normalize_export_validate(db, tmp_path, fake_minio):
    # 1. scan
    svc, job = _scan(db, E2EClient(), tmp_path)
    assert job.status == JobStatus.COMPLETED
    assert svc.jobs.get_latest_checkpoint(job.id).cursor["_counts"] == EXPECTED_SCAN_COUNTS

    # 2. normalize + export
    outcome = _normalize(db, job, tmp_path, fake_minio)

    # 3. validate: row counts
    for table in TABLES:
        assert outcome.record_counts[table] == EXPECTED_ROWS[table], table

    # 4. validate: what is stored in the DB equals what was returned
    db.refresh(job)
    stored = {t: len(rows) for t, rows in job.result.items() if isinstance(rows, list)}
    assert stored == outcome.record_counts

    # 5. validate: every exported object exists, is under this job's prefix,
    #    and holds exactly as many rows as the normalized table
    prefix = MinioClient.job_prefix(str(job.id))
    assert set(TABLES) <= set(outcome.exports)
    for table, files in outcome.exports.items():
        count = outcome.record_counts[table]
        for fmt, path in files.items():
            assert path.startswith(prefix), path
            assert fake_minio.object_exists(path), path
            raw = fake_minio.download_bytes(path)
            if fmt == "parquet":
                assert _parquet_rows(raw) == count, f"{table} parquet"
            elif fmt == "json":
                rows = _json_rows(raw)
                assert rows is None or rows == count, f"{table} json"

    # 6. validate: audit trail tells the whole story
    actions = _audit_actions(db, job)
    assert set(actions) == {
        "scan_created", "scan_started", "scan_completed",
        "normalization_started", "normalization_completed",
    }
    assert len(actions) == 5                       # nothing duplicated
    assert actions[0] == "scan_created"            # the story starts here...
    assert actions[-1] == "normalization_completed"  # ...and ends here


def test_interrupted_and_resumed_scan_gives_same_result_as_clean_scan(db, tmp_path):
    clean_minio, resumed_minio = InMemoryMinio(), InMemoryMinio()

    _, clean_job = _scan(db, E2EClient(), tmp_path)
    clean = _normalize(db, clean_job, tmp_path, clean_minio)

    flaky = E2EClient(fail_recipients_on="env-3")
    svc, job = _scan(db, flaky, tmp_path)
    assert job.status == JobStatus.FAILED
    _, job = _scan(db, flaky, tmp_path, job=job)  # resume
    assert job.status == JobStatus.COMPLETED
    resumed = _normalize(db, job, tmp_path, resumed_minio)

    assert resumed.record_counts == clean.record_counts == {
        **clean.record_counts, **EXPECTED_ROWS}
    assert set(resumed.exports) == set(clean.exports)
    assert len(resumed_minio.objects) == len(clean_minio.objects)


def test_normalization_refuses_unfinished_job(db, tmp_path, fake_minio):
    job = JobService(db).create_job("scan", PARAMS)  # still pending

    with pytest.raises(JobNotReadyError):
        _normalize(db, job, tmp_path, fake_minio)

    assert fake_minio.objects == {}  # nothing was exported


def test_normalization_refuses_when_raw_data_is_gone(db, tmp_path, fake_minio):
    _, job = _scan(db, E2EClient(), tmp_path)
    shutil.rmtree(tmp_path / str(job.id))  # e.g. removed by /api/maintenance/cleanup

    with pytest.raises(RawDataMissingError):
        _normalize(db, job, tmp_path, fake_minio)

    assert fake_minio.objects == {}


def test_normalization_rerun_is_idempotent(db, tmp_path, fake_minio):
    _, job = _scan(db, E2EClient(), tmp_path)

    first = _normalize(db, job, tmp_path, fake_minio)
    objects_after_first = set(fake_minio.objects)
    second = _normalize(db, job, tmp_path, fake_minio)

    assert second.record_counts == first.record_counts
    assert second.exports == first.exports  # deterministic paths
    assert set(fake_minio.objects) == objects_after_first  # overwritten, not duplicated


def test_api_status_and_results_before_and_after_normalization(db, tmp_path, fake_minio, api):
    _, job = _scan(db, E2EClient(), tmp_path)
    job_id = str(job.id)

    # before normalization
    status = api.get(f"/api/normalization/{job_id}/status").json()
    assert status["job_status"] == "completed"
    assert status["normalized"] is False
    assert status["exports_ready"] is False
    assert api.get(f"/api/normalization/{job_id}/results").status_code == 404

    # after normalization
    outcome = _normalize(db, job, tmp_path, fake_minio)

    status = api.get(f"/api/normalization/{job_id}/status").json()
    assert status["normalized"] is True
    assert status["exports_ready"] is True
    assert status["record_counts"] == outcome.record_counts

    results = api.get(f"/api/normalization/{job_id}/results").json()
    assert results["bucket"] == "test-bucket"
    for table, files in outcome.exports.items():
        assert results["files"][table] == files


def test_api_error_codes(db, api):
    unfinished = JobService(db).create_job("scan", PARAMS)

    assert api.post("/api/normalization/not-a-uuid").status_code == 400
    assert api.post("/api/normalization/00000000-0000-0000-0000-000000000000").status_code == 404
    assert api.post(f"/api/normalization/{unfinished.id}").status_code == 409
    assert api.get("/api/normalization/00000000-0000-0000-0000-000000000000/status").status_code == 404