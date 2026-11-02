import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

from core.downloader import (
    append_playlist_order,
    reindex_existing_playlist_files,
    restore_dates_from_order,
    write_playlist_order,
)


class PlaylistOrderTests(unittest.TestCase):
    def test_write_and_append_order_avoid_duplicate_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            write_playlist_order(output_dir, ["first.mp3", "second.mp3"])
            append_playlist_order(output_dir, "second.mp3")
            append_playlist_order(output_dir, "third.mp3")
            append_playlist_order(output_dir, "")

            self.assertEqual(
                (output_dir / "playlist_order.txt").read_text(encoding="utf-8"),
                "first.mp3\nsecond.mp3\nthird.mp3\n",
            )

    def test_restore_dates_uses_order_positions_and_skips_missing_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            first = output_dir / "first.mp3"
            last = output_dir / "last.mp3"
            first.touch()
            last.touch()
            (output_dir / "playlist_order.txt").write_text(
                "first.mp3\nmissing.mp3\nlast.mp3\n", encoding="utf-8"
            )

            with patch("core.downloader.time.time", return_value=1_700_000_000), patch(
                "core.downloader.os.utime"
            ) as set_times:
                restored = restore_dates_from_order(output_dir)

            self.assertEqual(restored, 2)
            self.assertEqual(set_times.call_args_list, [
                call(first, (1_700_000_000, 1_700_000_000)),
                call(last, (1_700_000_002, 1_700_000_002)),
            ])

    def _make_indexed_library(self, output_dir, tracks):
        mapping = {}
        for stem, video_id in tracks:
            (output_dir / f"{stem}.mp3").write_bytes(b"x" * (101 * 1024))
            mapping[stem] = video_id
        (output_dir / "stem_vid_map.json").write_text(
            json.dumps(mapping), encoding="utf-8"
        )

    def test_reindex_updates_tags_timestamps_and_playlist_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            first = output_dir / "Artist A - First.mp3"
            second = output_dir / "Artist A - Second.mp3"
            self._make_indexed_library(output_dir, [
                (first.stem, "id-first"),
                (second.stem, "id-second"),
            ])
            entries = [
                {
                    "id": "id-second", "title": "Second", "uploader": "Artist A",
                    "upload_date": "20240615", "thumbnail": "second.jpg",
                },
                {
                    "id": "id-first", "title": "First", "uploader": "Artist A",
                    "upload_date": "20230102", "thumbnail": "first.jpg",
                },
            ]

            with patch("core.downloader.time.time", return_value=1_700_000_000), patch(
                "core.downloader.os.utime"
            ) as set_times, patch("core.downloader.fix_mp3_tags") as fix_tags, patch(
                "core.downloader.fix_mp3_cover"
            ) as fix_cover:
                reindex_existing_playlist_files(output_dir, entries)

            order = (output_dir / "playlist_order.txt").read_text(encoding="utf-8")
            self.assertEqual(order, f"{second.name}\n{first.name}\n")
            tag_calls = {call.kwargs["title"]: call.kwargs for call in fix_tags.call_args_list}
            self.assertEqual(tag_calls["Second"]["track_num"], 2)
            self.assertEqual(tag_calls["Second"]["total_tracks"], 2)
            self.assertEqual(tag_calls["Second"]["year"], "2024")
            self.assertEqual(tag_calls["First"]["track_num"], 1)
            self.assertEqual(fix_cover.call_count, 2)
            self.assertEqual(set_times.call_args_list, [
                call(str(second), (1_699_913_602, 1_699_913_602)),
                call(str(first), (1_699_913_601, 1_699_913_601)),
            ])

    def test_reindex_respects_disabled_metadata_settings(self):
        class SettingsStub:
            def get(self, key, default=None):
                if key == "embed_all_metadata":
                    return False
                if key == "audio_metadata_tags":
                    return {name: False for name in (
                        "track_number", "album", "artist", "title", "year", "cover"
                    )}
                return default

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            track = output_dir / "Artist A - Song.mp3"
            self._make_indexed_library(output_dir, [(track.stem, "id-song")])

            with patch("core.downloader.fix_mp3_tags") as fix_tags, patch(
                "core.downloader.fix_mp3_cover"
            ) as fix_cover, patch("core.downloader.os.utime"):
                reindex_existing_playlist_files(
                    output_dir,
                    [{"id": "id-song", "title": "Song", "uploader": "Artist A"}],
                    SettingsStub(),
                )

            self.assertEqual(fix_tags.call_count, 1)
            self.assertTrue(all(value is None for value in fix_tags.call_args.kwargs.values()))
            fix_cover.assert_not_called()


if __name__ == "__main__":
    unittest.main()
