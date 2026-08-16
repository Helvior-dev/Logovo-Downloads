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


def clean_filename_for_all_devices(name: str, max_len: int = 160) -> str:
    """Sanitize filename to be 100% compatible with Windows NTFS, Android MTP, FAT32, exFAT and Samsung USB transfers."""
    if not name:
        return "unnamed"

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

    # Remove non-printable / control characters
    cleaned = "".join(ch for ch in cleaned if unicodedata.category(ch)[0] != "C")

    # Collapse multiple spaces and dashes
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"(\s*-\s*)+", " - ", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned)

    # Strip leading/trailing invalid chars (especially trailing dots/spaces which break MTP)
    cleaned = cleaned.strip(" .-_#")

    if not cleaned:
        cleaned = "unnamed"

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].strip(" .-_#")

    return cleaned or "unnamed"


def sanitize_filename(filename: str) -> str:
    """Sanitize string to be used as filename across all devices."""
    return clean_filename_for_all_devices(filename)

