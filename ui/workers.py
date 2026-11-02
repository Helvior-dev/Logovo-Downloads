import os
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.constants import MEDIA_EXTS
from core.diagnostics import run_network_diagnostics, run_self_diagnostics
from core.downloader import (
    MediaDownloader,
    apply_playlist_cover_settings,
    apply_cleanup_plan,
    build_local_files_index,
    detect_online_playlist_duplicates,
    detect_orphan_files_in_folder,
    detect_platform_name,
    ensure_nomedia_file,
    is_entry_in_index,
    plan_cleanup_orphan_files,
    reindex_existing_playlist_files,
    restore_dates_from_order,
)
from core.playlist_autoheal import apply_autoheal_pairs, plan_autoheal_orphans_and_missing
from core.playlist_index import add_kept_orphans, clear_kept_orphans
from core.preview import get_video_preview


class DownloadSettingsOverlay:
    """Read saved per-download settings first and fall back to current settings."""

    def __init__(self, current_settings, saved_settings: dict):
        self.current_settings = current_settings
        self.saved_settings = saved_settings if isinstance(saved_settings, dict) else {}

    def get(self, key, default=None):
        if key in self.saved_settings:
            return self.saved_settings[key]
        if self.current_settings is not None:
            return self.current_settings.get(key, default)
        return default


class WorkerThread(QThread):
    progress_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool, str, bool, bool)

    def __init__(
        self,
        url,
        media_type,
        output_dir,
        quality,
        cookies,
        subtitles,
        playlist_index=None,
        playlist_count=None,
        title=None,
        author=None,
        speed_limit=None,
        naming_pattern=None,
        settings=None,
        thumbnail=None,
        format_compat=None,
    ):
        super().__init__()
        self.url = url
        self.media_type = media_type
        self.output_dir = output_dir
        self.quality = quality
        self.cookies = cookies
        self.subtitles = subtitles
        self.playlist_index = playlist_index
        self.playlist_count = playlist_count
        self.title = title
        self.author = author
        self.speed_limit = speed_limit
        self.naming_pattern = naming_pattern
        self.settings = settings
        self.thumbnail = thumbnail
        self.format_compat = format_compat

    def run(self):
        downloader = MediaDownloader(output_dir=self.output_dir, settings=self.settings, format_compat=self.format_compat)

        def progress_callback(*args, **kwargs):
            if args and isinstance(args[0], dict):
                d = args[0]
            else:
                pct = args[0] if len(args) > 0 else 100.0
                status_txt = args[1] if len(args) > 1 else ""
                speed = args[2] if len(args) > 2 else ""
                eta = args[3] if len(args) > 3 else ""
                d = {
                    "status": "downloading" if pct < 100 else "finished",
                    "_percent_str": f"{pct:.1f}%",
                    "_speed_str": speed,
                    "_eta_str": eta,
                    "status_text": status_txt,
                }
            self.progress_signal.emit(d)

        success, error_msg, was_skipped = downloader.download(
            self.url,
            media_type=self.media_type,
            quality=self.quality,
            cookies=self.cookies,
            subtitles=self.subtitles,
            progress_callback=progress_callback,
            playlist_index=self.playlist_index,
            playlist_count=self.playlist_count,
            title=self.title,
            author=self.author,
            speed_limit=self.speed_limit,
            naming_pattern=self.naming_pattern,
            thumbnail=self.thumbnail,
            format_compat=self.format_compat,
            cancel_check=self.isInterruptionRequested,
        )
        self.finished_signal.emit(success, error_msg, was_skipped, downloader.was_cancelled)


class SelfDiagnosticsWorker(QThread):
    finished_signal = pyqtSignal(object)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def run(self):
        try:
            self.finished_signal.emit(run_self_diagnostics(self.settings))
        except Exception as exc:
            self.finished_signal.emit([{
                "name": "Self-diagnostics",
                "status": "FAIL",
                "details": f"Diagnostics could not complete: {exc}",
            }])


class NetworkDiagnosticsWorker(QThread):
    finished_signal = pyqtSignal(object)

    def run(self):
        try:
            self.finished_signal.emit(run_network_diagnostics())
        except Exception as exc:
            self.finished_signal.emit([{
                "name": "Network diagnostics",
                "status": "FAIL",
                "details": f"Network check could not complete: {exc}",
            }])


class FetchPreviewWorker(QThread):
    finished_signal = pyqtSignal(dict, object)
    error_signal = pyqtSignal(str, object)

    def __init__(self, url, context=None, cookies=None):
        super().__init__()
        self.url = url
        self.context = context
        self.cookies = cookies

    def run(self):
        try:
            preview = get_video_preview(self.url, cookies=self.cookies)
            if preview:
                self.finished_signal.emit(preview, self.context)
            else:
                platform = detect_platform_name(self.url)
                self.error_signal.emit(f"Could not fetch media metadata from {platform}.", self.context)
        except Exception as e:
            self.error_signal.emit(str(e), self.context)


