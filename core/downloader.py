import base64
import io
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from PIL import Image
import yt_dlp
from core.settings import SettingsManager

try:
    from mutagen.flac import FLAC, Picture
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK, TDRC, TYER, USLT
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
except ImportError:
    FLAC, Picture = None, None
    ID3, APIC, TALB, TIT2, TPE1, TRCK, TDRC, TYER, USLT = None, None, None, None, None, None, None, None, None
    MP4, MP4Cover = None, None
    OggOpus = None

ERROR_REASONS: list[tuple[str, str]] = [
    ("Sign in to confirm your age", "Age-restricted — cookies required"),
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
    return Path(__file__).parent.parent


def get_ffmpeg_path() -> Optional[str]:
    local_ffmpeg = get_base_dir() / "ffmpeg.exe"
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        return which_ffmpeg
    return None


def get_ffprobe_path() -> Optional[str]:
    local_ffprobe = get_base_dir() / "ffprobe.exe"
    if local_ffprobe.exists():
        return str(local_ffprobe)
    which_ffprobe = shutil.which("ffprobe")
    if which_ffprobe:
        return which_ffprobe
    return None


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
    """Read stem -> video_id mapping from stem_vid_map.json."""
    map_file = Path(output_dir) / "stem_vid_map.json"
    if map_file.exists():
        try:
            return json.loads(map_file.read_text(encoding="utf-8"))
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


def check_and_clean_archive_if_file_missing(output_dir: Path | str, vid: str, title: str = "", author: str = "") -> None:
    """If a track is listed in downloaded_archive.txt but not found on disk, remove it from archive so yt-dlp re-downloads it."""
    if not vid:
        return
    out = Path(output_dir)
    archive_file = out / "downloaded_archive.txt"
    if not archive_file.exists():
        return

    stem_map = read_stem_vid_map(out)
    valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".webm", ".avi"}
    file_exists = False

    # 1. Check via stem_map
    for stem, mapped_vid in stem_map.items():
        if mapped_vid == vid:
            for ext in valid_exts:
                if (out / f"{stem}{ext}").exists():
                    file_exists = True
                    break
        if file_exists:
            break

    # 2. Check via title matching in filenames if not found in stem_map
    if not file_exists and title and len(title.strip()) >= 3:
        clean_t = title.strip().lower()
        try:
            for f in out.iterdir():
                if f.is_file() and f.suffix.lower() in valid_exts:
                    if clean_t in f.name.lower() or f.stem.lower() in clean_t:
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

        target_file: Optional[Path] = None

        # 1. Look up via vid
        if vid and vid in vid_to_paths and vid_to_paths[vid]:
            target_file = vid_to_paths[vid][0]

        # 2. Look up via title match
        if not target_file and title and len(title.strip()) >= 3:
            clean_t = title.strip().lower()
            for f in all_local_files:
                if clean_t in f.name.lower() or f.stem.lower() in clean_t:
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
    """Append failed download record to failed_downloads.txt in the output directory."""
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


def clear_failed_log_if_clean(output_dir: Path | str) -> None:
    """Remove failed_downloads.txt from output directory if all tracks succeeded."""
    out = Path(output_dir)
    failed_log = out / "failed_downloads.txt"
    if failed_log.exists():
        try:
            unhide_file(failed_log)
            failed_log.unlink(missing_ok=True)
        except Exception:
            pass


# ─── Tag & Cover Processing ───────────────────────────────────────────────────

def fix_mp3_cover(path: Path) -> None:
    """Crop embedded MP3 cover to 1000x1000 square and save strictly with ID3v2.3 for Windows Explorer."""
    if ID3 is None or APIC is None:
        return
    try:
        tags = ID3(path)
    except Exception:
        return

    apic_keys = [k for k in tags if k.startswith("APIC")]
    if not apic_keys:
        return

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
            tags.save(v2_version=3)
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


def fix_flac_cover(path: Path) -> None:
    """Crop embedded FLAC cover to 1000x1000 square Picture block."""
    if FLAC is None:
        return
    try:
        audio = FLAC(path)
    except Exception:
        return

    pictures = list(audio.pictures)
    if not pictures:
        return

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


