"""Tests for the sites API."""
import pytest


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_site(client):
    resp = client.post("/sites", json={"name": "mysite", "site_type": "static"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "mysite"
    assert data["domain"] == "mysite.local"
    assert data["site_type"] == "static"
    assert data["status"] == "pending"


def test_create_site_custom_domain(client):
    resp = client.post(
        "/sites",
        json={"name": "mysite", "site_type": "node", "domain": "mysite.internal"},
    )
    assert resp.status_code == 201
    assert resp.json()["domain"] == "mysite.internal"


def test_create_site_duplicate_name(client):
    client.post("/sites", json={"name": "dupsite", "site_type": "static"})
    resp = client.post("/sites", json={"name": "dupsite", "site_type": "php"})
    assert resp.status_code == 409


def test_create_site_invalid_name(client):
    resp = client.post("/sites", json={"name": "UPPER", "site_type": "static"})
    assert resp.status_code == 422  # validation error


def test_list_sites_empty(client):
    resp = client.get("/sites")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_sites(client):
    client.post("/sites", json={"name": "site1", "site_type": "static"})
    client.post("/sites", json={"name": "site2", "site_type": "php"})
    resp = client.get("/sites")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_site(client):
    client.post("/sites", json={"name": "mysite", "site_type": "python"})
    resp = client.get("/sites/mysite")
    assert resp.status_code == 200
    assert resp.json()["name"] == "mysite"


def test_get_site_not_found(client):
    resp = client.get("/sites/nonexistent")
    assert resp.status_code == 404


def test_update_site(client):
    client.post("/sites", json={"name": "mysite", "site_type": "node"})
    resp = client.patch("/sites/mysite", json={"image": "node:18-alpine"})
    assert resp.status_code == 200
    assert resp.json()["image"] == "node:18-alpine"


def test_delete_site(client):
    client.post("/sites", json={"name": "mysite", "site_type": "static"})
    resp = client.delete("/sites/mysite")
    assert resp.status_code == 204
    resp = client.get("/sites/mysite")
    assert resp.status_code == 404


def test_deploy_site_dev_mode(client):
    """In dev mode, deploy should succeed without real Docker."""
    client.post("/sites", json={"name": "mysite", "site_type": "static"})
    resp = client.post("/sites/mysite/deploy")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "running"
    assert data["container_id"].startswith("dev-container-")


def test_stop_site_dev_mode(client):
    client.post("/sites", json={"name": "mysite", "site_type": "static"})
    client.post("/sites/mysite/deploy")
    resp = client.post("/sites/mysite/stop")
    assert resp.status_code == 200
    assert resp.json()["status"] == "stopped"


def test_all_site_types(client):
    for i, stype in enumerate(["static", "php", "node", "python", "proxy"]):
        resp = client.post("/sites", json={"name": f"site-{i}", "site_type": stype})
        assert resp.status_code == 201, f"Failed for type {stype}: {resp.json()}"
