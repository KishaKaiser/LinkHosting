"""WordPress per-site deployment service.

Uses the Docker Engine API (via the Python Docker SDK) so that no ``docker``
CLI binary is required inside the worker/panel containers.  The compose YAML
and ``.secrets`` files are still generated for visibility / manual recovery.
"""
import logging
import secrets
import string
import json
from pathlib import Path

import yaml

from app.config import settings

log = logging.getLogger(__name__)
_RESERVED_WORDPRESS_ENV = frozenset(
    {
        "WORDPRESS_DB_HOST",
        "WORDPRESS_DB_USER",
        "WORDPRESS_DB_PASSWORD",
        "WORDPRESS_DB_NAME",
        "WORDPRESS_TABLE_PREFIX",
    }
)


def _random_password(length: int = 24) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def site_project_dir(site_name: str) -> Path:
    """Return (and create) the per-site project directory."""
    p = Path(settings.sites_base_dir) / site_name
    p.mkdir(parents=True, exist_ok=True)
    return p


def _compose_project_name(site_name: str) -> str:
    """Unique docker compose project name for a site."""
    safe = site_name.replace("-", "_")
    return f"lh_wp_{safe}"


def _wordpress_service_name(site_name: str) -> str:
    """Name of the WordPress container in the per-site compose project."""
    return f"wp_{site_name.replace('-', '_')}"


