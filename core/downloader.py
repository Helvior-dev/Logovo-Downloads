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
    from mutagen.id3 import APIC, ID3, TALB, TIT2, TPE1, TRCK
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggopus import OggOpus
except ImportError:
    FLAC, Picture = None, None
    ID3, APIC, TALB, TIT2, TPE1, TRCK = None, None, None, None, None, None
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


def clean_media_url(url: str) -> str:
    """Clean tracking params and normalize music.youtube.com to youtube.com to prevent 403 Forbidden."""
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
            if "list" in params:
                clean_params["list"] = params["list"]
            if "t" in params:
                clean_params["t"] = params["t"]
            if clean_params:
                new_query = urllib.parse.urlencode(clean_params, doseq=True)
                return urllib.parse.urlunparse(parsed._replace(query=new_query))
        except Exception:
            pass
    return url


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent.parent


def get_ffmpeg_path() -> Optional[str]:
    local_ffmpeg = get_base_dir() / "ffmpeg.exe"
    if local_ffmpeg.exists():
        return str(local_ffmpeg)
    return None


FFMPEG_PATH = get_ffmpeg_path()


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


def set_folder_icon(folder_path: Path | str, image_source: Any) -> bool:
    """
    Sets the Windows folder icon from an image URL, PIL Image, or local image file.
    Creates desktop.ini and folder_icon.ico with system & hidden attributes.
    """
    if sys.platform != "win32":
        return False
    if not image_source:
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
    if not image_source:
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
    if not image_source or mode == "none":
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
    """Write the ordered list of filenames in playlist_order.txt."""
    if not file_names:
        return
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


def reindex_existing_playlist_files(output_dir: Path | str, entries: list[dict]) -> None:
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
            try:
                if ext == ".mp3":
                    fix_mp3_tags(target_file, track_num=track_num, total_tracks=count, album=out.name)
                elif ext == ".flac":
                    fix_flac_tags(target_file, track_num=track_num, total_tracks=count, album=out.name)
                elif ext in (".opus", ".ogg"):
                    fix_opus_tags(target_file, track_num=track_num, total_tracks=count, album=out.name)
                elif ext in (".m4a", ".aac", ".alac"):
                    fix_m4a_tags(target_file, track_num=track_num, total_tracks=count, album=out.name)

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
) -> None:
    if ID3 is None:
        return
    try:
        tags = ID3(path)
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

    if changed:
        try:
            tags.save(v2_version=3)
        except Exception:
            pass


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
            changed = True
        except Exception:
            new_pictures.append(pic)

    if changed:
        try:
            audio.clear_pictures()
            for p in new_pictures:
                audio.add_picture(p)
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

    if changed:
        try:
            audio.save()
        except Exception:
            pass


def parse_speed_limit(limit_str: Optional[str]) -> Optional[int]:
    """Convert '5 MB/s', '10 MB/s', '500 KB/s', etc. to bytes per second."""
    if not limit_str or str(limit_str).lower() in ("unlimited", "none", "0"):
        return None
    s = str(limit_str).upper().replace("/S", "").replace("S", "").strip()
    if "MB" in s:
        try:
            return int(float(s.replace("MB", "").strip()) * 1024 * 1024)
        except ValueError:
            pass
    elif "KB" in s:
        try:
            return int(float(s.replace("KB", "").strip()) * 1024)
        except ValueError:
            pass
    elif "GB" in s:
        try:
            return int(float(s.replace("GB", "").strip()) * 1024 * 1024 * 1024)
        except ValueError:
            pass
    return None


