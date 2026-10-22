from fastapi import APIRouter
from sqlalchemy import create_engine, text
from minio import Minio
from app.config import settings

router = APIRouter()

@router.get("/health")
def health():
    status = {"db": False, "minio": False}
    try:
        with create_engine(settings.DATABASE_URL).connect() as c:
            c.execute(text("select 1")); status["db"] = True
    except Exception: pass
    try:
        Minio(settings.MINIO_ENDPOINT, settings.MINIO_ACCESS_KEY, settings.MINIO_SECRET_KEY, secure=False).list_buckets()
        status["minio"] = True
    except Exception: pass
    return {"status": "ok" if all(status.values()) else "degraded", **status}