import sys
import subprocess
import requests
from PyQt6.QtCore import QThread, pyqtSignal

def get_installed_ytdlp_version() -> str:
    try:
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
        resp = requests.get("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest", headers=headers, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            tag = data.get("tag_name", "").lstrip("v").strip()
            if tag:
                # Compare versions
                if installed != "Unknown" and tag != installed:
                    # Check if tag is strictly newer
                    try:
                        inst_parts = [int(p) for p in installed.split(".")]
                        tag_parts = [int(p) for p in tag.split(".")]
                        if tag_parts > inst_parts:
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
    Upgrades yt-dlp using pip in the active Python environment.
    """
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return True, "Successfully upgraded yt-dlp core."
        else:
            err = proc.stderr.strip() or proc.stdout.strip()
            return False, f"Upgrade failed: {err}"
    except Exception as e:
        return False, str(e)


class CheckUpdateThread(QThread):
    result_signal = pyqtSignal(bool, str, str) # has_update, current_ver, latest_ver

    def run(self):
        has_update, current_ver, latest_ver = check_latest_ytdlp_version()
        self.result_signal.emit(has_update, current_ver, latest_ver)


class UpgradeWorker(QThread):
    finished_signal = pyqtSignal(bool, str) # success, message

    def run(self):
        success, msg = upgrade_ytdlp_core()
        self.finished_signal.emit(success, msg)
