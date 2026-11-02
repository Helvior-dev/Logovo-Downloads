"""Non-secret download queue snapshots for recovery after shutdown."""

import json
import os
from pathlib import Path

from core.history import sanitize_download_options
from core.settings import get_app_data_dir


QUEUE_FIELDS = frozenset({
    "url", "original_url", "title", "uploader", "channel", "artist", "platform",
    "duration", "media_type", "media_type_category", "playlist_output_dir",
    "playlist_index", "playlist_count", "format_compat", "specific_subs",
    "thumbnail", "formats_available", "subtitles_available", "is_retry",
})


def queue_state_path() -> Path:
    return get_app_data_dir() / "pending_queue.json"


def save_pending_queue(items: list[dict], path: Path | None = None) -> None:
    path = path or queue_state_path()
    records = []
    for item in items:
        record = {
            key: value for key, value in item.items()
            if key in QUEUE_FIELDS and (
                value is None or isinstance(value, (str, int, float, bool))
                or isinstance(value, list) and all(isinstance(v, str) for v in value)
            )
        }
        options = sanitize_download_options(item.get("download_options"))
        if options:
            record["download_options"] = options
        if record.get("url"):
            records.append(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def load_pending_queue(path: Path | None = None) -> list[dict]:
    path = path or queue_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict) and isinstance(item.get("url"), str)]
    except (OSError, ValueError, TypeError):
        return []
