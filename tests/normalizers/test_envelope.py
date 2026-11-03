
from datetime import datetime

from app.normalizers.base import parse_dt
from app.normalizers.envelope import EnvelopeNormalizer

n = EnvelopeNormalizer()


def base_env(**extra):
    return {
        "envelopeId": "env-1",
        "status": "completed",
        "emailSubject": "Please sign",
        "createdDateTime": "2026-10-01T10:00:00.1234567Z",
        "sentDateTime": "2026-10-01T10:05:00Z",
        "completedDateTime": "",
        "sender": {
            "userId": "u1",
            "userName": "Ann",
            "email": "ann@x.com",
        },
        **extra,
    }


def normalize_one(envelope):
    """Helper to normalize one envelope using the standard interface."""
    result = n.normalize([envelope])
    return result["envelopes"][0]


def test_basic_fields():
    row = normalize_one(base_env())

    assert row["envelope_id"] == "env-1"
    assert row["status"] == "completed"
    assert row["sender_email"] == "ann@x.com"
    assert isinstance(row["created_at"], datetime)
    assert row["custom_fields"] == {}


def test_empty_and_missing_dates_become_none():
    row = normalize_one(base_env())

    assert row["completed_at"] is None
    assert row["voided_at"] is None


def test_custom_fields_text_and_list():
    env = base_env(
        customFields={
            "textCustomFields": [
                {"name": "Dept", "value": "HR"}
            ],
            "listCustomFields": [
                {"name": "Region", "value": "APAC"}
            ],
        }
    )

    row = normalize_one(env)

    assert row["custom_fields"] == {
        "Dept": "HR",
        "Region": "APAC",
    }


def test_missing_sender_does_not_crash():
    env = base_env()
    del env["sender"]

    row = normalize_one(env)

    assert row["sender_user_id"] is None
    assert row["sender_name"] is None
    assert row["sender_email"] is None


def test_parse_dt_garbage():
    assert parse_dt("not-a-date") is None
    assert parse_dt(None) is None


def test_missing_envelope_id_is_skipped():
    env = {"status": "completed"}

    result = n.normalize([env])

    assert result == {"envelopes": []}


def test_multiple_envelopes():
    result = n.normalize([
        base_env(),
        base_env(envelopeId="env-2"),
    ])

    assert len(result["envelopes"]) == 2
    assert result["envelopes"][1]["envelope_id"] == "env-2"
