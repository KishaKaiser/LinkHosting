"""Tests for WordPress deployment and background job models."""
import os
import pytest

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_wordpress.db"


# ── WordPress service unit tests ─────────────────────────────────────────────

def test_generate_wordpress_compose_dev_mode(tmp_path, monkeypatch):
    """In dev mode, compose file generation should not write any files."""
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    compose_file, credentials = wp_module.generate_wordpress_compose("mysite", "mysite.link")

    # In dev mode no real files should be written
    assert not compose_file.exists()
    # Credentials dict should contain the expected keys
    assert "db_name" in credentials
    assert "db_user" in credentials
    assert "db_password" in credentials
    assert "db_root_password" in credentials
    assert credentials["db_name"].startswith("wp_")
    assert len(credentials["db_password"]) >= 24


def test_generate_wordpress_compose_prod_mode(tmp_path, monkeypatch):
    """In prod mode, compose file and secrets file should be written."""
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    compose_file, credentials = wp_module.generate_wordpress_compose("mysite", "mysite.link")

    assert compose_file.exists()
    content = compose_file.read_text()
    assert "wordpress:" in content
    assert "mariadb" in content
    assert credentials["db_password"] in content
    php_ini_file = tmp_path / "mysite" / "php" / "conf.d" / "zz-linkhosting-runtime.ini"
    assert php_ini_file.exists()
    assert str(php_ini_file) in content
    assert "/usr/local/etc/php/conf.d/zz-linkhosting-runtime.ini:ro" in content

    secrets_file = tmp_path / "mysite" / ".secrets"
    assert secrets_file.exists()
    assert oct(secrets_file.stat().st_mode)[-3:] == "600"
    secrets_content = secrets_file.read_text()
    assert f"db_password={credentials['db_password']}" in secrets_content
    assert f"db_root_password={credentials['db_root_password']}" in secrets_content


def test_generate_wordpress_compose_reuses_existing_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    compose_file, first_credentials = wp_module.generate_wordpress_compose("mysite", "mysite.link")
    compose_file, second_credentials = wp_module.generate_wordpress_compose("mysite", "mysite.link")

    for key in ("db_name", "db_user", "db_password", "db_root_password", "table_prefix"):
        assert second_credentials[key] == first_credentials[key]

    content = compose_file.read_text()
    assert second_credentials["db_password"] in content


def test_generate_wordpress_compose_partial_secrets_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    site_dir = tmp_path / "mysite"
    site_dir.mkdir(parents=True, exist_ok=True)
    secrets_file = site_dir / ".secrets"
    secrets_file.write_text(
        "db_user=existing_user\n"
        "db_password=existing_password\n"
        "table_prefix=custom_\n"
        "bad_line_without_equals\n"
        "db_root_password=\n"
    )

    _, credentials = wp_module.generate_wordpress_compose("mysite", "mysite.link")

    assert credentials["db_user"] == "existing_user"
    assert credentials["db_password"] == "existing_password"
    assert credentials["table_prefix"] == "custom_"
    assert credentials["db_name"] == "wp_mysite"
    assert credentials["db_root_password"]


def test_generate_wordpress_compose_with_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    compose_file, _ = wp_module.generate_wordpress_compose(
        "mysite",
        "mysite.link",
        wordpress_image="wordpress:php8.2-apache",
        wordpress_env={"WORDPRESS_CONFIG_EXTRA": "define('WP_DEBUG', true);"},
        php_ini_overrides={"upload_max_filesize": "64M", "post_max_size": "128M"},
    )
    content = compose_file.read_text()
    assert "wordpress:php8.2-apache" in content
    assert "WORDPRESS_CONFIG_EXTRA" in content
    php_ini_content = (tmp_path / "mysite" / "php" / "conf.d" / "zz-linkhosting-runtime.ini").read_text()
    assert "upload_max_filesize = 64M" in php_ini_content
    assert "post_max_size = 128M" in php_ini_content


def test_generate_wordpress_compose_creates_missing_sites_base_parent(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path / "missing" / "sites"))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    compose_file, _ = wp_module.generate_wordpress_compose(
        "mysite",
        "mysite.link",
        php_ini_overrides={"upload_max_filesize": "256M"},
    )

    php_ini_file = tmp_path / "missing" / "sites" / "mysite" / "php" / "conf.d" / "zz-linkhosting-runtime.ini"
    assert compose_file.exists()
    assert php_ini_file.exists()
    assert "upload_max_filesize = 256M" in php_ini_file.read_text()


