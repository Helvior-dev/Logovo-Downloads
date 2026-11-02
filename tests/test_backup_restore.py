import json
import os
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QMessageBox

from core.backup import export_backup, import_backup
from core.settings import SettingsManager
from ui.main_window import MainWindow


class BackupRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_restore_through_settings_reloads_active_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings_path = root / 'settings.json'
            settings_path.write_text(json.dumps({
                'ui_theme': 'cyan', 'download_path': str(root),
                'check_ytdlp_updates_on_startup': False,
                'check_app_updates_on_startup': False,
                'check_playlists_on_startup': False,
            }), encoding='utf-8')
            playlist_url = 'https://example.org/playlist'
            (root / 'playlists.json').write_text(json.dumps([{
                'url': playlist_url, 'folder_path': str(root), 'format_compat': 'windows',
            }]), encoding='utf-8')
            (root / 'history.json').write_text('[{"title":"Previous"}]', encoding='utf-8')
            backup_path = root / 'backup.zip'

            with patch('core.settings.get_app_data_dir', return_value=root), patch(
                'core.backup.get_app_data_dir', return_value=root
            ), patch('ui.main_window.get_app_data_dir', return_value=root), patch(
                'core.history.get_app_data_dir', return_value=root
            ), patch('core.playlists_manager.get_app_data_dir', return_value=root), patch(
                'core.queue_state.queue_state_path', return_value=root / 'pending_queue.json'
            ), patch.object(MainWindow, 'setup_tray'), patch('ui.main_window.QTimer.singleShot'):
                window = MainWindow()
                try:
                    self.assertTrue(export_backup(backup_path)[0])
                    window._on_ui_theme_changed('red')
                    window.playlists_mgr.playlists = []
                    window.playlists_mgr.save()
                    window.history.history = []
                    window.history.save()
                    old_settings_tab = window.settings_tab
                    window.tabs.setCurrentWidget(old_settings_tab)
                    window.is_downloading = True
                    with patch('ui.main_window.QFileDialog.getOpenFileName') as choose, patch(
                        'ui.main_window.QFileDialog.getSaveFileName'
                    ) as save_as, patch('ui.main_window.QMessageBox.warning') as warning:
                        window.import_app_data()
                        window.export_app_data()
                    choose.assert_not_called()
                    save_as.assert_not_called()
                    self.assertEqual(warning.call_count, 2)
                    window.is_downloading = False
                    with patch('ui.main_window.QFileDialog.getOpenFileName', return_value=(str(backup_path), 'ZIP')), patch(
                        'ui.main_window.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes
                    ), patch('ui.main_window.QMessageBox.information'):
                        window.import_app_data()

                    self.assertEqual(window.settings.get('ui_theme'), 'cyan')
                    self.assertEqual(window.ui_theme_combo.currentData(), 'cyan')
                    self.assertEqual(window.ui_theme, 'cyan')
                    self.assertNotEqual(window.settings_tab, old_settings_tab)
                    self.assertEqual(window.playlists_mgr.get_all()[0]['url'], playlist_url)
                    self.assertEqual(window.history.get_all()[0]['title'], 'Previous')
                finally:
                    window.close()

    def test_export_and_import_round_trip_on_temporary_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            app_dir = root / 'app'
            app_dir.mkdir()
            original = {
                'settings.json': b'{"ui_theme":"cyan"}',
                'playlists.json': b'[{"url":"https://example.org/list","folder_path":"test"}]',
                'history.json': b'[{"title":"Test"}]',
                'app_logs.txt': b'log entry',
            }
            for name, contents in original.items():
                (app_dir / name).write_bytes(contents)
            backup = root / 'backup.zip'
            with patch('core.backup.get_app_data_dir', return_value=app_dir):
                ok, _ = export_backup(backup)
                self.assertTrue(ok)
                with zipfile.ZipFile(backup) as archive:
                    self.assertEqual(set(archive.namelist()), set(original))
                for name in original:
                    (app_dir / name).write_bytes(b'changed')
                ok, _ = import_backup(backup)
            self.assertTrue(ok)
            self.assertEqual({name: (app_dir / name).read_bytes() for name in original}, original)
            self.assertFalse(list(app_dir.glob('logovo-restore-*')))

    def test_invalid_archive_does_not_change_any_existing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            before = {'settings.json': b'{"download_path":"old"}', 'history.json': b'[]'}
            for name, contents in before.items():
                (root / name).write_bytes(contents)
            archive_path = root / 'broken.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('settings.json', '{"download_path":"new"}')
                archive.writestr('history.json', 'not json')
            with patch('core.backup.get_app_data_dir', return_value=root):
                ok, _ = import_backup(archive_path)
            self.assertFalse(ok)
            self.assertEqual({name: (root / name).read_bytes() for name in before}, before)
            self.assertFalse(list(root.glob('logovo-restore-*')))

            archive_path.write_bytes(b'not a ZIP archive')
            with patch('core.backup.get_app_data_dir', return_value=root):
                ok, _ = import_backup(archive_path)
            self.assertFalse(ok)
            self.assertEqual({name: (root / name).read_bytes() for name in before}, before)

    def test_invalid_json_shape_and_duplicate_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            current = root / 'settings.json'
            current.write_text('{"ui_theme":"green"}', encoding='utf-8')
            archive_path = root / 'backup.zip'
            with patch('core.backup.get_app_data_dir', return_value=root):
                with zipfile.ZipFile(archive_path, 'w') as archive:
                    archive.writestr('settings.json', '[]')
                ok, _ = import_backup(archive_path)
                self.assertFalse(ok)
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with zipfile.ZipFile(archive_path, 'w') as archive:
                        archive.writestr('settings.json', '{}')
                        archive.writestr('settings.json', '{}')
                ok, _ = import_backup(archive_path)
                self.assertFalse(ok)
            self.assertEqual(current.read_text(encoding='utf-8'), '{"ui_theme":"green"}')

    def test_failed_second_replace_restores_previous_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = root / 'settings.json'
            history = root / 'history.json'
            settings.write_bytes(b'{"ui_theme":"green"}')
            history.write_bytes(b'[]')
            backup = root / 'backup.zip'
            with zipfile.ZipFile(backup, 'w') as archive:
                archive.writestr('settings.json', '{"ui_theme":"red"}')
                archive.writestr('history.json', '[{"title":"New"}]')

            from core import backup as backup_module
            original_replace = backup_module.os.replace

            def fail_history_once(source, destination):
                if Path(destination) == history and Path(source).parent.name == 'staged':
                    raise OSError('simulated replacement failure')
                return original_replace(source, destination)

            with patch('core.backup.get_app_data_dir', return_value=root), patch(
                'core.backup.os.replace', side_effect=fail_history_once
            ):
                ok, message = import_backup(backup)
            self.assertFalse(ok)
            self.assertIn('previous data restored', message)
            self.assertEqual(settings.read_bytes(), b'{"ui_theme":"green"}')
            self.assertEqual(history.read_bytes(), b'[]')
            self.assertFalse(list(root.glob('logovo-restore-*')))

    def test_empty_export_keeps_existing_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backup = root / 'backup.zip'
            backup.write_bytes(b'older backup')
            with patch('core.backup.get_app_data_dir', return_value=root):
                ok, _ = export_backup(backup)
            self.assertFalse(ok)
            self.assertEqual(backup.read_bytes(), b'older backup')

    def test_failed_export_keeps_existing_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / 'settings.json').write_text('{}', encoding='utf-8')
            target = root / 'backup.zip'
            target.write_bytes(b'older backup')
            with patch('core.backup.get_app_data_dir', return_value=root), patch(
                'core.backup.zipfile.ZipFile.write', side_effect=OSError('simulated disk failure')
            ):
                ok, _ = export_backup(target)
            self.assertFalse(ok)
            self.assertEqual(target.read_bytes(), b'older backup')
            self.assertFalse(list(root.glob('logovo-export-*')))

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
