import json
import os
import tempfile
import datetime
from pathlib import Path
from core.settings import get_app_data_dir

class PlaylistsManager:
    def __init__(self):
        self.file_path = get_app_data_dir() / 'playlists.json'
        self.playlists = self.load()

    def load(self) -> list[dict]:
        if self.file_path.exists():
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        # Validate: only keep entries with required fields
                        valid = []
                        for item in data:
                            if isinstance(item, dict) and item.get('url') and item.get('folder_path'):
                                if not item.get('format_compat'):
                                    try:
                                        from core.downloader import read_playlist_format
                                        fmt = read_playlist_format(item['folder_path'])
                                        item['format_compat'] = fmt or 'windows'
                                    except Exception:
                                        item['format_compat'] = 'windows'
                                valid.append(item)
                            else:
                                print(f"[PlaylistsManager] Skipping invalid playlist entry: {item}")
                        return valid
            except json.JSONDecodeError as e:
                print(f"Error loading playlists.json (corrupted): {e}")
                # Try to restore from backup
                backup = self.file_path.with_suffix('.tmp.json')
                if backup.exists():
                    try:
                        with open(backup, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            if isinstance(data, list):
                                return data
                    except Exception:
                        pass
                return []
            except Exception as e:
                print(f"Error loading playlists.json: {e}")
                return []
        return []

    def save(self) -> None:
        try:
            # Atomic write: write to temp file first, then rename to avoid corruption
            tmp_path = self.file_path.with_suffix('.tmp.json')
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.playlists, f, indent=4, ensure_ascii=False)
            tmp_path.replace(self.file_path)
        except Exception as e:
            print(f"Error saving playlists.json: {e}")

    def get_all(self) -> list[dict]:
        return list(self.playlists)

    def get_by_url(self, url: str) -> dict | None:
        for p in self.playlists:
            if p.get('url') == url:
                return p
        return None

    def add_playlist(
        self,
        url: str,
        title: str,
        folder_path: str,
        thumbnail: str = "",
        track_count: int = 0,
        media_type: str = "Audio",
        format_compat: str = "windows"
    ) -> dict:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # Check if already exists; if so, update
        for p in self.playlists:
            if p.get('url') == url:
                p['title'] = title or p.get('title', 'Playlist')
                p['folder_path'] = folder_path
                if thumbnail:
                    p['thumbnail'] = thumbnail
                p['track_count'] = track_count or p.get('track_count', 0)
                p['media_type'] = media_type
                if format_compat:
                    p['format_compat'] = format_compat
                p['last_synced'] = now_str
                self.save()
                if folder_path and format_compat:
                    try:
                        from core.downloader import write_playlist_format
                        write_playlist_format(folder_path, format_compat)
                    except Exception:
                        pass
                return p

        item = {
            'url': url,
            'title': title or 'Playlist',
            'folder_path': folder_path,
            'thumbnail': thumbnail,
            'track_count': track_count,
            'media_type': media_type,
            'format_compat': format_compat or 'windows',
            'last_synced': now_str
        }
        self.playlists.append(item)
        self.save()
        if folder_path and format_compat:
            try:
                from core.downloader import write_playlist_format
                write_playlist_format(folder_path, format_compat)
            except Exception:
                pass
        return item

    def remove_playlist(self, url: str) -> bool:
        initial_len = len(self.playlists)
        self.playlists = [p for p in self.playlists if p.get('url') != url]
        if len(self.playlists) != initial_len:
            self.save()
            return True
        return False

    def update_sync_info(self, url: str, track_count: int = None, status: str = None, new_tracks_count: int = None, unavailable_count: int = None, duplicates_count: int = None, removed_tracks_count: int = None, format_compat: str = None) -> None:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        for p in self.playlists:
            if p.get('url') == url:
                p['last_synced'] = now_str
                if track_count is not None:
                    p['track_count'] = track_count
                if status is not None:
                    p['status'] = status
                if format_compat is not None:
                    p['format_compat'] = format_compat
                    folder = p.get('folder_path')
                    if folder:
                        try:
                            from core.downloader import write_playlist_format
                            write_playlist_format(folder, format_compat)
                        except Exception:
                            pass
                if unavailable_count is not None:
                    p['unavailable_count'] = unavailable_count
                if duplicates_count is not None:
                    p['duplicates_count'] = duplicates_count
                if new_tracks_count is not None:
                    p['new_tracks_count'] = new_tracks_count
                elif status == 'synced':
                    p['new_tracks_count'] = 0
                if removed_tracks_count is not None:
                    p['removed_tracks_count'] = removed_tracks_count
                break
        self.save()

    def set_playlist_format(self, url: str, format_compat: str) -> None:
        for p in self.playlists:
            if p.get('url') == url:
                p['format_compat'] = format_compat
                folder = p.get('folder_path')
                if folder:
                    try:
                        from core.downloader import write_playlist_format
                        write_playlist_format(folder, format_compat)
                    except Exception:
                        pass
                self.save()
                break

    def reorder_playlists(self, ordered_urls: list[str]) -> None:
        url_map = {p.get('url'): p for p in self.playlists}
        new_list = []
        for u in ordered_urls:
            if u in url_map:
                new_list.append(url_map[u])
        for p in self.playlists:
            if p not in new_list:
                new_list.append(p)
        self.playlists = new_list
        self.save()

    def move_playlist(self, from_idx: int, to_idx: int) -> bool:
        if 0 <= from_idx < len(self.playlists) and 0 <= to_idx < len(self.playlists):
            item = self.playlists.pop(from_idx)
            self.playlists.insert(to_idx, item)
            self.save()
            return True
        return False

    def get_sorted(self, sort_by: str = "custom") -> list[dict]:
        items = list(self.playlists)
        if sort_by == "name_asc":
            items.sort(key=lambda x: (x.get('title') or '').lower())
        elif sort_by == "name_desc":
            items.sort(key=lambda x: (x.get('title') or '').lower(), reverse=True)
        elif sort_by == "tracks_desc":
            items.sort(key=lambda x: x.get('track_count', 0), reverse=True)
        elif sort_by == "tracks_asc":
            items.sort(key=lambda x: x.get('track_count', 0))
        elif sort_by == "synced_desc":
            items.sort(key=lambda x: x.get('last_synced') or '', reverse=True)
        elif sort_by == "format_win":
            def _win_key(x):
                fmt = (x.get('format_compat') or 'windows').lower()
                order = 0 if fmt in ('windows', 'win') else (1 if fmt in ('unix/win', 'mixed') else 2)
                return (order, (x.get('title') or '').lower())
            items.sort(key=_win_key)
        elif sort_by == "format_unix":
            def _unix_key(x):
                fmt = (x.get('format_compat') or 'windows').lower()
                order = 0 if fmt in ('unix', 'posix') else (1 if fmt in ('unix/win', 'mixed') else 2)
                return (order, (x.get('title') or '').lower())
            items.sort(key=_unix_key)
        return items

