"""SQLAlchemy ORM models."""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SiteType(str, enum.Enum):
    static = "static"
    php = "php"
    node = "node"
    python = "python"
    proxy = "proxy"
    wordpress = "wordpress"


class SiteStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    stopped = "stopped"
    error = "error"


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    domain: Mapped[str] = mapped_column(String(253), unique=True, index=True, nullable=False)
    site_type: Mapped[SiteType] = mapped_column(Enum(SiteType), nullable=False)
    status: Mapped[SiteStatus] = mapped_column(
        Enum(SiteStatus), default=SiteStatus.pending, nullable=False
    )
    container_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    image: Mapped[str | None] = mapped_column(String(256), nullable=True)
    env_vars: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    upstream_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    git_repo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    git_branch: Mapped[str | None] = mapped_column(String(128), nullable=True)
    build_dir: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    databases: Mapped[list["SiteDatabase"]] = relationship(
        "SiteDatabase", back_populates="site", cascade="all, delete-orphan"
    )
    certificates: Mapped[list["Certificate"]] = relationship(
        "Certificate", back_populates="site", cascade="all, delete-orphan"
    )
    sftp_accounts: Mapped[list["SFTPAccount"]] = relationship(
        "SFTPAccount", back_populates="site", cascade="all, delete-orphan"
    )
    deploy_jobs: Mapped[list["DeployJob"]] = relationship(
        "DeployJob", back_populates="site", cascade="all, delete-orphan"
    )


class DatabaseEngine(str, enum.Enum):
    postgres = "postgres"
    mysql = "mysql"


class SiteDatabase(Base):
    __tablename__ = "site_databases"
    __table_args__ = (
        UniqueConstraint("db_name", "engine", name="uq_site_databases_name_engine"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("sites.id"), nullable=False)
    db_name: Mapped[str] = mapped_column(String(64), nullable=False)
    db_user: Mapped[str] = mapped_column(String(64), nullable=False)
    db_password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    engine: Mapped[DatabaseEngine] = mapped_column(
        Enum(DatabaseEngine), default=DatabaseEngine.postgres, nullable=False
    )
    host: Mapped[str] = mapped_column(String(128), default="db-pg", nullable=False)
    port: Mapped[int] = mapped_column(Integer, default=5432, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    site: Mapped["Site"] = relationship("Site", back_populates="databases")


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("sites.id"), nullable=False)
    domain: Mapped[str] = mapped_column(String(253), nullable=False)
    cert_path: Mapped[str] = mapped_column(String(512), nullable=False)
    key_path: Mapped[str] = mapped_column(String(512), nullable=False)
    ca_signed: Mapped[bool] = mapped_column(Boolean, default=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    site: Mapped["Site"] = relationship("Site", back_populates="certificates")


class SFTPAccount(Base):
    __tablename__ = "sftp_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("sites.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    home_dir: Mapped[str] = mapped_column(String(512), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    site: Mapped["Site"] = relationship("Site", back_populates="sftp_accounts")


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class DeployJob(Base):
    """Tracks background deployment jobs (WordPress docker-compose deployments)."""
    __tablename__ = "deploy_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    site_id: Mapped[int] = mapped_column(Integer, ForeignKey("sites.id"), nullable=False)
    rq_job_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.queued, nullable=False
    )
    logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    site: Mapped["Site"] = relationship("Site", back_populates="deploy_jobs")
