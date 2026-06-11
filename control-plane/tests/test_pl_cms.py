"""Tests for PL_CMS deployment support."""
import importlib
import os
from pathlib import Path
from unittest.mock import patch

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_pl_cms.db"


def _write_pl_cms_build_context(site_dir: Path) -> None:
    (site_dir / "apps" / "web").mkdir(parents=True, exist_ok=True)
    (site_dir / "apps" / "api").mkdir(parents=True, exist_ok=True)
    (site_dir / "packages" / "db").mkdir(parents=True, exist_ok=True)
    (site_dir / "pnpm-workspace.yaml").write_text("packages:\n  - 'apps/*'\n  - 'packages/*'\n")
    (site_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    (site_dir / "apps" / "web" / "package.json").write_text('{"name":"@pl-cms/web"}\n')
    (site_dir / "apps" / "api" / "package.json").write_text('{"name":"@pl-cms/api"}\n')
    (site_dir / "packages" / "db" / "package.json").write_text('{"name":"@pl-cms/db"}\n')


def test_generate_pl_cms_compose_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        compose_file, config = pl_cms_module.generate_pl_cms_compose("plcms", "plcms.link")
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)

    assert not compose_file.exists()
    assert config["public_api_base_url"] == "http://plcms.link/api"
    assert config["web_env"]["API_BASE_URL"] == "http://lh_plcms_plcms-api-1:3001/api"


def test_generate_pl_cms_compose_prod_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        compose_file, config = pl_cms_module.generate_pl_cms_compose("plcms", "plcms.link")
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)

    assert compose_file.exists()
    content = compose_file.read_text()
    assert "postgres:16-alpine" in content
    assert "redis:7-alpine" in content
    assert "lh_plcms_plcms-api-1:3001/api" in content
    assert "http://plcms.link/api" in content
    assert ".linkhosting/pl_cms/web.Dockerfile" in content

    assert config["dockerfiles"]["web"].exists()
    assert config["dockerfiles"]["api"].exists()


def test_generate_pl_cms_compose_reuses_existing_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        _, first = pl_cms_module.generate_pl_cms_compose("plcms", "plcms.link")
        _, second = pl_cms_module.generate_pl_cms_compose("plcms", "plcms.link")
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)

    assert second["secrets"] == first["secrets"]


def test_deploy_pl_cms_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        stdout, stderr = pl_cms_module.deploy_pl_cms("plcms", "plcms.link")
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)
    assert "DEV" in stdout
    assert stderr == ""


def test_stop_pl_cms_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        stdout, stderr = pl_cms_module.stop_pl_cms("plcms")
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)
    assert "DEV" in stdout
    assert stderr == ""


def test_deploy_pl_cms_prod_mode_calls_subprocess(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        _write_pl_cms_build_context(tmp_path / "plcms")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = None
            stdout, stderr = pl_cms_module.deploy_pl_cms("plcms", "plcms.link")
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)

    assert stderr == ""
    assert "plcms" in stdout
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    assert call_args[:3] == ["docker", "compose", "-f"]
    assert call_args[4:] == ["up", "-d"]
    assert "plcms" in call_args[3]  # compose file path contains site name


def test_deploy_pl_cms_prod_mode_fails_early_when_build_context_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        with patch("app.services.docker_api.run_compose_up") as mock_run:
            try:
                pl_cms_module.deploy_pl_cms("plcms", "plcms.link")
                assert False, "Expected RuntimeError"
            except RuntimeError as exc:
                message = str(exc)
                assert "PL_CMS source/build context is missing" in message
                assert "pnpm-workspace.yaml" in message
                assert "apps/web/package.json" in message
                assert str(tmp_path / "plcms") in message
        mock_run.assert_not_called()
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)


def test_proxy_vhost_includes_pl_cms_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import proxy as proxy_module
    importlib.reload(proxy_module)

    from app.models import Site, SiteStatus, SiteType

    site = Site(
        id=1,
        name="plcms",
        domain="plcms.link",
        site_type=SiteType.pl_cms,
        status=SiteStatus.pending,
    )
    try:
        proxy_module.write_vhost(site, tls=False)

        conf = (tmp_path / "plcms.conf").read_text()
        assert "proxy_pass http://lh_plcms_plcms-api-1:3001;" in conf
        assert "proxy_pass http://lh_plcms_plcms-web-1:3000;" in conf
        assert 'proxy_set_header Upgrade $http_upgrade;' in conf
        assert 'proxy_set_header Connection "upgrade";' in conf
    finally:
        config_module.settings = original_settings
        importlib.reload(proxy_module)


def test_deploy_job_created_on_pl_cms_deploy(client, tmp_path, monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "sites_base_dir", str(tmp_path))
    client.post("/sites", json={"name": "plcms", "site_type": "pl_cms"})
    resp = client.post("/sites/plcms/deploy")
    assert resp.status_code == 200

    jobs_resp = client.get("/sites/plcms/jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert len(jobs) >= 1
    assert jobs[0]["status"] == "succeeded"
