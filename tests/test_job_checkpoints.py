"""Needs a `db` fixture (SQLAlchemy Session on your test Postgres) in conftest.py."""
from app.services.job_service import JobService


def test_latest_checkpoint_none_for_new_job(db):
    svc = JobService(db)
    job = svc.create_job("scan", {})
    assert svc.get_latest_checkpoint(job.id) is None


def test_latest_checkpoint_returns_most_recent(db):
    svc = JobService(db)
    job = svc.create_job("scan", {})

    svc.save_checkpoint(
        job.id,
        "envelopes",
        {"start_position": 100},
        {"envelopes": 100},
    )

    svc.save_checkpoint(
        job.id,
        "envelopes",
        {"start_position": 200},
        {"envelopes": 200},
    )

    latest = svc.get_latest_checkpoint(job.id)

    assert latest is not None
    assert latest.resource_type == "envelopes"
    assert latest.cursor["start_position"] == 200
    assert latest.cursor["_counts"]["envelopes"] == 200