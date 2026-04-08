"""Docker Engine API helpers using the Python Docker SDK.

Replaces all ``subprocess`` calls to ``docker``/``docker compose`` inside the
control-plane containers.  The worker and panel containers only need access to
the Docker socket (``/var/run/docker.sock``) – no Docker CLI binary required.
"""
import logging

import docker
import docker.errors

from app.config import settings

log = logging.getLogger(__name__)


def _client() -> docker.DockerClient:
    """Return a Docker client connected via the configured socket."""
    return docker.DockerClient(base_url=settings.docker_socket)


def create_or_get_network(
    name: str,
    driver: str = "bridge",
    internal: bool = False,
) -> str:
    """Ensure a Docker network exists; return its ID."""
    client = _client()
    try:
        net = client.networks.get(name)
        log.debug("Network %s already exists (id=%s)", name, net.id[:12])
        return net.id
    except docker.errors.NotFound:
        net = client.networks.create(name, driver=driver, internal=internal)
        log.info("Created network %s (id=%s)", name, net.id[:12])
        return net.id


def create_volume(name: str) -> str:
    """Ensure a Docker named volume exists; return its name."""
    client = _client()
    try:
        vol = client.volumes.get(name)
        log.debug("Volume %s already exists", name)
        return vol.name
    except docker.errors.NotFound:
        vol = client.volumes.create(name)
        log.info("Created volume %s", name)
        return vol.name


def run_container(
    *,
    name: str,
    image: str,
    environment: dict,
    volumes: dict,
    network: str,
    extra_networks: list | None = None,
    labels: dict,
    restart_policy: str = "unless-stopped",
) -> str:
    """Create and start a container, returning its ID.

    If a container with the same name already exists and is running its ID is
    returned unchanged.  A stopped container with the same name is removed and
    re-created.
    """
    client = _client()

    # Check for an existing container with this name
    try:
        existing = client.containers.get(name)
        if existing.status == "running":
            log.info("Container %s already running (%s)", name, existing.id[:12])
            return existing.id
        # Stopped or otherwise non-running — remove so we can recreate
        existing.remove(force=True)
        log.info("Removed stale container %s", name)
    except docker.errors.NotFound:
        pass

    container = client.containers.run(
        image,
        name=name,
        detach=True,
        environment=environment,
        volumes=volumes,
        network=network,
        labels=labels,
        restart_policy={"Name": restart_policy},
    )

    # Attach to any additional networks
    for net_name in (extra_networks or []):
        try:
            net = client.networks.get(net_name)
            net.connect(container)
            log.debug("Connected container %s to network %s", name, net_name)
        except Exception as exc:
            log.warning("Could not connect %s to network %s: %s", name, net_name, exc)

    log.info("Started container %s (id=%s)", name, container.id[:12])
    return container.id


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
