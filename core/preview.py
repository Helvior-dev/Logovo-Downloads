import yt_dlp

def get_video_preview(url: str) -> dict:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': 'in_playlist',
        'color': 'no_color',
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
            
            formats_available.update(['Audio (Best)', 'Video (Best)', 'Audio (FLAC)'])
            
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
