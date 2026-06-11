"""PL_CMS per-site deployment service."""
import json
import logging
import secrets
import string
from pathlib import Path

import yaml

from app.config import settings

log = logging.getLogger(__name__)

_REQUIRED_SECRET_KEYS = frozenset(
    {
        "postgres_db",
        "postgres_user",
        "postgres_password",
        "jwt_access_secret",
        "jwt_refresh_secret",
    }
)
_RESERVED_API_ENV = frozenset(
    {
        "NODE_ENV",
        "PORT",
        "DATABASE_URL",
        "REDIS_URL",
        "JWT_ACCESS_SECRET",
        "JWT_REFRESH_SECRET",
        "JWT_ACCESS_EXPIRES_IN",
        "JWT_REFRESH_EXPIRES_IN",
        "WEB_BASE_URL",
        "NEXT_PUBLIC_API_BASE_URL",
        "API_BASE_URL",
    }
)
_REQUIRED_BUILD_CONTEXT_PATHS = (
    "pnpm-workspace.yaml",
    "pnpm-lock.yaml",
    "apps/web/package.json",
    "apps/api/package.json",
    "packages/db/package.json",
)


def _random_secret(length: int = 48) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def site_project_dir(site_name: str) -> Path:
    """Return (and create) the per-site project directory."""
    project_dir = Path(settings.sites_base_dir) / site_name
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _compose_project_name(site_name: str) -> str:
    safe = site_name.replace("-", "_")
    return f"lh_plcms_{safe}"


def get_pl_cms_container_name(site_name: str, service_name: str = "web") -> str:
    """Return the expected container name for a PL_CMS compose service."""
    project = _compose_project_name(site_name)
    return f"{project}-{service_name}-1"


def _image_tag(site_name: str, service_name: str) -> str:
    safe = site_name.replace("-", "_")
    return f"lh_plcms_{safe}_{service_name}:latest"


def _load_env_json(env_vars_json: str | None) -> dict[str, str]:
    if not env_vars_json:
        return {}
    try:
        loaded = json.loads(env_vars_json)
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): str(value) for key, value in loaded.items()}


def _load_secrets(secrets_file: Path) -> dict[str, str]:
    if not secrets_file.exists():
        return {}

    loaded: dict[str, str] = {}
    for line in secrets_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            loaded[key] = value
    return loaded


def _load_existing_compose_secrets(compose_file: Path) -> dict[str, str]:
    if not compose_file.exists():
        return {}
    try:
        loaded = yaml.safe_load(compose_file.read_text()) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(loaded, dict):
        return {}

    services = loaded.get("services") or {}
    if not isinstance(services, dict):
        return {}

    postgres_env = (services.get("postgres") or {}).get("environment") or {}
    api_env = (services.get("api") or {}).get("environment") or {}
    if not isinstance(postgres_env, dict) or not isinstance(api_env, dict):
        return {}

    extracted = {
        "postgres_db": str(postgres_env.get("POSTGRES_DB", "")).strip(),
        "postgres_user": str(postgres_env.get("POSTGRES_USER", "")).strip(),
        "postgres_password": str(postgres_env.get("POSTGRES_PASSWORD", "")).strip(),
        "jwt_access_secret": str(api_env.get("JWT_ACCESS_SECRET", "")).strip(),
        "jwt_refresh_secret": str(api_env.get("JWT_REFRESH_SECRET", "")).strip(),
    }
    return {key: value for key, value in extracted.items() if value}


def _identifier(prefix: str, site_name: str, max_length: int = 63) -> str:
    safe_site = site_name.replace("-", "_")
    value = f"{prefix}{safe_site}"
    return value[:max_length]


def _default_secrets(site_name: str) -> dict[str, str]:
    return {
        "postgres_db": _identifier("plcms_", site_name),
        "postgres_user": _identifier("plcms_", site_name),
        "postgres_password": _random_secret(32),
        "jwt_access_secret": _random_secret(48),
        "jwt_refresh_secret": _random_secret(48),
    }


def _merged_secrets(site_name: str, secrets_file: Path, env_vars_json: str | None) -> dict[str, str]:
    defaults = _default_secrets(site_name)
    compose_file = secrets_file.parent / "docker-compose.yml"
    existing = _load_existing_compose_secrets(compose_file)
    if not existing:
        existing = _load_secrets(secrets_file)
    user_env = _load_env_json(env_vars_json)
    merged = {key: existing.get(key) or defaults[key] for key in _REQUIRED_SECRET_KEYS}

    if user_env.get("JWT_ACCESS_SECRET"):
        merged["jwt_access_secret"] = existing.get("jwt_access_secret") or user_env["JWT_ACCESS_SECRET"]
    if user_env.get("JWT_REFRESH_SECRET"):
        merged["jwt_refresh_secret"] = existing.get("jwt_refresh_secret") or user_env["JWT_REFRESH_SECRET"]

    return merged


def _dockerfile_paths(site_dir: Path) -> dict[str, Path]:
    dockerfile_dir = site_dir / ".linkhosting" / "pl_cms"
    return {
        "dir": dockerfile_dir,
        "web": dockerfile_dir / "web.Dockerfile",
        "api": dockerfile_dir / "api.Dockerfile",
    }


