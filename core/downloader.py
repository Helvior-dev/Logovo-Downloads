import base64
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from PIL import Image
import yt_dlp
from core.settings import SettingsManager
from core.utils import clean_filename_for_all_devices

try:
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK, TDRC, TYER, USLT
    from mutagen.easyid3 import EasyID3
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
except ImportError:
    FLAC, Picture = None, None
    ID3, APIC, TALB, TIT2, TPE1, TRCK, TDRC, TYER, USLT = None, None, None, None, None, None, None, None, None
    EasyID3 = None
    MP4, MP4Cover = None, None
    OggOpus = None

ERROR_REASONS: list[tuple[str, str]] = [
    ("rate-limited", "YouTube Rate Limit — try again later"),
    ("try again later", "YouTube Rate Limit — try again later"),
    ("HTTP Error 429", "YouTube Rate Limit (429) — try again later"),
    ("Sign in to confirm your age", "Age-restricted — cookies required"),
    ("does not look like a netscape format", "Invalid cookies format (Netscape required)"),
    ("failed to load cookies", "Failed to load cookies file"),
    ("Video unavailable", "Video unavailable"),
    ("copyright claim", "Blocked by copyright claim"),
    ("This video is not available", "Video not available in your region"),
    ("Private video", "Private video"),
    ("This video has been removed", "Video removed by uploader"),
    ("confirm you're not a bot", "Bot check — try adding cookies"),
    ("HTTP Error 403", "Server busy / 403 Forbidden"),
    ("Forbidden", "Server busy / 403 Forbidden"),
]


def friendly_error(raw: str) -> str:
    """Return a short human-readable reason from a raw yt-dlp error string."""
    if not raw:
        return "Unknown error"
    for needle, label in ERROR_REASONS:
        if needle.lower() in raw.lower():
            return label
    clean = re.sub(r"\x1b\[[0-9;]*m", "", raw).strip()
    clean = re.sub(r"^ERROR:\s*", "", clean).strip()
    first = re.split(r"[\n.]", clean)[0].strip()
    return first[:100] if first else raw[:100]


def is_rate_limited(raw: str) -> bool:
    """Return True if the error indicates YouTube is rate-limiting the session."""
    if not raw:
        return False
    low = raw.lower()
    return any(k in low for k in (
        "rate-limited",
        "rate limit",
        "try again later",
        "too many requests",
        "http error 429",
    ))


def is_valid_netscape_cookies(cookie_file: str) -> bool:
    """Validate that cookie_file exists, is non-empty, and conforms to Netscape cookie format."""
    if not cookie_file or not os.path.exists(cookie_file):
        return False
    try:
        if os.path.getsize(cookie_file) < 10:
            return False
        with open(cookie_file, 'r', encoding='utf-8', errors='ignore') as f:
            for _ in range(25):
                line = f.readline()
                if not line:
                    break
                line_s = line.strip()
                if "netscape" in line_s.lower() or "http cookie file" in line_s.lower():
                    return True
                if line_s and not line_s.startswith("#") and len(line_s.split('\t')) >= 6:
                    return True
            return False
    except Exception:
        return False


def is_platform_unavailable(raw: str) -> bool:
    """Return True if video is deleted/unavailable on YouTube/platform (not a rate-limit or cookie error)."""
    if not raw:
        return False
    low = raw.lower()
    if is_rate_limited(raw) or "does not look like a netscape format" in low or "failed to load cookies" in low:
        return False
    return any(k in low for k in (
        "video unavailable",
        "this video is not available",
        "has been removed",
        "copyright removal",
        "copyright claim",
        "private video",
        "account has been terminated",
        "no longer available",
        "this video is unavailable",
    ))


def clean_media_url(url: str, keep_list: bool = False) -> str:
    """Clean tracking params and normalize music.youtube.com to youtube.com to prevent 403 Forbidden and album licensing restrictions."""
    if not url:
        return url
    url = url.strip()
    if "youtube.com" in url or "youtu.be" in url:
        url = url.replace("music.youtube.com", "www.youtube.com")
        try:
            parsed = urllib.parse.urlparse(url)
            params = urllib.parse.parse_qs(parsed.query)
            clean_params = {}
            if "v" in params:
                clean_params["v"] = params["v"]
                if keep_list and "list" in params:
                    clean_params["list"] = params["list"]
            elif "list" in params:
                clean_params["list"] = params["list"]
            if "t" in params:
                clean_params["t"] = params["t"]
            if clean_params:
                new_query = urllib.parse.urlencode(clean_params, doseq=True)
                return urllib.parse.urlunparse(parsed._replace(query=new_query))
        except Exception:
            pass
    return url


import shutil

def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def get_ffmpeg_dir() -> Optional[Path]:
    """Find the directory containing bundled or system ffmpeg/ffprobe binaries."""
    candidates = []
    # 1. PyInstaller _MEIPASS temp directory
    if hasattr(sys, "_MEIPASS"):
        meipass = Path(sys._MEIPASS)
        candidates.extend([meipass / "bin", meipass])
    
    # 2. Application executable or project root directory
    base_dir = get_base_dir()
    candidates.extend([base_dir / "bin", base_dir])

    for c in candidates:
        if (c / "ffmpeg.exe").exists():
            return c
    return None


def get_ffmpeg_path() -> Optional[str]:
    f_dir = get_ffmpeg_dir()
    if f_dir and (f_dir / "ffmpeg.exe").exists():
        return str(f_dir / "ffmpeg.exe")
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return which_ffmpeg
    return None


def get_ffprobe_path() -> Optional[str]:
    f_dir = get_ffmpeg_dir()
    if f_dir and (f_dir / "ffprobe.exe").exists():
        return str(f_dir / "ffprobe.exe")
    which_ffprobe = shutil.which("ffprobe")
    if which_ffprobe:
        return which_ffprobe
    return None


# Prepend bundled ffmpeg/bin directory to PATH if available
_ffmpeg_dir = get_ffmpeg_dir()
if _ffmpeg_dir:
    _str_dir = str(_ffmpeg_dir)
    _current_path = os.environ.get("PATH", "")
    if _str_dir not in _current_path:
        os.environ["PATH"] = f"{_str_dir}{os.pathsep}{_current_path}"

FFMPEG_PATH = get_ffmpeg_path()
FFPROBE_PATH = get_ffprobe_path()


# ─── Windows File Visibility & Folder Icon Helpers ────────────────────────────

def hide_file(path: Path | str) -> None:
    """Set hidden attribute on Windows so service files don't clutter Explorer view."""
    if sys.platform == "win32":
        try:
            import ctypes
            p = str(path)
            if os.path.exists(p):
                ctypes.windll.kernel32.SetFileAttributesW(p, 0x02)  # FILE_ATTRIBUTE_HIDDEN
        except Exception:
            pass


def unhide_file(path: Path | str) -> None:
    """Remove hidden attribute on Windows before writing/updating."""
    if sys.platform == "win32":
        try:
            import ctypes
            p = str(path)
            if os.path.exists(p):
                ctypes.windll.kernel32.SetFileAttributesW(p, 0x80)  # FILE_ATTRIBUTE_NORMAL
        except Exception:
            pass


def crop_to_square(img: Image.Image) -> Image.Image:
    """Center-crop an image to 1:1 aspect ratio and resize to 1000x1000 with LANCZOS."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    resample = getattr(Image, "Resampling", Image).LANCZOS
    return img.crop((left, top, left + side, top + side)).resize((1000, 1000), resample)


def is_root_or_general_folder(folder_path: Path | str) -> bool:
    """Return True if path is a drive root, user standard directories, or the global download directory."""
    if not folder_path:
        return True
    try:
        p = Path(folder_path).resolve()
        # Protect drive roots (e.g. C:\, D:\)
        if len(p.parts) <= 1 or p.parent == p:
            return True
        # Protect user home and top-level user libraries
        home = Path.home().resolve()
        protected = {
            home,
            (home / "Downloads").resolve(),
            (home / "Desktop").resolve(),
            (home / "Music").resolve(),
            (home / "Videos").resolve(),
            (home / "Documents").resolve(),
        }
        if p in protected:
            return True
        # Protect global download_path configured in settings
        try:
            from core.settings import SettingsManager
            mgr = SettingsManager()
            global_dp = Path(mgr.get("download_path", str(home / "Downloads"))).resolve()
            if p == global_dp:
                return True
        except Exception:
            pass
    except Exception:
        pass
    return False


def set_folder_icon(folder_path: Path | str, image_source: Any) -> bool:
    """
    Sets the Windows folder icon from an image URL, PIL Image, or local image file.
    Creates desktop.ini and folder_icon.ico with system & hidden attributes.
    """
    if sys.platform != "win32":
        return False
    if not image_source or is_root_or_general_folder(folder_path):
        return False

    try:
        folder = Path(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        ico_path = folder / "folder_icon.ico"
        ini_path = folder / "desktop.ini"

        img = None
        if isinstance(image_source, Image.Image):
            img = image_source
        elif isinstance(image_source, (str, Path)):
            src_str = str(image_source)
            if src_str.startswith("http://") or src_str.startswith("https://"):
                import requests
                resp = requests.get(src_str, timeout=6)
                if resp.status_code == 200:
                    img = Image.open(io.BytesIO(resp.content))
            elif Path(src_str).exists():
                p = Path(src_str)
                if p.suffix.lower() == ".mp3" and ID3:
                    try:
                        tags = ID3(p)
                        for k in tags:
                            if k.startswith("APIC"):
                                img = Image.open(io.BytesIO(tags[k].data))
                                break
                    except Exception:
                        pass
                if not img:
                    try:
                        img = Image.open(src_str)
                    except Exception:
                        pass

        if not img:
            return False

        # Center crop to square
        sq_img = crop_to_square(img)

        # Save multi-resolution ICO
        unhide_file(ico_path)
        sq_img.save(
            str(ico_path),
            format="ICO",
            sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
        )

        # Write desktop.ini
        unhide_file(ini_path)
        ini_content = (
            "[.ShellClassInfo]\n"
            "IconResource=folder_icon.ico,0\n"
            "[ViewState]\n"
            "Mode=\n"
            "Vid=\n"
            "FolderType=Generic\n"
        )
        ini_path.write_text(ini_content, encoding="utf-8")

        # Set attributes: 0x06 (HIDDEN | SYSTEM) on files, 0x01 (READONLY) on folder for Explorer
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(ico_path), 0x06)
        ctypes.windll.kernel32.SetFileAttributesW(str(ini_path), 0x06)
        ctypes.windll.kernel32.SetFileAttributesW(str(folder), 0x01)

        # Notify Windows Shell of folder icon update
        try:
            ctypes.windll.shell32.SHChangeNotify(0x00002000, 0x0005, str(folder), None)
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"Error setting folder icon: {e}")
        return False


def save_playlist_cover_image(folder_path: Path | str, image_source: Any) -> Optional[Path]:
    """Save playlist cover as 1:1 square-cropped cover.jpg / cover.png in 1000x1000 quality."""
    if not image_source or is_root_or_general_folder(folder_path):
        return None
    try:
        folder = Path(folder_path)
        folder.mkdir(parents=True, exist_ok=True)
        img = None
        if isinstance(image_source, Image.Image):
            img = image_source
        elif isinstance(image_source, (str, Path)):
            src_str = str(image_source)
            if src_str.startswith("http://") or src_str.startswith("https://"):
                import requests
                resp = requests.get(src_str, timeout=6)
                if resp.status_code == 200:
                    img = Image.open(io.BytesIO(resp.content))
            elif Path(src_str).exists():
                p = Path(src_str)
                if p.suffix.lower() == ".mp3" and ID3:
                    try:
                        tags = ID3(p)
                        for k in tags:
                            if k.startswith("APIC"):
                                img = Image.open(io.BytesIO(tags[k].data))
                                break
                    except Exception:
                        pass
                if not img:
                    try:
                        img = Image.open(src_str)
                    except Exception:
                        pass

        if not img:
            return None

        # Center crop to 1000x1000 square
        sq_img = crop_to_square(img)

        # Save single lossless PNG cover (highest quality, no JPEG artifacts)
        png_cover = folder / "cover.png"
        sq_img.save(str(png_cover), format="PNG")

        # Clean up redundant cover.jpg if present
        jpg_cover = folder / "cover.jpg"
        if jpg_cover.exists():
            try:
                jpg_cover.unlink(missing_ok=True)
            except Exception:
                pass

        return png_cover
    except Exception as e:
        print(f"Error saving playlist cover image: {e}")
        return None


def apply_playlist_cover_settings(folder_path: Path | str, image_source: Any, mode: str = "both") -> None:
    """Apply playlist cover according to user settings mode: 'both', 'icon', 'file', 'none'."""
    if not image_source or mode == "none" or is_root_or_general_folder(folder_path):
        return
    if mode in ("file", "both"):
        save_playlist_cover_image(folder_path, image_source)
    if mode in ("icon", "both"):
        set_folder_icon(folder_path, image_source)


# ─── Playlist Persistence Helpers ─────────────────────────────────────────────

def read_stem_vid_map(output_dir: Path | str) -> dict[str, str]:
    """Read stem -> video_id mapping from stem_vid_map.json, keeping only existing files."""
    out = Path(output_dir)
    map_file = out / "stem_vid_map.json"
    if map_file.exists():
        try:
            raw = json.loads(map_file.read_text(encoding="utf-8"))
            valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".webm"}
            cleaned = {}
            for stem, vid in raw.items():
                for ext in valid_exts:
                    p = out / f"{stem}{ext}"
                    try:
                        if p.exists() and p.stat().st_size > 100 * 1024:
                            cleaned[stem] = vid
                            break
                    except Exception:
                        pass
            return cleaned
        except Exception:
            pass
    return {}


def update_stem_vid_map(output_dir: Path | str, stem: str, vid: str) -> None:
    """Record a track's stem (filename without extension) and video ID in stem_vid_map.json."""
    if not stem or not vid:
        return
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    map_file = out / "stem_vid_map.json"
    unhide_file(map_file)
    data = read_stem_vid_map(out)
    data[stem] = vid
    try:
        map_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        hide_file(map_file)
    except Exception:
        pass


