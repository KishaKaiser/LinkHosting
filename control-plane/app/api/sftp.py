"""SFTP accounts API router."""
import logging
import socket

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Site, SFTPAccount
from app.schemas import SFTPAccountOut, SFTPCredentials

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sites/{site_name}/sftp", tags=["sftp"])


def _sftp_host() -> str:
    try:
        return socket.gethostbyname("sftp-server")
    except Exception:
        return "sftp-server"


@router.post("", response_model=SFTPCredentials, status_code=201)
def create_sftp_account(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    existing = db.query(SFTPAccount).filter(SFTPAccount.site_id == site.id).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"SFTP account already exists for site '{site_name}'",
        )

    from app.services.sftp import provision_sftp_account, hash_password

    username, password, home_dir = provision_sftp_account(site.name)

    account = SFTPAccount(
        site_id=site.id,
        username=username,
        password_hash=hash_password(password),
        home_dir=home_dir,
        active=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    log.info("Created SFTP account %s for site %s", username, site_name)
    credentials = SFTPCredentials(
        username=username,
        password=password,
        home_dir=home_dir,
        ssh_host=_sftp_host(),
        ssh_port=2222,
    )
    password = None  # clear from scope after hashing and credential object creation
    return credentials


@router.get("", response_model=list[SFTPAccountOut])
def list_sftp_accounts(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    return db.query(SFTPAccount).filter(SFTPAccount.site_id == site.id).all()


@router.delete("", status_code=204)
def delete_sftp_account(site_name: str, db: Session = Depends(get_db)):
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    account = db.query(SFTPAccount).filter(SFTPAccount.site_id == site.id).first()
    if not account:
        raise HTTPException(status_code=404, detail="SFTP account not found")

    from app.services.sftp import deprovision_sftp_account
    deprovision_sftp_account(account.username)

    db.delete(account)
    db.commit()
