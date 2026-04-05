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


def test_cert_dev_mode(tmp_path):
    from app.services.cert import issue_cert
    cert_path, key_path, valid_until = issue_cert("testsite.local", tmp_path)
    assert cert_path.exists()
    assert key_path.exists()


def test_get_ca_cert_pem_dev_mode():
    from app.services.cert import get_ca_cert_pem
    pem = get_ca_cert_pem()
    assert "cert" in pem.lower() or "dev" in pem.lower()
