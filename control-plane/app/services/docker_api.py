"""Docker helpers for the control-plane.

Provides:
* ``run_compose_up`` – shared entry-point for all compose-based deployments.
* Lower-level helpers that wrap the Python Docker SDK for operations that do
  not have a compose equivalent (e.g. stopping individual containers, sending
  signals, exec inside a running container).
"""
import logging
import subprocess
from pathlib import Path

import docker
import docker.errors

from app.config import settings

log = logging.getLogger(__name__)


def _client() -> docker.DockerClient:
    """Return a Docker client connected via the configured socket."""
    return docker.DockerClient(base_url=settings.docker_socket)


def run_compose_up(compose_file: Path) -> tuple[str, str]:
    """Bring up all services defined in *compose_file* with ``docker compose up -d``.

    Both WordPress and PL_CMS deployments share this single execution path so
    that the exact same CLI is always used regardless of site type.

    Returns ``(stdout_msg, stderr_msg)``.  Raises ``RuntimeError`` on failure.
    """
    try:
        subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "docker CLI is not available in the control-plane runtime. "
            "Ensure the runtime image includes Docker CLI support."
        ) from exc
    except subprocess.CalledProcessError as exc:
        details: list[str] = []
        if exc.stderr and exc.stderr.strip():
            details.append(f"stderr:\n{exc.stderr.strip()}")
        if exc.stdout and exc.stdout.strip():
            details.append(f"stdout:\n{exc.stdout.strip()}")

        detail_msg = f"\n\n{'\n\n'.join(details)}" if details else ""
        raise RuntimeError(
            f"docker compose up failed for {compose_file} (exit {exc.returncode}).{detail_msg}"
        ) from exc
    log.info("docker compose up -d succeeded for %s", compose_file)
    return f"Started services from {compose_file}", ""


def stop_remove_containers(names: list) -> None:
    """Stop and remove a list of containers by name (best-effort)."""
    client = _client()
    for name in names:
        try:
            c = client.containers.get(name)
            c.stop(timeout=10)
            c.remove()
            log.info("Removed container %s", name)
        except docker.errors.NotFound:
            log.debug("Container %s not found, skipping", name)
        except Exception as exc:
            log.warning("Error removing container %s: %s", name, exc)


def remove_volumes(names: list) -> None:
    """Remove a list of named volumes (best-effort)."""
    client = _client()
    for name in names:
        try:
            vol = client.volumes.get(name)
            vol.remove()
            log.info("Removed volume %s", name)
        except docker.errors.NotFound:
            log.debug("Volume %s not found, skipping", name)
        except Exception as exc:
            log.warning("Error removing volume %s: %s", name, exc)


def exec_in_container(container_name: str, cmd: list) -> tuple[int, str]:
    """Run *cmd* inside *container_name*.  Returns ``(exit_code, output_str)``."""
    client = _client()
    try:
        container = client.containers.get(container_name)
        result = container.exec_run(cmd)
        output = result.output.decode("utf-8", errors="replace") if result.output else ""
        return result.exit_code, output
    except Exception as exc:
        log.error("exec_in_container failed for %s: %s", container_name, exc)
        return 1, str(exc)


def signal_container(container_name: str, signal: str = "SIGHUP") -> None:
    """Send a Unix signal to PID 1 inside the named container."""
    client = _client()
    try:
        container = client.containers.get(container_name)
        container.kill(signal=signal)
        log.info("Sent %s to container %s", signal, container_name)
    except Exception as exc:
        log.error("signal_container failed for %s: %s", container_name, exc)
        raise
