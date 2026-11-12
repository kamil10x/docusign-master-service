from unittest.mock import MagicMock

import pytest
from minio.error import S3Error

from app.services.minio_client import MinioClient


def _s3_error(code: str) -> S3Error:
    # Keyword arguments: the positional order of S3Error differs between minio versions.
    return S3Error(
        code=code,
        message="msg",
        resource="resource",
        request_id="request-id",
        host_id="host-id",
        response=MagicMock(),
    )


@pytest.fixture
def mc():
    raw = MagicMock()
    return MinioClient(client=raw, bucket="test-bucket"), raw


def test_build_object_path_and_prefix():
    assert MinioClient.build_object_path("j1", "envelopes", "parquet") == "normalized/j1/envelopes.parquet"
    assert MinioClient.job_prefix("j1") == "normalized/j1/"


def test_ensure_bucket_creates_when_missing(mc):
    client, raw = mc
    raw.bucket_exists.return_value = False
    client.ensure_bucket()
    raw.make_bucket.assert_called_once_with("test-bucket")


def test_ensure_bucket_noop_when_present(mc):
    client, raw = mc
    raw.bucket_exists.return_value = True
    client.ensure_bucket()
    raw.make_bucket.assert_not_called()


def test_upload_bytes_sends_length_and_content_type(mc):
    client, raw = mc
    raw.bucket_exists.return_value = True
    assert client.upload_bytes("a/b.json", b"{}", "application/json") == "a/b.json"
    args, kwargs = raw.put_object.call_args
    assert args[0] == "test-bucket" and args[1] == "a/b.json"
    assert kwargs["length"] == 2 and kwargs["content_type"] == "application/json"


def test_upload_bytes_checks_bucket_only_once(mc):
    client, raw = mc
    raw.bucket_exists.return_value = True
    client.upload_bytes("a", b"1")
    client.upload_bytes("b", b"2")
    assert raw.bucket_exists.call_count == 1
    assert raw.put_object.call_count == 2


def test_download_bytes_releases_connection(mc):
    client, raw = mc
    resp = MagicMock()
    resp.read.return_value = b"data"
    raw.get_object.return_value = resp
    assert client.download_bytes("x") == b"data"
    resp.close.assert_called_once()
    resp.release_conn.assert_called_once()


def test_object_exists_true(mc):
    client, _ = mc
    assert client.object_exists("yes") is True


def test_object_exists_false_on_missing_key(mc):
    client, raw = mc
    raw.stat_object.side_effect = _s3_error("NoSuchKey")
    assert client.object_exists("nope") is False


def test_object_exists_reraises_other_errors(mc):
    client, raw = mc
    raw.stat_object.side_effect = _s3_error("AccessDenied")
    with pytest.raises(S3Error):
        client.object_exists("x")


def test_list_objects_returns_sorted_names(mc):
    client, raw = mc
    raw.list_objects.return_value = [MagicMock(object_name="p/b"), MagicMock(object_name="p/a")]
    assert client.list_objects("p/") == ["p/a", "p/b"]
    raw.list_objects.assert_called_once_with("test-bucket", prefix="p/", recursive=True)


def test_list_objects_missing_bucket_is_empty(mc):
    client, raw = mc
    raw.list_objects.side_effect = _s3_error("NoSuchBucket")
    assert client.list_objects("p/") == []