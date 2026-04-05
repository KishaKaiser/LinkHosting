"""Sites API router."""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Site, SiteStatus
from app.schemas import SiteCreate, SiteOut, SiteUpdate
from app.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sites", tags=["sites"])


def _auto_domain(name: str) -> str:
    return f"{name}.{settings.domain_suffix}"


@router.get("", response_model=list[SiteOut])
def list_sites(db: Session = Depends(get_db)):
    return db.query(Site).all()


@router.post("", response_model=SiteOut, status_code=status.HTTP_201_CREATED)
def create_site(payload: SiteCreate, db: Session = Depends(get_db)):
    domain = payload.domain or _auto_domain(payload.name)

    existing = db.query(Site).filter(
        (Site.name == payload.name) | (Site.domain == domain)
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Site '{payload.name}' or domain '{domain}' already exists",
        )

    env_json: Optional[str] = None
    if payload.env_vars:
        env_json = json.dumps(payload.env_vars)

    site = Site(
        name=payload.name,
        domain=domain,
        site_type=payload.site_type,
        status=SiteStatus.pending,
        image=payload.image,
        upstream_url=payload.upstream_url,
        env_vars=env_json,
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    log.info("Created site %s (%s)", site.name, site.domain)
    return site


@router.get("/{site_name}", response_model=SiteOut)
def get_site(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return site


@router.patch("/{site_name}", response_model=SiteOut)
def update_site(site_name: str, payload: SiteUpdate, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    if payload.status is not None:
        site.status = payload.status
    if payload.image is not None:
        site.image = payload.image
    if payload.upstream_url is not None:
        site.upstream_url = payload.upstream_url
    if payload.env_vars is not None:
        site.env_vars = json.dumps(payload.env_vars)

    db.commit()
    db.refresh(site)
    return site


@router.delete("/{site_name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_site(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    # Stop container if running
    from app.services.container import stop_container
    from app.services.proxy import remove_vhost, reload_proxy

    stop_container(site)
    remove_vhost(site.name)
    reload_proxy()

    db.delete(site)
    db.commit()


@router.post("/{site_name}/deploy", response_model=SiteOut)
def deploy_site(site_name: str, db: Session = Depends(get_db)):
    """Provision container + write vhost + reload proxy."""
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    from app.services.container import provision_container
    from app.services.proxy import write_vhost, reload_proxy

    # Determine if TLS cert exists
    from app.models import Certificate
    cert = db.query(Certificate).filter(Certificate.site_id == site.id).first()
    tls = cert is not None

    try:
        container_id = provision_container(site)
        site.container_id = container_id
        site.status = SiteStatus.running
        db.commit()

        write_vhost(site, tls=tls)
        reload_proxy()

        db.refresh(site)
    except Exception as exc:
        site.status = SiteStatus.error
        db.commit()
        log.exception("Failed to deploy site %s", site_name)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return site


@router.post("/{site_name}/stop", response_model=SiteOut)
def stop_site(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    from app.services.container import stop_container

    stop_container(site)
    site.status = SiteStatus.stopped
    site.container_id = None
    db.commit()
    db.refresh(site)
    return site
