import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QColor, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QGridLayout,
)

from core.downloader import (
    add_kept_orphans,
    read_archive_ids,
    read_kept_orphans,
    read_stem_all_vids_map,
    read_stem_vid_map,
)
from ui.styles import get_theme_colors


class PlaylistSyncPreviewDialog(QDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        playlist = plan.playlist
        self.setWindowTitle("Review Playlist Sync")
        self.setStyleSheet("QDialog { background-color: #080b09; }")
        self.setMinimumSize(700, 420)
        self.resize(820, 620 if plan.orphaned_files else 520 if plan.missing_entries else 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(14)

        title = QLabel(f"Sync preview: {playlist.get('title', 'Playlist')}")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet("font-size: 17px; font-weight: bold; color: #d2ddd3;")
        title.setWordWrap(True)
        layout.addWidget(title)

        count = plan.preview.get("count", len(plan.preview.get("entries", [])))
        metrics = [
            ("Playlist tracks", count),
            ("To download", len(plan.missing_entries)),
            ("Local files after cleanup", plan.local_count),
            ("Unavailable", len(plan.unavailable_entries)),
            ("Online duplicates", len(plan.online_duplicates)),
            ("Removed from playlist", len(plan.orphaned_files)),
        ]
        if plan.autoheal_pairs:
            metrics.append(("Matched existing files", len(plan.autoheal_pairs)))

        summary_frame = QFrame()
        summary_frame.setStyleSheet("QFrame { background-color: #0b120d; border: 1px solid #28392b; }")
        summary_grid = QGridLayout(summary_frame)
        summary_grid.setContentsMargins(14, 12, 14, 12)
        summary_grid.setHorizontalSpacing(20)
        summary_grid.setVerticalSpacing(8)
        for index, (caption, value) in enumerate(metrics):
            label = QLabel(caption)
            label.setStyleSheet("border: none; color: #aab7aa; font-size: 13px;")
            value_label = QLabel(str(value))
            value_label.setStyleSheet("border: none; color: #d2ddd3; font-size: 15px; font-weight: bold;")
            summary_grid.addWidget(label, index // 2, (index % 2) * 2)
            summary_grid.addWidget(value_label, index // 2, (index % 2) * 2 + 1)
        summary_grid.setColumnStretch(0, 1)
        summary_grid.setColumnStretch(2, 1)
        layout.addWidget(summary_frame)

        cleanup_deletes = sum(action["action"] == "delete" for action in plan.cleanup_actions)
        cleanup_conversions = sum(action["action"] == "convert_to_audio" for action in plan.cleanup_actions)
        notices = []
        if cleanup_deletes or cleanup_conversions:
            cleanup_summary = []
            if cleanup_deletes:
                cleanup_summary.append(f"remove {cleanup_deletes} temporary or invalid file(s)")
            if cleanup_conversions:
                cleanup_summary.append(f"attempt to convert {cleanup_conversions} leftover video container(s)")
            notices.append("Cleanup will " + " and ".join(cleanup_summary) + ".")
            if cleanup_conversions:
                notices.append(
                    "The download queue will be recalculated after conversion; failed conversions may add tracks to it."
                )

        if plan.redownload_from_scratch:
            notices.append(
                f"Re-download from scratch: {len(plan.redownload_files)} existing media/subtitle file(s) will be removed."
            )
        if plan.playlist_format_update:
            notices.append("The playlist's filename format setting will be updated after confirmation.")
        if notices:
            notice = QLabel("\n".join(notices))
            notice.setTextFormat(Qt.TextFormat.PlainText)
            notice.setStyleSheet("color: #e3aaa3; font-size: 13px; padding: 8px; background-color: #0b120d;")
            notice.setWordWrap(True)
            layout.addWidget(notice)

        if plan.missing_entries:
            downloads_label = QLabel(f"TO DOWNLOAD  ·  {len(plan.missing_entries)} tracks")
            downloads_label.setStyleSheet("color: #d2ddd3; font-size: 13px; font-weight: bold;")
            layout.addWidget(downloads_label)

            visible_entries = plan.missing_entries[:100]
            track_lines = []
            for index, entry in enumerate(visible_entries, start=1):
                title_text = entry.get("title") or "Unknown title"
                author = entry.get("uploader") or entry.get("channel") or entry.get("artist") or ""
                track_lines.append(f"{index}. {author} — {title_text}" if author else f"{index}. {title_text}")
            if len(plan.missing_entries) > len(visible_entries):
                track_lines.append(f"… and {len(plan.missing_entries) - len(visible_entries)} more track(s)")

            tracks = QTextEdit()
            tracks.setReadOnly(True)
            tracks.setPlainText("\n".join(track_lines))
            tracks.setMinimumHeight(140)
            tracks.setMaximumHeight(240 if plan.orphaned_files else 360)
            tracks.setStyleSheet(
                "QTextEdit { background-color: #0b120d; color: #d2ddd3; "
                "border: 1px solid #354a38; border-radius: 0px; font-size: 13px; padding: 10px; }"
            )
            layout.addWidget(tracks, 1 if not plan.orphaned_files else 0)

        if plan.redownload_files:
            files_label = QLabel("Existing media/subtitle files to remove for re-download:")
            files_label.setStyleSheet("color: #e3aaa3; font-size: 12px;")
            layout.addWidget(files_label)

            visible_files = plan.redownload_files[:100]
            file_lines = visible_files.copy()
            if len(plan.redownload_files) > len(visible_files):
                file_lines.append(f"… and {len(plan.redownload_files) - len(visible_files)} more file(s)")
            files = QTextEdit()
            files.setReadOnly(True)
            files.setPlainText("\n".join(file_lines))
            files.setMaximumHeight(110)
            files.setStyleSheet(
                "QTextEdit { background-color: #080b09; color: #e3aaa3; "
                "border: 1px solid #70413d; border-radius: 0px; padding: 6px; }"
            )
            layout.addWidget(files)

        if plan.cleanup_actions:
            cleanup_label = QLabel("Other cleanup operations after confirmation:")
            cleanup_label.setStyleSheet("color: #aab7aa; font-size: 12px;")
            layout.addWidget(cleanup_label)

            visible_actions = plan.cleanup_actions[:100]
            action_lines = [
                f"{'Convert to audio' if action['action'] == 'convert_to_audio' else 'Remove'} — {action['path'].name}"
                for action in visible_actions
            ]
            if len(plan.cleanup_actions) > len(visible_actions):
                action_lines.append(f"… and {len(plan.cleanup_actions) - len(visible_actions)} more operation(s)")
            cleanup_details = QTextEdit()
            cleanup_details.setReadOnly(True)
            cleanup_details.setPlainText("\n".join(action_lines))
            cleanup_details.setMaximumHeight(110)
            cleanup_details.setStyleSheet(
                "QTextEdit { background-color: #080b09; color: #cbd5cc; "
                "border: 1px solid #0b120d; border-radius: 0px; padding: 6px; }"
            )
            layout.addWidget(cleanup_details)

        if plan.orphaned_files:
            orphan_label = QLabel(
                "These local files are no longer in the online playlist. Checked files will be permanently "
                "deleted after confirmation; uncheck any files you want to keep."
            )
            orphan_label.setStyleSheet("color: #aab7aa; font-size: 12px;")
            orphan_label.setWordWrap(True)
            layout.addWidget(orphan_label)

            selection_row = QHBoxLayout()
            self.orphan_selection_label = QLabel()
            self.orphan_selection_label.setStyleSheet("color: #e3aaa3; font-size: 12px;")
            self.orphan_toggle_button = QPushButton()
            self.orphan_toggle_button.setMinimumHeight(30)
            self.orphan_toggle_button.clicked.connect(self._toggle_orphan_selection)
            selection_row.addWidget(self.orphan_selection_label)
            selection_row.addStretch()
            selection_row.addWidget(self.orphan_toggle_button)
            layout.addLayout(selection_row)

            self.orphan_table = QTableWidget(len(plan.orphaned_files), 2)
            self.orphan_table.setHorizontalHeaderLabels(["Local file (select to delete)", "Video ID"])
            self.orphan_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            self.orphan_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            self.orphan_table.verticalHeader().setVisible(False)
            self.orphan_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.orphan_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.orphan_table.setStyleSheet("""
                QTableWidget {
                    background-color: #080b09;
                    border: 1px solid #0b120d;
                    border-radius: 0px;
                    color: #cbd5cc;
                    gridline-color: transparent;
                }
                QTableWidget::item { padding: 6px 8px; border-bottom: 1px solid #0b120d; }
                QHeaderView::section {
                    background-color: #0b120d;
                    color: #aab7aa;
                    font-weight: bold;
                    padding: 7px;
                    border: none;
                }
            """)
            for row, orphan in enumerate(plan.orphaned_files):
                filename_item = QTableWidgetItem(orphan.get("filename", ""))
                filename_item.setFlags(
                    (filename_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    & ~Qt.ItemFlag.ItemIsEditable
                )
                filename_item.setCheckState(Qt.CheckState.Checked)
                self.orphan_table.setItem(row, 0, filename_item)

                video_id = QTableWidgetItem(orphan.get("vid") or "Unknown")
                video_id.setFlags(video_id.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.orphan_table.setItem(row, 1, video_id)
            layout.addWidget(self.orphan_table, 1)
            self.orphan_table.itemChanged.connect(lambda _: self._update_orphan_selection_ui())
            self._update_orphan_selection_ui()
        elif not plan.missing_entries:
            self.orphan_table = None
            layout.addStretch(1)
        else:
            self.orphan_table = None

        button_row = QHBoxLayout()
        button_row.addStretch()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setMinimumSize(90, 34)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button = QPushButton("Apply Sync")
        self.apply_button.setMinimumSize(120, 34)
        self.apply_button.setStyleSheet("""
            QPushButton { background-color: #14271a; color: #a6efb4; font-weight: bold; padding: 8px 16px; }
            QPushButton:hover { background-color: #1a3422; }
        """)
        self.apply_button.clicked.connect(self.accept)
        button_row.addWidget(self.cancel_button)
        button_row.addWidget(self.apply_button)
        layout.addLayout(button_row)

    def _update_orphan_selection_ui(self):
        selected_count = len(self.selected_files_to_delete())
        total = self.orphan_table.rowCount()
        self.orphan_selection_label.setText(f"{selected_count} of {total} selected for deletion")
        self.orphan_toggle_button.setText("Deselect All" if selected_count == total else "Select All")

    def _toggle_orphan_selection(self):
        select_all = len(self.selected_files_to_delete()) < self.orphan_table.rowCount()
        previous = self.orphan_table.blockSignals(True)
        try:
            for row in range(self.orphan_table.rowCount()):
                self.orphan_table.item(row, 0).setCheckState(
                    Qt.CheckState.Checked if select_all else Qt.CheckState.Unchecked
                )
        finally:
            self.orphan_table.blockSignals(previous)
        self._update_orphan_selection_ui()

    def selected_files_to_delete(self) -> list[str]:
        if self.orphan_table is None:
            return []
        selected = []
        for row in range(self.orphan_table.rowCount()):
            item = self.orphan_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
        return selected


class OrphanFilesDialog(QDialog):
    def __init__(self, orphan_items: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Removed Tracks Detected")
        self.setStyleSheet("QDialog { background-color: #080b09; }")
        self.setMinimumSize(700, 440)
        self.resize(700, 440)
        self.deleted_files = []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(f"<h3>Found {len(orphan_items)} track(s) removed from online playlist</h3>")
        header.setStyleSheet("color: #cbd5cc;")
        desc = QLabel(
            "The following files were downloaded previously, but are no longer present in the online YouTube playlist.\n"
            "Review the list below and choose whether to delete them locally or keep them on your disk:"
        )
        desc.setStyleSheet("color: #aab7aa; font-size: 12px;")
        desc.setWordWrap(True)

        layout.addWidget(header)
        layout.addWidget(desc)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Track / Filename", "Video ID", "YouTube Link"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 140)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #080b09;
                border: 1px solid #0b120d;
                border-radius: 0px;
                color: #cbd5cc;
                gridline-color: transparent;
                outline: none;
            }
            QTableWidget::item {
                padding: 0px 8px;
                border-bottom: 1px solid #0b120d;
            }
            QHeaderView::section {
                background-color: #0b120d;
                color: #aab7aa;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #354a38;
            }
        """)
        self.table.setRowCount(len(orphan_items))

        for row, item in enumerate(orphan_items):
            fn = item.get('filename', '')
            vid = item.get('vid', 'Unknown')
            url = item.get('url', '')

            item_fn = QTableWidgetItem(fn)
            item_fn.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            item_fn.setFlags(item_fn.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item_fn.setFlags(item_fn.flags() & ~Qt.ItemFlag.ItemIsEditable)
            item_fn.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, item_fn)

            item_vid = QTableWidgetItem(vid)
            item_vid.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            item_vid.setForeground(QColor("#91e5a3"))
            item_vid.setFlags(item_vid.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, item_vid)

            if url:
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
                        background-color: #14271a;
                        color: #a6efb4;
                        border: none;
                        border-radius: 0px;
                        padding: 0px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #1a3422;
                    }
                    QPushButton:pressed {
                        background-color: #315f39;
                    }
                """)
                btn_link.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 2, btn_widget)
            else:
                self.table.setItem(row, 2, QTableWidgetItem("-"))

        layout.addWidget(self.table)

        sel_box = QHBoxLayout()
        btn_sel_all = QPushButton("Select All")
        btn_desel_all = QPushButton("Deselect All")
        btn_sel_all.clicked.connect(self._select_all)
        btn_desel_all.clicked.connect(self._deselect_all)
        sel_box.addWidget(btn_sel_all)
        sel_box.addWidget(btn_desel_all)
        sel_box.addStretch()
        layout.addLayout(sel_box)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_keep = QPushButton("Keep All (Do Not Delete)")
        self.btn_keep.clicked.connect(self.reject)

        self.btn_delete = QPushButton("Delete Selected")
        self.btn_delete.setStyleSheet("""
            QPushButton {
                background-color: #1b100f;
                color: #e39a91;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 0px;
            }
            QPushButton:hover {
                background-color: #522723;
            }
        """)
        self.btn_delete.clicked.connect(self._on_delete_selected)

        btn_row.addWidget(self.btn_keep)
        btn_row.addWidget(self.btn_delete)
        layout.addLayout(btn_row)

    def _select_all(self):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item: item.setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self):
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item: item.setCheckState(Qt.CheckState.Unchecked)

    def _on_delete_selected(self):
        self.deleted_files = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                self.deleted_files.append(item.text())
        self.accept()


def detect_and_prompt_orphans(parent, out_dir: str, preview: dict) -> list[str]:
    """Detect truly orphaned files with known video IDs no longer in online playlist and prompt user with interactive details dialog."""
    local_files = [f for f in os.listdir(out_dir) if os.path.isfile(os.path.join(out_dir, f)) and not f.startswith('.')]
    archived_ids = read_archive_ids(out_dir)
    stem_all_vids = read_stem_all_vids_map(out_dir)
    stem_map = read_stem_vid_map(out_dir)
    kept_items = read_kept_orphans(out_dir)

    playlist_ids = set()
    for e in preview.get('entries', []):
        vid = e.get('id')
        if not vid:
            url = e.get('url', '')
            if 'v=' in url: vid = url.split('v=')[-1].split('&')[0]
            elif 'youtu.be/' in url: vid = url.split('youtu.be/')[-1].split('?')[0]
        if vid:
            playlist_ids.add(vid)

    orphan_ids = archived_ids - playlist_ids
    if not orphan_ids or not local_files:
        return []

    valid_exts = ('.mp3', '.mp4', '.webm', '.m4a', '.wav', '.flac', '.opus', '.ogg', '.mkv', '.avi')
    orphan_items = []

    for f in local_files:
        f_lower = f.lower()
        if not f_lower.endswith(valid_exts):
            continue
        stem = os.path.splitext(f)[0]
        if f in kept_items or stem in kept_items:
            continue

        mapped_vids = stem_all_vids.get(stem, set())
        if mapped_vids and any(v in playlist_ids for v in mapped_vids):
            continue

        mapped_vid = stem_map.get(stem)

        # STRICT CHECK: Only flag if mapped_vid is explicitly in orphan_ids and NOT in online playlist_ids
        if mapped_vid and (mapped_vid in orphan_ids) and (mapped_vid not in playlist_ids):
            url = f"https://www.youtube.com/watch?v={mapped_vid}"
            orphan_items.append({
                'filename': f,
                'vid': mapped_vid,
                'url': url,
                'title': stem
            })

    if not orphan_items:
        return []

    dlg = OrphanFilesDialog(orphan_items, parent=parent)
    res = dlg.exec()
    if res == QDialog.DialogCode.Accepted and dlg.deleted_files:
        deleted = []
        for fn in dlg.deleted_files:
            try:
                os.remove(os.path.join(out_dir, fn))
                deleted.append(fn)
                if hasattr(parent, 'history'):
                    stem = Path(fn).stem
                    parts = stem.split(" - ", 1)
                    t_author = parts[1] if len(parts) > 1 else ""
                    t_title = parts[0]
                    parent.history.add_entry(
                        t_title,
                        t_author,
                        platform="YouTube",
                        status="Deleted (Removed from playlist)",
                        url="",
                        media_type="Audio"
                    )
            except Exception:
                pass
        kept_fns = [it.get('filename') for it in orphan_items if it.get('filename') not in dlg.deleted_files]
        if kept_fns:
            add_kept_orphans(out_dir, kept_fns)
        return deleted
    else:
        add_kept_orphans(out_dir, [it.get('filename') for it in orphan_items if it.get('filename')])
        return []


class OnlineDuplicatesDialog(QDialog):
    def __init__(self, duplicate_items: list[dict], playlist_title: str = "Playlist", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Online Duplicates Detected")
        self.setStyleSheet("QDialog { background-color: #080b09; }")
        self.setMinimumSize(840, 460)
        self.resize(840, 460)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(f"<h3>Found {len(duplicate_items)} duplicate track(s) in '{playlist_title}'</h3>")
        header.setStyleSheet("color: #cbd5cc;")
        desc = QLabel(
            "The following tracks are added multiple times in your online YouTube playlist.\n"
            "You can open the duplicate links below to locate and remove them directly from YouTube Music:"
        )
        desc.setStyleSheet("color: #aab7aa; font-size: 12px;")
        desc.setWordWrap(True)

        layout.addWidget(header)
        layout.addWidget(desc)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Original Track in Playlist", "Duplicate Track Found", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 160)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #080b09;
                border: 1px solid #0b120d;
                border-radius: 0px;
                color: #cbd5cc;
                gridline-color: transparent;
                outline: none;
            }
            QTableWidget::item {
                padding: 0px 8px;
                border-bottom: 1px solid #0b120d;
            }
            QHeaderView::section {
                background-color: #0b120d;
                color: #aab7aa;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #354a38;
            }
        """)
        self.table.setRowCount(len(duplicate_items))

        for row, item in enumerate(duplicate_items):
            title = item.get('title', 'Unknown')
            author = item.get('author', '')
            dupe_idx = item.get('dupe_index', '')
            dupe_display = f"#{dupe_idx} • {author} - {title}" if author else f"#{dupe_idx} • {title}"

            orig_t = item.get('orig_title') or title
            orig_a = item.get('orig_author') or ''
            orig_idx = item.get('orig_index', '')
            orig_display = f"#{orig_idx} • {orig_a} - {orig_t}" if orig_a else f"#{orig_idx} • {orig_t}"
            dupe_url = item.get('dupe_url', '') or item.get('orig_url', '')

            item_orig = QTableWidgetItem(orig_display)
            item_orig.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            item_orig.setForeground(QColor("#65c77e"))
            item_orig.setFlags(item_orig.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_orig)

            item_dupe = QTableWidgetItem(dupe_display)
            item_dupe.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            item_dupe.setForeground(QColor("#91e5a3"))
            item_dupe.setFlags(item_dupe.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, item_dupe)

            if dupe_url:
                btn_widget = QWidget()
                btn_widget.setStyleSheet("background: transparent;")
                btn_layout = QHBoxLayout(btn_widget)
                btn_layout.setContentsMargins(0, 0, 0, 0)
                btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

                btn_link = QPushButton("Open Duplicate ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setFixedSize(135, 28)
                btn_link.setStyleSheet("""
                    QPushButton {
                        background-color: #14271a;
                        color: #a6efb4;
                        border: none;
                        border-radius: 0px;
                        padding: 0px;
                        font-size: 11px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #1a3422;
                    }
                    QPushButton:pressed {
                        background-color: #315f39;
                    }
                """)
                btn_link.clicked.connect(lambda _, u=dupe_url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 2, btn_widget)

        self.duplicate_items = duplicate_items
        layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        btn_copy = QPushButton("Copy Duplicates List")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setStyleSheet("background-color: #14271a; color: #a6efb4; border: 1px solid #65a875; border-radius: 0px; padding: 6px 14px; font-weight: bold; font-size: 12px;")
        btn_copy.clicked.connect(self._copy_list)
        btn_box.addWidget(btn_copy)
        btn_box.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(100)
        btn_close.setStyleSheet("background-color: #354a38; color: #cbd5cc; border-radius: 0px; padding: 6px 14px; font-weight: bold; font-size: 12px;")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def _copy_list(self):
        lines = []
        for i, item in enumerate(self.duplicate_items, 1):
            title = item.get('title', 'Unknown')
            author = item.get('author', '')
            dupe_idx = item.get('dupe_index', '')
            dupe_display = f"{author} - {title}" if author else title

            orig_t = item.get('orig_title') or title
            orig_a = item.get('orig_author') or ''
            orig_idx = item.get('orig_index', '')
            orig_display = f"{orig_a} - {orig_t}" if orig_a else orig_t
            dupe_url = item.get('dupe_url', '') or item.get('orig_url', '')

            lines.append(f"{i}. Duplicate #{dupe_idx}: {dupe_display}\n   Original  #{orig_idx}: {orig_display}\n   URL: {dupe_url}")
        QApplication.clipboard().setText("\n\n".join(lines))
        QMessageBox.information(self, "Copied", "Duplicates list copied to clipboard.")


class PlaylistUpToDateDialog(QDialog):
    def __init__(self, title: str, count: int, local_files_count: Optional[int] = None, duplicates: Optional[list] = None, unavailable: Optional[list] = None, parent=None):
        super().__init__(parent)
        self.duplicates = duplicates or []
        self.unavailable = unavailable or []
        self.playlist_title = title
        self.local_files_count = local_files_count
        self.setWindowTitle("Playlist Up to Date")
        colors = get_theme_colors(getattr(parent, "ui_theme", "green"))
        self.setStyleSheet(f"QDialog {{ background-color: {colors['root_bg']}; }}")
        self.setFixedWidth(480)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)

        card = QFrame(self)
        card.setObjectName("UpToDateCard")
        card.setStyleSheet(f"""
            QFrame#UpToDateCard {{
                background-color: {colors['card_bg']};
                border: 1px solid {colors['border_soft']};
                border-radius: 0px;
            }}
        """)

        layout = QVBoxLayout(card)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 18)

        status = QLabel("PLAYLIST UP TO DATE")
        status.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {colors['accent']}; background: transparent;")
        layout.addWidget(status)

        h_lbl = QLabel(title)
        h_lbl.setTextFormat(Qt.TextFormat.PlainText)
        h_lbl.setWordWrap(True)
        h_lbl.setStyleSheet(f"font-size: 17px; font-weight: bold; color: {colors['input_text']}; background: transparent;")
        layout.addWidget(h_lbl)

        available_count = max(0, count - len(self.unavailable) - len(self.duplicates))
        if self.local_files_count is not None and self.local_files_count < available_count:
            desc_text = f"{self.local_files_count} local files for {available_count} available tracks.\nNo new downloads needed."
        else:
            desc_text = f"All {available_count} available tracks are present locally.\nNo changes needed."

        desc_lbl = QLabel(desc_text)
        desc_lbl.setTextFormat(Qt.TextFormat.PlainText)
        desc_lbl.setStyleSheet(f"font-size: 13px; color: {colors['text_secondary']}; background: transparent;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(desc_lbl)

        details_row = QHBoxLayout()
        if self.duplicates:
            btn_dupes = QPushButton(f"View Duplicates ({len(self.duplicates)})", card)
            btn_dupes.clicked.connect(self._show_duplicates)
            details_row.addWidget(btn_dupes)

        if self.unavailable:
            btn_unavail = QPushButton(f"View Unavailable Tracks ({len(self.unavailable)})", card)
            btn_unavail.clicked.connect(self._show_unavailable)
            details_row.addWidget(btn_unavail)
        if details_row.count():
            layout.addLayout(details_row)

        btn_ok = QPushButton("Close", card)
        btn_ok.setMinimumSize(110, 36)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors['primary_bg']};
                color: {colors['accent_text']};
                border-radius: 0px;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {colors['primary_hover']};
            }}
        """)
        btn_ok.clicked.connect(self.accept)

        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(btn_ok)
        layout.addLayout(footer)
        main_layout.addWidget(card)

    def _show_duplicates(self):
        OnlineDuplicatesDialog(self.duplicates, playlist_title=self.playlist_title, parent=self).exec()

    def _show_unavailable(self):
        UnavailableTracksDialog(self.unavailable, parent=self).exec()


