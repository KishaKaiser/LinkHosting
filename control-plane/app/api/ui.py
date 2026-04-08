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
    site_type: str = Form(""),
    domain: str = Form(""),
    git_repo: str = Form(""),
    git_branch: str = Form(""),
    db: Session = Depends(get_db),
):
    redirect = _require_login(request)
    if redirect:
        return redirect

    import re

    form = {
        "name": name,
        "site_type": site_type,
        "domain": domain,
        "git_repo": git_repo,
        "git_branch": git_branch,
    }

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

    # Validate / resolve site type
    git_repo = git_repo.strip()
    git_branch = git_branch.strip() or None
    site_type_enum = None

    if site_type:
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
    elif not git_repo:
        return templates.TemplateResponse(
            request,
            "create_site.html",
            {
                "error": "Site type is required when no Git repository URL is provided.",
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

    # Clone git repository if provided
    if git_repo:
        from pathlib import Path
        from app.services.github import clone_repo, detect_site_type, _validate_github_url

        try:
            git_repo = _validate_github_url(git_repo)
        except ValueError as exc:
            return templates.TemplateResponse(
                request,
                "create_site.html",
                {
                    "error": f"Invalid Git repository URL: {exc}",
                    "form": form,
                    "domain_suffix": settings.domain_suffix,
                },
                status_code=422,
            )

        site_dir = Path(settings.sites_base_dir) / name
        try:
            clone_repo(git_repo, site_dir, branch=git_branch)
        except Exception as exc:
            log.exception("UI: Git clone failed for site %s", name)
            return templates.TemplateResponse(
                request,
                "create_site.html",
                {
                    "error": f"Git clone failed: {exc}",
                    "form": form,
                    "domain_suffix": settings.domain_suffix,
                },
                status_code=422,
            )

        if site_type_enum is None:
            site_type_enum = detect_site_type(site_dir)
            log.info("UI: Auto-detected site type %s for %s", site_type_enum, name)

    site = Site(
        name=name,
        domain=final_domain,
        site_type=site_type_enum,
        status=SiteStatus.pending,
        git_repo=git_repo or None,
        git_branch=git_branch,
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

    return RedirectResponse(f"/panel/sites/{site.name}", status_code=302)


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
    return RedirectResponse(f"/panel/sites/{site.name}", status_code=302)


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


# ── Settings / password change ────────────────────────────────────────────────

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    redirect = _require_login(request)
    if redirect:
        return redirect

    message = request.session.pop("flash_message", None)
    error = request.session.pop("flash_error", None)
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"message": message, "error": error},
    )


@router.post("/settings/change-password")
async def change_password_post(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    redirect = _require_login(request)
    if redirect:
        return redirect

    def _render_error(msg: str):
        return templates.TemplateResponse(
            request,
            "settings.html",
            {"message": None, "error": msg},
            status_code=422,
        )

    if not secrets.compare_digest(current_password, settings.admin_secret_key):
        return _render_error("Current password is incorrect.")

    if new_password != confirm_password:
        return _render_error("New password and confirmation do not match.")

    if len(new_password) < 12:
        return _render_error("New password must be at least 12 characters.")

    # Update in-memory setting (takes effect immediately for all requests)
    settings.admin_secret_key = new_password

    # Persist to override file so the new key survives container restarts
    import pathlib
    override_path = pathlib.Path(settings.admin_key_override_file)
    try:
        override_path.parent.mkdir(parents=True, exist_ok=True)
        override_path.write_text(new_password)
        log.info("Admin key override written to %s", override_path)
    except OSError as exc:
        log.warning("Could not persist admin key to %s: %s", override_path, exc)

    log.info("Admin password changed via web UI")
    request.session["flash_message"] = (
        "Password updated successfully. Use the new password on your next login."
    )
    return RedirectResponse("/panel/settings", status_code=302)
