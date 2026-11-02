import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from core.constants import AUDIO_EXTS, VIDEO_EXTS
from core.track_matching import (
    _author_and_title_match,
    clean_artist_name,
    clean_song_title,
    extract_significant_version_tags,
    translit_both_ways,
)


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

# ─── Playlist Persistence Helpers ─────────────────────────────────────────────

def read_raw_stem_vid_map(output_dir: Path | str) -> dict[str, str | dict]:
    """Read raw stem -> video_id (or dict with vid/original_vid) from stem_vid_map.json."""
    out = Path(output_dir)
    map_file = out / "stem_vid_map.json"
    if map_file.exists():
        try:
            raw = json.loads(map_file.read_text(encoding="utf-8"))
            valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".webm"}
            cleaned = {}
            for stem, val in raw.items():
                for ext in valid_exts:
                    p = out / f"{stem}{ext}"
                    try:
                        if p.exists() and p.stat().st_size > 100 * 1024:
                            cleaned[stem] = val
                            break
                    except Exception:
                        pass
            return cleaned
        except Exception:
            pass
    return {}


def read_stem_vid_map(output_dir: Path | str) -> dict[str, str]:
    """Read stem -> video_id mapping from stem_vid_map.json, keeping only existing files.
    Backwards-compatible: always returns a string ID (preferring original_vid if available)."""
    raw = read_raw_stem_vid_map(output_dir)
    res: dict[str, str] = {}
    for stem, val in raw.items():
        if isinstance(val, dict):
            vid = val.get("original_vid") or val.get("vid") or ""
            if vid:
                res[stem] = str(vid)
        elif isinstance(val, str) and val:
            res[stem] = val
    return res


def read_stem_all_vids_map(output_dir: Path | str) -> dict[str, set[str]]:
    """Return all video IDs (both original playlist ID and alternative download ID) mapped to each stem."""
    raw = read_raw_stem_vid_map(output_dir)
    res: dict[str, set[str]] = {}
    for stem, val in raw.items():
        vids = set()
        if isinstance(val, dict):
            if val.get("original_vid"):
                vids.add(str(val["original_vid"]).strip())
            if val.get("vid"):
                vids.add(str(val["vid"]).strip())
        elif isinstance(val, str) and val:
            vids.add(val.strip())
        if vids:
            res[stem] = vids
    return res


def update_stem_vid_map(output_dir: Path | str, stem: str, vid: str, original_vid: Optional[str] = None) -> None:
    """Record a track's stem (filename without extension) and video ID in stem_vid_map.json.
    Supports storing both candidate vid and original_vid for fallback/alternative downloads."""
    if not stem or (not vid and not original_vid):
        return
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    map_file = out / "stem_vid_map.json"
    unhide_file(map_file)
    data = read_raw_stem_vid_map(out)

    existing_entry = data.get(stem)
    if original_vid and vid and original_vid != vid:
        data[stem] = {"vid": vid, "original_vid": original_vid}
    elif isinstance(existing_entry, dict):
        if vid:
            existing_entry["vid"] = vid
        if original_vid:
            existing_entry["original_vid"] = original_vid
        data[stem] = existing_entry
    elif original_vid and not vid:
        data[stem] = original_vid
    else:
        data[stem] = vid

    try:
        map_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        hide_file(map_file)
    except Exception:
        pass


def read_kept_orphans(output_dir: Path | str) -> set[str]:
    """Read set of filenames/stems that user explicitly chose to keep despite not being in online playlist."""
    out = Path(output_dir)
    f = out / ".kept_orphans.json"
    if not f.exists():
        return set()
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(data, list):
            valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".mp4", ".mkv", ".webm"}
            kept = set()
            for s in data:
                # Keep if file physically exists
                if (out / s).exists() or any((out / f"{s}{ext}").exists() for ext in valid_exts):
                    kept.add(s)
            return kept
    except Exception:
        pass
    return set()


def add_kept_orphans(output_dir: Path | str, items: list[str] | set[str]) -> None:
    """Add filenames/stems to .kept_orphans.json."""
    if not items:
        return
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    f = out / ".kept_orphans.json"
    unhide_file(f)
    existing = read_kept_orphans(out)
    for it in items:
        stem = Path(it).stem
        existing.add(it)
        existing.add(stem)
    try:
        f.write_text(json.dumps(sorted(list(existing)), ensure_ascii=False, indent=2), encoding="utf-8")
        hide_file(f)
    except Exception:
        pass


