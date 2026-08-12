import yt_dlp
import os
import sys
from typing import Dict, Any, Callable, Optional
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.postprocessor import EmbedThumbnailPP, FFmpegMetadataPP
from PIL import Image
import io

try:
    from mutagen.id3 import ID3, APIC
    from mutagen.flac import FLAC
except ImportError:
    ID3, APIC, FLAC = None, None, None

def crop_to_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    resample = getattr(Image, "Resampling", Image).LANCZOS
    return img.crop((left, top, left + side, top + side)).resize((1000, 1000), resample)

class MutagenCoverFixPP(PostProcessor):
    def __init__(self, downloader=None, playlist_index=None, playlist_count=None):
        super().__init__(downloader)
        self.playlist_index = playlist_index
        self.playlist_count = playlist_count

    def run(self, info):
        filepath = info.get('filepath')
        if not filepath or not os.path.exists(filepath):
            return [], info
            
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.mp3' and ID3:
            self.to_screen("Fixing MP3 cover with mutagen...")
            try:
                tags = ID3(filepath)
                apic_keys = [k for k in tags if k.startswith("APIC")]
                changed = False
                for key in apic_keys:
                    apic = tags[key]
                    img = Image.open(io.BytesIO(apic.data))
                    if img.width == img.height == 1000:
                        continue
                    buf = io.BytesIO()
                    crop_to_square(img).save(buf, format="JPEG", quality=95)
                    tags[key] = APIC(encoding=apic.encoding, mime="image/jpeg", type=apic.type, desc=apic.desc, data=buf.getvalue())
                    changed = True
                    
                # Add TRCK tag
                if self.playlist_index is not None:
                    from mutagen.id3 import TRCK
                    track_str = str(self.playlist_index)
                    if self.playlist_count:
                        track_str += f"/{self.playlist_count}"
                    tags["TRCK"] = TRCK(encoding=3, text=[track_str])
                    changed = True
                    self.to_screen(f"Set MP3 track number to {track_str}")
                    
                if changed:
                    tags.save(v2_version=3)
                    self.to_screen("Successfully fixed MP3 tags/cover.")
            except Exception as e:
                self.to_screen(f"Error fixing MP3 cover: {e}")
                
        elif ext == '.flac' and FLAC:
            self.to_screen("Fixing FLAC cover with mutagen...")
            try:
                audio = FLAC(filepath)
                pictures = audio.pictures
                changed = False
                for pic in pictures:
                    img = Image.open(io.BytesIO(pic.data))
                    if img.width == img.height == 1000:
                        continue
                    buf = io.BytesIO()
                    crop_to_square(img).save(buf, format="JPEG", quality=95)
                    pic.data, pic.mime = buf.getvalue(), "image/jpeg"
                    pic.width, pic.height, pic.depth = 1000, 1000, 24
                    changed = True
                if changed:
                    audio.clear_pictures()
                    for pic in pictures:
                        audio.add_picture(pic)
                        
                # Add tracknumber tag
                if self.playlist_index is not None:
                    track_str = str(self.playlist_index)
                    if self.playlist_count:
                        track_str += f"/{self.playlist_count}"
                    audio["tracknumber"] = [track_str]
                    changed = True
                    self.to_screen(f"Set FLAC track number to {track_str}")
                    
                if changed:
                    audio.save()
                    self.to_screen("Successfully fixed FLAC tags/cover.")
            except Exception as e:
                self.to_screen(f"Error fixing FLAC tags/cover: {e}")
                
        # Fix file timestamp for playlist sorting
        if self.playlist_index is not None:
            import time
            try:
                base_time = time.time()
                # Subtract a day then add index seconds to ensure proper relative sorting
                # independent of download duration
                new_time = base_time - 86400 + self.playlist_index
                os.utime(filepath, (new_time, new_time))
                self.to_screen(f"Adjusted file timestamp for sorting (index {self.playlist_index})")
            except Exception as e:
                self.to_screen(f"Error adjusting timestamp: {e}")
                
        return [], info

