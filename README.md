# Logovo Downloads

Logovo Downloads is a Windows desktop app for downloading audio and video and keeping local folders in sync with online playlists. It uses yt-dlp for downloads and PyQt6 for the interface. The current application version is **1.8.11**; changes since the last release are still unreleased.

## What it does

- Downloads individual links and playlists as audio or video. Supported sites depend on yt-dlp and can change when a site changes its player or access rules.
- Keeps a queue of downloads. You can pause it, close the app, restore unfinished items on the next launch, or remove one item without deleting its downloaded files. Resuming a partial download depends on the source.
- Tracks playlist folders and compares them with the online playlist before applying changes. Removed local tracks are shown in a preview; deleting selected files requires a separate confirmation.
- Writes audio and video metadata, artwork and subtitles where the source and chosen format allow it. Includes a history view and tools for comparing tracked playlists.
- Provides seven color themes and settings grouped under General, Audio, Video, Quality, Access and Maintenance.
- Offers a manual cleanup view for `.part` files and old yt-dlp backups. Nothing is preselected or removed automatically. The active yt-dlp core and the most recent working backup are excluded.
- Exports and imports settings, playlist records, history and logs as a ZIP backup. The backup does **not** include downloaded media.

Settings, history and logs live under `%APPDATA%\Logovo-Dushnil\Logovo-Downloads`. Downloads go to the folder selected in General. Cookies can be supplied from a browser or a file when a site requires them; do not commit cookie files or exported backups.

## Run from source

Use Python 3.10 or newer on Windows. FFmpeg and FFprobe must be available in `PATH` or in the local `bin/` directory for media conversion and probing. Some sites may also require Deno for yt-dlp's JavaScript challenges.

```powershell
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

To run the tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

## Build for Windows

Install the build requirements in the same virtual environment, prepare the external binaries, then build the one-folder distribution:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe tools/prepare_build_assets.py
.\.venv\Scripts\python.exe -m PyInstaller LogovoDownloads.spec
```

The preparation script downloads pinned FFmpeg, FFprobe and Deno archives, verifies their SHA-256 hashes and puts the files under `.build-assets/`. Build output is written to `dist/Logovo-Downloads/`. These generated directories and local environments are ignored by Git. If distributing a build, include the bundled licenses and review [third-party notices](THIRD_PARTY_NOTICES.md); the included FFmpeg build is GPLv3.

## Notes

- Pause and stop are cooperative. A worker can take time to finish a network request or post-processing step.
- Playlist synchronization has a read-only planning stage, but confirming cleanup can permanently delete selected local files. Check the preview before proceeding.
- yt-dlp updates are staged for the next app launch. The previous working core is retained for rollback.
- Network diagnostics run only when requested. Automatic update checks can be disabled in settings.

## Acknowledgements

Developed independently with the assistance of AI, inspired by Magerko's [Universal Media Downloader](https://github.com/Magerko/universal-media-downloader).

Licensed under [MIT](LICENSE).
