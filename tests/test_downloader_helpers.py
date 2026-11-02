import tempfile
import unittest
from pathlib import Path

from core.downloader import (
    clean_media_url,
    detect_platform_name,
    friendly_error,
    is_platform_unavailable,
    is_rate_limited,
    is_valid_netscape_cookies,
    parse_speed_limit,
)


class DownloaderHelperTests(unittest.TestCase):
    def test_friendly_error_maps_known_errors_and_cleans_unknown_messages(self):
        self.assertEqual(friendly_error("HTTP Error 429: Too many requests"), "YouTube Rate Limit (429) — try again later")
        self.assertEqual(friendly_error("\x1b[31mERROR: custom failure. Details omitted\x1b[0m"), "custom failure")
        self.assertEqual(friendly_error(""), "Unknown error")

    def test_rate_limit_and_unavailable_classification_excludes_cookie_errors(self):
        self.assertTrue(is_rate_limited("HTTP Error 429: Too many requests"))
        self.assertFalse(is_rate_limited("Video unavailable"))
        self.assertTrue(is_platform_unavailable("This video has been removed"))
        self.assertFalse(is_platform_unavailable("Video unavailable: try again later"))
        self.assertFalse(is_platform_unavailable("Failed to load cookies"))

    def test_netscape_cookie_validation_accepts_header_or_cookie_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            header_file = root / "header.txt"
            header_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
            row_file = root / "row.txt"
            row_file.write_text(".example.com\tTRUE\t/\tFALSE\t0\tname\tvalue\n", encoding="utf-8")
            invalid_file = root / "invalid.txt"
            invalid_file.write_text("not a cookie file\n", encoding="utf-8")

            self.assertTrue(is_valid_netscape_cookies(str(header_file)))
            self.assertTrue(is_valid_netscape_cookies(str(row_file)))
            self.assertFalse(is_valid_netscape_cookies(str(invalid_file)))
            self.assertFalse(is_valid_netscape_cookies(str(root / "missing.txt")))

    def test_platform_detection_handles_specific_hosts_and_fallback(self):
        cases = (
            ("https://music.youtube.com/watch?v=abc", "YouTube Music"),
            ("https://youtu.be/abc", "YouTube"),
            ("https://soundcloud.com/artist/track", "SoundCloud"),
            ("https://vkvideo.ru/video-1", "VK Video"),
            ("ytsearch5:Artist Song", "YouTube Search"),
            ("https://example.invalid/media", "Media Service"),
            ("", "Media Service"),
        )
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(detect_platform_name(url), expected)

    def test_clean_media_url_preserves_supported_youtube_params_and_drops_tracking(self):
        url = "https://music.youtube.com/watch?v=abc&list=PLx&index=3&si=track&t=42"
        self.assertEqual(
            clean_media_url(url),
            "https://www.youtube.com/watch?v=abc&t=42",
        )
        self.assertEqual(
            clean_media_url(url, keep_list=True),
            "https://www.youtube.com/watch?v=abc&list=PLx&t=42",
        )
        self.assertEqual(
            clean_media_url("https://youtube.com/playlist?list=PLx&si=track"),
            "https://youtube.com/playlist?list=PLx",
        )
        self.assertEqual(clean_media_url("ytsearch5:Artist Song"), "ytsearch5:Artist Song")

    def test_clean_media_url_removes_known_third_party_tracking_params(self):
        url = "https://soundcloud.com/artist/track?utm_source=share&si=tracking&feature=share"
        self.assertEqual(
            clean_media_url(url),
            "https://soundcloud.com/artist/track?feature=share",
        )

    def test_parse_speed_limit_converts_units_and_rejects_unlimited_or_invalid_values(self):
        cases = (
            ("500 KB/s", 500 * 1024),
            ("1.5 MB/s", int(1.5 * 1024 * 1024)),
            ("2 Gbps", 2 * 1024 * 1024 * 1024),
            ("256", 256),
            ("Unlimited", None),
            ("not a speed", None),
            (None, None),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(parse_speed_limit(value), expected)


if __name__ == "__main__":
    unittest.main()
