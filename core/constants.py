"""Shared constants for the Logovo Downloads project."""

APP_VERSION = "1.6.0"

# Media file extensions for audio files
AUDIO_EXTS = frozenset({".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac"})

# Media file extensions for video files
VIDEO_EXTS = frozenset({".mp4", ".mkv", ".webm", ".avi", ".mov"})

# All tracked media extensions (audio + video)
MEDIA_EXTS = AUDIO_EXTS | VIDEO_EXTS

# Sort modes for playlists
SORT_CUSTOM = "custom"
SORT_NAME_ASC = "name_asc"
SORT_NAME_DESC = "name_desc"
SORT_TRACKS_DESC = "tracks_desc"
SORT_TRACKS_ASC = "tracks_asc"
SORT_SYNCED_DESC = "synced_desc"

# Media type category strings
MEDIA_TYPE_AUDIO = "Audio"
MEDIA_TYPE_VIDEO = "Video"

# Settings keys
SETTING_PLAYLIST_SORT_MODE = "playlist_sort_mode"

# Minimum valid media file size (500 KB)
MIN_MEDIA_SIZE_BYTES = 500 * 1024

# Thumbnail cache max age in seconds (7 days)
THUMB_CACHE_MAX_AGE_SECS = 7 * 24 * 3600
