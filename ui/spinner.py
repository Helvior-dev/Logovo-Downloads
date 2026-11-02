"""Theme-aware busy indicator for operations without measurable progress."""

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ui.styles import get_theme_colors


class SpinnerWidget(QWidget):
    def __init__(self, parent=None, size=40):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.accent_color = get_theme_colors()["accent"]
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)

    def set_theme(self, theme_name: str):
        self.accent_color = get_theme_colors(theme_name)["accent"]
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start(30)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def rotate(self):
        self.angle = (self.angle + 15) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)
        radius = max(3, (self.width() - 10) // 2)
        pen = QPen(QColor(self.accent_color), 2 if self.width() < 30 else 3,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(-radius, -radius, radius * 2, radius * 2, 0, 270 * 16)
        painter.end()
