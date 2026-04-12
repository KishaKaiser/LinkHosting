"""GitHub repository import service."""
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import SiteType

log = logging.getLogger(__name__)

# Mapping from detected repo content → SiteType
_DETECTION_CHECKS = [
    # (glob pattern or filename, SiteType)
    ("package.json", SiteType.node),
    ("requirements.txt", SiteType.python),
    ("pyproject.toml", SiteType.python),
    ("setup.py", SiteType.python),
    ("Pipfile", SiteType.python),
    ("composer.json", SiteType.php),
    ("index.php", SiteType.php),
]


def detect_site_type(repo_dir: Path) -> SiteType:
    """Inspect the cloned repo directory and return the most likely SiteType."""
    for filename, site_type in _DETECTION_CHECKS:
        if (repo_dir / filename).exists():
            return site_type

    # PHP: any .php file at root
    if list(repo_dir.glob("*.php")):
        return SiteType.php

    return SiteType.static


def _validate_github_url(repo_url: str) -> str:
    """
    Validate and normalise a GitHub repository URL.
    Accepts:
      - https://github.com/owner/repo
      - https://github.com/owner/repo.git
      - github.com/owner/repo
    Raises ValueError for obviously invalid input.
    """
    url = repo_url.strip()
    # Prepend scheme if missing
    if url.startswith("github.com/"):
        url = "https://" + url
    if not url.startswith("https://github.com/"):
        raise ValueError(
            f"Only GitHub HTTPS URLs are supported (got: {repo_url!r}). "
            "Expected format: https://github.com/owner/repo"
        )
    # Strip trailing slash
    url = url.rstrip("/")
    # Ensure .git suffix for canonical form
    if not url.endswith(".git"):
        url += ".git"
    # Basic structure check: https://github.com/<owner>/<repo>.git
    parts = url[len("https://github.com/"):].split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(
            f"Invalid GitHub URL — expected https://github.com/<owner>/<repo>, got: {repo_url!r}"
        )
    return url


def _inject_token(url: str, token: str) -> str:
    """
    Return an authenticated clone URL by embedding *token* as the HTTP
    username.  The canonical form ``https://github.com/owner/repo.git``
    becomes ``https://<token>@github.com/owner/repo.git``.
    The token is treated as a credential and must never appear in log output.
    """
    return url.replace("https://", f"https://{token}@", 1)


def clone_repo(
    repo_url: str,
    target_dir: Path,
    branch: Optional[str] = None,
) -> None:
    """
    Clone a GitHub repository into *target_dir*.

    If ``settings.github_token`` is set the token is injected into the clone
    URL so that private repositories can be accessed.  The token is never
    written to log output.

    In dev mode, only validates the URL and logs; does not perform a real clone.
    """
    url = _validate_github_url(repo_url)

    if settings.dev_mode:
        log.info("[DEV] Would clone %s (branch=%s) → %s", url, branch or "default", target_dir)
        # Create the directory so callers can inspect it
        target_dir.mkdir(parents=True, exist_ok=True)
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    # Build the clone URL — inject token for private repos if one is configured.
    clone_url = _inject_token(url, settings.github_token) if settings.github_token else url

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [clone_url, str(target_dir)]

    log.info("Cloning %s → %s", url, target_dir)  # log sanitised URL (no token)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},  # never prompt for credentials
    )

    if result.returncode != 0:
        # Strip the token from any error output before surfacing it.
        stderr = result.stderr.strip()
        if settings.github_token:
            stderr = stderr.replace(settings.github_token, "***")
        raise RuntimeError(
            f"git clone failed (exit {result.returncode}): {stderr}"
        )
    log.info("Cloned %s successfully", url)


def pull_repo(site_dir: Path, branch: Optional[str] = None) -> None:
    """Pull latest changes in an already-cloned repo directory."""
    if settings.dev_mode:
        log.info("[DEV] Would pull in %s", site_dir)
        return

    git_dir = site_dir / ".git"
    if not git_dir.exists():
        raise RuntimeError(f"No .git directory found in {site_dir} — was this repo cloned?")

    if branch:
        subprocess.run(
            ["git", "checkout", branch],
            cwd=str(site_dir), capture_output=True, check=True, timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    result = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(site_dir), capture_output=True, text=True, timeout=120,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git pull failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    log.info("Pulled latest changes in %s", site_dir)
