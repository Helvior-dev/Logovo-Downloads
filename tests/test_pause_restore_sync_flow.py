"""Offline lifecycle test: pause, close, restore, and confirm playlist deletion."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

from core.queue_state import load_pending_queue
from core.settings import SettingsManager
from ui.main_window import MainWindow
from ui.workers import ApplyPlaylistSyncWorker, SyncPlaylistWorker, WorkerThread


class PauseRestoreSyncFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pause_close_restore_then_sync_removed_track_on_test_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            downloads = root / "downloads"
            downloads.mkdir()
            playlist_dir = root / "playlist"
            playlist_dir.mkdir()
            partial = downloads / "unfinished.mp4.part"
            partial.write_bytes(b"resume fixture")
            old_track = playlist_dir / "Old Artist - Old Song.mp3"
            old_track.write_bytes(b"0" * (600 * 1024))
            (playlist_dir / "stem_vid_map.json").write_text(
                '{"Old Artist - Old Song": "old-video-id"}', encoding="utf-8"
            )
            playlist_url = "https://www.youtube.com/playlist?list=offline-test"
            playlist = {
                "url": playlist_url, "folder_path": str(playlist_dir),
                "title": "Offline Test", "media_type": "Audio", "format_compat": "windows",
            }
            with patch("core.settings.get_app_data_dir", return_value=root):
                settings = SettingsManager()
            settings.settings.update({
                "download_path": str(downloads),
                "check_ytdlp_updates_on_startup": False,
                "check_app_updates_on_startup": False,
                "check_playlists_on_startup": False,
                "playlist_cover_mode": "none",
                "create_nomedia_file": False,
            })
            preview = {"is_playlist": True, "count": 0, "entries": []}
            saved_path = root / "pending_queue.json"

            with patch("ui.main_window.SettingsManager", return_value=settings), patch(
                "ui.main_window.get_app_data_dir", return_value=root
            ), patch("core.history.get_app_data_dir", return_value=root), patch(
                "core.playlists_manager.get_app_data_dir", return_value=root
            ), patch("core.queue_state.queue_state_path", return_value=saved_path), patch.object(
                MainWindow, "setup_tray"
            ), patch("ui.main_window.QTimer.singleShot"), patch.object(
                WorkerThread, "start"
            ), patch("ui.workers.get_video_preview", return_value=preview), patch.object(
                SyncPlaylistWorker, "start", lambda worker: worker.run()
            ), patch.object(ApplyPlaylistSyncWorker, "start", lambda worker: worker.run()), patch(
                "ui.workers.restore_dates_from_order"
            ), patch("ui.workers.reindex_existing_playlist_files"), patch(
                "ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
            ) as confirm:
                first = MainWindow()
                first.show()
                self.app.processEvents()
                try:
                    first._add_single_item_to_queue({
                        "url": "https://example.org/unfinished", "title": "Unfinished",
                        "media_type": "Video (Best)", "media_type_category": "Video",
                    })
                    first.start_queue()
                    item = first.download_queue[0]
                    self.assertIn(item, first.active_workers)
                    first.pause_download()
                    self.assertTrue(first._pause_requested)
                    first.task_finished(item, False, "Cancelled", was_cancelled=True)
                    self.assertEqual(item.status_state, "Pending")
                    self.assertFalse(first.is_downloading)
                    self.assertTrue(partial.exists())
                    first.close()
                    self.assertEqual(len(load_pending_queue()), 1)
                finally:
                    first.close()

                second = MainWindow()
                second.show()
                self.app.processEvents()
                try:
                    second._offer_queue_restore()
                    self.assertEqual(len(second.download_queue), 1)
                    restored = second.download_queue[0]
                    self.assertEqual(restored.item_data["url"], "https://example.org/unfinished")
                    self.assertTrue(partial.exists())
                    self.assertIn(restored, second.active_workers)
                    second.pause_download()
                    second.task_finished(restored, False, "Cancelled", was_cancelled=True)

                    second.playlists_mgr.playlists = [playlist]
                    def accept_preview(dialog):
                        self.assertEqual(dialog.selected_files_to_delete(), [old_track.name])
                        self.assertTrue(old_track.exists())  # Planning must be read-only.
                        return QDialog.DialogCode.Accepted

                    with patch("ui.main_window.PlaylistSyncPreviewDialog.exec", accept_preview), patch(
                        "ui.main_window.PlaylistUpToDateDialog.exec", return_value=QDialog.DialogCode.Accepted
                    ):
                        second.sync_tracked_playlist(playlist, skip_format_dialog=True)

                    self.assertFalse(old_track.exists())
                    self.assertTrue(partial.exists())
                    self.assertEqual(len(load_pending_queue()), 1)
                    self.assertNotIn(playlist_url, second._active_sync_urls)
                    self.assertGreaterEqual(confirm.call_count, 2)  # Restore and deletion.
                finally:
                    second.close()


if __name__ == "__main__":
    unittest.main()