def read_archive_ids(output_dir: Path | str) -> set[str]:
    """Read video IDs recorded in downloaded_archive.txt."""
    archive_file = Path(output_dir) / "downloaded_archive.txt"
    ids: set[str] = set()
    if not archive_file.exists():
        return ids
    try:
        for line in archive_file.read_text(encoding="utf-8").splitlines():
            parts = line.strip().split()
            if len(parts) >= 2:
                ids.add(parts[1])
    except Exception:
        pass
    return ids


def write_archive_ids(output_dir: Path | str, ids: set[str]) -> None:
    """Write/append video IDs into downloaded_archive.txt."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    archive_file = out / "downloaded_archive.txt"
    unhide_file(archive_file)
    try:
        with open(archive_file, "a", encoding="utf-8") as f:
            for vid in ids:
                f.write(f"youtube {vid}\n")
        hide_file(archive_file)
    except Exception:
        pass


def clean_song_title(title: str, author: str = "") -> str:
    """Strip only pure metadata video noise (preserving remixes, extended, feats)."""
    t = (title or "").strip()
    # Remove invisible zero-width characters
    t = re.sub(r'[\u200b\u200c\u200d\ufeff\u00a0]+', '', t)
    noise_patterns = [
        r'[\(\[\{]\s*(?:official\s*(?:music\s*)?video|music\s*video|official\s*audio|official|audio|hd|4k|4k\s*upgrade|remaster(?:ed)?(?:\s*\d+)?|video|clip|lyrics?|visualizer|bonus\s*edition)\s*[\)\]\}]',
        r'\[Official\s+HD\s+Music\s+Video\]',
        r'\(from\s+the\s+series\s+Arcane\s+League\s+of\s+Legends\)',
        r'[\(\[\{]\s*from\s+[^)\]\}]+[\)\]\}]',
    ]
    for pat in noise_patterns:
        t = re.sub(pat, '', t, flags=re.IGNORECASE)
    # Strip repeated artists from title e.g. "Blank Banshee - Blank Banshee - B: / Start Up"
    if ' - ' in t:
        parts = [p.strip() for p in t.split(' - ') if p.strip()]
        a_clean = re.sub(r'[\W_]+', '', (author or '').lower())
        new_parts = []
        for p in parts:
            p_clean = re.sub(r'[\W_]+', '', p.lower())
            if a_clean and (p_clean == a_clean or a_clean in p_clean):
                continue
            new_parts.append(p)
        if new_parts:
            t = ' - '.join(new_parts)
    return re.sub(r'[\W_]+', '', t.lower()).strip()


def clean_artist_name(author: str) -> str:
    a = (author or "").strip()
    a = re.sub(r'[\u200b\u200c\u200d\ufeff\u00a0]+', '', a)
    for p in ('the ', 'we are ', 'weare', 'i am ', 'iam ', 'official ', 'dj '):
        if a.lower().startswith(p):
            a = a[len(p):].strip()
    for suffix in ('- Topic', 'Topic', 'VEVO', 'Official', 'Uptown', 'Music', 'TV', 'Records', 'Channel', 'HD', 'HQ'):
        if a.lower().endswith(suffix.lower()):
            a = a[:-len(suffix)].strip()
    return re.sub(r'[\W_]+', '', a.lower()).strip()


def translit_ru_to_en(text: str) -> str:
    mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z',
        'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'u', 'я': 'a'
    }
    res = ''
    for ch in (text or '').lower():
        res += mapping.get(ch, ch)
    res = res.replace('kh', 'h').replace('ju', 'u').replace('ja', 'a').replace('ya', 'a').replace('yu', 'u')
    return re.sub(r'[\W_]+', '', res)


def _author_and_title_match(stem: str, title: Optional[str], author: Optional[str]) -> bool:
    """Strictly matches track title AND artist against file stem, supporting transliteration, multi-part filenames, and CamelCase."""
    if not title or len(title.strip()) < 2:
        return False

    def _split_camel_case(s: str) -> str:
        return re.sub(r'([a-z])([A-Z])', r'\1 \2', s)

    def _extract_words(text: str) -> set[str]:
        clean = _split_camel_case(text or "")
        clean = re.sub(r'[\(\[\{]\s*(?:from|official|video|audio|lyrics?|visualizer|read\s+desc|out\s+on\s+spotify)[^\)\]\}]*[\)\]\}]', '', clean, flags=re.IGNORECASE)
        clean = re.sub(r'\b(?:Russia|VEVO|Topic|Official|Channel|Records|Music)\b', '', clean, flags=re.IGNORECASE)
        words = set(re.findall(r'[a-zA-Z0-9\u0400-\u04FF]+', clean.lower()))
        res = set()
        for w in words:
            if len(w) >= 2 and w not in ('from', 'the', 'series', 'official', 'video', 'audio', 'lyrics', 'visualizer', 'version', 'feat', 'ft', 'with', 'and', 'music', 'topic', 'release', 'channel', 'vevo', 'records'):
                res.add(w)
                tr = translit_ru_to_en(w)
                if tr and tr != w:
                    res.add(tr)
                    res.add(tr.replace('iya', 'ia').replace('ya', 'ia').replace('y', 'i'))
                if w.startswith('dj') and len(w) >= 5:
                    res.add(w[2:])
        return res

    # 1. Exact cleaned check
    clean_t = clean_song_title(title, author or "")
    clean_a = clean_artist_name(author or "")
    clean_s = clean_song_title(stem, author or "")
    if clean_t and clean_t in clean_s and (not clean_a or clean_a in clean_s or any(u in clean_s for u in ('topic', 'release', 'variousartists', 'soundtrack'))):
        return True

    # 2. Word-set intersection
    words_t = _extract_words(title)
    words_a = _extract_words(author or "")
    words_s = _extract_words(stem)

    if not words_t:
        return False

    title_matches = all(wt in words_s or any(wt in ws or ws in wt for ws in words_s) for wt in words_t)
    if not title_matches:
        stem_tr = translit_ru_to_en(stem)
        words_s_tr = _extract_words(stem_tr)
        title_matches = all(wt in words_s_tr or any(wt in ws or ws in wt for ws in words_s_tr) for wt in words_t)

    if not title_matches:
        return False

    # Sequel check: ensure Roman numerals or part numbers aren't mismatched
    stem_lower_words = set(stem.lower().split())
    title_lower_words = set(title.lower().split())
    for part in ('ii', 'iii', 'iv', '2', '3', '4', 'pt 2', 'part 2'):
        if part in stem_lower_words and part not in title_lower_words:
            return False

    if not words_a:
        return True

    artist_matches = any(wa in words_s or any(wa in ws or ws in wa for ws in words_s) for wa in words_a)
    if not artist_matches:
        stem_tr = translit_ru_to_en(stem)
        words_s_tr = _extract_words(stem_tr)
        artist_matches = any(wa in words_s_tr or any(wa in ws or ws in wa for ws in words_s_tr) for wa in words_a)
    if not artist_matches:
        stem_lower = stem.lower()
        if any(lbl in stem_lower for lbl in ('riot games music', 'soundtrack', 'original soundtrack', 'ost', 'release - topic', 'vevo')):
            artist_matches = True

    return artist_matches


def match_search_candidate(cand_title: str, cand_uploader: str, orig_title: str, orig_artist: str) -> bool:
    """Verify that search candidate actually matches original song title and artist."""
    if not orig_title:
        return False

    t_clean = re.sub(r'[\(\[\{]\s*from\s+[^)\]\}]+[\)\]\}]', '', orig_title, flags=re.IGNORECASE)
    t_clean = re.sub(r'[\(\[\{]\s*(?:official\s*(?:music\s*)?video|music\s*video|official\s*audio|official|video|audio|lyrics?|visualizer|remaster(?:ed)?)\s*[\)\]\}]', '', t_clean, flags=re.IGNORECASE)

    words_t = [w for w in re.findall(r'[a-zA-Z0-9\u0400-\u04FF]+', t_clean.lower()) if len(w) >= 2 and w not in ('from', 'the', 'series', 'official', 'video', 'audio', 'lyrics', 'visualizer', 'version', 'feat', 'ft', 'with', 'and')]
    words_a = [w for w in re.findall(r'[a-zA-Z0-9\u0400-\u04FF]+', orig_artist.lower()) if len(w) >= 2 and w not in ('the', 'official', 'music', 'topic', 'channel', 'read', 'desc')]

    cand_full = f"{cand_title} {cand_uploader}".lower()

    if not words_t:
        return False
    title_match = all(w in cand_full for w in words_t)

    # Sequel check: ensure Roman numerals or part numbers aren't mismatched
    for part in ('ii', 'iii', 'iv', '2', '3', '4', 'pt 2', 'part 2'):
        if part in cand_full.split() and part not in orig_title.lower().split():
            return False

    if words_a:
        artist_match = any(w in cand_full for w in words_a) or any(u in cand_uploader.lower() for u in ('topic', 'release', 'soundtrack', 'vevo', 'records', 'official', 'riot games music'))
    else:
        artist_match = True

    return title_match and artist_match


def check_and_clean_archive_if_file_missing(output_dir: Path | str, vid: str, title: str = "", author: str = "") -> None:
    """If a track is listed in downloaded_archive.txt but not found on disk, remove it from archive so yt-dlp re-downloads it."""
    if not vid:
        return
    out = Path(output_dir)
    archive_file = out / "downloaded_archive.txt"
    if not archive_file.exists():
        return

    valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".webm"}
    stem_map = read_stem_vid_map(out)
    file_exists = False

    # Check stem_map
    for stem, mapped_vid in stem_map.items():
        if mapped_vid == vid:
            for ext in valid_exts:
                p = out / f"{stem}{ext}"
                try:
                    if p.exists() and p.stat().st_size >= 500 * 1024:
                        file_exists = True
                        break
                except Exception:
                    pass
            if file_exists:
                break

    # Check via strict Author & Title matching in filenames
    if not file_exists and title and len(title.strip()) >= 2:
        try:
            for f in out.iterdir():
                if f.is_file() and f.suffix.lower() in valid_exts and f.stat().st_size >= 500 * 1024:
                    if _author_and_title_match(f.stem, title, author):
                        file_exists = True
                        break
        except Exception:
            pass

    # If file does not exist on disk, remove vid from downloaded_archive.txt
    if not file_exists:
        try:
            unhide_file(archive_file)
            lines = archive_file.read_text(encoding="utf-8").splitlines()
            new_lines = [ln for ln in lines if vid not in ln]
            if len(new_lines) != len(lines):
                archive_file.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
            hide_file(archive_file)
        except Exception:
            pass


def is_file_already_downloaded(output_dir: Path | str, vid: str, title: Optional[str] = None, author: Optional[str] = None, is_audio: bool = True) -> bool:
    """Instant local disk check: returns True in ~0.0001s if valid media file (>=500KB) already exists on disk."""
    out = Path(output_dir)
    if not out.exists():
        return False

    if is_audio:
        valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac"}
    else:
        valid_exts = {".mp4", ".mkv", ".webm", ".avi", ".mov"}

    stem_map = read_stem_vid_map(out)

    # 1. Check via stem_map
    for stem, mapped_vid in stem_map.items():
        if mapped_vid == vid:
            for ext in valid_exts:
                p = out / f"{stem}{ext}"
                try:
                    if p.exists() and p.stat().st_size >= 500 * 1024:
                        return True
                except Exception:
                    pass

    # 2. Check via strict Author & Title matching in filenames
    if title and len(title.strip()) >= 2:
        try:
            for f in out.iterdir():
                if f.is_file() and f.suffix.lower() in valid_exts and f.stat().st_size >= 500 * 1024:
                    if _author_and_title_match(f.stem, title, author):
                        update_stem_vid_map(out, f.stem, vid)
                        return True

            # 3. Check via ID3 / audio tags if not matched by filename (e.g. truncated filename)
            if is_audio and EasyID3:
                for f in out.iterdir():
                    if f.is_file() and f.suffix.lower() in (".mp3", ".flac", ".m4a") and f.stat().st_size >= 500 * 1024:
                        try:
                            tag_t, tag_a = "", ""
                            if f.suffix.lower() == ".mp3":
                                e = EasyID3(f)
                                tag_t = (e.get('title') or [''])[0]
                                tag_a = (e.get('artist') or [''])[0]
                            if tag_t and _author_and_title_match(f"{tag_a} - {tag_t}", title, author):
                                update_stem_vid_map(out, f.stem, vid)
                                return True
                        except Exception:
                            pass
        except Exception:
            pass

    return False


def cleanup_orphan_files(output_dir: Path | str, is_audio_playlist: bool = True) -> int:
    """Clean up orphan .webp, .png, .jpg thumbnails, .part, .ytdl, and corrupted media stubs (<500KB).
    Only converts orphan raw containers if is_audio_playlist is explicitly True.
    Preserves playlist covers (cover.png, cover.jpg, cover.webp, folder.ico, desktop.ini) and service logs.
    """
    out = Path(output_dir)
    if not out.exists():
        return 0

    protected_basenames = {
        "cover.png", "cover.jpg", "cover.jpeg", "cover.webp", "cover.ico",
        "folder.ico", "desktop.ini",
        "stem_vid_map.json", "playlist_order.txt", "downloaded_archive.txt",
        "failed_downloads.txt", "app_logs.txt"
    }

    audio_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav"}
    cleaned_count = 0
    try:
        all_files = list(out.iterdir())
        audio_stems = {f.stem.lower() for f in all_files if f.is_file() and f.suffix.lower() in audio_exts}

        for f in all_files:
            if not f.is_file():
                continue
            name_lower = f.name.lower()
            if name_lower in protected_basenames:
                continue

            # 1. Temporary download fragments
            if f.suffix.lower() in (".part", ".ytdl", ".tmp", ".temp"):
                try:
                    f.unlink(missing_ok=True)
                    cleaned_count += 1
                except Exception:
                    pass
            # 2. Orphan thumbnails left after failed or interrupted downloads
            elif f.suffix.lower() in (".webp", ".png", ".jpg", ".jpeg"):
                try:
                    f.unlink(missing_ok=True)
                    cleaned_count += 1
                except Exception:
                    pass
            # 3. Corrupted / truncated media stubs (<500 KB) that cannot be played
            elif f.suffix.lower() in audio_exts or f.suffix.lower() in (".mp4", ".mkv", ".webm"):
                try:
                    if f.stat().st_size < 500 * 1024:
                        f.unlink(missing_ok=True)
                        cleaned_count += 1
                except Exception:
                    pass
            # 4. Leftover .mp4 / .webm video containers ONLY in explicit audio playlists
            elif is_audio_playlist and f.suffix.lower() in (".mp4", ".webm", ".mkv"):
                # If an audio version already exists, delete the duplicate video container
                if f.stem.lower() in audio_stems:
                    try:
                        f.unlink(missing_ok=True)
                        cleaned_count += 1
                    except Exception:
                        pass
                else:
                    # If only the .mp4 remains in an audio playlist, convert to .mp3 and delete .mp4
                    try:
                        ensure_audio_format(f, ".mp3")
                        cleaned_count += 1
                    except Exception:
                        pass
    except Exception:
        pass
    return cleaned_count


def write_playlist_order(output_dir: Path | str, file_names: list[str]) -> None:
    """Write exact list of filenames to playlist_order.txt in order."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    order_file = out / "playlist_order.txt"
    unhide_file(order_file)
    try:
        order_file.write_text("\n".join(file_names) + "\n", encoding="utf-8")
        hide_file(order_file)
    except Exception:
        pass


