import yt_dlp

def get_video_preview(url: str) -> dict:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if info.get('_type') == 'playlist' or 'entries' in info:
                entries = []
                for entry in info.get('entries', []):
                    if entry:
                        thumbnail_url = None
                        if entry.get('thumbnails'):
                            thumbnail_url = entry.get('thumbnails')[-1].get('url')
                        entries.append({
                            'title': entry.get('title', 'Unknown'),
                            'url': entry.get('url', url),
                            'duration': entry.get('duration'),
                            'thumbnail': thumbnail_url,
                            'uploader': entry.get('uploader'),
                            'channel': entry.get('channel')
                        })
                return {
                    'is_playlist': True,
                    'title': info.get('title', 'Playlist'),
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
            
            return {
                'is_playlist': False,
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'subtitles_available': subs_available
            }
    except Exception as e:
        print(f"Error fetching preview: {e}")
        return None
