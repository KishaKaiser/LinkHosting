"""Certificates API router."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Certificate, Site
from app.schemas import CertOut
from app.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sites/{site_name}/cert", tags=["certificates"])


@router.post("", response_model=CertOut, status_code=201)
def create_cert(site_name: str, db: Session = Depends(get_db)):
    """Issue a TLS certificate for the site's domain using the internal CA."""
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    from app.services.cert import issue_cert
    from app.services.proxy import write_vhost, reload_proxy

    cert_dir = Path(settings.certs_base_dir) / site.name
    cert_path, key_path, valid_until = issue_cert(site.domain, cert_dir)

    # Remove existing cert records for site
    db.query(Certificate).filter(Certificate.site_id == site.id).delete()

    cert_obj = Certificate(
        site_id=site.id,
        domain=site.domain,
        cert_path=str(cert_path),
        key_path=str(key_path),
        ca_signed=True,
        valid_until=valid_until,
    )
    db.add(cert_obj)
    db.commit()
    db.refresh(cert_obj)

    # Update vhost to use TLS if site is already deployed
    if site.container_id:
        write_vhost(site, tls=True)
        reload_proxy()

    return cert_obj


@router.get("", response_model=list[CertOut])
def list_certs(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return db.query(Certificate).filter(Certificate.site_id == site.id).all()


@router.get("/ca.crt")
def download_ca_cert():
    """Download the internal CA certificate PEM for client trust installation."""
    from fastapi.responses import PlainTextResponse
    from app.services.cert import get_ca_cert_pem
    return PlainTextResponse(
        content=get_ca_cert_pem(),
        media_type="application/x-pem-file",
        headers={"Content-Disposition": "attachment; filename=linkhosting-ca.crt"},
    )
