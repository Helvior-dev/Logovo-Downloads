import re
import unicodedata
from typing import Optional

def normalize_unicode_text(text: str) -> str:
    """Normalize Unicode stylistic fonts (small caps, fullwidth, gothic) into standard Latin characters."""
    small_caps = {
        'ᴀ': 'a', 'ʙ': 'b', 'ᴄ': 'c', 'ᴅ': 'd', 'ᴇ': 'e', 'ꜰ': 'f', 'ɢ': 'g', 'ʜ': 'h', 'ɪ': 'i',
        'ᴊ': 'j', 'ᴋ': 'k', 'ʟ': 'l', 'ᴍ': 'm', 'ɴ': 'n', 'ᴏ': 'o', 'ᴘ': 'p', 'ǫ': 'q', 'ʀ': 'r',
        'ꜱ': 's', 'ᴛ': 't', 'ᴜ': 'u', 'ᴠ': 'v', 'ᴡ': 'w', 'x': 'x', 'ʏ': 'y', 'ᴢ': 'z',
    }
    t = text or ''
    res = ''
    for ch in t:
        res += small_caps.get(ch, ch)
    res = unicodedata.normalize('NFKD', res)
    return res


def clean_song_title(title: str, author: str = "") -> str:
    """Strip only pure metadata video noise (preserving remixes, extended, feats)."""
    t = (title or "").strip()
    t = normalize_unicode_text(t)
    t = re.sub(r'[\u200b\u200c\u200d\ufeff\u00a0]+', '', t)
    noise_patterns = [
        r'[\(\[\{]\s*(?:official\s*(?:music\s*)?video|music\s*video|official\s*audio|official\s*visualizer|official\s*hd\s*music\s*video|official|audio|hd|hq|4k|4k\s*upgrade|remaster(?:ed)?(?:\s*\d+)?|\d{4}\s*remaster|mixed|video|clip|lyrics?|visualizer|bonus\s*edition|bonus\s*track|original\s*mix|album\s*version|read\s+desc|out\s+on\s+spotify[!]*|slowed|reverb|resurgence)[^\)\]\}]*[\)\]\}]',
        r'[\(\[\{]\s*\b(?:19\d\d|20\d\d)\b\s*[\)\]\}]',
        r'[\(\[\{]\s*(?:feat|ft|with)\.?\s+[^)\]\}]+[\)\]\}]',
        r'\(from\s+the\s+series\s+Arcane\s+League\s+of\s+Legends\)',
        r'[\(\[\{]\s*from\s+[^)\]\}]+[\)\]\}]',
        r'\[[A-Za-z0-9_\s-]+(?:Channel|Topic|Music|Records|Release|Audio|Video|Visualizer)\]',
        r'\[[A-Za-z0-9_-]+\]',
    ]
    for pat in noise_patterns:
        t = re.sub(pat, '', t, flags=re.IGNORECASE)

    # Strip feat / with in title
    t = re.sub(r'\b(?:feat|ft|with)\.?\s+[a-zA-Z0-9\u0400-\u04FF\s]+(?=[\(\[\{]|$)', '', t, flags=re.IGNORECASE)
    t = re.sub(r'[-–—]\s*[a-zA-Z0-9\s_]+\(out\s+on\s+spotify[!]*\)', '', t, flags=re.IGNORECASE)

    # Clean artist candidates for filtering repeated artist tokens in title
    author_tokens = set()
    if author:
        author_tokens.add(clean_artist_name(author))
        pure_author = re.sub(r'[\(\[\{][^\)\]\}]*[\)\]\}]', '', author).strip()
        author_tokens.add(clean_artist_name(pure_author))
        author_tokens.discard('')

    # Strip repeated artists from title e.g. "Blank Banshee - Blank Banshee - B: / Start Up" or "-proloxx"
    if re.search(r'[-–—]', t):
        parts = [p.strip() for p in re.split(r'\s*[-–—]\s*', t) if p.strip()]
        new_parts = []
        for p in parts:
            p_clean = clean_artist_name(p)
            if author_tokens and any(p_clean == at or (len(p_clean) >= 3 and p_clean in at) for at in author_tokens):
                continue
            new_parts.append(p)
        if new_parts:
            t = ' - '.join(new_parts)
    return re.sub(r'[\W_]+', '', t.lower()).strip()


def extract_significant_version_tags(text: str) -> set[str]:
    """Extract distinct audio versions like Remix, VIP, Extended, Acoustic, Instrumental, Live."""
    text_lower = (text or '').lower()
    tags = set()
    for tag in ('remix', 'vip', 'extended', 'acoustic', 'instrumental', 'orchestral', 'live', 'dub', 'cover', 'slowed', 'reverb', 'sped up', 'vocal mix'):
        if re.search(rf'\b{re.escape(tag)}\b', text_lower):
            tags.add(tag)
    return tags


