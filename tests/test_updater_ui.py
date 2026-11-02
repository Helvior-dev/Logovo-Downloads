import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.main_window import MainWindow


class UpdaterUiTests(unittest.TestCase):
    def test_successful_core_update_without_removed_version_label(self):
        window = SimpleNamespace(status_label=Mock())
        with patch("ui.main_window.QMessageBox.information") as information:
            MainWindow.on_upgrade_finished(window, True, "yt-dlp v2026.10.26 ready. Restart the app to activate it.")

        information.assert_called_once_with(window, "Update Complete", "yt-dlp v2026.10.26 ready. Restart the app to activate it.")
        window.status_label.setText.assert_called_once_with("yt-dlp update ready. Restart the app to activate it.")

    def test_failed_core_update_still_reports_error(self):
        window = SimpleNamespace(status_label=Mock())
        with patch("ui.main_window.QMessageBox.warning") as warning:
            MainWindow.on_upgrade_finished(window, False, "Network failure")

        warning.assert_called_once_with(window, "Upgrade Failed", "Failed to upgrade yt-dlp core:\n\nNetwork failure")
        window.status_label.setText.assert_called_once_with("Core upgrade failed.")

    def test_update_does_not_start_during_active_downloads(self):
        window = SimpleNamespace(active_workers={"download": object()})
        with patch("ui.main_window.QMessageBox.warning") as warning, patch(
            "ui.main_window.UpgradeWorker"
        ) as worker:
            MainWindow.run_ytdlp_upgrade(window)

        warning.assert_called_once()
        worker.assert_not_called()

    def test_close_waits_for_active_update(self):
        window = SimpleNamespace(upgrade_worker=Mock(), _save_queue=Mock())
        window.upgrade_worker.isRunning.return_value = True
        event = Mock()
        with patch("ui.main_window.QMessageBox.information") as information:
            MainWindow.closeEvent(window, event)

        event.ignore.assert_called_once()
        information.assert_called_once()
        window._save_queue.assert_not_called()


if __name__ == "__main__":
    unittest.main()
