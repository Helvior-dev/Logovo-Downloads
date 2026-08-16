import os
import zipfile
import shutil
from pathlib import Path
from core.settings import get_app_data_dir


def export_backup(target_zip_path: str | Path) -> tuple[bool, str]:
    """Exports settings, playlists, history, and logs into a single zip file."""
    try:
        app_dir = get_app_data_dir()
        target_path = Path(target_zip_path)
        if not target_path.name.lower().endswith('.zip'):
            target_path = target_path.with_suffix('.zip')

        os.makedirs(target_path.parent, exist_ok=True)

        backup_files = [
            'settings.json',
            'playlists.json',
            'history.json',
            'app_logs.txt'
        ]

        with zipfile.ZipFile(target_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            added_count = 0
            for fn in backup_files:
                f_path = app_dir / fn
                if f_path.exists():
                    zf.write(f_path, arcname=fn)
                    added_count += 1

        if added_count == 0:
            return False, "No data files found to export."

        return True, f"Successfully exported backup to {target_path.name} ({added_count} files)."
    except Exception as e:
        return False, f"Failed to export backup: {e}"


def import_backup(source_zip_path: str | Path) -> tuple[bool, str]:
    """Restores settings, playlists, history from a zip backup into AppData."""
    try:
        source_path = Path(source_zip_path)
        if not source_path.exists():
            return False, "Selected backup file does not exist."

        app_dir = get_app_data_dir()
        os.makedirs(app_dir, exist_ok=True)

        allowed_files = {
            'settings.json',
            'playlists.json',
            'history.json',
            'app_logs.txt'
        }

        restored_count = 0
        with zipfile.ZipFile(source_path, 'r') as zf:
            for member in zf.namelist():
                base_name = Path(member).name
                if base_name in allowed_files:
                    target_file = app_dir / base_name
                    with zf.open(member) as source_file, open(target_file, 'wb') as dest_file:
                        shutil.copyfileobj(source_file, dest_file)
                    restored_count += 1

        if restored_count == 0:
            return False, "Invalid backup: no recognized Logovo Downloads configuration files found in archive."

        return True, f"Successfully restored {restored_count} data file(s) from backup."
    except Exception as e:
        return False, f"Failed to restore backup: {e}"
