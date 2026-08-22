import os
import json
import re
import requests
import yt_dlp
from core.downloader import clean_media_url, is_valid_netscape_cookies, detect_platform_name


def fetch_spotify_metadata(url: str) -> dict | None:
    """Fetch Spotify track, album, or playlist metadata using Spotify's public embed API."""
    clean_u = url.split("?")[0].strip()
    match = re.search(r"spotify\.com/(track|playlist|album|artist)/([a-zA-Z0-9]+)", clean_u)
    if not match:
        return None

    media_type, media_id = match.groups()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    embed_url = f"https://open.spotify.com/embed/{media_type}/{media_id}"
    try:
        r = requests.get(embed_url, headers=headers, timeout=12)
        if r.status_code != 200:
            return None

        match_data = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', r.text)
        if not match_data:
            return None

        data = json.loads(match_data.group(1))
        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        if not entity:
            return None

        title = entity.get("title") or entity.get("name") or "Spotify Media"
        thumb = None
        if entity.get("coverArt", {}).get("sources"):
            thumb = entity["coverArt"]["sources"][0].get("url")
        elif entity.get("visualIdentity", {}).get("image"):
            thumb = entity["visualIdentity"]["image"][0].get("url")

        track_list = entity.get("trackList", [])

        if media_type == "track":
            artist = entity.get("subtitle") or ""
            if not artist and entity.get("artists"):
                artist = entity["artists"][0].get("name", "")
            duration_ms = entity.get("duration", 0)
            track_title = entity.get("title") or entity.get("name") or title
            query = f"{artist} - {track_title}".strip(" - ")
            search_target = f"ytsearch1:{query}"

            return {
                "is_playlist": False,
                "title": f"{artist} - {track_title}" if artist and artist not in track_title else track_title,
                "thumbnail": thumb,
                "duration": duration_ms // 1000 if duration_ms else None,
                "uploader": artist,
                "channel": artist,
                "artist": artist,
                "subtitles_available": [],
                "formats_available": ["Audio (Best)", "Audio (MP3)", "Audio (FLAC)", "Audio (M4A)", "Audio (Opus)", "Audio (WAV)"],
                "url": search_target,
                "original_url": url,
                "platform": "Spotify"
            }
        else:
            entries = []
            for t in track_list:
                t_title = t.get("title", "")
                t_artist = t.get("subtitle", "")
                t_dur = (t.get("duration", 0) or 0) // 1000
                q = f"{t_artist} - {t_title}".strip(" - ")
                entries.append({
                    "title": f"{t_artist} - {t_title}" if t_artist and t_artist not in t_title else t_title,
                    "url": f"ytsearch1:{q}",
                    "duration": t_dur if t_dur > 0 else None,
                    "thumbnail": thumb,
                    "uploader": t_artist or "Spotify",
                    "channel": t_artist or "Spotify",
                    "is_unavailable": False,
                    "spotify_uri": t.get("uri")
                })

            return {
                "is_playlist": True,
                "title": title,
                "thumbnail": thumb,
                "count": len(entries),
                "entries": entries,
                "platform": "Spotify"
            }
    except Exception as e:
        print(f"Error fetching Spotify metadata: {e}")
        return None


def get_video_preview(url: str, cookies: dict = None) -> dict:
    if not url:
        return None
    url = url.strip()

    # Special handling for Spotify links
    if "spotify.com" in url:
        sp_res = fetch_spotify_metadata(url)
        if sp_res:
            return sp_res

    clean_url = clean_media_url(url, keep_list=True)
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
    if cookies and cookies.get('use'):
        if cookies.get('source') == 'browser' and cookies.get('browser'):
            ydl_opts['cookiesfrombrowser'] = (cookies.get('browser'), None, None, None)
        elif cookies.get('source') == 'file' and cookies.get('file'):
            cookie_path = cookies.get('file')
            if cookie_path and is_valid_netscape_cookies(cookie_path):
                ydl_opts['cookiefile'] = cookie_path
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
                        e_title = entry.get('title')
                        entry_id = entry.get('id') or (entry.get('url', '').split('v=')[-1].split('&')[0])
                        is_unavail = False
                        if not e_title or str(e_title).strip() in ('', 'None', 'Unknown', '[Deleted video]', '[Private video]', 'Deleted video', 'Private video'):
                            is_unavail = True
                            e_title = f"[Unavailable / Deleted]"

                        thumbnail_url = None
                        if entry.get('thumbnails'):
                            thumbnail_url = entry.get('thumbnails')[-1].get('url')
                        elif entry.get('thumbnail'):
                            thumbnail_url = entry.get('thumbnail')
                        
                        if not thumbnail_url and entry_id and len(entry_id) == 11:
                            thumbnail_url = f"https://i.ytimg.com/vi/{entry_id}/hqdefault.jpg"

                        if not playlist_thumb and thumbnail_url:
                            playlist_thumb = thumbnail_url
                            
                        track_url = f"https://www.youtube.com/watch?v={entry_id}" if entry_id and len(entry_id) == 11 else clean_media_url(entry.get('url', clean_url))

                        entries.append({
                            'title': e_title,
                            'url': track_url,
                            'duration': entry.get('duration'),
                            'thumbnail': thumbnail_url,
                            'uploader': entry.get('uploader') or ("YouTube" if is_unavail else ""),
                            'channel': entry.get('channel'),
                            'is_unavailable': is_unavail
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
                for k in info['subtitles'].keys():
                    if k not in subs_available:
                        subs_available.append(k)
            if 'automatic_captions' in info:
                # Prioritize common / primary languages
                priority_langs = ['en', 'ru', 'uk', 'orig', 'en-orig']
                for pl in priority_langs:
                    for k in info['automatic_captions'].keys():
                        if k == pl or k.startswith(f"{pl}-"):
                            entry = f"{k} (auto)"
                            if entry not in subs_available and k not in subs_available:
                                subs_available.append(entry)
                # Cap any other auto captions to prevent 150 items spam
                for k in info['automatic_captions'].keys():
                    entry = f"{k} (auto)"
                    if entry not in subs_available and k not in subs_available and len(subs_available) < 12:
                        subs_available.append(entry)
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
