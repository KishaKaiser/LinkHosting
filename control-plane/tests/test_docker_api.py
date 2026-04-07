"""Unit tests for docker_api helper module (mocking Docker SDK)."""
import os
import pytest
from unittest.mock import MagicMock, patch, call

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_docker_api.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client_mock(
    *,
    network_exists: bool = False,
    volume_exists: bool = False,
    container_status: str = "running",
    container_exists: bool = True,
):
    """Return a mock DockerClient wired up for common scenarios."""
    import docker.errors

    mock_client = MagicMock()

    # Network mock
    mock_network = MagicMock()
    mock_network.id = "abc123def456"
    if network_exists:
        mock_client.networks.get.return_value = mock_network
    else:
        mock_client.networks.get.side_effect = docker.errors.NotFound("not found")
        mock_client.networks.create.return_value = mock_network

    # Volume mock
    mock_volume = MagicMock()
    mock_volume.name = "test_volume"
    if volume_exists:
        mock_client.volumes.get.return_value = mock_volume
    else:
        mock_client.volumes.get.side_effect = docker.errors.NotFound("not found")
        mock_client.volumes.create.return_value = mock_volume

    # Container mock
    mock_container = MagicMock()
    mock_container.id = "deadbeef1234"
    mock_container.status = container_status
    if container_exists:
        mock_client.containers.get.return_value = mock_container
    else:
        mock_client.containers.get.side_effect = docker.errors.NotFound("not found")
    mock_client.containers.run.return_value = mock_container

    return mock_client


# ── create_or_get_network ─────────────────────────────────────────────────────

def test_create_or_get_network_existing():
    """If the network already exists get() is called, create() is not."""
    mock_client = _make_client_mock(network_exists=True)
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        net_id = docker_api.create_or_get_network("my_net")
    assert net_id == mock_client.networks.get.return_value.id
    mock_client.networks.create.assert_not_called()


def test_create_or_get_network_creates_when_missing():
    """If the network does not exist it should be created."""
    mock_client = _make_client_mock(network_exists=False)
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        net_id = docker_api.create_or_get_network("new_net", driver="bridge", internal=True)
    mock_client.networks.create.assert_called_once_with("new_net", driver="bridge", internal=True)
    assert net_id == mock_client.networks.create.return_value.id


# ── create_volume ─────────────────────────────────────────────────────────────

def test_create_volume_existing():
    mock_client = _make_client_mock(volume_exists=True)
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        name = docker_api.create_volume("my_vol")
    assert name == mock_client.volumes.get.return_value.name
    mock_client.volumes.create.assert_not_called()


def test_create_volume_creates_when_missing():
    mock_client = _make_client_mock(volume_exists=False)
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        docker_api.create_volume("new_vol")
    mock_client.volumes.create.assert_called_once_with("new_vol")


# ── run_container ─────────────────────────────────────────────────────────────

def test_run_container_already_running():
    """If a container with that name is already running, skip creation."""
    mock_client = _make_client_mock(container_exists=True, container_status="running")
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        cid = docker_api.run_container(
            name="my_container",
            image="nginx",
            environment={},
            volumes={},
            network="my_net",
            labels={},
        )
    mock_client.containers.run.assert_not_called()
    assert cid == mock_client.containers.get.return_value.id


def test_run_container_removes_stale_and_starts():
    """Stopped container should be removed then re-created."""
    mock_client = _make_client_mock(container_exists=True, container_status="exited")
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        cid = docker_api.run_container(
            name="my_container",
            image="nginx",
            environment={"FOO": "bar"},
            volumes={"vol": {"bind": "/data", "mode": "rw"}},
            network="my_net",
            labels={"key": "val"},
        )
    mock_client.containers.get.return_value.remove.assert_called_once_with(force=True)
    mock_client.containers.run.assert_called_once()
    assert cid == mock_client.containers.run.return_value.id


