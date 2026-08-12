# Logovo Downloads

Logovo Downloads is a modern, beautiful, and user-friendly graphical interface (GUI) for `yt-dlp`. It allows you to download videos, audio, and playlists from YouTube, Twitch, SoundCloud, Spotify, and many other platforms without ever needing to touch the command line.

> **Note:** This is a **fan project** created with the assistance of AI (Google Antigravity).

## Features
- **Modern UI:** A clean, dark-themed interface built with PyQt6.
- **Queue Management:** Add multiple tracks or playlists to a queue, preview thumbnails, and download everything in bulk.
- **Smart Metadata & Post-Processing:** Automatically embeds thumbnails, artist names, and album art into MP3 files.
- **Archive Tracking:** Keeps an archive of downloaded files so you never download the same track twice (automatically marks them as skipped).
- **History Log:** View the status of all your past downloads.
- **Cookies Support:** Easily bypass age-restricted or premium-only content blocks by importing `cookies.txt`.
- **Quality Selection:** Choose between audio-only (MP3) or various video resolutions (up to 4K) for multiple platforms.

## Installation

If you're using the standalone executable (`.exe`):
1. Download the latest release from the Releases page.
2. Unpack the folder and run `LogovoDownloads.exe`. No installation required!

If you want to run from source:
1. Clone the repository: `git clone https://github.com/Helvior-dev/Logovo-Downloads.git`
2. Install Python 3.10+
3. Install dependencies: `pip install -r requirements.txt` (Make sure you have `PyQt6` and `yt-dlp[default]`)
4. Run `python main.py`

## Requirements
- To embed thumbnails and convert audio to MP3, you need `ffmpeg` installed on your system and added to your PATH. (If you use the pre-built `.exe` folder release, `ffmpeg.exe` may need to be placed in the same folder if not globally installed).

## Disclaimer
This project is an independent open-source tool. It is not affiliated with YouTube, Google, or any other media platforms. Please use responsibly and respect local copyright laws.

## Inspiration
This project was developed with the assistance of AI and was inspired by Magerko's [Universal Media Downloader](https://github.com/Magerko/universal-media-downloader).