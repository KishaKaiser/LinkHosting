"""Tests for PL_CMS deployment support."""
import importlib
import os
from unittest.mock import patch

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_pl_cms.db"


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


def test_deploy_pl_cms_prod_mode_calls_docker_api(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    from app.services import pl_cms as pl_cms_module
    importlib.reload(pl_cms_module)

    try:
        with (
            patch("app.services.docker_api.build_image") as mock_build,
            patch("app.services.docker_api.create_or_get_network") as mock_net,
            patch("app.services.docker_api.create_volume") as mock_vol,
            patch("app.services.docker_api.run_container") as mock_run,
            patch.object(pl_cms_module, "_wait_for_dependencies") as mock_wait,
        ):
            stdout, stderr = pl_cms_module.deploy_pl_cms("plcms", "plcms.link")
    finally:
        config_module.settings = original_settings
        importlib.reload(pl_cms_module)

    assert stderr == ""
    assert "plcms" in stdout
    assert mock_build.call_count == 2
    assert mock_net.call_count == 2
    assert mock_vol.call_count == 2
    assert mock_run.call_count == 4
    assert mock_wait.call_count == 1

    api_call = mock_run.call_args_list[2]
    web_call = mock_run.call_args_list[3]
    assert api_call.kwargs["environment"]["DATABASE_URL"].startswith("postgresql://")
    assert web_call.kwargs["environment"]["API_BASE_URL"] == "http://lh_plcms_plcms-api-1:3001/api"
    assert web_call.kwargs["extra_networks"] == ["linkhosting_proxy"]


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
