"""Tests for the databases API."""
import pytest


def test_create_database(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})

    resp = client.post(
        "/sites/dbsite/database",
        json={"engine": "postgres"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["db_name"] == "site_dbsite"
    assert data["db_user"] == "user_dbsite"
    assert data["engine"] == "postgres"
    assert data["db_password"] != ""
    assert "postgresql://" in data["dsn"]


def test_create_database_site_not_found(client):
    resp = client.post("/sites/nonexistent/database", json={"engine": "postgres"})
    assert resp.status_code == 404


def test_create_database_duplicate(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})
    client.post("/sites/dbsite/database", json={"engine": "postgres"})
    resp = client.post("/sites/dbsite/database", json={"engine": "postgres"})
    assert resp.status_code == 409


def test_list_databases(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})
    client.post("/sites/dbsite/database", json={"engine": "postgres"})

    resp = client.get("/sites/dbsite/database")
    assert resp.status_code == 200
    dbs = resp.json()
    assert len(dbs) == 1
    assert dbs[0]["db_name"] == "site_dbsite"


def test_delete_database(client):
    client.post("/sites", json={"name": "dbsite", "site_type": "python"})
    client.post("/sites/dbsite/database", json={"engine": "postgres"})

    dbs = client.get("/sites/dbsite/database").json()
    db_id = dbs[0]["id"]

    resp = client.delete(f"/sites/dbsite/database/{db_id}")
    assert resp.status_code == 204

    resp = client.get("/sites/dbsite/database")
    assert resp.json() == []


def test_db_name_with_hyphen(client):
    """Site names with hyphens should produce valid db identifiers."""
    client.post("/sites", json={"name": "my-site", "site_type": "node"})
    resp = client.post("/sites/my-site/database", json={"engine": "postgres"})
    assert resp.status_code == 201
    data = resp.json()
    assert "_" in data["db_name"]  # hyphen replaced with underscore
