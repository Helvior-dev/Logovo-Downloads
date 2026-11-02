"""Exercise queue shutdown and restore with an actual QThread, without network access."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.queue_state import load_pending_queue
from core.settings import SettingsManager
from ui.main_window import MainWindow


class RealWorkerPauseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait_for(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return
            time.sleep(0.01)
        self.fail('Timed out waiting for the real download worker to finish')

    def test_close_interrupts_real_thread_and_restored_queue_can_pause_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            downloads = root / 'downloads'
            downloads.mkdir()
            partial = downloads / 'test-video.part'
            saved_path = root / 'pending_queue.json'
            started = threading.Event()
            download_calls = []

            class TestDownloader:
                def __init__(self, output_dir, **_kwargs):
                    self.output_dir = Path(output_dir)
                    self.was_cancelled = False

                def download(self, url, *, cancel_check, **_kwargs):
                    download_calls.append(url)
                    partial.write_bytes(b'partial data')
                    started.set()
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        if cancel_check():
                            self.was_cancelled = True
                            return False, 'Cancelled', False
                        time.sleep(0.01)
                    return False, 'Worker did not receive interruption', False

            with patch('core.settings.get_app_data_dir', return_value=root):
                settings = SettingsManager()
            settings.settings.update({
                'download_path': str(downloads),
                'max_concurrent_downloads': 1,
                'check_ytdlp_updates_on_startup': False,
                'check_app_updates_on_startup': False,
                'check_playlists_on_startup': False,
            })
            real_single_shot = QTimer.singleShot

            def without_startup_prompts(delay, callback):
                if getattr(callback, '__name__', '') in (
                    'check_cookies_file_validity', '_offer_queue_restore',
                ):
                    return
                return real_single_shot(delay, callback)

            with patch('ui.main_window.SettingsManager', return_value=settings), patch(
                'ui.main_window.get_app_data_dir', return_value=root
            ), patch('core.history.get_app_data_dir', return_value=root), patch(
                'core.playlists_manager.get_app_data_dir', return_value=root
            ), patch('core.queue_state.queue_state_path', return_value=saved_path), patch.object(
                MainWindow, 'setup_tray'
            ), patch('ui.main_window.QTimer.singleShot', side_effect=without_startup_prompts), patch(
                'ui.workers.MediaDownloader', TestDownloader
            ), patch('ui.main_window.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                first = MainWindow()
                second = None
                try:
                    first.show()
                    first._add_single_item_to_queue({
                        'url': 'https://example.org/test-video', 'title': 'Test video',
                        'media_type': 'Video (Best)', 'media_type_category': 'Video',
                    })
                    first._add_single_item_to_queue({
                        'url': 'https://example.org/next-video', 'title': 'Next video',
                        'media_type': 'Video (Best)', 'media_type_category': 'Video',
                    })
                    first.start_queue()
                    self.assertTrue(started.wait(2))
                    self.assertEqual(len(download_calls), 1)
                    self.assertFalse(first.close())  # Close is deferred until the thread exits.
                    self.assertTrue(first._closing_after_pause)
                    self._wait_for(lambda: not first.isVisible())
                    self.assertEqual(len(download_calls), 1)
                    self.assertTrue(partial.exists())
                    self.assertEqual(len(load_pending_queue()), 2)

                    started.clear()
                    second = MainWindow()
                    second.show()
                    second._offer_queue_restore()
                    self.assertEqual(len(second.download_queue), 2)
                    self.assertTrue(started.wait(2))
                    second.pause_download()
                    self._wait_for(lambda: not second.is_downloading)
                    self.assertEqual(len(download_calls), 2)
                    self.assertTrue(partial.exists())
                    self.assertEqual(len(load_pending_queue()), 2)
                finally:
                    for window in (first, second):
                        if window is None:
                            continue
                        for worker in window.active_workers.values():
                            worker.requestInterruption()
                            worker.wait(2000)
                        window.close()


if __name__ == '__main__':
    unittest.main()
