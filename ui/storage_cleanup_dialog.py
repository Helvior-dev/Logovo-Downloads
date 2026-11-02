"""Manual cleanup of paused download fragments and old yt-dlp backups."""

import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.storage_cleanup import delete_cleanup_candidates, scan_cleanup_candidates
from ui.styles import get_theme_colors


def _format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


class StorageCleanupDialog(QDialog):
    def __init__(self, download_dirs, app_dir: Path, is_busy, parent=None):
        super().__init__(parent)
        self.download_dirs = download_dirs
        self.app_dir = app_dir
        self.is_busy = is_busy
        self.candidates = []
        colors = get_theme_colors(getattr(parent, "ui_theme", "green"))

        self.setWindowTitle("Storage Cleanup")
        self.setMinimumSize(710, 390)
        self.resize(850, 500)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("Review unused download data")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {colors['input_text']};")
        layout.addWidget(title)
        description = QLabel(
            "Only .part files in the download and tracked playlist folders and old yt-dlp backups are shown. "
            "Nothing is selected automatically. Deleting a .part file prevents resuming that file."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Item", "Location", "Size", "Modified"])
        self.table.horizontalHeader().setStretchLastSection(False)
        from PyQt6.QtWidgets import QHeaderView
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemChanged.connect(self._update_selection)
        layout.addWidget(self.table, 1)

        self.selection_label = QLabel()
        layout.addWidget(self.selection_label)

        actions = QHBoxLayout()
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.clicked.connect(self._delete_selected)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        actions.addWidget(self.btn_refresh)
        actions.addStretch()
        actions.addWidget(self.btn_delete)
        actions.addWidget(btn_close)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        self.candidates = scan_cleanup_candidates(self.download_dirs, self.app_dir)
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self.candidates))
            for row, candidate in enumerate(self.candidates):
                path = candidate["path"]
                item = QTableWidgetItem(path.name)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setToolTip(str(path))
                self.table.setItem(row, 0, item)
                self.table.setItem(row, 1, QTableWidgetItem(str(path.parent)))
                self.table.setItem(row, 2, QTableWidgetItem(_format_size(candidate["size"])))
                modified = datetime.datetime.fromtimestamp(candidate["mtime_ns"] / 1_000_000_000)
                self.table.setItem(row, 3, QTableWidgetItem(modified.strftime("%Y-%m-%d %H:%M")))
        finally:
            self.table.blockSignals(False)
        self._update_selection()

    def _selected(self):
        return [
            candidate for row, candidate in enumerate(self.candidates)
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        ]

    def _update_selection(self, *_args):
        selected = self._selected()
        self.selection_label.setText(
            f"{len(selected)} of {len(self.candidates)} selected · {_format_size(sum(item['size'] for item in selected))}"
        )
        self.btn_delete.setEnabled(bool(selected))

    def _delete_selected(self):
        selected = self._selected()
        if not selected:
            return
        if self.is_busy():
            QMessageBox.warning(self, "Cleanup unavailable", "Wait for downloads, playlist sync, and updates to finish.")
            return
        answer = QMessageBox.question(
            self, "Permanently delete selected items?",
            f"Delete {len(selected)} selected item(s), {_format_size(sum(item['size'] for item in selected))}?\n"
            "They will not go to the Recycle Bin. This may prevent resuming paused downloads.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes or self.is_busy():
            return
        deleted, errors = delete_cleanup_candidates(selected, self.download_dirs, self.app_dir)
        self.refresh()
        if errors:
            QMessageBox.warning(self, "Cleanup incomplete", f"Deleted {deleted} item(s).\n" + "\n".join(errors[:5]))
        else:
            QMessageBox.information(self, "Cleanup complete", f"Deleted {deleted} item(s).")
