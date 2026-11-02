import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QPushButton

from core.settings import SettingsManager
from ui.main_window import MainWindow
from ui.storage_cleanup_dialog import StorageCleanupDialog
from ui.styles import get_theme_colors


class SettingsNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_existing_settings_remain_in_named_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("core.settings.get_app_data_dir", return_value=root):
                settings = SettingsManager()
            settings.settings.update({
                "download_path": str(root),
                "check_ytdlp_updates_on_startup": False,
                "check_app_updates_on_startup": False,
                "check_playlists_on_startup": False,
            })
            with patch("ui.main_window.SettingsManager", return_value=settings), patch(
                "ui.main_window.get_app_data_dir", return_value=root
            ), patch("core.history.get_app_data_dir", return_value=root), patch(
                "core.playlists_manager.get_app_data_dir", return_value=root
            ), patch("core.queue_state.queue_state_path", return_value=root / "pending_queue.json"), patch.object(
                MainWindow, "setup_tray"
            ), patch("ui.main_window.QTimer.singleShot"):
                window = MainWindow()
                try:
                    pages = window.settings_sections
                    self.assertEqual(
                        [pages.tabText(index) for index in range(pages.count())],
                        ["GENERAL", "AUDIO", "VIDEO", "QUALITY", "ACCESS", "MAINTENANCE"],
                    )
                    for section, control in (
                        (0, window.ui_theme_combo),
                        (0, window.folder_input),
                        (0, window.threads_combo),
                        (1, window.naming_input),
                        (1, window.chk_audio_lyrics),
                        (2, window.v_naming_input),
                        (2, window.v_container_combo),
                        (3, window.settings_sections.widget(3).widget()),
                        (4, window.cookies_source_combo),
                        (5, window.btn_self_diagnostics),
                    ):
                        self.assertTrue(pages.widget(section).isAncestorOf(control))
                    self.assertEqual(window.naming_input.text(), settings.get("naming_pattern"))
                    window.resize(1150, 720)
                    window.show()
                    window.tabs.setCurrentWidget(window.settings_tab)
                    self.app.processEvents()
                    self.assertEqual(
                        {window.ui_theme_combo.itemData(i) for i in range(window.ui_theme_combo.count())},
                        {"green", "blue", "pink", "red", "amber", "cyan", "violet"},
                    )
                    for theme in ("blue", "pink", "amber", "cyan", "violet"):
                        window.ui_theme_combo.setCurrentIndex(window.ui_theme_combo.findData(theme))
                        self.app.processEvents()
                        self.assertEqual(settings.get("ui_theme"), theme)
                        scroll = pages.widget(0)
                        wrapper = scroll.widget()
                        self.assertEqual(wrapper.objectName(), "SettingsScrollWrapper")
                        background = scroll.viewport().grab().toImage().pixelColor(8, 90).name()
                        self.assertEqual(background, get_theme_colors(theme)["root_bg"])

                    tab_bar = pages.tabBar()
                    for delta in (-120, 120):
                        wheel = QWheelEvent(
                            QPointF(25, 15), QPointF(25, 15), QPoint(0, 0), QPoint(0, delta),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.ScrollUpdate, False,
                        )
                        self.app.sendEvent(tab_bar, wheel)
                        self.assertEqual(pages.currentIndex(), 0)
                    window.resize(880, 640)
                    window.tabs.setCurrentWidget(window.downloads_tab)
                    self.app.processEvents()
                    self.assertEqual(window.minimumSize().height(), 640)
                    self.assertGreaterEqual(window.queue_scroll_area.height(), 350)
                    self.assertLessEqual(
                        window.btn_download_all.mapTo(window, window.btn_download_all.rect().bottomLeft()).y(),
                        window.height(),
                    )
                    pages.setCurrentIndex(5)
                    window.tabs.setCurrentWidget(window.settings_tab)
                    self.app.processEvents()
                    maintenance_scroll = pages.widget(5)
                    scroll_bar = maintenance_scroll.verticalScrollBar()
                    scroll_bar.setValue(scroll_bar.maximum())
                    self.assertEqual(scroll_bar.value(), scroll_bar.maximum())
                    review = next(
                        button for button in pages.widget(5).findChildren(QPushButton)
                        if button.text() == "Review Files..."
                    )
                    playlist_dir = root / "playlist"
                    window.playlists_mgr.playlists = [{"folder_path": str(playlist_dir)}]
                    opened = []
                    with patch.object(StorageCleanupDialog, "exec", lambda dialog: opened.append(dialog)):
                        review.click()
                    self.assertEqual(len(opened), 1)
                    dialog = opened[0]
                    self.assertEqual(dialog.download_dirs, [str(root), str(playlist_dir)])
                    self.assertFalse(dialog.is_busy())
                    window.is_downloading = True
                    self.assertTrue(dialog.is_busy())
                    window.is_downloading = False
                    window._active_sync_urls = {"https://example.org/list"}
                    self.assertTrue(dialog.is_busy())
                finally:
                    window.close()


if __name__ == "__main__":
    unittest.main()
