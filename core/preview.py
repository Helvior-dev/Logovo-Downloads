import yt_dlp

def get_video_preview(url: str) -> dict:
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Extract available subtitles
            subs_available = []
            if 'subtitles' in info:
                subs_available.extend(info['subtitles'].keys())
            if 'automatic_captions' in info:
                # Add auto captions but mark them
                for k in info['automatic_captions'].keys():
                    if k not in subs_available:
                        subs_available.append(f"{k} (auto)")
            
            return {
                'title': info.get('title', 'Unknown Title'),
                'thumbnail': info.get('thumbnail'),
                'duration': info.get('duration'),
                'is_playlist': 'entries' in info,
                'subtitles_available': subs_available
            }
    except Exception as e:
        print(f"Error fetching preview: {e}")
        return None
