"""Unit tests for docker_api helper module."""
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_docker_api.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client_mock(
    *,
    container_status: str = "running",
    container_exists: bool = True,
):
    """Return a mock DockerClient wired up for common scenarios."""
    import docker.errors

    mock_client = MagicMock()

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


# ── run_compose_up ────────────────────────────────────────────────────────────

def test_control_plane_runtime_installs_docker_compose_cli():
    """Control-plane runtime image should include docker CLI + compose plugin.

    Specifically requires docker-ce-cli from Docker's official apt repo, NOT
    the unreliable docker.io package from default Debian sources which does not
    bundle docker-compose-plugin.
    """
    dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile"
    content = dockerfile.read_text()
    assert "docker-ce-cli" in content, "Dockerfile must install docker-ce-cli (not docker.io)"
    assert "docker-compose-plugin" in content, "Dockerfile must install docker-compose-plugin"
    assert "docker.io" not in content, "Dockerfile must NOT install docker.io (use docker-ce-cli instead)"
    assert "download.docker.com" in content, "Dockerfile must add Docker's official apt repo"


def test_run_compose_up_calls_subprocess(tmp_path):
    """run_compose_up should invoke docker compose up -d via subprocess."""
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("version: '3'")

    from app.services import docker_api
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = None
        stdout, stderr = docker_api.run_compose_up(compose_file)

    mock_run.assert_called_once_with(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert str(compose_file) in stdout
    assert stderr == ""


def test_run_compose_up_raises_on_failure(tmp_path):
    """run_compose_up should raise RuntimeError when docker compose exits non-zero."""
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("version: '3'")

    from app.services import docker_api
    error = subprocess.CalledProcessError(
        1,
        ["docker", "compose"],
        output="compose stdout",
        stderr="compose stderr",
    )
    with patch("subprocess.run", side_effect=error):
        try:
            docker_api.run_compose_up(compose_file)
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "docker compose up failed" in str(exc)
            assert "exit 1" in str(exc)
            assert "compose stderr" in str(exc)
            assert "compose stdout" in str(exc)


def test_run_compose_up_raises_clear_error_when_docker_missing(tmp_path):
    """run_compose_up should raise clear RuntimeError when docker CLI is missing."""
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text("version: '3'")

    from app.services import docker_api
    with patch("subprocess.run", side_effect=FileNotFoundError("docker")):
        try:
            docker_api.run_compose_up(compose_file)
            assert False, "Expected RuntimeError"
        except RuntimeError as exc:
            assert "docker CLI is not available" in str(exc)


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


# ── WordPress deploy_wordpress (subprocess path) ──────────────────────────────

def test_deploy_wordpress_prod_mode_calls_subprocess(tmp_path, monkeypatch):
    """deploy_wordpress should call docker compose up -d via subprocess."""
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    try:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = None
            stdout, stderr = wp_module.deploy_wordpress(
                "testsite",
                "testsite.link",
                php_ini_overrides={
                    "upload_max_filesize": "256M",
                    "post_max_size": "128M",
                },
            )
    finally:
        config_module.settings = original_settings
        importlib.reload(wp_module)

    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[:3] == ["docker", "compose", "-f"]
    assert call_args[4:] == ["up", "-d"]
    assert "testsite" in call_args[3]  # compose file path contains site name
    # PHP ini file should have been written
    expected_ini = tmp_path / "testsite" / "php" / "conf.d" / "zz-linkhosting-runtime.ini"
    assert expected_ini.exists()
    assert "upload_max_filesize = 256M" in expected_ini.read_text()
    assert "post_max_size = 128M" in expected_ini.read_text()


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