def _web_dockerfile() -> str:
    return """\
FROM node:20-bookworm-slim
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@9.0.0 --activate

COPY . .

RUN pnpm install --frozen-lockfile

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NODE_ENV=production

RUN pnpm -r build

EXPOSE 3000
CMD ["pnpm", "--filter", "@pl-cms/web", "start"]
"""


def _api_dockerfile() -> str:
    return """\
FROM node:20-bookworm-slim
WORKDIR /app

RUN corepack enable && corepack prepare pnpm@9.0.0 --activate

COPY . .

RUN pnpm install --frozen-lockfile

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NODE_ENV=production

RUN pnpm -r build

EXPOSE 3001
CMD ["sh", "-lc", "pnpm --filter @pl-cms/db migrate:deploy && pnpm --filter @pl-cms/api start"]
"""


def _write_dockerfiles(site_dir: Path) -> dict[str, Path]:
    dockerfiles = _dockerfile_paths(site_dir)
    dockerfiles["dir"].mkdir(parents=True, exist_ok=True)

    if settings.dev_mode:
        return dockerfiles

    dockerfiles["web"].write_text(_web_dockerfile())
    dockerfiles["api"].write_text(_api_dockerfile())
    return dockerfiles


def _validate_build_context(site_dir: Path) -> None:
    missing_paths = [rel_path for rel_path in _REQUIRED_BUILD_CONTEXT_PATHS if not (site_dir / rel_path).exists()]
    if not missing_paths:
        return

    missing = ", ".join(missing_paths)
    raise RuntimeError(
        "PL_CMS source/build context is missing from "
        f"{site_dir}. Expected the cloned PL_CMS monorepo in the site directory before deploy. "
        f"Missing: {missing}. Re-import or clone the PL_CMS repository into this site directory and retry."
    )


def _build_runtime_config(
    site_name: str,
    domain: str,
    env_vars_json: str | None = None,
    *,
    tls: bool = False,
) -> dict:
    site_dir = site_project_dir(site_name)
    secrets_file = site_dir / ".secrets"
    secrets_map = _merged_secrets(site_name, secrets_file, env_vars_json)
    user_env = _load_env_json(env_vars_json)

    project = _compose_project_name(site_name)
    postgres_container = get_pl_cms_container_name(site_name, "postgres")
    redis_container = get_pl_cms_container_name(site_name, "redis")
    api_container = get_pl_cms_container_name(site_name, "api")
    scheme = "https" if tls else "http"
    public_web_base_url = user_env.get("WEB_BASE_URL") or f"{scheme}://{domain}"
    public_api_base_url = user_env.get("NEXT_PUBLIC_API_BASE_URL") or f"{public_web_base_url.rstrip('/')}/api"
    internal_api_base_url = f"http://{api_container}:3001/api"

    api_env = {
        "NODE_ENV": "production",
        "PORT": "3001",
        "DATABASE_URL": (
            f"postgresql://{secrets_map['postgres_user']}:{secrets_map['postgres_password']}"
            f"@{postgres_container}:5432/{secrets_map['postgres_db']}"
        ),
        "REDIS_URL": f"redis://{redis_container}:6379",
        "JWT_ACCESS_SECRET": secrets_map["jwt_access_secret"],
        "JWT_REFRESH_SECRET": secrets_map["jwt_refresh_secret"],
        "JWT_ACCESS_EXPIRES_IN": user_env.get("JWT_ACCESS_EXPIRES_IN", "15m"),
        "JWT_REFRESH_EXPIRES_IN": user_env.get("JWT_REFRESH_EXPIRES_IN", "7d"),
        "WEB_BASE_URL": public_web_base_url,
    }
    web_env = {
        "NODE_ENV": "production",
        "PORT": "3000",
        "NEXT_PUBLIC_API_BASE_URL": public_api_base_url,
        "API_BASE_URL": internal_api_base_url,
    }

    for key, value in user_env.items():
        if key in _RESERVED_API_ENV:
            continue
        api_env[key] = value
        if key.startswith("NEXT_PUBLIC_"):
            web_env[key] = value

    return {
        "project": project,
        "site_dir": site_dir,
        "secrets": secrets_map,
        "api_env": api_env,
        "web_env": web_env,
        "public_api_base_url": public_api_base_url,
        "public_web_base_url": public_web_base_url,
        "web_image": _image_tag(site_name, "web"),
        "api_image": _image_tag(site_name, "api"),
        "dockerfiles": _dockerfile_paths(site_dir),
    }


