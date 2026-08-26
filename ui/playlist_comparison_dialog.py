import os
import re
import json
import urllib.parse
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QMessageBox, QApplication, QFrame, QWidget,
    QScrollArea
)
from PyQt6.QtCore import Qt, QUrl, QTimer
from PyQt6.QtGui import QColor, QDesktopServices

from core.playlist_comparator import PlaylistComparator
from core.playlists_manager import PlaylistsManager
from core.downloader import read_raw_stem_vid_map


class TrackOverlapDetailsDialog(QDialog):
    """Clean popup dialog showing all playlists and locations where a track exists."""

    def __init__(self, display_name: str, playlists_data: list[dict], track_url: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Track Overlap Breakdown")
        self.setStyleSheet("QDialog { background-color: #0b0e14; color: #f8fafc; }")
        self.setFixedSize(680, 440)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 18, 20, 18)

        # Header
        header = QLabel(f"<h3>🎵 {display_name}</h3>")
        header.setStyleSheet("color: #38bdf8; font-weight: bold; margin-bottom: 0px;")
        header.setWordWrap(True)
        layout.addWidget(header)

        sub = QLabel(f"This track is present in <b>{len(playlists_data)}</b> of your tracked playlists:")
        sub.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(sub)

        # Scroll area with playlist cards
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
            }
        """)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        container_layout = QVBoxLayout(container)
        container_layout.setSpacing(8)
        container_layout.setContentsMargins(10, 10, 10, 10)

        for i, item in enumerate(playlists_data, 1):
            pl_name = item.get('playlist', 'Unknown Playlist')
            fp = item.get('filepath', '')

            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background-color: #1e293b;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    padding: 8px;
                }
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 8, 10, 8)
            card_layout.setSpacing(4)

            top_row = QHBoxLayout()
            lbl_name = QLabel(f"<b>#{i}. {pl_name}</b>")
            lbl_name.setStyleSheet("color: #10b981; font-size: 13px;")
            top_row.addWidget(lbl_name)
            top_row.addStretch()

            if fp and os.path.exists(fp):
                btn_open_f = QPushButton("📁 Folder")
                btn_open_f.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_open_f.setStyleSheet("""
                    QPushButton {
                        background-color: #0f172a;
                        color: #94a3b8;
                        border: 1px solid #475569;
                        border-radius: 4px;
                        padding: 3px 8px;
                        font-size: 11px;
                        font-weight: 500;
                    }
                    QPushButton:hover {
                        background-color: #334155;
                        color: #ffffff;
                    }
                """)
                btn_open_f.clicked.connect(lambda _, p=fp: self._open_in_explorer(p))
                top_row.addWidget(btn_open_f)

            card_layout.addLayout(top_row)

            if fp:
                lbl_path = QLabel(f"Path: {fp}")
                lbl_path.setStyleSheet("color: #64748b; font-size: 11px;")
                lbl_path.setWordWrap(True)
                card_layout.addWidget(lbl_path)

            container_layout.addWidget(card)

        container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # Bottom actions
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        if track_url:
            btn_browser = QPushButton("Open in Browser ↗")
            btn_browser.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_browser.setStyleSheet("""
                QPushButton {
                    background-color: #2563eb;
                    color: white;
                    border-radius: 6px;
                    padding: 6px 14px;
                    font-weight: bold;
                    font-size: 12px;
                    border: none;
                }
                QPushButton:hover {
                    background-color: #1d4ed8;
                }
            """)
            btn_browser.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(track_url)))
            btn_layout.addWidget(btn_browser)

        btn_layout.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(90)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: white;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

    def _open_in_explorer(self, filepath: str):
        if filepath and os.path.exists(filepath):
            folder = os.path.dirname(filepath)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


class CrossPlaylistComparisonDialog(QDialog):
    """Dialog that analyzes and displays track intersections and duplicates across playlists."""

    def __init__(self, playlists_mgr: PlaylistsManager = None, default_target: str = "Trash", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cross-Playlist Track Comparison")
        self.setStyleSheet("QDialog { background-color: #0b0e14; }")
        self.setMinimumSize(1080, 640)
        self.resize(1160, 680)

        self.pm = playlists_mgr or PlaylistsManager()
        self.comparator = PlaylistComparator(self.pm)
        self.raw_results = []
        self.filtered_results = []
        self.pair_results = {}
        self.current_pair_subtab = "common"

        self.setup_ui(default_target)
        QTimer.singleShot(10, self.run_scan)

    def setup_ui(self, default_target: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header_layout = QVBoxLayout()
        header_title = QLabel("<h3>🔍 Cross-Playlist Track Comparison</h3>")
        header_title.setStyleSheet("color: #f8fafc; margin-bottom: 2px;")
        header_desc = QLabel(
            "Analyze your library to find songs that exist in multiple playlists simultaneously.\n"
            "Compare pairs of playlists (A ↔ B), audit single playlists against all others, or inspect overall collection duplicates."
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
        controls_layout.setSpacing(10)

        lbl_mode = QLabel("Mode:")
        lbl_mode.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px;")
        controls_layout.addWidget(lbl_mode)

        self.combo_mode = QComboBox()
        self.combo_mode.blockSignals(True)
        self.combo_mode.addItems([
            "Compare Single Playlist",
            "Compare Two Playlists (A ↔ B)",
            "Compare All Playlists (Audit)"
        ])
        self.combo_mode.setStyleSheet("""
            QComboBox {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 12px;
            }
        """)
        self.combo_mode.blockSignals(False)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        controls_layout.addWidget(self.combo_mode)

        # Target A selector
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
                padding: 5px 10px;
                font-size: 12px;
                min-width: 140px;
            }
        """)
        controls_layout.addWidget(self.combo_target)

        # Swap button for A ↔ B mode
        self.btn_swap = QPushButton("⇄")
        self.btn_swap.setToolTip("Swap Playlist A and Playlist B")
        self.btn_swap.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_swap.setFixedSize(30, 28)
        self.btn_swap.setStyleSheet("""
            QPushButton {
                background-color: #0f172a;
                color: #38bdf8;
                border: 1px solid #475569;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        self.btn_swap.clicked.connect(self._swap_playlists)
        self.btn_swap.setVisible(False)
        controls_layout.addWidget(self.btn_swap)

        # Target B selector (for A ↔ B mode)
        self.lbl_target_b = QLabel("Playlist B:")
        self.lbl_target_b.setStyleSheet("color: #f8fafc; font-weight: bold; font-size: 12px;")
        self.lbl_target_b.setVisible(False)
        controls_layout.addWidget(self.lbl_target_b)

        self.combo_target_b = QComboBox()
        self.combo_target_b.setStyleSheet("""
            QComboBox {
                background-color: #0f172a;
                color: #f8fafc;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 12px;
                min-width: 140px;
            }
        """)
        self.combo_target_b.setVisible(False)
        controls_layout.addWidget(self.combo_target_b)

        all_pls = self.pm.get_all()
        target_idx_a = 0
        target_idx_b = 1 if len(all_pls) > 1 else 0

        self.combo_target.blockSignals(True)
        self.combo_target_b.blockSignals(True)
        for i, p in enumerate(all_pls):
            t = p.get('title', 'Untitled')
            self.combo_target.addItem(t)
            self.combo_target_b.addItem(t)
            if t.lower() == default_target.lower():
                target_idx_a = i

        if all_pls:
            self.combo_target.setCurrentIndex(target_idx_a)
            self.combo_target_b.setCurrentIndex(target_idx_b)

        self.combo_target.blockSignals(False)
        self.combo_target_b.blockSignals(False)
        self.combo_target.currentIndexChanged.connect(self._on_target_changed)
        self.combo_target_b.currentIndexChanged.connect(self._on_target_b_changed)

        controls_layout.addSpacing(6)

        # Search box
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Filter by track name, artist...")
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

        self.btn_rescan = QPushButton("🔄 Rescan")
        self.btn_rescan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_rescan.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.btn_rescan.clicked.connect(self.run_scan)
        controls_layout.addWidget(self.btn_rescan)

        layout.addWidget(controls_frame)

        # Sub-tabs bar for Mode 1 (A ↔ B)
        self.subtabs_frame = QFrame()
        self.subtabs_frame.setStyleSheet("""
            QFrame {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
                padding: 4px;
            }
        """)
        subtabs_layout = QHBoxLayout(self.subtabs_frame)
        subtabs_layout.setContentsMargins(8, 4, 8, 4)
        subtabs_layout.setSpacing(8)

        self.btn_tab_common = QPushButton("Common / Overlaps (0)")
        self.btn_tab_common.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_common.clicked.connect(lambda: self._set_pair_subtab("common"))
        subtabs_layout.addWidget(self.btn_tab_common)

        self.btn_tab_only_a = QPushButton("Only in A (0)")
        self.btn_tab_only_a.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_only_a.clicked.connect(lambda: self._set_pair_subtab("only_a"))
        subtabs_layout.addWidget(self.btn_tab_only_a)

        self.btn_tab_only_b = QPushButton("Only in B (0)")
        self.btn_tab_only_b.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_only_b.clicked.connect(lambda: self._set_pair_subtab("only_b"))
        subtabs_layout.addWidget(self.btn_tab_only_b)

        self.btn_tab_all = QPushButton("All Tracks (0)")
        self.btn_tab_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_all.clicked.connect(lambda: self._set_pair_subtab("all"))
        subtabs_layout.addWidget(self.btn_tab_all)

        subtabs_layout.addStretch()

        self.lbl_pair_stats = QLabel("")
        self.lbl_pair_stats.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 500;")
        subtabs_layout.addWidget(self.lbl_pair_stats)

        self.subtabs_frame.setVisible(False)
        layout.addWidget(self.subtabs_frame)

        # Results Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Track / File", "Also Exists In Playlists", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 360)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.cellClicked.connect(self._on_table_cell_clicked)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
                color: #f1f5f9;
                gridline-color: transparent;
                outline: none;
            }
            QTableWidget::item {
                padding: 6px 10px;
                border-bottom: 1px solid #1e293b;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: bold;
                font-size: 12px;
                padding: 8px 10px;
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
        bottom_bar.addSpacing(16)

        lbl_hint = QLabel("💡 <i>Click any row to open detailed breakdown & paths</i>")
        lbl_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        bottom_bar.addWidget(lbl_hint)

        bottom_bar.addStretch()

        btn_copy = QPushButton("📋 Copy Results")
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
                border: none;
            }
            QPushButton:hover {
                background-color: #475569;
            }
        """)
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)

        layout.addLayout(bottom_bar)

    def _on_mode_changed(self):
        mode = self.combo_mode.currentIndex()
        is_single = (mode == 0)
        is_pair = (mode == 1)

        self.lbl_target.setVisible(is_single or is_pair)
        self.lbl_target.setText("Playlist A:" if is_pair else "Target Playlist:")
        self.combo_target.setVisible(is_single or is_pair)

        self.btn_swap.setVisible(is_pair)
        self.lbl_target_b.setVisible(is_pair)
        self.combo_target_b.setVisible(is_pair)

        self.subtabs_frame.setVisible(is_pair)

        # Clear table immediately to prevent any ghost cells
        self.table.clearContents()
        self.table.setRowCount(0)

        self.run_scan()

    def _swap_playlists(self):
        idx_a = self.combo_target.currentIndex()
        idx_b = self.combo_target_b.currentIndex()
        self.combo_target.blockSignals(True)
        self.combo_target_b.blockSignals(True)
        self.combo_target.setCurrentIndex(idx_b)
        self.combo_target_b.setCurrentIndex(idx_a)
        self.combo_target.blockSignals(False)
        self.combo_target_b.blockSignals(False)
        self.run_scan()

    def _on_target_changed(self):
        mode = self.combo_mode.currentIndex()
        if mode == 0:
            self.run_scan()
        elif mode == 1:
            if self.combo_target.currentIndex() == self.combo_target_b.currentIndex():
                next_idx = (self.combo_target.currentIndex() + 1) % max(1, self.combo_target_b.count())
                self.combo_target_b.blockSignals(True)
                self.combo_target_b.setCurrentIndex(next_idx)
                self.combo_target_b.blockSignals(False)
            self.run_scan()

    def _on_target_b_changed(self):
        if self.combo_mode.currentIndex() == 1:
            if self.combo_target_b.currentIndex() == self.combo_target.currentIndex():
                next_idx = (self.combo_target_b.currentIndex() + 1) % max(1, self.combo_target.count())
                self.combo_target.blockSignals(True)
                self.combo_target.setCurrentIndex(next_idx)
                self.combo_target.blockSignals(False)
            self.run_scan()

    def _set_pair_subtab(self, tab_name: str):
        self.current_pair_subtab = tab_name
        self._update_pair_subtabs()
        self._apply_pair_results_to_raw()
        self._filter_results()

    def run_scan(self):
        """Scans folders in real-time and performs comparison based on selected mode."""
        self.btn_rescan.setEnabled(False)
        self.combo_mode.setEnabled(False)
        self.lbl_status.setText("⏳ Comparing playlists...")
        QApplication.processEvents()

        try:
            self.comparator.scan_all_playlists()
            mode = self.combo_mode.currentIndex()

            if mode == 0:
                target = self.combo_target.currentText()
                self.table.setColumnCount(3)
                self.table.setHorizontalHeaderLabels([f"Track in '{target}'", "Also Found In Playlists", "Action"])
                self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(0, 360)
                self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(2, 140)
                self.raw_results = self.comparator.compare_single_playlist(target)

            elif mode == 1:
                target_a = self.combo_target.currentText()
                target_b = self.combo_target_b.currentText()
                self.table.setColumnCount(4)
                self.table.setHorizontalHeaderLabels(["Track / Title", f"File in '{target_a}'", f"File in '{target_b}'", "Action"])
                self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(0, 280)
                self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
                self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(3, 120)

                self.pair_results = self.comparator.compare_two_playlists(target_a, target_b)
                self._update_pair_subtabs()
                self._apply_pair_results_to_raw()

            else:
                self.table.setColumnCount(3)
                self.table.setHorizontalHeaderLabels(["Track / Title", "Shared In Playlists (Clustered)", "Action"])
                self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
                self.table.setColumnWidth(0, 360)
                self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
                self.table.setColumnWidth(2, 140)
                self.raw_results = self.comparator.compare_all_playlists()

            self._filter_results()
        finally:
            self.btn_rescan.setEnabled(True)
            self.combo_mode.setEnabled(True)

    def _update_pair_subtabs(self):
        stats = self.pair_results.get('stats', {})
        common_cnt = stats.get('common_count', 0)
        only_a_cnt = stats.get('only_a_count', 0)
        only_b_cnt = stats.get('only_b_count', 0)
        total_cnt = common_cnt + only_a_cnt + only_b_cnt

        target_a = self.combo_target.currentText()
        target_b = self.combo_target_b.currentText()

        self.btn_tab_common.setText(f"Common / Overlaps ({common_cnt})")
        self.btn_tab_only_a.setText(f"Only in {target_a} ({only_a_cnt})")
        self.btn_tab_only_b.setText(f"Only in {target_b} ({only_b_cnt})")
        self.btn_tab_all.setText(f"All Tracks ({total_cnt})")

        pct_a = stats.get('overlap_pct_a', 0)
        pct_b = stats.get('overlap_pct_b', 0)
        self.lbl_pair_stats.setText(f"Overlap: <b>{common_cnt}</b> tracks ({pct_a}% of A, {pct_b}% of B)")

        for tab_name, btn in [
            ('common', self.btn_tab_common),
            ('only_a', self.btn_tab_only_a),
            ('only_b', self.btn_tab_only_b),
            ('all', self.btn_tab_all),
        ]:
            if tab_name == self.current_pair_subtab:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2563eb;
                        color: #ffffff;
                        border: 1px solid #3b82f6;
                        border-radius: 6px;
                        padding: 5px 12px;
                        font-weight: bold;
                        font-size: 11px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #1e293b;
                        color: #94a3b8;
                        border: 1px solid #334155;
                        border-radius: 6px;
                        padding: 5px 12px;
                        font-weight: 500;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background-color: #334155;
                        color: #f8fafc;
                    }
                """)

    def _apply_pair_results_to_raw(self):
        subtab = self.current_pair_subtab
        if subtab == 'common':
            self.raw_results = list(self.pair_results.get('common', []))
        elif subtab == 'only_a':
            self.raw_results = [
                {'track_a': ta, 'title': ta.get('title'), 'artist': ta.get('artist'), 'display_name': ta.get('filename'), 'vid': ta.get('vid')}
                for ta in self.pair_results.get('only_a', [])
            ]
        elif subtab == 'only_b':
            self.raw_results = [
                {'track_b': tb, 'title': tb.get('title'), 'artist': tb.get('artist'), 'display_name': tb.get('filename'), 'vid': tb.get('vid')}
                for tb in self.pair_results.get('only_b', [])
            ]
        else:  # 'all'
            all_list = []
            for c in self.pair_results.get('common', []):
                all_list.append(dict(c))
            for ta in self.pair_results.get('only_a', []):
                all_list.append({'track_a': ta, 'title': ta.get('title'), 'artist': ta.get('artist'), 'display_name': ta.get('filename'), 'vid': ta.get('vid')})
            for tb in self.pair_results.get('only_b', []):
                all_list.append({'track_b': tb, 'title': tb.get('title'), 'artist': tb.get('artist'), 'display_name': tb.get('filename'), 'vid': tb.get('vid')})
            self.raw_results = all_list

    def _filter_results(self):
        query = (self.search_edit.text() or "").strip().lower()
        mode = self.combo_mode.currentIndex()

        filtered = []
        for item in self.raw_results:
            if mode == 0:
                tt = item.get('primary_track', {})
                fname = tt.get('filename', '').lower()
                art = tt.get('artist', '').lower()
                other_pls = " ".join([o.get('playlist', '').lower() for o in item.get('other_playlists', [])])
                if not query or query in fname or query in art or query in other_pls:
                    filtered.append(item)
            elif mode == 1:
                disp = (item.get('display_name') or '').lower()
                t = (item.get('title') or '').lower()
                a = (item.get('artist') or '').lower()
                fname_a = (item.get('track_a', {}).get('filename') or '').lower()
                fname_b = (item.get('track_b', {}).get('filename') or '').lower()
                if not query or query in disp or query in t or query in a or query in fname_a or query in fname_b:
                    filtered.append(item)
            else:
                title = item.get('title', '').lower()
                art = item.get('artist', '').lower()
                pls = " ".join([p.lower() for p in item.get('unique_playlists', [])])
                if not query or query in title or query in art or query in pls:
                    filtered.append(item)

        self.filtered_results = filtered
        self._populate_table()

    def _get_track_url(self, item: dict, display_name: str) -> str:
        """Get best YouTube URL for a track (direct video ID or YouTube Music search)."""
        vid = item.get('vid')
        if not vid and 'primary_track' in item:
            vid = item['primary_track'].get('vid')
            if not vid:
                for o in item.get('other_playlists', []):
                    if o.get('track', {}).get('vid'):
                        vid = o['track']['vid']
                        break
        elif not vid and 'track_a' in item:
            vid = item['track_a'].get('vid')
        elif not vid and 'track_b' in item:
            vid = item['track_b'].get('vid')
        elif not vid and 'tracks' in item:
            for t in item.get('tracks', []):
                if t.get('vid'):
                    vid = t['vid']
                    break

        if vid:
            return f"https://www.youtube.com/watch?v={vid}"

        clean_q = re.sub(r'\.(mp3|flac|m4a|opus|ogg|wav)$', '', display_name, flags=re.IGNORECASE).strip()
        return f"https://music.youtube.com/search?q={urllib.parse.quote(clean_q)}"

    def _confirm_and_delete_track(self, filepath: str, pl_title: str, track_display: str):
        """Strictly prompt user before deleting file, then immediately rescan and refresh table."""
        if not filepath or not os.path.exists(filepath):
            QMessageBox.warning(self, "File Not Found", f"File does not exist on disk:\n{filepath}")
            return

        reply = QMessageBox.question(
            self,
            "Confirm File Deletion",
            f"Are you sure you want to permanently delete this track from '{pl_title}'?\n\n"
            f"Track: {track_display}\n"
            f"File: {os.path.basename(filepath)}\n"
            f"Path: {filepath}\n\n"
            f"This action will permanently delete the audio file from your drive.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel  # Default button is Cancel for safety!
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(filepath)
                # Clean from stem_vid_map
                folder = os.path.dirname(filepath)
                stem = Path(filepath).stem
                raw_map = read_raw_stem_vid_map(folder)
                if stem in raw_map:
                    raw_map.pop(stem, None)
                    map_path = os.path.join(folder, "stem_vid_map.json")
                    with open(map_path, "w", encoding="utf-8") as f:
                        json.dump(raw_map, f, indent=2, ensure_ascii=False)

                # Immediately re-scan and re-render without ghost entries!
                self.run_scan()
                self.lbl_status.setText(f"Deleted '{os.path.basename(filepath)}' from '{pl_title}'.")
            except Exception as e:
                QMessageBox.critical(self, "Deletion Error", f"Could not delete file:\n{e}")

    def _open_in_explorer(self, filepath: str):
        if filepath and os.path.exists(filepath):
            folder = os.path.dirname(filepath)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _create_pair_file_cell(self, track_info: dict, pl_title: str, display_name: str) -> QWidget:
        """Create an interactive cell for Playlist A or B with open folder and safe delete buttons."""
        widget = QWidget()
        widget.setStyleSheet("background-color: #0f172a; border-radius: 4px;")
        cell_layout = QHBoxLayout(widget)
        cell_layout.setContentsMargins(6, 2, 6, 2)
        cell_layout.setSpacing(6)

        fname = track_info.get('filename', '')
        fp = track_info.get('filepath', '')

        lbl = QLabel(fname)
        lbl.setStyleSheet("color: #f1f5f9; font-size: 11px; background: transparent;")
        lbl.setToolTip(f"{fname}\nPath: {fp}")
        cell_layout.addWidget(lbl, 1)

        btn_folder = QPushButton("📁")
        btn_folder.setToolTip("Open folder in Explorer")
        btn_folder.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_folder.setFixedSize(26, 26)
        btn_folder.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                border: 1px solid #475569;
                border-radius: 4px;
                font-size: 12px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #334155;
                color: #ffffff;
            }
        """)
        btn_folder.clicked.connect(lambda _, p=fp: self._open_in_explorer(p))
        cell_layout.addWidget(btn_folder)

        btn_del = QPushButton("🗑️")
        btn_del.setToolTip(f"Delete file from {pl_title}")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.setFixedSize(26, 26)
        btn_del.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #ef4444;
                border: 1px solid #7f1d1d;
                border-radius: 4px;
                font-size: 12px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: #ef4444;
                color: #ffffff;
            }
        """)
        btn_del.clicked.connect(lambda _, p=fp, pl=pl_title, d=display_name: self._confirm_and_delete_track(p, pl, d))
        cell_layout.addWidget(btn_del)

        return widget

    def _populate_table(self):
        # Thoroughly clear all previous items and child widgets to prevent any overlapping ghost text!
        self.table.clearContents()
        mode = self.combo_mode.currentIndex()
        self.table.setRowCount(len(self.filtered_results))

        for row, item in enumerate(self.filtered_results):
            if mode == 0:
                tt = item.get('primary_track', {})
                display_name = tt.get('filename', 'Unknown')
                other_pls = item.get('other_playlists', [])
                pls_names = [o['playlist'] for o in other_pls]
                pls_str = ", ".join(pls_names)

                item_track = QTableWidgetItem(display_name)
                item_track.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item_track.setForeground(QColor("#f8fafc"))
                item_track.setFlags(item_track.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_track.setToolTip(f"{display_name}\n(Click row for full breakdown)")
                self.table.setItem(row, 0, item_track)

                self.table.setCellWidget(row, 1, None)
                item_pls = QTableWidgetItem(pls_str)
                item_pls.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item_pls.setForeground(QColor("#38bdf8"))
                item_pls.setFlags(item_pls.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_pls.setToolTip(f"{pls_str}\n(Click row for full breakdown)")
                self.table.setItem(row, 1, item_pls)

                track_url = self._get_track_url(item, display_name)
                btn_widget = QWidget()
                btn_widget.setStyleSheet("background: transparent;")
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                btn_link = QPushButton("Open Link ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setFixedSize(120, 28)
                btn_link.setStyleSheet("""
                    QPushButton {
                        background-color: #2563eb;
                        color: #ffffff;
                        border: none;
                        border-radius: 5px;
                        padding: 0px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover { background-color: #1d4ed8; }
                """)
                btn_link.clicked.connect(lambda _, u=track_url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 2, btn_widget)

            elif mode == 1:
                target_a = self.combo_target.currentText()
                target_b = self.combo_target_b.currentText()

                disp_name = item.get('display_name') or f"{item.get('artist', '')} - {item.get('title', '')}".strip(" -")
                item_track = QTableWidgetItem(disp_name)
                item_track.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item_track.setForeground(QColor("#f8fafc"))
                item_track.setFlags(item_track.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_track.setToolTip(disp_name)
                self.table.setItem(row, 0, item_track)

                # Column 1: In Playlist A
                if 'track_a' in item and item['track_a']:
                    empty_a = QTableWidgetItem("")
                    empty_a.setFlags(Qt.ItemFlag.NoItemFlags)
                    self.table.setItem(row, 1, empty_a)
                    w_a = self._create_pair_file_cell(item['track_a'], target_a, disp_name)
                    self.table.setCellWidget(row, 1, w_a)
                else:
                    self.table.setCellWidget(row, 1, None)
                    item_missing_a = QTableWidgetItem(f"— Not in {target_a} —")
                    item_missing_a.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
                    item_missing_a.setForeground(QColor("#64748b"))
                    item_missing_a.setFlags(item_missing_a.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 1, item_missing_a)

                # Column 2: In Playlist B
                if 'track_b' in item and item['track_b']:
                    empty_b = QTableWidgetItem("")
                    empty_b.setFlags(Qt.ItemFlag.NoItemFlags)
                    self.table.setItem(row, 2, empty_b)
                    w_b = self._create_pair_file_cell(item['track_b'], target_b, disp_name)
                    self.table.setCellWidget(row, 2, w_b)
                else:
                    self.table.setCellWidget(row, 2, None)
                    item_missing_b = QTableWidgetItem(f"— Not in {target_b} —")
                    item_missing_b.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignCenter)
                    item_missing_b.setForeground(QColor("#64748b"))
                    item_missing_b.setFlags(item_missing_b.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, 2, item_missing_b)

                # Column 3: Action
                track_url = self._get_track_url(item, disp_name)
                btn_widget = QWidget()
                btn_widget.setStyleSheet("background: transparent;")
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                btn_link = QPushButton("Open Link ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setFixedSize(110, 28)
                btn_link.setStyleSheet("""
                    QPushButton {
                        background-color: #2563eb;
                        color: #ffffff;
                        border: none;
                        border-radius: 5px;
                        padding: 0px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover { background-color: #1d4ed8; }
                """)
                btn_link.clicked.connect(lambda _, u=track_url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 3, btn_widget)

            else:
                title = item.get('title', 'Unknown')
                artist = item.get('artist', '')
                display_name = f"{artist} - {title}" if artist else title
                pls = item.get('unique_playlists', [])
                pls_str = ", ".join(pls)

                item_track = QTableWidgetItem(display_name)
                item_track.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item_track.setForeground(QColor("#f8fafc"))
                item_track.setFlags(item_track.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_track.setToolTip(f"{display_name}\n(Click row for full breakdown)")
                self.table.setItem(row, 0, item_track)

                self.table.setCellWidget(row, 1, None)
                item_pls = QTableWidgetItem(pls_str)
                item_pls.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item_pls.setForeground(QColor("#10b981"))
                item_pls.setFlags(item_pls.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_pls.setToolTip(f"{pls_str}\n(Click row for full breakdown)")
                self.table.setItem(row, 1, item_pls)

                track_url = self._get_track_url(item, display_name)
                btn_widget = QWidget()
                btn_widget.setStyleSheet("background: transparent;")
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                btn_link = QPushButton("Open Link ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setFixedSize(120, 28)
                btn_link.setStyleSheet("""
                    QPushButton {
                        background-color: #2563eb;
                        color: #ffffff;
                        border: none;
                        border-radius: 5px;
                        padding: 0px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover { background-color: #1d4ed8; }
                """)
                btn_link.clicked.connect(lambda _, u=track_url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 2, btn_widget)

        self.table.resizeRowsToContents()
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) < 48:
                self.table.setRowHeight(r, 48)

        count = len(self.filtered_results)
        if mode == 0:
            target = self.combo_target.currentText()
            self.lbl_status.setText(f"Found <b>{count}</b> track(s) in '<b>{target}</b>' that already exist in your other playlists.")
        elif mode == 1:
            target_a = self.combo_target.currentText()
            target_b = self.combo_target_b.currentText()
            subtab = self.current_pair_subtab
            subtab_desc = {
                'common': 'shared between both playlists',
                'only_a': f'present only in {target_a}',
                'only_b': f'present only in {target_b}',
                'all': f'across both {target_a} and {target_b}'
            }.get(subtab, '')
            self.lbl_status.setText(f"Showing <b>{count}</b> track(s) {subtab_desc}.")
        else:
            self.lbl_status.setText(f"Found <b>{count}</b> cross-playlist track cluster(s) across your entire music collection.")

    def _on_table_cell_clicked(self, row: int, column: int):
        """Open detailed breakdown popup when user clicks a row (Mode 0 & 2)."""
        mode = self.combo_mode.currentIndex()
        if mode == 1 or column == self.table.columnCount() - 1:
            return  # In Mode 1, actions and paths are in the table cells directly

        if 0 <= row < len(self.filtered_results):
            item = self.filtered_results[row]
            if mode == 0:
                tt = item.get('primary_track', {})
                display_name = tt.get('filename', 'Unknown')
                target_pl = self.combo_target.currentText()
                pl_list = [{'playlist': target_pl, 'filename': display_name, 'filepath': tt.get('filepath', '')}]
                for o in item.get('other_playlists', []):
                    tr = o.get('track', {})
                    pl_list.append({
                        'playlist': o.get('playlist', ''),
                        'filename': tr.get('filename', display_name),
                        'filepath': tr.get('filepath', '')
                    })
            else:
                title = item.get('title', 'Unknown')
                artist = item.get('artist', '')
                display_name = f"{artist} - {title}" if artist else title
                pl_list = []
                for t in item.get('tracks', []):
                    pl_list.append({
                        'playlist': t.get('playlist', ''),
                        'filename': t.get('filename', display_name),
                        'filepath': t.get('filepath', '')
                    })

            track_url = self._get_track_url(item, display_name)
            dlg = TrackOverlapDetailsDialog(display_name, pl_list, track_url, parent=self)
            dlg.exec()

    def _copy_results(self):
        mode = self.combo_mode.currentIndex()
        lines = []
        for i, item in enumerate(self.filtered_results, 1):
            if mode == 0:
                tt = item.get('primary_track', {})
                fname = tt.get('filename', 'Unknown')
                other_pls = [o.get('playlist', '') for o in item.get('other_playlists', [])]
                url = self._get_track_url(item, fname)
                lines.append(f"{i}. {fname}\n   Also in: {', '.join(other_pls)}\n   Link: {url}")
            elif mode == 1:
                disp = item.get('display_name') or f"{item.get('artist', '')} - {item.get('title', '')}".strip(" -")
                target_a = self.combo_target.currentText()
                target_b = self.combo_target_b.currentText()
                in_a = "Yes" if 'track_a' in item and item['track_a'] else "No"
                in_b = "Yes" if 'track_b' in item and item['track_b'] else "No"
                url = self._get_track_url(item, disp)
                lines.append(f"{i}. {disp}\n   In '{target_a}': {in_a} | In '{target_b}': {in_b}\n   Link: {url}")
            else:
                title = item.get('title', 'Unknown')
                artist = item.get('artist', '')
                display_name = f"{artist} - {title}" if artist else title
                pls = item.get('unique_playlists', [])
                url = self._get_track_url(item, display_name)
                lines.append(f"{i}. {display_name}\n   Shared across {len(pls)} playlists: {', '.join(pls)}\n   Link: {url}")

        QApplication.clipboard().setText("\n\n".join(lines))
        QMessageBox.information(self, "Copied", "Comparison results copied to clipboard!")
