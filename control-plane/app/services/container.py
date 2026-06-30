"""Container provisioning service using Docker SDK."""
import json
import logging
import os
import posixpath
import shlex
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import Site, SiteStatus, SiteType

log = logging.getLogger(__name__)

# Default Docker images per site type
DEFAULT_IMAGES: dict[SiteType, str] = {
    SiteType.static: "nginx:alpine",
    SiteType.php: "php:8.3-apache",
    SiteType.node: "node:20-bookworm",
    SiteType.python: "python:3.12-slim",
    SiteType.proxy: "nginx:alpine",
}

# Keep-alive commands for images whose default entrypoint exits immediately
# (e.g. the node/python REPLs quit when run detached without stdin).
# This ensures the container stays running so that docker exec can be used
# for build commands such as `npm install` / `npm run build`.
_KEEPALIVE_COMMANDS: dict[SiteType, list[str]] = {
    SiteType.node: ["tail", "-f", "/dev/null"],
    SiteType.python: ["tail", "-f", "/dev/null"],
}
_NODE_INSTALL_COMMAND_ENV_KEY = "LINKHOSTING_INSTALL_COMMAND"
_NODE_BUILD_COMMAND_ENV_KEY = "LINKHOSTING_BUILD_COMMAND"
_NODE_START_COMMAND_ENV_KEY = "LINKHOSTING_START_COMMAND"
_NODE_WORKDIR_ENV_KEY = "LINKHOSTING_WORKDIR"
_NODE_UPSTREAM_PORT_ENV_KEY = "LINKHOSTING_UPSTREAM_PORT"


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
    if site.site_type == SiteType.node:
        env.setdefault("HOST", "0.0.0.0")
        env.setdefault("PORT", env.get(_NODE_UPSTREAM_PORT_ENV_KEY, "3000"))
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


def _safe_relative_workdir(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().replace("\\", "/")
    if not raw or raw in {".", "./"}:
        return None
    raw = raw.removeprefix("/var/www/html/")
    raw = raw.lstrip("/")
    normalized = posixpath.normpath(raw)
    if normalized in {"", "."} or normalized.startswith("..") or "\0" in normalized:
        return None
    return normalized


def _node_command(site: Site, env: dict[str, str]) -> list[str] | None:
    start_command = env.get(_NODE_START_COMMAND_ENV_KEY, "").strip()
    if not start_command:
        return _KEEPALIVE_COMMANDS.get(site.site_type)

    workdir_rel = _safe_relative_workdir(env.get(_NODE_WORKDIR_ENV_KEY) or site.build_dir)
    workdir = "/var/www/html" if not workdir_rel else f"/var/www/html/{workdir_rel}"
    command_parts = [f"cd {shlex.quote(workdir)}"]

    install_command = env.get(_NODE_INSTALL_COMMAND_ENV_KEY, "").strip()
    build_command = env.get(_NODE_BUILD_COMMAND_ENV_KEY, "").strip()
    if install_command:
        command_parts.append(install_command)
    if build_command:
        command_parts.append(build_command)
    command_parts.append(start_command)
    return ["sh", "-lc", " && ".join(command_parts)]


def _container_command(site: Site, env: dict[str, str]) -> list[str] | None:
    if site.site_type == SiteType.node:
        return _node_command(site, env)
    return _KEEPALIVE_COMMANDS.get(site.site_type)


def _remove_existing_site_container(client, site_name: str) -> None:
    container_name = f"site-{site_name}"
    try:
        existing = client.containers.get(container_name)
    except Exception:
        return
    try:
        existing.stop(timeout=10)
        existing.remove()
        log.info("Removed existing container %s before redeploy", container_name)
    except Exception as exc:
        log.warning("Could not remove existing container %s: %s", container_name, exc)


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
    _remove_existing_site_container(client, site.name)

    container = client.containers.run(
        image=image,
        name=f"site-{site.name}",
        detach=True,
        restart_policy={"Name": "unless-stopped"},
        network=settings.docker_network,
        environment=env,
        volumes=volumes,
        labels=labels,
        command=_container_command(site, env),
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
