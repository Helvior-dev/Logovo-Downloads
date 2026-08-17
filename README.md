# Logovo Downloads

<p align="center">
  <img src="media/icon.ico" width="80" height="80" alt="Logovo Downloads Logo" />
  <br>
  <b>Desktop audio and video downloader with playlist synchronization and metadata embedding.</b>
  <br>
  <sub>Built with Python 3.10+, PyQt6, and yt-dlp.</sub>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-1.7.1-007acc.svg?style=flat-square" alt="Version 1.7.1" />
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/GUI-PyQt6-41CD52.svg?style=flat-square&logo=qt&logoColor=white" alt="PyQt6" />
  <img src="https://img.shields.io/badge/Core-yt--dlp-red.svg?style=flat-square" alt="yt-dlp" />
  <img src="https://img.shields.io/badge/Audio-FFmpeg-007808.svg?style=flat-square&logo=ffmpeg&logoColor=white" alt="FFmpeg" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg?style=flat-square" alt="License MIT" /></a>
</p>

---

## Overview

**Logovo Downloads** is a desktop tool for downloading media and keeping local audio folders synchronized with online playlists (YouTube, YouTube Music, and other services supported by `yt-dlp`).

The application is built for managing large local music libraries: it syncs playlists, extracts clean metadata, detects duplicate tracks, and prevents redundant downloads.

---

## Features

### Media Downloads
- **Formats:** Audio (MP3 up to 320 kbps, FLAC, M4A, Opus, Ogg, WAV, ALAC) and Video (up to 4K/8K 60fps, MP4/MKV).
- **Concurrency:** Multi-threaded download queue with configurable thread count (up to 6 streams).
- **Windows Integration:** Taskbar progress bar and system tray notifications.
- **Bandwidth Control:** Optional global speed limits.

### Playlist Synchronization
- **Fast Local Indexing:** Compares local folders against online playlists in seconds using cached metadata.
- **Removed Tracks Detection & Cleanup:** Automatically detects tracks removed from online playlists and prompts an interactive dialog to review and delete local copies if desired.
- **Metadata Cleaning:** Automatically strips video labels, promo tags, and release years while preserving distinct version tags (`Remix`, `VIP`, `Extended`, `Acoustic`, `Instrumental`, `Live`).
- **Artist Extraction:** Resolves artist and title from channel uploads and record label titles (e.g. `Hospital Records - Netsky - Secret Agent`).
- **Online Duplicate Detection:** Identifies duplicate tracks within online playlists and provides direct links to manage them on YouTube Music.
- **Unavailable Tracks Tracking:** Accounts for copyright claims and deleted tracks with neutral status markers.

### Library Management
- **Cross-Playlist Comparison:** Scans tracked playlists to find tracks that exist in multiple folders simultaneously.
- **Track Breakdown Modal:** View full folder paths across all playlists with options to open files or copy details.
- **Metadata Embedding:** Embeds ID3v2.3/ID3v2.4 tags into MP3 files, attaches 1000x1000 square cover art, and saves synchronized `.lrc` lyrics.
- **Safe File Tagging:** Retry handlers to avoid issues with temporary Windows file locks.

### Maintenance & Security
- **Authentication:** Supports importing Netscape-format `cookies.txt` for authenticated downloads where supported.
- **Dual Log Viewer:** User-friendly event view and raw developer console with search and export.
- **In-App Updater:** Check for and install `yt-dlp` core updates directly from the settings tab.
- **Backup & Restore:** Export or import settings, history, and playlist configurations as a zip archive.

---

## Tech Stack

- **GUI:** PyQt6
- **Engine:** `yt-dlp` (with `curl-cffi` backend)
- **Audio/Video Backend:** FFmpeg / FFprobe
- **Metadata:** Mutagen
- **Image Processing:** Pillow (PIL)
- **Runtime:** Native Python 3.10+ (does not require Node.js or Deno)

---

## Project Structure

```text
Logovo-Downloads/
├── core/                             # Backend logic and core modules
│   ├── constants.py                  # App constants, versioning and format definitions
│   ├── downloader.py                 # yt-dlp wrapper, tagger, cleaners and post-processors
│   ├── preview.py                    # Metadata extraction and playlist previewer
│   ├── playlists_manager.py          # Tracked playlists storage and state persistence
│   ├── playlist_comparator.py        # Cross-playlist comparison and clustering engine
│   ├── history.py                    # Download history manager
│   ├── logger.py                     # File and UI logging dispatcher
│   ├── settings.py                   # User preferences manager
│   ├── taskbar.py                    # Windows Taskbar progress integration
│   ├── updater.py                    # yt-dlp core auto-updater
│   ├── backup.py                     # Backup and restore utilities
│   └── utils.py                      # Filename sanitization and helpers
│
├── ui/                               # User interface (PyQt6)
│   ├── main_window.py                # Main window coordinator and tabs
│   ├── queue_item.py                 # Download queue item widget
│   ├── playlist_comparison_dialog.py # Cross-playlist comparison modal
│   ├── log_viewer_dialog.py          # Log viewer dialog (User & Developer tabs)
│   └── styles.py                     # Dark theme stylesheets and styling tokens
│
├── bin/                              # Optional embedded binaries (FFmpeg / FFprobe)
├── media/                            # Assets and application icons
├── downloads/                        # Default download directory
├── main.py                           # Application entrypoint
├── requirements.txt                  # Python dependencies
├── .gitignore                        # Git exclusion rules
└── README.md                         # Project documentation
```

---

## Installation & Setup

### Prerequisites
- **Python 3.10+** (64-bit)
- **[FFmpeg](https://ffmpeg.org/download.html)** (in system `PATH` or placed inside `bin/`)

### Setup

```bash
# 1. Clone repository
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads

# 2. Create virtual environment
# Windows:
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Linux / macOS:
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run application
python main.py
```

---

## Acknowledgements

This project was developed independently with the assistance of AI and was inspired by Magerko's [Universal Media Downloader](https://github.com/Magerko/universal-media-downloader).

---

## License

This project is licensed under the [MIT License](LICENSE).