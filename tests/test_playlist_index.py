import json
import tempfile
import unittest
from pathlib import Path

from core.downloader import (
    build_local_files_index,
    detect_orphan_files_in_folder,
    is_entry_in_index,
)


class PlaylistIndexTests(unittest.TestCase):
    def _make_library(self, output_dir):
        stems = (
            "Artist A - Song",
            "Artist A - Old Song",
            "Artist B - Same Title",
        )
        for stem in stems:
            (output_dir / f"{stem}.mp3").write_bytes(b"0" * (600 * 1024))

        (output_dir / "stem_vid_map.json").write_text(json.dumps({
            "Artist A - Song": {"vid": "alt-song", "original_vid": "vid-song"},
            "Artist A - Old Song": "vid-old",
            "Artist B - Same Title": "vid-other",
            "Missing File": "stale-id",
        }), encoding="utf-8")

    def test_index_uses_existing_file_ids_and_respects_artist_and_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            self._make_library(output_dir)

            video_ids, title_index, valid_count = build_local_files_index(output_dir)

            self.assertEqual(valid_count, 3)
            self.assertEqual(video_ids, {"vid-song", "alt-song", "vid-old", "vid-other"})
            self.assertTrue(is_entry_in_index("vid-song", "Song", "Artist A", video_ids, title_index))
            self.assertTrue(is_entry_in_index("", "Song", "Artist A", video_ids, title_index))
            self.assertFalse(is_entry_in_index("", "Song", "Artist B", video_ids, title_index))
            self.assertFalse(is_entry_in_index("", "Song Remix", "Artist A", video_ids, title_index))

    def test_orphan_detection_ignores_online_and_user_kept_tracks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            self._make_library(output_dir)
            (output_dir / ".kept_orphans.json").write_text(
                json.dumps(["Artist A - Old Song.mp3"]), encoding="utf-8"
            )

            orphans = detect_orphan_files_in_folder(output_dir, [{
                "id": "vid-song",
                "title": "Song",
                "uploader": "Artist A",
            }])

            self.assertEqual([item["filename"] for item in orphans], ["Artist B - Same Title.mp3"])
            self.assertEqual(orphans[0]["vid"], "vid-other")

    def test_pending_audio_conversion_is_included_in_read_only_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            video_container = output_dir / "Artist A - Song.webm"
            video_container.write_bytes(b"0" * (600 * 1024))
            (output_dir / "stem_vid_map.json").write_text(
                json.dumps({"Artist A - Song": "vid-song"}),
                encoding="utf-8",
            )
            online_entry = {
                "id": "vid-song",
                "title": "Song",
                "uploader": "Artist A",
            }

            video_ids, title_index, valid_count = build_local_files_index(
                output_dir,
                additional_files=[video_container],
            )
            orphans = detect_orphan_files_in_folder(
                output_dir,
                [online_entry],
                additional_files=[video_container],
            )

            self.assertEqual(valid_count, 1)
            self.assertTrue(is_entry_in_index("vid-song", "Song", "Artist A", video_ids, title_index))
            self.assertEqual(orphans, [])
            self.assertTrue(video_container.exists())


if __name__ == "__main__":
    unittest.main()
