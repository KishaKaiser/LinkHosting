"""Tests for the SFTP accounts API."""
import pytest


def test_create_sftp_account(client):
    client.post("/sites", json={"name": "sftpsite", "site_type": "static"})

    resp = client.post("/sites/sftpsite/sftp")
    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "sftp-sftpsite"
    assert data["password"] != ""
    assert data["ssh_port"] == 2222


def test_create_sftp_site_not_found(client):
    resp = client.post("/sites/nonexistent/sftp")
    assert resp.status_code == 404


def test_create_sftp_duplicate(client):
    client.post("/sites", json={"name": "sftpsite", "site_type": "static"})
    client.post("/sites/sftpsite/sftp")
    resp = client.post("/sites/sftpsite/sftp")
    assert resp.status_code == 409


def test_list_sftp_accounts(client):
    client.post("/sites", json={"name": "sftpsite", "site_type": "static"})
    client.post("/sites/sftpsite/sftp")

    resp = client.get("/sites/sftpsite/sftp")
    assert resp.status_code == 200
    accounts = resp.json()
    assert len(accounts) == 1
    assert accounts[0]["username"] == "sftp-sftpsite"


def test_delete_sftp_account(client):
    client.post("/sites", json={"name": "sftpsite", "site_type": "static"})
    client.post("/sites/sftpsite/sftp")

    resp = client.delete("/sites/sftpsite/sftp")
    assert resp.status_code == 204

    resp = client.get("/sites/sftpsite/sftp")
    assert resp.json() == []
