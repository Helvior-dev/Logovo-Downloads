# Logovo Downloads

<p align="center">
  <b>Modern, aesthetic, and resilient media downloader with PyQt6 and yt-dlp</b>
</p>

---

## 🌟 Overview

**Logovo Downloads** is a state-of-the-art graphical interface (GUI) designed for seamless, high-quality audio and video downloads from YouTube, YouTube Music, SoundCloud, Twitch, Spotify, and hundreds of other media platforms.

Built on top of `yt-dlp` and `PyQt6`, it delivers an ultra-smooth experience with automated post-processing, resilient multi-client retry strategies, Windows folder custom icons, and real-time queue telemetry.

---

## ✨ Features

- 🎨 **Sleek Modern UI:** Clean dark-slate design with fluid queue management and micro-animations.
- 📁 **Smart Playlist Modes:**
  - **New Playlist:** Auto-creates folder in any custom directory or default Downloads, downloads the real playlist cover, and automatically applies it as a multi-resolution Windows folder icon (`folder_icon.ico` + `desktop.ini`).
  - **Continue Existing Folder:** Synchronizes missing tracks with orphan detection (prompts to remove local files deleted from online playlists) without overriding folder icons.
- 🖼️ **1:1 Square Cover Cropping & Tagging:** Center-crops album art to a perfect square ($1000\times1000$) with Lanczos filtering and writes clean ID3/FLAC/Opus/MP4 metadata tags (Track Number, Artist, Album, Title).
- 🛡️ **Zero-403 Multi-Client Resilience:** Built-in automatic client rotation (`android`, `ios`, `mweb`, `web`) and spacing protection against YouTube HTTP 403 Forbidden errors.
- ⚡ **Real-Time Queue Telemetry:** Live indicators for Downloaded size vs Total size (e.g. `💾 32 MB / 360 MB`) and dynamic Time Remaining (ETA) based on rolling download speeds.
- ⚙️ **Customizable Artwork Settings:** Choose between setting Windows folder icons, saving `cover.png` in original quality, doing both, or disabling cover saving.
- 🔄 **History & Error Highlighting:** Interactive history table with color-coded statuses (Completed, Error, Skipped) and human-friendly error descriptions.
- 🍪 **Cookie Extraction Support:** Easily bypass age restrictions and login walls via browser cookies or `cookies.txt`.

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