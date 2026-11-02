import tempfile
import unittest
from pathlib import Path

from core.downloader import (
    autoheal_orphans_and_missing,
    is_safe_autoheal_match,
    read_archive_ids,
    read_stem_all_vids_map,
)
from core.playlist_autoheal import plan_autoheal_orphans_and_missing


class AutohealTests(unittest.TestCase):
    def _orphan(self, *, title="Artist A - Song", duration=100):
        return {
            "filename": f"{title}.mp3",
            "title": title,
            "vid": "old-id",
            "duration": duration,
        }

    def _entry(self, *, title="Song", artist="Artist A", duration=105):
        return {
            "id": "new-id",
            "title": title,
            "uploader": artist,
            "duration": duration,
        }

    def test_safe_match_requires_version_artist_and_duration_agreement(self):
        self.assertTrue(is_safe_autoheal_match(self._orphan(), self._entry()))
        self.assertFalse(is_safe_autoheal_match(self._orphan(title="Artist A - Song Remix"), self._entry()))
        self.assertFalse(is_safe_autoheal_match(self._orphan(), self._entry(artist="Artist B")))
        self.assertFalse(is_safe_autoheal_match(self._orphan(duration=100), self._entry(duration=130)))

    def test_unique_pair_updates_original_and_alternative_video_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            stem = "Artist A - Song"
            (output_dir / f"{stem}.mp3").write_bytes(b"0" * (600 * 1024))
            (output_dir / "downloaded_archive.txt").write_text("youtube old-id\n", encoding="utf-8")
            orphaned = [self._orphan()]
            missing = [self._entry()]

            remaining_orphans, remaining_missing = autoheal_orphans_and_missing(
                output_dir, orphaned, missing
            )

            self.assertEqual(remaining_orphans, [])
            self.assertEqual(remaining_missing, [])
            self.assertEqual(read_stem_all_vids_map(output_dir)[stem], {"old-id", "new-id"})
            self.assertEqual(read_archive_ids(output_dir), {"old-id", "new-id"})

    def test_ambiguous_pair_is_left_unmodified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            orphaned = [self._orphan()]
            missing = [self._entry(), self._entry()]

            remaining_orphans, remaining_missing = autoheal_orphans_and_missing(
                output_dir, orphaned, missing
            )

            self.assertEqual(remaining_orphans, orphaned)
            self.assertEqual(remaining_missing, missing)
            self.assertFalse((output_dir / "stem_vid_map.json").exists())

    def test_planning_unique_pair_does_not_write_id_map_or_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            stem = "Artist A - Song"
            (output_dir / f"{stem}.mp3").write_bytes(b"0" * (600 * 1024))
            (output_dir / "downloaded_archive.txt").write_text("youtube old-id\n", encoding="utf-8")

            remaining_orphans, remaining_missing, healed_pairs = plan_autoheal_orphans_and_missing(
                [self._orphan()],
                [self._entry()],
            )

            self.assertEqual(remaining_orphans, [])
            self.assertEqual(remaining_missing, [])
            self.assertEqual(len(healed_pairs), 1)
            self.assertFalse((output_dir / "stem_vid_map.json").exists())
            self.assertEqual(
                (output_dir / "downloaded_archive.txt").read_text(encoding="utf-8"),
                "youtube old-id\n",
            )


if __name__ == "__main__":
    unittest.main()
