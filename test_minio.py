import os
from minio import Minio
from dotenv import load_dotenv

load_dotenv()

client = Minio(
    os.getenv("MINIO_ENDPOINT"),
    access_key=os.getenv("MINIO_ACCESS_KEY"),
    secret_key=os.getenv("MINIO_SECRET_KEY"),
    secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
)

bucket = os.getenv("MINIO_BUCKET")

print("Endpoint:", os.getenv("MINIO_ENDPOINT"))
print("Bucket:", bucket)

if client.bucket_exists(bucket):
    print("SUCCESS: Connected to MinIO/SILO")
    print(f"SUCCESS: Bucket '{bucket}' exists")
else:
    print(f"ERROR: Bucket '{bucket}' does not exist")