def fix_opus_cover(path: Path) -> None:
    """Crop embedded Opus/OGG cover to 1000x1000 square Picture block."""
    if OggOpus is None or Picture is None:
        return
    try:
        audio = OggOpus(path)
    except Exception:
        return

    pic_keys = [k for k in audio.keys() if k.lower() == "metadata_block_picture"]
    if not pic_keys:
        return

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


def fix_m4a_cover(path: Path) -> None:
    """Crop embedded M4A/ALAC cover to 1000x1000 square."""
    if MP4 is None or MP4Cover is None:
        return
    try:
        audio = MP4(path)
    except Exception:
        return

    covers = audio.get("covr", [])
    if not covers:
        return

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
) -> Path:
    """Fix artwork to 1000x1000 and ID3 tags for Windows Explorer / Groove."""
    path = Path(file_path)
    if not path.exists():
        return path

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
                fix_mp3_cover(path)
            fix_mp3_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)
        elif ext == ".flac":
            if cover_enabled:
                fix_flac_cover(path)
            fix_flac_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)
        elif ext in (".opus", ".ogg"):
            if cover_enabled:
                fix_opus_cover(path)
            fix_opus_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)
        elif ext in (".m4a", ".aac", ".alac"):
            if cover_enabled:
                fix_m4a_cover(path)
            fix_m4a_tags(path, track_num=target_idx, total_tracks=playlist_count if track_number_enabled else None, album=target_album, artist=target_artist, title=target_title, year=target_year, lyrics=target_lyrics)

        # Apply custom naming pattern if specified
        if naming_pattern and naming_pattern.strip():
            pat = naming_pattern.strip()
            safe_artist = artist or ""
            safe_title = title or path.stem
            safe_idx = f"{playlist_index:02d}" if playlist_index is not None else ""
            safe_album = album or ""
            safe_year = str(year or "")
            
            new_stem = pat
            new_stem = new_stem.replace("{artist}", safe_artist)
            new_stem = new_stem.replace("{title}", safe_title)
            new_stem = new_stem.replace("{index}", safe_idx)
            new_stem = new_stem.replace("{album}", safe_album)
            new_stem = new_stem.replace("{year}", safe_year)
            
            for ch in r'\/:*?"<>|':
                new_stem = new_stem.replace(ch, "_")
            new_stem = new_stem.strip(" -._")

            if new_stem:
                new_path = path.parent / f"{new_stem}{path.suffix}"
                try:
                    is_same = (new_path.resolve() == path.resolve())
                except Exception:
                    is_same = (str(new_path).lower() == str(path).lower())

                if not is_same:
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

        for ch in r'\/:*?"<>|':
            new_stem = new_stem.replace(ch, "_")
        new_stem = new_stem.strip(" -._")
        if new_stem:
            new_path = path.parent / f"{new_stem}{path.suffix}"
            try:
                is_same = (new_path.resolve() == path.resolve())
            except Exception:
                is_same = (str(new_path).lower() == str(path).lower())

            if not is_same:
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
    ) -> tuple[bool, str, bool]:
        """Download media from the given URL with auto client rotation, rate limit, and playlist tracking."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

        clean_url = clean_media_url(url)
        is_audio = media_type.startswith("Audio") or quality in ("Audio only (MP3)", "Best Audio")
        outtmpl = os.path.join(self.output_dir, "%(title)s - %(artist,uploader,creator,channel)s.%(ext)s")

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
            client_rotations = [
                ["android", "web"],
                ["web", "android"],
            ]
        else:
            # For video, prioritize high-resolution desktop clients
            client_rotations = [
                ["web", "default"],
                ["web"],
                ["android", "web"],
            ]

        ydl_opts: dict[str, Any] = {
            "outtmpl": outtmpl,
            "writethumbnail": (is_audio and codec != "wav") or not is_audio,
            "convertthumbnails": "jpg",
            "addmetadata": True,
            "embedthumbnail": (is_audio and codec != "wav") or not is_audio,
            "quiet": False,
            "no_warnings": True,
            "noprogress": False,
            "retries": 20,
            "fragment_retries": 20,
            "retry_sleep_functions": {
                "http": lambda n: min(2 * 2**n, 20),
                "fragment": lambda n: min(2 * 2**n, 20),
            },
            "socket_timeout": 30,
            "ignoreerrors": True,
            "parse_metadata": ["%(artist,uploader,creator,channel)s:%(meta_artist)s"],
            "color": "no_color",
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
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
                    with open(self.log_path, "a", encoding="utf-8") as f:
                        f.write(
                            f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {clean_msg}\n"
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
                if cookie_file and os.path.exists(cookie_file):
                    ydl_opts["cookiefile"] = cookie_file

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

        if should_track_playlist:
            if extracted_vid:
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
            ydl_opts["format"] = "bestaudio/bestvideo+bestaudio/best"
            post_audio = {
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
            }
            if quality_val is not None:
                post_audio["preferredquality"] = quality_val

            pps = [
                post_audio,
                {"key": "FFmpegMetadata"},
            ]
            if codec != "wav":
                pps.append({"key": "EmbedThumbnail"})

            ydl_opts["postprocessors"] = pps
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

                success = retcode == 0
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

        # Smart Auto-Fallback: if 18+ age restriction or video unavailable, search and download official alternate
        if not success and not self.was_skipped:
            err_lower = self.last_error.lower()
            if any(k in err_lower for k in ("sign in to confirm your age", "age-restricted", "video unavailable", "not available", "private video", "blocked")):
                try:
                    safe_title = (title or "").strip()
                    safe_author = (author or "").strip()
                    if safe_author and safe_author.lower() in safe_title.lower():
                        search_query = safe_title
                    else:
                        search_query = f"{safe_author} {safe_title}".strip()

                    if not search_query or search_query == "Unknown":
                        # Try flat extract to get track name
                        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl_flat:
                            try:
                                meta = ydl_flat.extract_info(clean_url, download=False)
                                u = meta.get('uploader', '') or meta.get('artist', '')
                                t = meta.get('title', '')
                                search_query = f"{u} {t}".strip()
                            except Exception:
                                pass

                    if search_query and search_query != "Unknown":
                        fallback_term = f"ytsearch1:{search_query} audio" if is_audio else f"ytsearch1:{search_query}"
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            retcode = ydl.download([fallback_term])
                            if retcode == 0:
                                success = True
                                self.last_error = ""
                except Exception:
                    pass

        if not success and not self.last_error:
            self.last_error = "Unknown error occurred."

        try:
            # Post-process downloaded files: crop covers / tags for audio, custom renaming for video
            processed_files: list[Path] = []
            for fp in list(downloaded_files):
                p = Path(fp)
                target_paths = [p]
                for ext in (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv"):
                    target_paths.append(p.with_suffix(ext))

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

            # Fallback scan in output directory if hook didn't capture full name
            if not processed_files:
                for f in Path(self.output_dir).glob("*.*"):
                    if (
                        f.is_file()
                        and f.suffix.lower() in (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv")
                        and (time.time() - f.stat().st_mtime < 120 or f.stat().st_mtime >= start_time - 5)
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

            # Hide service files on Windows if created/updated
            if should_track_playlist:
                hide_file(out_path / "downloaded_archive.txt")
                hide_file(out_path / "stem_vid_map.json")
                hide_file(out_path / "playlist_order.txt")

            # If download failed, log to failed_downloads.txt in playlist folder
            if not success and self.last_error and not self.was_skipped:
                if should_track_playlist:
                    log_failed_download(
                        self.output_dir,
                        title=title or "Unknown Title",
                        author=author or "Unknown Artist",
                        url=url,
                        reason=self.last_error,
                    )

            return success, self.last_error, self.was_skipped
        except Exception as e:
            if success:
                return True, "", self.was_skipped
            return False, str(e), False
