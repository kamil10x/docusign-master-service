import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.normalization as api
from app.db.session import get_db
from app.services.normalization_service import (
    JobNotFoundError,
    JobNotReadyError,
    NormalizationOutcome,
    RawDataMissingError,
)

JOB_ID = str(uuid.uuid4())

OUTCOME = NormalizationOutcome(
    data={"envelopes": [{"id": "e1"}, {"id": "e2"}], "recipients": [{"id": "r1"}]},
    exports={
        "envelopes": {
            "parquet": f"normalized/{JOB_ID}/envelopes.parquet",
            "json": f"normalized/{JOB_ID}/envelopes.json",
        }
    },
)


@pytest.fixture
def client():
    """Router-only app (no HMAC middleware), like tests/test_hmac.py does."""
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_db] = lambda: None
    api._active_jobs.clear()
    yield TestClient(app)
    api._active_jobs.clear()


@pytest.fixture
def patch_service(monkeypatch):
    def _patch(outcome=None, error=None):
        class FakeService:
            def __init__(self, db):
                pass

            def run(self, job_id):
                if error is not None:
                    raise error
                return outcome

        monkeypatch.setattr(api, "NormalizationService", FakeService)

    return _patch


@pytest.fixture
def patch_job(monkeypatch):
    def _patch(job):
        class FakeJobs:
            def __init__(self, db):
                pass

            def get_job(self, job_id):
                return job

        monkeypatch.setattr(api, "JobService", FakeJobs)

    return _patch


class FakeStorage:
    bucket = "test-bucket"

    def __init__(self, names=None, fail=False):
        self.names, self.fail = names or [], fail

    def list_objects(self, prefix):
        if self.fail:
            raise RuntimeError("storage down")
        return [n for n in self.names if n.startswith(prefix)]


def _job(result=None, status="completed"):
    return SimpleNamespace(status=status, result=result)


EXPORT_NAMES = [
    f"normalized/{JOB_ID}/envelopes.parquet",
    f"normalized/{JOB_ID}/envelopes.json",
]


# ------------------------------------------------------------------- POST
def test_run_returns_counts_and_exports_without_data(client, patch_service):
    patch_service(outcome=OUTCOME)
    r = client.post(f"/api/normalization/{JOB_ID}")
    assert r.status_code == 200
    body = r.json()
    assert body["record_counts"] == {"envelopes": 2, "recipients": 1}
    assert body["exports"]["envelopes"]["parquet"].endswith("envelopes.parquet")
    assert "data" not in body


def test_run_include_data_returns_rows(client, patch_service):
    patch_service(outcome=OUTCOME)
    r = client.post(f"/api/normalization/{JOB_ID}?include_data=true")
    assert r.json()["data"]["envelopes"][0] == {"id": "e1"}


def test_run_invalid_uuid_is_400(client):
    assert client.post("/api/normalization/not-a-uuid").status_code == 400


def test_run_unknown_job_is_404(client, patch_service):
    patch_service(error=JobNotFoundError("Job not found"))
    assert client.post(f"/api/normalization/{JOB_ID}").status_code == 404


def test_run_unfinished_scan_is_409(client, patch_service):
    patch_service(error=JobNotReadyError("not completed"))
    assert client.post(f"/api/normalization/{JOB_ID}").status_code == 409


def test_run_missing_raw_data_is_409(client, patch_service):
    patch_service(error=RawDataMissingError("No raw extraction data found"))
    r = client.post(f"/api/normalization/{JOB_ID}")
    assert r.status_code == 409 and "raw" in r.json()["detail"]


def test_run_other_value_error_is_400(client, patch_service):
    patch_service(error=ValueError("bad input"))
    assert client.post(f"/api/normalization/{JOB_ID}").status_code == 400


def test_run_unexpected_error_is_500_and_releases_guard(client, patch_service):
    patch_service(error=RuntimeError("boom"))
    r = client.post(f"/api/normalization/{JOB_ID}")
    assert r.status_code == 500 and "boom" in r.json()["detail"]
    assert JOB_ID not in api._active_jobs


def test_run_while_already_running_is_409(client, patch_service):
    patch_service(outcome=OUTCOME)
    api._active_jobs.add(JOB_ID)
    assert client.post(f"/api/normalization/{JOB_ID}").status_code == 409


