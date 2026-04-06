"""Databases API router."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import DatabaseEngine, Site, SiteDatabase
from app.schemas import DatabaseCreate, DatabaseCredentials, DatabaseOut

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sites/{site_name}/database", tags=["databases"])

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("", response_model=DatabaseCredentials, status_code=201)
def create_database(
    site_name: str,
    payload: DatabaseCreate,
    db: Session = Depends(get_db),
):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    existing = (
        db.query(SiteDatabase)
        .filter(SiteDatabase.site_id == site.id, SiteDatabase.engine == payload.engine)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A {payload.engine} database already exists for site '{site_name}'",
        )

    from app.services.database import provision_database, db_identifiers

    # Compute identifiers independently (not tainted by password)
    db_name, db_user = db_identifiers(site.name)
    host = "db-pg" if payload.engine == DatabaseEngine.postgres else "db-mysql"
    port = 5432 if payload.engine == DatabaseEngine.postgres else 3306

    log.info("Creating database %s for site %s", db_name, site_name)

    _, _, password, host, port = provision_database(site.name, payload.engine)

    pw_hash = pwd_context.hash(password)
    site_db = SiteDatabase(
        site_id=site.id,
        db_name=db_name,
        db_user=db_user,
        db_password_hash=pw_hash,
        engine=payload.engine,
        host=host,
        port=port,
    )
    db.add(site_db)
    db.commit()
    db.refresh(site_db)

    if payload.engine == DatabaseEngine.postgres:
        dsn = f"postgresql://{db_user}:{password}@{host}:{port}/{db_name}"
    else:
        dsn = f"mysql://{db_user}:{password}@{host}:{port}/{db_name}"

    return DatabaseCredentials(
        db_name=db_name,
        db_user=db_user,
        db_password=password,
        engine=payload.engine,
        host=host,
        port=port,
        dsn=dsn,
    )


@router.get("", response_model=list[DatabaseOut])
def list_databases(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return db.query(SiteDatabase).filter(SiteDatabase.site_id == site.id).all()


@router.delete("/{db_id}", status_code=204)
def delete_database(site_name: str, db_id: int, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    site_db = db.query(SiteDatabase).filter(
        SiteDatabase.id == db_id, SiteDatabase.site_id == site.id
    ).first()
    if not site_db:
        raise HTTPException(status_code=404, detail="Database not found")

    from app.services.database import deprovision_database
    deprovision_database(site_db.db_name, site_db.db_user, site_db.engine)

    db.delete(site_db)
    db.commit()
