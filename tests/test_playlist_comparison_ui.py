"""Offline UI checks for local playlist comparison and its deletion guard."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

from ui.playlist_comparison_dialog import CrossPlaylistComparisonDialog
from ui.styles import get_theme_colors


class PlaylistComparisonUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_pair_filters_search_and_confirmation_on_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            playlists = []
            for title, names in (
                ('First', ('Artist - Shared.mp3', 'Artist - Only First.mp3')),
                ('Second', ('Artist - Shared.mp3', 'Artist - Only Second.mp3')),
            ):
                directory = root / title
                directory.mkdir()
                for name in names:
                    (directory / name).write_bytes(b'test audio')
                playlists.append({'title': title, 'folder_path': str(directory)})

            class Manager:
                def get_all(self):
                    return playlists

            parent = QWidget()
            parent.ui_theme = 'cyan'
            with patch('ui.playlist_comparison_dialog.QTimer.singleShot'):
                dialog = CrossPlaylistComparisonDialog(Manager(), default_target='Second', parent=parent)
            dialog.show()
            self.app.processEvents()
            try:
                self.assertIn(get_theme_colors('cyan')['root_bg'], dialog.styleSheet())
                self.assertEqual(dialog.combo_mode.currentText(), 'One playlist')
                self.assertIn('other tracked folder', dialog.mode_description.text())
                dialog.combo_mode.setCurrentIndex(1)
                dialog.resize(1080, 640)
                self.app.processEvents()
                self.assertNotEqual(dialog.combo_target.currentIndex(), dialog.combo_target_b.currentIndex())
                self.assertEqual(dialog.btn_tab_common.text(), 'Shared (1)')
                self.assertEqual(dialog.btn_tab_only_a.text(), 'Only A (1)')
                self.assertEqual(dialog.btn_tab_only_b.text(), 'Only B (1)')
                self.assertEqual(dialog.table.rowCount(), 1)
                self.assertFalse(dialog.empty_state.isVisible())
                self.assertGreater(dialog.table.height(), 200)
                for button in (dialog.btn_tab_common, dialog.btn_tab_only_a, dialog.btn_tab_only_b, dialog.btn_tab_all):
                    self.assertGreaterEqual(button.width(), button.fontMetrics().horizontalAdvance(button.text()) + 20)
                self.assertIn('watch?v=video-id', dialog._get_track_url({
                    'track_a': {'vid': ''}, 'track_b': {'vid': 'video-id'},
                }, 'Artist - Shared.mp3'))

                dialog.btn_tab_only_a.click()
                self.assertEqual(dialog.table.rowCount(), 1)
                dialog.search_edit.setText('nothing matches')
                self.assertEqual(dialog.table.rowCount(), 0)
                self.assertIn('Clear the search field', dialog.empty_state.text())
                self.assertFalse(dialog.btn_copy.isEnabled())
                dialog.search_edit.clear()
                self.assertEqual(dialog.table.rowCount(), 1)

                dialog.btn_tab_common.click()
                shared = playlists[0]['folder_path']
                track = str(Path(shared) / 'Artist - Shared.mp3')
                with patch('ui.playlist_comparison_dialog.QMessageBox.question', return_value=QMessageBox.StandardButton.Cancel):
                    dialog._confirm_and_delete_track(track, 'First', 'Artist - Shared')
                self.assertTrue(Path(track).exists())

                dialog.combo_mode.setCurrentIndex(2)
                self.assertFalse(dialog.combo_target.isVisible())
                self.assertGreaterEqual(dialog.table.rowCount(), 1)
                self.assertEqual(dialog.search_edit.placeholderText(), 'Track, artist or playlist name')
                self.assertEqual(dialog.btn_copy.text(), 'Copy visible results')
            finally:
                dialog.close()
                parent.close()

    def test_pair_mode_explains_when_only_one_playlist_is_tracked(self):
        with tempfile.TemporaryDirectory() as folder:
            class Manager:
                def get_all(self):
                    return [{'title': 'Only playlist', 'folder_path': folder}]

            with patch('ui.playlist_comparison_dialog.QTimer.singleShot'):
                dialog = CrossPlaylistComparisonDialog(Manager())
            dialog.show()
            self.app.processEvents()
            try:
                dialog.combo_mode.setCurrentIndex(1)
                self.assertEqual(dialog.table.rowCount(), 0)
                self.assertIn('Track at least two playlists', dialog.empty_state.text())
                self.assertFalse(dialog.btn_copy.isEnabled())
            finally:
                dialog.close()

    def test_empty_library_explains_where_to_start(self):
        class Manager:
            def get_all(self):
                return []

        with patch('ui.playlist_comparison_dialog.QTimer.singleShot'):
            dialog = CrossPlaylistComparisonDialog(Manager())
        dialog.show()
        self.app.processEvents()
        try:
            dialog.run_scan()
            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertIn('Add one in the Playlists tab', dialog.empty_state.text())
        finally:
            dialog.close()


if __name__ == '__main__':
    unittest.main()
