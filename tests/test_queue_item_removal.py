import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core.queue_state import load_pending_queue
from core.settings import SettingsManager
from ui.main_window import MainWindow
from ui.queue_item import QueueItemWidget


class QueueItemRemovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_remove_button_enabled_after_stop_but_not_while_downloading(self):
        widget = QueueItemWidget({
            "url": "https://example.org/video", "title": "Video",
            "media_type": "Video (Best)", "media_type_category": "Video",
        })
        widget.resize(700, 110)
        widget.show()
        self.app.processEvents()
        try:
            removed = []
            widget.remove_requested.connect(removed.append)
            widget.set_status("Stopped", "Pending")
            self.assertTrue(widget.btn_remove.isVisible())
            self.assertTrue(widget.btn_remove.isEnabled())
            self.assertEqual(widget.btn_remove.text(), "×")
            self.assertGreaterEqual(widget.btn_remove.width(), 26)
            widget.btn_remove.click()
            self.assertEqual(removed, [widget])

            widget.set_status("Starting download...", "Downloading")
            self.assertFalse(widget.btn_remove.isEnabled())
            widget.btn_remove.click()
            self.assertEqual(removed, [widget])
        finally:
            widget.close()

    def test_remove_stopped_item_updates_snapshot_and_allows_readding_url(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("core.settings.get_app_data_dir", return_value=root):
                settings = SettingsManager()
            settings.settings.update({
                "download_path": str(root),
                "check_ytdlp_updates_on_startup": False,
                "check_app_updates_on_startup": False,
                "check_playlists_on_startup": False,
            })
            with patch("core.queue_state.queue_state_path", return_value=root / "pending_queue.json"), patch(
                "ui.main_window.SettingsManager", return_value=settings
            ), patch("ui.main_window.get_app_data_dir", return_value=root), patch(
                "core.history.get_app_data_dir", return_value=root
            ), patch("core.playlists_manager.get_app_data_dir", return_value=root), patch.object(
                MainWindow, "setup_tray"
            ), patch("ui.main_window.QTimer.singleShot"):
                window = MainWindow()
                window.show()
                try:
                    data = {
                        "url": "https://example.org/video", "title": "Video",
                        "media_type": "Video (Best)", "media_type_category": "Video",
                    }
                    window._add_single_item_to_queue(dict(data))
                    widget = window.download_queue[0]
                    widget.format_combo.setCurrentText("Video (H.264)")
                    widget.set_status("Stopped", "Pending")
                    window.active_workers[widget] = Mock()
                    window.remove_queue_item(widget)
                    self.assertEqual(len(window.download_queue), 1)
                    window.active_workers.clear()

                    widget.btn_remove.click()
                    self.assertEqual(window.download_queue, [])
                    self.assertEqual(load_pending_queue(), [])
                    self.assertEqual(window._queue_url_set, set())

                    window._add_single_item_to_queue(dict(data))
                    self.assertEqual(len(window.download_queue), 1)
                    self.assertEqual(len(load_pending_queue()), 1)
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
