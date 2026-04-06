"""SFTP account provisioning service."""
import logging
import secrets
import string
from pathlib import Path

from passlib.context import CryptContext

from app.config import settings

log = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SFTP_BASE = Path(settings.sftp_base_dir)
SSH_CONTAINER_NAME = "sftp-server"


def _random_password(length: int = 20) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)


def sftp_username(site_name: str) -> str:
    """Return the SFTP username for a site — deterministic, no secrets."""
    return f"sftp-{site_name}"


def sftp_home_dir(site_name: str) -> str:
    """Return the SFTP home directory for a site — deterministic, no secrets."""
    return str(SFTP_BASE / site_name)


def provision_sftp_account(site_name: str) -> tuple[str, str, str]:
    """
    Create an SFTP account for a site.
    Returns (username, plain_password, home_dir).
    """
    username = sftp_username(site_name)
    home_dir = sftp_home_dir(site_name)
    password = _random_password()

    if settings.dev_mode:
        log.info("[DEV] Would create SFTP account %s -> %s", username, home_dir)
        return username, password, home_dir

    home_path = Path(home_dir) / "www"
    home_path.mkdir(parents=True, exist_ok=True)

    # Write credentials to the SFTP container's auth file
    # This uses the atmoz/sftp or custom sshd image which reads /etc/sftp-users.conf
    _write_sftp_users_entry(username, password, home_dir)

    log.info("Provisioned SFTP account %s -> %s", username, home_dir)
    return username, password, home_dir


def deprovision_sftp_account(username: str) -> None:
    """Remove an SFTP account."""
    if settings.dev_mode:
        log.info("[DEV] Would remove SFTP account %s", username)
        return

    _remove_sftp_users_entry(username)
    log.info("Deprovisioned SFTP account %s", username)


# ── SFTP users file helpers ───────────────────────────────────────────────────
# Format compatible with atmoz/sftp: username:password:uid:gid:homedir

SFTP_USERS_FILE = Path("/data/sftp/users.conf")


def _write_sftp_users_entry(username: str, password: str, home_dir: str) -> None:
    SFTP_USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_sftp_users()
    existing[username] = f"{username}:{password}:::{home_dir}"
    _write_sftp_users(existing)


def _remove_sftp_users_entry(username: str) -> None:
    existing = _read_sftp_users()
    existing.pop(username, None)
    _write_sftp_users(existing)


def _read_sftp_users() -> dict[str, str]:
    if not SFTP_USERS_FILE.exists():
        return {}
    lines = SFTP_USERS_FILE.read_text().splitlines()
    result: dict[str, str] = {}
    for line in lines:
        if line.strip() and not line.startswith("#"):
            user = line.split(":")[0]
            result[user] = line
    return result


def _write_sftp_users(entries: dict[str, str]) -> None:
    content = "\n".join(entries.values()) + "\n"
    SFTP_USERS_FILE.write_text(content)
