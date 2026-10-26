from fastapi import Depends, FastAPI

from app.core.hmac_auth import verify_hmac

from app.api import health, validate_credentials  # your actual modules

from app.api.validate import router as validate_router
from app.core.hmac_auth import HMACAuthMiddleware

app = FastAPI(title="DocuSign Master Service")
app.add_middleware(HMACAuthMiddleware)
app.include_router(validate_router)

# public
app.include_router(health.router, prefix="/api")

# protected
protected = [Depends(verify_hmac)]

app.include_router(validate_credentials.router, prefix="/api", dependencies=protected)
# later: scan, normalization, maintenance get the same `dependencies=protected`