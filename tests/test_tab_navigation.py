import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QScrollArea, QTabWidget, QWidget

from ui.main_window import CustomTabBar


class TabNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_wheel_on_tab_bar_does_not_change_tab_but_click_does(self):
        tabs = QTabWidget()
        bar = CustomTabBar(tabs)
        tabs.setTabBar(bar)
        for name in ("DOWNLOADS", "PLAYLISTS", "HISTORY", "SETTINGS", "ABOUT"):
            tabs.addTab(QWidget(), name)
        tabs.resize(700, 350)
        tabs.show()
        self.app.processEvents()

        try:
            for delta in (-120, 120):
                wheel = QWheelEvent(
                    QPointF(bar.tabRect(0).center()),
                    QPointF(bar.mapToGlobal(bar.tabRect(0).center())),
                    QPoint(0, 0), QPoint(0, delta),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.ScrollUpdate, False,
                )
                QApplication.sendEvent(bar, wheel)
                self.assertTrue(wheel.isAccepted())
                self.assertEqual(tabs.currentIndex(), 0)

            QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.tabRect(2).center())
            self.assertEqual(tabs.currentIndex(), 2)

            area = QScrollArea(tabs.widget(2))
            area.setWidget(QLabel("row\n" * 100))
            area.resize(200, 100)
            area.show()
            self.app.processEvents()
            self.assertGreater(area.verticalScrollBar().maximum(), 0)
            before = area.verticalScrollBar().value()
            viewport = area.viewport()
            center = viewport.rect().center()
            scroll = QWheelEvent(
                QPointF(center), QPointF(viewport.mapToGlobal(center)),
                QPoint(0, 0), QPoint(0, -120),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.ScrollUpdate, False,
            )
            QApplication.sendEvent(viewport, scroll)
            self.assertGreater(area.verticalScrollBar().value(), before)
            self.assertEqual(tabs.currentIndex(), 2)
        finally:
            tabs.close()


if __name__ == "__main__":
    unittest.main()
