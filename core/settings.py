import os
import json
from pathlib import Path

APP_NAME = "Logovo-Downloads"

def get_app_data_dir() -> Path:
    app_data = Path(os.getenv('APPDATA', Path.home() / '.config'))
    new_dir = app_data / "Logovo-Dushnil" / "Logovo-Downloads"
    new_dir.mkdir(parents=True, exist_ok=True)

    # Seamlessly migrate existing data from old AppData directories if present
    old_dirs = [
        app_data / "LogovoDownloads",
        app_data / "Logovo-Downloads",
        app_data / "Logovo-Dushnil" / "LogovoDownloads"
    ]
    for old_dir in old_dirs:
        if old_dir.exists() and old_dir.is_dir() and old_dir != new_dir:
            for fname in ("settings.json", "playlists.json", "history.json", "app_logs.txt", "cookies.txt", "failed_downloads.txt", "downloaded_archive.txt"):
                old_f = old_dir / fname
                new_f = new_dir / fname
                if old_f.exists() and not new_f.exists():
                    try:
                        import shutil
                        shutil.copy2(old_f, new_f)
                    except Exception:
                        pass
    return new_dir

class SettingsManager:
    def __init__(self):
        self.settings_file = get_app_data_dir() / 'settings.json'
        self.default_settings = {
            'ui_theme': 'green',
            'download_path': str(Path.home() / 'Downloads'),
            'download_subtitles': False,
            'subtitles_langs': 'orig', # 'orig', 'all', 'en', 'ru', 'uk'
            'playlist_cover_mode': 'both', # 'both', 'icon', 'file', 'none'
            'max_concurrent_downloads': 3, # 1 to 6
            'naming_pattern': '{artist} - {title}', # e.g. '{artist} - {title}', '{index}. {artist} - {title}'
            'speed_limit': 'Unlimited', # 'Unlimited', '1 MB/s', '3 MB/s', '5 MB/s', '10 MB/s', '20 MB/s'
            'playlist_sort_mode': 'custom', # 'custom', 'name_asc', 'name_desc', 'tracks_desc', 'tracks_asc', 'synced_desc'
            'filename_compat': 'Windows (Original)', # 'Windows (Original)' or 'UNIX / POSIX / MTP'
            'create_nomedia_file': False, # Whether to create .nomedia file in download / playlist folders
            'post_download_action': 'Disabled', # 'Disabled', 'Shutdown PC', 'Sleep / Suspend'
            'check_ytdlp_updates_on_startup': True,
            'embed_all_metadata': True,
            'download_audio_lyrics': False,
            'lyrics_langs': 'orig', # 'orig', 'all', 'en', 'ru', 'uk'
            'audio_metadata_tags': {
                'artist': True,
                'title': True,
                'album': True,
                'cover': True,
                'track_number': True,
                'year': True,
                'lyrics': True
            },
            'video_naming_pattern': '{title}',
            'video_container': 'mp4',
            'video_codec': 'auto',
            'embed_all_video_metadata': True,
            'video_metadata_tags': {
                'title_desc': True,
                'author': True,
                'year': True,
                'thumbnail': True,
                'chapters': True,
                'subtitles': True
            },
            'use_cookies': False,
            'cookies_source': 'none', # 'none', 'browser' or 'file'
            'cookies_browser': 'chrome',
            'cookies_file': '',
            'quality_settings': {
                'YouTube': 'Best video',
                'Twitch': 'Source (Best)',
                'SoundCloud': 'Best Audio',
                'Spotify': 'Best Audio',
                'Facebook': 'Best video',
                'Instagram': 'Best video',
                'Twitter (X)': 'Best video',
                'TikTok': 'Best video'
            }
        }
        self.settings = self.load()

    def load(self):
        if self.settings_file.exists():
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    merged = self.default_settings.copy()

                    # Migrate legacy cookie setting names used by earlier builds.
                    for old_key, new_key in (
                        ('cookie_source_type', 'cookies_source'),
                        ('cookie_browser', 'cookies_browser'),
                        ('cookie_file', 'cookies_file'),
                    ):
                        if old_key in data:
                            data.setdefault(new_key, data[old_key])
                            data.pop(old_key)
                    
                    # Ensure nested dicts are updated properly
                    if 'quality_settings' in data:
                        merged['quality_settings'].update(data['quality_settings'])
                        del data['quality_settings']
                        
                    merged.update(data)
                    return merged
            except Exception:
                return self.default_settings.copy()
        return self.default_settings.copy()

    def reload(self):
        self.settings = self.load()
        return self.settings

    def save(self):
        with open(self.settings_file, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, indent=4)

    def get(self, key, default=None):
        return self.settings.get(key, default if default is not None else self.default_settings.get(key))

    def set(self, key, value):
        self.settings[key] = value
        self.save()
        
    def get_quality(self, platform):
        return self.settings.get('quality_settings', {}).get(platform, 'Best video' if platform == 'YouTube' else 'Best')
        
    def set_quality(self, platform, quality):
        if 'quality_settings' not in self.settings:
            self.settings['quality_settings'] = self.default_settings['quality_settings'].copy()
        self.settings['quality_settings'][platform] = quality
        self.save()
