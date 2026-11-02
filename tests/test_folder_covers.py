import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image

from core.downloader import (
    apply_playlist_cover_settings,
    save_playlist_cover_image,
    set_folder_icon,
)


class FolderCoverTests(unittest.TestCase):
    def test_save_playlist_cover_writes_png_and_removes_legacy_jpg(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "playlist"
            folder.mkdir()
            legacy_jpg = folder / "cover.jpg"
            legacy_jpg.write_bytes(b"old cover")
            image = Image.new("RGB", (320, 180), "orange")

            with patch("core.downloader.is_root_or_general_folder", return_value=False):
                saved_path = save_playlist_cover_image(folder, image, cover_style="original")

            self.assertEqual(saved_path, folder / "cover.png")
            self.assertTrue(saved_path.exists())
            self.assertFalse(legacy_jpg.exists())
            with Image.open(saved_path) as cover:
                self.assertEqual(cover.format, "PNG")
                self.assertEqual(cover.size, (320, 180))

    def test_set_folder_icon_writes_icon_ini_and_applies_windows_attributes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "playlist"
            image = Image.new("RGB", (64, 64), "blue")
            windll = Mock()

            with patch("core.downloader.is_root_or_general_folder", return_value=False), patch(
                "ctypes.windll", windll, create=True
            ):
                result = set_folder_icon(folder, image, cover_style="square")

            self.assertTrue(result)
            self.assertTrue((folder / "folder_icon.ico").exists())
            desktop_ini = (folder / "desktop.ini").read_text(encoding="utf-8")
            self.assertIn("IconResource=folder_icon.ico,0", desktop_ini)
            self.assertEqual(windll.kernel32.SetFileAttributesW.call_count, 3)
            windll.shell32.SHChangeNotify.assert_called_once()

    def test_cover_and_icon_helpers_refuse_protected_folders(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            protected = Path(temp_dir) / "protected"
            image = Image.new("RGB", (32, 32), "black")

            with patch("core.downloader.is_root_or_general_folder", return_value=True):
                self.assertIsNone(save_playlist_cover_image(protected, image))
                self.assertFalse(set_folder_icon(protected, image))
                apply_playlist_cover_settings(protected, image, mode="both")

            self.assertFalse(protected.exists())

    def test_apply_playlist_cover_settings_dispatches_modes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / "playlist"
            image = Image.new("RGB", (32, 32), "black")
            with patch("core.downloader.is_root_or_general_folder", return_value=False), patch(
                "core.downloader.save_playlist_cover_image"
            ) as save_cover, patch("core.downloader.set_folder_icon") as set_icon:
                apply_playlist_cover_settings(folder, image, mode="file")
                apply_playlist_cover_settings(folder, image, mode="icon")
                apply_playlist_cover_settings(folder, image, mode="both")
                apply_playlist_cover_settings(folder, image, mode="none")

            self.assertEqual(save_cover.call_count, 2)
            self.assertEqual(set_icon.call_count, 2)


if __name__ == "__main__":
    unittest.main()
