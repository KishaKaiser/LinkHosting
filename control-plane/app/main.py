"""
LinkHosting Control Plane — FastAPI application entry point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.api import sites as sites_router
from app.api import certs as certs_router
from app.api import databases as databases_router
from app.api import sftp as sftp_router
from app.api import jobs as jobs_router
from app.api import ui as ui_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (production should use Alembic migrations)
    Base.metadata.create_all(bind=engine)

    # Load persisted admin key override (written by the password-change UI)
    import pathlib
    override_file = pathlib.Path(settings.admin_key_override_file)
    if override_file.exists():
        key = override_file.read_text().strip()
        if key:
            settings.admin_secret_key = key
            log.info("Loaded admin key override from %s", override_file)

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

# Session middleware (must be added before CORS)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret_key,
    session_cookie="lh_session",
    https_only=False,  # HTTP is acceptable for MVP / home hosting
    same_site="lax",
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
app.include_router(jobs_router.router)
app.include_router(ui_router.router)


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

