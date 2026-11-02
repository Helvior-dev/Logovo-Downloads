import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QMessageBox

from core.queue_state import load_pending_queue, save_pending_queue
from ui.main_window import MainWindow


class QueueStateTests(unittest.TestCase):
    def test_snapshot_keeps_playlist_options_but_not_cookie_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pending_queue.json"
            save_pending_queue([{
                "url": "https://example.org/track",
                "title": "Track",
                "media_type": "Video (Best)",
                "playlist_output_dir": folder,
                "playlist_index": 3,
                "cookies": {"file": "secret"},
                "download_options": {
                    "media_type": "Video (Best)",
                    "output_dir": folder,
                    "settings": {"video_codec": "h264", "cookies_file": "secret"},
                    "cookies": {"file": "secret"},
                },
            }], path)

            saved = load_pending_queue(path)
            self.assertEqual(saved[0]["playlist_index"], 3)
            self.assertEqual(saved[0]["download_options"]["settings"]["video_codec"], "h264")
            self.assertNotIn("secret", path.read_text(encoding="utf-8"))
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 1)

    def test_corrupt_snapshot_does_not_raise(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pending_queue.json"
            path.write_text("{", encoding="utf-8")
            self.assertEqual(load_pending_queue(path), [])

    def test_pending_item_keeps_download_settings_before_first_start(self):
        class Settings:
            def get(self, key, default=None):
                return {"download_path": "C:/downloads", "video_codec": "h264"}.get(key, default)

            def get_quality(self, platform):
                return "720p"

        widget = SimpleNamespace(
            status_state="Pending",
            item_data={"url": "https://example.org/video", "media_type": "Video (Best)"},
            format_combo=SimpleNamespace(currentText=lambda: "Video (Best)"),
        )
        window = SimpleNamespace(download_queue=[widget], settings=Settings(), status_label=Mock())
        with patch("ui.main_window.save_pending_queue") as save:
            MainWindow._save_queue(window)
        options = save.call_args.args[0][0]["download_options"]
        self.assertEqual(options["output_dir"], "C:/downloads")
        self.assertEqual(options["quality"], "720p")
        self.assertEqual(options["settings"]["video_codec"], "h264")

    def test_pause_waits_for_worker_and_does_not_start_next_item(self):
        worker = Mock()
        active = Mock()
        pending = SimpleNamespace(status_state="Pending")
        window = SimpleNamespace(
            is_downloading=True, _pause_requested=False, _closing_after_pause=False,
            active_workers={active: worker}, download_queue=[active, pending],
            btn_pause=Mock(), btn_stop=Mock(), btn_download_all=Mock(),
            status_label=Mock(), _save_queue=Mock(), update_queue_ui=Mock(),
        )
        MainWindow.pause_download(window)
        worker.requestInterruption.assert_called_once_with()
        self.assertTrue(window._pause_requested)
        self.assertEqual(pending.status_state, "Pending")

        window.active_workers.clear()
        window.process_queue = Mock()
        MainWindow.process_queue(window)
        window.process_queue.assert_not_called()
        self.assertFalse(window.is_downloading)
        self.assertFalse(window._pause_requested)
        window._save_queue.assert_called()

    def test_declined_restore_is_not_offered_again_and_keeps_partial_file(self):
        old = {"url": "https://example.org/old", "media_type": "Audio (Best)"}
        new = {
            "url": "https://example.org/new", "media_type": "Video (Best)",
            "download_options": {"source_url": "https://example.org/new"},
        }
        widget = SimpleNamespace(
            status_state="Pending", item_data=new,
            format_combo=SimpleNamespace(currentText=lambda: new["media_type"]),
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pending_queue.json"
            partial = Path(folder) / "old.mp3.part"
            partial.write_bytes(b"partial download")
            save_pending_queue([old], path)
            window = SimpleNamespace(download_queue=[], status_label=Mock())
            window._save_queue = lambda: MainWindow._save_queue(window)

            with patch("ui.main_window.load_pending_queue", side_effect=lambda: load_pending_queue(path)), patch(
                "ui.main_window.save_pending_queue", side_effect=lambda items: save_pending_queue(items, path)
            ), patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as question:
                MainWindow._offer_queue_restore(window)
                self.assertEqual(load_pending_queue(path), [])
                self.assertEqual(partial.read_bytes(), b"partial download")

                # A fresh launch must not ask again; newly added work remains allowed.
                next_window = SimpleNamespace(download_queue=[], status_label=Mock())
                next_window._save_queue = lambda: MainWindow._save_queue(next_window)
                MainWindow._offer_queue_restore(next_window)
                question.assert_called_once()
                next_window.download_queue.append(widget)
                next_window._save_queue()
                self.assertEqual([item["url"] for item in load_pending_queue(path)], [new["url"]])
                widget.status_state = "Success"
                next_window._save_queue()
                self.assertEqual(load_pending_queue(path), [])
                self.assertEqual(partial.read_bytes(), b"partial download")

    def test_restore_yes_still_adds_and_starts_saved_downloads(self):
        old = {"url": "https://example.org/old", "media_type": "Audio (Best)"}
        window = SimpleNamespace(
            download_queue=[], status_label=Mock(), update_queue_ui=Mock(),
            start_queue=Mock(), _add_single_item_to_queue=Mock(),
        )
        window._save_queue = Mock()
        with patch("ui.main_window.load_pending_queue", return_value=[old]), patch(
            "ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ):
            MainWindow._offer_queue_restore(window)
        window._add_single_item_to_queue.assert_called_once_with(
            old, batch=True, preserve_subtitle_defaults=True,
        )
        window._save_queue.assert_called_once()
        window.start_queue.assert_called_once()
        self.assertFalse(window._restoring_queue)

    def test_declined_restore_reports_save_failure(self):
        window = SimpleNamespace(download_queue=[], status_label=Mock())
        window._save_queue = lambda: MainWindow._save_queue(window)
        with patch("ui.main_window.load_pending_queue", return_value=[{"url": "https://example.org/old"}]), patch(
            "ui.main_window.save_pending_queue", side_effect=OSError("disk full")
        ), patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No), patch(
            "ui.main_window.QMessageBox.warning"
        ) as warning:
            MainWindow._offer_queue_restore(window)
        warning.assert_called_once()
        self.assertIn("Could not remember", warning.call_args.args[2])

    def test_close_waits_for_thread_exit_after_result(self):
        worker = Mock()
        worker.isRunning.return_value = True
        event = Mock()
        window = SimpleNamespace(
            _save_queue=Mock(), active_workers={}, _ending_workers=[worker],
            _closing_after_pause=False, _finish_close_if_ready=Mock(),
        )
        MainWindow.closeEvent(window, event)
        event.ignore.assert_called_once()
        self.assertTrue(window._closing_after_pause)
        window._finish_close_if_ready.assert_called_once()

        worker.isRunning.return_value = False
        window.close = Mock()
        with patch("ui.main_window.QTimer.singleShot") as timer:
            MainWindow._finish_close_if_ready(window)
        self.assertFalse(window._closing_after_pause)
        timer.assert_called_once_with(0, window.close)

    def test_declining_close_keeps_active_download_running(self):
        worker = Mock()
        event = Mock()
        window = SimpleNamespace(
            active_workers={Mock(): worker}, _close_confirmed=False,
            _save_queue=Mock(), pause_download=Mock(),
        )
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No) as question:
            MainWindow.closeEvent(window, event)
        question.assert_called_once()
        self.assertEqual(question.call_args.args[-1], QMessageBox.StandardButton.No)
        event.ignore.assert_called_once()
        window._save_queue.assert_not_called()
        window.pause_download.assert_not_called()
        worker.requestInterruption.assert_not_called()
        self.assertFalse(window._close_confirmed)

    def test_confirming_close_pauses_once_without_repeating_prompt(self):
        worker = Mock()
        event = Mock()
        window = SimpleNamespace(
            active_workers={Mock(): worker}, _close_confirmed=False,
            _closing_after_pause=False, _save_queue=Mock(),
            pause_download=Mock(), status_label=Mock(),
        )
        with patch("ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes) as question:
            MainWindow.closeEvent(window, event)
            MainWindow.closeEvent(window, event)
        question.assert_called_once()
        self.assertTrue(window._close_confirmed)
        self.assertTrue(window._closing_after_pause)
        self.assertEqual(window.pause_download.call_count, 2)
        event.ignore.assert_called()


if __name__ == "__main__":
    unittest.main()
