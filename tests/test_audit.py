from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import audit
from app.core.hmac_auth import HMACAuthMiddleware
from app.db.models import AuditLog, Job
from app.db.session import get_db
from app.services.audit_service import AuditService
from app.services.extraction_service import ExtractionService
from app.services.job_service import JobService


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(audit.router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _job(db):
    job = Job(job_type="scan", status="pending", params={})
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _log(db, action, *, job_id=None, actor=None, created_at=None):
    row = AuditLog(action=action, job_id=job_id, actor=actor, details={})
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.commit()
    return row


# ---------------------------------------------------------------- service
def test_log_event_writes_row(db):
    job = _job(db)

    row = AuditService(db).log_event(
        "scan_started", job_id=job.id, actor="key-1", details={"stage": "envelopes"}
    )

    assert row is not None and row.id is not None
    saved = db.query(AuditLog).one()
    assert saved.action == "scan_started"
    assert saved.actor == "key-1"
    assert saved.job_id == job.id
    assert saved.details == {"stage": "envelopes"}


def test_log_event_serializes_datetime_details(db):
    AuditService(db).log_event("x", details={"at": datetime(2026, 1, 1, tzinfo=timezone.utc)})

    assert isinstance(db.query(AuditLog).one().details["at"], str)


def test_log_event_never_raises(db, monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "commit", boom)

    assert AuditService(db).log_event("x") is None


def test_query_filters(db):
    job_a, job_b = _job(db), _job(db)
    _log(db, "scan_started", job_id=job_a.id, actor="k1")
    _log(db, "scan_completed", job_id=job_a.id, actor="k2")
    _log(db, "scan_started", job_id=job_b.id, actor="k1")

    svc = AuditService(db)
    assert svc.query(job_id=job_a.id)[0] == 2
    assert svc.query(action="scan_started")[0] == 2
    assert svc.query(actor="k2")[0] == 1
    assert svc.query(job_id=job_a.id, action="scan_started")[0] == 1


def test_query_date_range_and_order_and_paging(db):
    now = datetime.now(timezone.utc)
    _log(db, "old", created_at=now - timedelta(days=10))
    _log(db, "mid", created_at=now - timedelta(days=5))
    _log(db, "new", created_at=now - timedelta(days=1))

    svc = AuditService(db)

    total, rows = svc.query(since=now - timedelta(days=6))
    assert total == 2
    assert [r.action for r in rows] == ["new", "mid"]  # newest first

    total, rows = svc.query(until=now - timedelta(days=6))
    assert [r.action for r in rows] == ["old"]

    total, rows = svc.query(limit=1, offset=1)
    assert total == 3
    assert [r.action for r in rows] == ["mid"]


# ------------------------------------------------------------------ hooks
def test_job_service_add_audit_log_records_actor(db):
    jobs = JobService(db)
    job = jobs.create_job("scan", {})

    jobs.add_audit_log(job.id, "something", {"a": 1}, actor="key-1")

    row = db.query(AuditLog).filter_by(job_id=job.id).one()
    assert row.action == "something"
    assert row.actor == "key-1"


def test_start_scan_logs_scan_created(db):
    job = ExtractionService(db, client=None).start_scan({"from_date": "2026-01-01"})

    row = db.query(AuditLog).filter_by(job_id=job.id, action="scan_created").one()
    assert row.details["params"] == {"from_date": "2026-01-01"}


def test_record_failed_call_is_audited(db):
    jobs = JobService(db)
    job = jobs.create_job("scan", {})

    call = jobs.record_failed_call(
        "docusign", "get", "/envelopes/x", job_id=job.id, status_code=404
    )

    row = db.query(AuditLog).filter_by(action="failed_call_recorded").one()
    assert row.details["failed_call_id"] == call.id
    assert row.details["status_code"] == 404


# -------------------------------------------------------------------- API
def test_api_lists_and_filters(client, db):
    job = _job(db)
    _log(db, "scan_started", job_id=job.id, actor="k1")
    _log(db, "scan_completed", job_id=job.id, actor="k1")
    _log(db, "other")

    body = client.get("/api/audit", params={"job_id": str(job.id)}).json()
    assert body["total"] == 2
    assert {log["action"] for log in body["logs"]} == {"scan_started", "scan_completed"}

    body = client.get("/api/audit", params={"action": "other"}).json()
    assert body["total"] == 1


def test_api_paging(client, db):
    for i in range(5):
        _log(db, f"a{i}")

    body = client.get("/api/audit", params={"limit": 2, "offset": 2}).json()

    assert body["total"] == 5
    assert body["count"] == 2


def test_api_date_range(client, db):
    now = datetime.now(timezone.utc)
    _log(db, "old", created_at=now - timedelta(days=10))
    _log(db, "new", created_at=now - timedelta(days=1))

    body = client.get(
        "/api/audit", params={"since": (now - timedelta(days=3)).isoformat()}
    ).json()

    assert [log["action"] for log in body["logs"]] == ["new"]


def test_api_rejects_bad_input(client):
    assert client.get("/api/audit", params={"job_id": "nope"}).status_code == 400
    assert client.get("/api/audit", params={"limit": 0}).status_code == 422
    bad_range = {"since": "2026-02-01T00:00:00Z", "until": "2026-01-01T00:00:00Z"}
    assert client.get("/api/audit", params=bad_range).status_code == 400


def test_api_requires_hmac_auth(db):
    app = FastAPI()
    app.add_middleware(HMACAuthMiddleware)
    app.include_router(audit.router)
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).get("/api/audit")

    assert response.status_code in (401, 403)