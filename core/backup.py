import os
import zipfile
import shutil
import json
import tempfile
from pathlib import Path
from core.settings import get_app_data_dir


BACKUP_FILES = ('settings.json', 'playlists.json', 'history.json', 'app_logs.txt')


def export_backup(target_zip_path: str | Path) -> tuple[bool, str]:
    """Exports settings, playlists, history, and logs into a single zip file."""
    try:
        app_dir = get_app_data_dir()
        target_path = Path(target_zip_path)
        if not target_path.name.lower().endswith('.zip'):
            target_path = target_path.with_suffix('.zip')

        target_path.parent.mkdir(parents=True, exist_ok=True)
        files = [name for name in BACKUP_FILES if (app_dir / name).is_file()]
        if not files:
            return False, "No data files found to export."
        with tempfile.TemporaryDirectory(prefix='logovo-export-', dir=target_path.parent) as temp_dir:
            staged = Path(temp_dir) / 'backup.zip'
            with zipfile.ZipFile(staged, 'w', zipfile.ZIP_DEFLATED) as zf:
                for name in files:
                    zf.write(app_dir / name, arcname=name)
            os.replace(staged, target_path)

        return True, f"Successfully exported backup to {target_path.name} ({len(files)} files)."
    except Exception as e:
        return False, f"Failed to export backup: {e}"


def _validate_backup_file(path: Path) -> None:
    if path.name == 'app_logs.txt':
        return
    with path.open('r', encoding='utf-8') as source:
        data = json.load(source)
    if path.name == 'settings.json':
        if not isinstance(data, dict):
            raise ValueError('settings.json must contain an object')
        for key in ('quality_settings', 'audio_metadata_tags', 'video_metadata_tags'):
            if key in data and not isinstance(data[key], dict):
                raise ValueError(f'{key} must contain an object')
    elif not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise ValueError(f'{path.name} must contain a list of objects')
    elif path.name == 'playlists.json' and any(
        not isinstance(item.get('url'), str) or not item['url']
        or not isinstance(item.get('folder_path'), str) or not item['folder_path']
        for item in data
    ):
        raise ValueError('playlists.json contains an invalid playlist')


def import_backup(source_zip_path: str | Path) -> tuple[bool, str]:
    """Validate and stage the archive before replacing any current data."""
    temp_dir = None
    retain_recovery_files = False
    try:
        source_path = Path(source_zip_path)
        if not source_path.is_file():
            return False, "Selected backup file does not exist."

        app_dir = get_app_data_dir()
        temp_dir = Path(tempfile.mkdtemp(prefix='logovo-restore-', dir=app_dir))
        staged_dir = temp_dir / 'staged'
        previous_dir = temp_dir / 'previous'
        staged_dir.mkdir()
        previous_dir.mkdir()

        names = []
        with zipfile.ZipFile(source_path, 'r') as zf:
            for member in zf.infolist():
                if member.filename not in BACKUP_FILES:
                    continue
                if member.is_dir() or member.filename in names:
                    raise ValueError(f"Duplicate or invalid backup entry: {member.filename}")
                names.append(member.filename)
                staged = staged_dir / member.filename
                with zf.open(member) as source_file, staged.open('wb') as dest_file:
                    shutil.copyfileobj(source_file, dest_file)
                _validate_backup_file(staged)

        if not names:
            return False, "Invalid backup: no recognized Logovo Downloads configuration files found in archive."

        for name in names:
            current = app_dir / name
            if current.exists():
                if not current.is_file() or current.is_symlink():
                    raise ValueError(f"Cannot replace non-regular application data: {name}")
                shutil.copy2(current, previous_dir / name)

        installed = []
        try:
            for name in names:
                os.replace(staged_dir / name, app_dir / name)
                installed.append(name)
        except OSError as exc:
            rollback_errors = []
            for name in reversed(installed):
                try:
                    original = previous_dir / name
                    if original.exists():
                        os.replace(original, app_dir / name)
                    else:
                        (app_dir / name).unlink()
                except OSError as rollback_exc:
                    rollback_errors.append(f"{name}: {rollback_exc}")
            if rollback_errors:
                retain_recovery_files = True
                return False, f"Restore failed: {exc}. Manual recovery files remain in {temp_dir}: {'; '.join(rollback_errors)}"
            return False, f"Restore failed; previous data restored: {exc}"

        return True, f"Successfully restored {len(names)} data file(s) from backup."
    except Exception as e:
        return False, f"Failed to restore backup: {e}"
    finally:
        if temp_dir is not None and not retain_recovery_files:
            shutil.rmtree(temp_dir, ignore_errors=True)
