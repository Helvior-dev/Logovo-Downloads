import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.storage_cleanup import delete_cleanup_candidates, scan_cleanup_candidates
from ui.storage_cleanup_dialog import StorageCleanupDialog


class StorageCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scan_lists_direct_partials_and_old_backups_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            downloads = root / "downloads"
            downloads.mkdir()
            playlist = root / "playlist"
            playlist.mkdir()
            part = downloads / "song.mp3.part"
            part.write_bytes(b"partial")
            (downloads / "complete.mp3").write_bytes(b"complete")
            nested = downloads / "nested"
            nested.mkdir()
            (nested / "invisible.part").write_bytes(b"nested")
            (playlist / "video.mp4.part").write_bytes(b"video")

            app_dir = root / "app"
            app_dir.mkdir()
            backup_old = app_dir / ("ytdlp_core_backup_" + "a" * 32)
            backup_old.mkdir()
            (backup_old / "version.py").write_bytes(b"old")
            backup_latest = app_dir / ("ytdlp_core_backup_" + "b" * 32)
            backup_latest.mkdir()
            (backup_latest / "version.py").write_bytes(b"new")
            old_time = backup_old.stat().st_mtime - 3600
            os.utime(backup_old, (old_time, old_time))
            (app_dir / "ytdlp_core_backup_pending").mkdir()
            (app_dir / "ytdlp_core_pending").mkdir()

            found = scan_cleanup_candidates([downloads, playlist], app_dir)
            self.assertEqual({item["path"] for item in found}, {
                part.resolve(), (playlist / "video.mp4.part").resolve(), backup_old.resolve(),
            })
            self.assertEqual(next(item["size"] for item in found if item["path"] == backup_old.resolve()), 3)

    def test_delete_requires_selected_unchanged_item_and_keeps_completed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            downloads = root / "downloads"
            downloads.mkdir()
            part = downloads / "video.mp4.part"
            part.write_bytes(b"partial")
            complete = downloads / "video.mp4"
            complete.write_bytes(b"complete")
            other = root / "outside.part"
            other.write_bytes(b"outside")

            found = scan_cleanup_candidates([downloads], root)
            self.assertEqual(len(found), 1)
            part.write_bytes(b"new content")
            deleted, errors = delete_cleanup_candidates(found, [downloads], root)
            self.assertEqual(deleted, 0)
            self.assertEqual(len(errors), 1)
            self.assertTrue(part.exists())

            found = scan_cleanup_candidates([downloads], root)
            deleted, errors = delete_cleanup_candidates(found, [downloads], root)
            self.assertEqual((deleted, errors), (1, []))
            self.assertFalse(part.exists())
            self.assertTrue(complete.exists())
            self.assertTrue(other.exists())

    def test_latest_backup_cannot_be_deleted_even_with_forged_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            backup = root / ("ytdlp_core_backup_" + "c" * 32)
            backup.mkdir()
            (backup / "version.py").write_bytes(b"keep")
            forged = {
                "kind": "backup", "path": backup,
                "mtime_ns": backup.stat().st_mtime_ns, "size": 4,
            }
            deleted, errors = delete_cleanup_candidates([forged], [], root)
            self.assertEqual(deleted, 0)
            self.assertTrue(errors)
            self.assertTrue(backup.exists())

    def test_dialog_requires_selection_and_confirmation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            downloads = root / "downloads"
            downloads.mkdir()
            part = downloads / "clip.mp4.part"
            part.write_bytes(b"partial")
            dialog = StorageCleanupDialog([downloads], root, is_busy=lambda: False)
            try:
                self.assertEqual(dialog.table.rowCount(), 1)
                self.assertEqual(dialog.table.item(0, 0).checkState(), Qt.CheckState.Unchecked)
                self.assertFalse(dialog.btn_delete.isEnabled())
                dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
                self.assertTrue(dialog.btn_delete.isEnabled())
                with patch("ui.storage_cleanup_dialog.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
                    dialog.btn_delete.click()
                self.assertTrue(part.exists())
                with patch("ui.storage_cleanup_dialog.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes), patch(
                    "ui.storage_cleanup_dialog.QMessageBox.information"
                ):
                    dialog.btn_delete.click()
                self.assertFalse(part.exists())
                self.assertEqual(dialog.table.rowCount(), 0)
            finally:
                dialog.close()

    def test_dialog_refuses_deletion_when_downloads_are_busy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            part = root / "clip.part"
            part.write_bytes(b"partial")
            dialog = StorageCleanupDialog([root], root, is_busy=lambda: True)
            try:
                dialog.table.item(0, 0).setCheckState(Qt.CheckState.Checked)
                with patch("ui.storage_cleanup_dialog.QMessageBox.warning") as warning, patch(
                    "ui.storage_cleanup_dialog.QMessageBox.question"
                ) as question:
                    dialog.btn_delete.click()
                warning.assert_called_once()
                question.assert_not_called()
                self.assertTrue(part.exists())
            finally:
                dialog.close()


if __name__ == "__main__":
    unittest.main()
