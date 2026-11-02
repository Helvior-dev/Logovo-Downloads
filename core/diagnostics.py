import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import requests

from core.constants import APP_VERSION
from core.downloader import get_ffmpeg_path, get_ffprobe_path, is_valid_netscape_cookies
from core.updater import get_installed_ytdlp_version


def _check(name: str, status: str, details: str) -> dict[str, str]:
    return {"name": name, "status": status, "details": details}


def _probe_media_tool(name: str, executable: str | None) -> dict[str, str]:
    if not executable:
        return _check(name, "WARN", "Not found; media conversion or metadata processing may be limited.")

    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return _check(name, "FAIL", f"Executable returned exit code {result.returncode}.")
        output = (result.stdout or result.stderr or "").strip()
        version_line = output.splitlines()[0] if output else "Version command succeeded."
        return _check(name, "OK", version_line[:180])
    except subprocess.TimeoutExpired:
        return _check(name, "FAIL", "Version check timed out after 5 seconds.")
    except Exception as exc:
        return _check(name, "FAIL", f"Could not start executable: {exc}")


def _check_download_folder(settings) -> dict[str, str]:
    configured_path = settings.get("download_path", "") if settings else ""
    if not configured_path:
        return _check("Download folder", "FAIL", "No download folder is configured.")

    path = Path(configured_path).expanduser()
    if not path.exists():
        return _check("Download folder", "WARN", f"Folder does not exist yet: {path}")
    if not path.is_dir():
        return _check("Download folder", "FAIL", f"Configured path is not a folder: {path}")
    if not os.access(path, os.W_OK):
        return _check("Download folder", "FAIL", f"Folder is not writable: {path}")

    try:
        free_bytes = shutil.disk_usage(path).free
        free_gb = free_bytes / (1024 ** 3)
        status = "WARN" if free_bytes < 1024 ** 3 else "OK"
        details = f"Writable; {free_gb:.1f} GB free — {path}"
        if status == "WARN":
            details = f"Low free space ({free_gb:.1f} GB); {path}"
        return _check("Download folder", status, details)
    except OSError as exc:
        return _check("Download folder", "WARN", f"Writable, but free space could not be checked: {exc}")


def _check_cookie_configuration(settings) -> dict[str, str]:
    source = settings.get("cookies_source", "none") if settings else "none"
    if source == "none":
        return _check("Cookies", "INFO", "Not configured; cookies are optional.")
    if source == "browser":
        browser = settings.get("cookies_browser", "chrome") if settings else "chrome"
        return _check("Cookies", "INFO", f"Browser source configured ({browser}); availability is checked during download.")
    if source == "file":
        cookie_file = settings.get("cookies_file", "") if settings else ""
        if is_valid_netscape_cookies(cookie_file):
            return _check("Cookies", "OK", "Configured cookie file exists and has Netscape format; contents were not displayed.")
        return _check("Cookies", "WARN", "Configured cookie file is missing or is not valid Netscape format.")
    return _check("Cookies", "WARN", f"Unknown cookie source setting: {source}")


def run_self_diagnostics(settings) -> list[dict[str, str]]:
    """Run local, read-only checks. This function does not make network requests."""
    results = [
        _check("Application", "OK", f"Logovo Downloads {APP_VERSION}"),
        _check("Runtime", "OK", f"Python {platform.python_version()} ({platform.system()} {platform.machine()})"),
    ]

    ytdlp_version = get_installed_ytdlp_version()
    if ytdlp_version == "Unknown":
        results.append(_check("yt-dlp", "FAIL", "Could not import yt-dlp."))
    else:
        results.append(_check("yt-dlp", "OK", f"Version {ytdlp_version}"))

    results.extend([
        _probe_media_tool("FFmpeg", get_ffmpeg_path()),
        _probe_media_tool("FFprobe", get_ffprobe_path()),
        _check_download_folder(settings),
        _check_cookie_configuration(settings),
    ])

    settings_file = getattr(settings, "settings_file", None)
    if settings_file:
        settings_dir = Path(settings_file).parent
        if settings_dir.is_dir() and os.access(settings_dir, os.R_OK):
            results.append(_check("Application data", "OK", "Settings directory is accessible."))
        else:
            results.append(_check("Application data", "WARN", "Settings directory is not accessible."))
    else:
        results.append(_check("Application data", "INFO", "Settings directory is unavailable from this settings provider."))

    return results


def run_network_diagnostics(timeout: float = 6.0) -> list[dict[str, str]]:
    """Check network reachability for the services used by downloads and updates."""
    targets = (
        ("YouTube", "https://www.youtube.com/generate_204"),
        ("PyPI (yt-dlp updates)", "https://pypi.org/pypi/yt-dlp/json"),
        ("GitHub (app updates)", "https://api.github.com/repos/Helvior-dev/Logovo-Downloads/releases/latest"),
    )
    results = []
    headers = {"User-Agent": f"Logovo-Downloads/{APP_VERSION} diagnostics"}
    for name, url in targets:
        response = None
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True)
            status_code = response.status_code
            if 200 <= status_code < 400:
                results.append(_check(name, "OK", f"Reachable (HTTP {status_code})."))
            else:
                results.append(_check(name, "WARN", f"Server responded (HTTP {status_code}); access may be restricted."))
        except requests.RequestException as exc:
            results.append(_check(name, "FAIL", str(exc)))
        except Exception as exc:
            results.append(_check(name, "FAIL", str(exc)))
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
    return results
