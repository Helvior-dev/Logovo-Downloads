import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow
from ui.queue_item import QueueItemWidget
from ui.styles import get_theme_colors


class PostprocessingIndicatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_audio_processing_spinner_replaces_full_bar_and_stops(self):
        widget = QueueItemWidget({"url": "https://example.org/audio", "title": "Test audio", "media_type": "Audio (Best)"}, theme_name="cyan")
        widget.resize(700, 110)
        widget.show()
        self.app.processEvents()
        window = SimpleNamespace(download_queue=[widget], _stop_requested=False, _update_taskbar_progress=Mock())
        try:
            MainWindow.update_widget_progress(window, widget, {
                "status": "downloading", "_percent_str": "100%", "_speed_str": "1 MiB/s", "_eta_str": "0:00",
            })
            self.assertEqual(widget.progress_bar.value(), 100)
            self.assertTrue(widget.progress_bar.isVisible())
            MainWindow.update_widget_progress(window, widget, {"status": "finished"})
            self.assertEqual(widget.status_label.text(), "Converting audio...")
            self.assertTrue(widget.processing_spinner.isVisible())
            self.assertTrue(widget.processing_spinner.timer.isActive())
            self.assertFalse(widget.progress_bar.isVisible())
            self.assertFalse(widget.btn_remove.isEnabled())
            self.assertEqual(widget.processing_spinner.accent_color, get_theme_colors("cyan")["accent"])
            self.assertFalse(widget.processing_spinner.grab().isNull())

            widget.set_theme("purple")
            self.assertTrue(widget.processing_spinner.isVisible())
            self.assertEqual(widget.processing_spinner.accent_color, get_theme_colors("purple")["accent"])
            widget.set_status("Finished", "Success")
            self.assertFalse(widget.processing_spinner.isVisible())
            self.assertFalse(widget.processing_spinner.timer.isActive())
            self.assertTrue(widget.btn_remove.isEnabled())
        finally:
            widget.close()

    def test_video_processing_and_error_or_pause_stop_spinner(self):
        widget = QueueItemWidget({"url": "https://example.org/video", "title": "Test video", "media_type": "Video (Best)"})
        widget.resize(700, 110)
        widget.show()
        self.app.processEvents()
        window = SimpleNamespace(download_queue=[widget], _stop_requested=False)
        try:
            MainWindow.update_widget_progress(window, widget, {"status": "finished"})
            self.assertEqual(widget.status_label.text(), "Processing video...")
            self.assertTrue(widget.processing_spinner.isVisible())
            widget.set_status("Error", "Error")
            self.assertFalse(widget.processing_spinner.isVisible())
            widget.set_processing("Processing video...")
            widget.set_status("Paused", "Pending")
            self.assertFalse(widget.processing_spinner.isVisible())
            self.assertFalse(widget.processing_spinner.timer.isActive())
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
