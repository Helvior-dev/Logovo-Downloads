"""Read-only inventory and explicit deletion of known download leftovers."""

import os
import re
import shutil
from pathlib import Path


_BACKUP_NAME = re.compile(r"ytdlp_core_(?:backup|pending_previous)_[0-9a-f]{32}$")


def _backup_size(folder: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder, followlinks=False):
        for name in files:
            path = Path(root) / name
            try:
                if not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
    return total


def scan_cleanup_candidates(download_dirs, app_dir: Path) -> list[dict]:
    """Only list direct .part files and inactive yt-dlp backup directories."""
    candidates = []
    for folder in {Path(folder).resolve() for folder in download_dirs if folder}:
        try:
            for path in folder.iterdir():
                if path.suffix.lower() != ".part" or path.is_symlink() or not path.is_file():
                    continue
                info = path.stat()
                candidates.append({
                    "path": path, "kind": "partial", "size": info.st_size,
                    "mtime_ns": info.st_mtime_ns,
                })
        except OSError:
            continue

    app_dir = Path(app_dir).resolve()
    backups = []
    try:
        for path in app_dir.iterdir():
            if _BACKUP_NAME.fullmatch(path.name) and not path.is_symlink() and path.is_dir():
                try:
                    backups.append((path, path.stat().st_mtime_ns))
                except OSError:
                    continue
    except OSError:
        pass

    # Keep the newest backup for rollback. Pending and active cores are never listed.
    working_backups = [item for item in backups if item[0].name.startswith("ytdlp_core_backup_")]
    newest_backup = max(working_backups, key=lambda item: item[1])[0] if working_backups else None
    for path, modified in backups:
        if path == newest_backup:
            continue
        try:
            candidates.append({
                "path": path, "kind": "backup", "size": _backup_size(path),
                "mtime_ns": modified,
            })
        except OSError:
            continue
    return sorted(candidates, key=lambda item: item["mtime_ns"])


def delete_cleanup_candidates(selected: list[dict], download_dirs, app_dir: Path) -> tuple[int, list[str]]:
    """Reject changed, moved, or unlisted paths before deleting selected items."""
    allowed = {Path(folder).resolve() for folder in download_dirs if folder}
    eligible = {
        (item["kind"], item["path"]): item
        for item in scan_cleanup_candidates(download_dirs, app_dir)
    }
    app_dir = Path(app_dir).resolve()
    deleted = 0
    errors = []
    for item in selected:
        path = item.get("path")
        kind = item.get("kind")
        if not isinstance(path, Path) or kind not in ("partial", "backup"):
            errors.append("Invalid cleanup entry")
            continue
        try:
            current = eligible.get((kind, path))
            if (current is None or current["mtime_ns"] != item["mtime_ns"]
                    or current["size"] != item["size"] or path.is_symlink()):
                raise ValueError("Item changed or is protected")
            if kind == "partial":
                if path.parent.resolve() not in allowed or path.suffix.lower() != ".part":
                    raise ValueError("File is outside a download folder")
                path.unlink()
            else:
                if path.parent.resolve() != app_dir or not _BACKUP_NAME.fullmatch(path.name):
                    raise ValueError("Directory is not an inactive yt-dlp backup")
                shutil.rmtree(path)
            deleted += 1
        except (OSError, ValueError, KeyError) as exc:
            errors.append(f"{path}: {exc}")
    return deleted, errors
