from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.models import Job
from app.services import scan_runner


class _FakeService:
    ran: list = []

    def __init__(self, db, client):
        pass

    def run_scan(self, job_id):
        _FakeService.ran.append(job_id)


@pytest.fixture
def runner(db, monkeypatch):
    _FakeService.ran = []

    async def account():
        return SimpleNamespace(base_uri="https://demo.docusign.net", account_id="acc")

    monkeypatch.setattr(scan_runner, "SessionLocal", lambda: db)
    monkeypatch.setattr(scan_runner, "auth_client", SimpleNamespace(get_account_info=account))
    monkeypatch.setattr(scan_runner, "DocuSignClient", lambda **kw: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(scan_runner, "ExtractionService", _FakeService)
    return _FakeService


def _job(db, status, age_minutes=0):
    job = Job(job_type="scan", status=status, params={})
    job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    db.add(job)
    db.commit()
    db.refresh(job)
    return str(job.id)


def test_failed_job_can_be_resumed(db, runner):
    job_id = _job(db, "failed")
    scan_runner.run_scan_in_background(job_id)
    assert runner.ran == [job_id]


def test_completed_job_is_not_rerun(db, runner):
    job_id = _job(db, "completed")
    scan_runner.run_scan_in_background(job_id)
    assert runner.ran == []


def test_running_job_with_fresh_heartbeat_is_not_started_twice(db, runner):
    job_id = _job(db, "running", age_minutes=0)
    scan_runner.run_scan_in_background(job_id)
    assert runner.ran == []


def test_running_job_with_stale_heartbeat_can_be_resumed(db, runner):
    job_id = _job(db, "running", age_minutes=24 * 60)
    scan_runner.run_scan_in_background(job_id)
    assert runner.ran == [job_id]