def clean_artist_name(author: str) -> str:
    a = (author or "").strip()
    a = normalize_unicode_text(a)
    a = re.sub(r'[\u200b\u200c\u200d\ufeff\u00a0]+', '', a)
    for p in ('the ', 'we are ', 'weare', 'i am ', 'iam ', 'official ', 'dj ', 'dj', 'its ', 'itsthe ', 'itsthe', 'theofficial ', 'theofficial'):
        if a.lower().startswith(p):
            a = a[len(p):].strip()
    for suffix in ('- Topic', 'Topic', 'VEVO', 'Official', 'Uptown', 'Music', 'TV', 'Records', 'Channel', 'HD', 'HQ', 'Show', 'Band'):
        if a.lower().endswith(suffix.lower()):
            a = a[:-len(suffix)].strip()
    return re.sub(r'[\W_]+', '', a.lower()).strip()


def translit_ru_to_en(text: str) -> str:
    mapping = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z',
        'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'u', 'я': 'a', 'і': 'i', 'ї': 'yi', 'є': 'ye'
    }
    res = ''
    for ch in (text or '').lower():
        res += mapping.get(ch, ch)
    res = res.replace('kh', 'h').replace('ju', 'u').replace('ja', 'a').replace('ya', 'a').replace('yu', 'u')
    return re.sub(r'[\W_]+', '', res)


def translit_both_ways(text: str) -> set[str]:
    mapping_ru_en = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'e', 'ж': 'zh', 'з': 'z',
        'и': 'i', 'й': 'j', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r',
        'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'u', 'я': 'a', 'і': 'i', 'ї': 'yi', 'є': 'ye'
    }
    mapping_en_ru = {
        'a': 'а', 'b': 'б', 'v': 'в', 'g': 'г', 'd': 'д', 'e': 'е', 'z': 'з', 'i': 'і', 'y': 'и',
        'k': 'к', 'l': 'л', 'm': 'м', 'n': 'н', 'o': 'о', 'p': 'п', 'r': 'р', 's': 'с', 't': 'т',
        'u': 'у', 'f': 'ф', 'h': 'х'
    }
    t = (text or '').lower()
    res = {re.sub(r'[\W_]+', '', t)}
    s_en = ''
    for ch in t:
        s_en += mapping_ru_en.get(ch, ch)
    res.add(re.sub(r'[\W_]+', '', s_en))
    s_ru = ''
    for ch in t:
        s_ru += mapping_en_ru.get(ch, ch)
    res.add(re.sub(r'[\W_]+', '', s_ru))
    return {x for x in res if x}


def _author_and_title_match(stem: str, title: Optional[str], author: Optional[str], is_in_archive: bool = False) -> bool:
    """Strictly matches track title AND artist against file stem, supporting multi-part filenames, promotional channels, and version tags."""
    if not title or len(title.strip()) < 2:
        return False

    tags_title = extract_significant_version_tags(title)
    tags_stem = extract_significant_version_tags(stem)

    if tags_title and tags_title != tags_stem:
        return False
    if tags_stem and not tags_title:
        critical_tags = {'remix', 'vip', 'extended', 'acoustic', 'instrumental', 'orchestral', 'live', 'dub', 'cover'}
        if any(t in critical_tags for t in tags_stem):
            return False

    online_a_clean = clean_artist_name(author or "")
    title_candidates = [title]
    if re.search(r'\s+[-–—]\s+', title):
        t_parts = [p.strip() for p in re.split(r'\s+[-–—]\s+', title) if p.strip()]
        if len(t_parts) >= 2:
            for tp in [t_parts[-1], ' - '.join(t_parts[1:]), ' - '.join(t_parts[:-1]), t_parts[0]]:
                if clean_artist_name(tp) != online_a_clean:
                    title_candidates.append(tp)

    # Extract all candidate (artist, title) splits from multi-part stem
    parts = [p.strip() for p in re.split(r'\s+[-–—]\s+', stem) if p.strip()]
    candidates = []

    if len(parts) == 1:
        candidates.append(("", parts[0]))
    elif len(parts) == 2:
        candidates.append((parts[0], parts[1]))
        candidates.append((parts[1], parts[0]))
        candidates.append(("", stem))
    elif len(parts) >= 3:
        candidates.append((parts[0], ' - '.join(parts[1:])))
        candidates.append((parts[1], ' - '.join(parts[2:])))
        candidates.append((' - '.join(parts[:-1]), parts[-1]))
        candidates.append((parts[0] + ' ' + parts[1], ' - '.join(parts[2:])))
        candidates.append(("", stem))

    generic_uploaders = {'topic', 'release', 'variousartists', 'soundtrack', ''}
    clean_a_variants = translit_both_ways(online_a_clean)
    lead_artist_clean = clean_artist_name(parts[0]) if parts else ""

    for raw_t in title_candidates:
        clean_t = clean_song_title(raw_t, author or "")
        if clean_t == online_a_clean:
            continue
        clean_t_variants = translit_both_ways(clean_t)

        for cand_a_raw, cand_t_raw in candidates:
            cand_a_clean = clean_artist_name(cand_a_raw)
            cand_t_clean = clean_artist_name(cand_t_raw)
            if cand_t_clean and (cand_t_clean == cand_a_clean or cand_t_clean == lead_artist_clean or cand_t_clean == online_a_clean):
                continue

            cand_t_variants = translit_both_ways(clean_song_title(cand_t_raw, cand_a_raw))
            cand_a_variants = translit_both_ways(clean_artist_name(cand_a_raw))

            t_match = bool(clean_t_variants & cand_t_variants)
            if not t_match:
                for ct in clean_t_variants:
                    for cdt in cand_t_variants:
                        if ct and cdt and (ct in cdt or cdt in ct):
                            if min(len(ct), len(cdt)) / max(len(ct), len(cdt)) >= 0.7:
                                t_match = True
                                break
                    if t_match:
                        break

            if not t_match:
                continue

            # If title matches, verify artist
            if not author or any(g in clean_a_variants for g in generic_uploaders):
                if len(clean_song_title(raw_t)) >= 5:
                    return True
                continue

            if clean_a_variants & cand_a_variants:
                return True

            for ca in clean_a_variants:
                for cda in cand_a_variants:
                    if ca and cda and (ca in cda or cda in ca):
                        return True

            if any(cda and len(cda) >= 3 and cda in clean_artist_name(title) for cda in cand_a_variants):
                return True

    return False


