"""MinIO wrapper: file helpers (Day 2) + in-memory/object helpers (Day 19)."""
import io
import logging

from minio import Minio
from minio.error import S3Error

from app.config import settings

logger = logging.getLogger(__name__)

CONTENT_TYPES = {
    "parquet": "application/vnd.apache.parquet",
    "json": "application/json",
}

_MISSING_OBJECT_CODES = {"NoSuchKey", "NoSuchObject", "NotFound"}


class MinioClient:
    def __init__(self, client: Minio | None = None, bucket: str | None = None):
        # Minio() does not open a connection here, so import-time creation is safe.
        self.client = client or Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = bucket or settings.MINIO_BUCKET
        self._bucket_ready = False

    # ------------------------------------------------------------ paths
    @staticmethod
    def build_object_path(job_id: str, table: str, fmt: str) -> str:
        """normalized/<job_id>/<table>.<fmt> - the single source of truth for paths."""
        return f"normalized/{job_id}/{table}.{fmt}"

    @staticmethod
    def job_prefix(job_id: str) -> str:
        return f"normalized/{job_id}/"

    # ----------------------------------------------------------- bucket
    def ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

    def _ensure_bucket_once(self) -> None:
        if not self._bucket_ready:
            self.ensure_bucket()
            self._bucket_ready = True

    # ------------------------------------------------- file helpers (old)
    def upload_file(self, object_name, file_path):
        self.ensure_bucket()
        return self.client.fput_object(
            self.bucket,
            object_name,
            file_path,
        )

    def download_file(self, object_name, file_path):
        return self.client.fget_object(
            self.bucket,
            object_name,
            file_path,
        )

    def delete_file(self, object_name):
        self.client.remove_object(
            self.bucket,
            object_name,
        )

    # ---------------------------------------------------- object helpers
    def upload_bytes(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        self._ensure_bucket_once()
        self.client.put_object(
            self.bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info("Uploaded %s (%d bytes)", object_name, len(data))
        return object_name

    def download_bytes(self, object_name: str) -> bytes:
        response = self.client.get_object(self.bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def object_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error as exc:
            if exc.code in _MISSING_OBJECT_CODES:
                return False
            raise

    def list_objects(self, prefix: str) -> list[str]:
        """Object names under `prefix` (sorted). Missing bucket -> empty list."""
        try:
            return sorted(
                obj.object_name
                for obj in self.client.list_objects(
                    self.bucket, prefix=prefix, recursive=True
                )
            )
        except S3Error as exc:
            if exc.code == "NoSuchBucket":
                return []
            raise


minio_client = MinioClient()