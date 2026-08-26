import os
import re
import time
from pathlib import Path
from core.playlists_manager import PlaylistsManager
from core.downloader import (
    clean_song_title,
    clean_artist_name,
    translit_both_ways,
    extract_significant_version_tags,
    read_stem_vid_map,
    read_stem_all_vids_map,
)

MEDIA_EXTS = {'.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac', '.alac'}


class PlaylistComparator:
    """Scans and compares tracks across tracked playlist folders to find duplicates and intersections."""

    def __init__(self, playlists_mgr: PlaylistsManager = None):
        self.pm = playlists_mgr or PlaylistsManager()
        self.pl_index = {}  # pl_title -> list of track dicts

    def scan_all_playlists(self) -> dict:
        """Scan all tracked playlist folders and build a live memory index of all audio files."""
        playlists = self.pm.get_all()
        pl_index = {}

        for p in playlists:
            title = p.get('title', 'Untitled Playlist')
            folder = p.get('folder_path', '')
            if not folder or not os.path.exists(folder):
                continue

            stem_vid = read_stem_vid_map(folder)
            stem_all_vids = read_stem_all_vids_map(folder)
            tracks = []

            try:
                for entry in os.scandir(folder):
                    if entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in MEDIA_EXTS:
                            stem = os.path.splitext(entry.name)[0]
                            vid = stem_vid.get(stem, '')
                            all_vids = set(stem_all_vids.get(stem, set()))
                            if vid:
                                all_vids.add(vid)
                            tags = extract_significant_version_tags(stem)

                            if ' - ' in stem:
                                parts = stem.split(' - ', 1)
                                artist = parts[0].strip()
                                song_title = parts[1].strip()
                            else:
                                artist = ''
                                song_title = stem.strip()

                            clean_t = clean_song_title(song_title, artist)
                            clean_a = clean_artist_name(artist)
                            ct_vars = translit_both_ways(clean_t)
                            ca_vars = translit_both_ways(clean_a)

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
                                'ct_vars': ct_vars,
                                'ca_vars': ca_vars,
                                'vid': vid,
                                'vids': all_vids,
                                'tags': tags,
                                'playlist': title
                            })
            except Exception as e:
                print(f"Error scanning playlist folder '{folder}': {e}")

            pl_index[title] = tracks

        self.pl_index = pl_index
        return pl_index

    @staticmethod
    def are_tracks_matching(t1: dict, t2: dict) -> bool:
        """Strict matching between two local tracks using video IDs and clean metadata.
        1. Video ID match (supports dual-IDs: original and fallback).
        2. Strict version tags match (original vs remix never match).
        3. Clean Title & Artist match (using transliteration and generic publishers).
        """
        # 1. Multi-ID match (covers original playlist ID and fallback ID)
        vids1 = t1.get('vids') or set()
        vids2 = t2.get('vids') or set()
        if vids1 and vids2 and (vids1 & vids2):
            return True

        # 2. Strict Version Tag guard
        tags1 = t1.get('tags') or set()
        tags2 = t2.get('tags') or set()
        if tags1 != tags2:
            return False

        # 3. Clean Title matching (use precomputed transliteration variants)
        ct1 = t1.get('clean_title') or ''
        ct2 = t2.get('clean_title') or ''
        if not ct1 or not ct2:
            return False

        ct1_vars = t1.get('ct_vars') or translit_both_ways(ct1)
        ct2_vars = t2.get('ct_vars') or translit_both_ways(ct2)
        if not (ct1_vars & ct2_vars):
            match_sub = False
            for c1 in ct1_vars:
                for c2 in ct2_vars:
                    if c1 and c2 and len(c1) >= 6 and len(c2) >= 6:
                        if c1 in c2 or c2 in c1:
                            match_sub = True
                            break
                if match_sub:
                    break
            if not match_sub:
                return False

        # 4. Artist matching (use precomputed transliteration variants)
        ca1 = t1.get('clean_artist') or ''
        ca2 = t2.get('clean_artist') or ''
        generic = {'topic', 'release', 'variousartists', 'soundtrack', 'records', 'music', 'official', ''}

        ca1_vars = t1.get('ca_vars') or translit_both_ways(ca1)
        ca2_vars = t2.get('ca_vars') or translit_both_ways(ca2)

        if not ca1 or not ca2 or (ca1_vars & generic) or (ca2_vars & generic):
            return True

        if ca1_vars & ca2_vars:
            return True

        for a1 in ca1_vars:
            for a2 in ca2_vars:
                if a1 and a2 and (a1 in a2 or a2 in a1):
                    return True

        return False

    def compare_single_playlist(self, target_title: str) -> list[dict]:
        """Find all tracks in target_title that also exist in at least one other playlist.
        Uses inverted hash indexing for instant O(1) matching across thousands of tracks.
        """
        if not self.pl_index:
            self.scan_all_playlists()

        target_tracks = self.pl_index.get(target_title, [])
        if not target_tracks:
            return []

        # Build fast inverted index of all other playlists
        vid_map = {}        # vid -> list of (pl_title, ot)
        title_map = {}      # title_var -> list of (pl_title, ot)

        for pl_title, other_tracks in self.pl_index.items():
            if pl_title == target_title:
                continue
            for ot in other_tracks:
                for v in ot.get('vids', set()):
                    if v:
                        vid_map.setdefault(v, []).append((pl_title, ot))
                for tv in ot.get('ct_vars', set()):
                    if tv and len(tv) >= 3:
                        title_map.setdefault(tv, []).append((pl_title, ot))

        overlaps = []

        for tt in target_tracks:
            found_in = {}  # pl_title -> ot

            # 1. Instant lookup by Video ID
            for v in tt.get('vids', set()):
                if v in vid_map:
                    for pl_title, ot in vid_map[v]:
                        if pl_title not in found_in:
                            found_in[pl_title] = ot

            # 2. Instant lookup by clean title variants
            for tv in tt.get('ct_vars', set()):
                if tv in title_map:
                    for pl_title, ot in title_map[tv]:
                        if pl_title in found_in:
                            continue
                        if self.are_tracks_matching(tt, ot):
                            found_in[pl_title] = ot

            # 3. Fallback substring search only if not matched and title is long
            if not found_in:
                for tv_t in tt.get('ct_vars', set()):
                    if len(tv_t) >= 8:
                        for tv_o, ot_list in title_map.items():
                            if len(tv_o) >= 8 and (tv_t in tv_o or tv_o in tv_t):
                                for pl_title, ot in ot_list:
                                    if pl_title not in found_in and self.are_tracks_matching(tt, ot):
                                        found_in[pl_title] = ot
                                if found_in:
                                    break
                    if found_in:
                        break

            if found_in:
                overlaps.append({
                    'primary_track': tt,
                    'other_playlists': [{'playlist': p, 'track': t} for p, t in found_in.items()],
                    'total_count': len(found_in) + 1
                })

        return overlaps

    def compare_two_playlists(self, title_a: str, title_b: str) -> dict:
        """Compare exactly two playlists A and B with indexed candidate lookup for instant results."""
        if not self.pl_index:
            self.scan_all_playlists()

        tracks_a = self.pl_index.get(title_a, [])
        tracks_b = self.pl_index.get(title_b, [])

        # Build candidate indices for B
        b_by_vid = {}
        b_by_title = {}
        for idx_b, tb in enumerate(tracks_b):
            for v in tb.get('vids', set()):
                if v:
                    b_by_vid.setdefault(v, []).append(idx_b)
            for tv in tb.get('ct_vars', set()):
                if tv and len(tv) >= 3:
                    b_by_title.setdefault(tv, []).append(idx_b)

        common = []
        matched_b_indices = set()
        matched_a_indices = set()

        for idx_a, ta in enumerate(tracks_a):
            candidate_b_indices = []

            # 1. Check VID candidates
            for v in ta.get('vids', set()):
                if v in b_by_vid:
                    candidate_b_indices.extend(b_by_vid[v])

            # 2. Check title variant candidates
            for tv in ta.get('ct_vars', set()):
                if tv in b_by_title:
                    candidate_b_indices.extend(b_by_title[tv])

            # 3. Check substring only for long titles
            if not candidate_b_indices:
                for tv_a in ta.get('ct_vars', set()):
                    if len(tv_a) >= 8:
                        for tv_b, b_list in b_by_title.items():
                            if len(tv_b) >= 8 and (tv_a in tv_b or tv_b in tv_a):
                                candidate_b_indices.extend(b_list)
                                break
                    if candidate_b_indices:
                        break

            # Test candidates
            for idx_b in candidate_b_indices:
                if idx_b in matched_b_indices:
                    continue
                tb = tracks_b[idx_b]
                if self.are_tracks_matching(ta, tb):
                    common.append({
                        'track_a': ta,
                        'track_b': tb,
                        'title': ta.get('title') or tb.get('title'),
                        'artist': ta.get('artist') or tb.get('artist'),
                        'display_name': ta.get('filename') or tb.get('filename'),
                        'vid': ta.get('vid') or tb.get('vid'),
                    })
                    matched_b_indices.add(idx_b)
                    matched_a_indices.add(idx_a)
                    break

        only_a = [ta for idx, ta in enumerate(tracks_a) if idx not in matched_a_indices]
        only_b = [tb for idx, tb in enumerate(tracks_b) if idx not in matched_b_indices]

        stats = {
            'total_a': len(tracks_a),
            'total_b': len(tracks_b),
            'common_count': len(common),
            'only_a_count': len(only_a),
            'only_b_count': len(only_b),
            'overlap_pct_a': round(100.0 * len(common) / max(1, len(tracks_a)), 1) if tracks_a else 0,
            'overlap_pct_b': round(100.0 * len(common) / max(1, len(tracks_b)), 1) if tracks_b else 0,
        }

        return {
            'title_a': title_a,
            'title_b': title_b,
            'common': common,
            'only_a': only_a,
            'only_b': only_b,
            'stats': stats
        }

    def compare_all_playlists(self) -> list[dict]:
        """Group all duplicate tracks across the entire library into clusters."""
        if not self.pl_index:
            self.scan_all_playlists()

        clusters: list[dict] = []
        vid_index: dict[str, int] = {}    # vid -> cluster_index (O(1) lookup)
        title_index: dict[str, int] = {}  # clean_title -> cluster_index (O(1) lookup)

        for pl_title, tracks in self.pl_index.items():
            for t in tracks:
                all_vids = t.get('vids') or {t.get('vid')} - {''}
                ct = t.get('clean_title')
                ca = t.get('clean_artist')
                tags = t.get('tags') or set()

                matched_idx = None

                # 1. Lookup by video ID (checking all associated IDs)
                for v in all_vids:
                    if v and v in vid_index:
                        matched_idx = vid_index[v]
                        break

                # 2. Lookup by clean title and verify version tags
                if matched_idx is None and ct and ct in title_index:
                    cand_idx = title_index[ct]
                    cand_cluster = clusters[cand_idx]
                    cand_tags = cand_cluster.get('tags', set())
                    if cand_tags == tags:
                        matched_idx = cand_idx

                if matched_idx is not None:
                    clusters[matched_idx]['tracks'].append(t)
                    for v in all_vids:
                        if v:
                            vid_index[v] = matched_idx
                else:
                    new_idx = len(clusters)
                    cluster = {
                        'title': t['title'],
                        'artist': t['artist'],
                        'clean_title': ct,
                        'clean_artist': ca,
                        'tags': tags,
                        'tracks': [t]
                    }
                    clusters.append(cluster)
                    for v in all_vids:
                        if v:
                            vid_index[v] = new_idx
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