class CheckAppUpdateWorker(QThread):
    finished_signal = pyqtSignal(bool, str, str, str)  # has_update, latest_ver, release_url, release_notes

    def __init__(self, current_ver: str, repo: str = "Helvior-dev/Logovo-Downloads"):
        super().__init__()
        self.current_ver = current_ver
        self.repo = repo

    def run(self):
        import requests
        import re
        try:
            headers = {
                "User-Agent": f"Logovo-Downloads/{self.current_ver}",
                "Accept": "application/vnd.github.v3+json"
            }
            url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            r = requests.get(url, headers=headers, timeout=6)
            if r.status_code == 200:
                data = r.json()
                tag = data.get("tag_name", "")
                rel_url = data.get("html_url", f"https://github.com/{self.repo}/releases/latest")
                body = data.get("body", "") or ""

                def parse_v(v_str):
                    clean = str(v_str).lstrip("v").strip()
                    parts = [int(p) for p in re.findall(r"\d+", clean)]
                    return parts or [0]

                has_update = parse_v(tag) > parse_v(self.current_ver)
                clean_tag = tag.lstrip("v")
                self.finished_signal.emit(has_update, clean_tag, rel_url, body)
            else:
                self.finished_signal.emit(False, "", "", "")
        except Exception:
            self.finished_signal.emit(False, "", "", "")


class StartupPlaylistCheckWorker(QThread):
    finished_signal = pyqtSignal()

    def __init__(self, playlists_mgr, cookies=None):
        super().__init__()
        self.playlists_mgr = playlists_mgr
        self.cookies = cookies

    def run(self):
        from core.logger import get_logger
        logger = get_logger("logovo.startup_check")
        try:
            valid_media_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac", ".mp4", ".mkv", ".webm"}
            items = self.playlists_mgr.get_all()
            for p in items:
                out_dir = p.get('folder_path')
                url = p.get('url')
                if not out_dir or not url or not os.path.exists(out_dir):
                    continue

                preview = get_video_preview(url, cookies=self.cookies)
                if not preview or not preview.get('entries'):
                    continue

                is_audio = (p.get('media_type', 'Audio') == 'Audio')
                combined_vid_set, title_index, local_cnt = build_local_files_index(out_dir, is_audio=is_audio)

                missing_cnt = 0
                for entry in preview.get('entries', []):
                    if entry.get('is_unavailable') or "unavailable / deleted" in str(entry.get('title', '')).lower():
                        continue
                    vid = entry.get('url', '').split('v=')[-1].split('&')[0]
                    author = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ""
                    title = entry.get('title') or ""

                    already = is_entry_in_index(vid, title, author, combined_vid_set, title_index)
                    if not already:
                        missing_cnt += 1

                dupes = detect_online_playlist_duplicates(preview.get('entries', []))
                dupes_cnt = len(dupes)
                unavail_cnt = sum(1 for entry in preview.get('entries', []) if entry.get('is_unavailable') or "unavailable / deleted" in str(entry.get('title', '')).lower())
                total_cnt = preview.get('count', 0)
                orphans = detect_orphan_files_in_folder(out_dir, preview.get('entries', []), is_audio=is_audio)
                orphans_cnt = len(orphans)

                p['unavailable_count'] = unavail_cnt
                p['duplicates_count'] = dupes_cnt
                p['track_count'] = total_cnt
                p['new_tracks_count'] = missing_cnt
                p['removed_tracks_count'] = orphans_cnt

            self.playlists_mgr.save()
            self.finished_signal.emit()
        except Exception as e:
            try:
                from core.logger import get_logger
                get_logger("logovo.startup_check").exception("StartupPlaylistCheckWorker failed: %s", e)
            except Exception:
                pass


@dataclass
class PlaylistSyncPlan:
    preview: dict
    playlist: dict
    analysis: dict
    cleanup_actions: list[dict]
    format_compat: str | None
    playlist_format_update: str | None
    redownload_from_scratch: bool
    redownload_files: list[str]

    @property
    def missing_entries(self):
        return self.analysis["missing_entries"]

    @property
    def local_count(self):
        return self.analysis["local_count"]

    @property
    def online_duplicates(self):
        return self.analysis["online_duplicates"]

    @property
    def unavailable_entries(self):
        return self.analysis["unavailable_entries"]

    @property
    def orphaned_files(self):
        return self.analysis["orphaned_files"]

    @property
    def autoheal_pairs(self):
        return self.analysis["autoheal_pairs"]