def extract_wordpress_env_overrides(env_vars_json: str | None) -> dict[str, str]:
    """Extract user-defined WordPress env vars from a site's env JSON payload."""
    if not env_vars_json:
        return {}
    try:
        loaded = json.loads(env_vars_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(loaded, dict):
        return {}

    out: dict[str, str] = {}
    for key, value in loaded.items():
        key = str(key)
        if key.startswith("WORDPRESS_") and key not in _RESERVED_WORDPRESS_ENV:
            out[key] = str(value)
    return out


def _wordpress_environment(
    db_container_name: str,
    db_user: str,
    db_password: str,
    db_name: str,
    table_prefix: str,
    wordpress_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = {
        "WORDPRESS_DB_HOST": db_container_name,
        "WORDPRESS_DB_USER": db_user,
        "WORDPRESS_DB_PASSWORD": db_password,
        "WORDPRESS_DB_NAME": db_name,
        "WORDPRESS_TABLE_PREFIX": table_prefix,
    }
    if wordpress_env:
        for key, value in wordpress_env.items():
            if key in _RESERVED_WORDPRESS_ENV:
                continue
            env[key] = str(value)
    return env


def generate_wordpress_compose(
    site_name: str,
    domain: str,
    wordpress_image: str | None = None,
    wordpress_env: dict[str, str] | None = None,
) -> tuple[Path, dict]:
    """
    Generate docker-compose.yml for a WordPress site.

    Returns (compose_file_path, credentials_dict).
    Credentials are also written to a .secrets file in the site directory.
    """
    site_dir = site_project_dir(site_name)
    compose_file = site_dir / "docker-compose.yml"
    secrets_file = site_dir / ".secrets"

    db_root_password = _random_password(32)
    db_name = f"wp_{site_name.replace('-', '_')}"
    db_user = f"wp_{site_name.replace('-', '_')}"
    db_password = _random_password(32)
    table_prefix = "wp_"

    wp_service = _wordpress_service_name(site_name)
    project = _compose_project_name(site_name)

    compose_data = {
        "name": project,
        "services": {
            wp_service: {
                "image": wordpress_image or "wordpress:latest",
                "restart": "unless-stopped",
                "environment": _wordpress_environment(
                    "db",
                    db_user,
                    db_password,
                    db_name,
                    table_prefix,
                    wordpress_env=wordpress_env,
                ),
                "volumes": [
                    f"{site_name}-wp-content:/var/www/html/wp-content",
                ],
                "networks": ["internal", "proxy"],
                "labels": {
                    "linkhosting.site": site_name,
                    "linkhosting.domain": domain,
                    "linkhosting.type": "wordpress",
                },
            },
            "db": {
                "image": "mariadb:10.11",
                "restart": "unless-stopped",
                "environment": {
                    "MARIADB_ROOT_PASSWORD": db_root_password,
                    "MARIADB_DATABASE": db_name,
                    "MARIADB_USER": db_user,
                    "MARIADB_PASSWORD": db_password,
                },
                "volumes": [
                    f"{site_name}-db-data:/var/lib/mysql",
                ],
                "networks": ["internal"],
            },
        },
        "volumes": {
            f"{site_name}-wp-content": None,
            f"{site_name}-db-data": None,
        },
        "networks": {
            "internal": {"driver": "bridge"},
            "proxy": {"external": True, "name": "linkhosting_proxy"},
        },
    }

    compose_yaml = yaml.dump(compose_data, default_flow_style=False, sort_keys=False)

    credentials = {
        "db_name": db_name,
        "db_user": db_user,
        "db_password": db_password,
        "db_root_password": db_root_password,
        "table_prefix": table_prefix,
        "wp_service": wp_service,
        "project": project,
    }

    if settings.dev_mode:
        log.info("[DEV] Would write compose to %s:\n%s", compose_file, compose_yaml)
        log.info("[DEV] Would write secrets to %s", secrets_file)
    else:
        compose_file.write_text(compose_yaml)
        # Write secrets file (not committed to git, chmod 600)
        secrets_lines = "\n".join(f"{k}={v}" for k, v in credentials.items())
        secrets_file.write_text(secrets_lines + "\n")
        secrets_file.chmod(0o600)
        log.info("Wrote WordPress compose for site %s at %s", site_name, compose_file)

    return compose_file, credentials


def deploy_wordpress(
    site_name: str,
    domain: str,
    wordpress_image: str | None = None,
    wordpress_env: dict[str, str] | None = None,
) -> tuple[str, str]:
    """
    Deploy a WordPress site using the Docker Engine API.

    Creates the required networks, volumes, and containers via the Docker SDK.
    Returns (stdout_msg, stderr_msg).
    Raises RuntimeError on failure.
    """
    from app.services.docker_api import (
        create_or_get_network,
        create_volume,
        run_container,
    )

    site_dir = site_project_dir(site_name)
    compose_file = site_dir / "docker-compose.yml"
    secrets_file = site_dir / ".secrets"

    # Ensure compose/secrets files exist (generated once; re-used on redeploy)
    credentials: dict = {}
    if not compose_file.exists():
        _, credentials = generate_wordpress_compose(
            site_name,
            domain,
            wordpress_image=wordpress_image,
            wordpress_env=wordpress_env,
        )
    else:
        # Re-read existing credentials from the secrets file
        if secrets_file.exists():
            for line in secrets_file.read_text().strip().splitlines():
                k, _, v = line.partition("=")
                credentials[k.strip()] = v.strip()
        if not credentials:
            # Regenerate if secrets file is missing or empty
            _, credentials = generate_wordpress_compose(
                site_name,
                domain,
                wordpress_image=wordpress_image,
                wordpress_env=wordpress_env,
            )

    project = _compose_project_name(site_name)
    wp_service = _wordpress_service_name(site_name)

    if settings.dev_mode:
        log.info(
            "[DEV] Would deploy WordPress for site %s via Docker API (project=%s)",
            site_name,
            project,
        )
        return f"[DEV] Docker API deploy for {site_name}", ""

    # ── Networks ──────────────────────────────────────────────────────────────
    # Internal bridge for WP ↔ DB communication (not reachable from outside)
    internal_net = f"{project}_internal"
    # External proxy network – must already exist (created by the main stack)
    proxy_net = "linkhosting_proxy"

    create_or_get_network(internal_net, driver="bridge", internal=True)
    create_or_get_network(proxy_net, driver="bridge", internal=False)

    # ── Volumes ───────────────────────────────────────────────────────────────
    wp_content_vol = f"{project}_{site_name}-wp-content"
    db_data_vol = f"{project}_{site_name}-db-data"

    create_volume(wp_content_vol)
    create_volume(db_data_vol)

    # ── Container names (match docker-compose naming convention) ─────────────
    db_container_name = f"{project}-db-1"
    wp_container_name = f"{project}-{wp_service}-1"

    db_name = credentials["db_name"]
    db_user = credentials["db_user"]
    db_password = credentials["db_password"]
    db_root_password = credentials["db_root_password"]
    table_prefix = credentials.get("table_prefix", "wp_")

    common_labels = {
        "linkhosting.site": site_name,
        "linkhosting.domain": domain,
        "linkhosting.type": "wordpress",
    }

    # ── MariaDB container (internal network only) ─────────────────────────────
    run_container(
        name=db_container_name,
        image="mariadb:10.11",
        environment={
            "MARIADB_ROOT_PASSWORD": db_root_password,
            "MARIADB_DATABASE": db_name,
            "MARIADB_USER": db_user,
            "MARIADB_PASSWORD": db_password,
        },
        volumes={db_data_vol: {"bind": "/var/lib/mysql", "mode": "rw"}},
        network=internal_net,
        labels=common_labels,
    )

    # ── WordPress container (internal + proxy networks) ───────────────────────
    run_container(
        name=wp_container_name,
        image=wordpress_image or "wordpress:latest",
        environment=_wordpress_environment(
            db_container_name,
            db_user,
            db_password,
            db_name,
            table_prefix,
            wordpress_env=wordpress_env,
        ),
        volumes={wp_content_vol: {"bind": "/var/www/html/wp-content", "mode": "rw"}},
        network=internal_net,
        extra_networks=[proxy_net],
        labels=common_labels,
    )

    log.info("Deployed WordPress site %s via Docker API (project=%s)", site_name, project)
    return f"WordPress site {site_name} deployed via Docker API", ""


def get_wordpress_container_name(site_name: str) -> str:
    """Return the expected container name for the wordpress service."""
    project = _compose_project_name(site_name)
    wp_service = _wordpress_service_name(site_name)
    return f"{project}-{wp_service}-1"


def stop_wordpress(site_name: str) -> tuple[str, str]:
    """Stop and remove WordPress deployment containers for *site_name*."""
    if settings.dev_mode:
        log.info("[DEV] Would stop WordPress containers for site %s", site_name)
        return f"[DEV] Docker API stop for {site_name}", ""

    from app.services.docker_api import stop_remove_containers

    project = _compose_project_name(site_name)
    wp_service = _wordpress_service_name(site_name)

    containers = [
        f"{project}-{wp_service}-1",
        f"{project}-db-1",
    ]
    stop_remove_containers(containers)

    log.info("Stopped WordPress containers for site %s", site_name)
    return f"WordPress site {site_name} stopped", ""
