import io
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pandas as pd

from app.utils.serializers import rows_to_json_bytes, rows_to_parquet_bytes

REF = uuid4()
CREATED = datetime(2026, 1, 1, 10, 30, tzinfo=timezone.utc)

ROWS = [
    {
        "id": "env-1",
        "created": CREATED,
        "due": date(2026, 2, 1),
        "amount": Decimal("12.50"),
        "ref": REF,
        "custom_fields": {"region": "EU", "tags": []},
        "empty": {},
    }
]


def _read(data: bytes) -> pd.DataFrame:
    return pd.read_parquet(io.BytesIO(data))


def test_json_handles_datetime_date_decimal_uuid():
    data = json.loads(rows_to_json_bytes(ROWS))
    assert data[0]["created"].startswith("2026-01-01T10:30")
    assert data[0]["due"] == "2026-02-01"
    assert data[0]["amount"] == "12.50"
    assert data[0]["ref"] == str(REF)


def test_json_keeps_unicode_readable():
    raw = rows_to_json_bytes([{"name": "Zoë"}]).decode("utf-8")
    assert "Zoë" in raw


def test_parquet_round_trip_with_special_types():
    df = _read(rows_to_parquet_bytes(ROWS))
    assert len(df) == 1
    assert df.loc[0, "id"] == "env-1"
    assert pd.Timestamp(df.loc[0, "created"]) == pd.Timestamp(CREATED)
    assert df.loc[0, "ref"] == str(REF)
    assert json.loads(df.loc[0, "custom_fields"]) == {"region": "EU", "tags": []}


def test_parquet_survives_empty_dict_column():
    df = _read(rows_to_parquet_bytes([{"id": 1, "meta": {}}, {"id": 2, "meta": {}}]))
    assert list(df["id"]) == [1, 2]


def test_parquet_survives_missing_keys_and_none():
    df = _read(rows_to_parquet_bytes([{"id": "a", "x": "1"}, {"id": "b"}, {"id": "c", "x": None}]))
    assert list(df["id"]) == ["a", "b", "c"]
    assert df.loc[0, "x"] == "1"
    assert pd.isna(df.loc[1, "x"]) and pd.isna(df.loc[2, "x"])


def test_parquet_mixed_types_fall_back_to_strings():
    df = _read(rows_to_parquet_bytes([{"a": 1}, {"a": "two"}]))
    assert list(df["a"]) == ["1", "two"]