from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import maintenance
from app.db.models import AuditLog, FailedExternalCall, Job
from app.db.session import get_db


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(maintenance.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _job(db, status="pending", job_type="scan", updated_at=None, result=None):
    job = Job(job_type=job_type, status=status, params={}, result=result)
    if updated_at is not None:
        job.updated_at = updated_at
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _old(days=30):
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_list_jobs_filters_by_status(client, db):
    _job(db, status="running")
    _job(db, status="failed")

    body = client.get("/api/maintenance/jobs", params={"status": "failed"}).json()

    assert body["count"] == 1
    assert body["jobs"][0]["status"] == "failed"


def test_recover_stale_dry_run_changes_nothing(client, db):
    stale = _job(db, status="running", updated_at=_old(3))

    body = client.post("/api/maintenance/recover-stale-jobs?dry_run=true").json()

    assert body["job_ids"] == [str(stale.id)]
    db.refresh(stale)
    assert stale.status == "running"


def test_recover_stale_marks_failed_and_keeps_fresh_jobs(client, db):
    stale = _job(db, status="running", updated_at=_old(3))
    fresh = _job(db, status="running", updated_at=datetime.now(timezone.utc))

    body = client.post("/api/maintenance/recover-stale-jobs").json()

    assert body["count"] == 1
    db.refresh(stale)
    db.refresh(fresh)
    assert stale.status == "failed"
    assert "no heartbeat" in stale.error_message
    assert fresh.status == "running"
    assert db.query(AuditLog).filter_by(action="job_recovered_stale").count() == 1


def test_failed_calls_list_and_resolve(client, db):
    call = FailedExternalCall(service="docusign", method="GET", endpoint="/envelopes/x", status_code=404)
    db.add(call)
    db.commit()

    listed = client.get("/api/maintenance/failed-calls", params={"resolved": False}).json()
    assert listed["count"] == 1

    resolved = client.post(f"/api/maintenance/failed-calls/{call.id}/resolve").json()
    assert resolved["resolved"] is True

    listed = client.get("/api/maintenance/failed-calls", params={"resolved": False}).json()
    assert listed["count"] == 0


def test_resolve_unknown_failed_call_is_404(client):
    assert client.post("/api/maintenance/failed-calls/999/resolve").status_code == 404


def _raw_dir(tmp_path, job):
    d = tmp_path / str(job.id) / "envelopes"
    d.mkdir(parents=True)
    (d / "page_000000.json").write_text("{}")
    return tmp_path / str(job.id)


def test_cleanup_dry_run_keeps_files(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "RAW_BASE_DIR", tmp_path)
    job = _job(db, status="failed", updated_at=_old())
    path = _raw_dir(tmp_path, job)

    body = client.post("/api/maintenance/cleanup").json()

    assert body["dry_run"] is True
    assert body["removed_jobs"] == [str(job.id)]
    assert path.exists()


def test_cleanup_deletes_old_finished_jobs(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "RAW_BASE_DIR", tmp_path)
    job = _job(db, status="failed", updated_at=_old())
    path = _raw_dir(tmp_path, job)

    body = client.post("/api/maintenance/cleanup?dry_run=false").json()

    assert body["removed_jobs"] == [str(job.id)]
    assert not path.exists()
    assert db.query(AuditLog).filter_by(action="raw_data_cleaned").count() == 1


def test_cleanup_skips_unnormalized_completed_scan(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "RAW_BASE_DIR", tmp_path)
    job = _job(db, status="completed", updated_at=_old(), result=None)
    path = _raw_dir(tmp_path, job)

    body = client.post("/api/maintenance/cleanup?dry_run=false").json()

    assert body["skipped_unnormalized"] == [str(job.id)]
    assert path.exists()


def test_cleanup_ignores_recent_and_running_jobs(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(maintenance, "RAW_BASE_DIR", tmp_path)
    running = _job(db, status="running", updated_at=_old())
    recent = _job(db, status="failed", updated_at=datetime.now(timezone.utc))
    _raw_dir(tmp_path, running)
    _raw_dir(tmp_path, recent)

    body = client.post("/api/maintenance/cleanup?dry_run=false").json()

    assert body["removed_jobs"] == []