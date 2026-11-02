import unittest

from core.downloader import _author_and_title_match


class TrackMatchingTests(unittest.TestCase):
    def test_matches_when_artist_and_title_match(self):
        self.assertTrue(_author_and_title_match("Artist A - Song", "Song", "Artist A"))

    def test_rejects_same_title_by_different_artist(self):
        self.assertFalse(_author_and_title_match("Artist B - Song", "Song", "Artist A"))

    def test_requires_matching_version_tags(self):
        self.assertFalse(_author_and_title_match("Artist A - Song (Remix)", "Song", "Artist A"))
        self.assertTrue(_author_and_title_match("Artist A - Song (Remix)", "Song (Remix)", "Artist A"))

    def test_matches_cyrillic_title_to_latin_filename(self):
        self.assertTrue(_author_and_title_match("Artist A - Privet", "Привет", "Artist A"))


if __name__ == "__main__":
    unittest.main()
