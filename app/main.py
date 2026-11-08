
from fastapi import Depends, FastAPI

from app.core.hmac_auth import verify_hmac, HMACAuthMiddleware

from app.api import health, validate_credentials

from app.api.validate import router as validate_router
from app.api.scan import router as scan_router
from app.api.normalization import router as normalization_router


app = FastAPI(title="DocuSign Master Service")

# HMAC middleware protects all non-public routes
app.add_middleware(HMACAuthMiddleware)

# Existing routers
app.include_router(validate_router)
app.include_router(normalization_router)

# Public routes
app.include_router(health.router, prefix="/api")

# Protected routes
protected = [Depends(verify_hmac)]

app.include_router(
    validate_credentials.router,
    prefix="/api",
    dependencies=protected
)

# Scan router: authentication handled by HMAC middleware
app.include_router(scan_router)