class UnavailableTracksDialog(QDialog):
    def __init__(self, items: list[tuple[dict, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unavailable Tracks on YouTube")
        self.setMinimumSize(660, 520)
        self.setStyleSheet("""
            QDialog { background-color: #080b09; color: #cbd5cc; }
            QTextEdit { background-color: #080b09; border: 1px solid #0b120d; border-radius: 0px; color: #cbd5cc; font-family: monospace; font-size: 12px; padding: 10px; }
            QPushButton { background-color: #14271a; color: #a6efb4; border-radius: 0px; padding: 8px 18px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #23442c; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        h_lbl = QLabel(f"Unavailable tracks on YouTube: {len(items)}")
        h_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #d9b66d;")
        layout.addWidget(h_lbl)

        desc_lbl = QLabel(
            "These tracks cannot be downloaded because they were removed by copyright, set to private, or deleted from YouTube by the uploader.\n\n"
            "You can copy this list to find and remove them from your online playlist:"
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; color: #aab7aa; line-height: 1.4;")
        layout.addWidget(desc_lbl)

        self.text_area = QTextEdit()
        self.text_area.setReadOnly(True)
        lines = []
        for i, (item_data, reason) in enumerate(items, 1):
            t = item_data.get('title', 'Unknown Title')
            a = item_data.get('uploader') or item_data.get('artist') or item_data.get('channel') or 'Unknown Artist'
            u = item_data.get('url', '')
            clean_reason = reason.strip()
            if "copyright" in clean_reason.lower():
                clean_reason = "Removed by copyright"
            elif "not available" in clean_reason.lower() or "video unavailable" in clean_reason.lower():
                clean_reason = "Deleted / Video unavailable"
            lines.append(f"{i}. {a} - {t}\n   URL: {u}\n   Status: {clean_reason}\n")
        self.text_area.setPlainText("\n".join(lines))
        layout.addWidget(self.text_area, 1)

        # Step-by-step guide banner
        guide_box = QFrame()
        guide_box.setStyleSheet("""
            QFrame {
                background-color: #0b120d;
                border: 1px solid #354a38;
                border-radius: 0px;
            }
        """)
        guide_layout = QVBoxLayout(guide_box)
        guide_layout.setContentsMargins(12, 10, 12, 10)
        guide_layout.setSpacing(6)

        guide_title = QLabel("<b>Remove unavailable videos from a YouTube playlist:</b>")
        guide_title.setStyleSheet("color: #91e5a3; font-size: 12px; font-weight: bold; background: transparent; border: none;")

        guide_body = QLabel(
            "1. Open your playlist on YouTube or YouTube Music.<br>"
            "2. Click the <b>three dots menu (⋮)</b> under the playlist title/cover and select <b>'Show unavailable videos'</b>.<br>"
            "3. The hidden/deleted items will appear grayed out in your playlist.<br>"
            "4. Click the <b>three dots (⋮)</b> next to each unavailable video and choose <b>'Remove from playlist'</b>."
        )
        guide_body.setWordWrap(True)
        guide_body.setStyleSheet("color: #cbd5cc; font-size: 11px; line-height: 1.45; background: transparent; border: none;")

        guide_layout.addWidget(guide_title)
        guide_layout.addWidget(guide_body)
        layout.addWidget(guide_box)

        btn_box = QHBoxLayout()
        btn_copy = QPushButton("Copy List to Clipboard")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(self.copy_list)

        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("background-color: #354a38; color: #cbd5cc;")
        btn_close.clicked.connect(self.accept)

        btn_box.addWidget(btn_copy)
        btn_box.addStretch()
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def copy_list(self):
        QApplication.clipboard().setText(self.text_area.toPlainText())
        QMessageBox.information(self, "Copied", "Unavailable tracks list copied to clipboard.")


class SafeModeDialog(QDialog):
    def __init__(self, count: int, concurrency: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Queue Concurrency")
        self.setFixedWidth(480)
        self.setStyleSheet("""
            QDialog { background-color: #080b09; color: #cbd5cc; }
            QPushButton { border-radius: 0px; padding: 9px 16px; font-weight: bold; font-size: 12px; }
            QCheckBox { color: #aab7aa; font-size: 11px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title_lbl = QLabel(f"Large Download Queue ({count} tracks)")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #91e5a3;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            f"Queued tracks: <b>{count}</b>. Concurrent downloads: <b>{concurrency}</b>.<br><br>"
            "Large queues with high concurrency may trigger temporary <b>YouTube rate limits</b>.<br><br>"
            "<b>Reduced concurrency</b> uses 3 concurrent downloads with a delay between starts. This may reduce rate limiting but does not prevent it."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; color: #cbd5cc; line-height: 1.45;")
        layout.addWidget(desc_lbl)

        self.chk_remember = QCheckBox("Remember choice for this session")
        layout.addWidget(self.chk_remember)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_full = QPushButton(f"Keep {concurrency} Downloads")
        self.btn_full.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_full.setStyleSheet("""
            QPushButton {
                background-color: #354a38;
                color: #cbd5cc;
                border: 1px solid #354a38;
            }
            QPushButton:hover { background-color: #354a38; }
        """)
        self.btn_full.clicked.connect(self._choose_full)

        self.btn_safe = QPushButton("Reduce to 3 Downloads")
        self.btn_safe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_safe.setStyleSheet("""
            QPushButton {
                background-color: #14271a;
                color: #a6efb4;
                border: none;
            }
            QPushButton:hover { background-color: #1a3422; }
        """)
        self.btn_safe.clicked.connect(self._choose_safe)

        btn_layout.addWidget(self.btn_full)
        btn_layout.addWidget(self.btn_safe)
        layout.addLayout(btn_layout)

        self.enable_safe_mode = True

    def _choose_safe(self):
        self.enable_safe_mode = True
        self.accept()

    def _choose_full(self):
        self.enable_safe_mode = False
        self.accept()


class PlaylistFormatMismatchDialog(QDialog):
    def __init__(self, parent=None, pl_title: str = "Playlist", pl_format: str = "unix", settings_format: str = "windows"):
        super().__init__(parent)
        self.setWindowTitle("Format Compatibility Mismatch")
        self.setFixedWidth(560)
        self.setStyleSheet("""
            QDialog { background-color: #080b09; color: #cbd5cc; }
            QPushButton { border-radius: 0px; padding: 10px 16px; font-weight: bold; font-size: 12px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title_lbl = QLabel("File Format Compatibility Mismatch")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #d9b66d;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)

        pl_fmt_label = "UNIX" if pl_format == "unix" else ("Windows" if pl_format == "windows" else "Unix/Win")
        set_fmt_label = "Windows" if settings_format == "windows" else "UNIX"

        desc_lbl = QLabel(
            f"Your application settings currently use <b>{set_fmt_label}</b> format compatibility, "
            f"while the playlist <b>\"{pl_title}\"</b> was previously downloaded using <b>{pl_fmt_label}</b> format.<br><br>"
            "How would you like to proceed with this synchronization?"
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; color: #cbd5cc; line-height: 1.5;")
        layout.addWidget(desc_lbl)

        self.choice = None

        # Option 1: Keep playlist format
        opt1_box = QVBoxLayout()
        opt1_box.setSpacing(4)
        btn_keep = QPushButton(f"Keep Playlist Format ({pl_fmt_label})")
        btn_keep.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_keep.setStyleSheet("""
            QPushButton {
                background-color: #14271a;
                color: #a6efb4;
                border: none;
                text-align: left;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: bold;
                border-radius: 0px;
            }
            QPushButton:hover { background-color: #1a3422; }
        """)
        btn_keep.clicked.connect(self._choose_keep)
        opt1_box.addWidget(btn_keep)

        hint_keep = QLabel(f"• Downloads missing tracks using the original {pl_fmt_label} format. The badge remains {pl_fmt_label}.")
        hint_keep.setWordWrap(True)
        hint_keep.setStyleSheet("font-size: 11px; color: #aab7aa; padding-left: 14px;")
        opt1_box.addWidget(hint_keep)
        layout.addLayout(opt1_box)

        # Option 2: Switch to settings format (mixed)
        opt2_box = QVBoxLayout()
        opt2_box.setSpacing(4)
        btn_settings = QPushButton(f"Use {set_fmt_label} for New Tracks (Mixed Formats)")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_settings.setStyleSheet("""
            QPushButton {
                background-color: #2b2414;
                color: #d9b66d;
                border: none;
                text-align: left;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: bold;
                border-radius: 0px;
            }
            QPushButton:hover { background-color: #9b7c3d; }
        """)
        btn_settings.clicked.connect(self._choose_settings)
        opt2_box.addWidget(btn_settings)

        hint_settings = QLabel(f"• Only new tracks will be saved in {set_fmt_label} format. Existing files are kept as-is, and the badge becomes Unix/Win.")
        hint_settings.setWordWrap(True)
        hint_settings.setStyleSheet("font-size: 11px; color: #aab7aa; padding-left: 14px;")
        opt2_box.addWidget(hint_settings)
        layout.addLayout(opt2_box)

        # Option 3: Re-download from scratch in settings format
        opt3_box = QVBoxLayout()
        opt3_box.setSpacing(4)
        btn_redownload = QPushButton(f"Re-download All Tracks in {set_fmt_label}")
        btn_redownload.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_redownload.setStyleSheet("""
            QPushButton {
                background-color: #2b2414;
                color: #d9b66d;
                border: none;
                text-align: left;
                padding: 10px 16px;
                font-size: 12px;
                font-weight: bold;
                border-radius: 0px;
            }
            QPushButton:hover { background-color: #433619; }
        """)
        btn_redownload.clicked.connect(self._choose_redownload)
        opt3_box.addWidget(btn_redownload)

        hint_redownload = QLabel(f"• Removes existing tracks in this playlist folder and re-downloads all tracks cleanly from scratch in {set_fmt_label} format. The badge updates to {set_fmt_label}.")
        hint_redownload.setWordWrap(True)
        hint_redownload.setStyleSheet("font-size: 11px; color: #aab7aa; padding-left: 14px;")
        opt3_box.addWidget(hint_redownload)
        layout.addLayout(opt3_box)

        # Cancel
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #354a38;
                color: #cbd5cc;
                border: 1px solid #354a38;
                font-size: 12px;
                font-weight: 500;
                border-radius: 0px;
                padding: 8px 16px;
            }
            QPushButton:hover { background-color: #354a38; color: #cbd5cc; }
        """)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(btn_cancel)

    def _choose_keep(self):
        self.choice = 'keep'
        self.accept()

    def _choose_settings(self):
        self.choice = 'settings'
        self.accept()

    def _choose_redownload(self):
        self.choice = 'redownload'
        self.accept()
