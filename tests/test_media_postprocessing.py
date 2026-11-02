import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.downloader import ensure_audio_format, postprocess_audio_file


class MediaPostprocessingTests(unittest.TestCase):
    def test_ensure_audio_format_returns_matching_format_without_running_ffmpeg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "track.mp3"
            source.touch()

            with patch("subprocess.run") as run:
                result = ensure_audio_format(source, ".mp3")

            self.assertEqual(result, source)
            run.assert_not_called()

    def test_ensure_audio_format_converts_video_container_and_removes_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "track.webm"
            target = source.with_suffix(".mp3")
            source.write_bytes(b"video")

            def run_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b"a" * 1001)
                return SimpleNamespace(returncode=0)

            with patch("core.downloader.get_ffmpeg_path", return_value="ffmpeg.exe"), patch(
                "subprocess.run", side_effect=run_ffmpeg
            ) as run:
                result = ensure_audio_format(source, ".mp3")

            self.assertEqual(result, target)
            self.assertFalse(source.exists())
            self.assertEqual(target.stat().st_size, 1001)
            command = run.call_args.args[0]
            self.assertEqual(command[:8], [
                "ffmpeg.exe", "-y", "-i", str(source), "-vn", "-c:a", "libmp3lame", "-q:a"
            ])
            self.assertEqual(command[8], "0")
            self.assertEqual(command[9], str(target))

    def test_ensure_audio_format_keeps_source_when_ffmpeg_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "track.mkv"
            source.write_bytes(b"video")

            with patch("core.downloader.get_ffmpeg_path", return_value="ffmpeg.exe"), patch(
                "subprocess.run", return_value=SimpleNamespace(returncode=1)
            ):
                result = ensure_audio_format(source, ".flac")

            self.assertEqual(result, source)
            self.assertTrue(source.exists())
            self.assertFalse(source.with_suffix(".flac").exists())

    def test_postprocess_audio_applies_tags_lyrics_naming_and_playlist_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "raw.mp3"
            source.write_bytes(b"audio")
            source.with_suffix(".lrc").write_text("[00:00.00]Lyrics line\n", encoding="utf-8")

            with patch("core.downloader.fix_mp3_cover") as fix_cover, patch(
                "core.downloader.fix_mp3_tags"
            ) as fix_tags, patch("core.downloader.time.time", return_value=1_700_000_000), patch(
                "core.downloader.os.utime"
            ) as set_times:
                result = postprocess_audio_file(
                    source,
                    playlist_index=1,
                    playlist_count=3,
                    album="Album",
                    artist="Artist A",
                    title="Song",
                    year="2025",
                    naming_pattern="{index} - {artist} - {title}",
                    thumbnail_url="https://example.invalid/cover.jpg",
                )

            self.assertEqual(result.name, "01 - Artist A - Song.mp3")
            fix_cover.assert_called_once_with(
                source,
                thumbnail_url="https://example.invalid/cover.jpg",
                artist="Artist A",
                title="Song",
            )
            self.assertEqual(fix_tags.call_args.kwargs, {
                "track_num": 1,
                "total_tracks": 3,
                "album": "Album",
                "artist": "Artist A",
                "title": "Song",
                "year": "2025",
                "lyrics": "[00:00.00]Lyrics line\n",
            })
            set_times.assert_called_once_with(str(result), (1_699_913_602, 1_699_913_602))

    def test_postprocess_audio_respects_disabled_metadata_fields(self):
        class SettingsStub:
            def get(self, key, default=None):
                if key == "embed_all_metadata":
                    return False
                if key == "audio_metadata_tags":
                    return {name: False for name in (
                        "artist", "title", "album", "cover", "track_number", "year", "lyrics"
                    )}
                return default

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "track.mp3"
            source.write_bytes(b"audio")

            with patch("core.downloader.fix_mp3_cover") as fix_cover, patch(
                "core.downloader.fix_mp3_tags"
            ) as fix_tags, patch("core.downloader.os.utime"):
                result = postprocess_audio_file(
                    source,
                    playlist_index=1,
                    playlist_count=1,
                    album="Album",
                    artist="Artist",
                    title="Title",
                    year="2024",
                    settings=SettingsStub(),
                )

            self.assertEqual(result, source)
            fix_cover.assert_not_called()
            self.assertTrue(all(value is None for value in fix_tags.call_args.kwargs.values()))


if __name__ == "__main__":
    unittest.main()
