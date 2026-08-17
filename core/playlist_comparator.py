import os
import re
import time
from pathlib import Path
from core.playlists_manager import PlaylistsManager
from core.downloader import clean_song_title, clean_artist_name, read_stem_vid_map

MEDIA_EXTS = {'.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac', '.alac'}


class PlaylistComparator:
    """Scans and compares tracks across tracked playlist folders to find duplicates and intersections."""

    def __init__(self, playlists_mgr: PlaylistsManager = None):
        self.pm = playlists_mgr or PlaylistsManager()
        self.pl_index = {} # pl_title -> list of track dicts

    def scan_all_playlists(self) -> dict:
        """Scan all tracked playlist folders and build a memory index of all audio files."""
        playlists = self.pm.get_all()
        pl_index = {}

        for p in playlists:
            title = p.get('title', 'Untitled Playlist')
            folder = p.get('folder_path', '')
            if not folder or not os.path.exists(folder):
                continue

            stem_vid = read_stem_vid_map(folder)
            tracks = []

            try:
                for entry in os.scandir(folder):
                    if entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in MEDIA_EXTS:
                            stem = os.path.splitext(entry.name)[0]
                            vid = stem_vid.get(stem, '')

                            if ' - ' in stem:
                                parts = stem.split(' - ', 1)
                                artist = parts[0].strip()
                                song_title = parts[1].strip()
                            else:
                                artist = ''
                                song_title = stem.strip()

                            clean_t = clean_song_title(song_title, artist)
                            clean_a = clean_artist_name(artist)

                            tracks.append({
                                'filename': entry.name,
                                'stem': stem,
                                'filepath': entry.path,
                                'folder': folder,
                                'size': entry.stat().st_size,
                                'artist': artist,
                                'title': song_title,
                                'clean_title': clean_t,
                                'clean_artist': clean_a,
                                'vid': vid,
                                'playlist': title
                            })
            except Exception as e:
                print(f"Error scanning playlist folder '{folder}': {e}")

            pl_index[title] = tracks

        self.pl_index = pl_index
        return pl_index

    def compare_single_playlist(self, target_title: str) -> list[dict]:
        """Find all tracks in target_title that also exist in at least one other playlist."""
        if not self.pl_index:
            self.scan_all_playlists()

        target_tracks = self.pl_index.get(target_title, [])
        overlaps = []

        for tt in target_tracks:
            found_in = []
            t_clean_t = tt['clean_title']
            t_clean_a = tt['clean_artist']
            t_vid = tt['vid']

            for pl_title, other_tracks in self.pl_index.items():
                if pl_title == target_title:
                    continue

                for ot in other_tracks:
                    matched = False
                    if t_vid and ot['vid'] and t_vid == ot['vid']:
                        matched = True
                    elif t_clean_t and ot['clean_title'] and t_clean_t == ot['clean_title']:
                        ca1 = t_clean_a
                        ca2 = ot['clean_artist']
                        if not ca1 or not ca2 or ca1 in ('topic', 'release') or ca2 in ('topic', 'release') or ca1 == ca2 or ca1 in ca2 or ca2 in ca1:
                            matched = True

                    if matched:
                        found_in.append({
                            'playlist': pl_title,
                            'track': ot
                        })
                        break

            if found_in:
                overlaps.append({
                    'primary_track': tt,
                    'other_playlists': found_in,
                    'total_count': len(found_in) + 1
                })

        return overlaps

    def compare_all_playlists(self) -> list[dict]:
        """Group all duplicate tracks across the entire library into clusters."""
        if not self.pl_index:
            self.scan_all_playlists()

        clusters: list[dict] = []
        vid_index: dict[str, int] = {}    # vid -> cluster_index (O(1) lookup)
        title_index: dict[str, int] = {}  # clean_title -> cluster_index (O(1) lookup)

        for pl_title, tracks in self.pl_index.items():
            for t in tracks:
                vid = t['vid']
                ct = t['clean_title']
                ca = t['clean_artist']

                matched_idx = None

                # O(1) lookup by video ID
                if vid and vid in vid_index:
                    matched_idx = vid_index[vid]

                # O(1) lookup by clean title
                if matched_idx is None and ct and ct in title_index:
                    matched_idx = title_index[ct]

                if matched_idx is not None:
                    clusters[matched_idx]['tracks'].append(t)
                else:
                    new_idx = len(clusters)
                    cluster = {
                        'title': t['title'],
                        'artist': t['artist'],
                        'clean_title': ct,
                        'clean_artist': ca,
                        'tracks': [t]
                    }
                    clusters.append(cluster)
                    if vid:
                        vid_index[vid] = new_idx
                    if ct:
                        title_index[ct] = new_idx

        # Only return clusters that appear in 2 or more DIFFERENT playlists
        results = []
        for c in clusters:
            unique_pls = {t['playlist'] for t in c['tracks']}
            if len(unique_pls) >= 2:
                c['unique_playlists'] = sorted(list(unique_pls))
                c['total_playlists'] = len(unique_pls)
                results.append(c)

        # Sort by most overlapping first
        results.sort(key=lambda x: x['total_playlists'], reverse=True)
        return results
