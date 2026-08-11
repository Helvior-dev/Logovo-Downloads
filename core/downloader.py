import yt_dlp
import os
from typing import Dict, Any, Callable, Optional
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.postprocessor import EmbedThumbnailPP, FFmpegMetadataPP
from PIL import Image

class SquareCropPP(PostProcessor):
    def run(self, info):
        self.to_screen("Cropping thumbnail to square using PIL...")
        for thumb in info.get('thumbnails', []):
            filepath = thumb.get('filepath')
            if filepath and os.path.exists(filepath):
                try:
                    img = Image.open(filepath)
                    width, height = img.size
                    if width != height:
                        new_size = min(width, height)
                        left = (width - new_size) / 2
                        top = (height - new_size) / 2
                        right = (width + new_size) / 2
                        bottom = (height + new_size) / 2
                        img = img.crop((left, top, right, bottom))
                        img.save(filepath)
                        self.to_screen(f"Successfully cropped thumbnail to {new_size}x{new_size}")
                except Exception as e:
                    self.to_screen(f"Error cropping thumbnail: {e}")
        return [], info

class MediaDownloader:
    def __init__(self, output_dir: str = "downloads"):
        self.output_dir = output_dir
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def _map_quality(self, quality: str) -> str:
        if quality == "Best video" or quality == "Best":
            return 'bestvideo+bestaudio/best'
        elif quality == "Worst":
            return 'worst'
        elif quality == "Audio only (MP3)":
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

    def download(self, url: str, 
                 media_type: str = "video", 
                 quality: str = "Best video",
                 cookies: dict = None,
                 subtitles: dict = None,
                 embed_thumbnail: bool = True,
                 download_thumbnail_only: bool = False,
                 progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> bool:
        
        outtmpl = os.path.join(self.output_dir, '%(playlist_index)s - %(title)s.%(ext)s') if 'playlist' in url else os.path.join(self.output_dir, '%(title)s.%(ext)s')
        
        ydl_opts = {
            'outtmpl': outtmpl,
            'writethumbnail': embed_thumbnail or download_thumbnail_only,
            'quiet': False,
            'no_warnings': True,
        }

        # Cookies
        if cookies and cookies.get('use'):
            if cookies.get('source') == 'browser':
                ydl_opts['cookiesfrombrowser'] = (cookies.get('browser', 'chrome'),)
            elif cookies.get('source') == 'file' and cookies.get('file'):
                ydl_opts['cookiefile'] = cookies.get('file')

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
            if media_type == "audio" or quality == "Audio only (MP3)":
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
                is_audio = (media_type == "audio" or quality == "Audio only (MP3)")
                if is_audio and embed_thumbnail and not download_thumbnail_only:
                    ydl.add_post_processor(SquareCropPP(ydl), when='post_process')
                    ydl.add_post_processor(EmbedThumbnailPP(ydl), when='post_process')
                    ydl.add_post_processor(FFmpegMetadataPP(ydl, add_metadata=True), when='post_process')
                    
                ydl.download([url])
            return True
        except Exception as e:
            print(f"Download error: {e}")
            return False