def clear_kept_orphans(output_dir: Path | str) -> None:
    """Reset / clear .kept_orphans.json so files will be re-evaluated on next sync."""
    out = Path(output_dir)
    f = out / ".kept_orphans.json"
    if f.exists():
        try:
            unhide_file(f)
            f.unlink(missing_ok=True)
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


def is_file_already_downloaded(
    output_dir: Path | str,
    vid: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    is_audio: bool = True,
    stem_map: Optional[dict[str, str]] = None,
    local_stems: Optional[list[str]] = None,
    archive_ids: Optional[set[str]] = None,
) -> bool:
    """Instant local disk check: returns True in ~0.0001s if valid media file (>=500KB) already exists on disk."""
    out = Path(output_dir)
    if not out.exists():
        return False

    if is_audio:
        valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac"}
    else:
        valid_exts = {".mp4", ".mkv", ".webm", ".avi", ".mov"}

    if stem_map is None:
        stem_map = read_stem_vid_map(out)

    # 1. Fast check via video ID in stem_map (only if file exists on disk)
    if vid:
        for mapped_stem, mapped_vid in stem_map.items():
            if mapped_vid == vid:
                for ext in valid_exts:
                    if (out / f"{mapped_stem}{ext}").exists():
                        return True

    # 2. Check via strict Author & Title matching in filenames
    if title and len(title.strip()) >= 2:
        if local_stems is None:
            try:
                local_stems = [
                    f.stem for f in out.iterdir()
                    if f.is_file() and f.suffix.lower() in valid_exts and f.stat().st_size >= 500 * 1024
                ]
            except Exception:
                local_stems = []

        for stem in local_stems:
            if _author_and_title_match(stem, title, author):
                return True

    return False


def build_local_files_index(
    output_dir: Path | str,
    is_audio: bool = True,
    additional_files: Optional[list[Path | str]] = None,
    excluded_files: Optional[list[Path | str]] = None,
) -> tuple[set[str], dict[str, list[tuple[set[str], set[str], str]]], int]:
    """Build an in-memory inverted index for instant O(1) matching of online playlist entries.
    Returns:
        (combined_vid_set, title_index, valid_file_count)
    """
    out = Path(output_dir)
    if not out.exists():
        return set(), {}, 0

    if is_audio:
        valid_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac"}
    else:
        valid_exts = {".mp4", ".mkv", ".webm", ".avi", ".mov"}

    excluded = {Path(path) for path in (excluded_files or [])}
    local_files = []
    try:
        local_files = [
            f for f in out.iterdir()
            if f.is_file() and f.suffix.lower() in valid_exts and f not in excluded
        ]
    except Exception:
        pass

    for raw_path in additional_files or []:
        path = Path(raw_path)
        try:
            if path.is_file() and path not in excluded and path not in local_files:
                local_files.append(path)
        except Exception:
            pass

    stem_all_vids = read_stem_all_vids_map(out)

    # Only consider video IDs whose files are part of the effective local media set.
    verified_vids: set[str] = set()
    present_stems = {f.stem for f in local_files}
    for stem, vids in stem_all_vids.items():
        if stem in present_stems:
            verified_vids.update(vids)

    title_index: dict[str, list[tuple[set[str], set[str], str]]] = {}
    valid_file_count = 0

    try:
        for f in local_files:
            if f.stat().st_size >= 500 * 1024:
                valid_file_count += 1
                stem = f.stem
                parts = [p.strip() for p in re.split(r'\s+[-–—]\s*|\s*[-–—]\s+', stem) if p.strip()] if re.search(r'[-–—]', stem) else [stem]
                tags = extract_significant_version_tags(stem)

                candidates = []
                if len(parts) == 1:
                    candidates.append(("", parts[0]))
                elif len(parts) == 2:
                    candidates.append((parts[0], parts[1]))
                    candidates.append((parts[1], parts[0]))
                    candidates.append(("", stem))
                elif len(parts) >= 3:
                    candidates.append((parts[0], ' - '.join(parts[1:])))
                    candidates.append((parts[1], ' - '.join(parts[2:])))
                    candidates.append((' - '.join(parts[:-1]), parts[-1]))
                    candidates.append((parts[0] + ' ' + parts[1], ' - '.join(parts[2:])))
                    candidates.append(("", stem))

                lead_artist_clean = clean_artist_name(parts[0]) if parts else ""
                for cand_a_raw, cand_t_raw in candidates:
                    cand_a_clean = clean_artist_name(cand_a_raw)
                    cand_t_clean = clean_artist_name(cand_t_raw)
                    if cand_t_clean and (cand_t_clean == cand_a_clean or cand_t_clean == lead_artist_clean):
                        continue
                    cand_t_vars = translit_both_ways(clean_song_title(cand_t_raw, cand_a_raw))
                    cand_a_vars = translit_both_ways(clean_artist_name(cand_a_raw))
                    for tv in cand_t_vars:
                        if tv and tv != lead_artist_clean:
                            title_index.setdefault(tv, []).append((tags, cand_a_vars, stem))
    except Exception:
        pass

    return verified_vids, title_index, valid_file_count


