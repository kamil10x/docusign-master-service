from fastapi import APIRouter
from sqlalchemy import create_engine, text
from app.config import settings
from app.services.minio_client import minio_client

router = APIRouter()


@router.get("/health")
def health():
    status = {"db": False, "minio": False}

    try:
        with create_engine(settings.DATABASE_URL).connect() as c:
            c.execute(text("select 1"))
            status["db"] = True
    except Exception:
        pass

    try:
        minio_client.client.list_buckets()
        status["minio"] = True
    except Exception:
        pass

    return {
        "status": "ok" if all(status.values()) else "degraded",
        **status
    }