"""Sites API router."""
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import require_bearer_token
from app.database import get_db
from app.models import Site, SiteStatus, SiteType
from app.schemas import GitHubImport, SiteCreate, SiteOut, SiteUpdate
from app.config import settings

log = logging.getLogger(__name__)
router = APIRouter(
    prefix="/sites",
    tags=["sites"],
    dependencies=[Depends(require_bearer_token)],
)


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

    # Determine site type — auto-detect from GitHub repo if not specified
    site_type = payload.site_type
    git_repo = payload.github_repo
    git_branch = payload.github_branch

    if git_repo:
        from app.services.github import clone_repo, detect_site_type, _validate_github_url
        try:
            git_repo = _validate_github_url(git_repo)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        site_dir = Path(settings.sites_base_dir) / payload.name
        try:
            clone_repo(git_repo, site_dir, branch=git_branch)
        except Exception as exc:
            log.exception("GitHub clone failed for site %s", payload.name)
            raise HTTPException(status_code=422, detail=f"GitHub clone failed: {exc}") from exc

        if site_type is None:
            site_type = detect_site_type(site_dir)
            log.info("Auto-detected site type %s for %s", site_type, payload.name)

    if site_type is None:
        raise HTTPException(
            status_code=422,
            detail="site_type is required when github_repo is not provided",
        )

    env_json: Optional[str] = None
    if payload.env_vars:
        env_json = json.dumps(payload.env_vars)

    site = Site(
        name=payload.name,
        domain=domain,
        site_type=site_type,
        status=SiteStatus.pending,
        image=payload.image,
        upstream_url=payload.upstream_url,
        env_vars=env_json,
        git_repo=git_repo,
        git_branch=git_branch,
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


@router.post("/{site_name}/import-github", response_model=SiteOut)
def import_github(
    site_name: str,
    payload: GitHubImport,
    db: Session = Depends(get_db),
):
    """
    Clone (or re-clone) a GitHub repository into a site's content directory.

    - If the site already has content, the directory is replaced with a fresh clone.
    - When `auto_detect_type` is true (default), the site's `site_type` is updated
      based on the repository contents.
    - Records `git_repo` and `git_branch` on the site for future reference.
    """
    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")

    from app.services.github import clone_repo, detect_site_type, _validate_github_url
    import shutil

    try:
        repo_url = _validate_github_url(payload.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    site_dir = Path(settings.sites_base_dir) / site.name

    # Remove existing content so clone starts clean (non-dev mode only)
    if not settings.dev_mode and site_dir.exists():
        shutil.rmtree(site_dir)

    try:
        clone_repo(repo_url, site_dir, branch=payload.branch)
    except Exception as exc:
        log.exception("GitHub import failed for site %s", site_name)
        raise HTTPException(status_code=422, detail=f"GitHub clone failed: {exc}") from exc

    site.git_repo = repo_url
    site.git_branch = payload.branch

    if payload.auto_detect_type:
        detected = detect_site_type(site_dir)
        if detected != site.site_type:
            log.info(
                "Updated site type for %s: %s → %s", site_name, site.site_type, detected
            )
            site.site_type = detected

    db.commit()
    db.refresh(site)
    log.info("Imported GitHub repo %s into site %s", repo_url, site_name)
    return site

