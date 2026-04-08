"""
Background deploy job executed by the RQ worker.

Each job:
  1. Generates the per-site docker-compose.yml (if not already present)
  2. Runs `docker compose up -d`
  3. Generates/updates the nginx vhost config
  4. Reloads nginx
  5. Updates the DeployJob and Site records in the database
"""
import logging
import os
from datetime import datetime

log = logging.getLogger(__name__)


def run_wordpress_deploy(job_id: int) -> None:
    """
    Entry point called by the RQ worker.

    *job_id* is the primary key of a DeployJob row.
    Everything is looked up from the database inside this function so the job
    is self-contained and can be re-run after a worker restart.
    """
    # Import here so this module can be imported without the full app context
    # available (e.g. during testing).
    os.environ.setdefault("DATABASE_URL", "sqlite:///./dev.db")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.config import settings
    from app.models import DeployJob, JobStatus, Site, SiteStatus
    from app.services.wordpress import deploy_wordpress, generate_wordpress_compose
    from app.services.proxy import write_vhost, reload_proxy
    from app.services.dns import add_dns_record

    engine = create_engine(settings.database_url, pool_pre_ping=True,
                           connect_args={"check_same_thread": False}
                           if settings.database_url.startswith("sqlite") else {})
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        job = db.query(DeployJob).filter(DeployJob.id == job_id).first()
        if not job:
            log.error("DeployJob %d not found", job_id)
            return

        site = db.query(Site).filter(Site.id == job.site_id).first()
        if not site:
            log.error("Site for DeployJob %d not found", job_id)
            job.status = JobStatus.failed
            job.logs = "Site record not found"
            db.commit()
            return

        job.status = JobStatus.running
        db.commit()

        log_lines: list[str] = []

        try:
            # 1. Generate docker-compose.yml
            compose_file, _ = generate_wordpress_compose(site.name, site.domain)
            log_lines.append(f"Generated compose file: {compose_file}")

            # 2. Run docker compose up -d
            stdout, stderr = deploy_wordpress(site.name, site.domain)
            if stdout:
                log_lines.append(stdout)
            if stderr:
                log_lines.append(stderr)

            # 3. Write nginx vhost and reload
            write_vhost(site, tls=False)
            log_lines.append(f"Wrote nginx vhost for {site.domain}")
            reload_proxy()
            log_lines.append("Nginx reloaded")

            # 4. Add DNS record
            add_dns_record(site.domain)
            log_lines.append(f"Added DNS record for {site.domain}")

            # 5. Update site status
            from app.services.wordpress import get_wordpress_container_name
            site.container_id = get_wordpress_container_name(site.name)
            site.status = SiteStatus.running
            db.commit()

            job.status = JobStatus.succeeded
            job.logs = "\n".join(log_lines)
            db.commit()
            log.info("DeployJob %d for site %s succeeded", job_id, site.name)

        except Exception as exc:
            log.exception("DeployJob %d failed", job_id)
            log_lines.append(f"ERROR: {exc}")
            job.status = JobStatus.failed
            job.logs = "\n".join(log_lines)
            site.status = SiteStatus.error
            db.commit()

    finally:
        db.close()