def test_guard_is_released_after_success(client, patch_service):
    patch_service(outcome=OUTCOME)
    assert client.post(f"/api/normalization/{JOB_ID}").status_code == 200
    assert client.post(f"/api/normalization/{JOB_ID}").status_code == 200


# ----------------------------------------------------------------- status
def test_status_shape(client, patch_job, monkeypatch):
    patch_job(_job(result={"envelopes": [1, 2], "recipients": [1]}))
    monkeypatch.setattr(api, "minio_client", FakeStorage(EXPORT_NAMES))
    r = client.get(f"/api/normalization/{JOB_ID}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["normalized"] is True and body["running"] is False
    assert body["record_counts"] == {"envelopes": 2, "recipients": 1}
    assert body["exports_ready"] is True
    assert set(body["exports"]["envelopes"]) == {"parquet", "json"}


def test_status_not_normalized_yet(client, patch_job, monkeypatch):
    patch_job(_job(result=None))
    monkeypatch.setattr(api, "minio_client", FakeStorage())
    body = client.get(f"/api/normalization/{JOB_ID}/status").json()
    assert body["normalized"] is False and body["exports_ready"] is False


def test_status_reports_running(client, patch_job, monkeypatch):
    patch_job(_job())
    monkeypatch.setattr(api, "minio_client", FakeStorage())
    api._active_jobs.add(JOB_ID)
    assert client.get(f"/api/normalization/{JOB_ID}/status").json()["running"] is True


def test_status_survives_storage_outage(client, patch_job, monkeypatch):
    patch_job(_job(result={"envelopes": [1]}))
    monkeypatch.setattr(api, "minio_client", FakeStorage(fail=True))
    r = client.get(f"/api/normalization/{JOB_ID}/status")
    assert r.status_code == 200
    assert r.json()["exports"] is None and r.json()["exports_ready"] is None


def test_status_unknown_job_404(client, patch_job):
    patch_job(None)
    assert client.get(f"/api/normalization/{JOB_ID}/status").status_code == 404


# ---------------------------------------------------------------- results
def test_results_groups_files_by_table(client, patch_job, monkeypatch):
    patch_job(_job())
    monkeypatch.setattr(api, "minio_client", FakeStorage(EXPORT_NAMES))
    r = client.get(f"/api/normalization/{JOB_ID}/results")
    assert r.status_code == 200
    assert r.json()["bucket"] == "test-bucket"
    assert set(r.json()["files"]["envelopes"]) == {"parquet", "json"}


def test_results_404_when_no_output_yet(client, patch_job, monkeypatch):
    patch_job(_job())
    monkeypatch.setattr(api, "minio_client", FakeStorage())
    assert client.get(f"/api/normalization/{JOB_ID}/results").status_code == 404


def test_results_404_unknown_job(client, patch_job):
    patch_job(None)
    assert client.get(f"/api/normalization/{JOB_ID}/results").status_code == 404


def test_results_503_when_storage_down(client, patch_job, monkeypatch):
    patch_job(_job())
    monkeypatch.setattr(api, "minio_client", FakeStorage(fail=True))
    assert client.get(f"/api/normalization/{JOB_ID}/results").status_code == 503


def test_group_exports_ignores_foreign_and_odd_files():
    names = EXPORT_NAMES + [f"normalized/{JOB_ID}/readme.txt", "other/envelopes.json"]
    assert list(api._group_exports(JOB_ID, names)) == ["envelopes"]


# ------------------------------------------------------------------- HMAC
def test_real_app_rejects_unsigned_requests(monkeypatch):
    """Uses the real app (with HMACAuthMiddleware) to prove the routes are protected."""
    from app.config import settings
    from app.main import app as real_app

    monkeypatch.setattr(settings, "HMAC_ENABLED", True)
    monkeypatch.setattr(settings, "HMAC_SECRET_KEY_CORE", "core-secret")
    monkeypatch.setattr(settings, "HMAC_SECRET_KEY_ENGINEER", "eng-secret")

    c = TestClient(real_app)
    assert c.post(f"/api/normalization/{JOB_ID}").status_code == 401
    assert c.get(f"/api/normalization/{JOB_ID}/status").status_code == 401
    assert c.get(f"/api/normalization/{JOB_ID}/results").status_code == 401