def test_run_container_new():
    """New container (no existing) should be started directly."""
    mock_client = _make_client_mock(container_exists=False)
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        cid = docker_api.run_container(
            name="brand_new",
            image="wordpress:latest",
            environment={},
            volumes={},
            network="net",
            labels={},
        )
    mock_client.containers.run.assert_called_once()
    assert cid == mock_client.containers.run.return_value.id


def test_run_container_attaches_extra_networks():
    """Extra networks should each get a net.connect() call."""
    mock_client = _make_client_mock(container_exists=False)
    mock_extra_net = MagicMock()
    # Clear the side_effect set by _make_client_mock so return_value is used
    mock_client.networks.get.side_effect = None
    mock_client.networks.get.return_value = mock_extra_net

    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        docker_api.run_container(
            name="c1",
            image="img",
            environment={},
            volumes={},
            network="primary_net",
            extra_networks=["proxy_net"],
            labels={},
        )
    # networks.get("proxy_net") and then connect(container)
    mock_extra_net.connect.assert_called_once()


# ── stop_remove_containers ────────────────────────────────────────────────────

def test_stop_remove_containers():
    mock_client = _make_client_mock(container_exists=True)
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        docker_api.stop_remove_containers(["c1", "c2"])
    assert mock_client.containers.get.call_count == 2
    assert mock_client.containers.get.return_value.stop.call_count == 2
    assert mock_client.containers.get.return_value.remove.call_count == 2


def test_stop_remove_containers_not_found():
    """Missing containers should be silently skipped."""
    import docker.errors
    mock_client = MagicMock()
    mock_client.containers.get.side_effect = docker.errors.NotFound("not found")
    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        # Should not raise
        docker_api.stop_remove_containers(["missing"])


# ── exec_in_container ─────────────────────────────────────────────────────────

def test_exec_in_container_success():
    mock_client = _make_client_mock(container_exists=True)
    exec_result = MagicMock()
    exec_result.exit_code = 0
    exec_result.output = b"pong\n"
    mock_client.containers.get.return_value.exec_run.return_value = exec_result

    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        code, output = docker_api.exec_in_container("lh-proxy", ["nginx", "-s", "reload"])
    assert code == 0
    assert "pong" in output


def test_exec_in_container_failure():
    mock_client = MagicMock()
    import docker.errors
    mock_client.containers.get.side_effect = docker.errors.NotFound("not found")

    with patch("app.services.docker_api._client", return_value=mock_client):
        from app.services import docker_api
        code, output = docker_api.exec_in_container("missing", ["cmd"])
    assert code == 1


# ── WordPress deploy_wordpress (Docker SDK path, mocked) ─────────────────────

def test_deploy_wordpress_prod_mode_calls_docker_api(tmp_path, monkeypatch):
    """deploy_wordpress should call docker_api helpers instead of subprocess."""
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    try:
        with (
            patch("app.services.docker_api.create_or_get_network") as mock_net,
            patch("app.services.docker_api.create_volume") as mock_vol,
            patch("app.services.docker_api.run_container") as mock_run,
        ):
            stdout, stderr = wp_module.deploy_wordpress("testsite", "testsite.link")
    finally:
        # Restore settings so subsequent tests are not affected
        config_module.settings = original_settings
        importlib.reload(wp_module)

    # Networks: internal + proxy
    assert mock_net.call_count == 2
    # Volumes: wp-content + db-data
    assert mock_vol.call_count == 2
    # Containers: db + wordpress
    assert mock_run.call_count == 2
    assert "testsite" in stdout


def test_stop_wordpress_prod_mode_calls_docker_api(tmp_path, monkeypatch):
    """stop_wordpress should call stop_remove_containers via docker_api."""
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    try:
        with patch("app.services.docker_api.stop_remove_containers") as mock_stop:
            stdout, stderr = wp_module.stop_wordpress("testsite")
    finally:
        config_module.settings = original_settings
        importlib.reload(wp_module)

    mock_stop.assert_called_once()
    names = mock_stop.call_args[0][0]
    assert any("testsite" in n for n in names)
