import sys
import os
import requests
import zipfile
import io
import shutil
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal
from core.settings import get_app_data_dir

def get_ytdlp_core_dir() -> Path:
    return get_app_data_dir() / "ytdlp_core"

def init_ytdlp_core():
    """Add custom AppData yt-dlp core to sys.path if it exists."""
    core_dir = get_ytdlp_core_dir()
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
    try:
        headers = {"User-Agent": "Logovo-Downloads-Updater"}
        resp = requests.get("https://pypi.org/pypi/yt-dlp/json", headers=headers, timeout=10)
        if resp.status_code != 200:
            return False, f"Failed to fetch update info from PyPI (status {resp.status_code})"

        data = resp.json()
        target_version = data.get("info", {}).get("version", "latest")
        urls = data.get("urls", [])
        whl_url = None
        for u in urls:
            if u.get("filename", "").endswith(".whl"):
                whl_url = u.get("url")
                break
        if not whl_url and urls:
            whl_url = urls[0].get("url")

        if not whl_url:
            return False, "Could not find downloadable package for latest yt-dlp release."

        whl_resp = requests.get(whl_url, headers=headers, timeout=60)
        if whl_resp.status_code != 200:
            return False, f"Failed to download package (status {whl_resp.status_code})"

        core_dir = get_ytdlp_core_dir()
        temp_dir = get_app_data_dir() / "ytdlp_core_temp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        temp_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(io.BytesIO(whl_resp.content)) as z:
            for member in z.namelist():
                if member.startswith("yt_dlp/"):
                    z.extract(member, temp_dir)

        if not (temp_dir / "yt_dlp").exists():
            return False, "Downloaded package did not contain yt_dlp core."

        # Replace existing core
        if core_dir.exists():
            shutil.rmtree(core_dir, ignore_errors=True)
        temp_dir.rename(core_dir)

        # Inject into sys.path
        init_ytdlp_core()

        # Reload modules in memory
        import importlib
        if "yt_dlp" in sys.modules:
            try:
                import yt_dlp
                importlib.reload(yt_dlp)
                if "yt_dlp.version" in sys.modules:
                    import yt_dlp.version
                    importlib.reload(yt_dlp.version)
            except Exception:
                pass

        return True, f"Successfully upgraded yt-dlp core to v{target_version}."
    except Exception as e:
        return False, f"Upgrade error: {e}"


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