def test_extract_wordpress_env_overrides():
    from app.services.wordpress import extract_wordpress_env_overrides

    env_json = (
        '{"WORDPRESS_CONFIG_EXTRA":"define(\\"WP_DEBUG\\", true);",'
        '"WP_MEMORY_LIMIT":"256M",'
        '"upload_max_filesize":"64M",'
        '"WP_CACHE":"1",'
        '"WORDPRESS_DB_NAME":"override",'
        '"OTHER":"value"}'
    )
    parsed = extract_wordpress_env_overrides(env_json)
    assert "WORDPRESS_CONFIG_EXTRA" in parsed
    assert "define('WP_MEMORY_LIMIT', '256M');" in parsed["WORDPRESS_CONFIG_EXTRA"]
    assert "define('WP_CACHE', true);" in parsed["WORDPRESS_CONFIG_EXTRA"]
    assert "WORDPRESS_DB_NAME" not in parsed
    assert "OTHER" not in parsed


def test_extract_php_ini_overrides():
    from app.services.wordpress import extract_php_ini_overrides

    env_json = (
        '{"upload_max_filesize":"64M",'
        '"post_max_size":"128M",'
        '"max_execution_time":"180",'
        '"display_errors":"0",'
        '"OTHER":"value"}'
    )
    parsed = extract_php_ini_overrides(env_json)
    assert parsed == {
        "upload_max_filesize": "64M",
        "post_max_size": "128M",
        "max_execution_time": "180",
        "display_errors": "Off",
    }


def test_extract_php_ini_overrides_ignores_injection_attempts():
    from app.services.wordpress import extract_php_ini_overrides

    env_json = (
        '{"upload_max_filesize":"64M\\npost_max_size=128M",'
        '"display_errors":"maybe",'
        '"max_input_vars":"5000"}'
    )
    parsed = extract_php_ini_overrides(env_json)
    assert parsed == {"max_input_vars": "5000"}


def test_compose_project_name():
    from app.services.wordpress import _compose_project_name
    assert _compose_project_name("my-site") == "lh_wp_my_site"
    assert _compose_project_name("mysite") == "lh_wp_mysite"


def test_wordpress_service_name():
    from app.services.wordpress import _wordpress_service_name
    assert _wordpress_service_name("my-site") == "wp_my_site"
    assert _wordpress_service_name("mysite") == "wp_mysite"


def test_wordpress_container_name():
    from app.services.wordpress import get_wordpress_container_name
    name = get_wordpress_container_name("mysite")
    assert "lh_wp_mysite" in name
    assert "wp_mysite" in name


def test_deploy_wordpress_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    # In dev mode, deploy should not raise
    stdout, stderr = wp_module.deploy_wordpress("mysite", "mysite.link")
    assert "DEV" in stdout


def test_stop_wordpress_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import wordpress as wp_module
    importlib.reload(wp_module)

    # In dev mode, stop should not raise and should return a DEV message
    stdout, stderr = wp_module.stop_wordpress("mysite")
    assert "DEV" in stdout
    assert stderr == ""


# ── DeployJob model tests ─────────────────────────────────────────────────────

def test_deploy_job_created_on_wordpress_deploy(client):
    """POSTing to /sites/{name}/deploy for a wordpress site should create a DeployJob."""
    client.post("/sites", json={"name": "wpsite", "site_type": "wordpress"})
    resp = client.post("/sites/wpsite/deploy")
    assert resp.status_code == 200

    # Check jobs endpoint
    jobs_resp = client.get("/sites/wpsite/jobs")
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert len(jobs) >= 1
    job = jobs[0]
    assert job["site_id"] is not None
    assert job["status"] in ("queued", "running", "succeeded", "failed")


def test_list_jobs_endpoint(client):
    client.post("/sites", json={"name": "wpsite", "site_type": "wordpress"})
    client.post("/sites/wpsite/deploy")
    resp = client.get("/jobs")
    assert resp.status_code == 200
    jobs = resp.json()
    assert isinstance(jobs, list)


def test_get_job_endpoint(client):
    client.post("/sites", json={"name": "wpsite", "site_type": "wordpress"})
    client.post("/sites/wpsite/deploy")
    jobs_resp = client.get("/jobs")
    jobs = jobs_resp.json()
    assert len(jobs) >= 1
    job_id = jobs[0]["id"]

    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


def test_get_job_not_found(client):
    resp = client.get("/jobs/99999")
    assert resp.status_code == 404


def test_jobs_for_site_not_found(client):
    resp = client.get("/sites/nonexistent/jobs")
    assert resp.status_code == 404


def test_wordpress_deploy_job_inline_dev_mode(client):
    """In dev mode with no Redis, WordPress deploy should run inline and succeed."""
    client.post("/sites", json={"name": "wpsite", "site_type": "wordpress"})
    resp = client.post("/sites/wpsite/deploy")
    assert resp.status_code == 200

    jobs_resp = client.get("/sites/wpsite/jobs")
    jobs = jobs_resp.json()
    assert len(jobs) >= 1
    # In dev mode inline run: status should be succeeded (ran synchronously)
    assert jobs[0]["status"] == "succeeded"


