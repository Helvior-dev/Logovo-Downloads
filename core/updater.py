import sys
import os
import requests
import zipfile
import io
import shutil
import hashlib
import re
import tempfile
import threading
import uuid
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from core.settings import get_app_data_dir


_upgrade_lock = threading.Lock()

def get_ytdlp_core_dir() -> Path:
    return get_app_data_dir() / "ytdlp_core"

def init_ytdlp_core(activate_pending: bool = False):
    """Activate a staged update on startup and add the installed core to sys.path."""
    core_dir = get_ytdlp_core_dir()
    pending_backup = core_dir.with_name("ytdlp_core_backup_pending")
    pending_update = core_dir.with_name("ytdlp_core_pending")
    if not core_dir.exists() and pending_backup.is_dir():
        try:
            pending_backup.rename(core_dir)
        except OSError:
            pass  # The bundled or venv copy remains available.
    if activate_pending and pending_update.is_dir():
        had_old_core = core_dir.exists()
        try:
            if had_old_core and pending_backup.exists():
                pending_backup.rename(core_dir.with_name(f"ytdlp_core_backup_{uuid.uuid4().hex}"))
            if had_old_core:
                core_dir.rename(pending_backup)
            try:
                pending_update.rename(core_dir)
            except OSError:
                if had_old_core:
                    pending_backup.rename(core_dir)
                raise
            if had_old_core:
                try:
                    pending_backup.rename(core_dir.with_name(f"ytdlp_core_backup_{uuid.uuid4().hex}"))
                except OSError:
                    pass  # Still a valid backup for the next startup.
        except OSError:
            pass  # Keep the staged update; continue with the previous core.
    if (core_dir / "yt_dlp").exists():
        core_str = str(core_dir)
        if core_str not in sys.path:
            sys.path.insert(0, core_str)

def get_installed_ytdlp_version() -> str:
    try:
        init_ytdlp_core()
        import yt_dlp.version
        return str(yt_dlp.version.__version__)
    except Exception:
        try:
            import yt_dlp
            return str(getattr(yt_dlp, "__version__", "Unknown"))
        except Exception:
            return "Unknown"

def check_latest_ytdlp_version() -> tuple[bool, str, str]:
    """
    Returns (has_update, installed_version, latest_version)
    """
    installed = get_installed_ytdlp_version()
    try:
        headers = {"User-Agent": "Logovo-Downloads-Updater"}
        resp = requests.get("https://pypi.org/pypi/yt-dlp/json", headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get("info", {}).get("version", "").strip()
            if tag:
                def _norm(v):
                    return [int(p) for p in str(v).replace('-', '.').split('.') if p.isdigit()]
                try:
                    if _norm(tag) > _norm(installed):
                        return True, installed, tag
                except Exception:
                    if tag != installed:
                        return True, installed, tag
                return False, installed, tag
    except Exception as e:
        print(f"Error checking for yt-dlp updates: {e}")
    return False, installed, installed

def upgrade_ytdlp_core() -> tuple[bool, str]:
    """
    Downloads and extracts the latest yt-dlp wheel directly into AppData/Logovo-Dushnil/Logovo-Downloads/ytdlp_core.
    Works seamlessly in compiled .exe builds and source code without requiring pip.
    """
    if not _upgrade_lock.acquire(blocking=False):
        return False, "A yt-dlp update is already running."
    staging_dir = None
    try:
        headers = {"User-Agent": "Logovo-Downloads-Updater"}
        resp = requests.get("https://pypi.org/pypi/yt-dlp/json", headers=headers, timeout=10)
        if resp.status_code != 200:
            return False, f"Failed to fetch update info from PyPI (status {resp.status_code})"

        data = resp.json()
        target_version = data.get("info", {}).get("version")
        urls = data.get("urls", [])
        wheel = next((u for u in urls if u.get("filename", "").endswith(".whl")), None)
        if not target_version or not wheel or not wheel.get("digests", {}).get("sha256"):
            return False, "PyPI did not provide a wheel with a SHA-256 checksum."

        whl_resp = requests.get(wheel["url"], headers=headers, timeout=60)
        if whl_resp.status_code != 200:
            return False, f"Failed to download package (status {whl_resp.status_code})"
        if hashlib.sha256(whl_resp.content).hexdigest() != wheel["digests"]["sha256"]:
            return False, "Downloaded yt-dlp wheel failed SHA-256 verification."

        app_dir = get_app_data_dir()
        staging_dir = Path(tempfile.mkdtemp(prefix="ytdlp_core_stage_", dir=app_dir))
        with zipfile.ZipFile(io.BytesIO(whl_resp.content)) as archive:
            for member in archive.infolist():
                name = member.filename
                parts = Path(name).parts
                if not name.startswith("yt_dlp/"):
                    continue
                if "\\" in name or ".." in parts or not parts or parts[0] != "yt_dlp":
                    return False, "Unsafe path in yt-dlp wheel."
                if member.is_dir():
                    continue
                destination = staging_dir.joinpath(*parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)

        if not (staging_dir / "yt_dlp" / "__init__.py").is_file() or not (
            staging_dir / "yt_dlp" / "version.py"
        ).is_file():
            return False, "Downloaded package did not contain a complete yt_dlp core."
        version_source = (staging_dir / "yt_dlp" / "version.py").read_text(encoding="utf-8")
        version_match = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", version_source, re.MULTILINE)
        if not version_match or version_match.group(1) != target_version:
            return False, "Downloaded yt-dlp wheel version does not match PyPI metadata."

        pending_update = get_ytdlp_core_dir().with_name("ytdlp_core_pending")
        old_pending = None
        if pending_update.exists():
            old_pending = pending_update.with_name(f"ytdlp_core_pending_previous_{uuid.uuid4().hex}")
            pending_update.rename(old_pending)
        try:
            staging_dir.rename(pending_update)
        except OSError:
            if old_pending is not None:
                old_pending.rename(pending_update)
            raise

        return True, f"yt-dlp v{target_version} ready. Restart the app to activate it."
    except Exception as e:
        return False, f"Upgrade error: {e}"
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        _upgrade_lock.release()


class CheckUpdateThread(QThread):
    result_signal = pyqtSignal(bool, str, str)  # has_update, current_ver, latest_ver

    def run(self):
        has_update, current_ver, latest_ver = check_latest_ytdlp_version()
        self.result_signal.emit(has_update, current_ver, latest_ver)


class UpgradeWorker(QThread):
    finished_signal = pyqtSignal(bool, str)  # success, message

    def run(self):
        success, msg = upgrade_ytdlp_core()
        self.finished_signal.emit(success, msg)
