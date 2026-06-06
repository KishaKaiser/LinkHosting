"""Per-site file manager service.

Supports browsing and editing host project files and (for WordPress sites)
live ``wp-content`` files from the running WordPress container.
"""

from __future__ import annotations

import io
import mimetypes
import posixpath
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.models import Site, SiteType

HOST_ROOT_ID = "host"
WORDPRESS_ROOT_ID = "wp-content"
_WORDPRESS_CONTENT_PATH = "/var/www/html/wp-content"
_MAX_TEXT_FILE_BYTES = 512 * 1024


class FileManagerError(ValueError):
    """Raised for safe, user-facing file manager validation errors."""


@dataclass
class FileEntry:
    name: str
    rel_path: str
    is_dir: bool
    is_symlink: bool
    size: int
    modified_at: str


@dataclass
class FileManagerRoot:
    id: str
    label: str


class FileManagerBackend:
    root_id: str
    root_label: str

    def list_dir(self, rel_dir: str) -> tuple[str, str | None, list[FileEntry]]:
        raise NotImplementedError

    def read_text_file(self, rel_path: str) -> tuple[str, str]:
        raise NotImplementedError

    def create_text_file(self, rel_dir: str, name: str, content: str) -> str:
        raise NotImplementedError

    def save_text_file(self, rel_path: str, content: str) -> str:
        raise NotImplementedError

    def create_folder(self, rel_dir: str, name: str) -> str:
        raise NotImplementedError

    def upload_file(self, rel_dir: str, filename: str, content: bytes) -> str:
        raise NotImplementedError

    def move(self, src_rel: str, dest_rel: str) -> str:
        raise NotImplementedError

    def delete(self, rel_path: str) -> str:
        raise NotImplementedError

    def download_file(self, rel_path: str) -> tuple[str, bytes, str]:
        raise NotImplementedError