def match_search_candidate(cand_title: str, cand_uploader: str, orig_title: str, orig_artist: str) -> bool:
    """Verify that search candidate actually matches original song title and artist."""
    if not orig_title:
        return False

    t_clean = re.sub(r'[\(\[\{]\s*from\s+[^)\]\}]+[\)\]\}]', '', orig_title, flags=re.IGNORECASE)
    t_clean = re.sub(r'[\(\[\{]\s*(?:official\s*(?:music\s*)?video|music\s*video|official\s*audio|official|video|audio|lyrics?|visualizer|remaster(?:ed)?)\s*[\)\]\}]', '', t_clean, flags=re.IGNORECASE)

    words_t = [w for w in re.findall(r'[a-zA-Z0-9\u0400-\u04FF]+', t_clean.lower()) if len(w) >= 2 and w not in ('from', 'the', 'series', 'official', 'video', 'audio', 'lyrics', 'visualizer', 'version', 'feat', 'ft', 'with', 'and')]
    words_a = [w for w in re.findall(r'[a-zA-Z0-9\u0400-\u04FF]+', orig_artist.lower()) if len(w) >= 2 and w not in ('the', 'official', 'music', 'topic', 'channel', 'read', 'desc')]

    cand_full = f"{cand_title} {cand_uploader}".lower()

    if not words_t:
        return False
    title_match = all(w in cand_full for w in words_t)

    # Sequel check: ensure Roman numerals or part numbers aren't mismatched
    for part in ('ii', 'iii', 'iv', '2', '3', '4', 'pt 2', 'part 2'):
        if part in cand_full.split() and part not in orig_title.lower().split():
            return False

    if words_a:
        artist_match = any(w in cand_full for w in words_a) or any(u in cand_uploader.lower() for u in ('topic', 'release', 'soundtrack', 'vevo', 'records', 'official', 'riot games music'))
    else:
        artist_match = True

    return title_match and artist_match


def sanitize_extracted_artist(
    raw_artist: Optional[str],
    raw_uploader: Optional[str] = None,
    raw_channel: Optional[str] = None,
    raw_creator: Optional[str] = None,
) -> str:
    """Resolve clean artist name, stripping generic '- Topic', 'Release - Topic' uploader strings."""
    candidates = [raw_artist, raw_creator, raw_uploader, raw_channel]
    for cand in candidates:
        if not cand:
            continue
        c = str(cand).strip()
        c_clean = clean_artist_name(c)
        if c_clean in ("topic", "release", "variousartists", "soundtrack", "auto-generated"):
            continue
        if re.search(r'\s*-\s*Topic$', c, flags=re.IGNORECASE):
            c = re.sub(r'\s*-\s*Topic$', '', c, flags=re.IGNORECASE).strip()
        if c:
            return c
    return (raw_artist or raw_creator or raw_uploader or raw_channel or "").strip()
