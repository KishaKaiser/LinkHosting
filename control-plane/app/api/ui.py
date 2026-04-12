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

    # Convert stored JSON env vars → KEY=VALUE lines for the textarea editor
    import json as _json
    env_text = ""
    if site.env_vars:
        try:
            stored = _json.loads(site.env_vars)
            env_text = "\n".join(f"{k}={v}" for k, v in stored.items())
        except Exception:
            env_text = ""

    return templates.TemplateResponse(
        request,
        "site_detail.html",
        {
            "site": site,
            "jobs": jobs,
            "message": message,
            "error": error,
            "env_text": env_text,
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
        {
            "message": message,
            "error": error,
            "github_token_configured": bool(settings.github_token),
        },
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
            {"message": None, "error": msg, "github_token_configured": bool(settings.github_token)},
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
    import pathlib, os
    override_path = pathlib.Path(settings.admin_key_override_file)
    try:
        override_path.parent.mkdir(parents=True, exist_ok=True)
        override_path.write_text(new_password)
        os.chmod(override_path, 0o600)
        log.info("Admin key override written to %s", override_path)
    except OSError as exc:
        log.warning("Could not persist admin key to %s: %s", override_path, exc)

    log.info("Admin password changed via web UI")
    request.session["flash_message"] = (
        "Password updated successfully. Use the new password on your next login."
    )
    return RedirectResponse("/panel/settings", status_code=302)


# ── GitHub token ──────────────────────────────────────────────────────────────

@router.post("/settings/github-token")
async def save_github_token(
    request: Request,
    github_token: str = Form(...),
):
    """Save (or clear) the GitHub Personal Access Token used to clone private repos."""
    redirect = _require_login(request)
    if redirect:
        return redirect

    token = github_token.strip()

    settings.github_token = token

    import pathlib, os
    token_path = pathlib.Path(settings.github_token_override_file)
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token)
        os.chmod(token_path, 0o600)
        log.info("GitHub token override written to %s", token_path)
    except OSError as exc:
        log.warning("Could not persist GitHub token to %s: %s", token_path, exc)

    if token:
        request.session["flash_message"] = "GitHub token saved. Private repositories can now be cloned."
    else:
        request.session["flash_message"] = "GitHub token cleared."
    return RedirectResponse("/panel/settings", status_code=302)


# ── Issue SSL certificate ─────────────────────────────────────────────────────

@router.post("/sites/{site_name}/issue-cert")
async def issue_cert_ui(request: Request, site_name: str, db: Session = Depends(get_db)):
    """Issue (or renew) a TLS certificate for the site via the internal CA."""
    redirect = _require_login(request)
    if redirect:
        return redirect

    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        return RedirectResponse("/panel/", status_code=302)

    from pathlib import Path as _Path
    from app.models import Certificate
    from app.services.cert import issue_cert
    from app.services.proxy import write_vhost, reload_proxy

    cert_dir = _Path(settings.certs_base_dir) / site.name
    try:
        cert_path, key_path, valid_until = issue_cert(site.domain, cert_dir)
    except Exception as exc:
        log.exception("UI: cert issuance failed for %s", site_name)
        request.session["flash_error"] = f"Certificate issuance failed: {exc}"
        return RedirectResponse(f"/panel/sites/{site.name}", status_code=302)

    # Replace any existing cert records for this site
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

    # Update the proxy vhost to serve over HTTPS if the site is already running
    if site.container_id:
        try:
            write_vhost(site, tls=True)
            reload_proxy()
        except Exception as exc:
            log.warning("UI: could not reload proxy with TLS for %s: %s", site_name, exc)

    request.session["flash_message"] = (
        f"TLS certificate issued for {site.domain}."
        + (" Nginx reloaded with HTTPS." if site.container_id else
           " Deploy the site to activate HTTPS.")
    )
    return RedirectResponse(f"/panel/sites/{site.name}", status_code=302)


# ── Environment variables editor ──────────────────────────────────────────────

@router.post("/sites/{site_name}/env")
async def update_env_ui(
    request: Request,
    site_name: str,
    env_text: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Update a site's environment variables from a KEY=VALUE textarea.

    Lines starting with ``#`` and blank lines are ignored.  Each remaining
    line must contain an ``=`` sign.  The parsed variables are stored as JSON
    in ``site.env_vars`` and take effect on the next deploy.
    """
    redirect = _require_login(request)
    if redirect:
        return redirect

    site = db.query(Site).filter(Site.name == site_name).first()
    if not site:
        return RedirectResponse("/panel/", status_code=302)

    import json as _json

    env_vars: dict[str, str] = {}
    errors: list[str] = []
    for lineno, raw in enumerate(env_text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append(f"Line {lineno}: missing '=' in {line!r}")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            errors.append(f"Line {lineno}: empty key")
            continue
        env_vars[key] = value  # value may contain '=' characters — that's fine

    if errors:
        request.session["flash_error"] = "Invalid .env format: " + "; ".join(errors)
        return RedirectResponse(f"/panel/sites/{site.name}", status_code=302)

    site.env_vars = _json.dumps(env_vars) if env_vars else None
    db.commit()
    log.info("UI: updated env vars for site %s (%d vars)", site.name, len(env_vars))
    request.session["flash_message"] = (
        f"Environment variables saved ({len(env_vars)} variable(s)). "
        "Redeploy the site for changes to take effect."
    )
    return RedirectResponse(f"/panel/sites/{site.name}", status_code=302)