class HostFileBackend(FileManagerBackend):
    root_id = HOST_ROOT_ID
    root_label = "Host project files"

    def __init__(self, site_name: str):
        self.site_name = site_name
        self.root_path = Path(settings.sites_base_dir) / site_name
        self.root_path.mkdir(parents=True, exist_ok=True)
        self._resolved_root = self.root_path.resolve(strict=True)

    def _normalize_rel(self, rel_path: str | None, *, allow_empty: bool = True) -> str:
        if rel_path is None:
            return ""
        cleaned = rel_path.strip().replace("\\", "/")
        if cleaned in {"", ".", "./"}:
            if allow_empty:
                return ""
            raise FileManagerError("Path is required.")
        cleaned = cleaned.lstrip("/")
        normalized = posixpath.normpath(cleaned)
        if normalized in {"", "."}:
            if allow_empty:
                return ""
            raise FileManagerError("Path is required.")
        if normalized.startswith("../") or normalized == ".." or "\x00" in normalized:
            raise FileManagerError("Invalid path.")
        return normalized

    def _normalize_name(self, name: str) -> str:
        candidate = name.strip()
        if not candidate:
            raise FileManagerError("Name is required.")
        if "/" in candidate or "\\" in candidate or "\x00" in candidate:
            raise FileManagerError("Invalid name.")
        if candidate in {".", ".."}:
            raise FileManagerError("Invalid name.")
        return candidate

    def _ensure_within_root(self, resolved: Path) -> None:
        try:
            resolved.relative_to(self._resolved_root)
        except ValueError as exc:
            raise FileManagerError("Path escapes the site root.") from exc

    def _resolve_existing(self, rel_path: str) -> Path:
        rel = self._normalize_rel(rel_path, allow_empty=True)
        target = self._resolved_root if not rel else self.root_path / rel
        try:
            resolved = target.resolve(strict=True)
        except FileNotFoundError as exc:
            raise FileManagerError("Path not found.") from exc
        self._ensure_within_root(resolved)
        return resolved

    def _resolve_existing_dir(self, rel_dir: str) -> tuple[str, Path]:
        rel = self._normalize_rel(rel_dir, allow_empty=True)
        resolved = self._resolve_existing(rel)
        if not resolved.is_dir():
            raise FileManagerError("Directory not found.")
        return rel, resolved

    def _resolve_create_target(self, rel_dir: str, name: str) -> tuple[str, Path]:
        parent_rel, parent_dir = self._resolve_existing_dir(rel_dir)
        safe_name = self._normalize_name(name)
        target_rel = safe_name if not parent_rel else f"{parent_rel}/{safe_name}"
        target = parent_dir / safe_name
        try:
            # Resolve parent links first to catch symlink escape.
            parent_resolved = target.parent.resolve(strict=True)
        except FileNotFoundError as exc:
            raise FileManagerError("Parent directory not found.") from exc
        self._ensure_within_root(parent_resolved)
        return target_rel, target

    def list_dir(self, rel_dir: str) -> tuple[str, str | None, list[FileEntry]]:
        rel, directory = self._resolve_existing_dir(rel_dir)
        parent = None if not rel else rel.rsplit("/", 1)[0] if "/" in rel else ""
        entries: list[FileEntry] = []

        for item in sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            item_rel = item.name if not rel else f"{rel}/{item.name}"
            try:
                resolved = item.resolve(strict=True)
                self._ensure_within_root(resolved)
            except (FileNotFoundError, FileManagerError):
                continue

            stat_obj = item.stat(follow_symlinks=False)
            entries.append(
                FileEntry(
                    name=item.name,
                    rel_path=item_rel,
                    is_dir=item.is_dir(),
                    is_symlink=item.is_symlink(),
                    size=0 if item.is_dir() else stat_obj.st_size,
                    modified_at=datetime.fromtimestamp(
                        stat_obj.st_mtime, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC"),
                )
            )

        return rel, parent, entries

    def read_text_file(self, rel_path: str) -> tuple[str, str]:
        rel = self._normalize_rel(rel_path, allow_empty=False)
        target = self._resolve_existing(rel)
        if target.is_dir():
            raise FileManagerError("Cannot edit a directory.")

        data = target.read_bytes()
        if len(data) > _MAX_TEXT_FILE_BYTES:
            raise FileManagerError("File is too large for inline editing.")
        try:
            return rel, data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileManagerError("Binary file cannot be edited inline.") from exc

    def create_text_file(self, rel_dir: str, name: str, content: str) -> str:
        target_rel, target = self._resolve_create_target(rel_dir, name)
        if target.exists():
            raise FileManagerError("File already exists.")
        target.write_text(content, encoding="utf-8")
        return target_rel

    def save_text_file(self, rel_path: str, content: str) -> str:
        rel = self._normalize_rel(rel_path, allow_empty=False)
        target = self._resolve_existing(rel)
        if target.is_dir():
            raise FileManagerError("Cannot edit a directory.")
        target.write_text(content, encoding="utf-8")
        return rel

    def create_folder(self, rel_dir: str, name: str) -> str:
        target_rel, target = self._resolve_create_target(rel_dir, name)
        target.mkdir(exist_ok=False)
        return target_rel

    def upload_file(self, rel_dir: str, filename: str, content: bytes) -> str:
        target_rel, target = self._resolve_create_target(rel_dir, Path(filename).name)
        if target.exists():
            raise FileManagerError("File already exists.")
        target.write_bytes(content)
        return target_rel

    def move(self, src_rel: str, dest_rel: str) -> str:
        src_rel_norm = self._normalize_rel(src_rel, allow_empty=False)
        src = self._resolve_existing(src_rel_norm)

        dest_rel_norm = self._normalize_rel(dest_rel, allow_empty=False)
        dest_parent_rel = dest_rel_norm.rsplit("/", 1)[0] if "/" in dest_rel_norm else ""
        dest_name = dest_rel_norm.rsplit("/", 1)[-1]
        _, dest = self._resolve_create_target(dest_parent_rel, dest_name)

        if dest.exists():
            raise FileManagerError("Destination already exists.")
        src.rename(dest)
        return dest_rel_norm

    def delete(self, rel_path: str) -> str:
        rel = self._normalize_rel(rel_path, allow_empty=False)
        target = self._resolve_existing(rel)
        if target == self._resolved_root:
            raise FileManagerError("Cannot delete the root directory.")

        if target.is_dir():
            import shutil

            shutil.rmtree(target)
        else:
            target.unlink()
        return rel

    def download_file(self, rel_path: str) -> tuple[str, bytes, str]:
        rel = self._normalize_rel(rel_path, allow_empty=False)
        target = self._resolve_existing(rel)
        if target.is_dir():
            raise FileManagerError("Directories must be downloaded as files only.")
        filename = target.name
        content = target.read_bytes()
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return filename, content, content_type


class WordPressContentBackend(FileManagerBackend):
    root_id = WORDPRESS_ROOT_ID
    root_label = "Live WordPress wp-content"

    def __init__(self, site_name: str):
        self.site_name = site_name

    def _normalize_rel(self, rel_path: str | None, *, allow_empty: bool = True) -> str:
        cleaned = (rel_path or "").strip().replace("\\", "/")
        if cleaned in {"", ".", "./"}:
            if allow_empty:
                return ""
            raise FileManagerError("Path is required.")
        cleaned = cleaned.lstrip("/")
        normalized = posixpath.normpath(cleaned)
        if normalized in {"", "."}:
            if allow_empty:
                return ""
            raise FileManagerError("Path is required.")
        if normalized.startswith("../") or normalized == ".." or "\x00" in normalized:
            raise FileManagerError("Invalid path.")
        return normalized

    def _normalize_name(self, name: str) -> str:
        candidate = name.strip()
        if not candidate:
            raise FileManagerError("Name is required.")
        if "/" in candidate or "\\" in candidate or "\x00" in candidate:
            raise FileManagerError("Invalid name.")
        if candidate in {".", ".."}:
            raise FileManagerError("Invalid name.")
        return candidate

    def _container(self):
        import docker

        from app.services.wordpress import get_wordpress_container_name

        client = docker.from_env()
        expected = get_wordpress_container_name(self.site_name)
        try:
            return client.containers.get(expected)
        except docker.errors.NotFound:
            candidates = client.containers.list(
                all=True,
                filters={
                    "label": [
                        f"linkhosting.site={self.site_name}",
                        "linkhosting.type=wordpress",
                    ]
                },
            )
            if not candidates:
                raise FileManagerError(
                    "WordPress container is not available. Deploy the site first."
                )
            return candidates[0]

    def _exec(self, cmd: list[str]) -> tuple[int, str]:
        container = self._container()
        exit_code, output = container.exec_run(cmd, demux=False, stream=False)
        text = output.decode("utf-8", errors="replace") if output else ""
        return int(exit_code), text

    def _full_path(self, rel_path: str | None) -> str:
        rel = self._normalize_rel(rel_path, allow_empty=True)
        if not rel:
            return _WORDPRESS_CONTENT_PATH
        return f"{_WORDPRESS_CONTENT_PATH}/{rel}"

    def _canonical(self, full_path: str) -> str:
        code, output = self._exec(["readlink", "-f", full_path])
        if code != 0:
            raise FileManagerError("Path not found.")
        return output.strip()

    def _ensure_within_root(self, full_path: str) -> str:
        root_real = self._canonical(_WORDPRESS_CONTENT_PATH)
        candidate_real = self._canonical(full_path)
        if candidate_real != root_real and not candidate_real.startswith(root_real + "/"):
            raise FileManagerError("Path escapes wp-content.")
        return candidate_real

    def _ensure_dir(self, rel_dir: str) -> str:
        rel = self._normalize_rel(rel_dir, allow_empty=True)
        full_path = self._full_path(rel)
        self._ensure_within_root(full_path)
        code, _ = self._exec(["test", "-d", full_path])
        if code != 0:
            raise FileManagerError("Directory not found.")
        return rel

    def _ensure_file(self, rel_path: str) -> str:
        rel = self._normalize_rel(rel_path, allow_empty=False)
        full_path = self._full_path(rel)
        self._ensure_within_root(full_path)
        code, _ = self._exec(["test", "-f", full_path])
        if code != 0:
            raise FileManagerError("File not found.")
        return rel

    def _put_archive(self, parent_full_path: str, filename: str, content: bytes) -> None:
        container = self._container()
        archive_buf = io.BytesIO()
        with tarfile.open(fileobj=archive_buf, mode="w") as tf:
            info = tarfile.TarInfo(name=filename)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = int(datetime.now(tz=timezone.utc).timestamp())
            tf.addfile(info, io.BytesIO(content))
        archive_buf.seek(0)
        if not container.put_archive(parent_full_path, archive_buf.read()):
            raise FileManagerError("Upload failed.")

    def list_dir(self, rel_dir: str) -> tuple[str, str | None, list[FileEntry]]:
        rel = self._ensure_dir(rel_dir)
        full_dir = self._full_path(rel)
        parent = None if not rel else rel.rsplit("/", 1)[0] if "/" in rel else ""

        code, output = self._exec(
            [
                "find",
                full_dir,
                "-mindepth",
                "1",
                "-maxdepth",
                "1",
                "-printf",
                "%f\t%y\t%s\t%T@\n",
            ]
        )
        if code != 0:
            raise FileManagerError("Could not list directory.")

        entries: list[FileEntry] = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            name, kind, size_text, modified = parts[0], parts[1], parts[2], parts[3]
            item_rel = name if not rel else f"{rel}/{name}"
            is_dir = kind == "d"
            is_symlink = kind == "l"
            try:
                modified_float = float(modified)
            except ValueError:
                modified_float = 0.0
            entries.append(
                FileEntry(
                    name=name,
                    rel_path=item_rel,
                    is_dir=is_dir,
                    is_symlink=is_symlink,
                    size=0 if is_dir else int(size_text or "0"),
                    modified_at=datetime.fromtimestamp(
                        modified_float, tz=timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC"),
                )
            )

        entries.sort(key=lambda item: (not item.is_dir, item.name.lower()))
        return rel, parent, entries

    def read_text_file(self, rel_path: str) -> tuple[str, str]:
        rel = self._ensure_file(rel_path)
        _, content, _ = self.download_file(rel)
        if len(content) > _MAX_TEXT_FILE_BYTES:
            raise FileManagerError("File is too large for inline editing.")
        try:
            return rel, content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FileManagerError("Binary file cannot be edited inline.") from exc

    def create_text_file(self, rel_dir: str, name: str, content: str) -> str:
        rel_dir_safe = self._ensure_dir(rel_dir)
        safe_name = self._normalize_name(name)
        target_rel = safe_name if not rel_dir_safe else f"{rel_dir_safe}/{safe_name}"
        target_full = self._full_path(target_rel)

        code, _ = self._exec(["test", "-e", target_full])
        if code == 0:
            raise FileManagerError("File already exists.")

        self._put_archive(self._full_path(rel_dir_safe), safe_name, content.encode("utf-8"))
        return target_rel

    def save_text_file(self, rel_path: str, content: str) -> str:
        rel = self._ensure_file(rel_path)
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        name = rel.rsplit("/", 1)[-1]
        self._put_archive(self._full_path(parent), name, content.encode("utf-8"))
        return rel

    def create_folder(self, rel_dir: str, name: str) -> str:
        rel_dir_safe = self._ensure_dir(rel_dir)
        safe_name = self._normalize_name(name)
        target_rel = safe_name if not rel_dir_safe else f"{rel_dir_safe}/{safe_name}"
        target_full = self._full_path(target_rel)

        code, _ = self._exec(["test", "-e", target_full])
        if code == 0:
            raise FileManagerError("Path already exists.")

        code, _ = self._exec(["mkdir", target_full])
        if code != 0:
            raise FileManagerError("Could not create folder.")
        return target_rel

    def upload_file(self, rel_dir: str, filename: str, content: bytes) -> str:
        rel_dir_safe = self._ensure_dir(rel_dir)
        safe_name = self._normalize_name(Path(filename).name)
        target_rel = safe_name if not rel_dir_safe else f"{rel_dir_safe}/{safe_name}"
        target_full = self._full_path(target_rel)

        code, _ = self._exec(["test", "-e", target_full])
        if code == 0:
            raise FileManagerError("File already exists.")

        self._put_archive(self._full_path(rel_dir_safe), safe_name, content)
        return target_rel

    def move(self, src_rel: str, dest_rel: str) -> str:
        src_rel_safe = self._normalize_rel(src_rel, allow_empty=False)
        src_full = self._full_path(src_rel_safe)
        self._ensure_within_root(src_full)
        code, _ = self._exec(["test", "-e", src_full])
        if code != 0:
            raise FileManagerError("Source path not found.")

        dest_rel_safe = self._normalize_rel(dest_rel, allow_empty=False)
        dest_full = self._full_path(dest_rel_safe)
        dest_parent = dest_rel_safe.rsplit("/", 1)[0] if "/" in dest_rel_safe else ""
        self._ensure_dir(dest_parent)

        code, _ = self._exec(["test", "-e", dest_full])
        if code == 0:
            raise FileManagerError("Destination already exists.")

        code, _ = self._exec(["mv", src_full, dest_full])
        if code != 0:
            raise FileManagerError("Could not move path.")
        return dest_rel_safe

    def delete(self, rel_path: str) -> str:
        rel = self._normalize_rel(rel_path, allow_empty=False)
        full_path = self._full_path(rel)
        self._ensure_within_root(full_path)

        code, _ = self._exec(["test", "-e", full_path])
        if code != 0:
            raise FileManagerError("Path not found.")

        code, _ = self._exec(["rm", "-rf", full_path])
        if code != 0:
            raise FileManagerError("Could not delete path.")
        return rel

    def download_file(self, rel_path: str) -> tuple[str, bytes, str]:
        rel = self._ensure_file(rel_path)
        full_path = self._full_path(rel)

        container = self._container()
        stream, _ = container.get_archive(full_path)
        tar_data = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(tar_data), mode="r:") as tf:
            members = [m for m in tf.getmembers() if m.isfile()]
            if not members:
                raise FileManagerError("Could not download file.")
            member = members[0]
            extracted = tf.extractfile(member)
            if extracted is None:
                raise FileManagerError("Could not download file.")
            content = extracted.read()

        filename = Path(rel).name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return filename, content, content_type


def available_roots_for_site(site: Site) -> list[FileManagerRoot]:
    roots = [FileManagerRoot(id=HOST_ROOT_ID, label=HostFileBackend.root_label)]
    if site.site_type == SiteType.wordpress:
        roots.append(
            FileManagerRoot(id=WORDPRESS_ROOT_ID, label=WordPressContentBackend.root_label)
        )
    return roots


def resolve_backend(site: Site, root_id: str | None) -> tuple[FileManagerRoot, FileManagerBackend]:
    roots = available_roots_for_site(site)
    roots_by_id = {root.id: root for root in roots}
    selected_id = root_id or HOST_ROOT_ID
    root = roots_by_id.get(selected_id)
    if root is None:
        raise FileManagerError("Invalid root selection.")

    if selected_id == HOST_ROOT_ID:
        return root, HostFileBackend(site.name)
    if selected_id == WORDPRESS_ROOT_ID:
        return root, WordPressContentBackend(site.name)
    raise FileManagerError("Invalid root selection.")


def breadcrumbs(rel_path: str) -> list[dict[str, str]]:
    crumbs = [{"name": "root", "path": ""}]
    if not rel_path:
        return crumbs

    current = []
    for part in rel_path.split("/"):
        current.append(part)
        crumbs.append({"name": part, "path": "/".join(current)})
    return crumbs
