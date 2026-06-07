"""PL_CMS per-site deployment service."""
import json
import logging
import secrets
import string
import time
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
        "secrets_file": secrets_file,
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
    secrets_lines = "\n".join(
        [
            f"postgres_db={config['secrets']['postgres_db']}",
            f"postgres_user={config['secrets']['postgres_user']}",
            f"postgres_password={config['secrets']['postgres_password']}",
            f"jwt_access_secret={config['secrets']['jwt_access_secret']}",
            f"jwt_refresh_secret={config['secrets']['jwt_refresh_secret']}",
        ]
    )
    config["secrets_file"].write_text(secrets_lines + "\n")
    config["secrets_file"].chmod(0o600)
    log.info("Wrote PL_CMS compose for site %s at %s", site_name, compose_file)
    return compose_file, config


def _wait_for_dependencies(site_name: str, config: dict, timeout: int = 60) -> None:
    from app.services.docker_api import exec_in_container

    postgres_container = get_pl_cms_container_name(site_name, "postgres")
    redis_container = get_pl_cms_container_name(site_name, "redis")
    deadline = time.time() + timeout

    postgres_ready = False
    redis_ready = False

    while time.time() < deadline:
        if not postgres_ready:
            pg_code, _ = exec_in_container(
                postgres_container,
                [
                    "pg_isready",
                    "-U",
                    config["secrets"]["postgres_user"],
                    "-d",
                    config["secrets"]["postgres_db"],
                ],
            )
            postgres_ready = pg_code == 0

        if not redis_ready:
            redis_code, redis_output = exec_in_container(redis_container, ["redis-cli", "ping"])
            redis_ready = redis_code == 0 and "PONG" in redis_output

        if postgres_ready and redis_ready:
            return
        time.sleep(2)

    raise RuntimeError("PL_CMS dependencies did not become ready in time")


def deploy_pl_cms(
    site_name: str,
    domain: str,
    env_vars_json: str | None = None,
    *,
    tls: bool = False,
) -> tuple[str, str]:
    """Deploy a PL_CMS site using the Docker Engine API."""
    from app.services.docker_api import (
        build_image,
        create_or_get_network,
        create_volume,
        run_container,
    )

    _, config = generate_pl_cms_compose(site_name, domain, env_vars_json, tls=tls)

    if settings.dev_mode:
        log.info("[DEV] Would deploy PL_CMS for site %s via Docker API", site_name)
        return f"[DEV] Docker API deploy for {site_name}", ""

    project = config["project"]
    internal_net = f"{project}_internal"
    proxy_net = "linkhosting_proxy"
    common_labels = {
        "linkhosting.site": site_name,
        "linkhosting.domain": domain,
        "linkhosting.type": "pl_cms",
    }

    build_image(
        path=str(config["site_dir"]),
        dockerfile=str(config["dockerfiles"]["api"].relative_to(config["site_dir"])),
        tag=config["api_image"],
        buildargs={"NEXT_PUBLIC_API_BASE_URL": config["public_api_base_url"]},
        labels={**common_labels, "linkhosting.service": "api"},
    )
    build_image(
        path=str(config["site_dir"]),
        dockerfile=str(config["dockerfiles"]["web"].relative_to(config["site_dir"])),
        tag=config["web_image"],
        buildargs={"NEXT_PUBLIC_API_BASE_URL": config["public_api_base_url"]},
        labels={**common_labels, "linkhosting.service": "web"},
    )

    create_or_get_network(internal_net, driver="bridge", internal=True)
    create_or_get_network(proxy_net, driver="bridge", internal=False)

    postgres_volume = f"{project}_{site_name}-postgres-data"
    redis_volume = f"{project}_{site_name}-redis-data"
    create_volume(postgres_volume)
    create_volume(redis_volume)

    run_container(
        name=get_pl_cms_container_name(site_name, "postgres"),
        image="postgres:16-alpine",
        environment={
            "POSTGRES_DB": config["secrets"]["postgres_db"],
            "POSTGRES_USER": config["secrets"]["postgres_user"],
            "POSTGRES_PASSWORD": config["secrets"]["postgres_password"],
        },
        volumes={postgres_volume: {"bind": "/var/lib/postgresql/data", "mode": "rw"}},
        network=internal_net,
        labels={**common_labels, "linkhosting.service": "postgres"},
        force_recreate=True,
    )
    run_container(
        name=get_pl_cms_container_name(site_name, "redis"),
        image="redis:7-alpine",
        environment={},
        volumes={redis_volume: {"bind": "/data", "mode": "rw"}},
        network=internal_net,
        labels={**common_labels, "linkhosting.service": "redis"},
        force_recreate=True,
    )

    _wait_for_dependencies(site_name, config)

    run_container(
        name=get_pl_cms_container_name(site_name, "api"),
        image=config["api_image"],
        environment=config["api_env"],
        volumes={},
        network=internal_net,
        extra_networks=[proxy_net],
        labels={**common_labels, "linkhosting.service": "api"},
        force_recreate=True,
    )
    run_container(
        name=get_pl_cms_container_name(site_name, "web"),
        image=config["web_image"],
        environment=config["web_env"],
        volumes={},
        network=internal_net,
        extra_networks=[proxy_net],
        labels={**common_labels, "linkhosting.service": "web"},
        force_recreate=True,
    )

    log.info("Deployed PL_CMS site %s via Docker API (project=%s)", site_name, project)
    return f"PL_CMS site {site_name} deployed via Docker API", ""


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
