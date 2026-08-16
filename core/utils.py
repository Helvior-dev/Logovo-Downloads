import re
import unicodedata


def format_bytes(bytes_num: int) -> str:
    """Format bytes to human-readable string (KB, MB, GB)."""
    if bytes_num is None:
        return "Unknown size"
    
    for x in ['bytes', 'KB', 'MB', 'GB', 'TB']:
        if bytes_num < 1024.0:
            return "%3.1f %s" % (bytes_num, x)
        bytes_num /= 1024.0
    
    return "%3.1f %s" % (bytes_num, 'PB')


def clean_filename_for_all_devices(name: str, max_len: int = 240, mode: str = "windows") -> str:
    """Sanitize filename for Windows NTFS (default) or strict UNIX/POSIX/MTP."""
    if not name:
        return "unnamed"

    is_unix = str(mode).lower().startswith("unix") or str(mode).lower().startswith("posix")

    if is_unix:
        # Strict POSIX / FAT32 mode
        replacements = {
            "？": "", "?": "",
            "：": " - ", ":": " - ",
            "／": "-", "⧸": "-", "\\": "-", "/": "-", "＼": "-",
            "｜": " - ", "|": " - ",
            "＂": "'", '"': "'", "“": "'", "”": "'", "«": "'", "»": "'",
            "＜": "", "＞": "", "<": "", ">": "",
            "＊": "", "*": "",
            "\xa0": " ", "\u200b": "", "\ufeff": "",
            "\t": " ", "\n": " ", "\r": "",
        }
        cleaned = name
        for bad_char, rep in replacements.items():
            cleaned = cleaned.replace(bad_char, rep)
        cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != "C")
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"(\s*-\s*)+", " - ", cleaned)
        cleaned = cleaned.strip(" .-_#")
        if len(cleaned) > 160:
            cleaned = cleaned[:160].strip(" .-_#")
        return cleaned or "unnamed"
    else:
        # Windows Native (Original full names, preserves all characters except 9 forbidden Windows NTFS chars)
        replacements = {
            "?": "",
            ":": " - ",
            "\\": "-", "/": "-",
            "|": " - ",
            '"': "'",
            "<": "", ">": "",
            "*": "",
            "\xa0": " ", "\u200b": "", "\ufeff": "",
            "\t": " ", "\n": " ", "\r": "",
        }
        cleaned = name
        for bad_char, rep in replacements.items():
            cleaned = cleaned.replace(bad_char, rep)
        cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != "C")
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = cleaned.strip(" .")
        if len(cleaned) > max_len:
            cleaned = cleaned[:max_len].strip(" .")
        return cleaned or "unnamed"


def sanitize_filename(filename: str, mode: str = "windows") -> str:
    """Sanitize string to be used as filename."""
    return clean_filename_for_all_devices(filename, mode=mode)

