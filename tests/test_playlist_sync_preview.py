import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox, QPushButton, QTextEdit

from ui.dialogs import PlaylistSyncPreviewDialog, PlaylistUpToDateDialog
from ui.main_window import MainWindow
from ui.workers import ApplyPlaylistSyncWorker, PlaylistSyncPlan, SyncPlaylistWorker


class PlaylistSyncPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_groups_counts_and_gives_download_list_readable_space(self):
        entries = [{"title": f"Song {number}", "uploader": "Artist"} for number in range(8)]
        plan = SimpleNamespace(
            playlist={"title": "Core"}, preview={"count": 411},
            missing_entries=entries, local_count=400, unavailable_entries=[],
            online_duplicates=[], orphaned_files=[], autoheal_pairs=[],
            cleanup_actions=[], redownload_from_scratch=False,
            redownload_files=[], playlist_format_update=None,
        )
        dialog = PlaylistSyncPreviewDialog(plan)
        dialog.show()
        self.app.processEvents()
        try:
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertIn("Playlist tracks", labels)
            self.assertIn("To download", labels)
            self.assertIn("TO DOWNLOAD  ·  8 tracks", labels)
            self.assertIn("Sync preview: Core", labels)
            tracks = dialog.findChildren(QTextEdit)
            self.assertEqual(len(tracks), 1)
            self.assertIn("8. Artist — Song 7", tracks[0].toPlainText())
            self.assertGreaterEqual(tracks[0].height(), 140)
            self.assertLessEqual(dialog.height(), 620)
        finally:
            dialog.close()

    def test_noop_sync_shows_up_to_date_without_apply_worker(self):
        url = "https://example.org/playlist"
        plan = SimpleNamespace(
            playlist={"url": url, "title": "Core"}, preview={"count": 411},
            missing_entries=[], local_count=411, unavailable_entries=[],
            online_duplicates=[], orphaned_files=[], autoheal_pairs=[],
            cleanup_actions=[], redownload_from_scratch=False,
            redownload_files=[], playlist_format_update=None,
        )
        window = SimpleNamespace(
            loading_overlay=Mock(), playlists_mgr=Mock(),
            status_label=Mock(), refresh_playlists_ui=Mock(),
            _active_sync_urls={url},
        )
        with patch("ui.main_window.PlaylistUpToDateDialog") as up_to_date, patch(
            "ui.main_window.PlaylistSyncPreviewDialog"
        ) as preview, patch("ui.main_window.ApplyPlaylistSyncWorker") as apply:
            MainWindow._on_sync_playlist_plan_ready(window, plan)

        up_to_date.assert_called_once()
        up_to_date.return_value.exec.assert_called_once()
        preview.assert_not_called()
        apply.assert_not_called()
        window.playlists_mgr.update_sync_info.assert_called_once_with(
            url, track_count=411, status="synced",
            unavailable_count=0, duplicates_count=0, removed_tracks_count=0,
        )
        self.assertNotIn(url, window._active_sync_urls)

    def test_planned_changes_still_require_preview(self):
        for changes in (
            {"missing_entries": [{"title": "New"}]},
            {"orphaned_files": [{"filename": "Old.mp3"}]},
            {"autoheal_pairs": [("old", "new")]},
            {"cleanup_actions": [{"action": "delete", "path": Path("old.part")}]},
            {"playlist_format_update": "windows"},
            {"redownload_from_scratch": True},
        ):
            with self.subTest(changes=changes):
                plan_data = dict(
                    playlist={"url": "https://example.org/playlist", "title": "Core"},
                    preview={"count": 1}, missing_entries=[], local_count=1,
                    unavailable_entries=[], online_duplicates=[], orphaned_files=[],
                    autoheal_pairs=[], cleanup_actions=[], redownload_from_scratch=False,
                    redownload_files=[], playlist_format_update=None,
                )
                plan_data.update(changes)
                window = SimpleNamespace(
                    loading_overlay=Mock(), status_label=Mock(),
                    _active_sync_urls={plan_data["playlist"]["url"]},
                )
                with patch("ui.main_window.PlaylistSyncPreviewDialog") as preview, patch(
                    "ui.main_window.PlaylistUpToDateDialog"
                ) as up_to_date:
                    preview.return_value.exec.return_value = QDialog.DialogCode.Rejected
                    MainWindow._on_sync_playlist_plan_ready(window, SimpleNamespace(**plan_data))
                preview.assert_called_once()
                up_to_date.assert_not_called()

    def test_up_to_date_dialog_is_compact_and_counts_only_available_tracks(self):
        dialog = PlaylistUpToDateDialog(
            "Core", 411, local_files_count=400,
            unavailable=[({"title": f"Missing {index}"}, "Unavailable") for index in range(11)],
        )
        dialog.show()
        self.app.processEvents()
        try:
            texts = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertIn("PLAYLIST UP TO DATE", texts)
            self.assertIn("All 400 available tracks are present locally.\nNo changes needed.", texts)
            self.assertLess(dialog.height(), 320)
            self.assertIn("Close", [button.text() for button in dialog.findChildren(QPushButton)])
        finally:
            dialog.close()

    def test_plan_worker_does_not_modify_playlist_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "playlist"
            output_dir.mkdir()
            temporary = output_dir / "unfinished.part"
            thumbnail = output_dir / "stale-thumbnail.webp"
            corrupt_media = output_dir / "truncated.mp3"
            temporary.write_bytes(b"partial")
            thumbnail.write_bytes(b"image fixture")
            corrupt_media.write_bytes(b"short")
            before = {path.name: path.read_bytes() for path in output_dir.iterdir()}

            playlist = {
                "url": "https://www.youtube.com/playlist?list=playlist-id",
                "folder_path": str(output_dir),
                "title": "Test Playlist",
                "media_type": "Audio",
            }
            preview = {
                "is_playlist": True,
                "count": 1,
                "thumbnail": "https://example.invalid/cover.jpg",
                "entries": [{
                    "id": "new-video-id",
                    "url": "https://www.youtube.com/watch?v=new-video-id",
                    "title": "New Track",
                    "uploader": "Artist",
                }],
            }
            plans = []
            errors = []
            worker = SyncPlaylistWorker(
                playlist,
                {"playlist_cover_mode": "both", "create_nomedia_file": True},
            )
            worker.finished_signal.connect(plans.append)
            worker.error_signal.connect(lambda *args: errors.append(args))

            with patch("ui.workers.get_video_preview", return_value=preview), patch(
                "ui.workers.apply_cleanup_plan"
            ) as cleanup, patch("ui.workers.apply_playlist_cover_settings") as cover, patch(
                "ui.workers.ensure_nomedia_file"
            ) as nomedia, patch("ui.workers.restore_dates_from_order") as restore_dates:
                worker.run()

            self.assertEqual(errors, [])
            self.assertEqual(len(plans), 1)
            plan = plans[0]
            self.assertEqual(len(plan.missing_entries), 1)
            self.assertEqual(
                {(item["path"].name, item["action"]) for item in plan.cleanup_actions},
                {
                    ("unfinished.part", "delete"),
                    ("stale-thumbnail.webp", "delete"),
                    ("truncated.mp3", "delete"),
                },
            )
            self.assertEqual({path.name: path.read_bytes() for path in output_dir.iterdir()}, before)
            self.assertFalse((output_dir / ".nomedia").exists())
            cleanup.assert_not_called()
            cover.assert_not_called()
            nomedia.assert_not_called()
            restore_dates.assert_not_called()

    def test_redownload_plan_defers_media_deletion_until_apply(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "playlist"
            output_dir.mkdir()
            media_file = output_dir / "Existing Song.mp3"
            subtitle_file = output_dir / "Existing Song.lrc"
            media_file.write_bytes(b"0" * (600 * 1024))
            subtitle_file.write_text("lyrics", encoding="utf-8")
            playlist = {
                "url": "https://www.youtube.com/playlist?list=playlist-id",
                "folder_path": str(output_dir),
                "title": "Test Playlist",
                "media_type": "Audio",
            }
            preview = {
                "is_playlist": True,
                "count": 1,
                "entries": [{
                    "id": "video-id",
                    "url": "https://www.youtube.com/watch?v=video-id",
                    "title": "Song",
                    "uploader": "Artist",
                }],
            }
            plans = []
            worker = SyncPlaylistWorker(
                playlist,
                {},
                format_compat="windows",
                playlist_format_update="windows",
                redownload_from_scratch=True,
            )
            worker.finished_signal.connect(plans.append)

            with patch("ui.workers.get_video_preview", return_value=preview):
                worker.run()

            self.assertEqual(len(plans), 1)
            self.assertEqual(set(plans[0].redownload_files), {media_file.name, subtitle_file.name})
            self.assertEqual(len(plans[0].missing_entries), 1)
            self.assertTrue(media_file.exists())
            self.assertTrue(subtitle_file.exists())

    def test_preview_selects_orphans_and_toggle_can_keep_them(self):
        orphan = {"filename": "Removed Track.mp3", "vid": "video-id"}
        analysis = {
            "entries": [],
            "raw_missing_entries": [],
            "raw_orphaned_files": [orphan],
            "missing_entries": [],
            "orphaned_files": [orphan],
            "autoheal_pairs": [],
            "local_count": 1,
            "online_duplicates": [],
            "unavailable_entries": [],
            "count": 1,
        }
        plan = PlaylistSyncPlan(
            preview={"count": 1, "entries": []},
            playlist={"title": "Test Playlist"},
            analysis=analysis,
            cleanup_actions=[],
            format_compat="windows",
            playlist_format_update=None,
            redownload_from_scratch=False,
            redownload_files=[],
        )

        dialog = PlaylistSyncPreviewDialog(plan)
        item = dialog.orphan_table.item(0, 0)
        self.assertEqual(item.checkState(), Qt.CheckState.Checked)
        self.assertEqual(dialog.selected_files_to_delete(), ["Removed Track.mp3"])
        self.assertEqual(dialog.orphan_toggle_button.text(), "Deselect All")

        dialog.orphan_toggle_button.click()
        self.assertEqual(item.checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(dialog.selected_files_to_delete(), [])
        self.assertEqual(dialog.orphan_toggle_button.text(), "Select All")

        dialog.orphan_toggle_button.click()
        self.assertEqual(dialog.selected_files_to_delete(), ["Removed Track.mp3"])
        dialog.reject()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_partial_selection_button_selects_every_orphan(self):
        orphans = [{"filename": f"Song {index}.mp3", "vid": None} for index in range(3)]
        plan = SimpleNamespace(
            playlist={"title": "Test"}, preview={"count": 0},
            missing_entries=[], local_count=3, unavailable_entries=[],
            online_duplicates=[], orphaned_files=orphans, autoheal_pairs=[],
            cleanup_actions=[], redownload_from_scratch=False,
            redownload_files=[], playlist_format_update=None,
        )
        dialog = PlaylistSyncPreviewDialog(plan)
        dialog.orphan_table.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(dialog.orphan_toggle_button.text(), "Select All")
        self.assertEqual(dialog.orphan_selection_label.text(), "2 of 3 selected for deletion")
        dialog.orphan_toggle_button.click()
        self.assertEqual(dialog.selected_files_to_delete(), [item["filename"] for item in orphans])
        dialog.reject()

    def test_declined_bulk_deletion_does_not_apply_sync(self):
        url = "https://example.org/playlist"
        plan = SimpleNamespace(
            playlist={"title": "Test", "url": url}, preview={"count": 1},
            missing_entries=[], local_count=1, unavailable_entries=[],
            online_duplicates=[], orphaned_files=[{"filename": "Keep.mp3"}],
            autoheal_pairs=[], cleanup_actions=[], redownload_from_scratch=False,
            redownload_files=[], playlist_format_update=None,
        )
        window = SimpleNamespace(
            loading_overlay=Mock(), status_label=Mock(), _active_sync_urls={url},
        )
        with patch("ui.main_window.PlaylistSyncPreviewDialog") as preview, patch(
            "ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.No
        ) as confirm, patch("ui.main_window.ApplyPlaylistSyncWorker") as apply:
            preview.return_value.exec.return_value = QDialog.DialogCode.Accepted
            preview.return_value.selected_files_to_delete.return_value = ["Keep.mp3"]
            MainWindow._on_sync_playlist_plan_ready(window, plan)

        confirm.assert_called_once()
        self.assertEqual(confirm.call_args.args[-1], QMessageBox.StandardButton.No)
        self.assertIn("permanently delete 1", confirm.call_args.args[2])
        apply.assert_not_called()
        self.assertNotIn(url, window._active_sync_urls)

    def test_confirmed_bulk_deletion_passes_only_checked_files_to_worker(self):
        plan = SimpleNamespace(
            playlist={"title": "Test", "url": "https://example.org/playlist"},
            preview={"count": 1}, missing_entries=[], local_count=1,
            unavailable_entries=[], online_duplicates=[],
            orphaned_files=[{"filename": "Delete.mp3"}, {"filename": "Keep.mp3"}],
            autoheal_pairs=[], cleanup_actions=[], redownload_from_scratch=False,
            redownload_files=[], playlist_format_update=None,
        )
        window = SimpleNamespace(
            loading_overlay=Mock(), status_label=Mock(), settings=Mock(),
            _active_sync_urls={plan.playlist["url"]},
            _on_sync_playlist_committed=Mock(), _on_sync_playlist_commit_error=Mock(),
        )
        with patch("ui.main_window.PlaylistSyncPreviewDialog") as preview, patch(
            "ui.main_window.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes
        ), patch("ui.main_window.ApplyPlaylistSyncWorker") as apply:
            preview.return_value.exec.return_value = QDialog.DialogCode.Accepted
            preview.return_value.selected_files_to_delete.return_value = ["Delete.mp3"]
            MainWindow._on_sync_playlist_plan_ready(window, plan)

        apply.assert_called_once_with(plan, ["Delete.mp3"], window.settings)
        apply.return_value.start.assert_called_once()

    def test_sync_with_all_orphan_checks_cleared_skips_delete_confirmation(self):
        plan = SimpleNamespace(
            playlist={"title": "Test", "url": "https://example.org/playlist"},
            preview={"count": 1}, missing_entries=[], local_count=1,
            unavailable_entries=[], online_duplicates=[],
            orphaned_files=[{"filename": "Keep.mp3"}],
            autoheal_pairs=[], cleanup_actions=[], redownload_from_scratch=False,
            redownload_files=[], playlist_format_update=None,
        )
        window = SimpleNamespace(
            loading_overlay=Mock(), status_label=Mock(), settings=Mock(),
            _active_sync_urls={plan.playlist["url"]},
            _on_sync_playlist_committed=Mock(), _on_sync_playlist_commit_error=Mock(),
        )
        with patch("ui.main_window.PlaylistSyncPreviewDialog") as preview, patch(
            "ui.main_window.QMessageBox.question"
        ) as confirm, patch("ui.main_window.ApplyPlaylistSyncWorker") as apply:
            preview.return_value.exec.return_value = QDialog.DialogCode.Accepted
            preview.return_value.selected_files_to_delete.return_value = []
            MainWindow._on_sync_playlist_plan_ready(window, plan)

        confirm.assert_not_called()
        apply.assert_called_once_with(plan, [], window.settings)

    def test_apply_worker_deletes_only_the_explicitly_selected_orphan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            orphan_stem = "Old Artist - Old Song"
            orphan_path = output_dir / f"{orphan_stem}.mp3"
            orphan_path.write_bytes(b"0" * (600 * 1024))
            (output_dir / "stem_vid_map.json").write_text(
                '{"Old Artist - Old Song": "old-video-id"}',
                encoding="utf-8",
            )
            playlist = {
                "url": "https://www.youtube.com/playlist?list=playlist-id",
                "folder_path": str(output_dir),
                "title": "Test Playlist",
                "media_type": "Audio",
            }
            preview = {
                "count": 1,
                "entries": [{
                    "id": "new-video-id",
                    "url": "https://www.youtube.com/watch?v=new-video-id",
                    "title": "New Song",
                    "uploader": "New Artist",
                }],
            }
            plan = PlaylistSyncPlan(
                preview=preview,
                playlist=playlist,
                analysis={},
                cleanup_actions=[],
                format_compat="windows",
                playlist_format_update=None,
                redownload_from_scratch=False,
                redownload_files=[],
            )
            results = []
            worker = ApplyPlaylistSyncWorker(plan, [orphan_path.name], {
                "playlist_cover_mode": "none",
                "create_nomedia_file": False,
            })
            worker.finished_signal.connect(results.append)

            with patch("ui.workers.apply_cleanup_plan"), patch(
                "ui.workers.restore_dates_from_order"
            ), patch("ui.workers.reindex_existing_playlist_files"):
                worker.run()

            self.assertEqual(len(results), 1)
            self.assertFalse(orphan_path.exists())
            self.assertEqual(results[0]["deleted_files"], [orphan_path.name])
            self.assertEqual([entry["id"] for entry in results[0]["missing_entries"]], ["new-video-id"])

    def test_apply_worker_keeps_unselected_orphans_and_records_the_choice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            orphan_stem = "Old Artist - Old Song"
            orphan_path = output_dir / f"{orphan_stem}.mp3"
            orphan_path.write_bytes(b"0" * (600 * 1024))
            (output_dir / "stem_vid_map.json").write_text(
                '{"Old Artist - Old Song": "old-video-id"}',
                encoding="utf-8",
            )
            playlist = {
                "url": "https://www.youtube.com/playlist?list=playlist-id",
                "folder_path": str(output_dir),
                "title": "Test Playlist",
                "media_type": "Audio",
            }
            preview = {
                "count": 1,
                "entries": [{
                    "id": "new-video-id",
                    "url": "https://www.youtube.com/watch?v=new-video-id",
                    "title": "New Song",
                    "uploader": "New Artist",
                }],
            }
            plan = PlaylistSyncPlan(
                preview=preview,
                playlist=playlist,
                analysis={},
                cleanup_actions=[],
                format_compat="windows",
                playlist_format_update=None,
                redownload_from_scratch=False,
                redownload_files=[],
            )
            results = []
            worker = ApplyPlaylistSyncWorker(plan, [], {
                "playlist_cover_mode": "none",
                "create_nomedia_file": False,
            })
            worker.finished_signal.connect(results.append)

            with patch("ui.workers.apply_cleanup_plan"), patch(
                "ui.workers.restore_dates_from_order"
            ), patch("ui.workers.reindex_existing_playlist_files"):
                worker.run()

            self.assertEqual(len(results), 1)
            self.assertTrue(orphan_path.exists())
            self.assertIn(orphan_stem, (output_dir / ".kept_orphans.json").read_text(encoding="utf-8"))
            self.assertEqual(results[0]["deleted_files"], [])


if __name__ == "__main__":
    unittest.main()