def is_entry_in_index(
    vid: str,
    title: str,
    author: str,
    combined_vid_set: set[str],
    title_index: dict[str, list[tuple[set[str], set[str], str]]],
) -> bool:
    """O(1) lookup to check if an online track already exists locally."""
    # 1. Exact match via verified video ID
    if vid and vid in combined_vid_set:
        return True

    if not title or len(title.strip()) < 2:
        return False

    tags_online = extract_significant_version_tags(title)
    online_a_clean = clean_artist_name(author or "")
    online_a_vars = translit_both_ways(online_a_clean)
    generic = {'topic', 'release', 'variousartists', 'soundtrack', ''}

    title_candidates = [title]
    if re.search(r'\s+[-–—]\s+', title):
        t_parts = [p.strip() for p in re.split(r'\s+[-–—]\s+', title) if p.strip()]
        if len(t_parts) >= 2:
            for tp in [t_parts[-1], ' - '.join(t_parts[1:]), ' - '.join(t_parts[:-1]), t_parts[0]]:
                if clean_artist_name(tp) != online_a_clean:
                    title_candidates.append(tp)

    for raw_t in title_candidates:
        clean_t = clean_song_title(raw_t, author or "")
        if clean_t == online_a_clean:
            continue
        clean_t_vars = translit_both_ways(clean_t)
        for ctv in clean_t_vars:
            if not ctv or ctv == online_a_clean:
                continue
            if ctv in title_index:
                for file_tags, file_a_vars, raw_stem in title_index[ctv]:
                    if tags_online and tags_online != file_tags:
                        continue
                    if file_tags and not tags_online:
                        if any(t in {'remix', 'vip', 'extended', 'acoustic', 'instrumental', 'orchestral', 'live', 'dub', 'cover'} for t in file_tags):
                            continue
                    if not author or any(g in online_a_vars for g in generic):
                        if len(ctv) >= 5:
                            return True
                        continue
                    if online_a_vars & file_a_vars:
                        return True
                    for ca in online_a_vars:
                        for cda in file_a_vars:
                            if ca and cda and (ca in cda or cda in ca):
                                return True

                    if any(fa and len(fa) >= 3 and fa in clean_artist_name(title) for fa in file_a_vars):
                        return True

    return False


