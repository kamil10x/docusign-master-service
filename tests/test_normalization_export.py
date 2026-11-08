import io

import pandas as pd

from app.services.normalization_export import export_normalized_results


class FakeMinio:
    def __init__(self):
        self.store = {}

    def upload_bytes(self, name, data, content_type="application/octet-stream"):
        self.store[name] = (data, content_type)
        return name


TABLES = {
    "envelopes": [{"id": "e1", "status": "completed"}],
    "recipients": [{"id": "r1", "envelope_id": "e1"}],
    "documents": [],
    "templates": [{"id": "t1"}],
}


def test_exports_parquet_and_json_for_each_non_empty_table():
    fake = FakeMinio()
    exports = export_normalized_results("job-1", TABLES, minio=fake)

    assert set(exports) == {"envelopes", "recipients", "templates"}  # empty "documents" skipped
    assert exports["envelopes"] == {
        "parquet": "normalized/job-1/envelopes.parquet",
        "json": "normalized/job-1/envelopes.json",
    }
    assert len(fake.store) == 6


def test_uses_correct_content_types_and_valid_parquet():
    fake = FakeMinio()
    export_normalized_results("job-1", TABLES, minio=fake)

    data, ctype = fake.store["normalized/job-1/envelopes.parquet"]
    assert ctype == "application/vnd.apache.parquet"
    assert pd.read_parquet(io.BytesIO(data)).loc[0, "id"] == "e1"
    assert fake.store["normalized/job-1/envelopes.json"][1] == "application/json"


def test_exports_any_table_name_the_normalizers_produce():
    fake = FakeMinio()
    exports = export_normalized_results("job-1", {"envelope_custom_fields": [{"k": "v"}]}, minio=fake)
    assert "envelope_custom_fields" in exports


def test_unsafe_table_names_are_sanitized():
    fake = FakeMinio()
    exports = export_normalized_results("job-1", {"../evil/name": [{"a": 1}]}, minio=fake)
    assert list(exports) == ["___evil_name"]
    assert all(".." not in key for key in fake.store)


def test_all_empty_tables_export_nothing():
    fake = FakeMinio()
    assert export_normalized_results("job-1", {"envelopes": []}, minio=fake) == {}
    assert fake.store == {}