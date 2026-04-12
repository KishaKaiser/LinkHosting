"""Internal CoreDNS record management.

Writes per-site A records into the shared hosts file read by CoreDNS, and
signals CoreDNS to reload via SIGHUP so new records are active immediately.

The hosts file is mounted into both the control-plane container and the
CoreDNS container at the path configured by ``settings.dns_hosts_file``.
"""
import logging
from pathlib import Path

from app.config import settings

log = logging.getLogger(__name__)


def _hosts_path() -> Path:
    return Path(settings.dns_hosts_file)


def _read_records() -> dict[str, str]:
    """Return the current hosts file contents as ``{hostname: ip}``."""
    path = _hosts_path()
    records: dict[str, str] = {}
    if not path.exists():
        return records
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            records[parts[1]] = parts[0]
    return records


def _write_records(records: dict[str, str]) -> None:
    """Persist ``{hostname: ip}`` to the hosts file."""
    path = _hosts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CoreDNS hosts file — managed by LinkHosting control-plane",
        "# Do not edit manually; changes will be overwritten.",
        "",
    ]
    for hostname in sorted(records):
        lines.append(f"{records[hostname]}  {hostname}")
    path.write_text("\n".join(lines) + "\n")


def init_dns_hosts_file() -> None:
    """Create the hosts file with an empty record set if it does not exist.

    Called once at panel startup so CoreDNS always finds a valid (possibly
    empty) file from the first moment it tries to read it.
    Does nothing when ``DNS_ENABLED`` is ``false``, when running in dev mode,
    or when the file already exists.
    """
    if not settings.dns_enabled:
        log.debug("DNS disabled — skipping hosts file initialisation")
        return

    if settings.dev_mode:
        log.info("[DEV] Would initialise DNS hosts file")
        return

    path = _hosts_path()
    if path.exists():
        return

    _write_records({})
    log.info("Initialised empty DNS hosts file at %s", path)


def add_dns_record(hostname: str) -> None:
    """Add or update an A record pointing *hostname* to the configured LAN IP.

    Does nothing when ``DNS_ENABLED`` is ``false`` or ``HOST_LAN_IP`` is unset.
    """
    if not settings.dns_enabled:
        log.debug("DNS disabled — skipping add record for %s", hostname)
        return

    ip = settings.host_lan_ip
    if not ip:
        log.warning(
            "HOST_LAN_IP is not set; skipping DNS record for %s. "
            "Set HOST_LAN_IP in .env to enable automatic DNS.",
            hostname,
        )
        return

    if settings.dev_mode:
        log.info("[DEV] Would add DNS record: %s -> %s", hostname, ip)
        return

    records = _read_records()
    records[hostname] = ip
    _write_records(records)
    log.info("Added DNS record: %s -> %s", hostname, ip)
    reload_dns()


def remove_dns_record(hostname: str) -> None:
    """Remove the A record for *hostname* from the hosts file.

    Does nothing when ``DNS_ENABLED`` is ``false``.
    """
    if not settings.dns_enabled:
        log.debug("DNS disabled — skipping remove record for %s", hostname)
        return

    if settings.dev_mode:
        log.info("[DEV] Would remove DNS record for %s", hostname)
        return

    records = _read_records()
    if hostname in records:
        del records[hostname]
        _write_records(records)
        log.info("Removed DNS record for %s", hostname)
        reload_dns()
    else:
        log.debug("DNS record for %s not found; nothing to remove", hostname)


def reload_dns() -> None:
    """Send SIGHUP to CoreDNS so it reloads the hosts file immediately.

    The CoreDNS ``hosts`` plugin also polls for file changes every 5 s, so
    this call is a best-effort optimisation; DNS will converge even if it fails.
    """
    if settings.dev_mode:
        log.info("[DEV] Would reload CoreDNS")
        return

    try:
        from app.services.docker_api import signal_container
        signal_container(settings.dns_container_name, "SIGHUP")
        log.info("CoreDNS reloaded")
    except Exception as exc:
        log.warning(
            "CoreDNS reload failed (container=%s): %s — DNS will self-heal within 5 s",
            settings.dns_container_name,
            exc,
        )
