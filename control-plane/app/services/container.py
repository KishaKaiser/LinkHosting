"""Container provisioning service using Docker SDK."""
import json
import logging
import os
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import Site, SiteStatus, SiteType

log = logging.getLogger(__name__)

# Default Docker images per site type
DEFAULT_IMAGES: dict[SiteType, str] = {
    SiteType.static: "nginx:alpine",
    SiteType.php: "php:8.3-apache",
    SiteType.node: "node:20-alpine",
    SiteType.python: "python:3.12-slim",
    SiteType.proxy: "nginx:alpine",
}


def _docker_client():
    import docker
    return docker.from_env()


def _site_volume_dir(site_name: str) -> Path:
    return Path(settings.sites_base_dir) / site_name


def _cert_dir(site_name: str) -> Path:
    return Path(settings.certs_base_dir) / site_name


def _build_env(site: Site) -> dict[str, str]:
    env: dict[str, str] = {}
    if site.env_vars:
        stored = json.loads(site.env_vars)
        env.update(stored)
    return env


def _build_volumes(site: Site) -> dict[str, dict]:
    site_dir = str(_site_volume_dir(site.name))
    cert_dir = str(_cert_dir(site.name))
    volumes: dict[str, dict] = {
        site_dir: {"bind": "/var/www/html", "mode": "rw"},
        cert_dir: {"bind": "/certs", "mode": "ro"},
    }
    return volumes


def _ensure_network() -> None:
    if settings.dev_mode:
        return
    client = _docker_client()
    try:
        client.networks.get(settings.docker_network)
    except Exception:
        client.networks.create(settings.docker_network, driver="bridge")


def provision_container(site: Site) -> str:
    """Create and start a Docker container for a site. Returns container ID."""
    if settings.dev_mode:
        log.info("[DEV] Would provision container for site %s", site.name)
        return f"dev-container-{site.name}"

    _ensure_network()

    image = site.image or DEFAULT_IMAGES[site.site_type]
    env = _build_env(site)
    volumes = _build_volumes(site)

    site_dir = _site_volume_dir(site.name)
    site_dir.mkdir(parents=True, exist_ok=True)
    _cert_dir(site.name).mkdir(parents=True, exist_ok=True)

    labels = {
        "linkhosting.site": site.name,
        "linkhosting.domain": site.domain,
    }

    # Write a placeholder index page if none exists
    index = site_dir / "index.html"
    if site.site_type == SiteType.static and not index.exists():
        index.write_text(f"<h1>Site: {site.name}</h1><p>Deploy your content here.</p>\n")

    client = _docker_client()
    container = client.containers.run(
        image=image,
        name=f"site-{site.name}",
        detach=True,
        restart_policy={"Name": "unless-stopped"},
        network=settings.docker_network,
        environment=env,
        volumes=volumes,
        labels=labels,
    )
    log.info("Started container %s for site %s", container.id[:12], site.name)
    return container.id


def stop_container(site: Site) -> None:
    """Stop and remove a site's container."""
    if settings.dev_mode:
        log.info("[DEV] Would stop container for site %s", site.name)
        return

    if not site.container_id:
        return

    client = _docker_client()
    try:
        container = client.containers.get(site.container_id)
        container.stop(timeout=10)
        container.remove()
        log.info("Removed container %s for site %s", site.container_id[:12], site.name)
    except Exception as exc:
        log.warning("Could not remove container %s: %s", site.container_id, exc)


def get_container_status(site: Site) -> SiteStatus:
    """Return current container status."""
    if settings.dev_mode:
        return SiteStatus.running if site.container_id else SiteStatus.stopped

    if not site.container_id:
        return SiteStatus.stopped

    client = _docker_client()
    try:
        container = client.containers.get(site.container_id)
        state = container.status  # "running", "exited", etc.
        if state == "running":
            return SiteStatus.running
        return SiteStatus.stopped
    except Exception:
        return SiteStatus.error