def generate_pl_cms_compose(
    site_name: str,
    domain: str,
    env_vars_json: str | None = None,
    *,
    tls: bool = False,
) -> tuple[Path, dict]:
    """Generate docker-compose.yml, Dockerfiles, and secret material for PL_CMS."""
    config = _build_runtime_config(site_name, domain, env_vars_json, tls=tls)
    site_dir: Path = config["site_dir"]
    compose_file = site_dir / "docker-compose.yml"
    dockerfiles = _write_dockerfiles(site_dir)

    compose_data = {
        "name": config["project"],
        "services": {
            "web": {
                "build": {
                    "context": ".",
                    "dockerfile": str(dockerfiles["web"].relative_to(site_dir)),
                    "args": {
                        "NEXT_PUBLIC_API_BASE_URL": config["public_api_base_url"],
                    },
                },
                "image": config["web_image"],
                "restart": "unless-stopped",
                "environment": config["web_env"],
                "depends_on": {"api": {"condition": "service_started"}},
                "networks": ["internal", "proxy"],
                "labels": {
                    "linkhosting.site": site_name,
                    "linkhosting.domain": domain,
                    "linkhosting.type": "pl_cms",
                    "linkhosting.service": "web",
                },
            },
            "api": {
                "build": {
                    "context": ".",
                    "dockerfile": str(dockerfiles["api"].relative_to(site_dir)),
                    "args": {
                        "NEXT_PUBLIC_API_BASE_URL": config["public_api_base_url"],
                    },
                },
                "image": config["api_image"],
                "restart": "unless-stopped",
                "environment": config["api_env"],
                "depends_on": {
                    "postgres": {"condition": "service_healthy"},
                    "redis": {"condition": "service_healthy"},
                },
                "networks": ["internal", "proxy"],
                "labels": {
                    "linkhosting.site": site_name,
                    "linkhosting.domain": domain,
                    "linkhosting.type": "pl_cms",
                    "linkhosting.service": "api",
                },
            },
            "postgres": {
                "image": "postgres:16-alpine",
                "restart": "unless-stopped",
                "environment": {
                    "POSTGRES_DB": config["secrets"]["postgres_db"],
                    "POSTGRES_USER": config["secrets"]["postgres_user"],
                    "POSTGRES_PASSWORD": config["secrets"]["postgres_password"],
                },
                "volumes": [f"{site_name}-postgres-data:/var/lib/postgresql/data"],
                "healthcheck": {
                    "test": [
                        "CMD-SHELL",
                        f"pg_isready -U {config['secrets']['postgres_user']} -d {config['secrets']['postgres_db']}",
                    ],
                    "interval": "10s",
                    "timeout": "5s",
                    "retries": 5,
                },
                "networks": ["internal"],
            },
            "redis": {
                "image": "redis:7-alpine",
                "restart": "unless-stopped",
                "volumes": [f"{site_name}-redis-data:/data"],
                "healthcheck": {
                    "test": ["CMD", "redis-cli", "ping"],
                    "interval": "10s",
                    "timeout": "5s",
                    "retries": 5,
                },
                "networks": ["internal"],
            },
        },
        "volumes": {
            f"{site_name}-postgres-data": None,
            f"{site_name}-redis-data": None,
        },
        "networks": {
            "internal": {"driver": "bridge"},
            "proxy": {"external": True, "name": "linkhosting_proxy"},
        },
    }

    compose_yaml = yaml.dump(compose_data, default_flow_style=False, sort_keys=False)

    if settings.dev_mode:
        return compose_file, config

    compose_file.write_text(compose_yaml)
    log.info("Wrote PL_CMS compose assets")
    return compose_file, config


def deploy_pl_cms(
    site_name: str,
    domain: str,
    env_vars_json: str | None = None,
    *,
    tls: bool = False,
) -> tuple[str, str]:
    """Deploy a PL_CMS site using ``docker compose up -d``.

    Generates the compose file and Dockerfiles then delegates to the shared
    :func:`~app.services.docker_api.run_compose_up` helper so that PL_CMS
    and WordPress follow the exact same execution path.

    Returns (stdout_msg, stderr_msg).
    Raises RuntimeError on failure.
    """
    from app.services.docker_api import run_compose_up

    compose_file, _ = generate_pl_cms_compose(site_name, domain, env_vars_json, tls=tls)

    if settings.dev_mode:
        log.info("[DEV] Would deploy PL_CMS for site %s via docker compose up", site_name)
        return f"[DEV] docker compose deploy for {site_name}", ""

    _validate_build_context(compose_file.parent)
    stdout, stderr = run_compose_up(compose_file)
    log.info("Deployed PL_CMS site %s via docker compose up", site_name)
    return stdout, stderr


def stop_pl_cms(site_name: str) -> tuple[str, str]:
    """Stop and remove PL_CMS deployment containers for *site_name*."""
    if settings.dev_mode:
        log.info("[DEV] Would stop PL_CMS containers for site %s", site_name)
        return f"[DEV] Docker API stop for {site_name}", ""

    from app.services.docker_api import stop_remove_containers

    stop_remove_containers(
        [
            get_pl_cms_container_name(site_name, "web"),
            get_pl_cms_container_name(site_name, "api"),
            get_pl_cms_container_name(site_name, "postgres"),
            get_pl_cms_container_name(site_name, "redis"),
        ]
    )
    log.info("Stopped PL_CMS containers for site %s", site_name)
    return f"PL_CMS site {site_name} stopped", ""
