
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.services.normalization_service import NormalizationService

# Import get_db from the same location used in app/api/scan.py
from app.db.session import get_db


router = APIRouter(
    prefix="/api/normalization",
    tags=["Normalization"],
)


@router.post("/{job_id}")
def normalize_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    service = NormalizationService(db)

    try:
        result = service.normalize_job(job_id)

        return {
            "message": "Normalization completed successfully",
            "job_id": job_id,
            "record_counts": {
                table: len(rows)
                for table, rows in result.items()
            },
            "data": result,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Normalization failed: {str(exc)}",
        )
