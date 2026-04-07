"""WordPress per-site docker-compose deployment service."""
import logging
import os
import secrets
import string
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from app.config import settings

log = logging.getLogger(__name__)


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


def generate_wordpress_compose(site_name: str, domain: str) -> tuple[Path, dict]:
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
                "image": "wordpress:latest",
                "restart": "unless-stopped",
                "environment": {
                    "WORDPRESS_DB_HOST": "db",
                    "WORDPRESS_DB_USER": db_user,
                    "WORDPRESS_DB_PASSWORD": db_password,
                    "WORDPRESS_DB_NAME": db_name,
                    "WORDPRESS_TABLE_PREFIX": table_prefix,
                },
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


def deploy_wordpress(site_name: str, domain: str) -> tuple[str, str]:
    """
    Deploy a WordPress site using docker compose.

    Returns (stdout, stderr) from docker compose up -d.
    Raises RuntimeError on non-zero exit.
    """
    site_dir = site_project_dir(site_name)
    compose_file = site_dir / "docker-compose.yml"

    if not compose_file.exists():
        generate_wordpress_compose(site_name, domain)

    project = _compose_project_name(site_name)

    if settings.dev_mode:
        log.info("[DEV] Would run docker compose up -d for site %s (project=%s)", site_name, project)
        return f"[DEV] docker compose up -d for {site_name}", ""

    result = subprocess.run(
        [
            "docker", "compose",
            "-f", str(compose_file),
            "-p", project,
            "up", "-d", "--remove-orphans",
        ],
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ},
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        raise RuntimeError(
            f"docker compose up failed (exit {result.returncode}):\n{stderr}"
        )

    log.info("Deployed WordPress site %s (project=%s)", site_name, project)
    return stdout, stderr


def get_wordpress_container_name(site_name: str) -> str:
    """Return the expected container name for the wordpress service."""
    project = _compose_project_name(site_name)
    wp_service = _wordpress_service_name(site_name)
    return f"{project}-{wp_service}-1"


def stop_wordpress(site_name: str) -> tuple[str, str]:
    """Stop a WordPress deployment using docker compose down."""
    site_dir = site_project_dir(site_name)
    compose_file = site_dir / "docker-compose.yml"

    if not compose_file.exists():
        log.warning("No compose file found for site %s, nothing to stop", site_name)
        return "", ""

    project = _compose_project_name(site_name)

    if settings.dev_mode:
        log.info("[DEV] Would run docker compose down for site %s", site_name)
        return f"[DEV] docker compose down for {site_name}", ""

    result = subprocess.run(
        [
            "docker", "compose",
            "-f", str(compose_file),
            "-p", project,
            "down",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ},
    )

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        log.warning("docker compose down failed for %s: %s", site_name, stderr)

    return stdout, stderr