def postprocess_audio_file(
    file_path: Path | str,
    playlist_index: Optional[int] = None,
    playlist_count: Optional[int] = None,
    album: Optional[str] = None,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    naming_pattern: Optional[str] = None,
) -> Path:
    """Apply cover cropping, tag fixing, and optional custom renaming to a downloaded audio file."""
    path = Path(file_path)
    if not path.exists():
        return path

    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            fix_mp3_cover(path)
            fix_mp3_tags(path, track_num=playlist_index, total_tracks=playlist_count, album=album, artist=artist)
        elif ext == ".flac":
            fix_flac_cover(path)
            fix_flac_tags(path, track_num=playlist_index, total_tracks=playlist_count, album=album, artist=artist)
        elif ext in (".opus", ".ogg"):
            fix_opus_cover(path)
            fix_opus_tags(path, track_num=playlist_index, total_tracks=playlist_count, album=album, artist=artist)
        elif ext in (".m4a", ".aac", ".alac"):
            fix_m4a_cover(path)
            fix_m4a_tags(path, track_num=playlist_index, total_tracks=playlist_count, album=album)

        # Apply custom naming pattern if specified
        if naming_pattern and naming_pattern.strip():
            pat = naming_pattern.strip()
            safe_artist = artist or ""
            safe_title = title or path.stem
            safe_idx = f"{playlist_index:02d}" if playlist_index is not None else ""
            safe_album = album or ""
            
            new_stem = pat
            new_stem = new_stem.replace("{artist}", safe_artist)
            new_stem = new_stem.replace("{title}", safe_title)
            new_stem = new_stem.replace("{index}", safe_idx)
            new_stem = new_stem.replace("{album}", safe_album)
            
            for ch in r'\/:*?"<>|':
                new_stem = new_stem.replace(ch, "_")
            new_stem = new_stem.strip(" -._")
            if new_stem:
                new_path = path.parent / f"{new_stem}{path.suffix}"
                if new_path != path and not new_path.exists():
                    path = path.rename(new_path)

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

        # Client strategies for in-flight rotation if YouTube throws transient 403
        client_rotations = [
            ["android", "web"],
            ["ios", "web"],
            ["mweb", "android"],
            ["web", "default"],
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
                    "player_client": ["android", "web"],
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
            nonlocal extracted_vid, extracted_thumb, extracted_artist, extracted_title
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
                stem = Path(fn).stem if fn else ""
                if should_track_playlist and stem and extracted_vid:
                    update_stem_vid_map(self.output_dir, stem, extracted_vid)
            if progress_callback:
                progress_callback(d)

        def internal_postprocessor_hook(d: dict) -> None:
            nonlocal extracted_vid, extracted_thumb, extracted_artist, extracted_title
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
                stem = Path(fp).stem if fp else ""
                if should_track_playlist and stem and extracted_vid:
                    update_stem_vid_map(self.output_dir, stem, extracted_vid)

        ydl_opts["progress_hooks"] = [internal_progress_hook]
        ydl_opts["postprocessor_hooks"] = [internal_postprocessor_hook]

        # Postprocessors setup
        if is_audio:
            ydl_opts["format"] = "bestaudio/best"
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
            if "H.264" in media_type:
                ydl_opts["format"] = "bestvideo[vcodec^=avc]+bestaudio/best"
                ydl_opts["merge_output_format"] = "mp4"
            elif "H.265" in media_type:
                ydl_opts["format"] = "bestvideo[vcodec^=hev]+bestaudio/best"
                ydl_opts["merge_output_format"] = "mkv"
            else:
                ydl_opts["format"] = self._map_quality(quality)
                ydl_opts["merge_output_format"] = "mp4"

            ydl_opts["postprocessors"] = [
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail"},
            ]
            if subtitles and subtitles.get("download"):
                ydl_opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle"})

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

                # If 403 occurred, rotate client strategy and retry silently
                if ("403" in self.last_error or "forbidden" in self.last_error.lower()) and attempt < max_attempts - 1:
                    time.sleep(1.0 + 0.5 * attempt)
                    continue
                else:
                    break
            except Exception as e:
                self.last_error = str(e)
                if ("403" in str(e) or "forbidden" in str(e).lower()) and attempt < max_attempts - 1:
                    time.sleep(1.0 + 0.5 * attempt)
                    continue
                break

        if not success and not self.last_error:
            self.last_error = "Unknown error occurred."

        try:
            # Post-process audio files: crop covers to 1000x1000 square & fix tags for Windows Explorer
            processed_files: list[Path] = []
            for fp in list(downloaded_files):
                p = Path(fp)
                target_paths = [p]
                for ext in (".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv"):
                    target_paths.append(p.with_suffix(ext))

                for candidate in target_paths:
                    if candidate.exists() and candidate.is_file() and candidate not in processed_files:
                        if is_audio:
                            postprocess_audio_file(
                                candidate,
                                playlist_index=playlist_index,
                                playlist_count=playlist_count,
                                album=os.path.basename(self.output_dir) if playlist_count else None,
                                artist=extracted_artist or author,
                                title=extracted_title or title,
                                naming_pattern=naming_pattern,
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
                            postprocess_audio_file(
                                f,
                                playlist_index=playlist_index,
                                playlist_count=playlist_count,
                                album=os.path.basename(self.output_dir) if playlist_count else None,
                                artist=extracted_artist or author,
                                title=extracted_title or title,
                                naming_pattern=naming_pattern,
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

            # Ensure playlist cover/icon is applied if downloading a playlist/album
            if should_track_playlist or playlist_count:
                cover_mode = self.settings.get('playlist_cover_mode', 'both')
                if cover_mode != 'none':
                    ico_exists = (out_path / "folder_icon.ico").exists()
                    img_exists = (out_path / "cover.jpg").exists() or (out_path / "cover.png").exists()
                    if (not ico_exists or not img_exists) and (extracted_thumb or processed_files):
                        thumb_src = extracted_thumb or (processed_files[0] if processed_files else None)
                        if thumb_src:
                            apply_playlist_cover_settings(self.output_dir, thumb_src, mode=cover_mode)

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
            print(f"Download postprocessing error: {e}")
            if not self.was_skipped and should_track_playlist:
                log_failed_download(
                    self.output_dir,
                    title=title or "Unknown Title",
                    author=author or "Unknown Artist",
                    url=url,
                    reason=str(e),
                )
            return False, str(e), False
