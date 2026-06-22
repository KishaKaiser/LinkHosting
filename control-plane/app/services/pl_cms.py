"""PL_CMS per-site deployment service."""
import json
import logging
import secrets
import shutil
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
_PL_CMS_DEFAULT_REPO_URL = "https://github.com/KishaKaiser/PL_CMS.git"
_PL_CMS_GENERATED_ASSET_PATHS = frozenset({"docker-compose.yml", ".linkhosting", ".secrets"})


def default_pl_cms_repo_url() -> str:
    """Return the GitHub repository used for one-click PL_CMS installs."""
    return _PL_CMS_DEFAULT_REPO_URL


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
FROM node:22-bookworm-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates openssl \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable

COPY . .

RUN pnpm install --frozen-lockfile

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NODE_ENV=production

RUN node -e 'const fs=require("fs"); const q=String.fromCharCode(39); const p="apps/web/src/app/api/auth/login/route.ts"; if (fs.existsSync(p)) { let src=fs.readFileSync(p,"utf8"); src=src.replace("const isProduction = process.env.NODE_ENV === "+q+"production"+q+";","const forwardedProto = req.headers.get("+q+"x-forwarded-proto"+q+") ?? "+q+q+"; const secureCookie = process.env.NODE_ENV === "+q+"production"+q+" && forwardedProto === "+q+"https"+q+";"); src=src.replaceAll("secure: isProduction,", "secure: secureCookie,"); fs.writeFileSync(p, src); }'

RUN pnpm -r build

EXPOSE 3000
CMD ["pnpm", "--filter", "@pl-cms/web", "start"]
"""


def _api_dockerfile() -> str:
    return """\
FROM node:22-bookworm-slim
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates openssl \
    && rm -rf /var/lib/apt/lists/*

RUN corepack enable

COPY . .

RUN pnpm install --frozen-lockfile

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NODE_ENV=production

RUN pnpm -r build

RUN node -e "const fs=require('fs'); const p='packages/shared/package.json'; if (fs.existsSync(p) && fs.existsSync('packages/shared/dist/index.js')) { const pkg=JSON.parse(fs.readFileSync(p,'utf8')); pkg.main='./dist/index.js'; pkg.module='./dist/index.js'; pkg.types='./dist/index.d.ts'; pkg.exports={'.':{types:'./dist/index.d.ts',import:'./dist/index.js',require:'./dist/index.js'}}; fs.writeFileSync(p, JSON.stringify(pkg,null,2)); }"

RUN node -e 'const fs=require("fs"); const q=String.fromCharCode(39); const pkgPath="packages/db/package.json"; if (fs.existsSync(pkgPath)) { const pkg=JSON.parse(fs.readFileSync(pkgPath,"utf8")); pkg.scripts=pkg.scripts||{}; pkg.scripts["migrate:deploy"]="prisma db push --accept-data-loss --schema=prisma/schema.prisma"; fs.writeFileSync(pkgPath, JSON.stringify(pkg,null,2)); } const installPath="apps/api/dist/install/install.service.js"; if (fs.existsSync(installPath)) { let src=fs.readFileSync(installPath,"utf8"); src=src.split("migrate deploy").join("db push --accept-data-loss"); src=src.split(q+"migrate"+q+", "+q+"deploy"+q).join(q+"db"+q+", "+q+"push"+q+", "+q+"--accept-data-loss"+q); src=src.split("path.resolve(process.cwd(), "+q+"packages/db/prisma/schema.prisma"+q+")").join("path.resolve("+q+"/app"+q+", "+q+"packages/db/prisma/schema.prisma"+q+")"); fs.writeFileSync(installPath, src); }'

EXPOSE 3001
CMD ["sh", "-c", "pnpm --filter @pl-cms/db migrate:deploy && node apps/api/dist/main"]
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


def _stage_pl_cms_source_if_missing(
    site_dir: Path,
    *,
    repo_url: str | None = None,
    repo_branch: str | None = None,
) -> None:
    if all((site_dir / rel_path).exists() for rel_path in _REQUIRED_BUILD_CONTEXT_PATHS):
        return

    from app.services.github import clone_repo, _validate_github_url

    source_repo = _validate_github_url((repo_url or _PL_CMS_DEFAULT_REPO_URL).strip())

    if site_dir.exists():
        existing_paths = {entry.name for entry in site_dir.iterdir()}
        unknown_paths = sorted(existing_paths - _PL_CMS_GENERATED_ASSET_PATHS)
        if unknown_paths:
            log.info(
                "Skipping automatic PL_CMS source import for %s because site directory contains user-managed paths: %s",
                site_dir,
                ", ".join(unknown_paths),
            )
            return
        shutil.rmtree(site_dir)

    clone_repo(source_repo, site_dir, branch=repo_branch)
    log.info("Imported PL_CMS source %s into %s", source_repo, site_dir)


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
    public_api_base_url = user_env.get("NEXT_PUBLIC_API_BASE_URL", "")
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
                "volumes": [f"{site_name}-media-data:/app/storage/media"],
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
            f"{site_name}-media-data": None,
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
    repo_url: str | None = None,
    repo_branch: str | None = None,
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

    if settings.dev_mode:
        log.info("[DEV] Would deploy PL_CMS for site %s via docker compose up", site_name)
        return f"[DEV] docker compose deploy for {site_name}", ""

    site_dir = Path(settings.sites_base_dir) / site_name
    _stage_pl_cms_source_if_missing(
        site_dir,
        repo_url=repo_url,
        repo_branch=repo_branch,
    )
    _validate_build_context(site_dir)
    compose_file, _ = generate_pl_cms_compose(site_name, domain, env_vars_json, tls=tls)
    stdout, stderr = run_compose_up(compose_file)
    log.info("Deployed PL_CMS site %s via docker compose up", site_name)
    return stdout, stderr


def update_pl_cms_source(
    site_name: str,
    domain: str,
    env_vars_json: str | None = None,
    *,
    repo_branch: str | None = None,
    tls: bool = False,
) -> tuple[str, str]:
    """Pull the latest PL_CMS source and rebuild containers without removing data volumes."""
    from app.services.docker_api import run_compose_up
    from app.services.github import pull_repo

    if settings.dev_mode:
        log.info("[DEV] Would update PL_CMS source for site %s", site_name)
        return f"[DEV] PL_CMS source update for {site_name}", ""

    site_dir = Path(settings.sites_base_dir) / site_name
    _validate_build_context(site_dir)
    pull_repo(site_dir, branch=repo_branch)
    compose_file, _ = generate_pl_cms_compose(site_name, domain, env_vars_json, tls=tls)
    stdout, stderr = run_compose_up(compose_file, build=True)
    log.info("Updated PL_CMS site %s from source and rebuilt containers", site_name)
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
