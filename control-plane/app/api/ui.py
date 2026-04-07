"""
Web UI routes for the LinkHosting control panel.

Provides session-based login and HTML pages backed by Jinja2 templates.
All UI routes live under /panel/.
"""
import secrets
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import DeployJob, JobStatus, Site, SiteStatus, SiteType

log = logging.getLogger(__name__)

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

router = APIRouter(prefix="/panel", tags=["ui"])

# ── Auth helpers ──────────────────────────────────────────────────────────────

SESSION_KEY = "authenticated"


def _is_authenticated(request: Request) -> bool:
    return request.session.get(SESSION_KEY) is True


def _require_login(request: Request):
    """Redirect to login if not authenticated."""
    if not _is_authenticated(request):
        return RedirectResponse("/panel/login", status_code=302)
    return None


# ── Login / Logout ────────────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_authenticated(request):
        return RedirectResponse("/panel/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
async def login_post(request: Request, password: str = Form(...)):
    if secrets.compare_digest(password, settings.admin_secret_key):
        request.session[SESSION_KEY] = True
        return RedirectResponse("/panel/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid password"},
        status_code=401,
    )


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/panel/login", status_code=302)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    sites = db.query(Site).order_by(Site.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "dashboard.html", {"sites": sites}
    )


# ── Create site ───────────────────────────────────────────────────────────────

@router.get("/sites/new", response_class=HTMLResponse)
async def create_site_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        request,
        "create_site.html",
        {
            "error": None,
            "form": {},
            "domain_suffix": settings.domain_suffix,
        },
    )


@router.post("/sites/new")
async def create_site_post(
    request: Request,
    name: str = Form(...),
    site_type: str = Form(...),
    domain: str = Form(""),
    db: Session = Depends(get_db),
):
    redirect = _require_login(request)
    if redirect:
        return redirect

    import re

    form = {"name": name, "site_type": site_type, "domain": domain}

    # Validate name
    if not re.match(r"^[a-z0-9][a-z0-9\-]{0,62}$", name):
        return templates.TemplateResponse(
            request,
            "create_site.html",
            {
                "error": "Name must be lowercase letters, numbers, or hyphens (1–63 chars).",
                "form": form,
                "domain_suffix": settings.domain_suffix,
            },
            status_code=422,
        )

    # Validate type
    try:
        site_type_enum = SiteType(site_type)
    except ValueError:
        return templates.TemplateResponse(
            request,
            "create_site.html",
            {
                "error": f"Unknown site type: {site_type}",
                "form": form,
                "domain_suffix": settings.domain_suffix,
            },
            status_code=422,
        )

    final_domain = domain.strip() or f"{name}.{settings.domain_suffix}"

    # Check for duplicate
    existing = (
        db.query(Site)
        .filter((Site.name == name) | (Site.domain == final_domain))
        .first()
    )
    if existing:
        return templates.TemplateResponse(
            request,
            "create_site.html",
            {
                "error": f"Site '{name}' or domain '{final_domain}' already exists.",
                "form": form,
                "domain_suffix": settings.domain_suffix,
            },
            status_code=409,
        )

    site = Site(
        name=name,
        domain=final_domain,
        site_type=site_type_enum,
        status=SiteStatus.pending,
    )
    db.add(site)
    db.commit()
    db.refresh(site)
    log.info("UI: Created site %s (%s)", site.name, site.domain)
    return RedirectResponse(f"/panel/sites/{site.name}", status_code=302)


# ── Site detail ───────────────────────────────────────────────────────────────

