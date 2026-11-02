import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ui.main_window import MainWindow


class QueueCleanupTests(unittest.TestCase):
    def test_finishing_video_queue_preserves_videos_in_output_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            videos = [output_dir / "movie.mp4", output_dir / "with-audio.mp4", output_dir / "short.mp4"]
            for video in videos[:2]:
                video.write_bytes(b"v" * (500 * 1024))
            videos[2].write_bytes(b"short video")
            (output_dir / "with-audio.mp3").write_bytes(b"a" * (500 * 1024))
            temporary = output_dir / "unfinished.part"
            temporary.write_bytes(b"partial")

            settings = Mock()
            settings.get.side_effect = lambda key, default=None: {
                "download_path": str(output_dir), "max_concurrent_downloads": 1,
            }.get(key, default)
            window = SimpleNamespace(
                _stop_requested=False,
                _pause_requested=False,
                is_downloading=True,
                active_workers={},
                download_queue=[SimpleNamespace(
                    status_state="Success",
                    item_data={"media_type": "Video (Best)", "media_type_category": "Video"},
                )],
                failed_queue=[],
                unavailable_queue=[],
                settings=settings,
                btn_stop=Mock(),
                btn_pause=Mock(),
                global_progress=Mock(),
                status_label=Mock(),
                playlists_mgr=Mock(),
                update_queue_ui=Mock(),
                refresh_playlists_ui=Mock(),
                check_post_download_action=Mock(),
                _save_queue=Mock(),
            )
            window.playlists_mgr.get_all.return_value = []

            with patch("core.downloader.ensure_audio_format") as convert, patch(
                "ui.main_window.clear_failed_log_if_clean"
            ):
                MainWindow.process_queue(window)

            convert.assert_not_called()
            self.assertTrue(all(video.exists() for video in videos))
            self.assertTrue((output_dir / "with-audio.mp3").exists())
            self.assertTrue(temporary.exists())


if __name__ == "__main__":
    unittest.main()
