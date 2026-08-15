# Logovo Downloads

<p align="center">
  <b>Modern, aesthetic, and resilient multi-threaded media downloader with PyQt6 and yt-dlp</b>
</p>

---

## 🌟 Overview

**Logovo Downloads** is a state-of-the-art graphical application (GUI) designed for high-speed, parallel audio and video downloads from YouTube, YouTube Music, SoundCloud, Twitch, Spotify, and hundreds of other media platforms.

Built with `PyQt6` and `yt-dlp`, it delivers an ultra-smooth experience with multi-threaded parallel downloads, 1-click playlist synchronization, automated post-processing, Windows folder custom icons, real-time queue telemetry, and background core updater.

---

## ✨ Features

- ⚡ **Multi-Threaded Parallel Downloads:** Download 1 to 6 tracks simultaneously with individual progress bars, live speeds, and anti-ban jitter protection.
- 📁 **Tracked Playlists Library & 1-Click Sync:** Keep a permanent list of your favorite playlists in the **PLAYLISTS** tab. Sync all or individual playlists with one click — detects missing tracks and removes deleted orphans.
- 🎨 **Smart Folder Icons & Artwork:** Automatically extracts high-resolution playlist covers, converts them to multi-resolution Windows folder icons (`folder_icon.ico` + `desktop.ini`), and saves original `cover.png` files.
- 🏷️ **Custom File Naming Templates:** Format filenames freely using interactive tokens (`{artist}`, `{title}`, `{index}`, `{album}`, `{year}`) with 1-click presets.
- 🔄 **`yt-dlp` Core Auto-Updater:** Automatically checks for newer `yt-dlp` releases on startup (or via Settings) and upgrades the core in the background without reinstalling the app.
- 🖼️ **1:1 Square Cover Cropping & Tagging:** Center-crops album art to a crisp square ($1000\times1000$) and writes clean ID3/FLAC/Opus/MP4 metadata tags (Track Number/Total, Artist, Album, Title).
- 🛡️ **Zero-403 Multi-Client Resilience:** Built-in automatic client rotation (`android`, `ios`, `mweb`, `web`) and spacing protection against YouTube HTTP 403 Forbidden errors.
- 🚥 **Speed Limiter:** Bandwidth throttling options (`Unlimited`, `1 MB/s`, `3 MB/s`, `5 MB/s`, `10 MB/s`, `20 MB/s`) to prevent network congestion.
- 🌙 **Post-Download Actions:** Auto-shutdown PC or Sleep/Suspend with a 30-second cancellation countdown when long queues finish.
- 📊 **Real-Time Queue Telemetry:** Live indicators for Downloaded size vs Total size (e.g. `💾 32 MB / 360 MB`) and dynamic Time Remaining (ETA).
- 🔔 **Windows Tray & Toast Notifications:** Native Windows notifications with system sound when downloads finish.
- 🍪 **Cookie Extraction Support:** Bypass age restrictions and login walls via browser cookies or `cookies.txt`.

---

## 🚀 Installation & Running

### Prerequisites
- Python 3.10 or higher
- [FFmpeg](https://ffmpeg.org/download.html) installed and accessible in system `PATH`.

### From Source
```bash
# Clone the repository
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads

# Create and activate virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

# Install required dependencies
pip install -r requirements.txt

# Launch the application
python main.py
```

---

## 📦 Requirements

- `PyQt6`
- `yt-dlp[curl-cffi]`
- `requests`
- `Pillow`
- `mutagen`

---

## 📜 Disclaimer

This project is an independent open-source tool. It is not affiliated with, endorsed by, or sponsored by YouTube, Google, or any other media platforms. Please use responsibly and respect copyright laws.

---

## 💡 Inspiration & Credits

Developed with the assistance of AI (Google Antigravity) and inspired by [Universal Media Downloader](https://github.com/Magerko/universal-media-downloader).