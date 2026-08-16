# Logovo Downloads

<p align="center">
  <img src="media/icon.ico" width="80" height="80" alt="Logovo Downloads Logo" />
  <br>
  <b>Next-Generation multi-threaded audio & video downloader with intelligent playlist synchronization built with PyQt6 and yt-dlp</b>
</p>

---

## 🌟 Overview

**Logovo Downloads** is a powerful desktop application for downloading audio and video from YouTube, YouTube Music, SoundCloud, Twitch, Spotify, and other platforms supported by `yt-dlp`.

Designed for large music collections and automated workflows, it provides parallel multi-threaded downloading, intelligent tracked playlist synchronization, automatic replacement fallback for deleted/restricted tracks, interactive duplicate & orphan detection, square cover art cropping, and complete ID3/video metadata tagging.

---

## ✨ Features

### ⚡ Parallel Multi-Threaded Downloads
- Download up to **6 items concurrently** with real-time speed, progress bars, and status updates for each individual item.
- Supports pause, resume, individual queue item cancellation, and global queue controls.

### 🔄 Intelligent Playlist Synchronization
- **Tracked Playlists Library:** Track any number of YouTube / YouTube Music playlists. Sync new tracks in one click.
- **Smart Duplicate Detection:** Automatically detects tracks added multiple times in your online playlist. Displays exact original and duplicate positions with a direct **`[Open in YouTube ↗]`** button to quickly remove duplicates from YouTube Music.
- **Interactive Orphan Detection:** Detects files that were removed from the online playlist and presents a clean modal dialog to let you choose whether to delete them locally or preserve them on your disk.
- **Bidirectional Transliteration (RU $\leftrightarrow$ EN):** Accurately recognizes matching tracks across Cyrillic and Latin transliterations (e.g. `Манхэттен` $\leftrightarrow$ `Mankhetten`), producer channel names, remix suffixes, and featured artist credits.
- **Deleted / DMCA Ghost Filter:** Automatically filters out dead placeholder items and copyright-takedown entries without crashing or queueing blank items.
- **Status & Up-to-Date Indicators:** Visual green status badges (`All X synced`) showing exact file count and synchronization health.

### 🛡️ Smart Replacement Fallback Engine
- When a music track is unavailable, region-locked, or deleted on YouTube, the engine automatically searches for verified official audio releases.
- Real-time **`Searching official release...`** status indicator in the UI.
- Fallback downloads are seamlessly mapped to local playlist indices and archive records without duplicate downloads.

### 🍪 YouTube Authentication & Cookies Support
- **Netscape Cookies File Support:** Full support for exported `cookies.txt` files to download age-restricted (18+), private, and YouTube Premium high-bitrate audio streams.
- **EJS / n-sig Remote Decryption:** Integrated with remote components and web/mweb client rotation for reliable token decryption.
- **Built-in Step-by-Step Guide:** Built-in instructions in the Settings tab explaining how to export and import cookies.

### 🎵 High-Fidelity Audio Features
- **Naming Templates:** Customizable patterns using tokens: `{artist}`, `{title}`, `{index}`, `{album}`, `{year}`.
- **Square Artwork & Folder Covers:** Crops playlist and track artwork to clean 1000x1000 squares, generates Windows folder `.ico` icons, and saves high-res `cover.png`.
- **Complete Tagging:** Embeds ID3v2.3 / ID3v2.4 (MP3), FLAC, Opus, and M4A tags with protection against Windows file locking.
- **Synchronized Karaoke Lyrics:** Automatically fetches and embeds synced `.lrc` lyrics (`USLT`, `LYRICS`, `©lyr`) with dedicated language selection.

### 🎬 Video Features
- Supports 1080p, 1440p (2K), 2160p (4K UHD), and 60fps video downloads.
- Codec selection: Auto, H.264 (AVC), H.265 (HEVC), VP9, and AV1.
- Embeds soft subtitles, video chapter markers, description, channel, and cover posters into MP4/MKV containers.

### ⚙️ Core Engine & System Controls
- **In-App Core Updater:** Check and update `yt-dlp` directly inside the app with one click or automatically on startup.
- **Post-Download Actions:** Automatically put your PC to sleep or shut down when the queue completes.
- **Dark Slate UI:** Modern dark interface built with PyQt6.

---

## 🚀 Installation & Quick Start

### Prerequisites
- **Python 3.10+** (64-bit recommended)
- **[FFmpeg](https://ffmpeg.org/download.html)** installed and available in your system `PATH`.

### Setup
```bash
# 1. Clone the repository
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads

# 2. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch Logovo Downloads
python main.py
```

---

## 🛠️ Technology Stack

| Component | Technology |
|---|---|
| **GUI Framework** | PyQt6 (Python Qt6 bindings) |
| **Download Engine** | yt-dlp |
| **Audio Metadata** | Mutagen |
| **Image Processing** | Pillow (PIL) |
| **Networking** | requests, curl-cffi |

---

## 📄 License & Credits

Open-source project created for personal and educational use. Please respect copyright laws and the terms of service of the content platforms.