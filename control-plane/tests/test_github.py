"""Tests for GitHub repository import — service unit tests and API integration tests."""
import os
import pytest
from pathlib import Path

os.environ["DEV_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test.db"


# ── Service unit tests ────────────────────────────────────────────────────────

class TestValidateGitHubUrl:
    def test_valid_https(self):
        from app.services.github import _validate_github_url
        url = _validate_github_url("https://github.com/owner/repo")
        assert url == "https://github.com/owner/repo.git"

    def test_valid_https_with_git(self):
        from app.services.github import _validate_github_url
        url = _validate_github_url("https://github.com/owner/repo.git")
        assert url == "https://github.com/owner/repo.git"

    def test_valid_without_scheme(self):
        from app.services.github import _validate_github_url
        url = _validate_github_url("github.com/owner/repo")
        assert url == "https://github.com/owner/repo.git"

    def test_valid_trailing_slash(self):
        from app.services.github import _validate_github_url
        url = _validate_github_url("https://github.com/owner/repo/")
        assert url == "https://github.com/owner/repo.git"

    def test_invalid_non_github(self):
        from app.services.github import _validate_github_url
        with pytest.raises(ValueError, match="Only public GitHub HTTPS URLs"):
            _validate_github_url("https://gitlab.com/owner/repo")

    def test_invalid_no_owner(self):
        from app.services.github import _validate_github_url
        with pytest.raises(ValueError, match="Invalid GitHub URL"):
            _validate_github_url("https://github.com/repo-only")

    def test_invalid_empty_parts(self):
        from app.services.github import _validate_github_url
        with pytest.raises(ValueError):
            _validate_github_url("https://github.com//repo")


class TestDetectSiteType:
    def test_detects_node(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "package.json").write_text("{}")
        assert detect_site_type(tmp_path) == SiteType.node

    def test_detects_python_requirements(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "requirements.txt").write_text("flask\n")
        assert detect_site_type(tmp_path) == SiteType.python

    def test_detects_python_pyproject(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "pyproject.toml").write_text("[tool.poetry]\n")
        assert detect_site_type(tmp_path) == SiteType.python

    def test_detects_php_composer(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "composer.json").write_text("{}")
        assert detect_site_type(tmp_path) == SiteType.php

    def test_detects_php_index(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "index.php").write_text("<?php ?>")
        assert detect_site_type(tmp_path) == SiteType.php

    def test_detects_php_glob(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "home.php").write_text("<?php ?>")
        assert detect_site_type(tmp_path) == SiteType.php

    def test_defaults_to_static(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "index.html").write_text("<html></html>")
        assert detect_site_type(tmp_path) == SiteType.static

    def test_empty_dir_is_static(self, tmp_path):
        from app.services.github import detect_site_type
        from app.models import SiteType
        assert detect_site_type(tmp_path) == SiteType.static

    def test_node_takes_priority_over_php(self, tmp_path):
        """package.json is checked before composer.json."""
        from app.services.github import detect_site_type
        from app.models import SiteType
        (tmp_path / "package.json").write_text("{}")
        (tmp_path / "composer.json").write_text("{}")
        assert detect_site_type(tmp_path) == SiteType.node


class TestCloneRepoDev:
    def test_clone_creates_dir(self, tmp_path):
        from app.services.github import clone_repo
        target = tmp_path / "site"
        clone_repo("https://github.com/owner/repo", target)
        assert target.exists()

    def test_clone_with_branch(self, tmp_path):
        from app.services.github import clone_repo
        target = tmp_path / "site"
        clone_repo("https://github.com/owner/repo", target, branch="main")
        assert target.exists()

    def test_clone_invalid_url_raises(self, tmp_path):
        from app.services.github import clone_repo
        with pytest.raises(ValueError):
            clone_repo("https://evil.com/owner/repo", tmp_path / "site")


# ── API integration tests ─────────────────────────────────────────────────────

def test_create_site_with_github_repo(client, tmp_path, monkeypatch):
    """Creating a site with github_repo should clone and auto-detect type."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "sites_base_dir", str(tmp_path))
    # Simulate a Node.js repo
    (tmp_path / "myapp").mkdir()
    (tmp_path / "myapp" / "package.json").write_text("{}")

    resp = client.post("/sites", json={
        "name": "myapp",
        "github_repo": "https://github.com/owner/myapp",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["site_type"] == "node"
    assert data["git_repo"] == "https://github.com/owner/myapp.git"
    assert data["git_branch"] is None


def test_create_site_with_github_repo_explicit_type(client, tmp_path, monkeypatch):
    """Explicit site_type should not be overridden by auto-detection."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "sites_base_dir", str(tmp_path))

    resp = client.post("/sites", json={
        "name": "myapp",
        "site_type": "static",
        "github_repo": "https://github.com/owner/myapp",
    })
    assert resp.status_code == 201
    assert resp.json()["site_type"] == "static"


def test_create_site_with_github_repo_and_branch(client, tmp_path, monkeypatch):
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "sites_base_dir", str(tmp_path))

    resp = client.post("/sites", json={
        "name": "myapp",
        "site_type": "static",
        "github_repo": "https://github.com/owner/myapp",
        "github_branch": "develop",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["git_branch"] == "develop"


def test_create_site_github_invalid_url(client):
    resp = client.post("/sites", json={
        "name": "badsite",
        "github_repo": "https://gitlab.com/owner/repo",
    })
    assert resp.status_code == 422


def test_create_site_no_type_no_repo(client):
    """site_type is required when github_repo is not provided."""
    resp = client.post("/sites", json={"name": "nosite"})
    assert resp.status_code == 422


def test_import_github_endpoint(client, tmp_path, monkeypatch):
    """POST /sites/{name}/import-github clones repo and updates git_repo."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "sites_base_dir", str(tmp_path))

    # Create an existing site
    client.post("/sites", json={"name": "mysite", "site_type": "static"})

    # Simulate a Python repo
    (tmp_path / "mysite").mkdir(exist_ok=True)
    (tmp_path / "mysite" / "requirements.txt").write_text("flask\n")

    resp = client.post("/sites/mysite/import-github", json={
        "repo_url": "https://github.com/owner/mysite",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["git_repo"] == "https://github.com/owner/mysite.git"
    assert data["site_type"] == "python"


def test_import_github_no_auto_detect(client, tmp_path, monkeypatch):
    """auto_detect_type=false should leave site_type unchanged."""
    import app.config as cfg
    monkeypatch.setattr(cfg.settings, "sites_base_dir", str(tmp_path))

    client.post("/sites", json={"name": "mysite", "site_type": "static"})

    resp = client.post("/sites/mysite/import-github", json={
        "repo_url": "https://github.com/owner/mysite",
        "auto_detect_type": False,
    })
    assert resp.status_code == 200
    assert resp.json()["site_type"] == "static"


def test_import_github_site_not_found(client):
    resp = client.post("/sites/nonexistent/import-github", json={
        "repo_url": "https://github.com/owner/repo",
    })
    assert resp.status_code == 404


def test_import_github_invalid_url(client):
    client.post("/sites", json={"name": "mysite", "site_type": "static"})
    resp = client.post("/sites/mysite/import-github", json={
        "repo_url": "https://evil.com/owner/repo",
    })
    assert resp.status_code == 422


def test_site_out_includes_git_fields(client):
    """SiteOut should include git_repo and git_branch (null when not set)."""
    client.post("/sites", json={"name": "mysite", "site_type": "static"})
    data = client.get("/sites/mysite").json()
    assert "git_repo" in data
    assert data["git_repo"] is None
    assert "git_branch" in data
    assert data["git_branch"] is None
