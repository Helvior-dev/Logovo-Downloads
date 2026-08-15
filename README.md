# Logovo Downloads

<p align="center">
  <img src="media/icon.ico" width="72" height="72" alt="Logovo Downloads Logo" />
  <br>
  <b>Multi-threaded audio and video downloader built with PyQt6 and yt-dlp</b>
</p>

---

## Overview

**Logovo Downloads** is a desktop application for downloading audio and video from YouTube, YouTube Music, SoundCloud, Twitch, Spotify, and other platforms supported by `yt-dlp`.

It supports parallel multi-threaded downloading, tracked playlist synchronization with gapless auto-reindexing, square cover art cropping, custom file naming patterns, and full metadata tagging.

---

## Features

- **Parallel Downloads:** Download up to 6 files simultaneously with live speed and progress indicators for each track.
- **Tracked Playlists:** Save playlists to your library and sync new tracks with one click. Displays real-time downloaded tracks in folder vs total tracks in playlist. Missing or deleted files are handled automatically without gaps in numbering.
- **Folder Icons and Covers:** Automatically extracts playlist artwork, sets a Windows folder icon (`.ico`), and saves a `cover.png` file in the playlist folder.
- **Smart Fallback Engine:** Automatic intelligent search fallback for age-restricted (18+) or region-blocked music videos. Seamlessly downloads official audio streams without requiring browser cookies or account login.
- **Audio Settings:**
  - Custom file naming templates using tokens like `{artist}`, `{title}`, `{index}`, `{album}`, `{year}`.
  - Automatic 1000x1000 square cover art cropping.
  - Tagging for ID3 (MP3), FLAC, Opus, and M4A with retry safeguards against Windows file locks.
  - Granular metadata toggles (Artist, Title, Album, Cover, Track Number, Year, Lyrics).
  - Optional Karaoke mode for downloading and embedding synchronized `.lrc` lyrics (`USLT`, `LYRICS`, `©lyr`) with dedicated language selection (Original / specific language).
- **Video Settings:**
  - High-resolution downloading supporting 1080p, 1440p (2K), 2160p (4K UHD), and 60fps.
  - Granular subtitle language selection (per-item and global) with automatic suppression of auto-translate spam.
  - Video naming templates with tokens like `{title}`, `{author}`, `{resolution}`, `{fps}`, `{year}`, `{index}`.
  - Container selection: MP4 or MKV.
  - Preferred video codec: Auto, H.264 (AVC), H.265 (HEVC), or VP9 / AV1.
  - Metadata embedding: Title, Description, Channel, normalized 4-digit Year, Thumbnail Poster, Chapter markers, and soft Subtitles.
- **yt-dlp Core Updater:** Check and update `yt-dlp` directly inside the app without reinstalling.
- **Speed Limit and Post-Download Actions:** Throttle download speeds or set the PC to shutdown / sleep when the queue finishes.

---

## Installation

### Requirements
- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and added to `PATH`

### Setup
```bash
# Clone the repository
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads

# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

---

## Stack

- **GUI:** PyQt6
- **Engine:** yt-dlp
- **Tagging:** mutagen
- **Image Processing:** Pillow
- **Networking:** requests, curl-cffi

---

## License & Credits

Open-source project built for personal and educational use. Please respect copyright laws and the terms of service of the content platforms.