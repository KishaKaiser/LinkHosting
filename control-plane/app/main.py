"""
LinkHosting Control Plane — FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import Base, engine
from app.api import sites as sites_router
from app.api import certs as certs_router
from app.api import databases as databases_router
from app.api import sftp as sftp_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (production should use Alembic migrations)
    Base.metadata.create_all(bind=engine)
    log.info(
        "LinkHosting control-plane started (dev_mode=%s)", settings.dev_mode
    )
    yield
    log.info("LinkHosting control-plane shutting down")


app = FastAPI(
    title="LinkHosting Control Plane",
    description=(
        "Internal-only multi-tenant web hosting control plane. "
        "Manages sites, containers, TLS certificates, databases, and SFTP accounts."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — restrict to internal network in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten per deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sites_router.router)
app.include_router(certs_router.router)
app.include_router(databases_router.router)
app.include_router(sftp_router.router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "dev_mode": settings.dev_mode}


@app.get("/ca.crt", tags=["system"])
def download_ca_root():
    """Download the internal CA root certificate for client trust installation."""
    from fastapi.responses import PlainTextResponse
    from app.services.cert import get_ca_cert_pem
    return PlainTextResponse(
        content=get_ca_cert_pem(),
        media_type="application/x-pem-file",
        headers={"Content-Disposition": "attachment; filename=linkhosting-ca.crt"},
    )
