"""Tests for the per-site file manager UI and path safety."""

from pathlib import Path

import pytest

from app.services.file_manager import FileManagerError, HostFileBackend


def _authenticated_client(client):
    client.post("/panel/login", data={"password": "test-secret"})
    return client


def _create_site(client, name: str, site_type: str = "static"):
    resp = client.post("/sites", json={"name": name, "site_type": site_type})
    assert resp.status_code == 201, resp.text


def _set_sites_base_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("app.config.settings.sites_base_dir", str(tmp_path), raising=False)
    monkeypatch.setattr("app.api.sites.settings.sites_base_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(
        "app.services.file_manager.settings.sites_base_dir", str(tmp_path), raising=False
    )


def test_host_backend_rejects_symlink_escape(tmp_path, monkeypatch):
    _set_sites_base_dir(monkeypatch, tmp_path)

    site_root = tmp_path / "safe-site"
    site_root.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    (site_root / "evil-link").symlink_to(outside)

    backend = HostFileBackend("safe-site")
    with pytest.raises(FileManagerError, match="escapes"):
        backend.read_text_file("evil-link")


def test_host_backend_rejects_traversal(tmp_path, monkeypatch):
    _set_sites_base_dir(monkeypatch, tmp_path)
    (tmp_path / "safe-site").mkdir(parents=True)

    backend = HostFileBackend("safe-site")
    with pytest.raises(FileManagerError, match="Invalid path"):
        backend.download_file("../../etc/passwd")


def test_file_manager_page_shows_wp_root(client, tmp_path, monkeypatch):
    _set_sites_base_dir(monkeypatch, tmp_path)

    _authenticated_client(client)
    _create_site(client, "wpsite-files", site_type="wordpress")

    resp = client.get("/panel/sites/wpsite-files/files", follow_redirects=True)
    assert resp.status_code == 200
    assert "Host project files" in resp.text
    assert "Live WordPress wp-content" in resp.text


def test_file_manager_host_crud_flow(client, tmp_path, monkeypatch):
    _set_sites_base_dir(monkeypatch, tmp_path)

    _authenticated_client(client)
    _create_site(client, "filesite", site_type="static")

    base = tmp_path / "filesite"
    base.mkdir(parents=True, exist_ok=True)

    # Create folder
    resp = client.post(
        "/panel/sites/filesite/files/create-folder",
        data={"root": "host", "path": "", "folder_name": "docs"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert (base / "docs").is_dir()

    # Create text file
    resp = client.post(
        "/panel/sites/filesite/files/create-text",
        data={
            "root": "host",
            "path": "docs",
            "file_name": "hello.txt",
            "file_content": "hello world",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert (base / "docs" / "hello.txt").read_text(encoding="utf-8") == "hello world"

    # Edit text file
    resp = client.post(
        "/panel/sites/filesite/files/save-text",
        data={
            "root": "host",
            "path": "docs",
            "edit_path": "docs/hello.txt",
            "file_content": "updated",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert (base / "docs" / "hello.txt").read_text(encoding="utf-8") == "updated"

    # Move / rename file
    resp = client.post(
        "/panel/sites/filesite/files/move",
        data={
            "root": "host",
            "path": "docs",
            "src_path": "docs/hello.txt",
            "dest_path": "docs/renamed.txt",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert not (base / "docs" / "hello.txt").exists()
    assert (base / "docs" / "renamed.txt").exists()

    # Download file
    download = client.get(
        "/panel/sites/filesite/files/download",
        params={"root": "host", "target_path": "docs/renamed.txt"},
        follow_redirects=True,
    )
    assert download.status_code == 200
    assert download.content == b"updated"

    # Delete file then folder
    resp = client.post(
        "/panel/sites/filesite/files/delete",
        data={"root": "host", "path": "docs", "target_path": "docs/renamed.txt"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert not (base / "docs" / "renamed.txt").exists()

    resp = client.post(
        "/panel/sites/filesite/files/delete",
        data={"root": "host", "path": "", "target_path": "docs"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert not (base / "docs").exists()


def test_file_manager_upload_and_traversal_rejected(client, tmp_path, monkeypatch):
    _set_sites_base_dir(monkeypatch, tmp_path)

    _authenticated_client(client)
    _create_site(client, "uploadsite", site_type="static")

    base = tmp_path / "uploadsite"
    base.mkdir(parents=True, exist_ok=True)

    resp = client.post(
        "/panel/sites/uploadsite/files/upload",
        data={"root": "host", "path": ""},
        files={"upload": ("up.txt", b"abc", "text/plain")},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert (base / "up.txt").read_bytes() == b"abc"

    bad = client.post(
        "/panel/sites/uploadsite/files/delete",
        data={"root": "host", "path": "", "target_path": "../../etc/passwd"},
        follow_redirects=True,
    )
    assert bad.status_code == 200
    assert "Invalid path" in bad.text or "escapes" in bad.text
    assert (base / "up.txt").exists()


def test_file_manager_unauthenticated_redirect(client):
    resp = client.get("/panel/sites/any/files", follow_redirects=False)
    assert resp.status_code == 302
    assert "/panel/login" in resp.headers["location"]
