"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.models import DatabaseEngine, SiteStatus, SiteType


# ── Site ──────────────────────────────────────────────────────────────────────

class SiteCreate(BaseModel):
    name: str
    site_type: SiteType
    domain: Optional[str] = None       # auto-derived if omitted
    image: Optional[str] = None        # custom Docker image
    upstream_url: Optional[str] = None # for proxy type
    env_vars: Optional[dict] = None

    @field_validator("name")
    @classmethod
    def name_slug(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,62}$", v):
            raise ValueError(
                "name must be lowercase alphanumeric/hyphens, 1-63 chars, no leading hyphen"
            )
        return v


class SiteUpdate(BaseModel):
    status: Optional[SiteStatus] = None
    image: Optional[str] = None
    upstream_url: Optional[str] = None
    env_vars: Optional[dict] = None


class SiteOut(BaseModel):
    id: int
    name: str
    domain: str
    site_type: SiteType
    status: SiteStatus
    container_id: Optional[str]
    image: Optional[str]
    upstream_url: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Database ──────────────────────────────────────────────────────────────────

class DatabaseCreate(BaseModel):
    engine: DatabaseEngine = DatabaseEngine.postgres


class DatabaseOut(BaseModel):
    id: int
    site_id: int
    db_name: str
    db_user: str
    engine: DatabaseEngine
    host: str
    port: int
    created_at: datetime
    # password not returned; use /credentials endpoint

    model_config = {"from_attributes": True}


class DatabaseCredentials(BaseModel):
    db_name: str
    db_user: str
    db_password: str  # plain-text, returned once at creation
    engine: DatabaseEngine
    host: str
    port: int
    dsn: str


# ── Certificate ───────────────────────────────────────────────────────────────

class CertOut(BaseModel):
    id: int
    site_id: int
    domain: str
    cert_path: str
    key_path: str
    ca_signed: bool
    valid_until: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── SFTP ──────────────────────────────────────────────────────────────────────

class SFTPAccountOut(BaseModel):
    id: int
    site_id: int
    username: str
    home_dir: str
    active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SFTPCredentials(BaseModel):
    username: str
    password: str  # plain-text, returned once at creation
    home_dir: str
    ssh_host: str
    ssh_port: int = 2222