def append_playlist_order(output_dir: Path | str, file_name: str) -> None:
    """Append a filename to playlist_order.txt if not already listed."""
    if not file_name:
        return
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    order_file = out / "playlist_order.txt"
    unhide_file(order_file)
    existing = []
    if order_file.exists():
        try:
            existing = [ln.strip() for ln in order_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except Exception:
            existing = []
    if file_name not in existing:
        existing.append(file_name)
        try:
            order_file.write_text("\n".join(existing) + "\n", encoding="utf-8")
            hide_file(order_file)
        except Exception:
            pass


def restore_dates_from_order(output_dir: Path | str) -> int:
    """Restore file modification timestamps based on playlist_order.txt order."""
    out = Path(output_dir)
    order_file = out / "playlist_order.txt"
    if not order_file.exists():
        return 0
    try:
        names = [ln.strip() for ln in order_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception:
        return 0
    if not names:
        return 0
    base_time = time.time()
    restored = 0
    for i, name in enumerate(names):
        p = out / name
        if p.exists():
            try:
                os.utime(p, (base_time + i, base_time + i))
                restored += 1
            except Exception:
                pass
    return restored


def reindex_existing_playlist_files(output_dir: Path | str, entries: list[dict], settings: Optional[Any] = None) -> None:
    """
    Re-index and update ID3/FLAC/M4A/Opus tags & timestamps for all existing files in a playlist folder
    so track numbers (1..N) and total tracks always match the current online playlist structure without gaps.
    """
    out = Path(output_dir)
    if not out.exists() or not entries:
        return

    count = len(entries)
    stem_map = read_stem_vid_map(out)
    valid_exts = (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".webm", ".aac", ".alac")

    embed_all = True if settings is None else settings.get('embed_all_metadata', True)
    tag_opts = {} if settings is None else settings.get('audio_metadata_tags', {})

    track_number_enabled = embed_all or tag_opts.get('track_number', True)
    album_enabled = embed_all or tag_opts.get('album', True)
    artist_enabled = embed_all or tag_opts.get('artist', True)
    title_enabled = embed_all or tag_opts.get('title', True)
    year_enabled = embed_all or tag_opts.get('year', True)

    # Map vid -> list of existing Path objects
    vid_to_paths: dict[str, list[Path]] = {}
    for stem, vid in stem_map.items():
        for ext in valid_exts:
            p = out / f"{stem}{ext}"
            if p.exists() and p.is_file():
                vid_to_paths.setdefault(vid, []).append(p)

    # Scan all local audio files in out
    all_local_files = [f for f in out.iterdir() if f.is_file() and f.suffix.lower() in valid_exts]

    ordered_file_names: list[str] = []
    base_time = time.time()

    for i, entry in enumerate(entries):
        track_num = count - i
        vid = entry.get("id") or (entry.get("url", "").split("v=")[-1].split("&")[0])
        title = entry.get("title", "")
        author = entry.get("uploader") or entry.get("artist") or entry.get("channel") or ""
        year = str(entry.get("release_year") or entry.get("upload_date") or "")[:4] or None
        thumb = entry.get("thumbnail") or ""

        target_file: Optional[Path] = None

        # 1. Look up via vid
        if vid and vid in vid_to_paths and vid_to_paths[vid]:
            target_file = vid_to_paths[vid][0]

        # 2. Look up via strict Author & Title match
        if not target_file and title and len(title.strip()) >= 2:
            for f in all_local_files:
                if _author_and_title_match(f.stem, title, author):
                    target_file = f
                    break

        if target_file and target_file.exists():
            ordered_file_names.append(target_file.name)
            ext = target_file.suffix.lower()

            target_idx = track_num if track_number_enabled else None
            target_album = out.name if album_enabled else None
            target_art = author if artist_enabled else None
            target_tit = title if title_enabled else None
            target_yr = year if year_enabled else None

            try:
                if ext == ".mp3":
                    fix_mp3_tags(target_file, track_num=target_idx, total_tracks=count if track_number_enabled else None, album=target_album, artist=target_art, title=target_tit, year=target_yr)
                elif ext == ".flac":
                    fix_flac_tags(target_file, track_num=target_idx, total_tracks=count if track_number_enabled else None, album=target_album, artist=target_art, title=target_tit, year=target_yr)
                elif ext in (".opus", ".ogg"):
                    fix_opus_tags(target_file, track_num=target_idx, total_tracks=count if track_number_enabled else None, album=target_album, artist=target_art, title=target_tit, year=target_yr)
                elif ext in (".m4a", ".aac", ".alac"):
                    fix_m4a_tags(target_file, track_num=target_idx, total_tracks=count if track_number_enabled else None, album=target_album, artist=target_art, title=target_tit, year=target_yr)

                # Update timestamp for proper sorting
                new_time = base_time - 86400 + track_num
                os.utime(str(target_file), (new_time, new_time))
            except Exception:
                pass

    if ordered_file_names:
        write_playlist_order(out, ordered_file_names)


def log_failed_download(output_dir: Path | str, title: str, author: str, url: str, reason: str) -> None:
    """Append failed download record to failed_downloads.txt and app_logs.txt."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    failed_log = out / "failed_downloads.txt"
    unhide_file(failed_log)
    try:
        with open(failed_log, "a", encoding="utf-8") as f:
            f.write(f"{author} — {title}\n")
            if url:
                f.write(f"URL:    {url}\n")
            f.write(f"Reason: {friendly_error(reason)}\n\n")
        hide_file(failed_log)
    except Exception:
        pass

    try:
        import datetime
        from core.settings import get_app_data_dir
        app_log = get_app_data_dir() / "app_logs.txt"
        with open(app_log, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ERROR: Failed to download '{title}': {friendly_error(reason)}\n")
    except Exception:
        pass


def clear_failed_log_if_clean(output_dir: Path | str) -> None:
    """If all tracks in playlist directory exist and are valid, remove failed_downloads.txt."""
    out = Path(output_dir)
    failed_log = out / "failed_downloads.txt"
    if failed_log.exists():
        try:
            unhide_file(failed_log)
            failed_log.unlink(missing_ok=True)
        except Exception:
            pass


# ─── Tag & Cover Processing ───────────────────────────────────────────────────

def fetch_and_crop_cover_jpeg(
    path: Path,
    thumbnail_url: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None
) -> Optional[bytes]:
    """Search for downloaded thumbnail, or download thumbnail_url / YouTube / iTunes cover, crop to 1000x1000 square, and return JPEG bytes."""
    # 1. Search local thumbnail files in path.parent
    try:
        parent = path.parent
        stem = path.stem
        for ext in (".jpg", ".jpeg", ".webp", ".png"):
            cand = parent / f"{stem}{ext}"
            if cand.exists() and cand.is_file():
                try:
                    img = Image.open(cand)
                    sq = crop_to_square(img)
                    buf = io.BytesIO()
                    sq.save(buf, format="JPEG", quality=95)
                    cand.unlink(missing_ok=True)
                    return buf.getvalue()
                except Exception:
                    pass
        for f in parent.glob(f"{stem[:25]}*.*"):
            if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".webp", ".png") and not f.name.startswith("cover."):
                try:
                    img = Image.open(f)
                    sq = crop_to_square(img)
                    buf = io.BytesIO()
                    sq.save(buf, format="JPEG", quality=95)
                    f.unlink(missing_ok=True)
                    return buf.getvalue()
                except Exception:
                    pass
    except Exception:
        pass

    # 2. Download from explicit thumbnail_url
    if thumbnail_url and str(thumbnail_url).startswith("http"):
        try:
            req = urllib.request.Request(thumbnail_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read()
            img = Image.open(io.BytesIO(data))
            sq = crop_to_square(img)
            buf = io.BytesIO()
            sq.save(buf, format="JPEG", quality=95)
            return buf.getvalue()
        except Exception:
            pass

    # 3. Lookup video ID from stem_vid_map.json and fetch YouTube HQ thumbnail
    try:
        stem_map = read_stem_vid_map(path.parent)
        vid = stem_map.get(path.stem)
        if vid:
            for yt_url in (f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg", f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"):
                try:
                    req = urllib.request.Request(yt_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        if resp.status == 200:
                            data = resp.read()
                            img = Image.open(io.BytesIO(data))
                            sq = crop_to_square(img)
                            buf = io.BytesIO()
                            sq.save(buf, format="JPEG", quality=95)
                            return buf.getvalue()
                except Exception:
                    pass
    except Exception:
        pass

    # 4. Search iTunes API for original high-resolution square cover
    if (artist and title) or path.stem:
        try:
            query = f"{artist} {title}".strip() if (artist and title) else path.stem
            query_clean = re.sub(r'[\(\[\{].*?[\)\]\}]', '', query).strip()
            if query_clean:
                q_enc = urllib.parse.quote_plus(query_clean)
                itunes_url = f"https://itunes.apple.com/search?term={q_enc}&entity=song&limit=1"
                req = urllib.request.Request(itunes_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        import json as _json
                        data = _json.loads(resp.read().decode("utf-8", errors="ignore"))
                        results = data.get("results", [])
                        if results:
                            art_url = results[0].get("artworkUrl100", "")
                            if art_url:
                                high_res = art_url.replace("100x100bb.jpg", "1000x1000bb.jpg").replace("100x100bb.png", "1000x1000bb.png")
                                req_img = urllib.request.Request(high_res, headers={"User-Agent": "Mozilla/5.0"})
                                with urllib.request.urlopen(req_img, timeout=6) as r_img:
                                    if r_img.status == 200:
                                        img = Image.open(io.BytesIO(r_img.read()))
                                        sq = crop_to_square(img)
                                        buf = io.BytesIO()
                                        sq.save(buf, format="JPEG", quality=95)
                                        return buf.getvalue()
        except Exception:
            pass

    return None


def fix_mp3_cover(path: Path, thumbnail_url: Optional[str] = None, artist: Optional[str] = None, title: Optional[str] = None) -> None:
    """Crop embedded MP3 cover to 1000x1000 square, or download & embed if missing, saving strictly with ID3v2.3."""
    if ID3 is None or APIC is None:
        return
    try:
        tags = ID3(path)
    except Exception:
        try:
            tags = ID3()
            tags.save(str(path), v2_version=3)
        except Exception:
            return

    apic_keys = [k for k in tags if k.startswith("APIC")]
    if apic_keys:
        changed = False
        for key in apic_keys:
            apic = tags[key]
            try:
                img = Image.open(io.BytesIO(apic.data))
                if img.width == img.height == 1000:
                    continue
                buf = io.BytesIO()
                crop_to_square(img).save(buf, format="JPEG", quality=95)
                tags[key] = APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,  # Cover (front)
                    desc=getattr(apic, "desc", "Cover") or "Cover",
                    data=buf.getvalue(),
                )
                changed = True
            except Exception:
                pass
        if changed:
            try:
                tags.save(str(path), v2_version=3)
            except Exception:
                pass
    else:
        img_bytes = fetch_and_crop_cover_jpeg(path, thumbnail_url=thumbnail_url, artist=artist, title=title)
        if img_bytes:
            try:
                tags["APIC:Cover"] = APIC(
                    encoding=3,
                    mime="image/jpeg",
                    type=3,
                    desc="Cover",
                    data=img_bytes,
                )
                tags.save(str(path), v2_version=3)
            except Exception:
                pass


def fix_mp3_tags(
    path: Path,
    track_num: Optional[int] = None,
    total_tracks: Optional[int] = None,
    album: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    year: Optional[str] = None,
    lyrics: Optional[str] = None,
) -> None:
    if ID3 is None:
        return
    try:
        tags = ID3(path)
    except Exception:
        try:
            tags = ID3()
            tags.save(str(path), v2_version=3)
        except Exception:
            return

    changed = False
    if artist and TPE1:
        tags["TPE1"] = TPE1(encoding=3, text=[artist.strip()])
        changed = True
    elif "TPE1" in tags and TPE1:
        art_val = str(tags["TPE1"]).strip()
        if art_val:
            tags["TPE1"] = TPE1(encoding=3, text=[art_val])
            changed = True

    if title and TIT2:
        tags["TIT2"] = TIT2(encoding=3, text=[title.strip()])
        changed = True

    if track_num is not None and TRCK:
        track_text = f"{track_num}/{total_tracks}" if total_tracks else str(track_num)
        tags["TRCK"] = TRCK(encoding=3, text=[track_text])
        changed = True

    if album and TALB and not (str(tags.get("TALB", "")).strip()):
        tags["TALB"] = TALB(encoding=3, text=[album])
        changed = True

    if year:
        y_str = str(year).strip()[:4]
        if TYER:
            tags["TYER"] = TYER(encoding=3, text=[y_str])
            changed = True
        if TDRC:
            tags["TDRC"] = TDRC(encoding=3, text=[y_str])
            changed = True

    if lyrics and USLT:
        tags["USLT"] = USLT(encoding=3, lang="eng", desc="Lyrics", text=lyrics)
        changed = True

    if changed:
        for _ in range(4):
            try:
                tags.save(str(path), v2_version=3)
                break
            except (PermissionError, OSError):
                time.sleep(0.15)
            except Exception:
                break


def fix_flac_cover(path: Path, thumbnail_url: Optional[str] = None, artist: Optional[str] = None, title: Optional[str] = None) -> None:
    """Crop embedded FLAC cover to 1000x1000 square Picture block, or embed if missing."""
    if FLAC is None:
        return
    try:
        audio = FLAC(path)
    except Exception:
        return

    pictures = list(audio.pictures)
    if pictures:
        changed = False
        new_pictures = []
        for pic in pictures:
            try:
                img = Image.open(io.BytesIO(pic.data))
                if img.width == img.height == 1000:
                    new_pictures.append(pic)
                    continue
                buf = io.BytesIO()
                crop_to_square(img).save(buf, format="JPEG", quality=95)
                if Picture:
                    new_pic = Picture()
                    new_pic.data = buf.getvalue()
                    new_pic.mime = "image/jpeg"
                    new_pic.type = 3  # Cover (front)
                    new_pic.width = 1000
                    new_pic.height = 1000
                    new_pic.depth = 24
                    new_pic.desc = getattr(pic, "desc", "Cover") or "Cover"
                    new_pictures.append(new_pic)
                else:
                    pic.data = buf.getvalue()
                    pic.mime = "image/jpeg"
                    pic.width, pic.height, pic.depth = 1000, 1000, 24
                    pic.type = 3
                    new_pictures.append(pic)
                changed = True
            except Exception:
                new_pictures.append(pic)

        if changed:
            for _ in range(4):
                try:
                    audio.clear_pictures()
                    for p in new_pictures:
                        audio.add_picture(p)
                    audio.save()
                    break
                except (PermissionError, OSError):
                    time.sleep(0.15)
                except Exception:
                    break
    else:
        img_bytes = fetch_and_crop_cover_jpeg(path, thumbnail_url=thumbnail_url, artist=artist, title=title)
        if img_bytes and Picture:
            try:
                pic = Picture()
                pic.data = img_bytes
                pic.mime = "image/jpeg"
                pic.type = 3
                pic.width = 1000
                pic.height = 1000
                pic.depth = 24
                pic.desc = "Cover"
                audio.add_picture(pic)
                audio.save()
            except Exception:
                pass


def fix_flac_tags(
    path: Path,
    track_num: Optional[int] = None,
    total_tracks: Optional[int] = None,
    album: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    year: Optional[str] = None,
    lyrics: Optional[str] = None,
) -> None:
    if FLAC is None:
        return
    try:
        audio = FLAC(path)
    except Exception:
        return

    changed = False
    art_val = (
        artist
        or audio.get("artist", [""])[0].strip()
        or audio.get("albumartist", [""])[0].strip()
        or audio.get("uploader", [""])[0].strip()
    )
    if art_val:
        audio["artist"] = [art_val]
        changed = True

    if title:
        audio["title"] = [title.strip()]
        changed = True

    if track_num is not None:
        audio["tracknumber"] = [
            f"{track_num}/{total_tracks}" if total_tracks else str(track_num)
        ]
        changed = True

    if album and not audio.get("album", [""])[0].strip():
        audio["album"] = [album]
        changed = True

    if year:
        audio["date"] = [str(year).strip()[:4]]
        changed = True

    if lyrics:
        audio["lyrics"] = [lyrics]
        changed = True

    if changed:
        try:
            audio.save()
        except Exception:
            pass


def fix_opus_cover(path: Path, thumbnail_url: Optional[str] = None, artist: Optional[str] = None, title: Optional[str] = None) -> None:
    """Crop embedded Opus/OGG cover to 1000x1000 square Picture block, or embed if missing."""
    if OggOpus is None or Picture is None:
        return
    try:
        audio = OggOpus(path)
    except Exception:
        return

    pic_keys = [k for k in audio.keys() if k.lower() == "metadata_block_picture"]
    if pic_keys:
        changed = False
        new_b64_list = []
        for k in pic_keys:
            for b64_str in audio[k]:
                try:
                    raw_bytes = base64.b64decode(b64_str)
                    pic = Picture(raw_bytes)
                    img = Image.open(io.BytesIO(pic.data))
                    if img.width == img.height == 1000:
                        new_b64_list.append(b64_str)
                        continue
                    buf = io.BytesIO()
                    crop_to_square(img).save(buf, format="JPEG", quality=95)
                    pic.data = buf.getvalue()
                    pic.mime = "image/jpeg"
                    pic.type = 3
                    pic.width = 1000
                    pic.height = 1000
                    pic.depth = 24
                    pic.desc = "Cover"
                    new_b64_list.append(base64.b64encode(pic.write()).decode("ascii"))
                    changed = True
                except Exception:
                    new_b64_list.append(b64_str)

        if changed:
            try:
                for k in pic_keys:
                    del audio[k]
                audio["metadata_block_picture"] = new_b64_list
                audio.save()
            except Exception:
                pass
    else:
        img_bytes = fetch_and_crop_cover_jpeg(path, thumbnail_url=thumbnail_url, artist=artist, title=title)
        if img_bytes:
            try:
                pic = Picture()
                pic.data = img_bytes
                pic.mime = "image/jpeg"
                pic.type = 3
                pic.width = 1000
                pic.height = 1000
                pic.depth = 24
                pic.desc = "Cover"
                audio["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
                audio.save()
            except Exception:
                pass


def fix_opus_tags(
    path: Path,
    track_num: Optional[int] = None,
    total_tracks: Optional[int] = None,
    album: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    year: Optional[str] = None,
    lyrics: Optional[str] = None,
) -> None:
    if OggOpus is None:
        return
    try:
        audio = OggOpus(path)
    except Exception:
        return

    changed = False
    art_val = (
        artist
        or audio.get("artist", [""])[0].strip()
        or audio.get("albumartist", [""])[0].strip()
        or audio.get("uploader", [""])[0].strip()
    )
    if art_val:
        audio["artist"] = [art_val]
        changed = True

    if title:
        audio["title"] = [title.strip()]
        changed = True

    if track_num is not None:
        audio["tracknumber"] = [
            f"{track_num}/{total_tracks}" if total_tracks else str(track_num)
        ]
        changed = True

    if album and not audio.get("album", [""])[0].strip():
        audio["album"] = [album]
        changed = True

    if year:
        audio["date"] = [str(year).strip()[:4]]
        changed = True

    if lyrics:
        audio["lyrics"] = [lyrics]
        changed = True

    if changed:
        try:
            audio.save()
        except Exception:
            pass


def fix_m4a_cover(path: Path, thumbnail_url: Optional[str] = None, artist: Optional[str] = None, title: Optional[str] = None) -> None:
    """Crop embedded M4A/ALAC cover to 1000x1000 square, or embed if missing."""
    if MP4 is None or MP4Cover is None:
        return
    try:
        audio = MP4(path)
    except Exception:
        return

    covers = audio.get("covr", [])
    if covers:
        changed = False
        new_covers = []
        for cover in covers:
            try:
                img = Image.open(io.BytesIO(cover))
                if img.width == img.height == 1000:
                    new_covers.append(cover)
                    continue
                buf = io.BytesIO()
                crop_to_square(img).save(buf, format="JPEG", quality=95)
                new_covers.append(MP4Cover(buf.getvalue(), imageformat=MP4Cover.FORMAT_JPEG))
                changed = True
            except Exception:
                new_covers.append(cover)

        if changed:
            try:
                audio["covr"] = new_covers
                audio.save()
            except Exception:
                pass
    else:
        img_bytes = fetch_and_crop_cover_jpeg(path, thumbnail_url=thumbnail_url, artist=artist, title=title)
        if img_bytes:
            try:
                audio["covr"] = [MP4Cover(img_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
                audio.save()
            except Exception:
                pass


def fix_m4a_tags(
    path: Path,
    track_num: Optional[int] = None,
    total_tracks: Optional[int] = None,
    album: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    year: Optional[str] = None,
    lyrics: Optional[str] = None,
) -> None:
    if MP4 is None:
        return
    try:
        audio = MP4(path)
    except Exception:
        return

    changed = False
    if artist:
        audio["\xa9ART"] = [artist.strip()]
        changed = True

    if title:
        audio["\xa9nam"] = [title.strip()]
        changed = True

    if track_num is not None:
        audio["trkn"] = [(track_num, total_tracks or 0)]
        changed = True

    if album and not (audio.get("\xa9alb") or [""])[0]:
        audio["\xa9alb"] = [album]
        changed = True

    if year:
        audio["\xa9day"] = [str(year).strip()[:4]]
        changed = True

    if lyrics:
        audio["\xa9lyr"] = [lyrics]
        changed = True

    if changed:
        try:
            audio.save()
        except Exception:
            pass


def parse_speed_limit(limit_str: Optional[str]) -> Optional[int]:
    """Convert '5 MB/s', '10 MB/s', '500 KB/s', etc. to bytes per second."""
    if not limit_str or "unlimited" in limit_str.lower():
        return None
    m = re.match(r"^([\d.]+)\s*([KkMmGg]?)(?:[Bb]/s|[Bb]ps)?$", limit_str.strip())
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).upper()
    if unit == "K":
        return int(val * 1024)
    elif unit == "M":
        return int(val * 1024 * 1024)
    elif unit == "G":
        return int(val * 1024 * 1024 * 1024)
    return int(val)


def ensure_audio_format(path: Path, target_ext: str = ".mp3") -> Path:
    """Ensure audio file is converted to target audio format if left as .mp4, .m4a or .webm container."""
    if path.suffix.lower() == target_ext.lower():
        return path
    if path.suffix.lower() in (".mp4", ".webm", ".mkv"):
        ffmpeg_bin = get_ffmpeg_path() or "ffmpeg"
        target_path = path.with_suffix(target_ext)
        try:
            import subprocess
            cmd = [ffmpeg_bin, "-y", "-i", str(path), "-vn"]
            if target_ext.lower() == ".mp3":
                cmd.extend(["-c:a", "libmp3lame", "-q:a", "0"])
            elif target_ext.lower() == ".flac":
                cmd.extend(["-c:a", "flac"])
            elif target_ext.lower() == ".opus":
                cmd.extend(["-c:a", "libopus", "-b:a", "160k"])
            elif target_ext.lower() == ".wav":
                cmd.extend(["-c:a", "pcm_s16le"])
            else:
                cmd.extend(["-c:a", "copy"])
            cmd.append(str(target_path))

            flags = 0
            if sys.platform == "win32":
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
            if res.returncode == 0 and target_path.exists() and target_path.stat().st_size > 1000:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
                return target_path
        except Exception:
            pass
    return path


def postprocess_audio_file(
    file_path: Path | str,
    playlist_index: Optional[int] = None,
    playlist_count: Optional[int] = None,
    album: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    year: Optional[str] = None,
    naming_pattern: Optional[str] = None,
    settings: Optional[Any] = None,
    thumbnail_url: Optional[str] = None,
) -> Path:
    """Fix artwork to 1000x1000 and ID3 tags for Windows Explorer / Groove."""
    path = Path(file_path)
    if not path.exists():
        return path

    if path.suffix.lower() in (".mp4", ".webm", ".mkv"):
        path = ensure_audio_format(path, ".mp3")

    tag_opts = {}
    embed_all = True
    if settings:
        embed_all = settings.get('embed_all_metadata', True)
        tag_opts = settings.get('audio_metadata_tags', {})

    artist_enabled = embed_all or tag_opts.get('artist', True)
    title_enabled = embed_all or tag_opts.get('title', True)
    album_enabled = embed_all or tag_opts.get('album', True)
    cover_enabled = embed_all or tag_opts.get('cover', True)
    track_number_enabled = embed_all or tag_opts.get('track_number', True)
    year_enabled = embed_all or tag_opts.get('year', True)
    lyrics_enabled = embed_all or tag_opts.get('lyrics', True)

    target_artist = artist if artist_enabled else None
    target_title = title if title_enabled else None
    target_album = album if album_enabled else None
    target_idx = playlist_index if track_number_enabled else None
    target_year = year if year_enabled else None

    target_lyrics = None
    if lyrics_enabled:
        for l_ext in (".lrc", ".srt", ".vtt"):
            l_file = path.with_suffix(l_ext)
            if l_file.exists():
                try:
                    target_lyrics = l_file.read_text(encoding="utf-8", errors="ignore")
                    break
                except Exception:
                    pass

    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            if cover_enabled:
                fix_mp3_cover(path, thumbnail_url=thumbnail_url, artist=target_artist, title=target_title)
            fix_mp3_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)
        elif ext == ".flac":
            if cover_enabled:
                fix_flac_cover(path, thumbnail_url=thumbnail_url, artist=target_artist, title=target_title)
            fix_flac_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)
        elif ext in (".opus", ".ogg"):
            if cover_enabled:
                fix_opus_cover(path, thumbnail_url=thumbnail_url, artist=target_artist, title=target_title)
            fix_opus_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)
        elif ext in (".m4a", ".aac", ".alac"):
            if cover_enabled:
                fix_m4a_cover(path, thumbnail_url=thumbnail_url, artist=target_artist, title=target_title)
            fix_m4a_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)

        # Apply custom naming pattern if specified, or sanitize default name
        mode = "windows"
        if settings:
            mode = settings.get('filename_compat', 'windows')

        if naming_pattern and naming_pattern.strip():
            pat = naming_pattern.strip()
            safe_artist = (artist or "")
            safe_title = (title or path.stem)
            safe_idx = f"{playlist_index:02d}" if playlist_index is not None else ""
            safe_album = (album or "")
            safe_year = str(year or "")[:4]
            
            new_stem = pat
            new_stem = new_stem.replace("{artist}", safe_artist)
            new_stem = new_stem.replace("{title}", safe_title)
            new_stem = new_stem.replace("{index}", safe_idx)
            new_stem = new_stem.replace("{album}", safe_album)
            new_stem = new_stem.replace("{year}", safe_year)
            new_stem = clean_filename_for_all_devices(new_stem, max_len=240, mode=mode)
        else:
            new_stem = clean_filename_for_all_devices(path.stem, max_len=240, mode=mode)

        if new_stem and new_stem.lower() != path.stem.lower():
            new_path = path.parent / f"{new_stem}{path.suffix}"
            for _ in range(5):
                try:
                    os.replace(str(path), str(new_path))
                    path = new_path
                    break
                except (PermissionError, OSError):
                    time.sleep(0.2)
                except Exception:
                    break

        # File timestamp for Windows / player ordering
        if playlist_index is not None:
            try:
                base_time = time.time()
                new_time = base_time - 86400 + playlist_index
                os.utime(str(path), (new_time, new_time))
            except Exception:
                pass
    except Exception as e:
        print(f"Error during audio post-processing {path.name}: {e}")
    return path


def fix_video_tags(
    path: Path,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    year: Optional[str] = None,
    settings: Optional[Any] = None,
) -> None:
    """Normalize video metadata tags (especially fixing 4-digit Year for Windows Explorer)."""
    if MP4 is None or path.suffix.lower() != ".mp4":
        return
    try:
        video = MP4(path)
        changed = False

        # Fix Year: Windows Explorer parses the MP4 \xa9day atom as a 16-bit int.
        # If yt-dlp/ffmpeg writes an 8-digit date string like '20241125', it overflows 16-bit int to 56037.
        # We ensure \xa9day is strictly a clean 4-digit year '2024'.
        current_day = video.get("\xa9day")
        if current_day and current_day[0]:
            clean_year = str(current_day[0]).strip()[:4]
            if clean_year.isdigit() and len(clean_year) == 4:
                video["\xa9day"] = [clean_year]
                changed = True
        elif year:
            clean_year = str(year).strip()[:4]
            if clean_year.isdigit():
                video["\xa9day"] = [clean_year]
                changed = True

        if artist and not video.get("\xa9ART"):
            video["\xa9ART"] = [artist.strip()]
            changed = True

        if title and not video.get("\xa9nam"):
            video["\xa9nam"] = [title.strip()]
            changed = True

        if changed:
            try:
                video.save()
            except Exception:
                pass
    except Exception:
        pass


def postprocess_video_file(
    file_path: Path | str,
    playlist_index: Optional[int] = None,
    playlist_count: Optional[int] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    resolution: Optional[str] = None,
    fps: Optional[str] = None,
    year: Optional[str] = None,
    naming_pattern: Optional[str] = None,
    settings: Optional[Any] = None,
) -> Path:
    """Apply custom naming pattern, video metadata tag normalization, and timestamps to a downloaded video file."""
    path = Path(file_path)
    if not path.exists():
        return path

    fix_video_tags(path, artist=artist, title=title, year=year, settings=settings)

    mode = "windows"
    if settings:
        mode = settings.get('filename_compat', 'windows')

    if naming_pattern and naming_pattern.strip():
        pat = naming_pattern.strip()
        safe_title = title or path.stem
        safe_artist = artist or ""
        safe_res = resolution or ""
        safe_fps = f"{fps}fps" if fps and not str(fps).endswith("fps") else str(fps or "")
        safe_year = str(year or "")[:4]
        safe_idx = f"{playlist_index:02d}" if playlist_index is not None else ""

        new_stem = pat
        new_stem = new_stem.replace("{title}", safe_title)
        new_stem = new_stem.replace("{author}", safe_artist)
        new_stem = new_stem.replace("{artist}", safe_artist)
        new_stem = new_stem.replace("{resolution}", safe_res)
        new_stem = new_stem.replace("{fps}", safe_fps)
        new_stem = new_stem.replace("{year}", safe_year)
        new_stem = new_stem.replace("{index}", safe_idx)
        new_stem = clean_filename_for_all_devices(new_stem, max_len=240, mode=mode)
    else:
        new_stem = clean_filename_for_all_devices(path.stem, max_len=240, mode=mode)

    if new_stem and new_stem.lower() != path.stem.lower():
        new_path = path.parent / f"{new_stem}{path.suffix}"
        for _ in range(5):
            try:
                os.replace(str(path), str(new_path))
                path = new_path
                break
            except (PermissionError, OSError):
                time.sleep(0.2)
            except Exception:
                break

    # Apply Windows / player timestamp ordering if in a playlist
    if playlist_index is not None:
        try:
            base_time = time.time()
            new_time = base_time - 86400 + playlist_index
            os.utime(str(path), (new_time, new_time))
        except Exception:
            pass

    return path


class MediaDownloader:
    def __init__(self, output_dir: str = "downloads", settings: Optional[Any] = None):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        self.last_error = ""
        self.was_skipped = False
        self.settings = settings or SettingsManager()

    def _map_quality(self, quality: str) -> str:
        if quality in ("Best video", "Best", "Source (Best)"):
            return "bestvideo+bestaudio/best"
        elif quality in ("Worst", "Worst Audio"):
            return "worst"
        elif quality in ("Audio only (MP3)", "Best Audio"):
            return "bestaudio/best"
        elif quality == "Video only (no audio)":
            return "bestvideo"

        import re
        match = re.search(r"(\d+)p", quality)
        if match:
            height = match.group(1)
            return f"bestvideo[height<={height}]+bestaudio/best"

        return "bestvideo+bestaudio/best"

    def download(
        self,
        url: str,
        media_type: str = "Audio (Best)",
        quality: str = "Best",
        cookies: Optional[Dict[str, Any]] = None,
        subtitles: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable] = None,
        playlist_index: Optional[int] = None,
        playlist_count: Optional[int] = None,
        title: Optional[str] = None,
        author: Optional[str] = None,
        speed_limit: Optional[str] = None,
        naming_pattern: Optional[str] = None,
        thumbnail: Optional[str] = None,
    ) -> tuple[bool, str, bool]:
        """Download media from the given URL with auto client rotation, rate limit, and playlist tracking."""
        self.current_title = f"{author} - {title}".strip(" -") if (author or title) else ""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

        clean_url = clean_media_url(url)
        is_video = str(media_type).lower().startswith("video")
        is_audio = not is_video and (str(media_type).lower().startswith("audio") or quality in ("Audio only (MP3)", "Best Audio"))
        outtmpl = os.path.join(self.output_dir, "%(title).120B - %(artist,uploader,creator,channel).60B.%(ext)s")

        codec = "mp3"
        quality_val: Optional[str] = "320"
        if is_audio:
            if "FLAC" in media_type:
                codec = "flac"
                quality_val = None
            elif "Opus" in media_type:
                codec = "opus"
                quality_val = "160"
            elif "WAV" in media_type:
                codec = "wav"
                quality_val = None
            elif "M4A" in media_type or "AAC" in media_type:
                codec = "m4a"
                quality_val = "256"

        # Client strategies for in-flight rotation
        if is_audio:
            if cookies and cookies.get("use"):
                client_rotations = [
                    ["mweb", "web"],
                    ["web", "ios"],
                    ["mweb"],
                ]
            else:
                client_rotations = [
                    ["android", "web"],
                    ["web", "android"],
                ]
        else:
            client_rotations = [
                ["web_embedded", "web"],
                ["android_vr", "web"],
                ["web_embedded"],
                ["mweb", "web"],
            ]

        ydl_opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "noplaylist": True,
            "writethumbnail": not is_audio,
            "convertthumbnails": "jpg",
            "addmetadata": True,
            "embedthumbnail": not is_audio,
            "quiet": False,
            "no_warnings": True,
            "noprogress": False,
            "retries": 20,
            "fragment_retries": 20,
            "remote_components": ["ejs:github"],
            "retry_sleep_functions": {
                "http": lambda n: min(2 * 2**n, 20),
                "fragment": lambda n: min(2 * 2**n, 20),
            },
            "socket_timeout": 30,
            "ignoreerrors": True,
            "parse_metadata": ["%(artist,uploader,creator,channel)s:%(meta_artist)s"],
            "color": "no_color",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/131.0.0.0",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.youtube.com/",
            },
            "extractor_args": {
                "youtube": {
                    "player_client": client_rotations[0],
                },
                "youtubemusic": {
                    "player_client": ["web", "default"],
                },
            },
        }

        speed_limit_bytes = parse_speed_limit(speed_limit)
        if speed_limit_bytes:
            ydl_opts["ratelimit"] = speed_limit_bytes

        if FFMPEG_PATH:
            ydl_opts["ffmpeg_location"] = FFMPEG_PATH

        class YtDlpLogger:
            def __init__(self, log_path: Path, parent: "MediaDownloader"):
                self.log_path = log_path
                self.parent = parent

            def debug(self, msg: str) -> None:
                if (
                    "has already been recorded in the archive" in msg.lower()
                    or "has already been downloaded" in msg.lower()
                ):
                    self.parent.was_skipped = True

            def warning(self, msg: str) -> None:
                pass

            def error(self, msg: str) -> None:
                import re
                import datetime

                clean_msg = re.sub(r"\x1b\[[0-9;]*m", "", msg).strip()
                self.parent.last_error = clean_msg
                try:
                    track_tag = f"[{self.parent.current_title}] " if getattr(self.parent, "current_title", "") else ""
                    with open(self.log_path, "a", encoding="utf-8") as f:
                        f.write(
                            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {track_tag}{clean_msg}\n"
                        )
                except Exception:
                    pass

        # Global app logs
        from core.settings import get_app_data_dir
        log_file = get_app_data_dir() / "app_logs.txt"
        ydl_opts["logger"] = YtDlpLogger(log_file, self)

        # Cookies
        if cookies and cookies.get("use"):
            if cookies.get("source") == "browser":
                browser = cookies.get("browser")
                if browser:
                    ydl_opts["cookiesfrombrowser"] = (browser,)
            elif cookies.get("source") == "file":
                cookie_file = cookies.get("file")
                if cookie_file and is_valid_netscape_cookies(cookie_file):
                    ydl_opts["cookiefile"] = cookie_file
                elif cookie_file and os.path.exists(cookie_file):
                    print(f"[Cookies Warning] File '{cookie_file}' is not a valid Netscape cookie file. Skipping cookies.", file=sys.stderr)

        # Subtitles
        if subtitles and subtitles.get("download"):
            ydl_opts["writesubtitles"] = True
            langs = subtitles.get("langs", "all").strip()
            if langs.lower() == "all" or not langs:
                ydl_opts["subtitleslangs"] = ["all"]
            else:
                ydl_opts["subtitleslangs"] = [l.strip() for l in langs.split(",")]
            ydl_opts["embedsubtitles"] = True

        # Playlist tracking check
        out_path = Path(self.output_dir)
        is_playlist = (playlist_index is not None)
        has_existing_logs = (
            (out_path / "stem_vid_map.json").exists()
            or (out_path / "downloaded_archive.txt").exists()
            or (out_path / "playlist_order.txt").exists()
        )
        should_track_playlist = is_playlist or has_existing_logs

        # Tracking downloaded files & video IDs for postprocessing and mapping
        downloaded_files: set[str] = set()
        extracted_vid: str = ""
        extracted_thumb: str = ""
        extracted_artist: str = ""
        extracted_title: str = ""
        extracted_year: str = ""
        extracted_resolution: str = ""
        extracted_fps: str = ""
        if "v=" in clean_url:
            extracted_vid = clean_url.split("v=")[-1].split("&")[0]
        elif "youtu.be/" in clean_url:
            extracted_vid = clean_url.split("youtu.be/")[-1].split("?")[0]

        if should_track_playlist and extracted_vid:
            if is_file_already_downloaded(self.output_dir, extracted_vid, title=title, author=author, is_audio=is_audio):
                self.was_skipped = True
                if progress_callback:
                    try:
                        progress_callback({"status": "finished", "total_bytes": 1, "downloaded_bytes": 1, "_percent_str": "100%", "_speed_str": "0 MB/s", "_eta_str": "0s", "status_text": "Already downloaded (Skipped)"})
                    except Exception:
                        pass
                cleanup_orphan_files(self.output_dir, is_audio_playlist=is_audio)
                return True, "", True

            check_and_clean_archive_if_file_missing(self.output_dir, extracted_vid, title=title, author=author)
            archive_path = os.path.join(self.output_dir, "downloaded_archive.txt")
            unhide_file(archive_path)
            ydl_opts["download_archive"] = archive_path

        def internal_progress_hook(d: dict) -> None:
            nonlocal extracted_vid, extracted_thumb, extracted_artist, extracted_title, extracted_year, extracted_resolution, extracted_fps
            if d.get("status") == "finished":
                fn = d.get("filename")
                if fn:
                    downloaded_files.add(fn)
                info = d.get("info_dict") or {}
                if info.get("id"):
                    extracted_vid = info.get("id")
                if info.get("thumbnail"):
                    extracted_thumb = info.get("thumbnail")
                if info.get("artist") or info.get("creator") or info.get("uploader"):
                    extracted_artist = info.get("artist") or info.get("creator") or info.get("uploader")
                if info.get("track") or info.get("title"):
                    extracted_title = info.get("track") or info.get("title")
                if info.get("release_year"):
                    extracted_year = str(info.get("release_year"))[:4]
                elif info.get("upload_date"):
                    extracted_year = str(info.get("upload_date"))[:4]
                elif info.get("release_date"):
                    extracted_year = str(info.get("release_date"))[:4]
                if info.get("resolution"):
                    extracted_resolution = str(info.get("resolution"))
                elif info.get("height"):
                    extracted_resolution = f"{info.get('height')}p"
                if info.get("fps"):
                    try:
                        extracted_fps = str(int(info.get("fps")))
                    except Exception:
                        pass
                stem = Path(fn).stem if fn else ""
                if should_track_playlist and stem and extracted_vid:
                    update_stem_vid_map(self.output_dir, stem, extracted_vid)
            if progress_callback:
                progress_callback(d)

        def internal_postprocessor_hook(d: dict) -> None:
            nonlocal extracted_vid, extracted_thumb, extracted_artist, extracted_title, extracted_year, extracted_resolution, extracted_fps
            if d.get("status") == "finished":
                fp = d.get("filepath") or (d.get("info_dict") or {}).get("filepath")
                if fp:
                    downloaded_files.add(fp)
                info = d.get("info_dict") or {}
                if info.get("id"):
                    extracted_vid = info.get("id")
                if info.get("thumbnail"):
                    extracted_thumb = info.get("thumbnail")
                if info.get("artist") or info.get("creator") or info.get("uploader"):
                    extracted_artist = info.get("artist") or info.get("creator") or info.get("uploader")
                if info.get("track") or info.get("title"):
                    extracted_title = info.get("track") or info.get("title")
                if info.get("release_year"):
                    extracted_year = str(info.get("release_year"))[:4]
                elif info.get("upload_date"):
                    extracted_year = str(info.get("upload_date"))[:4]
                elif info.get("release_date"):
                    extracted_year = str(info.get("release_date"))[:4]
                if info.get("resolution"):
                    extracted_resolution = str(info.get("resolution"))
                elif info.get("height"):
                    extracted_resolution = f"{info.get('height')}p"
                if info.get("fps"):
                    try:
                        extracted_fps = str(int(info.get("fps")))
                    except Exception:
                        pass
                stem = Path(fp).stem if fp else ""
                if should_track_playlist and stem and extracted_vid:
                    update_stem_vid_map(self.output_dir, stem, extracted_vid)

        ydl_opts["progress_hooks"] = [internal_progress_hook]
        ydl_opts["postprocessor_hooks"] = [internal_postprocessor_hook]

        # Determine subtitle / lyrics configuration
        subs_cfg = subtitles or {}
        should_download_subs = False
        subs_lang_spec = "orig"

        if is_audio:
            # Audio Lyrics / Karaoke
            is_globally_enabled = self.settings.get('download_audio_lyrics', False) if self.settings else False
            if 'download' in subs_cfg:
                should_download_subs = subs_cfg['download']
                subs_lang_spec = str(subs_cfg.get('langs', 'orig'))
            else:
                should_download_subs = is_globally_enabled
                subs_lang_spec = self.settings.get('lyrics_langs', 'orig') if self.settings else 'orig'
        else:
            # Video Subtitles
            is_globally_enabled = self.settings.get('download_subtitles', False) if self.settings else False
            if 'download' in subs_cfg:
                should_download_subs = subs_cfg['download']
                subs_lang_spec = str(subs_cfg.get('langs', 'orig'))
            else:
                should_download_subs = is_globally_enabled
                subs_lang_spec = self.settings.get('subtitles_langs', 'orig') if self.settings else 'orig'

        if should_download_subs and subs_lang_spec not in ("None", "none", "No Subs", "No Lyrics", "Disabled"):
            ydl_opts["writesubtitles"] = True
            
            clean_spec = subs_lang_spec.strip()
            if clean_spec in ("orig", "Original / Uploaded Only", "Original (Default)", "Original (Uploaded)", "Original / Uploaded Only (Recommended)"):
                ydl_opts["writeautomaticsub"] = False
                ydl_opts["subtitleslangs"] = ["all", "-live_chat"]
            elif clean_spec in ("all", "All", "All Languages"):
                ydl_opts["writeautomaticsub"] = True
                ydl_opts["subtitleslangs"] = ["all", "-live_chat"]
            else:
                # Specific code, e.g. "en", "ru", "uk", "en (auto)", "English (en)"
                clean_code = clean_spec.split()[0].split('(')[0].strip().lower()
                m = re.search(r'\(([a-zA-Z\-_]+)\)', clean_spec)
                if m and m.group(1).lower() != "auto":
                    clean_code = m.group(1).lower()
                
                is_auto = "auto" in clean_spec.lower()
                ydl_opts["writeautomaticsub"] = is_auto
                ydl_opts["subtitleslangs"] = [clean_code, f"{clean_code}.*", f"{clean_code}-*"]

            if is_audio:
                ydl_opts["subtitlesformat"] = "lrc/srt/best"
            else:
                ydl_opts["subtitlesformat"] = "srt/vtt/best"
        else:
            ydl_opts["writesubtitles"] = False
            ydl_opts["writeautomaticsub"] = False

        # Postprocessors setup
        if is_audio:
            ydl_opts["format"] = "bestaudio/best"
            post_audio = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
            }
            if quality_val is not None:
                post_audio["preferredquality"] = quality_val

            ydl_opts["postprocessors"] = [post_audio]
        else:
            v_container = self.settings.get('video_container', 'mp4') if self.settings else 'mp4'
            v_codec = self.settings.get('video_codec', 'auto') if self.settings else 'auto'
            embed_all_v_meta = self.settings.get('embed_all_video_metadata', True) if self.settings else True
            v_meta_tags = self.settings.get('video_metadata_tags', {}) if self.settings else {}

            target_container = "mkv" if v_container == "mkv" else "mp4"

            if v_codec == "h264" or "H.264" in media_type:
                ydl_opts["format"] = "bestvideo[vcodec^=avc]+bestaudio[ext=m4a]/bestvideo[vcodec^=avc]+bestaudio/bestvideo+bestaudio/best"
                ydl_opts["merge_output_format"] = target_container
            elif v_codec == "h265" or "H.265" in media_type:
                ydl_opts["format"] = "bestvideo[vcodec^=hev]+bestaudio/bestvideo[vcodec^=h265]+bestaudio/bestvideo+bestaudio/best"
                ydl_opts["merge_output_format"] = "mkv" if v_container == "mkv" else "mp4"
            elif v_codec == "vp9_av1":
                ydl_opts["format"] = "bestvideo[vcodec^=vp9]+bestaudio/bestvideo[vcodec^=av01]+bestaudio/bestvideo+bestaudio/best"
                ydl_opts["merge_output_format"] = "mkv" if v_container == "mkv" else "mp4"
            else:
                ydl_opts["format"] = self._map_quality(quality)
                ydl_opts["merge_output_format"] = target_container

            video_pps = []
            if embed_all_v_meta or v_meta_tags.get('title_desc', True) or v_meta_tags.get('author', True):
                add_chap = embed_all_v_meta or v_meta_tags.get('chapters', True)
                video_pps.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": add_chap})
            if embed_all_v_meta or v_meta_tags.get('thumbnail', True):
                video_pps.append({"key": "EmbedThumbnail"})
            if (embed_all_v_meta or v_meta_tags.get('subtitles', True)) and should_download_subs:
                video_pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})

            ydl_opts["postprocessors"] = video_pps

        start_time = time.time()
        success = False

        # In-Flight Silent Auto-Recovery loop with client rotation
        max_attempts = len(client_rotations)
        for attempt in range(max_attempts):
            try:
                self.last_error = ""
                self.was_skipped = False
                ydl_opts["extractor_args"]["youtube"]["player_client"] = client_rotations[attempt]

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    retcode = ydl.download([clean_url])

                success = (retcode == 0) and not self.last_error
                if success or self.was_skipped:
                    break

                if attempt < max_attempts - 1:
                    time.sleep(0.3)
                    continue
                else:
                    break
            except Exception as e:
                self.last_error = str(e)
                if attempt < max_attempts - 1:
                    time.sleep(0.3)
                    continue
                break

        # Strict Verified Fallback for Deleted / Re-uploaded official tracks:
        if not success and not self.was_skipped:
            err_l = (self.last_error or "").lower()
            if any(k in err_l for k in ("video unavailable", "not available", "this video is not available", "unplayable", "removed following a copyright")):
                t = (title or extracted_title or "").strip()
                a = (author or extracted_artist or "").strip()
                is_placeholder = (
                    not t
                    or t.startswith("[Unavailable")
                    or t.startswith("[Deleted")
                    or "unavailable / deleted" in t.lower()
                    or t.lower() in ("deleted video", "private video", "unknown title", "video unavailable")
                )
                if not is_placeholder and t:
                    if progress_callback:
                        progress_callback({"status": "downloading", "msg": "Searching official release..."})
                    import re
                    clean_q_t = re.sub(r"[\(\[\{]\s*from\s+[^)\]\}]+[\)\]\}]", "", t, flags=re.IGNORECASE).strip()
                    clean_q_a = re.sub(r"[\(\[\{]\s*read\s+desc[^\)\]\}]*[\)\]\}]", "", a, flags=re.IGNORECASE).strip()
                    search_q = f"{clean_q_a} {clean_q_t}".strip()
                    try:
                        s_opts = dict(ydl_opts)
                        s_opts["extract_flat"] = True
                        s_opts.pop("download_archive", None)
                        with yt_dlp.YoutubeDL(s_opts) as ydl_s:
                            s_res = ydl_s.extract_info(f"ytsearch5:{search_q}", download=False)
                            cand_url = None
                            cand_id = None
                            for entry in s_res.get("entries", []):
                                e_id = entry.get("id")
                                e_title = entry.get("title", "")
                                e_uploader = entry.get("uploader", "")
                                if e_id and e_id != extracted_vid and match_search_candidate(e_title, e_uploader, t, a):
                                    cand_url = f"https://www.youtube.com/watch?v={e_id}"
                                    cand_id = e_id
                                    break
                            if cand_url:
                                dl_fallback_opts = dict(ydl_opts)
                                dl_fallback_opts.pop("download_archive", None)
                                with yt_dlp.YoutubeDL(dl_fallback_opts) as ydl_dl:
                                    retcode = ydl_dl.download([cand_url])
                                    if retcode == 0:
                                        success = True
                                        self.last_error = ""
                                        # Record mapped original VID into archive and map
                                        if should_track_playlist and extracted_vid:
                                            archive_file = Path(self.output_dir) / "downloaded_archive.txt"
                                            if archive_file.exists():
                                                try:
                                                    unhide_file(archive_file)
                                                    with open(archive_file, "a", encoding="utf-8") as f_arc:
                                                        f_arc.write(f"youtube {extracted_vid}\n")
                                                        if cand_id:
                                                            f_arc.write(f"youtube {cand_id}\n")
                                                    hide_file(archive_file)
                                                except Exception:
                                                    pass
                    except Exception:
                        pass

        if not success and not self.last_error:
            self.last_error = "Unknown error occurred."

        try:
            # Post-process downloaded files: crop covers / tags for audio, custom renaming for video
            processed_files: list[Path] = []
            for fp in list(downloaded_files):
                p = Path(fp)
                if is_audio:
                    exts = (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac")
                else:
                    exts = (".mp4", ".mkv", ".webm", ".avi", ".mov")
                target_paths = [p] + [p.with_suffix(ext) for ext in exts]

                for candidate in target_paths:
                    if candidate.exists() and candidate.is_file() and candidate not in processed_files:
                        if is_audio:
                            candidate = postprocess_audio_file(
                                candidate,
                                playlist_index=playlist_index,
                                playlist_count=playlist_count,
                                album=os.path.basename(self.output_dir) if playlist_count else None,
                                artist=extracted_artist or author,
                                title=extracted_title or title,
                                year=extracted_year,
                                naming_pattern=naming_pattern,
                                settings=self.settings,
                                thumbnail_url=extracted_thumb or thumbnail,
                            )
                        else:
                            v_pat = self.settings.get('video_naming_pattern', '{title}') if self.settings else '{title}'
                            candidate = postprocess_video_file(
                                candidate,
                                playlist_index=playlist_index,
                                playlist_count=playlist_count,
                                artist=extracted_artist or author,
                                title=extracted_title or title,
                                resolution=extracted_resolution,
                                fps=extracted_fps,
                                year=extracted_year,
                                naming_pattern=v_pat,
                                settings=self.settings,
                            )
                        processed_files.append(candidate)
                        if should_track_playlist:
                            append_playlist_order(self.output_dir, candidate.name)
                            if extracted_vid:
                                update_stem_vid_map(self.output_dir, candidate.stem, extracted_vid)

            # Strict validation: Only accept newly created/modified files matching this download
            if not processed_files and not self.was_skipped:
                for f in Path(self.output_dir).glob("*.*"):
                    if (
                        f.is_file()
                        and f.suffix.lower() in (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv")
                        and f.stat().st_size >= 500 * 1024
                        and f.stat().st_mtime >= start_time
                        and _author_and_title_match(f.stem, title or extracted_title, author or extracted_artist)
                    ):
                        if is_audio:
                            f = postprocess_audio_file(
                                f,
                                playlist_index=playlist_index,
                                playlist_count=playlist_count,
                                album=os.path.basename(self.output_dir) if playlist_count else None,
                                artist=extracted_artist or author,
                                title=extracted_title or title,
                                year=extracted_year,
                                naming_pattern=naming_pattern,
                                settings=self.settings,
                                thumbnail_url=extracted_thumb or thumbnail,
                            )
                        else:
                            v_pat = self.settings.get('video_naming_pattern', '{title}') if self.settings else '{title}'
                            f = postprocess_video_file(
                                f,
                                playlist_index=playlist_index,
                                playlist_count=playlist_count,
                                artist=extracted_artist or author,
                                title=extracted_title or title,
                                resolution=extracted_resolution,
                                fps=extracted_fps,
                                year=extracted_year,
                                naming_pattern=v_pat,
                                settings=self.settings,
                            )
                        processed_files.append(f)
                        if should_track_playlist:
                            append_playlist_order(self.output_dir, f.name)
                            if extracted_vid:
                                update_stem_vid_map(self.output_dir, f.stem, extracted_vid)

            if processed_files:
                success = True
                self.last_error = ""
            elif not self.was_skipped:
                success = False

            # Hide service files on Windows if created/updated
            if should_track_playlist:
                hide_file(out_path / "downloaded_archive.txt")
                hide_file(out_path / "stem_vid_map.json")
                hide_file(out_path / "playlist_order.txt")

            # If download failed, log to failed_downloads.txt in playlist folder
            if not success and self.last_error and not self.was_skipped:
                log_failed_download(
                    self.output_dir,
                    title=title or "Unknown Title",
                    author=author or "Unknown Artist",
                    url=url,
                    reason=self.last_error,
                )

            cleanup_orphan_files(self.output_dir, is_audio_playlist=is_audio)
            return success, self.last_error, self.was_skipped
        except Exception as e:
            cleanup_orphan_files(self.output_dir, is_audio_playlist=is_audio)
            if success:
                return True, "", self.was_skipped
            return False, str(e), False
