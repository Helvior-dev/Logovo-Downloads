import re
from pathlib import Path

from core.playlist_index import hide_file, unhide_file, update_stem_vid_map
from core.track_matching import (
    clean_artist_name,
    clean_song_title,
    extract_significant_version_tags,
    translit_both_ways,
)

def is_safe_autoheal_match(orphan_item: dict, entry: dict) -> bool:
    """Strictly evaluates whether an orphaned local file corresponds to a missing playlist entry.
    Enforces strict safety rules to completely eliminate false positives:
      1. Version tags MUST match identically (e.g. remix vs original never match).
      2. Artist matching (clean_artist_name with transliteration, no conflicting artists).
      3. Clean title token matching (must have high confidence, matching tokens).
      4. Duration guard: if both durations are known, diff must be <= 20 seconds.
    """
    orphan_stem = orphan_item.get('title') or Path(orphan_item.get('filename', '')).stem
    entry_title = entry.get('title') or ''
    entry_author = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ''

    if not orphan_stem or not entry_title:
        return False

    # 1. Strict Version Tags Matching
    orphan_tags = extract_significant_version_tags(orphan_stem)
    entry_tags = extract_significant_version_tags(entry_title)
    if orphan_tags != entry_tags:
        return False

    # 2. Duration Guard
    entry_dur = entry.get('duration')
    orphan_dur = orphan_item.get('duration')
    if entry_dur and orphan_dur:
        try:
            if abs(float(entry_dur) - float(orphan_dur)) > 20:
                return False
        except (ValueError, TypeError):
            pass

    # 3. Artist Matching
    stem_parts = [p.strip() for p in re.split(r'\s+[-–—]\s*|\s*[-–—]\s+', orphan_stem) if p.strip()]
    file_author = stem_parts[0] if len(stem_parts) >= 2 else ""

    clean_entry_a = clean_artist_name(entry_author)
    clean_pure_entry_a = clean_artist_name(re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', entry_author).strip())
    clean_file_a = clean_artist_name(file_author) if file_author else ""

    entry_a_vars = (translit_both_ways(clean_entry_a) | translit_both_ways(clean_pure_entry_a)) - {''}
    generic = {'topic', 'release', 'variousartists', 'soundtrack', ''}

    author_ok = False
    if not clean_entry_a or clean_entry_a in generic:
        author_ok = True
    elif not clean_file_a:
        author_ok = any(var and var in orphan_stem.lower() for var in entry_a_vars) or len(entry_title) >= 10
    else:
        file_a_vars = translit_both_ways(clean_file_a)
        if entry_a_vars & file_a_vars:
            author_ok = True
        elif any(ea and fa and (ea in fa or fa in ea) for ea in entry_a_vars for fa in file_a_vars if len(min(ea, fa)) >= 3):
            author_ok = True

    if not author_ok:
        return False

    # 4. Clean Title Matching
    clean_t_entry = clean_song_title(entry_title, entry_author)
    title_candidates = []
    if len(stem_parts) == 1:
        title_candidates.append(stem_parts[0])
    elif len(stem_parts) == 2:
        title_candidates.append(stem_parts[1])
        title_candidates.append(stem_parts[0])
    else:
        title_candidates.append(' - '.join(stem_parts[1:]))
        title_candidates.append(stem_parts[1])
        title_candidates.append(stem_parts[-1])
    title_candidates.append(orphan_stem)

    title_matched = False
    clean_entry_vars = translit_both_ways(clean_t_entry)
    for cand in title_candidates:
        clean_cand = clean_song_title(cand, file_author or entry_author)
        clean_cand_vars = translit_both_ways(clean_cand)
        if clean_entry_vars & clean_cand_vars:
            title_matched = True
            break
        for ev in clean_entry_vars:
            for cv in clean_cand_vars:
                if ev and cv and len(ev) >= 6 and len(cv) >= 6:
                    if ev in cv or cv in ev:
                        title_matched = True
                        break
            if title_matched:
                break
        if title_matched:
            break

    return title_matched


def plan_autoheal_orphans_and_missing(
    orphaned_files: list[dict],
    missing_entries: list[dict],
) -> tuple[list[dict], list[dict], list[tuple[dict, dict]]]:
    """Find safe one-to-one orphan/missing matches without modifying disk state."""
    if not orphaned_files or not missing_entries:
        return orphaned_files, missing_entries, []

    orphan_to_missing: dict[int, list[int]] = {}
    missing_to_orphan: dict[int, list[int]] = {}

    for o_idx, o_item in enumerate(orphaned_files):
        for m_idx, m_entry in enumerate(missing_entries):
            if is_safe_autoheal_match(o_item, m_entry):
                orphan_to_missing.setdefault(o_idx, []).append(m_idx)
                missing_to_orphan.setdefault(m_idx, []).append(o_idx)

    # Enforce strict 1-to-1 matching:
    healed_pairs = []
    for o_idx, m_list in orphan_to_missing.items():
        if len(m_list) == 1:
            m_idx = m_list[0]
            if len(missing_to_orphan.get(m_idx, [])) == 1:
                healed_pairs.append((o_idx, m_idx))

    if not healed_pairs:
        return orphaned_files, missing_entries, []

    healed_o_indices = set()
    healed_m_indices = set()

    for o_idx, m_idx in healed_pairs:
        healed_o_indices.add(o_idx)
        healed_m_indices.add(m_idx)

    remaining_orphans = [o for i, o in enumerate(orphaned_files) if i not in healed_o_indices]
    remaining_missing = [m for i, m in enumerate(missing_entries) if i not in healed_m_indices]
    matched_items = [(orphaned_files[o_idx], missing_entries[m_idx]) for o_idx, m_idx in healed_pairs]

    return remaining_orphans, remaining_missing, matched_items


def apply_autoheal_pairs(output_dir: Path | str, healed_pairs: list[tuple[dict, dict]]) -> None:
    """Persist already-reviewed safe matches to the playlist ID map and archive."""
    out = Path(output_dir)
    for orphan_item, entry in healed_pairs:
        entry_vid = entry.get('id')
        if not entry_vid:
            url = entry.get('url', '')
            if 'v=' in url:
                entry_vid = url.split('v=')[-1].split('&')[0]
            elif 'youtu.be/' in url:
                entry_vid = url.split('youtu.be/')[-1].split('?')[0]

        stem = orphan_item.get('title') or Path(orphan_item.get('filename', '')).stem
        candidate_vid = orphan_item.get('vid') if orphan_item.get('vid') != 'Local Copy' else None
        if not entry_vid or not stem:
            continue

        update_stem_vid_map(out, stem, vid=candidate_vid or entry_vid, original_vid=entry_vid)
        archive_file = out / "downloaded_archive.txt"
        if archive_file.exists():
            try:
                unhide_file(archive_file)
                with open(archive_file, "a", encoding="utf-8") as archive:
                    archive.write(f"youtube {entry_vid}\n")
                hide_file(archive_file)
            except Exception:
                pass


def autoheal_orphans_and_missing(
    output_dir: Path | str,
    orphaned_files: list[dict],
    missing_entries: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Preserve the existing mutating API for non-preview callers."""
    remaining_orphans, remaining_missing, healed_pairs = plan_autoheal_orphans_and_missing(
        orphaned_files,
        missing_entries,
    )
    apply_autoheal_pairs(output_dir, healed_pairs)
    return remaining_orphans, remaining_missing
