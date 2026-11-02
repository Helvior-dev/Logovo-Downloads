# Changelog

Changes are recorded from the existing 1.8.11 project baseline onward. Earlier release history was not available in the project files.

## Unreleased

### Fixed
- Apply restored settings to the active settings manager and refresh the Settings tab after importing a backup.
- Stop active yt-dlp downloads cooperatively without losing their worker tracking or marking them as failures.
- Prevent the all-playlists audit from grouping tracks with the same title but different artists.
- Process large leftover video containers in audio playlists: remove video duplicates or pass unpaired containers to audio conversion.
- Avoid rewriting MP4 tags when the stored year is already normalized and no other video metadata changed.
- Align cookie setting defaults with the UI keys and migrate legacy singular keys when loading settings.
- Add standard-library regression tests for download orchestration (Spotify lookup, cookie validation, H.265/VP9-AV1 formats, archive skips, logger handling, reupload matching, retries, and playlist tracking), cover image processing/fetching (local, explicit, YouTube, and iTunes sources), safe Windows folder cover/icon writing, downloader helpers and failure logs, codec-specific audio tags/covers, audio/video conversion and post-processing, cleanup, playlist order/date restoration and reindexing, backup/settings reload, autoheal, settings migration, cancellation, playlist grouping/indexing, track matching, and build assets.
- Use a stable, version-independent Windows AppUserModelID.

### Changed
- Move background workers to `ui/workers.py` and playlist dialogs to `ui/dialogs.py` without changing their public use from the main window.
- Extract pure track normalization and matching helpers to `core/track_matching.py` while preserving imports through `core/downloader.py`.
- Extract local playlist mapping, archive, index, and orphan-detection helpers to `core/playlist_index.py`; retain their imports through `core/downloader.py`.
- Extract strict orphan-to-missing-entry matching and autoheal orchestration to `core/playlist_autoheal.py`, preserving imports through `core/downloader.py`.
- Track the PyInstaller spec and add a hash-verified build-asset bootstrap for pinned FFmpeg/FFprobe and Deno binaries, including bundled third-party notices.
