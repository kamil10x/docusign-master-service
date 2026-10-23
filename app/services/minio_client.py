from minio import Minio

from app.config import settings


class MinioClient:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self.bucket = settings.MINIO_BUCKET

    def ensure_bucket(self):
        if not self.client.bucket_exists(self.bucket):
            self.client.make_bucket(self.bucket)

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


minio_client = MinioClient()