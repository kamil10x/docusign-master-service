"""Day 19: upload every normalized table to MinIO as Parquet + JSON."""
import logging
import re

from app.services.minio_client import CONTENT_TYPES, MinioClient, minio_client
from app.utils.serializers import rows_to_json_bytes, rows_to_parquet_bytes

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def export_normalized_results(
    job_id: str,
    tables: dict[str, list[dict]],
    minio: MinioClient | None = None,
) -> dict[str, dict[str, str]]:
    """Export {table: rows} and return {table: {"parquet": path, "json": path}}.

    Exports whatever tables the normalizers produced (not a fixed list), skips
    empty tables, and is idempotent: re-running overwrites the same objects.
    """
    if minio is None:
        minio = minio_client

    exports: dict[str, dict[str, str]] = {}

    for table, rows in tables.items():
        if not rows:
            logger.info("job %s: table %s is empty, skipping export", job_id, table)
            continue

        name = _UNSAFE.sub("_", table)
        parquet_path = MinioClient.build_object_path(job_id, name, "parquet")
        json_path = MinioClient.build_object_path(job_id, name, "json")

        minio.upload_bytes(parquet_path, rows_to_parquet_bytes(rows), CONTENT_TYPES["parquet"])
        minio.upload_bytes(json_path, rows_to_json_bytes(rows), CONTENT_TYPES["json"])
        exports[name] = {"parquet": parquet_path, "json": json_path}

    logger.info("job %s: exported %d table(s) to MinIO", job_id, len(exports))
    return exports