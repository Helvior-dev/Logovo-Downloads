import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.downloader import cleanup_orphan_files, plan_cleanup_orphan_files


class CleanupOrphanFilesTests(unittest.TestCase):
    def test_removes_temporary_files_and_thumbnails_but_keeps_service_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            removable = (
                "download.part", "download.ytdl", "download.tmp", "download.temp",
                "thumbnail.webp", "thumbnail.png", "thumbnail.jpg", "thumbnail.jpeg",
            )
            protected = (
                "cover.png", "cover.jpg", "cover.jpeg", "cover.webp", "cover.ico",
                "folder.ico", "desktop.ini", ".nomedia", "playlist_format.txt",
                "stem_vid_map.json", "playlist_order.txt", "downloaded_archive.txt",
                "failed_downloads.txt", "app_logs.txt",
            )
            for name in removable + protected:
                (output_dir / name).write_bytes(b"fixture")

            cleaned_count = cleanup_orphan_files(output_dir)

            self.assertEqual(cleaned_count, len(removable))
            self.assertTrue(all(not (output_dir / name).exists() for name in removable))
            self.assertTrue(all((output_dir / name).exists() for name in protected))

    def test_non_audio_cleanup_preserves_video_even_when_small(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "truncated.mp3").write_bytes(b"x" * (500 * 1024 - 1))
            (output_dir / "valid.mp3").write_bytes(b"x" * (500 * 1024))
            (output_dir / "truncated.mp4").write_bytes(b"x" * (500 * 1024 - 1))
            (output_dir / "video.mp4").write_bytes(b"x" * (500 * 1024))

            cleaned_count = cleanup_orphan_files(output_dir, is_audio_playlist=False)

            self.assertEqual(cleaned_count, 1)
            self.assertFalse((output_dir / "truncated.mp3").exists())
            self.assertTrue((output_dir / "truncated.mp4").exists())
            self.assertTrue((output_dir / "valid.mp3").exists())
            self.assertTrue((output_dir / "video.mp4").exists())

    def test_audio_playlist_removes_video_duplicate_when_audio_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            (output_dir / "Track.mp3").write_bytes(b"x" * (500 * 1024))
            (output_dir / "Track.mp4").write_bytes(b"x" * (500 * 1024))

            cleaned_count = cleanup_orphan_files(output_dir, is_audio_playlist=True)

            self.assertEqual(cleaned_count, 1)
            self.assertTrue((output_dir / "Track.mp3").exists())
            self.assertFalse((output_dir / "Track.mp4").exists())

    def test_audio_playlist_converts_unpaired_video_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            video_path = output_dir / "Unpaired.webm"
            video_path.write_bytes(b"x" * (500 * 1024))

            with patch("core.downloader.ensure_audio_format", return_value=output_dir / "Unpaired.mp3") as convert:
                cleaned_count = cleanup_orphan_files(output_dir, is_audio_playlist=True)

            self.assertEqual(cleaned_count, 1)
            convert.assert_called_once_with(video_path, ".mp3")

    def test_missing_directory_returns_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_dir = Path(temp_dir) / "not-created"

            self.assertEqual(cleanup_orphan_files(missing_dir), 0)

    def test_cleanup_plan_describes_actions_without_mutating_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            temporary = output_dir / "download.part"
            corrupt = output_dir / "truncated.mp3"
            raw_video = output_dir / "leftover.webm"
            temporary.write_bytes(b"partial")
            corrupt.write_bytes(b"x" * 100)
            raw_video.write_bytes(b"x" * (500 * 1024))

            actions = plan_cleanup_orphan_files(output_dir, is_audio_playlist=True)

            self.assertEqual(
                {(item["path"].name, item["action"]) for item in actions},
                {
                    ("download.part", "delete"),
                    ("truncated.mp3", "delete"),
                    ("leftover.webm", "convert_to_audio"),
                },
            )
            self.assertTrue(temporary.exists())
            self.assertTrue(corrupt.exists())
            self.assertTrue(raw_video.exists())


if __name__ == "__main__":
    unittest.main()
