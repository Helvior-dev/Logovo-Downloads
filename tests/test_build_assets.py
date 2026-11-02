import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.prepare_build_assets import download_verified, extract_zip_member, sha256_file


class BuildAssetTests(unittest.TestCase):
    def test_download_verified_rejects_hash_mismatch_and_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "asset.zip"

            with patch(
                "tools.prepare_build_assets.urllib.request.urlopen",
                return_value=io.BytesIO(b"untrusted archive"),
            ):
                with self.assertRaises(ValueError):
                    download_verified("https://example.invalid/asset.zip", "0" * 64, destination)

            self.assertFalse(destination.exists())

    def test_zip_member_is_copied_to_fixed_destination_without_path_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "asset.zip"
            destination = root / "output" / "ffmpeg.exe"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../../outside/bin/ffmpeg.exe", b"verified member")

            extract_zip_member(archive_path, "ffmpeg.exe", destination, parent_name="bin")

            self.assertEqual(destination.read_bytes(), b"verified member")
            self.assertFalse((root.parent / "outside" / "bin" / "ffmpeg.exe").exists())

    def test_sha256_fixture_matches_expected_digest(self):
        contents = b"build assets"
        with tempfile.TemporaryDirectory() as temp_dir:
            asset_path = Path(temp_dir) / "asset.bin"
            asset_path.write_bytes(contents)
            self.assertEqual(
                sha256_file(asset_path),
                hashlib.sha256(contents).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