def _analyze_playlist_sync(
    preview: dict,
    playlist: dict,
    settings,
    format_compat: str | None,
    *,
    additional_files=None,
    excluded_files=None,
    ignore_local: bool = False,
) -> dict:
    out_dir = playlist.get("folder_path")
    media_type_category = playlist.get("media_type", "Audio")
    is_audio = media_type_category == "Audio"
    entries = [dict(entry) for entry in preview.get("entries", [])]
    count = preview.get("count") or len(entries)
    missing_entries = []
    unavailable_entries = []

    for index, entry in enumerate(entries):
        entry["playlist_output_dir"] = out_dir
        entry["playlist_index"] = count - index
        entry["playlist_count"] = count
        entry["media_type_category"] = media_type_category
        entry["media_type"] = "Audio (Best)" if is_audio else "Video (Best)"
        if format_compat:
            entry["format_compat"] = format_compat

    if ignore_local:
        combined_vid_set, title_index, local_count = set(), {}, 0
        raw_orphaned_files = []
    else:
        combined_vid_set, title_index, local_count = build_local_files_index(
            out_dir,
            is_audio=is_audio,
            additional_files=additional_files,
            excluded_files=excluded_files,
        )
        raw_orphaned_files = detect_orphan_files_in_folder(
            out_dir,
            entries,
            is_audio=is_audio,
            additional_files=additional_files,
            excluded_files=excluded_files,
        )

    for entry in entries:
        title = entry.get("title") or ""
        if entry.get("is_unavailable") or "unavailable / deleted" in str(title).lower():
            unavailable_entries.append((entry, "Removed from online platform / Copyright Claim"))
            continue

        url = entry.get("url", "")
        vid = entry.get("id") or ""
        if not vid and "v=" in url:
            vid = url.split("v=")[-1].split("&")[0]
        elif not vid and "youtu.be/" in url:
            vid = url.split("youtu.be/")[-1].split("?", 1)[0]
        author = entry.get("uploader") or entry.get("channel") or entry.get("artist") or ""
        if not is_entry_in_index(vid, title, author, combined_vid_set, title_index):
            missing_entries.append(entry)

    raw_missing_entries = missing_entries
    online_duplicates = detect_online_playlist_duplicates(entries)
    orphaned_files, missing_entries, autoheal_pairs = plan_autoheal_orphans_and_missing(
        raw_orphaned_files,
        raw_missing_entries,
    )
    return {
        "entries": entries,
        "raw_missing_entries": raw_missing_entries,
        "raw_orphaned_files": raw_orphaned_files,
        "missing_entries": missing_entries,
        "orphaned_files": orphaned_files,
        "autoheal_pairs": autoheal_pairs,
        "local_count": local_count,
        "online_duplicates": online_duplicates,
        "unavailable_entries": unavailable_entries,
        "count": count,
    }


class SyncPlaylistWorker(QThread):
    finished_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str, dict)

    def __init__(
        self,
        p_dict: dict,
        settings,
        cookies=None,
        format_compat: str = None,
        playlist_format_update: str = None,
        redownload_from_scratch: bool = False,
    ):
        super().__init__()
        self.p_dict = p_dict
        self.settings = settings
        self.cookies = cookies
        self.format_compat = format_compat
        self.playlist_format_update = playlist_format_update
        self.redownload_from_scratch = redownload_from_scratch

    def run(self):
        try:
            url = self.p_dict.get("url")
            out_dir = Path(self.p_dict.get("folder_path", ""))
            media_type_category = self.p_dict.get("media_type", "Audio")

            preview = get_video_preview(url, cookies=self.cookies)
            if not preview or not preview.get("is_playlist"):
                platform = detect_platform_name(url)
                self.error_signal.emit(f"Invalid playlist response from {platform}.", self.p_dict)
                return

            redownload_files = []
            if self.redownload_from_scratch and out_dir.is_dir():
                redownload_files = [
                    item.name for item in out_dir.iterdir()
                    if item.is_file() and (
                        item.suffix.lower() in MEDIA_EXTS
                        or item.suffix.lower() in (".lrc", ".vtt", ".srt")
                    )
                ]

            cleanup_actions = plan_cleanup_orphan_files(
                out_dir,
                is_audio_playlist=(media_type_category == "Audio"),
            )
            if self.redownload_from_scratch:
                redownload_names = set(redownload_files)
                cleanup_actions = [
                    action for action in cleanup_actions
                    if action["path"].name not in redownload_names
                ]

            additional_files = []
            excluded_files = []
            if not self.redownload_from_scratch:
                additional_files = [
                    item["path"] for item in cleanup_actions
                    if item["action"] == "convert_to_audio"
                ]
                excluded_files = [
                    item["path"] for item in cleanup_actions
                    if item["action"] == "delete"
                ]

            analysis = _analyze_playlist_sync(
                preview,
                self.p_dict,
                self.settings,
                self.format_compat,
                additional_files=additional_files,
                excluded_files=excluded_files,
                ignore_local=self.redownload_from_scratch,
            )

            self.finished_signal.emit(PlaylistSyncPlan(
                preview=preview,
                playlist=dict(self.p_dict),
                analysis=analysis,
                cleanup_actions=cleanup_actions,
                format_compat=self.format_compat,
                playlist_format_update=self.playlist_format_update,
                redownload_from_scratch=self.redownload_from_scratch,
                redownload_files=redownload_files,
            ))
        except Exception as e:
            self.error_signal.emit(str(e), self.p_dict)