# ── UI router smoke tests ─────────────────────────────────────────────────────

def test_login_page(client):
    """GET /panel/login should return 200 with login form."""
    resp = client.get("/panel/login", follow_redirects=False)
    # Without session, login page should be served
    assert resp.status_code == 200
    assert b"Sign In" in resp.content or b"Login" in resp.content or b"Password" in resp.content


def test_login_redirect_when_authenticated(client):
    """After posting valid password, should redirect to dashboard."""
    resp = client.post(
        "/panel/login",
        data={"password": "test-secret"},  # matches conftest ADMIN_SECRET_KEY
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/panel/"


def test_login_wrong_password(client):
    """Wrong password should return 401 and stay on login page."""
    resp = client.post(
        "/panel/login",
        data={"password": "wrong-password"},
        follow_redirects=False,
    )
    assert resp.status_code == 401


def test_dashboard_requires_login(client):
    """Dashboard should redirect unauthenticated requests to login."""
    resp = client.get("/panel/", follow_redirects=False)
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]


def test_create_site_page_requires_login(client):
    resp = client.get("/panel/sites/new", follow_redirects=False)
    assert resp.status_code == 302


def test_proxy_vhost_includes_wordpress_container_name(tmp_path, monkeypatch):
    """write_vhost for a WordPress site must proxy_pass to the full container name.

    The container created by deploy_wordpress is named
    ``lh_wp_<safe_name>-wp_<safe_name>-1``.  Using this name (rather than
    ``site-wp_<safe_name>``) is what allows Docker's embedded DNS to resolve
    the upstream inside the ``linkhosting_proxy`` network, preventing the
    ``host not found in upstream`` Nginx error.
    """
    monkeypatch.setenv("PROXY_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import proxy as proxy_module
    importlib.reload(proxy_module)

    from app.models import Site, SiteType, SiteStatus
    site = Site(
        id=1,
        name="wpsite",
        domain="wpsite.link",
        site_type=SiteType.wordpress,
        status=SiteStatus.pending,
    )
    proxy_module.write_vhost(site, tls=False)

    conf = (tmp_path / "wpsite.conf").read_text()
    # proxy_pass must use the full Docker container name so DNS resolves
    expected_upstream = "lh_wp_wpsite-wp_wpsite-1"
    assert f"proxy_pass http://{expected_upstream}:80" in conf
    # Must NOT use the old broken pattern (site-wp_<name>) as the proxy_pass target
    assert "proxy_pass http://site-wp_wpsite" not in conf
    assert "proxy_pass http://site-wpsite" not in conf


def test_proxy_vhost_hyphenated_wordpress_site(tmp_path, monkeypatch):
    """Hyphens in the site name are normalised to underscores in container names."""
    monkeypatch.setenv("PROXY_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import proxy as proxy_module
    importlib.reload(proxy_module)

    from app.models import Site, SiteType, SiteStatus
    site = Site(
        id=2,
        name="psychic-link",
        domain="psychiclink.link",
        site_type=SiteType.wordpress,
        status=SiteStatus.pending,
    )
    proxy_module.write_vhost(site, tls=False)

    conf = (tmp_path / "psychic-link.conf").read_text()
    # Container name follows docker-compose naming: project-service-1
    expected_upstream = "lh_wp_psychic_link-wp_psychic_link-1"
    assert f"proxy_pass http://{expected_upstream}:80" in conf
    assert "site-wp_psychic_link" not in conf


def test_proxy_vhost_tls_uses_site_name_for_certs(tmp_path, monkeypatch):
    """TLS vhost must use site.name (not the upstream container name) for cert paths."""
    monkeypatch.setenv("PROXY_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("DEV_MODE", "false")
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import proxy as proxy_module
    importlib.reload(proxy_module)

    from app.models import Site, SiteType, SiteStatus
    site = Site(
        id=3,
        name="wpsite",
        domain="wpsite.link",
        site_type=SiteType.wordpress,
        status=SiteStatus.pending,
    )
    proxy_module.write_vhost(site, tls=True)

    conf = (tmp_path / "wpsite.conf").read_text()
    # Cert paths must be keyed on the human site name, not the container name
    assert "/etc/nginx/certs/wpsite/cert.pem" in conf
    assert "/etc/nginx/certs/wpsite/key.pem" in conf
    # proxy_pass still uses the full container name
    assert "proxy_pass http://lh_wp_wpsite-wp_wpsite-1:80" in conf
    assert "proxy_pass http://site-wpsite" not in conf
    assert "proxy_pass http://site-wp_wpsite" not in conf
