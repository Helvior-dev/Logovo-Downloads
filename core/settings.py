import os
import json
from pathlib import Path

APP_NAME = "LogovoDownloads"

def get_app_data_dir() -> Path:
    app_data = Path(os.getenv('APPDATA', Path.home() / '.config'))
    app_dir = app_data / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

class SettingsManager:
    def __init__(self):
        self.settings_file = get_app_data_dir() / 'settings.json'
        self.default_settings = {
            'download_path': str(Path.home() / 'Downloads'),
            'download_subtitles': False,
            'subtitles_langs': 'orig', # 'orig', 'all', 'en', 'ru', 'uk'
            'playlist_cover_mode': 'both', # 'both', 'icon', 'file', 'none'
            'max_concurrent_downloads': 3, # 1 to 6
            'naming_pattern': '{artist} - {title}', # e.g. '{artist} - {title}', '{index}. {artist} - {title}'
            'speed_limit': 'Unlimited', # 'Unlimited', '1 MB/s', '3 MB/s', '5 MB/s', '10 MB/s', '20 MB/s'
            'filename_compat': 'Windows (Original)', # 'Windows (Original)' or 'UNIX / POSIX / MTP'
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
            'cookie_source_type': 'browser', # 'browser' or 'file'
            'cookie_browser': 'chrome',
            'cookie_file': '',
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
                    
                    # Ensure nested dicts are updated properly
                    if 'quality_settings' in data:
                        merged['quality_settings'].update(data['quality_settings'])
                        del data['quality_settings']
                        
                    merged.update(data)
                    return merged
            except Exception:
                return self.default_settings.copy()
        return self.default_settings.copy()

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
