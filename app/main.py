from fastapi import FastAPI
from app.api import health

app = FastAPI(title="DocuSign Master Service")
app.include_router(health.router, prefix="/api")