# Logovo Downloads

<p align="center">
  <img src="media/icon.ico" width="80" height="80" alt="Logovo Downloads Logo" />
  <br>
  <b>A desktop audio & video downloader with smart playlist synchronization built with Python, PyQt6, and yt-dlp.</b>
</p>

---

> [!NOTE]
> **Disclaimer & AI Acknowledgement:**
> This is a **fan-made, non-commercial open-source project created with AI assistance**. It is built strictly for personal educational purposes, offline media archiving, and backup of your own playlists.
> The author is **not affiliated with, endorsed by, or connected to Google, YouTube, Spotify, SoundCloud, or any other media service**. The software is provided "as is", without warranty of any kind. Please respect copyright laws and the terms of service of the respective platforms.

---

## What is Logovo Downloads?

Logovo Downloads is a simple yet powerful desktop program for Windows (and other platforms) that lets you download music and videos from YouTube, YouTube Music, SoundCloud, Twitch, and other sites supported by `yt-dlp`.

It is especially tailored for people who maintain offline music libraries and want to keep their local folders in sync with their online playlists without duplicates, missing songs, or broken files.

---

## Key Features

- **Multi-threaded Downloads:** Download up to 6 tracks or videos simultaneously with live progress bars, speed metrics, and ETA.
- **Windows Taskbar Progress:** Live progress bar indicator right on the Windows taskbar icon while downloads are running.
- **Tracked Playlists Synchronization:**
  - Save your favorite YouTube / YouTube Music playlists to your library and sync them with 1 click.
  - **Online Duplicates Detection:** Scans your playlist for duplicate tracks added by mistake and provides direct links to open and remove them in YouTube Music.
  - **Orphan File Detection:** When tracks are removed from an online playlist, the app asks whether you want to delete local copies or keep them on your drive.
  - **Transliteration & Alias Matching:** Seamlessly matches songs between English and Russian / Ukrainian titles, handles remix tags, featured artist credits, and producer channel names.
  - **DMCA / Ghost Filter:** Automatically suppresses dead placeholder entries from copyright takedowns so your sync status stays clean and accurate.
- **Smart Fallback Search:** If a music track in your playlist is deleted, age-restricted, or geo-blocked, the app automatically searches for verified official alternative releases and downloads them seamlessly with real-time status.
- **YouTube Authentication & Cookies Support:**
  - Full support for importing `cookies.txt` (Netscape format) to download age-restricted (18+) content and high-bitrate YouTube Premium streams.
  - Integrated with remote token decryption components.
  - In-app step-by-step export guide.
- **Audio & Tagging Features:**
  - Customizable file naming templates: `{artist}`, `{title}`, `{index}`, `{album}`, `{year}`.
  - Auto-crops artwork to 1000x1000 square covers and generates Windows folder `.ico` icons.
  - Full ID3v2.3 / ID3v2.4 (MP3), FLAC, Opus, and M4A metadata embedding with Windows file-lock retry protections.
  - Automatic synchronized `.lrc` Karaoke lyrics download and tagging.
- **Video Features:**
  - Downloads resolutions from 360p up to 4K UHD at 60fps.
  - Choose preferred video codecs (H.264, HEVC, AV1, VP9) and container (MP4 / MKV).
  - Embeds soft subtitles, chapter markers, and video descriptions.
- **Built-in Tools:**
  - In-app `yt-dlp` core updater.
  - Post-download actions (sleep or shutdown PC after long queues finish).

---

## Requirements & Setup

### Requirements
- **Python 3.10+** (64-bit)
- **[FFmpeg](https://ffmpeg.org/download.html)** installed and added to your system `PATH`.

### Installation

```bash
# 1. Clone this repository
git clone https://github.com/Helvior-dev/Logovo-Downloads.git
cd Logovo-Downloads

# 2. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Install required packages
pip install -r requirements.txt

# 4. Run the program
python main.py
```

---

## Tech Stack

- **GUI:** PyQt6
- **Download Engine:** yt-dlp
- **Metadata & Tags:** Mutagen
- **Image Processing:** Pillow (PIL)
- **Networking:** requests, curl-cffi

---

## License

MIT License. Open source and free for personal and educational use.