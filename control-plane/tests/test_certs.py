"""Tests for the certificates API."""
import pytest


def test_create_cert(client, tmp_path, monkeypatch):
    """Create a TLS cert for a site in dev mode."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "certs_base_dir", str(tmp_path))

    # Create a site first
    client.post("/sites", json={"name": "certsite", "site_type": "static"})

    resp = client.post("/sites/certsite/cert")
    assert resp.status_code == 201
    data = resp.json()
    assert data["domain"] == "certsite.local"
    assert data["ca_signed"] is True
    assert data["cert_path"] != ""
    assert data["key_path"] != ""


def test_create_cert_site_not_found(client):
    resp = client.post("/sites/nonexistent/cert")
    assert resp.status_code == 404


def test_list_certs(client, tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "certs_base_dir", str(tmp_path))

    client.post("/sites", json={"name": "certsite", "site_type": "static"})
    client.post("/sites/certsite/cert")

    resp = client.get("/sites/certsite/cert")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_cert_replaces_existing(client, tmp_path, monkeypatch):
    """Issuing a cert twice should replace the old one."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "certs_base_dir", str(tmp_path))

    client.post("/sites", json={"name": "certsite", "site_type": "static"})
    client.post("/sites/certsite/cert")
    client.post("/sites/certsite/cert")

    resp = client.get("/sites/certsite/cert")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_download_ca_cert(client):
    resp = client.get("/ca.crt")
    assert resp.status_code == 200
    # In dev mode returns placeholder
    assert "cert" in resp.text.lower() or "dev" in resp.text.lower()
