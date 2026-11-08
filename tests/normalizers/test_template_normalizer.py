
from datetime import datetime, timezone

from app.normalizers.template import TemplateNormalizer


def test_template_normalizer():
    records = [
        {
            "templateId": "temp-101",
            "name": "Employment Agreement",
            "created": "2026-10-30T10:00:00Z",
            "lastModified": "2026-11-01T12:30:00Z",
            "owner": {
                "userId": "user-1",
                "userName": "Kamil",
                "email": "kamil@example.com",
            },
            "shared": True,
        }
    ]

    result = TemplateNormalizer().normalize(records)

    rows = result["templates"]

    assert len(rows) == 1

    row = rows[0]

    assert row["template_id"] == "temp-101"
    assert row["name"] == "Employment Agreement"
    assert row["created"] == datetime(
        2026, 10, 30, 10, 0, tzinfo=timezone.utc
    )
    assert row["last_modified"] == datetime(
        2026, 11, 1, 12, 30, tzinfo=timezone.utc
    )
    assert row["owner_user_id"] == "user-1"
    assert row["owner_name"] == "Kamil"
    assert row["owner_email"] == "kamil@example.com"
    assert row["shared"] is True


def test_template_normalizer_missing_optional_fields():
    records = [
        {
            "templateId": "temp-102",
        }
    ]

    result = TemplateNormalizer().normalize(records)

    row = result["templates"][0]

    assert row["template_id"] == "temp-102"
    assert row["name"] is None
    assert row["created"] is None
    assert row["last_modified"] is None
    assert row["owner_user_id"] is None
    assert row["owner_name"] is None
    assert row["owner_email"] is None
    assert row["shared"] is None


def test_template_normalizer_invalid_records():
    records = [
        None,
        {},
        {"name": "Missing template ID"},
    ]

    result = TemplateNormalizer().normalize(records)

    assert result["templates"] == []