class ApplyPlaylistSyncWorker(QThread):
    finished_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str, dict)

    def __init__(self, plan: PlaylistSyncPlan, selected_orphans: list[str], settings):
        super().__init__()
        self.plan = plan
        self.selected_orphans = set(selected_orphans)
        self.settings = settings

    def run(self):
        try:
            out_dir = Path(self.plan.playlist["folder_path"])
            out_dir.mkdir(parents=True, exist_ok=True)

            if self.plan.redownload_from_scratch:
                for filename in self.plan.redownload_files:
                    try:
                        (out_dir / filename).unlink(missing_ok=True)
                    except Exception:
                        pass
                clear_kept_orphans(out_dir)

            is_audio = self.plan.playlist.get("media_type", "Audio") == "Audio"
            apply_cleanup_plan(self.plan.cleanup_actions)

            cover_mode = self.settings.get("playlist_cover_mode", "both") if self.settings else "both"
            if self.plan.preview.get("thumbnail") and cover_mode != "none":
                apply_playlist_cover_settings(
                    out_dir,
                    self.plan.preview["thumbnail"],
                    mode=cover_mode,
                )
            if self.settings and self.settings.get("create_nomedia_file", False):
                ensure_nomedia_file(out_dir)
            restore_dates_from_order(out_dir)

            conversion_names = {
                Path(item["path"]).name
                for item in self.plan.cleanup_actions
                if item["action"] == "convert_to_audio"
            }
            deleted_files = []
            delete_failures = []
            for filename in self.selected_orphans:
                path = out_dir / filename
                if not path.exists() and filename in conversion_names:
                    path = path.with_suffix(".mp3")
                if not path.exists():
                    continue
                try:
                    path.unlink()
                    deleted_files.append(path.name)
                except Exception:
                    if path.exists():
                        delete_failures.append(path.name)

            analysis = _analyze_playlist_sync(
                self.plan.preview,
                self.plan.playlist,
                self.settings,
                self.plan.format_compat,
            )

            orphaned_files, missing_entries, autoheal_pairs = plan_autoheal_orphans_and_missing(
                analysis["raw_orphaned_files"],
                analysis["raw_missing_entries"],
            )
            kept_names = [item.get("filename") for item in orphaned_files if item.get("filename")]
            kept_names.extend(delete_failures)
            if kept_names:
                add_kept_orphans(out_dir, kept_names)
            apply_autoheal_pairs(out_dir, autoheal_pairs)

            reindex_existing_playlist_files(
                out_dir,
                analysis["entries"],
                settings=self.settings,
            )
            _, _, local_count = build_local_files_index(out_dir, is_audio=is_audio)

            self.finished_signal.emit({
                "plan": self.plan,
                "preview": self.plan.preview,
                "playlist": self.plan.playlist,
                "missing_entries": missing_entries,
                "local_count": local_count,
                "online_duplicates": analysis["online_duplicates"],
                "unavailable_entries": analysis["unavailable_entries"],
                "deleted_files": deleted_files,
                "delete_failures": delete_failures,
                "count": analysis["count"],
            })
        except Exception as e:
            self.error_signal.emit(str(e), self.plan.playlist)


class ReindexPlaylistWorker(QThread):
    finished_signal = pyqtSignal(dict, int)
    error_signal = pyqtSignal(str)

    def __init__(self, p_dict: dict, settings, cookies=None):
        super().__init__()
        self.p_dict = p_dict
        self.settings = settings
        self.cookies = cookies

    def run(self):
        try:
            url = self.p_dict.get('url')
            out_dir = self.p_dict.get('folder_path')
            preview = get_video_preview(url, cookies=self.cookies)
            if not preview or not preview.get('is_playlist'):
                platform = detect_platform_name(url)
                self.error_signal.emit(f"Could not load playlist from {platform}.")
                return
            entries = preview.get('entries', [])
            reindex_existing_playlist_files(out_dir, entries, settings=self.settings)
            self.finished_signal.emit(self.p_dict, len(entries))
        except Exception as e:
            self.error_signal.emit(str(e))
