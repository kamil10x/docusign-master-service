"""Day 19: normalized rows -> JSON / Parquet bytes.

Handles datetime/date/Decimal/UUID (the same class of bug that broke JSONB
earlier) and nested dict/list columns such as custom fields.
"""
import io
import json
import math
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import pandas as pd
import pyarrow as pa


def json_default(obj):
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (Decimal, UUID)):
        return str(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def rows_to_json_bytes(rows: list[dict]) -> bytes:
    return json.dumps(rows, default=json_default, ensure_ascii=False).encode("utf-8")


def _prepare_cell(value):
    """Make a cell safe for pyarrow. Nested values become JSON strings because
    pyarrow cannot infer a struct for empty or mixed-shape dicts."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=json_default, ensure_ascii=False)
    if isinstance(value, (UUID, bytes)):
        return json_default(value)
    return value


def _to_str_or_null(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return value if isinstance(value, str) else str(value)


def _write_parquet(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_parquet(buf, engine="pyarrow", index=False)
    return buf.getvalue()


def rows_to_parquet_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    for col in df.columns:
        df[col] = df[col].map(_prepare_cell)
    try:
        return _write_parquet(df)
    except (pa.ArrowInvalid, pa.ArrowTypeError):
        # A column holds mixed Python types (e.g. int and str). Fall back to
        # strings for the object columns so the export never fails.
        for col in df.columns:
            if df[col].dtype == object:
                df[col] = df[col].map(_to_str_or_null)
        return _write_parquet(df)