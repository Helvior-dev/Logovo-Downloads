import os
import re
import urllib.parse
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox,
    QLineEdit, QMessageBox, QApplication, QFrame, QWidget,
    QScrollArea
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices

from core.playlist_comparator import PlaylistComparator
from core.playlists_manager import PlaylistsManager


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
                    padding: 7px 16px;
                    font-weight: bold;
                    font-size: 12px;
                    border: none;
                }
                QPushButton:hover { background-color: #1d4ed8; }
            """)
            btn_browser.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(track_url)))
            btn_layout.addWidget(btn_browser)

        btn_copy = QPushButton("📋 Copy Info")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #334155; }
        """)
        copy_text = f"Track: {display_name}\nPlaylists:\n" + "\n".join([f"- {p.get('playlist', '')}: {p.get('filepath', '')}" for p in playlists_data])
        if track_url:
            copy_text += f"\nLink: {track_url}"
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(copy_text))
        btn_layout.addWidget(btn_copy)

        btn_layout.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(90)
        btn_close.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: white;
                border-radius: 6px;
                padding: 7px 16px;
                font-weight: bold;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover { background-color: #475569; }
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
        self.setMinimumSize(1020, 600)
        self.resize(1080, 640)

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
                border: none;
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
        self.table.setHorizontalHeaderLabels(["Track / File", "Also Exists In Playlists", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 360)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(50)
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
            self.table.setHorizontalHeaderLabels([f"Track in '{target}'", "Also Found In Playlists", "Action"])
            self.raw_results = self.comparator.compare_single_playlist(target)
        else:
            self.table.setHorizontalHeaderLabels(["Track / Title", "Shared In Playlists (Clustered)", "Action"])
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

    def _get_track_url(self, item: dict, display_name: str) -> str:
        """Get best YouTube URL for a track (direct video ID or YouTube Music search)."""
        vid = None
        if 'primary_track' in item:
            vid = item['primary_track'].get('vid')
            if not vid:
                for o in item.get('other_playlists', []):
                    if o.get('track', {}).get('vid'):
                        vid = o['track']['vid']
                        break
        elif 'tracks' in item:
            for t in item.get('tracks', []):
                if t.get('vid'):
                    vid = t['vid']
                    break

        if vid:
            return f"https://www.youtube.com/watch?v={vid}"

        clean_q = re.sub(r'\.(mp3|flac|m4a|opus|ogg|wav)$', '', display_name, flags=re.IGNORECASE).strip()
        return f"https://music.youtube.com/search?q={urllib.parse.quote(clean_q)}"

    def _populate_table(self):
        is_single = (self.combo_mode.currentIndex() == 0)
        self.table.setRowCount(len(self.filtered_results))

        for row, item in enumerate(self.filtered_results):
            if is_single:
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

                item_pls = QTableWidgetItem(pls_str)
                item_pls.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item_pls.setForeground(QColor("#38bdf8"))
                item_pls.setFlags(item_pls.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_pls.setToolTip(f"{pls_str}\n(Click row for full breakdown)")
                self.table.setItem(row, 1, item_pls)

                # Action button (Open Link)
                track_url = self._get_track_url(item, display_name)
                btn_widget = QWidget()
                btn_widget.setStyleSheet("background: transparent;")
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                btn_link = QPushButton("Open Link ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setFixedSize(130, 28)
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
                    QPushButton:hover {
                        background-color: #1d4ed8;
                    }
                    QPushButton:pressed {
                        background-color: #1e40af;
                    }
                """)
                btn_link.clicked.connect(lambda _, u=track_url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 2, btn_widget)

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

                item_pls = QTableWidgetItem(pls_str)
                item_pls.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                item_pls.setForeground(QColor("#10b981"))
                item_pls.setFlags(item_pls.flags() & ~Qt.ItemFlag.ItemIsEditable)
                item_pls.setToolTip(f"{pls_str}\n(Click row for full breakdown)")
                self.table.setItem(row, 1, item_pls)

                # Action button (Open Link)
                track_url = self._get_track_url(item, display_name)
                btn_widget = QWidget()
                btn_widget.setStyleSheet("background: transparent;")
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                btn_link = QPushButton("Open Link ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setFixedSize(130, 28)
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
                    QPushButton:hover {
                        background-color: #1d4ed8;
                    }
                    QPushButton:pressed {
                        background-color: #1e40af;
                    }
                """)
                btn_link.clicked.connect(lambda _, u=track_url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 2, btn_widget)

        self.table.resizeRowsToContents()
        for r in range(self.table.rowCount()):
            if self.table.rowHeight(r) < 50:
                self.table.setRowHeight(r, 50)

        count = len(self.filtered_results)
        if is_single:
            target = self.combo_target.currentText()
            self.lbl_status.setText(f"Found <b>{count}</b> track(s) in '<b>{target}</b>' that already exist in your other playlists.")
        else:
            self.lbl_status.setText(f"Found <b>{count}</b> cross-playlist track cluster(s) across your entire music collection.")

    def _on_table_cell_clicked(self, row: int, column: int):
        """Open detailed breakdown popup when user clicks a row."""
        if column == 2:
            return  # Handled by the button itself
        if 0 <= row < len(self.filtered_results):
            item = self.filtered_results[row]
            is_single = (self.combo_mode.currentIndex() == 0)

            if is_single:
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
        is_single = (self.combo_mode.currentIndex() == 0)
        lines = []
        for i, item in enumerate(self.filtered_results, 1):
            if is_single:
                tt = item.get('primary_track', {})
                fname = tt.get('filename', 'Unknown')
                other_pls = [o.get('playlist', '') for o in item.get('other_playlists', [])]
                url = self._get_track_url(item, fname)
                lines.append(f"{i}. {fname}\n   Also in: {', '.join(other_pls)}\n   Link: {url}")
            else:
                title = item.get('title', 'Unknown')
                artist = item.get('artist', '')
                display_name = f"{artist} - {title}" if artist else title
                pls = item.get('unique_playlists', [])
                url = self._get_track_url(item, display_name)
                lines.append(f"{i}. {display_name}\n   Shared across {len(pls)} playlists: {', '.join(pls)}\n   Link: {url}")

        QApplication.clipboard().setText("\n\n".join(lines))
        QMessageBox.information(self, "Copied", "Comparison results with links copied to clipboard!")
