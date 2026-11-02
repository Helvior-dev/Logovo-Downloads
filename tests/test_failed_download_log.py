import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.downloader import clear_failed_log_if_clean, log_failed_download


class FailedDownloadLogTests(unittest.TestCase):
    def test_failed_download_is_appended_to_playlist_and_app_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "playlist"
            output_dir.mkdir()
            app_dir = root / "app-data"
            app_dir.mkdir()
            failed_log = output_dir / "failed_downloads.txt"
            failed_log.write_text("Previous — Track\n", encoding="utf-8")

            with patch("core.settings.get_app_data_dir", return_value=app_dir):
                log_failed_download(
                    output_dir,
                    title="Song",
                    author="Artist",
                    url="https://example.invalid/song",
                    reason="Video unavailable",
                )

            playlist_log = failed_log.read_text(encoding="utf-8")
            self.assertTrue(playlist_log.startswith("Previous — Track\n"))
            self.assertIn("Artist — Song\n", playlist_log)
            self.assertIn("URL:    https://example.invalid/song\n", playlist_log)
            self.assertIn("Reason: Video unavailable\n", playlist_log)

            app_log = (app_dir / "app_logs.txt").read_text(encoding="utf-8")
            self.assertIn("ERROR: Failed to download 'Song': Video unavailable", app_log)

    def test_failed_log_omits_empty_url_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "playlist"
            app_dir = Path(temp_dir) / "app-data"
            app_dir.mkdir()

            with patch("core.settings.get_app_data_dir", return_value=app_dir):
                log_failed_download(output_dir, "Song", "Artist", "", "network failure")

            failed_log = output_dir / "failed_downloads.txt"
            contents = failed_log.read_text(encoding="utf-8")
            self.assertNotIn("URL:", contents)
            self.assertIn("Reason: network failure", contents)

            clear_failed_log_if_clean(output_dir)
            self.assertFalse(failed_log.exists())
            clear_failed_log_if_clean(output_dir)


if __name__ == "__main__":
    unittest.main()
