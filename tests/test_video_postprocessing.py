import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.downloader import fix_video_tags, postprocess_video_file


class VideoPostprocessingTests(unittest.TestCase):
    class SettingsStub:
        def get(self, key, default=None):
            if key == "embed_all_video_metadata":
                return False
            if key == "video_metadata_tags":
                return {"thumbnail": False}
            return default

    class FakeMP4(dict):
        def __init__(self, tags):
            super().__init__(tags)
            self.save_count = 0

        def save(self):
            self.save_count += 1

    def test_fix_video_tags_cleans_year_and_fills_missing_artist_and_title(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "clip.mp4"
            video_path.touch()
            video = self.FakeMP4({"\xa9day": ["20241225"]})

            with patch("core.downloader.MP4", return_value=video):
                fix_video_tags(
                    video_path,
                    artist="Artist A",
                    title="Clip",
                    year="2023",
                    settings=self.SettingsStub(),
                )

            self.assertEqual(video["\xa9day"], ["2024"])
            self.assertEqual(video["\xa9ART"], ["Artist A"])
            self.assertEqual(video["\xa9nam"], ["Clip"])
            self.assertEqual(video.save_count, 1)

    def test_fix_video_tags_does_not_save_when_tags_are_already_valid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "clip.mp4"
            video_path.touch()
            video = self.FakeMP4({
                "\xa9day": ["2024"],
                "\xa9ART": ["Artist A"],
                "\xa9nam": ["Clip"],
            })

            with patch("core.downloader.MP4", return_value=video):
                fix_video_tags(
                    video_path,
                    artist="Artist A",
                    title="Clip",
                    year="2024",
                    settings=self.SettingsStub(),
                )

            self.assertEqual(video.save_count, 0)

    def test_postprocess_video_applies_naming_and_playlist_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "raw.mp4"
            source.write_bytes(b"video")

            with patch("core.downloader.fix_video_tags") as fix_tags, patch(
                "core.downloader.time.time", return_value=1_700_000_000
            ), patch("core.downloader.os.utime") as set_times:
                result = postprocess_video_file(
                    source,
                    playlist_index=2,
                    playlist_count=5,
                    artist="Artist A",
                    title="Clip",
                    resolution="1080p",
                    fps="60",
                    year="2024-05-02",
                    naming_pattern="{index} - {artist} - {title} ({resolution}, {fps}, {year})",
                    thumbnail_url="https://example.invalid/cover.jpg",
                )

            self.assertEqual(result.name, "02 - Artist A - Clip (1080p, 60fps, 2024).mp4")
            fix_tags.assert_called_once_with(
                source,
                artist="Artist A",
                title="Clip",
                year="2024-05-02",
                settings=None,
                thumbnail_url="https://example.invalid/cover.jpg",
            )
            set_times.assert_called_once_with(str(result), (1_699_913_603, 1_699_913_603))

    def test_postprocess_video_returns_missing_path_without_processing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.mp4"

            with patch("core.downloader.fix_video_tags") as fix_tags, patch(
                "core.downloader.os.utime"
            ) as set_times:
                result = postprocess_video_file(missing, playlist_index=1)

            self.assertEqual(result, missing)
            fix_tags.assert_not_called()
            set_times.assert_not_called()


if __name__ == "__main__":
    unittest.main()
