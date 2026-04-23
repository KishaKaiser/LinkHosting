"""Unit tests for provisioning service logic (no I/O)."""
import os
import pytest

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_services.db"


def test_random_password_length():
    from app.services.database import _random_password
    pwd = _random_password(32)
    assert len(pwd) == 32


def test_random_password_uniqueness():
    from app.services.database import _random_password
    passwords = {_random_password() for _ in range(10)}
    assert len(passwords) == 10  # all unique


def test_sftp_hash_and_verify():
    from app.services.sftp import hash_password, verify_password
    pwd = "test-password-123"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed)
    assert not verify_password("wrong-password", hashed)


def test_provision_sftp_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("SFTP_BASE_DIR", str(tmp_path))
    # Reload settings to pick up monkeypatched env
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import sftp as sftp_module
    importlib.reload(sftp_module)

    username, password, home_dir = sftp_module.provision_sftp_account("testsite")
    assert username == "sftp-testsite"
    assert len(password) >= 16


def test_provision_container_dev_mode():
    from app.services.container import provision_container
    from app.models import Site, SiteType, SiteStatus

    site = Site(
        id=1,
        name="devsite",
        domain="devsite.local",
        site_type=SiteType.static,
        status=SiteStatus.pending,
    )
    container_id = provision_container(site)
    assert container_id == "dev-container-devsite"


def test_provision_node_container_uses_keepalive_command(tmp_path, monkeypatch):
    """Node.js containers must be started with a keep-alive command so they don't
    exit immediately (which would cause a restart loop and block build commands)."""
    import importlib
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("CERTS_BASE_DIR", str(tmp_path / "certs"))

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    import app.services.container as container_module
    importlib.reload(container_module)

    from app.models import Site, SiteType, SiteStatus

    site = Site(
        id=2,
        name="nodesite",
        domain="nodesite.local",
        site_type=SiteType.node,
        status=SiteStatus.pending,
    )

    mock_container = MagicMock()
    mock_container.id = "abc123"
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    try:
        with patch.object(container_module, "_docker_client", return_value=mock_client):
            with patch.object(container_module, "_ensure_network"):
                container_module.provision_container(site)
    finally:
        config_module.settings = original_settings
        importlib.reload(container_module)

    _, kwargs = mock_client.containers.run.call_args
    assert kwargs.get("command") == ["tail", "-f", "/dev/null"], (
        "Node.js container must use a keep-alive command to prevent restart loops"
    )


def test_provision_static_container_no_keepalive_command(tmp_path, monkeypatch):
    """Static (nginx) containers must NOT override the default command."""
    import importlib
    from unittest.mock import MagicMock, patch

    monkeypatch.setenv("DEV_MODE", "false")
    monkeypatch.setenv("SITES_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("CERTS_BASE_DIR", str(tmp_path / "certs"))

    import app.config as config_module
    original_settings = config_module.settings
    config_module.settings = config_module.Settings()

    import app.services.container as container_module
    importlib.reload(container_module)

    from app.models import Site, SiteType, SiteStatus

    site = Site(
        id=3,
        name="staticsite",
        domain="staticsite.local",
        site_type=SiteType.static,
        status=SiteStatus.pending,
    )

    mock_container = MagicMock()
    mock_container.id = "def456"
    mock_client = MagicMock()
    mock_client.containers.run.return_value = mock_container

    try:
        with patch.object(container_module, "_docker_client", return_value=mock_client):
            with patch.object(container_module, "_ensure_network"):
                container_module.provision_container(site)
    finally:
        config_module.settings = original_settings
        importlib.reload(container_module)

    _, kwargs = mock_client.containers.run.call_args
    assert kwargs.get("command") is None, (
        "Static/nginx containers should not override the image default command"
    )


def test_provision_database_dev_mode():
    from app.services.database import provision_database
    from app.models import DatabaseEngine

    db_name, db_user, password, host, port = provision_database("mysite", DatabaseEngine.postgres)
    assert db_name == "site_mysite"
    assert db_user == "user_mysite"
    assert len(password) >= 16
    assert port == 5432


def test_proxy_write_vhost_dev_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_CONFIG_DIR", str(tmp_path))
    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import proxy as proxy_module
    importlib.reload(proxy_module)

    from app.models import Site, SiteType, SiteStatus
    site = Site(
        id=1,
        name="proxysite",
        domain="proxysite.local",
        site_type=SiteType.static,
        status=SiteStatus.pending,
    )
    # In dev mode this should not raise
    proxy_module.write_vhost(site, tls=False)


def test_proxy_write_vhost_includes_client_max_body_size(tmp_path, monkeypatch):
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
        name="proxysize",
        domain="proxysize.local",
        site_type=SiteType.static,
        status=SiteStatus.pending,
        env_vars='{"LINKHOSTING_CLIENT_MAX_BODY_SIZE":"64M"}',
    )
    conf_path = proxy_module.write_vhost(site, tls=False)
    assert conf_path.exists()
    assert "client_max_body_size 64M;" in conf_path.read_text()


