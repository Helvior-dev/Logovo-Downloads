# Logovo Downloads

<p align="center">
  <img src="media/icon.ico" width="80" height="80" alt="Logovo Downloads Logo" />
  <br>
  <b>Desktop audio and video downloader with playlist synchronization and metadata embedding.</b>
  <br>
  <sub>Built with Python 3.10+, PyQt6, and yt-dlp.</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.8.0-007acc.svg?style=flat-square" alt="Version 1.8.0" />
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/GUI-PyQt6-41CD52.svg?style=flat-square&logo=qt&logoColor=white" alt="PyQt6" />
  <img src="https://img.shields.io/badge/Core-yt--dlp-red.svg?style=flat-square" alt="yt-dlp" />
  <img src="https://img.shields.io/badge/Audio-FFmpeg-007808.svg?style=flat-square&logo=ffmpeg&logoColor=white" alt="FFmpeg" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License MIT" /></a>
</p>

---

## Overview

**Logovo Downloads** is a desktop application for downloading media and keeping local audio and video directories synchronized with online playlists across YouTube, Spotify, SoundCloud, Bandcamp, and other platforms.

It is designed for managing offline music libraries with accurate metadata extraction, duplicate avoidance, and fast playlist verification.

---

## Key Features

### Media Downloads & Platform Support
- **Multi-Platform:** Native support for YouTube, Spotify, SoundCloud, Bandcamp, Twitch, TikTok, Vimeo, VK, and more.
- **Spotify DRM Bypass:** Automatically resolves Spotify tracks, albums, and playlists to high-quality audio streams while retaining original Spotify metadata, artist tags, and album artwork.
- **Formats:** Audio (MP3 320 kbps, FLAC, M4A, Opus, Ogg, WAV, ALAC) and Video (up to 4K/8K 60fps, MP4/MKV).
- **Fast Metadata Enrichment:** Automatically resolves titles, artist names, and HD thumbnails in 50ms when importing links from text files or pasting raw URLs.
- **Widescreen & Square Covers:** Native 16:9 thumbnails for video containers and square 1:1 artwork for audio files.
- **Multi-Threaded Queue:** Concurrent download queue with configurable stream limits (up to 6 workers).

### Playlist Synchronization
- **Fast Local Indexing:** Compares local folders against online playlists in seconds using cached file stems.
- **Removed Track Detection:** Identifies tracks removed or unlisted from playlists and displays neutral `-N removed` markers.
- **Zero-Lag Reordering:** Drag-and-drop playlist cards or use arrow buttons with instantaneous in-place reordering.
- **Title Cleaning:** Automatically strips junk video labels and promotional clutter while preserving genuine version suffixes (`Remix`, `VIP`, `Extended`, `Acoustic`, `Instrumental`, `Live`).
- **Duplicate Detection:** Identifies duplicate tracks within online playlists and provides direct links to manage them.

### App Updates & Maintenance
- **GitHub Release Checker:** Background check for new app versions on GitHub with non-intrusive KDE Plasma style toasts.
- **In-App `yt-dlp` Updater:** Upgrades the underlying downloader core directly within the UI without external package managers.
- **Clean AppData Hierarchy:** Settings and logs stored in `AppData/Roaming/Logovo-Dushnil/Logovo-Downloads`.
- **Backup & Restore:** Full backup and restore of playlists, settings, and history via zip archive.

---

## Tech Stack

- **GUI:** PyQt6
- **Download Engine:** `yt-dlp` (with `curl-cffi`)
- **Media Backend:** FFmpeg / FFprobe
- **Audio Tagging:** Mutagen
- **Image Processing:** Pillow (PIL)
- **JS Challenge Solver:** Deno (bundled)

---

## Project Structure

```text
Logovo-Downloads/
├── core/                             # Core services and business logic
│   ├── constants.py                  # App constants and format definitions
│   ├── downloader.py                 # Download engine, tagger, and URL sanitizers
│   ├── preview.py                    # Metadata parser (YouTube, Spotify, SoundCloud)
│   ├── playlists_manager.py          # Tracked playlists storage and persistence
│   ├── playlist_comparator.py        # Cross-playlist duplicate analysis
│   ├── history.py                    # Download history persistence
│   ├── logger.py                     # Centralized logging setup
│   ├── settings.py                   # App configuration manager
│   ├── taskbar.py                    # Windows Taskbar progress integration
│   └── updater.py                    # yt-dlp core auto-updater
│
├── ui/                               # GUI components (PyQt6)
│   ├── main_window.py                # Main window layout and tab controllers
│   ├── queue_item.py                 # Queue card widget and background enricher
│   ├── playlist_comparison_dialog.py # Duplicate analysis dialog
│   ├── log_viewer_dialog.py          # Dual log viewer modal
│   └── styles.py                     # Dark theme stylesheet
│
├── bin/                              # Bundled binaries (FFmpeg / FFprobe / Deno)
├── media/                            # App icons and graphics
├── downloads/                        # Default download output directory
├── main.py                           # Application entrypoint
├── requirements.txt                  # Python dependencies
└── README.md                         # Documentation
```

---

## Installation & Running from Source

### Prerequisites
- **Python 3.10+** (64-bit)
- **FFmpeg** (in system `PATH` or placed inside `bin/`)

### Setup

```bash
# 1. Clone repository
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads

# 2. Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run application
python main.py
```

---

## Acknowledgements

Developed independently with the assistance of AI, inspired by Magerko's [Universal Media Downloader](https://github.com/Magerko/universal-media-downloader).

---

## License

This project is licensed under the [MIT License](LICENSE).