class MediaDownloader:
    def __init__(self, output_dir: str = "downloads"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _map_quality(self, quality: str) -> str:
        if quality in ("Best video", "Best", "Source (Best)"):
            return 'bestvideo+bestaudio/best'
        elif quality in ("Worst", "Worst Audio"):
            return 'worst'
        elif quality in ("Audio only (MP3)", "Best Audio"):
            return 'bestaudio/best'
        elif quality == "Video only (no audio)":
            return 'bestvideo'
        
        # Resolutions like "1080p (Full HD)" -> 1080
        import re
        match = re.search(r'(\d+)p', quality)
        if match:
            height = match.group(1)
            return f'bestvideo[height<={height}]+bestaudio/best'
            
        return 'bestvideo+bestaudio/best'

    def download(self, url: str, media_type: str = "video", quality: str = "Best", cookies: Optional[Dict[str, Any]] = None, subtitles: Optional[Dict[str, Any]] = None, progress_callback: Optional[Callable] = None, playlist_index: int = None, playlist_count: int = None) -> bool:
        """Download media from the given URL."""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # Download thumbnail only if format is audio and quality is Best Audio
        embed_thumbnail = True
        download_thumbnail_only = False
        
        outtmpl = os.path.join(self.output_dir, '%(title)s - %(artist,uploader,creator,channel)s.%(ext)s')
        
        ydl_opts = {
            'outtmpl': outtmpl,
            'writethumbnail': embed_thumbnail or download_thumbnail_only,
            'quiet': False,
            'no_warnings': True,
            'retries': 15,
            'fragment_retries': 15,
            'retry_sleep_functions': {'http': lambda n: min(4 * 2 ** n, 60)},
            'socket_timeout': 30,
            'ignoreerrors': True,
            'convertthumbnails': 'jpg',
            'parse_metadata': ['%(artist,uploader,creator,channel)s:%(meta_artist)s'],
        }
        
        class YtDlpLogger:
            def __init__(self, log_path, parent):
                self.log_path = log_path
                self.parent = parent
            def debug(self, msg):
                if "has already been recorded in the archive" in msg.lower() or "has already been downloaded" in msg.lower():
                    self.parent.was_skipped = True
            def warning(self, msg): pass
            def error(self, msg):
                import re
                clean_msg = re.sub(r'\x1b\[[0-9;]*m', '', msg)
                self.parent.last_error = clean_msg
                import datetime
                try:
                    with open(self.log_path, "a", encoding="utf-8") as f:
                        f.write(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {clean_msg}\n")
                except: pass
                
        # Setup global app logs
        from core.settings import get_app_data_dir
        log_file = get_app_data_dir() / "app_logs.txt"
        ydl_opts['logger'] = YtDlpLogger(log_file, self)

        # Cookies
        if cookies and cookies.get('use'):
            if cookies.get('source') == 'browser':
                browser = cookies.get('browser')
                if browser:
                    ydl_opts['cookiesfrombrowser'] = (browser,)
            elif cookies.get('source') == 'file':
                cookie_file = cookies.get('file')
                if cookie_file and os.path.exists(cookie_file):
                    ydl_opts['cookiefile'] = cookie_file

        # Playlist Archive (skip downloaded)
        if playlist_index is not None:
            archive_path = os.path.join(self.output_dir, "downloaded_archive.txt")
            ydl_opts['download_archive'] = archive_path
            
            # Hide archive file on Windows if it's newly created
            if sys.platform == 'win32' and not os.path.exists(archive_path):
                # Write an empty file so we can hide it immediately
                with open(archive_path, 'w') as f: pass
                import ctypes
                try: ctypes.windll.kernel32.SetFileAttributesW(archive_path, 0x02)
                except Exception: pass

        # Subtitles
        if subtitles and subtitles.get('download'):
            ydl_opts['writesubtitles'] = True
            langs = subtitles.get('langs', 'all').strip()
            if langs.lower() == 'all' or not langs:
                ydl_opts['subtitleslangs'] = ['all']
            else:
                ydl_opts['subtitleslangs'] = [l.strip() for l in langs.split(',')]
            ydl_opts['embedsubtitles'] = True

        # Progress hook
        if progress_callback:
            def hook(d):
                progress_callback(d)
            ydl_opts['progress_hooks'] = [hook]

        if download_thumbnail_only:
            ydl_opts['skip_download'] = True
        else:
            if media_type == "audio" or quality in ("Audio only (MP3)", "Best Audio"):
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
                if embed_thumbnail:
                    ydl_opts['postprocessors'].append({
                        'key': 'FFmpegThumbnailsConvertor',
                        'format': 'jpg',
                    })
            else:
                ydl_opts['format'] = self._map_quality(quality)
                ydl_opts['merge_output_format'] = 'mp4'
                
                if embed_thumbnail:
                    ydl_opts['postprocessors'] = [{
                        'key': 'EmbedThumbnail',
                    }, {
                         'key': 'FFmpegMetadata',
                         'add_metadata': True,
                     }]
                     
                if subtitles and subtitles.get('download'):
                    # Ensure Subtitles PP is added correctly
                    ydl_opts.setdefault('postprocessors', []).append({
                        'key': 'FFmpegEmbedSubtitle'
                    })

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                is_audio = (media_type == "audio" or quality in ("Audio only (MP3)", "Best Audio"))
                if is_audio and embed_thumbnail and not download_thumbnail_only:
                    ydl.add_post_processor(EmbedThumbnailPP(ydl), when='post_process')
                    ydl.add_post_processor(FFmpegMetadataPP(ydl, add_metadata=True), when='post_process')
                    ydl.add_post_processor(MutagenCoverFixPP(ydl, playlist_index=playlist_index, playlist_count=playlist_count), when='post_process')
                    
                self.last_error = ""
                self.was_skipped = False
                retcode = ydl.download([url])
            
            success = retcode == 0
            if not success and not self.last_error:
                self.last_error = "Unknown error occurred (see console or logs)."
            return success, self.last_error, getattr(self, 'was_skipped', False)
        except Exception as e:
            print(f"Download error: {e}")
            return False, str(e), False
