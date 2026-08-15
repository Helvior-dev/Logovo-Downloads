import yt_dlp
from core.downloader import clean_media_url

def get_video_preview(url: str) -> dict:
    clean_url = clean_media_url(url)
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'color': 'no_color',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            
            if info.get('_type') == 'playlist' or 'entries' in info:
                entries = []
                playlist_thumb = None
                if info.get('thumbnails'):
                    playlist_thumb = info.get('thumbnails')[-1].get('url')
                elif info.get('thumbnail'):
                    playlist_thumb = info.get('thumbnail')

                for entry in info.get('entries', []):
                    if entry:
                        thumbnail_url = None
                        if entry.get('thumbnails'):
                            thumbnail_url = entry.get('thumbnails')[-1].get('url')
                        elif entry.get('thumbnail'):
                            thumbnail_url = entry.get('thumbnail')
                        
                        entry_id = entry.get('id') or (entry.get('url', '').split('v=')[-1].split('&')[0])
                        if not thumbnail_url and entry_id and len(entry_id) == 11:
                            thumbnail_url = f"https://i.ytimg.com/vi/{entry_id}/hqdefault.jpg"

                        if not playlist_thumb and thumbnail_url:
                            playlist_thumb = thumbnail_url
                            
                        entries.append({
                            'title': entry.get('title', 'Unknown'),
                            'url': entry.get('url', clean_url),
                            'duration': entry.get('duration'),
                            'thumbnail': thumbnail_url,
                            'uploader': entry.get('uploader'),
                            'channel': entry.get('channel')
                        })

                if not playlist_thumb and entries and entries[0].get('thumbnail'):
                    playlist_thumb = entries[0]['thumbnail']

                return {
                    'is_playlist': True,
                    'title': info.get('title', 'Playlist'),
                    'thumbnail': playlist_thumb,
                    'count': len(entries),
                    'entries': entries
                }
            
            # Extract available subtitles for single video
            subs_available = []
            if 'subtitles' in info:
                subs_available.extend(info['subtitles'].keys())
            if 'automatic_captions' in info:
                for k in info['automatic_captions'].keys():
                    if k not in subs_available:
                        subs_available.append(f"{k} (auto)")
            # Extract available formats
            formats_available = set()
            for f in info.get('formats', []):
                vcodec = f.get('vcodec', 'none')
                acodec = f.get('acodec', 'none')
                
                if vcodec != 'none':
                    if 'avc1' in vcodec or 'h264' in vcodec: formats_available.add('Video (H.264)')
                    elif 'hev' in vcodec or 'h265' in vcodec: formats_available.add('Video (H.265)')
                
                if acodec != 'none':
                    if 'mp4a' in acodec: formats_available.add('Audio (M4A)')
                    elif 'opus' in acodec: formats_available.add('Audio (Opus)')
                    elif 'mp3' in acodec: formats_available.add('Audio (MP3)')
            
            formats_available.update(['Audio (Best)', 'Video (Best)', 'Audio (FLAC)', 'Audio (WAV)'])
            
            return {
                'is_playlist': False,
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'subtitles_available': subs_available,
                'formats_available': sorted(list(formats_available)),
                'uploader': info.get('uploader'),
                'channel': info.get('channel'),
                'artist': info.get('artist')
            }
    except Exception as e:
        print(f"Error fetching preview: {e}")
        return None