def detect_orphan_files_in_folder(
    output_dir: Path | str,
    entries: list[dict],
    is_audio: bool = True,
    additional_files: Optional[list[Path | str]] = None,
    excluded_files: Optional[list[Path | str]] = None,
) -> list[dict]:
    """Identifies local audio/video files that were previously downloaded but are no longer present in the online playlist."""
    out = Path(output_dir)
    if not out.exists() or not out.is_dir():
        return []

    valid_exts = AUDIO_EXTS if is_audio else VIDEO_EXTS
    combined_vid_set, title_index, valid_cnt = build_local_files_index(
        out,
        is_audio=is_audio,
        additional_files=additional_files,
        excluded_files=excluded_files,
    )
    if valid_cnt == 0:
        return []

    kept_items = read_kept_orphans(out)
    stem_all_vids = read_stem_all_vids_map(out)
    stem_map = read_stem_vid_map(out)
    vid_to_stems: dict[str, list[str]] = {}
    for s, vids in stem_all_vids.items():
        for v in vids:
            vid_to_stems.setdefault(v, []).append(s)

    claimed_stems = set()
    generic = {'topic', 'release', 'variousartists', 'soundtrack', 'records', 'music', 'official', ''}

    for entry in entries:
        t = entry.get('title') or ''
        if not t or t in ('[Deleted video]', '[Private video]', 'None', 'Unknown') or entry.get('is_unavailable') or 'unavailable / deleted' in str(t).lower():
            continue

        vid = entry.get('id')
        if not vid:
            u = entry.get('url', '')
            if 'v=' in u: vid = u.split('v=')[-1].split('&')[0]
            elif 'youtu.be/' in u: vid = u.split('youtu.be/')[-1].split('?')[0]

        if vid and vid in vid_to_stems:
            for s in vid_to_stems[vid]:
                claimed_stems.add(s)
            continue

        author = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ''
        tags_online = extract_significant_version_tags(t)

        parts = [p.strip() for p in re.split(r'\s+[-–—]\s*|\s*[-–—]\s+', t) if p.strip()] if re.search(r'[-–—]', t) else [t]
        candidates = []
        if len(parts) == 1:
            candidates.append((author, parts[0]))
        elif len(parts) == 2:
            candidates.append((parts[0], parts[1]))
            candidates.append((parts[1], parts[0]))
            candidates.append((author, t))
        elif len(parts) >= 3:
            candidates.append((parts[0], ' - '.join(parts[1:])))
            candidates.append((parts[1], ' - '.join(parts[2:])))
            candidates.append((' - '.join(parts[:-1]), parts[-1]))
            candidates.append((parts[0] + ' ' + parts[1], ' - '.join(parts[2:])))
            candidates.append((author, t))

        entry_matched = False
        for cand_a, cand_t in candidates:
            if entry_matched:
                break
            online_a_vars = translit_both_ways(clean_artist_name(cand_a))
            clean_t_vars = translit_both_ways(clean_song_title(cand_t, cand_a))
            for ctv in clean_t_vars:
                if entry_matched:
                    break
                if ctv in title_index:
                    for file_tags, file_a_vars, raw_stem in title_index[ctv]:
                        if tags_online and tags_online != file_tags:
                            continue
                        if file_tags and not tags_online:
                            if any(tag in {'remix', 'vip', 'extended', 'acoustic', 'instrumental', 'orchestral', 'live', 'dub', 'cover'} for tag in file_tags):
                                continue

                        # Match condition:
                        # 1. Author match or generic publisher
                        if not cand_a or any(g in online_a_vars for g in generic) or (online_a_vars & file_a_vars):
                            claimed_stems.add(raw_stem)
                            entry_matched = True
                            break

                        # 2. Substring author match
                        match_sub = False
                        for ca in online_a_vars:
                            for cda in file_a_vars:
                                if ca and cda and (ca in cda or cda in ca):
                                    claimed_stems.add(raw_stem)
                                    entry_matched = True
                                    match_sub = True
                                    break
                            if match_sub:
                                break
                        if entry_matched:
                            break

                        # 3. High confidence title match (length >= 8, or unique title)
                        if len(ctv) >= 8 and len(title_index[ctv]) == 1:
                            claimed_stems.add(raw_stem)
                            entry_matched = True
                            break

    orphan_items = []
    excluded = {Path(path) for path in (excluded_files or [])}
    candidate_files = [
        f for f in out.iterdir()
        if f.is_file() and f.suffix.lower() in valid_exts and f not in excluded
    ]
    for raw_path in additional_files or []:
        path = Path(raw_path)
        if path not in excluded and path not in candidate_files:
            candidate_files.append(path)

    for f in candidate_files:
        if f.is_file() and f.stat().st_size >= 500 * 1024:
            stem = f.stem
            if f.name in kept_items or stem in kept_items:
                continue
            if stem not in claimed_stems:
                vid = stem_map.get(stem)
                url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
                orphan_items.append({
                    'filename': f.name,
                    'vid': vid or 'Local Copy',
                    'url': url,
                    'title': stem,
                    'filepath': str(f)
                })

    return orphan_items
