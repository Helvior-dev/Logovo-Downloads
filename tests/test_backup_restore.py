import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.backup import import_backup
from core.settings import SettingsManager


class BackupRestoreTests(unittest.TestCase):
    def test_imported_settings_are_applied_when_active_manager_reloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_dir = Path(temp_dir)
            settings_file = app_dir / "settings.json"
            settings_file.write_text(json.dumps({"download_path": "old-path"}), encoding="utf-8")
            backup_path = app_dir / "backup.zip"
            with zipfile.ZipFile(backup_path, "w") as archive:
                archive.writestr("settings.json", json.dumps({"download_path": "restored-path"}))

            with patch("core.settings.get_app_data_dir", return_value=app_dir):
                manager = SettingsManager()
                self.assertEqual(manager.get("download_path"), "old-path")

                with patch("core.backup.get_app_data_dir", return_value=app_dir):
                    ok, _message = import_backup(backup_path)

                self.assertTrue(ok)
                self.assertEqual(manager.get("download_path"), "old-path")
                manager.reload()
                self.assertEqual(manager.get("download_path"), "restored-path")


if __name__ == "__main__":
    unittest.main()
