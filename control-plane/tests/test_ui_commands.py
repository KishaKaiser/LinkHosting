"""Tests for the Settings run-migrations endpoint and site run-command endpoint."""
import os
import subprocess
from pathlib import Path

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


def test_web_create_pl_cms_site_records_default_repo(client):
    """Creating PL_CMS from the panel should wire the one-click source repo."""
    _authenticated_client(client)

    resp = client.post(
        "/panel/sites/new",
        data={"name": "panel-plcms", "site_type": "pl_cms"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    site_resp = client.get("/sites/panel-plcms")
    assert site_resp.status_code == 200
    assert site_resp.json()["git_repo"] == "https://github.com/KishaKaiser/PL_CMS.git"


def test_pl_cms_site_page_shows_update_button(client):
    _authenticated_client(client)
    client.post("/sites", json={"name": "panel-plcms-update", "site_type": "pl_cms"})

    resp = client.get("/panel/sites/panel-plcms-update")

    assert resp.status_code == 200
    assert "/panel/sites/panel-plcms-update/update-pl-cms" in resp.text
    assert "Update PL_CMS" in resp.text


def test_panel_deploy_node_site_adds_dns_record(client, monkeypatch):
    """Panel deploy should publish DNS records for direct container site types."""
    _authenticated_client(client)
    _create_site_via_api(client, "panel-node-dns", site_type="node")

    added_domains = []

    def fake_add_dns_record(domain):
        added_domains.append(domain)

    import app.services.dns as dns_module
    monkeypatch.setattr(dns_module, "add_dns_record", fake_add_dns_record)

    resp = client.post(
        "/panel/sites/panel-node-dns/deploy",
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert "panel-node-dns.link" in added_domains


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


# ── LinkHosting app update ─────────────────────────────────────────────────────

def test_update_linkhosting_unauthenticated(client):
    resp = client.post(
        "/panel/settings/update-linkhosting",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]


def test_update_linkhosting_not_configured(client):
    _authenticated_client(client)

    resp = client.post(
        "/panel/settings/update-linkhosting",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "LinkHosting updates are not configured" in resp.text


def test_check_linkhosting_updates_success(client, tmp_path, monkeypatch):
    _authenticated_client(client)
    (tmp_path / ".git").mkdir()

    import app.api.ui as ui_api
    override_dir = tmp_path / "repo_dir_override"
    override_dir.write_text(str(tmp_path))
    override_branch = tmp_path / "repo_branch_override"
    override_branch.write_text("main")
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir_override_file", str(override_dir))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch_override_file", str(override_branch))

    def fake_run(args, **kwargs):
        if args[:3] == ["git", "fetch", "origin"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="aaaaaaaaaaaa\n", stderr="")
        if args == ["git", "rev-parse", "origin/main"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="bbbbbbbbbbbb\n", stderr="")
        if args[:3] == ["git", "merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post(
        "/panel/settings/check-linkhosting-updates",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "LinkHosting update available" in resp.text


def test_update_linkhosting_success(client, tmp_path, monkeypatch):
    _authenticated_client(client)
    (tmp_path / ".git").mkdir()

    # Configure via override files (the path the updated handler reads from)
    import app.api.ui as ui_api
    override_dir = tmp_path / "repo_dir_override"
    override_dir.write_text(str(tmp_path))
    override_branch = tmp_path / "repo_branch_override"
    override_branch.write_text("main")
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir_override_file", str(override_dir))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch_override_file", str(override_branch))

    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs.get("cwd")
        if args[:3] == ["git", "fetch", "origin"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args == ["git", "rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="aaaaaaaaaaaa\n", stderr="")
        if args == ["git", "rev-parse", "origin/main"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="aaaaaaaaaaaa\n", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="Already up to date.\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post(
        "/panel/settings/update-linkhosting",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "LinkHosting updated from GitHub main" in resp.text
    assert captured["args"] == ["git", "pull", "--ff-only", "origin", "main"]
    assert captured["cwd"] == str(tmp_path)


def test_update_linkhosting_failure(client, tmp_path, monkeypatch):
    _authenticated_client(client)
    (tmp_path / ".git").mkdir()

    import app.api.ui as ui_api
    override_dir = tmp_path / "repo_dir_override"
    override_dir.write_text(str(tmp_path))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir_override_file", str(override_dir))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch_override_file", str(tmp_path / "nonexistent"))

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="merge required")

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post(
        "/panel/settings/update-linkhosting",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "LinkHosting update" in resp.text


def test_clear_cache_unauthenticated(client):
    resp = client.post(
        "/panel/settings/clear-cache",
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]


def test_clear_cache_success(client, monkeypatch):
    _authenticated_client(client)

    import app.api.ui as ui_api
    monkeypatch.setattr(ui_api.settings, "dev_mode", False)

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="Total reclaimed space: 12MB\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post(
        "/panel/settings/clear-cache",
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert "Docker build cache cleared" in resp.text
    assert calls == [
        ["docker", "builder", "prune", "-f"],
        ["docker", "image", "prune", "-f"],
    ]


def test_check_pl_cms_updates_success(client, monkeypatch):
    _authenticated_client(client)

    def fake_run(args, **kwargs):
        assert args[:2] == ["git", "ls-remote"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout="cccccccccccccccccccccccccccccccccccccccc\trefs/heads/main\n",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    resp = client.post(
        "/panel/settings/check-pl-cms-updates",
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "PL_CMS source check complete" in resp.text
    assert "cccccccccccc" in resp.text


# ── save-linkhosting-repo ─────────────────────────────────────────────────────

def test_save_linkhosting_repo_unauthenticated(client):
    resp = client.post(
        "/panel/settings/linkhosting-repo",
        data={"repo_dir": "/srv/linkhosting", "repo_branch": "main"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]


def test_save_linkhosting_repo_valid(client, tmp_path, monkeypatch):
    """Valid absolute path and branch should be accepted and reflected on settings page."""
    _authenticated_client(client)

    import app.api.ui as ui_api
    # Redirect override file writes to tmp_path so the test doesn't touch /data
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir_override_file", str(tmp_path / "repo_dir"))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch_override_file", str(tmp_path / "repo_branch"))

    resp = client.post(
        "/panel/settings/linkhosting-repo",
        data={"repo_dir": "/srv/linkhosting", "repo_branch": "release/1.0"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "LinkHosting repo configured" in resp.text
    assert "/srv/linkhosting" in resp.text


def test_save_linkhosting_repo_clear(client, tmp_path, monkeypatch):
    """Empty repo_dir should clear the configuration."""
    _authenticated_client(client)

    import app.api.ui as ui_api
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir_override_file", str(tmp_path / "repo_dir"))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch_override_file", str(tmp_path / "repo_branch"))

    resp = client.post(
        "/panel/settings/linkhosting-repo",
        data={"repo_dir": "", "repo_branch": "main"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "cleared" in resp.text.lower()


def test_save_linkhosting_repo_relative_path_rejected(client):
    """A relative path should be rejected with an error."""
    _authenticated_client(client)

    resp = client.post(
        "/panel/settings/linkhosting-repo",
        data={"repo_dir": "srv/linkhosting", "repo_branch": "main"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "absolute path" in resp.text.lower()


def test_save_linkhosting_repo_invalid_branch_rejected(client):
    """A branch name with shell-unsafe characters should be rejected."""
    _authenticated_client(client)

    resp = client.post(
        "/panel/settings/linkhosting-repo",
        data={"repo_dir": "/srv/linkhosting", "repo_branch": "main; rm -rf /"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "branch name" in resp.text.lower()


# ── settings page linkhosting config resolution ───────────────────────────────

def test_settings_page_shows_override_file_values(client, tmp_path, monkeypatch):
    """Settings page should display values from override files when they exist."""
    _authenticated_client(client)

    import app.api.ui as ui_api

    override_dir = tmp_path / "repo_dir_override"
    override_dir.write_text("/srv/linkhosting")
    override_branch = tmp_path / "repo_branch_override"
    override_branch.write_text("stable")

    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir_override_file", str(override_dir))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch_override_file", str(override_branch))
    # Clear in-memory values to confirm override files take precedence over them
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir", "")
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch", "")

    resp = client.get("/panel/settings", follow_redirects=True)
    assert resp.status_code == 200
    assert "/srv/linkhosting" in resp.text
    assert "stable" in resp.text


def test_settings_page_falls_back_to_env_vars(client, tmp_path, monkeypatch):
    """Settings page should fall back to env vars when override files are absent."""
    _authenticated_client(client)

    import app.api.ui as ui_api

    # Override files do not exist
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir_override_file", str(tmp_path / "nonexistent_dir"))
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch_override_file", str(tmp_path / "nonexistent_branch"))
    # Clear in-memory values
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_dir", "")
    monkeypatch.setattr(ui_api.settings, "linkhosting_repo_branch", "")

    monkeypatch.setenv("LINKHOSTING_REPO_DIR", "/opt/linkhosting")
    monkeypatch.setenv("LINKHOSTING_REPO_BRANCH", "develop")

    resp = client.get("/panel/settings", follow_redirects=True)
    assert resp.status_code == 200
    assert "/opt/linkhosting" in resp.text
    assert "develop" in resp.text


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
    setup_resp = client.post(
        "/panel/sites/nodebuilddirdot1/set-build-dir",
        data={"build_dir": "apps/web"},
        follow_redirects=True,
    )
    assert setup_resp.status_code == 200

    resp = client.post(
        "/panel/sites/nodebuilddirdot1/set-build-dir",
        data={"build_dir": "."},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "/var/www/html (default)" in resp.text
    assert "value=\"apps/web\"" not in resp.text


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


# ── web-settings ───────────────────────────────────────────────────────────────

def test_web_settings_php_site(client):
    _authenticated_client(client)
    _create_site_via_api(client, "phpsettings1", site_type="php")

    resp = client.post(
        "/panel/sites/phpsettings1/web-settings",
        data={"php_version": "8.2", "client_max_body_size": "64M"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Web settings saved" in resp.text
    assert "value=\"8.2\"" in resp.text
    assert "value=\"64M\"" in resp.text

    site_resp = client.get("/sites/phpsettings1")
    assert site_resp.status_code == 200
    assert site_resp.json()["image"] == "php:8.2-apache"


def test_web_settings_wordpress_site(client):
    _authenticated_client(client)
    _create_site_via_api(client, "wpsettings1", site_type="wordpress")

    wp_extra = "define('WP_DEBUG', true);"
    resp = client.post(
        "/panel/sites/wpsettings1/web-settings",
        data={
            "php_version": "8.3",
            "client_max_body_size": "128M",
            "wordpress_config_extra": wp_extra,
            "wp_memory_limit": "256M",
            "wp_max_memory_limit": "512M",
            "upload_max_filesize": "64M",
            "post_max_size": "64M",
            "max_execution_time": "180",
            "max_input_vars": "5000",
            "display_errors": "0",
            "wp_debug": "1",
            "wp_debug_log": "1",
            "wp_cache": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Web settings saved" in resp.text
    assert "value=\"8.3\"" in resp.text
    assert "value=\"128M\"" in resp.text
    assert "value=\"256M\"" in resp.text
    assert "value=\"512M\"" in resp.text
    assert "value=\"5000\"" in resp.text
    assert "value=\"180\"" in resp.text
    assert "WP_DEBUG" in resp.text
    assert "id=\"wp-cache\"" in resp.text

    site_resp = client.get("/sites/wpsettings1")
    assert site_resp.status_code == 200
    assert site_resp.json()["image"] == "wordpress:php8.3-apache"


def test_web_settings_rejects_injection_attempt(client):
    _authenticated_client(client)
    _create_site_via_api(client, "badsize1", site_type="php")

    resp = client.post(
        "/panel/sites/badsize1/web-settings",
        data={"client_max_body_size": "64M;rm -rf /", "php_version": "8.2"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Invalid client_max_body_size" in resp.text
    assert "64M;rm -rf /" not in resp.text

    site_resp = client.get("/sites/badsize1")
    assert site_resp.status_code == 200
    assert site_resp.json()["image"] is None


def test_web_settings_wordpress_rejects_invalid_runtime_values(client):
    _authenticated_client(client)
    _create_site_via_api(client, "badwpsettings1", site_type="wordpress")

    resp = client.post(
        "/panel/sites/badwpsettings1/web-settings",
        data={"max_execution_time": "abc", "wp_debug": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Invalid WordPress runtime settings" in resp.text

    site_resp = client.get("/sites/badwpsettings1")
    assert site_resp.status_code == 200
    assert site_resp.json()["image"] is None


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
    # Tolerate previously-stored prefixed values
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


# ── output truncation helper ────────────────────────────────────────────────────

def test_truncate_command_output_short():
    from app.api.ui import _truncate_command_output

    assert _truncate_command_output("ok", limit=10) == "ok"


def test_truncate_command_output_long():
    from app.api.ui import _truncate_command_output

    output = "A" * 1200 + "B" * 1200
    truncated = _truncate_command_output(output, limit=100)

    assert "... [output truncated] ..." in truncated
    assert truncated.startswith("A")
    assert truncated.endswith("B")
    assert len(truncated) == 100


def test_truncate_command_output_marker_boundary():
    from app.api.ui import _truncate_command_output

    output = "A" * 100
    marker = "... [output truncated] ..."
    truncated = _truncate_command_output(output, limit=len(marker))

    assert truncated == marker


def test_truncate_command_output_tiny_limit():
    from app.api.ui import _truncate_command_output

    output = "A" * 100
    assert _truncate_command_output(output, limit=1) == "."
    assert _truncate_command_output(output, limit=2) == ".."
    assert _truncate_command_output(output, limit=3) == "..."
