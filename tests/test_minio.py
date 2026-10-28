
import os

from dotenv import load_dotenv
from minio import Minio


def main():
    load_dotenv(override=True)

    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    bucket = os.getenv("MINIO_BUCKET")
    secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

    if not all([endpoint, access_key, secret_key, bucket]):
        print("ERROR: Missing required MinIO environment variables.")
        return

    # Use localhost:9000 when running this script directly on Windows.
    # Keep minio:9000 if running inside the Docker Compose network.
    if endpoint == "minio:9000":
        endpoint = "localhost:9000"

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
    )

    print("Endpoint:", endpoint)
    print("Bucket:", bucket)

    try:
        if client.bucket_exists(bucket):
            print("SUCCESS: Connected to MinIO/SILO")
            print(f"SUCCESS: Bucket '{bucket}' exists")
        else:
            client.make_bucket(bucket)
            print("SUCCESS: Connected to MinIO/SILO")
            print(f"SUCCESS: Bucket '{bucket}' created")
    except Exception as exc:
        print(f"ERROR: MinIO connection failed: {exc}")


if __name__ == "__main__":
    main()
