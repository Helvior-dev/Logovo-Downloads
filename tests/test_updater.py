import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import updater


def wheel_bytes(files=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in (files or {
            "yt_dlp/__init__.py": "",
            "yt_dlp/version.py": "__version__ = '2026.10.26'\n",
        }).items():
            archive.writestr(name, content)
    return stream.getvalue()


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.core = self.root / "ytdlp_core"
        self.app_dir_patch = patch("core.updater.get_app_data_dir", return_value=self.root)
        self.app_dir_patch.start()
        self.addCleanup(self.app_dir_patch.stop)

    def mock_downloads(self, content=None, digest=None):
        content = wheel_bytes() if content is None else content
        digest = hashlib.sha256(content).hexdigest() if digest is None else digest
        metadata = {"info": {"version": "2026.10.26"}, "urls": [{
            "filename": "yt_dlp-2026.10.26-py3-none-any.whl",
            "url": "https://files.pythonhosted.org/wheel.whl",
            "digests": {"sha256": digest},
        }]}
        return patch("core.updater.requests.get", side_effect=[
            SimpleNamespace(status_code=200, json=lambda: metadata),
            SimpleNamespace(status_code=200, content=content),
        ])

    def test_verified_update_activates_only_on_next_launch_and_keeps_backup(self):
        (self.core / "yt_dlp").mkdir(parents=True)
        (self.core / "yt_dlp" / "old.py").write_text("old", encoding="utf-8")

        with self.mock_downloads():
            success, message = updater.upgrade_ytdlp_core()

        self.assertTrue(success, message)
        self.assertIn("Restart", message)
        self.assertTrue((self.core / "yt_dlp" / "old.py").exists())
        self.assertTrue((self.root / "ytdlp_core_pending" / "yt_dlp" / "version.py").exists())
        with patch("core.updater.sys.path", []):
            updater.init_ytdlp_core()
            self.assertTrue((self.root / "ytdlp_core_pending").exists())
            updater.init_ytdlp_core(activate_pending=True)

        self.assertTrue((self.core / "yt_dlp" / "version.py").exists())
        self.assertFalse((self.root / "ytdlp_core_pending").exists())
        backups = list(self.root.glob("ytdlp_core_backup_*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "yt_dlp" / "old.py").read_text(encoding="utf-8"), "old")
        self.assertFalse(list(self.root.glob("ytdlp_core_stage_*")))

    def test_digest_mismatch_leaves_old_version_untouched(self):
        self.core.mkdir()
        old_file = self.core / "keep.txt"
        old_file.write_text("old", encoding="utf-8")

        with self.mock_downloads(digest="0" * 64):
            success, message = updater.upgrade_ytdlp_core()

        self.assertFalse(success)
        self.assertIn("SHA-256", message)
        self.assertEqual(old_file.read_text(encoding="utf-8"), "old")
        self.assertFalse(list(self.root.glob("ytdlp_core_stage_*")))

    def test_corrupt_wheel_keeps_old_version_and_cleans_staging(self):
        self.core.mkdir()
        (self.core / "keep.txt").write_text("old", encoding="utf-8")

        with self.mock_downloads(b"not a wheel"):
            success, message = updater.upgrade_ytdlp_core()

        self.assertFalse(success)
        self.assertIn("Upgrade error", message)
        self.assertTrue((self.core / "keep.txt").exists())
        self.assertFalse(list(self.root.glob("ytdlp_core_stage_*")))

    def test_simultaneous_update_in_same_process_is_rejected(self):
        updater._upgrade_lock.acquire()
        try:
            with patch("core.updater.requests.get") as request:
                success, message = updater.upgrade_ytdlp_core()
        finally:
            updater._upgrade_lock.release()

        self.assertFalse(success)
        self.assertIn("already running", message)
        request.assert_not_called()

    def test_missing_core_files_cannot_replace_old_version(self):
        self.core.mkdir()
        (self.core / "keep.txt").write_text("old", encoding="utf-8")

        with self.mock_downloads(wheel_bytes({"yt_dlp/__init__.py": ""})):
            success, message = updater.upgrade_ytdlp_core()

        self.assertFalse(success)
        self.assertIn("complete", message)
        self.assertTrue((self.core / "keep.txt").exists())
        self.assertFalse(list(self.root.glob("ytdlp_core_stage_*")))

    def test_wrong_version_cannot_be_staged(self):
        with self.mock_downloads(wheel_bytes({
            "yt_dlp/__init__.py": "",
            "yt_dlp/version.py": "__version__ = '2025.01.01'\n",
        })):
            success, message = updater.upgrade_ytdlp_core()

        self.assertFalse(success)
        self.assertIn("version", message)
        self.assertFalse((self.root / "ytdlp_core_pending").exists())

    def test_failed_staging_keeps_active_and_previous_pending_version(self):
        self.core.mkdir()
        (self.core / "keep.txt").write_text("old", encoding="utf-8")
        pending = self.root / "ytdlp_core_pending"
        pending.mkdir()
        (pending / "keep.txt").write_text("earlier", encoding="utf-8")
        original_rename = Path.rename

        def fail_staging_install(path, target):
            if path.name.startswith("ytdlp_core_stage_"):
                raise OSError("Install failed")
            return original_rename(path, target)

        with self.mock_downloads(), patch.object(Path, "rename", fail_staging_install):
            success, message = updater.upgrade_ytdlp_core()

        self.assertFalse(success)
        self.assertIn("Install failed", message)
        self.assertEqual((self.core / "keep.txt").read_text(encoding="utf-8"), "old")
        self.assertEqual((pending / "keep.txt").read_text(encoding="utf-8"), "earlier")
        self.assertFalse((self.root / "ytdlp_core_backup_pending").exists())
        self.assertFalse(list(self.root.glob("ytdlp_core_stage_*")))

    def test_startup_recovers_update_interrupted_after_old_core_moved(self):
        pending = self.root / "ytdlp_core_backup_pending"
        (pending / "yt_dlp").mkdir(parents=True)
        (pending / "yt_dlp" / "version.py").write_text("old", encoding="utf-8")

        with patch("core.updater.sys.path", []):
            updater.init_ytdlp_core()

        self.assertTrue((self.core / "yt_dlp" / "version.py").exists())
        self.assertFalse(pending.exists())

    def test_activation_failure_restores_old_core_and_keeps_pending_update(self):
        (self.core / "yt_dlp").mkdir(parents=True)
        (self.core / "yt_dlp" / "old.py").write_text("old", encoding="utf-8")
        pending = self.root / "ytdlp_core_pending"
        (pending / "yt_dlp").mkdir(parents=True)
        (pending / "yt_dlp" / "version.py").write_text("new", encoding="utf-8")
        original_rename = Path.rename

        def fail_pending_activation(path, target):
            if path == pending:
                raise OSError("Activation failed")
            return original_rename(path, target)

        with patch.object(Path, "rename", fail_pending_activation), patch("core.updater.sys.path", []):
            updater.init_ytdlp_core(activate_pending=True)

        self.assertTrue((self.core / "yt_dlp" / "old.py").exists())
        self.assertTrue((pending / "yt_dlp" / "version.py").exists())
        self.assertFalse((self.root / "ytdlp_core_backup_pending").exists())


if __name__ == "__main__":
    unittest.main()
