"""Tests for the Settings run-migrations endpoint and site run-command endpoint."""
import os
import subprocess

import pytest

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_ui_commands.db"
os.environ["ADMIN_SECRET_KEY"] = "test-secret"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _authenticated_client(client):
    """Log in and return the same client (session cookie set in-place)."""
    client.post("/panel/login", data={"password": "test-secret"})
    return client


def _create_site_via_api(client, name, site_type="node"):
    """Create a site via the REST API and return its JSON."""
    resp = client.post("/sites", json={"name": name, "site_type": site_type})
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── run-migrations ────────────────────────────────────────────────────────────

def test_run_migrations_unauthenticated(client):
    """Unauthenticated POST to run-migrations should redirect to login."""
    resp = client.post("/panel/settings/run-migrations", follow_redirects=False)
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]


def test_run_migrations_success(client, monkeypatch):
    """Successful migration run should flash a success message."""
    _authenticated_client(client)

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(
            args=args, returncode=0, stdout="No new migrations.", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post("/panel/settings/run-migrations", follow_redirects=True)
    assert resp.status_code == 200
    assert "Migrations applied successfully" in resp.text
    assert "alembic" in captured["args"]
    assert "upgrade" in captured["args"]
    assert "head" in captured["args"]


def test_run_migrations_failure(client, monkeypatch):
    """Failed migration should flash an error message."""
    _authenticated_client(client)

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=1, stdout="", stderr="ERROR: migration failed"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post("/panel/settings/run-migrations", follow_redirects=True)
    assert resp.status_code == 200
    assert "Migration failed" in resp.text


def test_run_migrations_timeout(client, monkeypatch):
    """Timeout during migration should flash an error."""
    _authenticated_client(client)

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args, timeout=120)

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post("/panel/settings/run-migrations", follow_redirects=True)
    assert resp.status_code == 200
    assert "timed out" in resp.text.lower()


# ── run-command ───────────────────────────────────────────────────────────────

