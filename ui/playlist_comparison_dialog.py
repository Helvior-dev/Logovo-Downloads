import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QMessageBox, QApplication, QFrame, QWidget
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices

from core.playlist_comparator import PlaylistComparator
from core.playlists_manager import PlaylistsManager


class CrossPlaylistComparisonDialog(QDialog):
    """Dialog that analyzes and displays track intersections and duplicates across playlists."""

    def __init__(self, playlists_mgr: PlaylistsManager = None, default_target: str = "Trash", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cross-Playlist Track Comparison")
        self.setMinimumSize(960, 580)

        self.pm = playlists_mgr or PlaylistsManager()
        self.comparator = PlaylistComparator(self.pm)
        self.raw_results = []
        self.filtered_results = []

        self.setup_ui(default_target)
        self.run_scan()

    def setup_ui(self, default_target: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # Header
        header_layout = QVBoxLayout()
        header_title = QLabel("<h3>🔍 Cross-Playlist Track Comparison</h3>")
        header_title.setStyleSheet("color: #f8fafc; margin-bottom: 2px;")
        header_desc = QLabel(
            "Analyze your library to find songs that exist in multiple playlists simultaneously.\n"
            "Quickly identify tracks in collection playlists (like Trash) that are already organized in your main playlists."
        )
        header_desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        header_desc.setWordWrap(True)

        header_layout.addWidget(header_title)
        header_layout.addWidget(header_desc)
        layout.addLayout(header_layout)

        # Controls Bar
        controls_frame = QFrame()
        controls_frame.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 6px;
            }
        """)
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(10, 8, 10, 8)
        controls_layout.setSpacing(12)

        lbl_mode = QLabel("Mode:")
        lbl_mode.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px;")
        controls_layout.addWidget(lbl_mode)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["Compare Single Playlist", "Compare All Playlists (Audit)"])
        self.combo_mode.setStyleSheet("""
            QComboBox {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
            }
        """)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        controls_layout.addWidget(self.combo_mode)

        self.lbl_target = QLabel("Target Playlist:")
        self.lbl_target.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px;")
        controls_layout.addWidget(self.lbl_target)

        self.combo_target = QComboBox()
        self.combo_target.setStyleSheet("""
            QComboBox {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
            }
        """)
        all_pls = self.pm.get_all()
        target_idx = 0
        for i, p in enumerate(all_pls):
            t = p.get('title', 'Untitled')
            self.combo_target.addItem(t)
            if t.lower() == default_target.lower():
                target_idx = i

        if all_pls:
            self.combo_target.setCurrentIndex(target_idx)

        self.combo_target.currentIndexChanged.connect(self._on_target_changed)
        controls_layout.addWidget(self.combo_target)

        controls_layout.addSpacing(10)

        # Search box
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Filter by track name, artist, or playlist...")
        self.search_edit.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 12px;
            }
        """)
        self.search_edit.textChanged.connect(self._filter_results)
        controls_layout.addWidget(self.search_edit, 1)

        btn_rescan = QPushButton("🔄 Rescan")
        btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_rescan.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        btn_rescan.clicked.connect(self.run_scan)
        controls_layout.addWidget(btn_rescan)

        layout.addWidget(controls_frame)

        # Results Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Track / File", "Also Exists In Playlists", "Actions"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
                color: #f1f5f9;
                gridline-color: #1e293b;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: bold;
                font-size: 12px;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #334155;
            }
        """)
        layout.addWidget(self.table, 1)

        # Bottom Bar
        bottom_bar = QHBoxLayout()
        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 500;")
        bottom_bar.addWidget(self.lbl_status)
        bottom_bar.addStretch()

        btn_copy = QPushButton("📋 Copy Overlap List")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #334155;
            }
        """)
        btn_copy.clicked.connect(self._copy_results)
        bottom_bar.addWidget(btn_copy)

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(100)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: white;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)

        layout.addLayout(bottom_bar)

    def _on_mode_changed(self):
        is_single = (self.combo_mode.currentIndex() == 0)
        self.lbl_target.setVisible(is_single)
        self.combo_target.setVisible(is_single)
        self.run_scan()

    def _on_target_changed(self):
        if self.combo_mode.currentIndex() == 0:
            self.run_scan()

    def run_scan(self):
        """Scans folders and performs comparison based on selected mode."""
        self.comparator.scan_all_playlists()
        is_single = (self.combo_mode.currentIndex() == 0)

        if is_single:
            target = self.combo_target.currentText()
            self.table.setHorizontalHeaderLabels([f"Track in '{target}'", "Also Found In Playlists", "Actions"])
            self.raw_results = self.comparator.compare_single_playlist(target)
        else:
            self.table.setHorizontalHeaderLabels(["Track / Title", "Shared In Playlists (Clustered)", "Actions"])
            self.raw_results = self.comparator.compare_all_playlists()

        self._filter_results()

    def _filter_results(self):
        query = (self.search_edit.text() or "").strip().lower()
        is_single = (self.combo_mode.currentIndex() == 0)

        filtered = []
        for item in self.raw_results:
            if is_single:
                tt = item.get('primary_track', {})
                fname = tt.get('filename', '').lower()
                art = tt.get('artist', '').lower()
                other_pls = " ".join([o.get('playlist', '').lower() for o in item.get('other_playlists', [])])
                if not query or query in fname or query in art or query in other_pls:
                    filtered.append(item)
            else:
                title = item.get('title', '').lower()
                art = item.get('artist', '').lower()
                pls = " ".join([p.lower() for p in item.get('unique_playlists', [])])
                if not query or query in title or query in art or query in pls:
                    filtered.append(item)

        self.filtered_results = filtered
        self._populate_table()

    def _populate_table(self):
        is_single = (self.combo_mode.currentIndex() == 0)
        self.table.setRowCount(len(self.filtered_results))

        for row, item in enumerate(self.filtered_results):
            if is_single:
                tt = item.get('primary_track', {})
                display_name = tt.get('filename', 'Unknown')
                fp = tt.get('filepath', '')
                other_pls = item.get('other_playlists', [])
                pls_str = ", ".join([f"<b>{o['playlist']}</b>" for o in other_pls])

                item_track = QTableWidgetItem(display_name)
                item_track.setForeground(QColor("#f8fafc"))
                self.table.setItem(row, 0, item_track)

                item_pls = QTableWidgetItem()
                item_pls.setText(f"{', '.join([o['playlist'] for o in other_pls])} ({len(other_pls)} other playlist{'s' if len(other_pls) > 1 else ''})")
                item_pls.setForeground(QColor("#38bdf8"))
                self.table.setItem(row, 1, item_pls)

                # Actions Box
                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(4, 2, 4, 2)
                actions_layout.setSpacing(6)

                btn_folder = QPushButton("📁 Folder")
                btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_folder.setStyleSheet("""
                    QPushButton {
                        background: #1e293b;
                        color: #94a3b8;
                        border: 1px solid #334155;
                        border-radius: 4px;
                        padding: 3px 8px;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background: #334155;
                        color: #ffffff;
                    }
                """)
                btn_folder.clicked.connect(lambda _, path=fp: self._open_file_in_explorer(path))
                actions_layout.addWidget(btn_folder)

                btn_delete = QPushButton("🗑️ Delete from Target")
                btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_delete.setStyleSheet("""
                    QPushButton {
                        background: #450a0a;
                        color: #f87171;
                        border: 1px solid #7f1d1d;
                        border-radius: 4px;
                        padding: 3px 8px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background: #991b1b;
                        color: #ffffff;
                    }
                """)
                btn_delete.clicked.connect(lambda _, path=fp, name=display_name: self._delete_track(path, name))
                actions_layout.addWidget(btn_delete)

                self.table.setCellWidget(row, 2, actions_widget)

            else:
                title = item.get('title', 'Unknown')
                artist = item.get('artist', '')
                display_name = f"{artist} - {title}" if artist else title
                pls = item.get('unique_playlists', [])
                pls_str = f"{len(pls)} playlists: {', '.join(pls)}"

                item_track = QTableWidgetItem(display_name)
                item_track.setForeground(QColor("#f8fafc"))
                self.table.setItem(row, 0, item_track)

                item_pls = QTableWidgetItem(pls_str)
                item_pls.setForeground(QColor("#10b981"))
                self.table.setItem(row, 1, item_pls)

                actions_widget = QWidget()
                actions_layout = QHBoxLayout(actions_widget)
                actions_layout.setContentsMargins(4, 2, 4, 2)
                actions_layout.setSpacing(6)

                btn_copy_info = QPushButton("📋 Copy Info")
                btn_copy_info.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_copy_info.setStyleSheet("""
                    QPushButton {
                        background: #1e293b;
                        color: #38bdf8;
                        border: 1px solid #334155;
                        border-radius: 4px;
                        padding: 3px 8px;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background: #0284c7;
                        color: #ffffff;
                    }
                """)
                info_text = f"{display_name}\nShared in: {', '.join(pls)}"
                btn_copy_info.clicked.connect(lambda _, t=info_text: QApplication.clipboard().setText(t))
                actions_layout.addWidget(btn_copy_info)

                self.table.setCellWidget(row, 2, actions_widget)

        count = len(self.filtered_results)
        if is_single:
            target = self.combo_target.currentText()
            self.lbl_status.setText(f"Found <b>{count}</b> track(s) in '<b>{target}</b>' that already exist in your other playlists.")
        else:
            self.lbl_status.setText(f"Found <b>{count}</b> cross-playlist track cluster(s) across your entire music collection.")

    def _open_file_in_explorer(self, filepath: str):
        if filepath and os.path.exists(filepath):
            folder = os.path.dirname(filepath)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        elif filepath:
            folder = os.path.dirname(filepath)
            if os.path.exists(folder):
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _delete_track(self, filepath: str, track_name: str):
        reply = QMessageBox.question(
            self,
            "Confirm File Deletion",
            f"Are you sure you want to delete this track from your collection?\n\n'{track_name}'\n\n(It already exists in your other playlists)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if os.path.exists(filepath):
                    os.remove(filepath)
                self.run_scan()
                QMessageBox.information(self, "Deleted", f"Deleted '{track_name}' successfully.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete file: {e}")

    def _copy_results(self):
        is_single = (self.combo_mode.currentIndex() == 0)
        lines = []
        for i, item in enumerate(self.filtered_results, 1):
            if is_single:
                tt = item.get('primary_track', {})
                fname = tt.get('filename', 'Unknown')
                other_pls = [o.get('playlist', '') for o in item.get('other_playlists', [])]
                lines.append(f"{i}. {fname}\n   Already in: {', '.join(other_pls)}")
            else:
                title = item.get('title', 'Unknown')
                artist = item.get('artist', '')
                display_name = f"{artist} - {title}" if artist else title
                pls = item.get('unique_playlists', [])
                lines.append(f"{i}. {display_name}\n   Shared across {len(pls)} playlists: {', '.join(pls)}")

        QApplication.clipboard().setText("\n\n".join(lines))
        QMessageBox.information(self, "Copied", "Comparison results copied to clipboard!")
