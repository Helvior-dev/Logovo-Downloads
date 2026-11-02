import json
from datetime import datetime
from core.settings import get_app_data_dir


DOWNLOAD_OPTION_KEYS = frozenset({
    'source_url',
    'output_dir',
    'media_type',
    'media_type_category',
    'quality',
    'subtitles',
    'speed_limit',
    'naming_pattern',
    'format_compat',
    'playlist_index',
    'playlist_count',
    'title',
    'author',
    'thumbnail',
    'settings',
})

DOWNLOAD_SETTING_KEYS = frozenset({
    'album_tag_mode',
    'audio_metadata_tags',
    'create_nomedia_file',
    'download_audio_lyrics',
    'download_subtitles',
    'embed_all_metadata',
    'embed_all_video_metadata',
    'filename_compat',
    'lyrics_langs',
    'subtitles_langs',
    'video_codec',
    'video_container',
    'video_metadata_tags',
    'video_naming_pattern',
})


def _copy_json_values(values: dict, allowed_keys: frozenset[str]) -> dict:
    copied = {}
    for key, value in values.items():
        if key not in allowed_keys:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            copied[key] = value
        elif isinstance(value, dict):
            copied[key] = {
                nested_key: nested_value
                for nested_key, nested_value in value.items()
                if isinstance(nested_key, str)
                and (isinstance(nested_value, (str, int, float, bool)) or nested_value is None)
            }
    return copied


def sanitize_download_options(options: dict | None) -> dict | None:
    """Keep only retry-relevant, JSON-safe, non-secret download parameters."""
    if not isinstance(options, dict):
        return None
    sanitized = _copy_json_values(options, DOWNLOAD_OPTION_KEYS)
    subtitles = options.get('subtitles')
    if isinstance(subtitles, dict):
        sanitized['subtitles'] = _copy_json_values(subtitles, frozenset({'download', 'langs'}))
    settings = options.get('settings')
    if isinstance(settings, dict):
        sanitized['settings'] = _copy_json_values(settings, DOWNLOAD_SETTING_KEYS)
    return sanitized


def snapshot_download_settings(settings) -> dict:
    """Capture the non-secret application settings used while downloading media."""
    if settings is None:
        return {}
    values = {key: settings.get(key) for key in DOWNLOAD_SETTING_KEYS}
    return _copy_json_values(values, DOWNLOAD_SETTING_KEYS)


def is_retryable_error(entry: dict) -> bool:
    if not isinstance(entry, dict) or not str(entry.get('status', '')).startswith('Error'):
        return False
    options = entry.get('download_options')
    return bool((options.get('source_url') if isinstance(options, dict) else None) or entry.get('url'))


def get_retryable_error_entries(entries: list[dict]) -> list[dict]:
    """Return current failed states, excluding errors later resolved or unavailable."""
    retryable = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        options = entry.get('download_options')
        url = (options.get('source_url') if isinstance(options, dict) else None) or entry.get('url')
        if not url:
            continue
        media_type = (
            options.get('media_type') if isinstance(options, dict) else None
        ) or entry.get('type', 'Audio')
        if str(media_type).lower() in ('audio', 'video'):
            media_type = f'{str(media_type).title()} (Best)'
        key = (url, media_type)
        if key in seen:
            continue
        seen.add(key)
        if is_retryable_error(entry):
            retryable.append(entry)
    return retryable


class HistoryManager:
    def __init__(self):
        self.history_file = get_app_data_dir() / 'history.json'
        self.history = self.load()

    def load(self):
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def save(self):
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, indent=4)

    def add_entry(
        self,
        title: str,
        author: str,
        platform: str = "YouTube",
        status: str = "Completed",
        url: str = "",
        media_type: str = "Audio",
        download_options: dict | None = None,
    ):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {
            'timestamp': now_str,
            'date': now_str,
            'title': title,
            'author': author,
            'platform': platform,
            'url': url,
            'type': media_type,
            'status': status
        }
        sanitized_options = sanitize_download_options(download_options)
        if sanitized_options:
            entry['download_options'] = sanitized_options
        self.history.insert(0, entry) # Add to top
        self.save()

    def get_all(self):
        return self.history
        
    def clear(self):
        self.history = []
        self.save()