@router.get("/sites/{site_name}", response_class=HTMLResponse)
async def site_detail(request: Request, site_name: str, db: Session = Depends(get_db)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        return RedirectResponse("/panel/", status_code=302)

    jobs = (
        db.query(DeployJob)
        .filter(DeployJob.site_id == site.id)
        .order_by(DeployJob.id.desc())
        .limit(10)
        .all()
    )

    message = request.session.pop("flash_message", None)
    error = request.session.pop("flash_error", None)

    return templates.TemplateResponse(
        request,
        "site_detail.html",
        {
            "site": site,
            "jobs": jobs,
            "message": message,
            "error": error,
        },
    )


# ── Deploy action ─────────────────────────────────────────────────────────────

@router.post("/sites/{site_name}/deploy")
async def deploy_site_ui(request: Request, site_name: str, db: Session = Depends(get_db)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        return RedirectResponse("/panel/", status_code=302)

    if site.site_type == SiteType.wordpress:
        # Enqueue background job via RQ
        job_record = DeployJob(site_id=site.id, status=JobStatus.queued)
        db.add(job_record)
        db.commit()
        db.refresh(job_record)

        rq_job_id = _enqueue_deploy_job(job_record, site, db)
        if rq_job_id:
            job_record.rq_job_id = rq_job_id
            db.commit()

        request.session["flash_message"] = (
            f"Deploy job #{job_record.id} queued. Refresh to see status."
        )
    else:
        # Synchronous deploy for non-WordPress sites
        from app.services.container import provision_container
        from app.services.proxy import write_vhost, reload_proxy

        try:
            container_id = provision_container(site)
            site.container_id = container_id
            site.status = SiteStatus.running
            db.commit()
            write_vhost(site, tls=False)
            reload_proxy()
            request.session["flash_message"] = "Site deployed successfully."
        except Exception as exc:
            site.status = SiteStatus.error
            db.commit()
            log.exception("UI: Deploy failed for %s", site_name)
            request.session["flash_error"] = f"Deploy failed: {exc}"

    return RedirectResponse(f"/panel/sites/{site_name}", status_code=302)


def _enqueue_deploy_job(job_record: "DeployJob", site: "Site", db: "Session") -> "str | None":
    """Enqueue the deploy job onto Redis/RQ. Returns RQ job id or None on error."""
    try:
        import redis
        from rq import Queue

        conn = redis.from_url(settings.redis_url)
        q = Queue("deploy", connection=conn)
        from app.jobs import run_wordpress_deploy
        rq_job = q.enqueue(run_wordpress_deploy, job_record.id)
        log.info("Enqueued RQ job %s for DeployJob %d", rq_job.id, job_record.id)
        return rq_job.id
    except Exception as exc:
        log.warning(
            "Could not enqueue RQ job (Redis unavailable?): %s — running inline", exc
        )
        # Fall back to inline execution using the provided DB session (avoids cross-session issues)
        if settings.dev_mode:
            from app.api.sites import _run_deploy_inline
            _run_deploy_inline(job_record, site, db)
        return None


# ── Stop action ───────────────────────────────────────────────────────────────

@router.post("/sites/{site_name}/stop")
async def stop_site_ui(request: Request, site_name: str, db: Session = Depends(get_db)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        return RedirectResponse("/panel/", status_code=302)

    if site.site_type == SiteType.wordpress:
        from app.services.wordpress import stop_wordpress
        try:
            stop_wordpress(site.name)
        except Exception as exc:
            log.warning("Could not stop WordPress site %s: %s", site_name, exc)
    else:
        from app.services.container import stop_container
        stop_container(site)

    site.status = SiteStatus.stopped
    site.container_id = None
    db.commit()
    request.session["flash_message"] = "Site stopped."
    return RedirectResponse(f"/panel/sites/{site_name}", status_code=302)


# ── Delete action ─────────────────────────────────────────────────────────────

@router.post("/sites/{site_name}/delete")
async def delete_site_ui(request: Request, site_name: str, db: Session = Depends(get_db)):
    redirect = _require_login(request)
    if redirect:
        return redirect

    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        return RedirectResponse("/panel/", status_code=302)

    if site.site_type == SiteType.wordpress:
        from app.services.wordpress import stop_wordpress
        try:
            stop_wordpress(site.name)
        except Exception as exc:
            log.warning("Could not stop WordPress site %s during delete: %s", site_name, exc)
    else:
        from app.services.container import stop_container
        stop_container(site)

    from app.services.proxy import remove_vhost, reload_proxy
    remove_vhost(site.name)
    reload_proxy()

    db.delete(site)
    db.commit()
    return RedirectResponse("/panel/", status_code=302)