def test_run_command_unauthenticated(client):
    resp = client.post(
        "/panel/sites/nodesite/run-command",
        data={"preset": "npm install"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]


def test_run_command_site_not_found(client):
    _authenticated_client(client)
    resp = client.post(
        "/panel/sites/no-such-site/run-command",
        data={"preset": "npm install"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/panel/" in resp.headers["location"]


def test_run_command_non_node_site(client):
    """Build commands are only supported for Node.js sites."""
    _authenticated_client(client)
    _create_site_via_api(client, "staticsite2", site_type="static")

    resp = client.post(
        "/panel/sites/staticsite2/run-command",
        data={"preset": "npm install"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "only supported for Node.js" in resp.text


def test_run_command_no_container(client):
    """run-command when no container is running should flash an error."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodenocontainer2", site_type="node")
    # A freshly-created site has no container_id

    resp = client.post(
        "/panel/sites/nodenocontainer2/run-command",
        data={"preset": "npm install"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "not running" in resp.text.lower()


def test_run_command_preset_dev_mode(client):
    """In dev mode a preset command should succeed without calling Docker."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodetestdev2", site_type="node")

    # Simulate a running container by patching deploy
    client.post("/sites/nodetestdev2/deploy")

    resp = client.post(
        "/panel/sites/nodetestdev2/run-command",
        data={"preset": "npm install"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # dev mode flashes a "[DEV] Would run: …" message
    assert "npm" in resp.text.lower()


def test_run_command_custom_invalid(client):
    """Invalid shell syntax in custom command should flash an error."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodecustom2", site_type="node")
    client.post("/sites/nodecustom2/deploy")

    # Unclosed quote → shlex parse error
    resp = client.post(
        "/panel/sites/nodecustom2/run-command",
        data={"custom": "npm run 'unclosed"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Invalid command" in resp.text


def test_run_command_no_selection(client):
    """Posting with neither preset nor custom should flash 'No command selected'."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodenone2", site_type="node")
    client.post("/sites/nodenone2/deploy")

    resp = client.post(
        "/panel/sites/nodenone2/run-command",
        data={"preset": "", "custom": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "No command selected" in resp.text


# ── set-build-dir ─────────────────────────────────────────────────────────────

def test_set_build_dir_unauthenticated(client):
    resp = client.post(
        "/panel/sites/somesite/set-build-dir",
        data={"build_dir": "frontend"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]


def test_set_build_dir_site_not_found(client):
    _authenticated_client(client)
    resp = client.post(
        "/panel/sites/no-such-site/set-build-dir",
        data={"build_dir": "frontend"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/panel/" in resp.headers["location"]


def test_set_build_dir_valid(client):
    """A valid relative subdirectory should be saved and reflected on the site detail page."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodebuilddir1", site_type="node")

    resp = client.post(
        "/panel/sites/nodebuilddir1/set-build-dir",
        data={"build_dir": "frontend"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "frontend" in resp.text


def test_set_build_dir_absolute_container_path(client):
    """Absolute paths under /var/www/html should be accepted and stored as relative."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodebuilddirabs1", site_type="node")

    resp = client.post(
        "/panel/sites/nodebuilddirabs1/set-build-dir",
        data={"build_dir": "/var/www/html/apps/web"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "apps/web" in resp.text


def test_set_build_dir_dot_clears_to_default(client):
    """A '.' value should be treated as the default root directory."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodebuilddirdot1", site_type="node")

    resp = client.post(
        "/panel/sites/nodebuilddirdot1/set-build-dir",
        data={"build_dir": "."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "default" in resp.text.lower() or "Build directory" in resp.text


def test_set_build_dir_clear(client):
    """An empty value should clear the stored build_dir."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodebuilddir2", site_type="node")

    # Set then clear
    client.post("/panel/sites/nodebuilddir2/set-build-dir", data={"build_dir": "apps/web"})
    resp = client.post(
        "/panel/sites/nodebuilddir2/set-build-dir",
        data={"build_dir": ""},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    # Flash message should mention the default
    assert "default" in resp.text.lower() or "Build directory" in resp.text


def test_set_build_dir_traversal_rejected(client):
    """Path traversal attempts should be rejected."""
    _authenticated_client(client)
    _create_site_via_api(client, "nodebuilddir3", site_type="node")

    resp = client.post(
        "/panel/sites/nodebuilddir3/set-build-dir",
        data={"build_dir": "../../etc/passwd"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Invalid build directory" in resp.text


# ── _resolve_workdir helper ───────────────────────────────────────────────────

def test_resolve_workdir():
    """_resolve_workdir should correctly resolve subdirectories and reject traversal."""
    from app.api.ui import _resolve_workdir

    assert _resolve_workdir(None) == "/var/www/html"
    assert _resolve_workdir("") == "/var/www/html"
    assert _resolve_workdir("frontend") == "/var/www/html/frontend"
    assert _resolve_workdir("/frontend") == "/var/www/html/frontend"
    assert _resolve_workdir("apps/web") == "/var/www/html/apps/web"
    assert _resolve_workdir(".") == "/var/www/html"
    assert _resolve_workdir("/var/www/html/apps/web") == "/var/www/html/apps/web"
    # tolerate previously-stored prefixed values
    assert _resolve_workdir("var/www/html/apps/web") == "/var/www/html/apps/web"
    # Traversal attempts must fall back to root
    assert _resolve_workdir("../../etc") == "/var/www/html"
    assert _resolve_workdir("..") == "/var/www/html"


# ── _wait_for_running helper ──────────────────────────────────────────────────

def test_wait_for_running_running_immediately():
    """Container already running should return without sleeping."""
    from unittest.mock import MagicMock
    from app.api.ui import _wait_for_running

    container = MagicMock()
    container.status = "running"
    _wait_for_running(container)  # must not raise


def test_wait_for_running_created_then_running():
    """Container in 'created' state should be polled until it becomes 'running'."""
    from unittest.mock import MagicMock, patch
    from app.api.ui import _wait_for_running

    container = MagicMock()
    container.status = "created"
    calls = []

    def reload_side_effect():
        calls.append(1)
        if len(calls) >= 2:
            container.status = "running"

    container.reload.side_effect = reload_side_effect

    with patch("time.sleep"):
        _wait_for_running(container, timeout=10, interval=1.0)


def test_wait_for_running_restarting_fails_fast():
    """Container in 'restarting' state should fail immediately with a helpful message."""
    import pytest
    from unittest.mock import MagicMock
    from app.api.ui import _wait_for_running

    container = MagicMock()
    container.status = "restarting"

    with pytest.raises(RuntimeError, match="restart loop"):
        _wait_for_running(container)


def test_wait_for_running_exited_fails_fast():
    """Container in 'exited' state should raise immediately."""
    import pytest
    from unittest.mock import MagicMock
    from app.api.ui import _wait_for_running

    container = MagicMock()
    container.status = "exited"

    with pytest.raises(RuntimeError, match="exited"):
        _wait_for_running(container)


def test_wait_for_running_timeout():
    """Container stuck in 'created' state should raise after timeout."""
    import pytest
    from unittest.mock import MagicMock, patch
    from app.api.ui import _wait_for_running

    container = MagicMock()
    container.status = "created"

    with patch("time.sleep"):
        with pytest.raises(RuntimeError, match="did not become ready"):
            _wait_for_running(container, timeout=4, interval=2.0)