def test_cert_dev_mode(tmp_path):
    from app.services.cert import issue_cert
    cert_path, key_path, valid_until = issue_cert("testsite.local", tmp_path)
    assert cert_path.exists()
    assert key_path.exists()


def test_get_ca_cert_pem_dev_mode():
    from app.services.cert import get_ca_cert_pem
    pem = get_ca_cert_pem()
    assert "cert" in pem.lower() or "dev" in pem.lower()


# ── DNS service tests ──────────────────────────────────────────────────────

def test_dns_init_hosts_file_creates_file(tmp_path, monkeypatch):
    """init_dns_hosts_file should create an empty hosts file when absent."""
    hosts_file = tmp_path / "hosts"
    monkeypatch.setenv("DNS_HOSTS_FILE", str(hosts_file))
    monkeypatch.setenv("DNS_ENABLED", "true")
    monkeypatch.setenv("DEV_MODE", "false")

    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import dns as dns_module
    importlib.reload(dns_module)

    assert not hosts_file.exists()
    dns_module.init_dns_hosts_file()
    assert hosts_file.exists()
    # Calling again should be a no-op (idempotent)
    mtime = hosts_file.stat().st_mtime
    dns_module.init_dns_hosts_file()
    assert hosts_file.stat().st_mtime == mtime


def test_dns_init_hosts_file_skips_when_disabled(tmp_path, monkeypatch):
    """init_dns_hosts_file should do nothing when DNS_ENABLED=false."""
    hosts_file = tmp_path / "hosts"
    monkeypatch.setenv("DNS_HOSTS_FILE", str(hosts_file))
    monkeypatch.setenv("DNS_ENABLED", "false")
    monkeypatch.setenv("DEV_MODE", "false")

    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import dns as dns_module
    importlib.reload(dns_module)

    dns_module.init_dns_hosts_file()
    assert not hosts_file.exists()


def test_dns_add_record_dev_mode(tmp_path, monkeypatch):
    """In dev mode, add_dns_record should log but not write any file."""
    monkeypatch.setenv("DNS_HOSTS_FILE", str(tmp_path / "hosts"))
    monkeypatch.setenv("HOST_LAN_IP", "192.168.4.32")

    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import dns as dns_module
    importlib.reload(dns_module)

    dns_module.add_dns_record("mysite.link")
    # dev mode: file should NOT be created
    assert not (tmp_path / "hosts").exists()


def test_dns_remove_record_dev_mode(tmp_path, monkeypatch):
    """In dev mode, remove_dns_record should log but not touch any file."""
    monkeypatch.setenv("DNS_HOSTS_FILE", str(tmp_path / "hosts"))
    monkeypatch.setenv("HOST_LAN_IP", "192.168.4.32")

    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import dns as dns_module
    importlib.reload(dns_module)

    # Should not raise even when no file exists
    dns_module.remove_dns_record("mysite.link")
    assert not (tmp_path / "hosts").exists()


def test_dns_disabled_skips_write(tmp_path, monkeypatch):
    """When DNS_ENABLED=false, no file should be written."""
    monkeypatch.setenv("DNS_HOSTS_FILE", str(tmp_path / "hosts"))
    monkeypatch.setenv("HOST_LAN_IP", "192.168.4.32")
    monkeypatch.setenv("DNS_ENABLED", "false")
    # Turn off dev mode so the disabled check is reached first
    monkeypatch.setenv("DEV_MODE", "false")

    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import dns as dns_module
    importlib.reload(dns_module)

    dns_module.add_dns_record("mysite.link")
    assert not (tmp_path / "hosts").exists()


def test_dns_read_write_records(tmp_path, monkeypatch):
    """_read_records / _write_records round-trip (no Docker calls needed)."""
    hosts_file = tmp_path / "hosts"
    monkeypatch.setenv("DNS_HOSTS_FILE", str(hosts_file))
    monkeypatch.setenv("HOST_LAN_IP", "192.168.4.32")
    monkeypatch.setenv("DNS_ENABLED", "true")
    monkeypatch.setenv("DEV_MODE", "false")

    import importlib
    import app.config as config_module
    config_module.settings = config_module.Settings()

    from app.services import dns as dns_module
    importlib.reload(dns_module)

    # Write two records directly
    dns_module._write_records({"alpha.link": "10.0.0.1", "beta.link": "10.0.0.2"})
    assert hosts_file.exists()

    records = dns_module._read_records()
    assert records["alpha.link"] == "10.0.0.1"
    assert records["beta.link"] == "10.0.0.2"

    # Remove one and verify
    del records["alpha.link"]
    dns_module._write_records(records)
    updated = dns_module._read_records()
    assert "alpha.link" not in updated
    assert "beta.link" in updated
