import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.downloader import MediaDownloader
from core.playlist_comparator import PlaylistComparator
from core.settings import SettingsManager


class SettingsStub:
    def get(self, key, default=None):
        return default


class CoreRegressionTests(unittest.TestCase):
    def test_settings_reload_migrates_legacy_cookie_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = SettingsManager.__new__(SettingsManager)
            manager.settings_file = Path(temp_dir) / "settings.json"
            manager.default_settings = {
                "cookies_source": "none",
                "cookies_browser": "chrome",
                "cookies_file": "",
                "quality_settings": {},
            }
            manager.settings = {"stale": True}
            manager.settings_file.write_text(json.dumps({
                "cookie_source_type": "browser",
                "cookie_browser": "firefox",
                "cookie_file": "legacy-cookies.txt",
            }), encoding="utf-8")

            loaded = manager.reload()

            self.assertIs(manager.settings, loaded)
            self.assertEqual(loaded["cookies_source"], "browser")
            self.assertEqual(loaded["cookies_browser"], "firefox")
            self.assertEqual(loaded["cookies_file"], "legacy-cookies.txt")
            self.assertNotIn("cookie_source_type", loaded)

    def test_cancelled_download_does_not_start_ytdlp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader.__new__(MediaDownloader)
            downloader.output_dir = temp_dir
            downloader.settings = SettingsStub()
            downloader.format_compat = None
            downloader.last_error = ""
            downloader.was_skipped = False
            downloader.was_cancelled = False

            with patch("core.settings.get_app_data_dir", return_value=Path(temp_dir)), \
                    patch("core.downloader.yt_dlp.YoutubeDL") as youtube_dl:
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    cancel_check=lambda: True,
                )

            self.assertEqual(result, (False, "", False))
            self.assertTrue(downloader.was_cancelled)
            youtube_dl.assert_not_called()

    def test_cancelled_download_stops_on_progress_hook_without_retry(self):
        class FakeYoutubeDL:
            instances = []

            def __init__(self, options):
                self.options = options
                self.instances.append(self)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def download(self, _urls):
                for hook in self.options["progress_hooks"]:
                    hook({"status": "downloading"})
                return 0

        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = MediaDownloader.__new__(MediaDownloader)
            downloader.output_dir = temp_dir
            downloader.settings = SettingsStub()
            downloader.format_compat = None
            downloader.last_error = ""
            downloader.was_skipped = False
            downloader.was_cancelled = False
            cancel_checks = 0

            def cancel_after_download_starts():
                nonlocal cancel_checks
                cancel_checks += 1
                return cancel_checks >= 2

            with patch("core.settings.get_app_data_dir", return_value=Path(temp_dir)), \
                    patch("core.downloader.yt_dlp.YoutubeDL", FakeYoutubeDL):
                result = downloader.download(
                    "https://www.youtube.com/watch?v=abcdefghijk",
                    cancel_check=cancel_after_download_starts,
                )

            self.assertEqual(result, (False, "", False))
            self.assertTrue(downloader.was_cancelled)
            self.assertEqual(len(FakeYoutubeDL.instances), 1)

    def test_all_playlist_audit_keeps_different_artists_separate(self):
        def make_track(artist, playlist):
            return {
                "vids": set(),
                "vid": "",
                "clean_title": "same song",
                "clean_artist": artist,
                "tags": set(),
                "ct_vars": {"same song"},
                "ca_vars": {artist},
                "title": "Same Song",
                "artist": artist,
                "filename": f"{artist}.mp3",
                "playlist": playlist,
            }

        playlists = type("PlaylistsStub", (), {"get_all": lambda self: []})()
        comparator = PlaylistComparator(playlists)
        comparator.pl_index = {
            "A": [make_track("Artist A", "A")],
            "B": [make_track("Artist B", "B")],
            "C": [make_track("Artist A", "C")],
        }

        results = comparator.compare_all_playlists()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["unique_playlists"], ["A", "C"])
        self.assertEqual(len(results[0]["tracks"]), 2)


if __name__ == "__main__":
    unittest.main()
