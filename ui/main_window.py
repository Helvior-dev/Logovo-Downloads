import sys
import time
import datetime
import requests
import re
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QProgressBar, 
    QComboBox, QMessageBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QFileDialog, QFormLayout,
    QApplication, QRadioButton, QButtonGroup, QGroupBox, QScrollArea, QDialog,
    QSystemTrayIcon, QMenu, QSpinBox, QSlider, QFrame, QGraphicsDropShadowEffect,
    QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QObject, QEvent
from PyQt6.QtGui import QPixmap, QDesktopServices, QAction, QIcon, QColor, QPainter, QPen

from core.preview import get_video_preview
from core.downloader import (
    MediaDownloader,
    friendly_error,
    is_platform_unavailable,
    set_folder_icon,
    save_playlist_cover_image,
    apply_playlist_cover_settings,
    clear_failed_log_if_clean,
    cleanup_orphan_files,
    is_file_already_downloaded,
    read_stem_vid_map,
    read_archive_ids,
    restore_dates_from_order,
    reindex_existing_playlist_files,
    update_stem_vid_map,
    write_playlist_order,
    parse_speed_limit,
    log_failed_download,
    clean_song_title,
    clean_artist_name,
    _author_and_title_match,
)
from core.utils import clean_filename_for_all_devices
from core.settings import SettingsManager, get_app_data_dir
from core.history import HistoryManager
from core.taskbar import taskbar_manager
from core.playlists_manager import PlaylistsManager
from core.updater import (
    get_installed_ytdlp_version,
    check_latest_ytdlp_version,
    CheckUpdateThread,
    UpgradeWorker,
)
from ui.styles import get_stylesheet, get_resource_path
from ui.queue_item import QueueItemWidget
from ui.log_viewer_dialog import LogViewerDialog


def estimate_track_size_mb(item_data: dict) -> float:
    media_type = str(item_data.get('media_type', 'Audio (Best)')).lower()
    duration = item_data.get('duration')
    if "flac" in media_type or "alac" in media_type:
        return 45.0
    elif "wav" in media_type:
        return 140.0
    elif "mp3" in media_type or "best audio" in media_type:
        return 8.0
    elif "m4a" in media_type or "aac" in media_type:
        return 6.0
    elif "opus" in media_type or "ogg" in media_type:
        return 4.0
    elif "video" in media_type or "h.264" in media_type or "h.265" in media_type:
        if duration:
            try:
                dur_s = float(duration)
                return max(15.0, (dur_s / 60.0) * 20.0)
            except Exception:
                pass
        return 85.0
    return 8.0


def format_time(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60:02d}m"
    if s >= 60:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s}s"


class WorkerThread(QThread):
    progress_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool, str, bool)

    def __init__(
        self,
        url,
        media_type,
        output_dir,
        quality,
        cookies,
        subtitles,
        playlist_index=None,
        playlist_count=None,
        title=None,
        author=None,
        speed_limit=None,
        naming_pattern=None,
        settings=None,
        thumbnail=None,
    ):
        super().__init__()
        self.url = url
        self.media_type = media_type
        self.output_dir = output_dir
        self.quality = quality
        self.cookies = cookies
        self.subtitles = subtitles
        self.playlist_index = playlist_index
        self.playlist_count = playlist_count
        self.title = title
        self.author = author
        self.speed_limit = speed_limit
        self.naming_pattern = naming_pattern
        self.settings = settings
        self.thumbnail = thumbnail

    def run(self):
        downloader = MediaDownloader(output_dir=self.output_dir, settings=self.settings)

        def progress_callback(*args, **kwargs):
            if args and isinstance(args[0], dict):
                d = args[0]
            else:
                pct = args[0] if len(args) > 0 else 100.0
                status_txt = args[1] if len(args) > 1 else ""
                speed = args[2] if len(args) > 2 else ""
                eta = args[3] if len(args) > 3 else ""
                d = {
                    "status": "downloading" if pct < 100 else "finished",
                    "_percent_str": f"{pct:.1f}%",
                    "_speed_str": speed,
                    "_eta_str": eta,
                    "status_text": status_txt,
                }
            self.progress_signal.emit(d)

        success, error_msg, was_skipped = downloader.download(
            self.url,
            media_type=self.media_type,
            quality=self.quality,
            cookies=self.cookies,
            subtitles=self.subtitles,
            progress_callback=progress_callback,
            playlist_index=self.playlist_index,
            playlist_count=self.playlist_count,
            title=self.title,
            author=self.author,
            speed_limit=self.speed_limit,
            naming_pattern=self.naming_pattern,
            thumbnail=self.thumbnail,
        )
        self.finished_signal.emit(success, error_msg, was_skipped)


class FetchPreviewWorker(QThread):
    finished_signal = pyqtSignal(dict, object)
    error_signal = pyqtSignal(str, object)

    def __init__(self, url, context=None, cookies=None):
        super().__init__()
        self.url = url
        self.context = context
        self.cookies = cookies

    def run(self):
        try:
            preview = get_video_preview(self.url, cookies=self.cookies)
            if preview:
                self.finished_signal.emit(preview, self.context)
            else:
                self.error_signal.emit("Could not fetch media metadata from YouTube.", self.context)
        except Exception as e:
            self.error_signal.emit(str(e), self.context)


class SyncPlaylistWorker(QThread):
    finished_signal = pyqtSignal(dict, dict, list, int, list)
    error_signal = pyqtSignal(str, dict)

    def __init__(self, p_dict: dict, settings, cookies=None):
        super().__init__()
        self.p_dict = p_dict
        self.settings = settings
        self.cookies = cookies

    def run(self):
        try:
            url = self.p_dict.get('url')
            out_dir = self.p_dict.get('folder_path')
            media_type_category = self.p_dict.get('media_type', 'Audio')

            preview = get_video_preview(url, cookies=self.cookies)
            if not preview or not preview.get('is_playlist'):
                self.error_signal.emit("Invalid playlist response from YouTube.", self.p_dict)
                return

            count = preview.get('count', 0)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)

            # Cleanup orphan files and leftover raw .mp4 before sync
            cleanup_orphan_files(out_dir, is_audio_playlist=(media_type_category == "Audio"))

            cover_mode = self.settings.get('playlist_cover_mode', 'both') if self.settings else 'both'
            pl_thumb = preview.get('thumbnail') or (preview.get('entries', [{}])[0].get('thumbnail') if preview.get('entries') else None)
            if pl_thumb and cover_mode != 'none':
                apply_playlist_cover_settings(out_dir, pl_thumb, mode=cover_mode)

            # Restore dates & reindex in background
            restore_dates_from_order(out_dir)
            reindex_existing_playlist_files(out_dir, preview.get('entries', []))

            # Build in-memory index of existing local files for instant O(1) comparison
            stem_map = read_stem_vid_map(out_dir)
            vid_set = set(stem_map.values())
            stem_title_index = {}
            valid_media_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac", ".mp4", ".mkv", ".webm"}
            local_cnt = 0
            all_local_stems = []

            if os.path.exists(out_dir):
                for f in Path(out_dir).iterdir():
                    if f.is_file() and f.suffix.lower() in valid_media_exts:
                        try:
                            if f.stat().st_size >= 500 * 1024:
                                local_cnt += 1
                                stem = f.stem
                                all_local_stems.append(stem)
                                parts = stem.split(' - ')
                                if len(parts) >= 2:
                                    a0 = clean_artist_name(parts[0])
                                    t1 = clean_song_title(' - '.join(parts[1:]), a0)
                                    t0 = clean_song_title(parts[0], clean_artist_name(' - '.join(parts[1:])))
                                    a1 = clean_artist_name(' - '.join(parts[1:]))
                                    stem_title_index.setdefault(t1, []).append((a0, stem))
                                    stem_title_index.setdefault(t0, []).append((a1, stem))
                                else:
                                    t = clean_song_title(stem)
                                    stem_title_index.setdefault(t, []).append(("", stem))
                        except Exception:
                            pass

            missing_entries = []
            for i, entry in enumerate(preview.get('entries', [])):
                entry['playlist_output_dir'] = out_dir
                entry['playlist_index'] = count - i
                entry['playlist_count'] = count
                entry['media_type_category'] = media_type_category
                entry['media_type'] = "Audio (Best)" if media_type_category == "Audio" else "Video (Best)"

                vid = entry.get('url', '').split('v=')[-1].split('&')[0]
                author = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ""
                title = entry.get('title') or ""

                already_downloaded = False
                if vid and vid in vid_set:
                    already_downloaded = True
                elif title:
                    ct = clean_song_title(title, author)
                    ca = clean_artist_name(author)
                    if ct in stem_title_index:
                        for stem_a, matched_stem in stem_title_index[ct]:
                            if not ca or not stem_a or ca in stem_a or stem_a in ca or ca in ('release', 'topic', 'variousartists', 'music', 'soundtrack', 'official', 'vevo') or ca in ct or (stem_a and stem_a in ct):
                                update_stem_vid_map(out_dir, matched_stem, vid)
                                already_downloaded = True
                                break
                    if not already_downloaded:
                        for f_stem in all_local_stems:
                            if _author_and_title_match(f_stem, title, author):
                                update_stem_vid_map(out_dir, f_stem, vid)
                                already_downloaded = True
                                break

                if not already_downloaded:
                    missing_entries.append(entry)

            # Detect online duplicates in playlist (exact matching title+artist or identical video ID)
            online_duplicates = []
            seen_tracks = []
            for i, entry in enumerate(preview.get('entries', [])):
                t = entry.get('title')
                a = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ""
                u = entry.get('url', '')
                if not t or t in ('[Deleted video]', '[Private video]', 'None', 'Unknown'):
                    continue
                e_vid = u.split('v=')[-1].split('&')[0]
                e_ct = clean_song_title(t, a)
                e_ca = clean_artist_name(a)

                found_orig = None
                for orig_idx, orig_u, orig_t, orig_a, orig_vid, orig_ct, orig_ca in seen_tracks:
                    if (e_vid and orig_vid and e_vid == orig_vid) or (e_ct and orig_ct and e_ct == orig_ct and (e_ca == orig_ca or not e_ca or not orig_ca)):
                        found_orig = (orig_idx, orig_u, orig_t, orig_a)
                        break

                if found_orig:
                    orig_idx, orig_u, orig_t, orig_a = found_orig
                    online_duplicates.append({
                        'title': t,
                        'author': a,
                        'orig_index': orig_idx + 1,
                        'dupe_index': i + 1,
                        'orig_url': orig_u,
                        'dupe_url': u
                    })
                else:
                    seen_tracks.append((i, u, t, a, e_vid, e_ct, e_ca))

            self.finished_signal.emit(preview, self.p_dict, missing_entries, local_cnt, online_duplicates)
        except Exception as e:
            self.error_signal.emit(str(e), self.p_dict)


class SpinnerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 54)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._rotate)
        self._timer.start(25)

    def _rotate(self):
        self._angle = (self._angle + 12) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(6, 6, -6, -6)

        # Background circle track
        pen_bg = QPen(QColor(51, 65, 85, 140), 4)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 0, 360 * 16)

        # Animated highlight arc
        pen_fg = QPen(QColor(56, 189, 248), 4)
        pen_fg.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_fg)
        painter.drawArc(rect, -self._angle * 16, 95 * 16)
        painter.end()


class LoadingOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setObjectName("LoadingCard")
        card.setFixedSize(400, 210)
        card.setStyleSheet("""
            QFrame#LoadingCard {
                background-color: #1e293b;
                border: 1px solid #38bdf8;
                border-radius: 12px;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(10)
        card_layout.setContentsMargins(24, 20, 24, 20)

        self.spinner = SpinnerWidget()
        self.title_label = QLabel("Syncing Playlist...")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #f8fafc;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.msg_label = QLabel("Connecting to YouTube...")
        self.msg_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setWordWrap(True)

        self.sub_label = QLabel("Syncing in progress... The application might freeze, this is normal.")
        self.sub_label.setStyleSheet("font-size: 11px; color: #64748b; font-style: italic;")
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setWordWrap(True)

        card_layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.msg_label)
        card_layout.addWidget(self.sub_label)

        layout.addWidget(card)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(15, 23, 42, 200))
        painter.end()

    def show_loading(self, title="Syncing Playlist...", message="Connecting to YouTube..."):
        self.title_label.setText(title)
        self.msg_label.setText(message)
        if self.parent():
            self.resize(self.parent().size())
            self.raise_()
        self.show()

    def hide_loading(self):
        self.hide()


class OrphanFilesDialog(QDialog):
    def __init__(self, orphan_items: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Removed Tracks Detected")
        self.setMinimumSize(700, 440)
        self.deleted_files = []

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(f"<h3>Found {len(orphan_items)} track(s) removed from online playlist</h3>")
        header.setStyleSheet("color: #f8fafc;")
        desc = QLabel(
            "The following files were downloaded previously, but are no longer present in the online YouTube playlist.\n"
            "Review the list below and choose whether to delete them locally or keep them on your disk:"
        )
        desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        desc.setWordWrap(True)

        layout.addWidget(header)
        layout.addWidget(desc)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Track / Filename", "Video ID", "YouTube Link"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setRowCount(len(orphan_items))

        for row, item in enumerate(orphan_items):
            fn = item.get('filename', '')
            vid = item.get('vid', 'Unknown')
            url = item.get('url', '')

            item_fn = QTableWidgetItem(fn)
            item_fn.setFlags(item_fn.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item_fn.setCheckState(Qt.CheckState.Checked)
            self.table.setItem(row, 0, item_fn)

            item_vid = QTableWidgetItem(vid)
            item_vid.setForeground(QColor("#38bdf8"))
            self.table.setItem(row, 1, item_vid)

            if url:
                btn_link = QPushButton("Open Link ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setStyleSheet("""
                    QPushButton {
                        background: #1e293b;
                        color: #38bdf8;
                        border: 1px solid #334155;
                        border-radius: 4px;
                        padding: 2px 8px;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background: #0284c7;
                        color: #ffffff;
                    }
                """)
                btn_link.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
                self.table.setCellWidget(row, 2, btn_link)
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
                background-color: #dc2626;
                color: #ffffff;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #ef4444;
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
    stem_map = read_stem_vid_map(out_dir)

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
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.deleted_files:
        deleted = []
        for fn in dlg.deleted_files:
            try:
                os.remove(os.path.join(out_dir, fn))
                deleted.append(fn)
            except Exception:
                pass
        return deleted
    return []


class OnlineDuplicatesDialog(QDialog):
    def __init__(self, duplicate_items: list[dict], playlist_title: str = "Playlist", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Online Duplicates Detected")
        self.setMinimumSize(740, 440)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        header = QLabel(f"<h3>Found {len(duplicate_items)} duplicate track(s) in '{playlist_title}'</h3>")
        header.setStyleSheet("color: #f8fafc;")
        desc = QLabel(
            "The following tracks are added multiple times in your online YouTube playlist.\n"
            "You can open the duplicate links below to locate and remove them directly from YouTube Music:"
        )
        desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        desc.setWordWrap(True)

        layout.addWidget(header)
        layout.addWidget(desc)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Track / Artist", "Original Position", "Duplicate Position", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setRowCount(len(duplicate_items))

        for row, item in enumerate(duplicate_items):
            title = item.get('title', 'Unknown')
            author = item.get('author', '')
            display_name = f"{author} - {title}" if author else title
            orig_idx = str(item.get('orig_index', ''))
            dupe_idx = str(item.get('dupe_index', ''))
            dupe_url = item.get('dupe_url', '') or item.get('orig_url', '')

            item_title = QTableWidgetItem(display_name)
            self.table.setItem(row, 0, item_title)

            item_orig = QTableWidgetItem(f"Track #{orig_idx}")
            item_orig.setForeground(QColor("#10b981"))
            self.table.setItem(row, 1, item_orig)

            item_dupe = QTableWidgetItem(f"Duplicate #{dupe_idx}")
            item_dupe.setForeground(QColor("#38bdf8"))
            self.table.setItem(row, 2, item_dupe)

            if dupe_url:
                btn_link = QPushButton("Open in YouTube ↗")
                btn_link.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_link.setStyleSheet("""
                    QPushButton {
                        background: #1e293b;
                        color: #38bdf8;
                        border: 1px solid #334155;
                        border-radius: 4px;
                        padding: 3px 10px;
                        font-size: 11px;
                        font-weight: 500;
                    }
                    QPushButton:hover {
                        background: #0284c7;
                        color: #ffffff;
                    }
                """)
                btn_link.clicked.connect(lambda _, u=dupe_url: QDesktopServices.openUrl(QUrl(u)))
                self.table.setCellWidget(row, 3, btn_link)

        layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)


class PlaylistUpToDateDialog(QDialog):
    def __init__(self, title: str, count: int, local_files_count: Optional[int] = None, duplicates: Optional[list] = None, parent=None):
        super().__init__(parent)
        self.duplicates = duplicates or []
        self.playlist_title = title
        self.setWindowTitle("Sync Complete")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        h = 330 if self.duplicates else 280
        self.setFixedSize(500, h)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        card = QFrame(self)
        card.setObjectName("UpToDateCard")
        card.setStyleSheet("""
            QFrame#UpToDateCard {
                background-color: #0f172a;
                border: 1px solid #10b981;
                border-radius: 14px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(25)
        shadow.setColor(QColor(16, 185, 129, 50))
        shadow.setOffset(0, 6)
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 18, 20, 18)

        icon_lbl = QLabel("✓")
        icon_lbl.setStyleSheet("font-size: 42px; color: #10b981; font-weight: bold; background: transparent;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        h_lbl = QLabel("Up to Date!")
        h_lbl.setStyleSheet("font-size: 18px; font-weight: bold; color: #10b981; background: transparent;")
        h_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        desc_lbl = QLabel(f"All <b>{count}</b> tracks in playlist<br><span style='color: #e2e8f0; font-size: 14px;'>{title}</span><br>are already verified and downloaded.")
        desc_lbl.setStyleSheet("font-size: 13px; color: #94a3b8; line-height: 1.4; background: transparent;")
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)

        layout.addWidget(icon_lbl)
        layout.addWidget(h_lbl)
        layout.addWidget(desc_lbl)

        if self.duplicates:
            btn_dupes = QPushButton(f"ℹ️ {len(self.duplicates)} Online Duplicate(s) Found — View List", card)
            btn_dupes.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_dupes.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #38bdf8;
                    border: 1px solid #0284c7;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 12px;
                    padding: 6px 14px;
                }
                QPushButton:hover {
                    background-color: #0284c7;
                    color: #ffffff;
                }
            """)
            btn_dupes.clicked.connect(self._show_duplicates)
            layout.addWidget(btn_dupes, 0, Qt.AlignmentFlag.AlignCenter)

        btn_ok = QPushButton("Awesome", card)
        btn_ok.setFixedSize(140, 36)
        btn_ok.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_ok.setDefault(True)
        btn_ok.setAutoDefault(True)
        btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                border-radius: 6px;
                font-weight: bold;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        btn_ok.clicked.connect(self.accept)

        layout.addSpacing(4)
        layout.addWidget(btn_ok, 0, Qt.AlignmentFlag.AlignCenter)
        
        main_layout.addWidget(card)

    def _show_duplicates(self):
        OnlineDuplicatesDialog(self.duplicates, playlist_title=self.playlist_title, parent=self).exec()


class UnavailableTracksDialog(QDialog):
    def __init__(self, items: list[tuple[dict, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unavailable Tracks on YouTube")
        self.setMinimumSize(620, 440)
        self.setStyleSheet("""
            QDialog { background-color: #0b1120; color: #f8fafc; }
            QTextEdit { background-color: #0f172a; border: 1px solid #1e293b; border-radius: 8px; color: #cbd5e1; font-family: monospace; font-size: 12px; padding: 10px; }
            QPushButton { background-color: #3b82f6; color: white; border-radius: 6px; padding: 8px 18px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background-color: #2563eb; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        h_lbl = QLabel(f"⚠️ {len(items)} track(s) removed or unavailable on YouTube")
        h_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #f59e0b;")
        layout.addWidget(h_lbl)

        desc_lbl = QLabel(
            "These tracks cannot be downloaded because they were removed by copyright, set to private, or deleted from YouTube by the uploader.\n\n"
            "You can copy this list to find and remove them from your online playlist:"
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; color: #94a3b8; line-height: 1.4;")
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

        btn_box = QHBoxLayout()
        btn_copy = QPushButton("📋 Copy List to Clipboard")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.clicked.connect(self.copy_list)

        btn_close = QPushButton("Close")
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("background-color: #334155; color: white;")
        btn_close.clicked.connect(self.accept)

        btn_box.addWidget(btn_copy)
        btn_box.addStretch()
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)

    def copy_list(self):
        QApplication.clipboard().setText(self.text_area.toPlainText())
        QMessageBox.information(self, "Copied", "Unavailable tracks list copied to clipboard!")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Logovo Downloads")
        self.setMinimumSize(880, 720)
        self.setStyleSheet(get_stylesheet())

        icon_path = get_resource_path("media/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setup_tray()

        self.settings = SettingsManager()
        self.history = HistoryManager()
        self.playlists_mgr = PlaylistsManager()

        # Add session divider to logs
        try:
            log_file = get_app_data_dir() / "app_logs.txt"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'-'*20} New Session: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {'-'*20}\n")
        except Exception:
            pass

        self.download_queue = []  # List of QueueItemWidget
        self.failed_queue = []    # List of (item_data, error_msg)
        self.unavailable_queue = [] # List of (item_data, error_msg)
        self.active_workers = {}  # widget -> WorkerThread
        self.widget_start_times = {} # widget -> timestamp
        self.is_downloading = False

        self.success_count = 0
        self.error_count = 0
        self.downloaded_count = 0
        self.skipped_count = 0
        self.track_durations = []

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        self.setup_downloads_tab()
        self.setup_playlists_tab()
        self.setup_history_tab()
        self.setup_settings_tab()
        self.setup_about_tab()

        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Startup yt-dlp core update check
        if self.settings.get('check_ytdlp_updates_on_startup', True):
            self.startup_update_thread = CheckUpdateThread()
            self.startup_update_thread.result_signal.connect(self.on_startup_update_check_result)
            self.startup_update_thread.start()

        # Loading overlay for smooth non-blocking operations
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()

    def _on_tab_changed(self, index: int):
        if index == 1:
            self.refresh_playlists_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay') and self.loading_overlay:
            self.loading_overlay.resize(self.size())

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon_path = get_resource_path("media/icon.ico")
        if icon_path.exists():
            self.tray_icon.setIcon(QIcon(str(icon_path)))

        tray_menu = QMenu()
        show_action = QAction("Restore", self)
        show_action.triggered.connect(self.showNormal)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_icon_activated)
        self.tray_icon.show()

    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.showNormal()

    # ─── TAB 1: DOWNLOADS ───────────────────────────────────────────────────────

    def setup_downloads_tab(self):
        self.downloads_tab = QWidget()
        layout = QVBoxLayout(self.downloads_tab)

        # Top Toolbar
        toolbar = QHBoxLayout()
        self.btn_paste = QPushButton("Paste from clipboard")
        self.btn_load = QPushButton("Load from file")

        self.btn_paste.clicked.connect(self.paste_from_clipboard)
        self.btn_load.clicked.connect(self.load_from_file)

        toolbar.addWidget(self.btn_paste)
        toolbar.addWidget(self.btn_load)
        toolbar.addStretch()

        # Sleek telemetry text directly in toolbar
        self.top_telemetry_label = QLabel("")
        self.top_telemetry_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        toolbar.addWidget(self.top_telemetry_label)

        layout.addLayout(toolbar)

        # URL Input
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter YouTube or YouTube Music URL...")
        url_layout.addWidget(self.url_input)

        # Visual Queue Scroll Area
        self.queue_scroll_area = QScrollArea()
        self.queue_scroll_area.setWidgetResizable(True)
        self.queue_scroll_area.setObjectName("QueueScrollArea")
        self.queue_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_scroll_area.setMinimumHeight(350)

        self.queue_container = QWidget()
        self.queue_container.setObjectName("QueueContainer")
        self.queue_container_layout = QVBoxLayout(self.queue_container)
        self.queue_container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.queue_container_layout.setSpacing(10)

        self.queue_scroll_area.setWidget(self.queue_container)

        layout.addLayout(url_layout)
        layout.addWidget(self.queue_scroll_area)

        # Format Selection & Add to Queue
        queue_layout = QHBoxLayout()
        queue_layout.addWidget(QLabel("Type:"))
        self.format_combo = QComboBox()
        self.format_combo.wheelEvent = lambda event: event.ignore()
        self.format_combo.addItems(["Audio", "Video"])
        self.format_combo.setPlaceholderText("Select Type...")
        self.format_combo.setCurrentIndex(-1)
        self.format_combo.currentIndexChanged.connect(self.on_main_format_combo_changed)
        queue_layout.addWidget(self.format_combo)

        self.lbl_main_subs = QLabel(" Subs/Lyrics:")
        queue_layout.addWidget(self.lbl_main_subs)
        self.subs_combo = QComboBox()
        self.subs_combo.wheelEvent = lambda event: event.ignore()
        self.subs_combo.addItems(["Default (Settings)", "None", "Original (Uploaded)", "All", "en", "ru", "uk"])
        queue_layout.addWidget(self.subs_combo)
        self.update_main_subs_combo_state()

        self.btn_add_queue = QPushButton("Add to queue")
        self.btn_add_queue.clicked.connect(self.add_to_queue_action)
        self.btn_add_queue.setMinimumHeight(30)

        self.btn_clear_queue = QPushButton("Clear Queue")
        self.btn_clear_queue.clicked.connect(self.clear_queue)
        self.btn_clear_queue.setMinimumHeight(30)

        queue_layout.addWidget(self.btn_add_queue)
        queue_layout.addWidget(self.btn_clear_queue)

        self.stats_label = QLabel("Success: 0 | In queue: 0 | Errors: 0")
        queue_layout.addStretch()
        queue_layout.addWidget(self.stats_label)

        layout.addLayout(queue_layout)

        # Status Label below Queue Area
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #94a3b8; font-style: italic;")
        layout.addWidget(self.status_label)

        # Global Progress Bar
        self.global_progress = QProgressBar()
        self.global_progress.setFixedHeight(6)
        self.global_progress.setTextVisible(False)
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self.global_progress.setStyleSheet("""
            QProgressBar {
                background-color: #1e293b;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #38bdf8;
                border-radius: 3px;
            }
        """)
        layout.addWidget(self.global_progress)

        # Bottom Actions Bar
        bottom_actions = QHBoxLayout()
        self.btn_download_all = QPushButton("Download")
        self.btn_download_all.setEnabled(False)
        self.btn_download_all.clicked.connect(self.start_queue)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_download)

        self.btn_clear_completed = QPushButton("Clear Completed")
        self.btn_clear_completed.clicked.connect(self.clear_completed)

        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.clicked.connect(self.open_downloads_folder)

        self.btn_logs = QPushButton("Logs")
        self.btn_logs.clicked.connect(self.open_logs_file)

        bottom_actions.addWidget(self.btn_download_all)
        bottom_actions.addWidget(self.btn_stop)
        bottom_actions.addWidget(self.btn_clear_completed)
        bottom_actions.addStretch()
        bottom_actions.addWidget(self.btn_open_folder)
        bottom_actions.addWidget(self.btn_logs)

        layout.addLayout(bottom_actions)
        self.tabs.addTab(self.downloads_tab, "DOWNLOADS")

    # ─── TAB 2: PLAYLISTS ──────────────────────────────────────────────────────

    def setup_playlists_tab(self):
        self.playlists_tab = QWidget()
        layout = QVBoxLayout(self.playlists_tab)

        # Top Bar
        top_bar = QHBoxLayout()
        btn_track_new = QPushButton("+ Track New Playlist")
        btn_sync_all = QPushButton("Sync All Playlists")
        self.lbl_playlists_count = QLabel("Tracked Playlists: 0")
        self.lbl_playlists_count.setStyleSheet("font-size: 12px; color: #94a3b8;")

        btn_track_new.clicked.connect(self.track_new_playlist_dialog)
        btn_sync_all.clicked.connect(self.sync_all_playlists)

        top_bar.addWidget(btn_track_new)
        top_bar.addWidget(btn_sync_all)
        top_bar.addStretch()
        top_bar.addWidget(self.lbl_playlists_count)
        layout.addLayout(top_bar)

        # Scroll Area for Playlist Cards
        self.playlists_scroll = QScrollArea()
        self.playlists_scroll.setWidgetResizable(True)
        self.playlists_scroll.setObjectName("QueueScrollArea")

        self.playlists_container = QWidget()
        self.playlists_container.setObjectName("QueueContainer")
        self.playlists_container_layout = QVBoxLayout(self.playlists_container)
        self.playlists_container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.playlists_container_layout.setSpacing(10)

        self.playlists_scroll.setWidget(self.playlists_container)
        layout.addWidget(self.playlists_scroll)

        self.refresh_playlists_ui()
        self.tabs.addTab(self.playlists_tab, "PLAYLISTS")

    def refresh_playlists_ui(self):
        # Disconnect old thumbnail loaders
        if hasattr(self, '_pl_loaders'):
            for l in self._pl_loaders:
                try:
                    l.disconnect()
                except Exception:
                    pass
            self._pl_loaders.clear()

        # Clear existing cards
        while self.playlists_container_layout.count():
            item = self.playlists_container_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        items = self.playlists_mgr.get_all()
        self.lbl_playlists_count.setText(f"Tracked Playlists: {len(items)}")

        if not items:
            empty_lbl = QLabel("No playlists tracked yet.\nClick '+ Track New Playlist' to save and sync playlists in 1 click.")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #64748b; font-size: 14px; margin-top: 60px;")
            self.playlists_container_layout.addWidget(empty_lbl)
            return

        for p in items:
            card = QWidget()
            card.setObjectName("PlaylistCard")
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(15)

            # Thumbnail
            thumb_lbl = QLabel()
            thumb_lbl.setFixedSize(64, 64)
            thumb_lbl.setStyleSheet("background-color: #0f172a; border-radius: 6px;")
            thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

            folder_str = p.get('folder_path', '')
            local_pix = None
            if folder_str and os.path.exists(folder_str):
                for fname in ("cover.jpg", "cover.png", "cover.jpeg", "folder_icon.ico"):
                    c_path = os.path.join(folder_str, fname)
                    if os.path.exists(c_path):
                        pix = QPixmap(c_path)
                        if not pix.isNull():
                            local_pix = pix
                            break

            thumb_url = p.get('thumbnail')
            if local_pix:
                thumb_lbl.setPixmap(local_pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
            elif thumb_url:
                class PlaylistThumbLoader(QThread):
                    loaded = pyqtSignal(QPixmap)
                    def __init__(self, url):
                        super().__init__()
                        self.url = url
                    def run(self):
                        try:
                            import requests
                            resp = requests.get(self.url, timeout=5)
                            if resp.status_code == 200:
                                pix = QPixmap()
                                pix.loadFromData(resp.content)
                                self.loaded.emit(pix)
                        except Exception:
                            pass

                loader = PlaylistThumbLoader(thumb_url)
                def _safe_set_pix(pix, target_lbl=thumb_lbl):
                    try:
                        import sip
                        if target_lbl and not sip.isdeleted(target_lbl):
                            target_lbl.setPixmap(pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                    except Exception:
                        pass

                loader.loaded.connect(_safe_set_pix)
                loader.start()
                if not hasattr(self, '_pl_loaders'):
                    self._pl_loaders = []
                self._pl_loaders.append(loader)
            else:
                thumb_lbl.setText("🎵")

            card_layout.addWidget(thumb_lbl)

            # Details
            info_layout = QVBoxLayout()
            title_lbl = QLabel(p.get('title', 'Untitled Playlist'))
            title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")

            path_lbl = QLabel(f"📁 {p.get('folder_path', '')}")
            path_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")

            media_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac", ".mp4", ".mkv", ".webm", ".avi", ".mov"}
            downloaded_count = 0
            if folder_str and os.path.exists(folder_str):
                try:
                    for entry in os.scandir(folder_str):
                        if entry.is_file():
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in media_exts:
                                downloaded_count += 1
                except Exception:
                    pass

            pl_track_count = p.get('track_count', 0)
            is_synced = p.get('status') == 'synced' or (downloaded_count >= pl_track_count and pl_track_count > 0)
            if is_synced or (downloaded_count > 0 and abs(downloaded_count - pl_track_count) <= 6):
                count_str = f"<b>{downloaded_count}</b> files (All <b>{pl_track_count}</b> synced)"
                status_color = "#10b981"
            else:
                count_str = f"<b>{downloaded_count}</b> / <b>{pl_track_count}</b> tracks"
                status_color = "#38bdf8"
            meta_lbl = QLabel(f"In Folder: {count_str}  |  Last Synced: {p.get('last_synced', 'Never')}")
            meta_lbl.setStyleSheet(f"font-size: 11px; color: {status_color}; font-weight: 500;")

            info_layout.addWidget(title_lbl)
            info_layout.addWidget(path_lbl)
            info_layout.addWidget(meta_lbl)
            card_layout.addLayout(info_layout, 1)

            # Buttons
            btn_box = QHBoxLayout()
            btn_sync = QPushButton("Sync")
            btn_sync.setFixedSize(75, 32)
            btn_sync.clicked.connect(lambda _, pl=p: self.sync_tracked_playlist(pl))

            btn_folder = QPushButton("Folder")
            btn_folder.setFixedSize(75, 32)
            btn_folder.clicked.connect(lambda _, fp=p.get('folder_path'): QDesktopServices.openUrl(QUrl.fromLocalFile(fp)))

            btn_remove = QPushButton("✕")
            btn_remove.setFixedSize(32, 32)
            btn_remove.setToolTip("Remove from tracking")
            btn_remove.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #ef4444;
                    border: 1px solid #334155;
                    border-radius: 6px;
                    font-size: 15px;
                    font-weight: bold;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #ef4444;
                    color: #ffffff;
                    border: 1px solid #ef4444;
                }
            """)
            btn_remove.clicked.connect(lambda _, u=p.get('url'): self.remove_tracked_playlist(u))

            btn_box.addWidget(btn_sync)
            btn_box.addWidget(btn_folder)
            btn_box.addWidget(btn_remove)
            card_layout.addLayout(btn_box)

            self.playlists_container_layout.addWidget(card)

    def track_new_playlist_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Track New Playlist")
        dialog.setFixedWidth(520)
        d_layout = QVBoxLayout(dialog)

        form = QFormLayout()
        url_input = QLineEdit()
        url_input.setPlaceholderText("https://music.youtube.com/playlist?list=...")
        form.addRow("Playlist URL:", url_input)

        folder_row = QHBoxLayout()
        initial_dir = self.settings.get('last_selected_folder') or self.settings.get('download_path')
        folder_input = QLineEdit(initial_dir)
        btn_browse = QPushButton("Browse...")

        def _browse_pl_folder():
            start_dir = folder_input.text().strip() or initial_dir
            chosen = QFileDialog.getExistingDirectory(dialog, "Select Save Folder", start_dir)
            if chosen:
                folder_input.setText(chosen)
                self.settings.set('last_selected_folder', chosen)

        btn_browse.clicked.connect(_browse_pl_folder)
        folder_row.addWidget(folder_input)
        folder_row.addWidget(btn_browse)
        form.addRow("Save Location:", folder_row)

        type_combo = QComboBox()
        type_combo.addItems(["Select Type...", "Audio", "Video"])
        form.addRow("Default Type:", type_combo)

        d_layout.addLayout(form)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_ok = QPushButton("Save & Track")
        btn_cancel = QPushButton("Cancel")

        def _validate_playlist_form():
            if type_combo.currentText() == "Select Type...":
                QMessageBox.warning(dialog, "Select Type", "Please select 'Audio' or 'Video' for this playlist.")
                return
            if not url_input.text().strip():
                QMessageBox.warning(dialog, "Missing URL", "Please enter a valid playlist URL.")
                return
            dialog.accept()

        btn_ok.clicked.connect(_validate_playlist_form)
        btn_cancel.clicked.connect(dialog.reject)
        btn_box.addWidget(btn_ok)
        btn_box.addWidget(btn_cancel)
        d_layout.addLayout(btn_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            url = url_input.text().strip()
            folder = folder_input.text().strip()
            if not url or not folder:
                return

            self.status_label.setText("Fetching playlist info...")
            QApplication.processEvents()
            preview = get_video_preview(url, cookies=self.get_cookies_config())
            title = preview.get('title', 'Playlist') if preview else 'Playlist'
            thumb = preview.get('thumbnail', '') if preview else ''
            count = preview.get('count', 0) if preview else 0

            # Sanitize playlist title for Android/MTP/Windows
            clean_title = clean_filename_for_all_devices(title, max_len=100) or "Playlist"

            # Check if chosen folder already ends with playlist title
            chosen_p = Path(folder).resolve()
            if chosen_p.name.lower() == clean_title.lower():
                final_folder = str(chosen_p)
            else:
                final_folder = str(chosen_p / clean_title)

            os.makedirs(final_folder, exist_ok=True)

            cover_mode = self.settings.get('playlist_cover_mode', 'both')
            if thumb and cover_mode != 'none':
                apply_playlist_cover_settings(final_folder, thumb, mode=cover_mode)

            self.playlists_mgr.add_playlist(
                url=url,
                title=title,
                folder_path=final_folder,
                thumbnail=thumb,
                track_count=count,
                media_type=type_combo.currentText()
            )
            self.refresh_playlists_ui()
            self.status_label.setText(f"Tracked playlist '{title}' added.")

    def remove_tracked_playlist(self, url: str):
        reply = QMessageBox.question(self, "Remove Playlist", "Remove this playlist from tracking?\n(Your downloaded files will not be deleted)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.playlists_mgr.remove_playlist(url)
            self.refresh_playlists_ui()

    def sync_tracked_playlist(self, p_dict: dict):
        url = p_dict.get('url')
        out_dir = p_dict.get('folder_path')
        if not url or not out_dir:
            return

        if not hasattr(self, '_active_sync_urls'):
            self._active_sync_urls = set()
        if url in self._active_sync_urls:
            return
        self._active_sync_urls.add(url)

        title = p_dict.get('title', 'Playlist')
        self.status_label.setText(f"Syncing playlist '{title}' in background...")
        self.loading_overlay.show_loading(f"Syncing '{title}'...", "Connecting to YouTube and comparing tracks...")

        worker = SyncPlaylistWorker(p_dict, self.settings, cookies=self.get_cookies_config())
        worker.finished_signal.connect(self._on_sync_playlist_finished)
        worker.error_signal.connect(self._on_sync_playlist_error)
        if not hasattr(self, '_sync_workers'):
            self._sync_workers = []
        self._sync_workers.append(worker)

        def _cleanup():
            if hasattr(self, '_active_sync_urls'):
                self._active_sync_urls.discard(url)
            if worker in self._sync_workers:
                self._sync_workers.remove(worker)

        worker.finished.connect(_cleanup)
        worker.start()

    def _on_sync_playlist_error(self, err_msg: str, p_dict: dict):
        self.loading_overlay.hide_loading()
        title = p_dict.get('title', 'Playlist') if p_dict else 'Playlist'
        self.status_label.setText(f"Sync error for '{title}'.")
        QMessageBox.warning(self, "Sync Error", f"Could not fetch playlist metadata from YouTube:\n{err_msg}")

    def _on_sync_playlist_finished(self, preview: dict, p_dict: dict, missing_entries: list, local_cnt: int, online_duplicates: list = None):
        self.loading_overlay.hide_loading()
        url = p_dict.get('url')
        out_dir = p_dict.get('folder_path')
        count = preview.get('count', 0)
        p_dict['track_count'] = count
        if preview.get('thumbnail'):
            p_dict['thumbnail'] = preview.get('thumbnail')
        if not missing_entries:
            self.playlists_mgr.update_sync_info(url, track_count=count, status='synced')
            self.refresh_playlists_ui()
            self.status_label.setText(f"No new media to sync. All {count} tracks in '{p_dict.get('title')}' are up to date.")
            PlaylistUpToDateDialog(p_dict.get('title', 'Playlist'), count, local_files_count=local_cnt, duplicates=online_duplicates, parent=self).exec()
            return
        else:
            self.playlists_mgr.update_sync_info(url, track_count=count, status='pending')

        # Auto-clear previous completed/finished queue if not downloading
        if self.download_queue and not self.is_downloading:
            all_done = all(w.status_state in ("Success", "Error", "Unavailable", "Completed", "Finished") for w in self.download_queue)
            if all_done:
                self.clear_queue()

        self.queue_container.setUpdatesEnabled(False)
        for entry in missing_entries:
            self._add_single_item_to_queue(entry, batch=True)
        self.queue_container.setUpdatesEnabled(True)

        media_type = p_dict.get('media_type', 'Audio')
        self.format_combo.blockSignals(True)
        self.format_combo.setCurrentText(media_type)
        self.format_combo.blockSignals(False)
        self.update_main_subs_combo_state()

        self.update_queue_ui()
        self.refresh_playlists_ui()
        self.tabs.setCurrentIndex(0)
        self.status_label.setText(f"Found {len(missing_entries)} new track(s) from '{p_dict.get('title')}'. Added to queue.")

    def sync_all_playlists(self):
        items = self.playlists_mgr.get_all()
        if not items:
            QMessageBox.information(self, "No Playlists", "No tracked playlists found to sync.")
            return

        for p in items:
            self.sync_tracked_playlist(p)

    # ─── TAB 3: HISTORY ────────────────────────────────────────────────────────

    def setup_history_tab(self):
        self.history_tab = QWidget()
        layout = QVBoxLayout(self.history_tab)

        toolbar = QHBoxLayout()
        btn_refresh = QPushButton("Refresh")
        btn_clear_hist = QPushButton("Clear History")

        btn_refresh.clicked.connect(self.refresh_history)
        btn_clear_hist.clicked.connect(self.clear_history)

        toolbar.addStretch()
        toolbar.addWidget(btn_refresh)
        toolbar.addWidget(btn_clear_hist)
        layout.addLayout(toolbar)

        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Date", "Author", "Title", "Platform", "Status"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.history_table.setColumnWidth(1, 200)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(3, 130)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.history_table.setColumnWidth(4, 140)
        self.history_table.horizontalHeader().setStretchLastSection(False)

        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history_table.setShowGrid(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_table.setStyleSheet("""
            QTableWidget {
                background-color: #0b1329;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 8px;
                gridline-color: #1e293b;
                selection-background-color: #1e293b;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                padding: 10px;
                border: none;
                font-weight: bold;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #1e293b;
            }
        """)
        layout.addWidget(self.history_table)

        self.history_stats_label = QLabel("Total: 0 | Completed: 0 | Errors: 0")
        layout.addWidget(self.history_stats_label)

        self.refresh_history()
        self.tabs.addTab(self.history_tab, "HISTORY")

    # ─── TAB 4: SETTINGS ───────────────────────────────────────────────────────

    def setup_settings_tab(self):
        self.settings_tab = QWidget()
        self.settings_tab.setObjectName("SettingsTab")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("SettingsScrollArea")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_wrapper = QWidget()
        scroll_wrapper.setObjectName("SettingsScrollWrapper")
        outer_h_layout = QHBoxLayout(scroll_wrapper)
        outer_h_layout.setContentsMargins(0, 10, 0, 20)

        content = QWidget()
        content.setObjectName("SettingsContainer")
        content.setMaximumWidth(820)
        layout = QVBoxLayout(content)
        layout.setSpacing(14)
        layout.setContentsMargins(15, 10, 15, 15)

        outer_h_layout.addStretch(1)
        outer_h_layout.addWidget(content)
        outer_h_layout.addStretch(1)

        def make_combo(items=None, min_width=None):
            cb = QComboBox()
            cb.wheelEvent = lambda event: event.ignore()
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            if min_width:
                cb.setMinimumWidth(min_width)
            if items:
                cb.addItems(items)
            return cb

        # 1. Download Folder
        folder_layout = QHBoxLayout()
        self.folder_input = QLineEdit(self.settings.get('download_path'))
        self.folder_input.setReadOnly(True)
        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(90)
        btn_browse.clicked.connect(self.browse_folder)
        folder_layout.addWidget(QLabel("Download Folder:"))
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(btn_browse)
        layout.addLayout(folder_layout)

        # 2. General Settings
        gen_grid = QGridLayout()
        gen_grid.setHorizontalSpacing(20)
        gen_grid.setVerticalSpacing(10)

        # Row 0: Concurrent Downloads
        gen_grid.addWidget(QLabel("Concurrent Downloads:"), 0, 0)
        self.threads_combo = make_combo(["1", "2", "3 (Recommended)", "4", "5", "6"])
        curr_threads = str(self.settings.get('max_concurrent_downloads', 3))
        for idx in range(self.threads_combo.count()):
            if self.threads_combo.itemText(idx).startswith(curr_threads):
                self.threads_combo.setCurrentIndex(idx)
                break
        self.threads_combo.currentIndexChanged.connect(
            lambda: self.settings.set('max_concurrent_downloads', int(self.threads_combo.currentText().split()[0]))
        )
        gen_grid.addWidget(self.threads_combo, 0, 1)

        # Row 1: Speed Limit
        gen_grid.addWidget(QLabel("Speed Limit:"), 1, 0)
        self.speed_combo = make_combo(["Unlimited", "1 MB/s", "3 MB/s", "5 MB/s", "10 MB/s", "20 MB/s"])
        self.speed_combo.setCurrentText(self.settings.get('speed_limit', 'Unlimited'))
        self.speed_combo.currentTextChanged.connect(lambda t: self.settings.set('speed_limit', t))
        gen_grid.addWidget(self.speed_combo, 1, 1)

        # Row 2: Post-Download Action
        gen_grid.addWidget(QLabel("Post-Download Action:"), 2, 0)
        self.post_combo = make_combo(["Disabled (Do nothing)", "Shutdown PC", "Sleep / Suspend"])
        curr_post = self.settings.get('post_download_action', 'Disabled')
        for i in range(self.post_combo.count()):
            if self.post_combo.itemText(i).startswith(curr_post):
                self.post_combo.setCurrentIndex(i)
                break
        self.post_combo.currentIndexChanged.connect(
            lambda: self.settings.set('post_download_action', self.post_combo.currentText().split()[0])
        )
        gen_grid.addWidget(self.post_combo, 2, 1)

        # Row 3: Filename Format / Compatibility
        gen_grid.addWidget(QLabel("Filename Format:"), 3, 0)
        self.compat_combo = make_combo()
        self.compat_combo.addItem("Windows Native (Full original titles, no length cutting) - Default", "windows")
        self.compat_combo.addItem("UNIX / POSIX / Android MTP (Strict FAT32 / 160 char limit)", "unix")
        cur_compat = self.settings.get('filename_compat', 'windows')
        idx_c = self.compat_combo.findData(cur_compat)
        if idx_c >= 0:
            self.compat_combo.setCurrentIndex(idx_c)
        else:
            self.compat_combo.setCurrentIndex(0)
        self.compat_combo.currentIndexChanged.connect(
            lambda: self.settings.set('filename_compat', self.compat_combo.currentData())
        )
        gen_grid.addWidget(self.compat_combo, 3, 1)

        gen_grid.setColumnStretch(1, 1)
        layout.addLayout(gen_grid)

        # 3. Audio & Music Settings GroupBox
        audio_group = QGroupBox("Audio & Music Settings")
        audio_layout = QVBoxLayout(audio_group)
        audio_layout.setSpacing(10)
        audio_layout.setContentsMargins(14, 16, 14, 14)

        # File Naming Pattern (with Reset button)
        naming_layout = QHBoxLayout()
        naming_layout.addWidget(QLabel("File Naming Pattern:"))
        self.naming_input = QLineEdit(self.settings.get('naming_pattern', '{artist} - {title}'))
        self.naming_input.textChanged.connect(lambda t: self.settings.set('naming_pattern', t))
        btn_reset_pattern = QPushButton("Reset to Default")
        btn_reset_pattern.setFixedWidth(130)
        btn_reset_pattern.setToolTip("Reset file naming pattern to default: {artist} - {title}")
        btn_reset_pattern.clicked.connect(self.reset_naming_pattern)
        naming_layout.addWidget(self.naming_input)
        naming_layout.addWidget(btn_reset_pattern)
        audio_layout.addLayout(naming_layout)

        badges_row = QHBoxLayout()
        badges_row.addWidget(QLabel("Insert token:"))
        tokens = [("{artist}", "Artist"), ("{title}", "Title"), ("{index}", "Index"), ("{album}", "Album"), ("{year}", "Year")]
        for token, label in tokens:
            btn_tag = QPushButton(token)
            btn_tag.setObjectName("TagPill")
            btn_tag.clicked.connect(lambda _, t=token: self.insert_naming_token(t))
            badges_row.addWidget(btn_tag)
        badges_row.addStretch()
        audio_layout.addLayout(badges_row)

        # Playlist Artwork Row
        art_layout = QHBoxLayout()
        art_layout.addWidget(QLabel("Playlist Artwork:"))
        self.cover_mode_combo = make_combo()
        self.cover_mode_combo.addItem("Set as Windows folder icon (.ico) & save image file (Recommended)", "both")
        self.cover_mode_combo.addItem("Set as Windows folder icon (.ico) only", "icon")
        self.cover_mode_combo.addItem("Save cover as PNG / JPG image file only", "file")
        self.cover_mode_combo.addItem("Do not save playlist cover", "none")
        current_cover_mode = self.settings.get('playlist_cover_mode') or 'both'
        idx = self.cover_mode_combo.findData(current_cover_mode)
        if idx >= 0:
            self.cover_mode_combo.setCurrentIndex(idx)
        else:
            self.cover_mode_combo.setCurrentIndex(0)
        self.cover_mode_combo.currentIndexChanged.connect(
            lambda: self.settings.set('playlist_cover_mode', self.cover_mode_combo.currentData())
        )
        art_layout.addWidget(self.cover_mode_combo, 1)
        audio_layout.addLayout(art_layout)

        # Karaoke Mode Toggle + Language Selection
        lyrics_section = QVBoxLayout()
        lyrics_section.setSpacing(6)
        self.chk_audio_lyrics = QCheckBox("Karaoke Mode (Download & embed synchronized lyrics / LRC if available)")
        self.chk_audio_lyrics.setChecked(self.settings.get('download_audio_lyrics', False))
        self.chk_audio_lyrics.toggled.connect(self.toggle_audio_lyrics_setting)
        lyrics_section.addWidget(self.chk_audio_lyrics)

        lyrics_lang_row = QHBoxLayout()
        lyrics_lang_row.setContentsMargins(22, 0, 0, 0)
        self.lbl_lyrics_lang = QLabel("Lyrics Language:")
        lyrics_lang_row.addWidget(self.lbl_lyrics_lang)
        self.audio_lyrics_lang_combo = make_combo()
        self.audio_lyrics_lang_combo.addItem("Original / Uploaded Only", "orig")
        self.audio_lyrics_lang_combo.addItem("All Available Languages", "all")
        self.audio_lyrics_lang_combo.addItem("English (en)", "en")
        self.audio_lyrics_lang_combo.addItem("Russian (ru)", "ru")
        self.audio_lyrics_lang_combo.addItem("Ukrainian (uk)", "uk")
        cur_lyr_lang = self.settings.get('lyrics_langs', 'orig')
        l_idx = self.audio_lyrics_lang_combo.findData(cur_lyr_lang)
        if l_idx >= 0:
            self.audio_lyrics_lang_combo.setCurrentIndex(l_idx)
        self.audio_lyrics_lang_combo.currentIndexChanged.connect(
            lambda: self.settings.set('lyrics_langs', self.audio_lyrics_lang_combo.currentData())
        )
        lyrics_lang_row.addWidget(self.audio_lyrics_lang_combo, 1)
        lyrics_section.addLayout(lyrics_lang_row)

        is_audio_lyr = self.settings.get('download_audio_lyrics', False)
        self.lbl_lyrics_lang.setEnabled(is_audio_lyr)
        self.audio_lyrics_lang_combo.setEnabled(is_audio_lyr)

        audio_layout.addLayout(lyrics_section)

        # Metadata Tags Section
        meta_section_lbl = QLabel("Embedded Audio Metadata Tags:")
        meta_section_lbl.setStyleSheet("font-weight: bold; color: #94a3b8; margin-top: 6px;")
        audio_layout.addWidget(meta_section_lbl)

        self.chk_embed_all_meta = QCheckBox("Embed all audio metadata (Recommended)")
        is_embed_all = self.settings.get('embed_all_metadata', True)
        self.chk_embed_all_meta.setChecked(is_embed_all)
        audio_layout.addWidget(self.chk_embed_all_meta)

        self.meta_tags_widget = QWidget()
        meta_grid = QGridLayout(self.meta_tags_widget)
        meta_grid.setContentsMargins(20, 2, 0, 2)
        meta_grid.setHorizontalSpacing(30)
        meta_grid.setVerticalSpacing(6)

        stored_tags = self.settings.get('audio_metadata_tags') or {}
        self.chk_meta_artist = QCheckBox("Artist / Channel (TPE1 / artist)")
        self.chk_meta_title = QCheckBox("Track Title (TIT2 / title)")
        self.chk_meta_album = QCheckBox("Album Name (TALB / album)")
        self.chk_meta_cover = QCheckBox("Album Cover Artwork (APIC / covr)")
        self.chk_meta_track_num = QCheckBox("Track Number / Position (TRCK / tracknumber)")
        self.chk_meta_year = QCheckBox("Release Date / Year (TYER / date)")
        self.chk_meta_lyrics = QCheckBox("Karaoke / Synced Lyrics (USLT / embed lyrics)")

        self.tag_checkboxes = {
            'artist': self.chk_meta_artist,
            'title': self.chk_meta_title,
            'album': self.chk_meta_album,
            'cover': self.chk_meta_cover,
            'track_number': self.chk_meta_track_num,
            'year': self.chk_meta_year,
            'lyrics': self.chk_meta_lyrics,
        }

        for k, chk in self.tag_checkboxes.items():
            val = stored_tags.get(k, True)
            chk.setChecked(val)
            chk.toggled.connect(self._on_metadata_tag_toggled)

        meta_grid.addWidget(self.chk_meta_artist, 0, 0)
        meta_grid.addWidget(self.chk_meta_title, 0, 1)
        meta_grid.addWidget(self.chk_meta_album, 1, 0)
        meta_grid.addWidget(self.chk_meta_cover, 1, 1)
        meta_grid.addWidget(self.chk_meta_track_num, 2, 0)
        meta_grid.addWidget(self.chk_meta_year, 2, 1)
        meta_grid.addWidget(self.chk_meta_lyrics, 3, 0)

        audio_layout.addWidget(self.meta_tags_widget)
        self.chk_embed_all_meta.toggled.connect(self._on_embed_all_meta_toggled)
        self._update_meta_checkboxes_state(is_embed_all)

        layout.addWidget(audio_group)

        # 4. Video Settings GroupBox
        video_group = QGroupBox("Video Settings")
        video_layout = QVBoxLayout(video_group)
        video_layout.setSpacing(10)
        video_layout.setContentsMargins(14, 16, 14, 14)

        # Video Naming Pattern (with Reset button)
        v_naming_layout = QHBoxLayout()
        v_naming_layout.addWidget(QLabel("File Naming Pattern:"))
        self.v_naming_input = QLineEdit(self.settings.get('video_naming_pattern', '{title}'))
        self.v_naming_input.textChanged.connect(lambda t: self.settings.set('video_naming_pattern', t))
        btn_reset_v_pattern = QPushButton("Reset to Default")
        btn_reset_v_pattern.setFixedWidth(130)
        btn_reset_v_pattern.setToolTip("Reset video naming pattern to default: {title}")
        btn_reset_v_pattern.clicked.connect(self.reset_video_naming_pattern)
        v_naming_layout.addWidget(self.v_naming_input)
        v_naming_layout.addWidget(btn_reset_v_pattern)
        video_layout.addLayout(v_naming_layout)

        v_badges_row = QHBoxLayout()
        v_badges_row.addWidget(QLabel("Insert token:"))
        v_tokens = [("{title}", "Title"), ("{author}", "Author"), ("{resolution}", "Resolution"), ("{fps}", "FPS"), ("{year}", "Year"), ("{index}", "Index")]
        for token, label in v_tokens:
            btn_v_tag = QPushButton(token)
            btn_v_tag.setObjectName("TagPill")
            btn_v_tag.clicked.connect(lambda _, t=token: self.insert_video_naming_token(t))
            v_badges_row.addWidget(btn_v_tag)
        v_badges_row.addStretch()
        video_layout.addLayout(v_badges_row)

        # Preferred Container & Codec
        v_fmt_layout = QGridLayout()
        v_fmt_layout.setHorizontalSpacing(20)
        v_fmt_layout.setVerticalSpacing(8)

        v_fmt_layout.addWidget(QLabel("Preferred Container:"), 0, 0)
        self.v_container_combo = make_combo(["MP4 (Universal Compatibility)", "MKV (Matroska)"])
        curr_vc = self.settings.get('video_container', 'mp4')
        self.v_container_combo.setCurrentIndex(1 if curr_vc == 'mkv' else 0)
        self.v_container_combo.currentIndexChanged.connect(
            lambda: self.settings.set('video_container', 'mkv' if self.v_container_combo.currentIndex() == 1 else 'mp4')
        )
        v_fmt_layout.addWidget(self.v_container_combo, 0, 1)

        v_fmt_layout.addWidget(QLabel("Preferred Video Codec:"), 1, 0)
        self.v_codec_combo = make_combo(["Auto (Best Quality)", "H.264 / AVC (Maximum Compatibility)", "H.265 / HEVC (High Efficiency)", "VP9 / AV1 (Highest Resolution 4K+)"])
        curr_vcodec = self.settings.get('video_codec', 'auto')
        codec_map = {'auto': 0, 'h264': 1, 'h265': 2, 'vp9_av1': 3}
        self.v_codec_combo.setCurrentIndex(codec_map.get(curr_vcodec, 0))
        self.v_codec_combo.currentIndexChanged.connect(
            lambda: self.settings.set('video_codec', ['auto', 'h264', 'h265', 'vp9_av1'][self.v_codec_combo.currentIndex()])
        )
        v_fmt_layout.addWidget(self.v_codec_combo, 1, 1)
        v_fmt_layout.setColumnStretch(1, 1)
        video_layout.addLayout(v_fmt_layout)

        # Subtitles (Video)
        v_subs_section = QVBoxLayout()
        v_subs_section.setSpacing(6)
        self.chk_subtitles = QCheckBox("Download subtitles (if available)")
        self.chk_subtitles.setChecked(self.settings.get('download_subtitles', False))
        self.chk_subtitles.toggled.connect(self.toggle_subs_setting)
        v_subs_section.addWidget(self.chk_subtitles)

        v_subs_lang_row = QHBoxLayout()
        v_subs_lang_row.setContentsMargins(22, 0, 0, 0)
        self.lbl_video_subs_lang = QLabel("Subtitles Language:")
        v_subs_lang_row.addWidget(self.lbl_video_subs_lang)
        self.video_subs_lang_combo = make_combo()
        self.video_subs_lang_combo.addItem("Original / Uploaded Only", "orig")
        self.video_subs_lang_combo.addItem("All Available Languages", "all")
        self.video_subs_lang_combo.addItem("English (en)", "en")
        self.video_subs_lang_combo.addItem("Russian (ru)", "ru")
        self.video_subs_lang_combo.addItem("Ukrainian (uk)", "uk")
        cur_v_lang = self.settings.get('subtitles_langs', 'orig')
        v_idx = self.video_subs_lang_combo.findData(cur_v_lang)
        if v_idx >= 0:
            self.video_subs_lang_combo.setCurrentIndex(v_idx)
        self.video_subs_lang_combo.currentIndexChanged.connect(
            lambda: self.settings.set('subtitles_langs', self.video_subs_lang_combo.currentData())
        )
        v_subs_lang_row.addWidget(self.video_subs_lang_combo, 1)
        v_subs_section.addLayout(v_subs_lang_row)

        is_v_subs = self.settings.get('download_subtitles', False)
        self.lbl_video_subs_lang.setEnabled(is_v_subs)
        self.video_subs_lang_combo.setEnabled(is_v_subs)
        video_layout.addLayout(v_subs_section)

        # Embedded Video Metadata Tags Section
        v_meta_section_lbl = QLabel("Embedded Video Metadata Tags:")
        v_meta_section_lbl.setStyleSheet("font-weight: bold; color: #94a3b8; margin-top: 6px;")
        video_layout.addWidget(v_meta_section_lbl)

        self.chk_embed_all_v_meta = QCheckBox("Embed all video metadata (Recommended)")
        is_embed_all_v = self.settings.get('embed_all_video_metadata', True)
        self.chk_embed_all_v_meta.setChecked(is_embed_all_v)
        video_layout.addWidget(self.chk_embed_all_v_meta)

        self.v_meta_tags_widget = QWidget()
        v_meta_grid = QGridLayout(self.v_meta_tags_widget)
        v_meta_grid.setContentsMargins(20, 2, 0, 2)
        v_meta_grid.setHorizontalSpacing(30)
        v_meta_grid.setVerticalSpacing(6)

        stored_v_tags = self.settings.get('video_metadata_tags') or {}
        self.chk_v_meta_title = QCheckBox("Video Title / Description")
        self.chk_v_meta_channel = QCheckBox("Channel / Creator Name")
        self.chk_v_meta_year = QCheckBox("Release Date / Year")
        self.chk_v_meta_thumbnail = QCheckBox("Embed Video Thumbnail (Cover Poster)")
        self.chk_v_meta_subtitles = QCheckBox("Embed Soft Subtitles Stream")
        self.chk_v_meta_chapters = QCheckBox("Embed Video Chapters Markers")

        self.v_tag_checkboxes = {
            'title': self.chk_v_meta_title,
            'channel': self.chk_v_meta_channel,
            'year': self.chk_v_meta_year,
            'thumbnail': self.chk_v_meta_thumbnail,
            'subtitles': self.chk_v_meta_subtitles,
            'chapters': self.chk_v_meta_chapters,
        }

        for k, chk in self.v_tag_checkboxes.items():
            val = stored_v_tags.get(k, True)
            chk.setChecked(val)
            chk.toggled.connect(self._on_v_metadata_tag_toggled)

        v_meta_grid.addWidget(self.chk_v_meta_title, 0, 0)
        v_meta_grid.addWidget(self.chk_v_meta_channel, 0, 1)
        v_meta_grid.addWidget(self.chk_v_meta_year, 1, 0)
        v_meta_grid.addWidget(self.chk_v_meta_thumbnail, 1, 1)
        v_meta_grid.addWidget(self.chk_v_meta_subtitles, 2, 0)
        v_meta_grid.addWidget(self.chk_v_meta_chapters, 2, 1)

        video_layout.addWidget(self.v_meta_tags_widget)
        self.chk_embed_all_v_meta.toggled.connect(self._on_embed_all_v_meta_toggled)
        self._update_v_meta_checkboxes_state(is_embed_all_v)

        layout.addWidget(video_group)

        # 5. Core Engine & Updates
        lbl_core = QLabel("Core Engine")
        lbl_core.setStyleSheet("font-weight: bold; color: #94a3b8; margin-top: 8px; margin-bottom: 2px;")
        layout.addWidget(lbl_core)
        core_layout = QHBoxLayout()
        btn_check_update = QPushButton("Check for yt-dlp Updates")
        btn_check_update.clicked.connect(self.manual_check_ytdlp_update)
        core_layout.addWidget(btn_check_update)
        core_layout.addSpacing(20)
        self.chk_auto_update = QCheckBox("Check updates on startup")
        self.chk_auto_update.setChecked(self.settings.get('check_ytdlp_updates_on_startup', True))
        self.chk_auto_update.toggled.connect(lambda c: self.settings.set('check_ytdlp_updates_on_startup', c))
        core_layout.addWidget(self.chk_auto_update)
        core_layout.addStretch()
        layout.addLayout(core_layout)

        # 6. Quality Settings
        lbl_quality = QLabel("Quality Settings")
        lbl_quality.setStyleSheet("font-weight: bold; color: #94a3b8; margin-top: 8px; margin-bottom: 2px;")
        layout.addWidget(lbl_quality)
        quality_grid = QGridLayout()
        quality_grid.setHorizontalSpacing(20)
        quality_grid.setVerticalSpacing(8)

        platforms = [
            ("YouTube", ["Best video", "Audio only (MP3)", "144p", "240p", "360p", "480p", "720p (HD)", "1080p (Full HD)", "1440p (2K)", "2160p (4K)"]),
            ("Twitch", ["Source (Best)", "1080p", "720p", "480p", "360p", "160p", "Audio only (MP3)"]),
            ("SoundCloud", ["Best Audio", "Worst Audio"]),
            ("Spotify", ["Best Audio", "Worst Audio"]),
            ("Facebook", ["Best video", "1080p", "720p", "480p", "360p", "240p", "Audio only (MP3)"]),
            ("Instagram", ["Best video", "1080p", "720p", "Audio only (MP3)"]),
            ("Twitter (X)", ["Best video", "1080p", "720p", "480p", "Audio only (MP3)"]),
            ("TikTok", ["Best video", "1080p", "720p", "Audio only (MP3)"])
        ]

        for i, (plat, options) in enumerate(platforms):
            quality_grid.addWidget(QLabel(plat + ":"), i // 2, (i % 2) * 3)
            combo = make_combo(options)
            combo.setCurrentText(self.settings.get_quality(plat))
            combo.currentTextChanged.connect(lambda t, p=plat: self.settings.set_quality(p, t))
            quality_grid.addWidget(combo, i // 2, (i % 2) * 3 + 1)
            quality_grid.setColumnStretch((i % 2) * 3 + 2, 1)

        layout.addLayout(quality_grid)

        # 7. YouTube Authentication (Cookies)
        lbl_cookies = QLabel("YouTube Authentication & Cookies")
        lbl_cookies.setStyleSheet("font-weight: bold; color: #94a3b8; margin-top: 10px; margin-bottom: 2px;")
        layout.addWidget(lbl_cookies)

        cookies_group = QWidget()
        cookies_layout = QVBoxLayout(cookies_group)
        cookies_layout.setContentsMargins(15, 12, 15, 12)
        cookies_layout.setSpacing(10)
        cookies_group.setStyleSheet("""
            QWidget#CookiesGroup {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        cookies_group.setObjectName("CookiesGroup")

        cookies_desc = QLabel(
            "Use your exported cookies.txt file or browser session to download age-restricted (18+), "
            "private, and high-quality YouTube Music tracks without errors."
        )
        cookies_desc.setWordWrap(True)
        cookies_desc.setStyleSheet("font-size: 12px; color: #94a3b8; line-height: 1.4;")
        cookies_layout.addWidget(cookies_desc)

        # Source Selection (None / File cookies.txt / Browser)
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Cookies Source:"))
        self.cookies_source_combo = make_combo()
        self.cookies_source_combo.addItem("Disabled (None)", "none")
        self.cookies_source_combo.addItem("Cookies File (cookies.txt - Recommended)", "file")
        self.cookies_source_combo.addItem("Direct from Browser (Auto)", "browser")

        current_source = self.settings.get('cookies_source', 'none')
        idx = self.cookies_source_combo.findData(current_source)
        if idx >= 0:
            self.cookies_source_combo.setCurrentIndex(idx)
        else:
            self.cookies_source_combo.setCurrentIndex(0)
        source_row.addWidget(self.cookies_source_combo, 1)
        cookies_layout.addLayout(source_row)

        # File Chooser Row (visible when 'file' is selected)
        self.cookies_file_widget = QWidget()
        file_widget_layout = QVBoxLayout(self.cookies_file_widget)
        file_widget_layout.setContentsMargins(0, 0, 0, 0)
        file_widget_layout.setSpacing(8)

        file_row = QHBoxLayout()
        file_row.setContentsMargins(0, 0, 0, 0)
        self.cookies_file_input = QLineEdit(self.settings.get('cookies_file', ''))
        self.cookies_file_input.setPlaceholderText("Select your exported cookies.txt file...")
        self.cookies_file_input.setReadOnly(True)
        btn_browse_cookie = QPushButton("Browse...")
        btn_browse_cookie.setFixedWidth(90)
        btn_browse_cookie.clicked.connect(self.browse_cookies_file)
        btn_clear_cookie = QPushButton("Clear")
        btn_clear_cookie.setFixedWidth(70)
        btn_clear_cookie.clicked.connect(self.clear_cookies_file)
        file_row.addWidget(QLabel("File Path:"))
        file_row.addWidget(self.cookies_file_input)
        file_row.addWidget(btn_browse_cookie)
        file_row.addWidget(btn_clear_cookie)
        file_widget_layout.addLayout(file_row)

        file_instructions = QLabel(
            "<b>📋 Step-by-Step Guide to Exporting cookies.txt:</b><br>"
            "1. Install a browser extension (e.g. <b>Get cookies.txt LOCALLY</b> or <b>Cookie-Editor</b> for Chrome / Firefox / Edge / Opera).<br>"
            "2. Open <a href='https://music.youtube.com' style='color: #38bdf8;'>music.youtube.com</a> or <a href='https://youtube.com' style='color: #38bdf8;'>youtube.com</a> and make sure you are logged into your Google account.<br>"
            "3. Click the extension icon in your browser toolbar and click <b>Export</b> (in <i>Netscape HTTP Cookie File</i> format).<br>"
            "4. Save the file (e.g. <code>music.youtube.com_cookies.txt</code>) on your computer.<br>"
            "5. Click <b>Browse...</b> above and select the saved file."
        )
        file_instructions.setOpenExternalLinks(True)
        file_instructions.setWordWrap(True)
        file_instructions.setStyleSheet("""
            background-color: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 10px 12px;
            font-size: 11px;
            color: #cbd5e1;
            line-height: 1.5;
        """)
        file_widget_layout.addWidget(file_instructions)
        cookies_layout.addWidget(self.cookies_file_widget)

        # Browser Chooser Row (visible when 'browser' is selected)
        self.cookies_browser_widget = QWidget()
        browser_widget_layout = QVBoxLayout(self.cookies_browser_widget)
        browser_widget_layout.setContentsMargins(0, 0, 0, 0)
        browser_widget_layout.setSpacing(8)

        b_row = QHBoxLayout()
        b_row.setContentsMargins(0, 0, 0, 0)
        b_row.addWidget(QLabel("Browser:"))
        self.cookies_browser_combo = make_combo(["Firefox", "Opera", "Chrome", "Edge", "Brave", "Vivaldi"])
        self.cookies_browser_combo.setCurrentText(self.settings.get('cookies_browser', 'Firefox').capitalize())
        self.cookies_browser_combo.currentTextChanged.connect(lambda b: self.settings.set('cookies_browser', b.lower()))
        b_row.addWidget(self.cookies_browser_combo, 1)
        browser_widget_layout.addLayout(b_row)

        browser_warning = QLabel(
            "<b>⚠️ Direct Browser Import Restriction:</b><br>"
            "In modern versions of Windows and Chromium-based browsers (Google Chrome, Microsoft Edge, Opera, Brave, Vivaldi, etc.), direct cookie reading is blocked by system-level <b>App-Bound Encryption (DPAPI)</b> data protection.<br><br>"
            "Direct cookie extraction is only supported for <b>Firefox</b>-based browsers, but this mode is experimental and has not been extensively tested.<br><br>"
            "💡 <b>Recommendation:</b> Use the <b>«Cookies File (cookies.txt)»</b> mode — it is 100% reliable, safe, and fully supports YouTube Premium."
        )
        browser_warning.setWordWrap(True)
        browser_warning.setStyleSheet("""
            background-color: #0f172a;
            border: 1px solid #ef4444;
            border-radius: 6px;
            padding: 10px 12px;
            font-size: 11px;
            color: #fca5a5;
            line-height: 1.5;
        """)
        browser_widget_layout.addWidget(browser_warning)
        cookies_layout.addWidget(self.cookies_browser_widget)

        def _update_cookies_ui_state():
            src = self.cookies_source_combo.currentData()
            self.settings.set('cookies_source', src)
            self.cookies_file_widget.setVisible(src == 'file')
            self.cookies_browser_widget.setVisible(src == 'browser')

        self.cookies_source_combo.currentIndexChanged.connect(_update_cookies_ui_state)
        _update_cookies_ui_state()

        layout.addWidget(cookies_group)
        layout.addStretch()

        scroll.setWidget(scroll_wrapper)
        main_tab_layout = QVBoxLayout(self.settings_tab)
        main_tab_layout.setContentsMargins(0, 0, 0, 0)
        main_tab_layout.addWidget(scroll)
        self.tabs.addTab(self.settings_tab, "SETTINGS")

    def browse_cookies_file(self):
        initial_dir = self.settings.get('last_selected_folder') or str(Path.home())
        file, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt file", initial_dir, "Text Files (*.txt);;All Files (*)")
        if file:
            self.cookies_file_input.setText(file)
            self.settings.set('cookies_file', file)
            self.settings.set('cookies_source', 'file')
            idx = self.cookies_source_combo.findData('file')
            if idx >= 0:
                self.cookies_source_combo.setCurrentIndex(idx)
            QMessageBox.information(self, "Cookies Loaded", f"Successfully loaded cookies file:\n{Path(file).name}")

    def clear_cookies_file(self):
        self.cookies_file_input.clear()
        self.settings.set('cookies_file', '')
        self.settings.set('cookies_source', 'none')
        self.cookies_source_combo.setCurrentIndex(0)

    def get_cookies_config(self):
        cookies_source = self.settings.get('cookies_source', 'none')
        if cookies_source == 'file':
            c_file = self.settings.get('cookies_file')
            if c_file and os.path.exists(c_file):
                return {'use': True, 'source': 'file', 'file': c_file}
        elif cookies_source == 'browser':
            b_name = self.settings.get('cookies_browser', 'opera').lower()
            return {'use': True, 'source': 'browser', 'browser': b_name}
        return None

    def insert_naming_token(self, token: str):
        text = self.naming_input.text()
        self.naming_input.setText(text + token)

    def reset_naming_pattern(self):
        default_pattern = "{artist} - {title}"
        self.naming_input.setText(default_pattern)
        self.settings.set('naming_pattern', default_pattern)

    def _on_embed_all_meta_toggled(self, checked: bool):
        self.settings.set('embed_all_metadata', checked)
        self._update_meta_checkboxes_state(checked)

    def _update_meta_checkboxes_state(self, embed_all: bool):
        for k, chk in getattr(self, 'tag_checkboxes', {}).items():
            if embed_all:
                chk.blockSignals(True)
                chk.setChecked(True)
                chk.blockSignals(False)
                chk.setEnabled(False)
            else:
                stored = (self.settings.get('audio_metadata_tags') or {}).get(k, True)
                chk.blockSignals(True)
                chk.setChecked(stored)
                chk.blockSignals(False)
                chk.setEnabled(True)

    def _on_metadata_tag_toggled(self):
        if not self.chk_embed_all_meta.isChecked():
            current_tags = {k: chk.isChecked() for k, chk in self.tag_checkboxes.items()}
            self.settings.set('audio_metadata_tags', current_tags)

    def insert_video_naming_token(self, token: str):
        text = self.v_naming_input.text()
        self.v_naming_input.setText(text + token)

    def reset_video_naming_pattern(self):
        default_pattern = "{title}"
        self.v_naming_input.setText(default_pattern)
        self.settings.set('video_naming_pattern', default_pattern)

    def _on_embed_all_v_meta_toggled(self, checked: bool):
        self.settings.set('embed_all_video_metadata', checked)
        self._update_v_meta_checkboxes_state(checked)

    def _update_v_meta_checkboxes_state(self, embed_all: bool):
        for k, chk in getattr(self, 'v_tag_checkboxes', {}).items():
            if embed_all:
                chk.blockSignals(True)
                chk.setChecked(True)
                chk.blockSignals(False)
                chk.setEnabled(False)
            else:
                stored = (self.settings.get('video_metadata_tags') or {}).get(k, True)
                chk.blockSignals(True)
                chk.setChecked(stored)
                chk.blockSignals(False)
                chk.setEnabled(True)

    def _on_v_metadata_tag_toggled(self):
        if not self.chk_embed_all_v_meta.isChecked():
            current_tags = {k: chk.isChecked() for k, chk in self.v_tag_checkboxes.items()}
            self.settings.set('video_metadata_tags', current_tags)

    # ─── TAB 5: ABOUT ──────────────────────────────────────────────────────────

    def setup_about_tab(self):
        self.about_tab = QWidget()
        layout = QVBoxLayout(self.about_tab)
        layout.addStretch()
        title = QLabel("Logovo Downloads")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        version = QLabel("Version: 1.5.0")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)
        btn_layout = QHBoxLayout()
        github = QPushButton("GitHub Repository")
        github.setMinimumWidth(200)
        github.setMaximumWidth(250)
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Helvior-dev/Logovo-Downloads")))
        btn_layout.addStretch()
        btn_layout.addWidget(github)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()
        self.tabs.addTab(self.about_tab, "ABOUT")

    # ─── UPDATER METHODS ───────────────────────────────────────────────────────

    def on_startup_update_check_result(self, has_update: bool, current_ver: str, latest_ver: str):
        if has_update:
            reply = QMessageBox.question(
                self,
                "yt-dlp Core Update Available",
                f"A newer version of the yt-dlp downloader core is available.\n\n"
                f"Current Version: {current_ver}\n"
                f"Latest Version: {latest_ver}\n\n"
                "Would you like to upgrade the downloader core now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.run_ytdlp_upgrade()

    def manual_check_ytdlp_update(self):
        self.status_label.setText("Checking for yt-dlp core updates...")
        QApplication.processEvents()
        has_update, cur_v, lat_v = check_latest_ytdlp_version()
        if has_update:
            reply = QMessageBox.question(
                self,
                "Update Available",
                f"New yt-dlp core version available!\n\nCurrent: {cur_v}\nLatest: {lat_v}\n\nUpgrade now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.run_ytdlp_upgrade()
        else:
            QMessageBox.information(self, "Up to Date", f"The yt-dlp downloader core is up to date (v{cur_v}).")
            self.status_label.setText("Downloader core is up to date.")

    def run_ytdlp_upgrade(self):
        self.status_label.setText("Upgrading yt-dlp core in background...")
        self.upgrade_worker = UpgradeWorker()
        self.upgrade_worker.finished_signal.connect(self.on_upgrade_finished)
        self.upgrade_worker.start()

    def on_upgrade_finished(self, success: bool, msg: str):
        if success:
            new_v = get_installed_ytdlp_version()
            self.lbl_ytdlp_ver.setText(f"Current Core Version: <b>{new_v}</b>")
            QMessageBox.information(self, "Upgrade Complete", f"yt-dlp core successfully upgraded to v{new_v}!")
            self.status_label.setText("Core upgrade completed successfully.")
        else:
            QMessageBox.warning(self, "Upgrade Failed", f"Failed to upgrade yt-dlp core:\n\n{msg}")
            self.status_label.setText("Core upgrade failed.")

    # ─── ACTIONS & QUEUE ENGINE ────────────────────────────────────────────────

    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text())

    def load_from_file(self):
        selected_type = self.format_combo.currentText()
        if not selected_type or selected_type == "Select Type...":
            self.highlight_format_combo()
            QMessageBox.warning(
                self, 
                "Select Type", 
                "Please select 'Audio' or 'Video' in the Type selector (highlighted in blue) before loading links from file."
            )
            return

        file, _ = QFileDialog.getOpenFileName(self, "Select text file with links", "", "Text Files (*.txt);;All Files (*)")
        if file:
            try:
                with open(file, 'r', encoding='utf-8') as f:
                    links = [line.strip() for line in f.readlines() if line.strip()]

                for link in links:
                    if link:
                        self._add_single_item_to_queue({
                            'url': link,
                            'title': link, 
                            'media_type_category': selected_type,
                            'media_type': "Audio (Best)" if selected_type == "Audio" else "Video (Best)"
                        })
                self.status_label.setText("Added links from file.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to read file: {e}")

    def clear_queue(self):
        for widget in list(self.download_queue):
            if widget.status_state != "Downloading":
                if hasattr(self, '_queue_url_set'):
                    self._queue_url_set.discard((widget.item_data.get('url'), widget.item_data.get('media_type')))
                self.queue_container_layout.removeWidget(widget)
                widget.deleteLater()
                self.download_queue.remove(widget)
        self.update_queue_ui()
        self._update_taskbar_progress()
        self.status_label.setText("Queue cleared (except active downloads).")

    def clear_completed(self):
        for widget in list(self.download_queue):
            if widget.status_state in ["Success", "Error"]:
                if hasattr(self, '_queue_url_set'):
                    self._queue_url_set.discard((widget.item_data.get('url'), widget.item_data.get('media_type')))
                self.queue_container_layout.removeWidget(widget)
                widget.deleteLater()
                self.download_queue.remove(widget)
        self.update_queue_ui()
        self._update_taskbar_progress()
        self.status_label.setText("Completed items removed from queue.")

    def open_downloads_folder(self):
        folder = self.settings.get('download_path')
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def browse_folder(self):
        initial_dir = self.settings.get('last_selected_folder') or self.settings.get('download_path')
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory", initial_dir)
        if folder:
            self.folder_input.setText(folder)
            self.settings.set('download_path', folder)
            self.settings.set('last_selected_folder', folder)

    def toggle_subs_setting(self, checked):
        self.settings.set('download_subtitles', checked)
        if hasattr(self, 'video_subs_lang_combo'):
            self.video_subs_lang_combo.setEnabled(checked)
        if hasattr(self, 'lbl_video_subs_lang'):
            self.lbl_video_subs_lang.setEnabled(checked)
        self.update_main_subs_combo_state()
        self.refresh_queue_items_subs()

    def toggle_audio_lyrics_setting(self, checked):
        self.settings.set('download_audio_lyrics', checked)
        if hasattr(self, 'audio_lyrics_lang_combo'):
            self.audio_lyrics_lang_combo.setEnabled(checked)
        if hasattr(self, 'lbl_lyrics_lang'):
            self.lbl_lyrics_lang.setEnabled(checked)
        self.update_main_subs_combo_state()
        self.refresh_queue_items_subs()

    def on_main_format_combo_changed(self, idx):
        self.clear_format_combo_highlight()
        self.update_main_subs_combo_state()
        new_type = self.format_combo.currentText()
        if new_type in ("Audio", "Video"):
            for widget in self.download_queue:
                if widget.status_state == "Pending":
                    if new_type == "Audio":
                        widget.format_combo.setCurrentText("Audio (Best)")
                    else:
                        widget.format_combo.setCurrentText("Video (Best)")

    def update_main_subs_combo_state(self):
        current_type = self.format_combo.currentText()
        if current_type == "Audio":
            is_enabled = self.settings.get('download_audio_lyrics', False)
        elif current_type == "Video":
            is_enabled = self.settings.get('download_subtitles', False)
        else:
            is_enabled = self.settings.get('download_subtitles', False) or self.settings.get('download_audio_lyrics', False)

        self.subs_combo.setEnabled(is_enabled)
        if hasattr(self, 'lbl_main_subs'):
            self.lbl_main_subs.setEnabled(is_enabled)
        if not is_enabled:
            self.subs_combo.setCurrentText("None")

    def refresh_queue_items_subs(self):
        for widget in self.download_queue:
            if hasattr(widget, '_populate_subs_combo'):
                widget._populate_subs_combo()

    def refresh_history(self):
        entries = self.history.get_all()
        self.history_table.setRowCount(len(entries))
        completed = 0
        errors = 0

        for i, entry in enumerate(entries):
            item_date = QTableWidgetItem(entry.get('timestamp', ''))
            item_author = QTableWidgetItem(entry.get('author', 'Unknown'))
            item_title = QTableWidgetItem(entry.get('title', 'Unknown'))
            item_plat = QTableWidgetItem(entry.get('platform', 'Unknown'))
            status = entry.get('status', 'Unknown')
            item_status = QTableWidgetItem(status)

            if status in ["Completed", "Success"]:
                completed += 1
                item_status.setForeground(QColor("#10b981"))
            elif "Error" in status:
                errors += 1
                item_status.setForeground(QColor("#ef4444"))
            elif status == "Skipped":
                item_status.setForeground(QColor("#94a3b8"))

            self.history_table.setItem(i, 0, item_date)
            self.history_table.setItem(i, 1, item_author)
            self.history_table.setItem(i, 2, item_title)
            self.history_table.setItem(i, 3, item_plat)
            self.history_table.setItem(i, 4, item_status)

        self.history_stats_label.setText(f"Total: {len(entries)} | Completed: {completed} | Errors: {errors}")

    def clear_history(self):
        self.history.clear()
        self.refresh_history()

    def highlight_format_combo(self):
        if hasattr(self, '_pulse_timer') and self._pulse_timer.isActive():
            self._pulse_timer.stop()

        shadow = QGraphicsDropShadowEffect(self.format_combo)
        shadow.setColor(QColor(56, 189, 248, 220))
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 0)
        self.format_combo.setGraphicsEffect(shadow)

        self._pulse_step = 0
        self._pulse_timer = QTimer(self)

        def do_pulse():
            import math
            self._pulse_step += 1
            t = (math.sin(self._pulse_step * 0.3) + 1.0) / 2.0
            alpha = int(120 + 135 * t)
            radius = int(8 + 14 * t)
            shadow.setColor(QColor(56, 189, 248, alpha))
            shadow.setBlurRadius(radius)

            self.format_combo.setStyleSheet("""
                QComboBox {
                    background-color: #1e293b;
                    border: 2px solid #38bdf8;
                    color: #38bdf8;
                    font-weight: bold;
                    border-radius: 6px;
                }
            """)

            if self._pulse_step >= 24:
                self._pulse_timer.stop()
                self.format_combo.setGraphicsEffect(None)
                self.format_combo.setStyleSheet("""
                    QComboBox {
                        background-color: #1e293b;
                        border: 2px solid #38bdf8;
                        color: #38bdf8;
                        font-weight: bold;
                        border-radius: 6px;
                    }
                """)

        self._pulse_timer.timeout.connect(do_pulse)
        self._pulse_timer.start(50)

    def clear_format_combo_highlight(self):
        if hasattr(self, '_pulse_timer') and self._pulse_timer.isActive():
            self._pulse_timer.stop()
        self.format_combo.setGraphicsEffect(None)
        self.format_combo.setStyleSheet("")

    def add_to_queue_action(self):
        url = self.url_input.text().strip()
        if not url:
            return

        selected_type = self.format_combo.currentText()
        if not selected_type or selected_type == "Select Type...":
            self.highlight_format_combo()
            QMessageBox.warning(
                self, 
                "Select Type", 
                "Please select 'Audio' or 'Video' in the Type selector (highlighted in blue) before adding to queue."
            )
            return

        self.status_label.setText("Fetching info in background...")
        self.btn_add_queue.setEnabled(False)
        self.loading_overlay.show_loading("Fetching Media Info...", "Connecting to YouTube...")

        worker = FetchPreviewWorker(url, context={'url': url, 'selected_type': selected_type}, cookies=self.get_cookies_config())
        worker.finished_signal.connect(self._on_queue_preview_ready)
        worker.error_signal.connect(lambda err, ctx: self._on_queue_preview_error(err))
        if not hasattr(self, '_preview_workers'):
            self._preview_workers = []
        self._preview_workers.append(worker)
        worker.finished.connect(lambda: self._preview_workers.remove(worker) if worker in self._preview_workers else None)
        worker.start()

    def _on_queue_preview_error(self, err_msg: str):
        self.loading_overlay.hide_loading()
        self.status_label.setText("Error fetching info.")
        self.btn_add_queue.setEnabled(True)

    def _on_queue_preview_ready(self, preview: dict, ctx: dict):
        self.loading_overlay.hide_loading()
        self.btn_add_queue.setEnabled(True)
        url = ctx.get('url')
        selected_type = ctx.get('selected_type')

        if preview:
            if preview.get('is_playlist'):
                count = preview.get('count', 0)
                playlist_title = preview.get('title', 'Playlist')
                for ch in r'\/:*?"<>|':
                    playlist_title = playlist_title.replace(ch, '_').strip()
                global_path = self.settings.get('download_path')
                default_path = os.path.join(global_path, playlist_title)

                msgBox = QMessageBox(self)
                msgBox.setWindowTitle("Playlist Destination")
                msgBox.setText(
                    f"<h3>Playlist: {preview.get('title', 'Playlist')}</h3>"
                    f"Total tracks found: <b>{count}</b><br><br>"
                    "Where would you like to save this playlist?"
                )
                btn_auto_new = msgBox.addButton(f"Save to '{playlist_title}' in Downloads", QMessageBox.ButtonRole.YesRole)
                btn_custom_new = msgBox.addButton("Choose Custom Folder...", QMessageBox.ButtonRole.ActionRole)
                btn_sync = msgBox.addButton("Sync into Existing Playlist Folder...", QMessageBox.ButtonRole.AcceptRole)
                btn_cancel = msgBox.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                msgBox.setDefaultButton(btn_auto_new)
                msgBox.exec()

                clicked_btn = msgBox.clickedButton()
                if clicked_btn == btn_cancel:
                    self.status_label.setText("Playlist addition cancelled.")
                    return

                cover_mode = self.settings.get('playlist_cover_mode') or 'both'
                playlist_thumb = preview.get('thumbnail')

                initial_dir = self.settings.get('last_selected_folder') or global_path

                if clicked_btn == btn_auto_new:
                    out_dir = default_path
                    if not os.path.exists(out_dir):
                        os.makedirs(out_dir, exist_ok=True)
                    if playlist_thumb and cover_mode != 'none':
                        apply_playlist_cover_settings(out_dir, playlist_thumb, mode=cover_mode)

                elif clicked_btn == btn_custom_new:
                    chosen = QFileDialog.getExistingDirectory(self, "Select Save Folder for Playlist", initial_dir)
                    if not chosen:
                        self.status_label.setText("Playlist addition cancelled.")
                        return
                    self.settings.set('last_selected_folder', chosen)
                    chosen_p = Path(chosen).resolve()
                    if chosen_p.name.lower() == playlist_title.lower():
                        out_dir = str(chosen_p)
                    else:
                        out_dir = str(chosen_p / playlist_title)
                    if not os.path.exists(out_dir):
                        os.makedirs(out_dir, exist_ok=True)
                    if playlist_thumb and cover_mode != 'none':
                        apply_playlist_cover_settings(out_dir, playlist_thumb, mode=cover_mode)

                else:
                    # Sync existing folder mode
                    out_dir = QFileDialog.getExistingDirectory(self, "Select Existing Playlist Folder", initial_dir)
                    if not out_dir:
                        self.status_label.setText("Playlist addition cancelled.")
                        return
                    self.settings.set('last_selected_folder', out_dir)

                    # Restore timestamps & detect orphans with interactive details dialog
                    restored = restore_dates_from_order(out_dir)
                    if restored > 0:
                        self.status_label.setText(f"Restored order for {restored} existing tracks.")

                    detect_and_prompt_orphans(self, out_dir, preview)

                # Cleanup orphan files and leftover raw .mp4 before batch adding
                cleanup_orphan_files(out_dir, is_audio_playlist=(selected_type == "Audio"))

                # Re-index existing tracks so numbers 1..N match current playlist count without gaps
                reindex_existing_playlist_files(out_dir, preview.get('entries', []))

                # Auto-clear previous completed/finished queue if not currently downloading
                if self.download_queue and not self.is_downloading:
                    all_done = all(w.status_state in ("Success", "Error", "Unavailable", "Completed", "Finished") for w in self.download_queue)
                    if all_done:
                        self.clear_queue()

                # Add tracks with batch speed optimization
                added_count = 0
                self.queue_container.setUpdatesEnabled(False)
                for i, entry in enumerate(preview.get('entries', [])):
                    entry['playlist_output_dir'] = out_dir
                    entry['playlist_index'] = count - i
                    entry['playlist_count'] = count
                    entry['media_type_category'] = selected_type
                    entry['media_type'] = "Audio (Best)" if selected_type == "Audio" else "Video (Best)"

                    vid = entry.get('url', '').split('v=')[-1].split('&')[0]
                    author = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ""
                    title = entry.get('title') or ""
                    if vid and title:
                        stem = f"{title} - {author}".strip(" -")
                        update_stem_vid_map(out_dir, stem, vid)

                    self._add_single_item_to_queue(entry, batch=True)
                    added_count += 1

                self.queue_container.setUpdatesEnabled(True)
                self.update_queue_ui()
                self.status_label.setText(f"Added {added_count} tracks from playlist.")
            else:
                preview['url'] = url
                preview['media_type_category'] = selected_type
                preview['media_type'] = "Audio (Best)" if selected_type == "Audio" else "Video (Best)"
                self._add_single_item_to_queue(preview)
                self.status_label.setText("Added to queue.")
        else:
            self.status_label.setText("Error fetching info.")

        self.btn_add_queue.setEnabled(True)

    def _add_single_item_to_queue(self, info_dict, batch=False):
        url = info_dict.get('url')
        selected_category = info_dict.get('media_type_category') or self.format_combo.currentText()
        if selected_category not in ("Audio", "Video"):
            selected_category = "Audio"

        info_dict['media_type_category'] = selected_category
        if not info_dict.get('media_type'):
            info_dict['media_type'] = "Audio (Best)" if selected_category == "Audio" else "Video (Best)"
        media_type = info_dict['media_type']

        # Fast O(1) deduplication
        if not hasattr(self, '_queue_url_set'):
            self._queue_url_set = set()
        queue_key = (url, media_type)
        if queue_key in self._queue_url_set:
            return
        self._queue_url_set.add(queue_key)

        chosen_subs = self.subs_combo.currentText()
        if chosen_subs and chosen_subs not in ("Default (Settings)", ""):
            info_dict['specific_subs'] = chosen_subs

        widget = QueueItemWidget(info_dict, settings=self.settings)
        widget.remove_requested.connect(self.remove_queue_item)

        self.queue_container_layout.addWidget(widget)
        self.download_queue.append(widget)
        if not batch:
            self.update_queue_ui()

    def remove_queue_item(self, widget):
        if widget in self.download_queue:
            if hasattr(self, '_queue_url_set'):
                self._queue_url_set.discard((widget.item_data.get('url'), widget.item_data.get('media_type')))
            self.queue_container_layout.removeWidget(widget)
            widget.deleteLater()
            self.download_queue.remove(widget)
            self.update_queue_ui()

    def update_queue_ui(self):
        total = len(self.download_queue)
        success_items = [w for w in self.download_queue if w.status_state == "Success"]
        error_items = [w for w in self.download_queue if w.status_state == "Error"]
        unavail_items = [w for w in self.download_queue if w.status_state == "Unavailable"]
        pending_items = [w for w in self.download_queue if w.status_state in ("Pending", "Downloading", "Retrying")]

        completed_count = len(success_items)
        pending_count = len(pending_items)
        error_count = len(error_items)
        unavail_count = len(unavail_items)

        # Top telemetry text
        if total == 0:
            self.top_telemetry_label.setText("")
        else:
            downloaded_mb = sum(estimate_track_size_mb(w.item_data) for w in success_items)
            total_mb = sum(estimate_track_size_mb(w.item_data) for w in self.download_queue)

            def fmt_mb(mb):
                return f"{mb / 1024:.1f} GB" if mb >= 1024 else f"{mb:.0f} MB"

            size_str = f"{fmt_mb(downloaded_mb)} / {fmt_mb(total_mb)}"

            if pending_count == 0:
                time_str = "Finished"
            else:
                avg_dur = (sum(self.track_durations[-5:]) / len(self.track_durations[-5:])) if self.track_durations else 4.5
                concurrency = max(1, int(self.settings.get('max_concurrent_downloads', 3)))
                eta_s = int((avg_dur * pending_count) / concurrency)
                if eta_s >= 60:
                    time_str = f"~{eta_s // 60}m {eta_s % 60:02d}s"
                else:
                    time_str = f"~{eta_s}s"

            self.top_telemetry_label.setText(
                f"<span style='color: #38bdf8;'>💾 {size_str}</span>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
                f"<span style='color: #fbbf24;'>⏳ {time_str}</span>"
            )

            total_progress = 0
            for w in self.download_queue:
                if w.status_state in ("Success", "Unavailable", "Error"):
                    total_progress += 100
                elif w.status_state == "Downloading":
                    total_progress += w.progress_bar.value()

            if pending_count == 0 and not self.is_downloading:
                self.global_progress.setValue(0)
            else:
                self.global_progress.setValue(int(total_progress / total))

        if unavail_count > 0:
            self.stats_label.setText(f"Success: {completed_count} | Queue: {pending_count} | Errors: {error_count} | Removed: {unavail_count}")
            self.stats_label.setToolTip(f"Success: {completed_count}\nIn queue: {pending_count}\nErrors: {error_count}\nRemoved from platform: {unavail_count}")
        else:
            self.stats_label.setText(f"Success: {completed_count} | Queue: {pending_count} | Errors: {error_count}")
            self.stats_label.setToolTip(f"Success: {completed_count}\nIn queue: {pending_count}\nErrors: {error_count}")

        if pending_count == 0:
            self.btn_download_all.setEnabled(False)
            self.btn_download_all.setText("Download")
        elif pending_count == 1:
            self.btn_download_all.setEnabled(not self.is_downloading)
            self.btn_download_all.setText("Download")
        else:
            self.btn_download_all.setEnabled(not self.is_downloading)
            self.btn_download_all.setText("Download All")

    def start_queue(self):
        if not self.download_queue or self.is_downloading:
            return

        self.is_downloading = True
        self.success_count = 0
        self.error_count = 0
        self.downloaded_count = 0
        self.skipped_count = 0
        self.btn_download_all.setEnabled(False)
        self.btn_stop.setEnabled(True)

        self.process_queue()

    def stop_download(self):
        self.is_downloading = False
        for worker in list(self.active_workers.values()):
            try:
                worker.disconnect()
            except Exception:
                pass
        self.active_workers.clear()
        self.widget_start_times.clear()

        for w in self.download_queue:
            if w.status_state in ("Downloading", "Retrying"):
                w.set_status("Stopped", "Pending")

        self.btn_stop.setEnabled(False)
        self.status_label.setText("Download stopped.")
        self.update_queue_ui()

    def process_queue(self):
        if not self.is_downloading:
            self.update_queue_ui()
            return

        max_concurrency = max(1, int(self.settings.get('max_concurrent_downloads', 3)))

        while len(self.active_workers) < max_concurrency:
            # Find next pending widget not currently being processed
            next_widget = None
            for widget in self.download_queue:
                if widget.status_state == "Pending" and widget not in self.active_workers:
                    next_widget = widget
                    break

            if not next_widget:
                if len(self.active_workers) == 0:
                    # Entire queue finished
                    self.is_downloading = False
                    self.btn_stop.setEnabled(False)
                    self.global_progress.setValue(0)

                    has_errors = bool(self.failed_queue) or any(w.status_state == "Error" for w in self.download_queue)
                    unavail_count = sum(1 for w in self.download_queue if w.status_state == "Unavailable")
                    if has_errors:
                        self.status_label.setText("Finished with errors. Check actions.")
                        if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                            self.tray_icon.showMessage(
                                "Logovo Downloads",
                                "Some downloads finished with errors.",
                                QSystemTrayIcon.MessageIcon.Warning,
                                3500
                            )
                    else:
                        if unavail_count > 0:
                            self.status_label.setText(f"All available downloads finished! ({self.downloaded_count} downloaded, {unavail_count} removed from platform)")
                        else:
                            self.status_label.setText("All downloads finished successfully!")
                        if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                            if self.downloaded_count > 0 and self.skipped_count > 0:
                                msg = f"All downloads completed ({self.downloaded_count} downloaded, {self.skipped_count} skipped)!"
                            elif self.downloaded_count > 0:
                                msg = f"All downloads completed ({self.downloaded_count} succeeded)!"
                            else:
                                msg = f"All downloads completed ({self.success_count} checked)!"
                            self.tray_icon.showMessage(
                                "Logovo Downloads",
                                msg,
                                QSystemTrayIcon.MessageIcon.Information,
                                3500
                            )
                    # Clean up orphan .webp/.tmp files & failed_downloads.txt across output dirs
                    dirs_to_clean = set()
                    for w in self.download_queue:
                        p_dir = w.item_data.get('playlist_output_dir') or self.settings.get('download_path')
                        if p_dir: dirs_to_clean.add(p_dir)
                    for d in dirs_to_clean:
                        cleanup_orphan_files(d)
                        clear_failed_log_if_clean(d)

                    self.update_queue_ui()
                    self.refresh_playlists_ui()
                    if getattr(self, 'unavailable_queue', None):
                        self.show_unavailable_summary()
                    if getattr(self, 'failed_queue', None):
                        self.show_failed_summary()

                    # Trigger Post-Download Action (Shutdown / Sleep)
                    self.check_post_download_action()
                break

            # Start worker for next_widget
            self.start_worker_for_widget(next_widget)
            time.sleep(0.2) # Jitter delay between concurrent worker starts

    def start_worker_for_widget(self, widget: QueueItemWidget):
        item_data = widget.item_data
        url = item_data['url']
        media_type = item_data['media_type']
        output_dir = item_data.get('playlist_output_dir') or self.settings.get('download_path')

        platform = "YouTube"
        if "twitch.tv" in url: platform = "Twitch"
        elif "soundcloud.com" in url: platform = "SoundCloud"
        elif "spotify.com" in url: platform = "Spotify"
        elif "facebook.com" in url or "fb.watch" in url: platform = "Facebook"
        elif "instagram.com" in url: platform = "Instagram"
        elif "twitter.com" in url or "x.com" in url: platform = "Twitter (X)"
        elif "tiktok.com" in url: platform = "TikTok"

        quality = self.settings.get_quality(platform)
        
        is_audio = media_type.startswith("Audio")
        global_subs_enabled = self.settings.get('download_audio_lyrics', False) if is_audio else self.settings.get('download_subtitles', False)
        global_subs_lang = self.settings.get('lyrics_langs', 'orig') if is_audio else self.settings.get('subtitles_langs', 'orig')

        specific_subs = item_data.get('specific_subs')
        if not specific_subs or specific_subs in ('Default', 'Global', 'Default (Settings)'):
            subtitles_cfg = {
                'download': global_subs_enabled,
                'langs': global_subs_lang
            }
        elif specific_subs in ('None', 'none', 'Disabled', 'No Lyrics', 'No Subs'):
            subtitles_cfg = {'download': False, 'langs': 'none'}
        else:
            subtitles_cfg = {'download': True, 'langs': specific_subs}

        # Check cookies
        cookies_source = self.settings.get('cookies_source', 'none')
        if cookies_source == 'browser':
            cookies = {'use': True, 'source': 'browser', 'browser': self.settings.get('cookies_browser', 'chrome').lower()}
        elif cookies_source == 'file':
            cookies = {'use': True, 'source': 'file', 'file': self.settings.get('cookies_file')}
        else:
            cookies = None

        speed_limit = self.settings.get('speed_limit', 'Unlimited')
        naming_pattern = self.settings.get('audio_naming_pattern', '{artist} - {title}') if is_audio else self.settings.get('video_naming_pattern', '{title}')

        thread = WorkerThread(
            url=url,
            media_type=media_type,
            output_dir=output_dir,
            quality=quality,
            cookies=cookies,
            subtitles=subtitles_cfg,
            playlist_index=item_data.get('playlist_index'),
            playlist_count=item_data.get('playlist_count'),
            title=item_data.get('title'),
            author=item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or item_data.get('author'),
            speed_limit=speed_limit,
            naming_pattern=naming_pattern,
            settings=self.settings,
            thumbnail=item_data.get('thumbnail')
        )

        self.widget_start_times[widget] = time.time()
        self.active_workers[widget] = thread
        thread.progress_signal.connect(lambda d, w=widget: self.update_widget_progress(w, d))
        thread.finished_signal.connect(lambda s, e, sk, w=widget: self.task_finished(w, s, e, sk))
        thread.start()
        self.update_queue_ui()

    def _update_taskbar_progress(self):
        if not self.download_queue:
            taskbar_manager.clear(int(self.winId()))
            return
        total = len(self.download_queue)
        finished = sum(1 for w in self.download_queue if w.status_state in ("Success", "Completed", "Finished", "Skipped", "Unavailable", "Error"))
        active_progress = 0.0
        for w in self.download_queue:
            if w.status_state == "Downloading":
                try:
                    active_progress += float(w.progress_bar.value()) / 100.0
                except Exception:
                    pass
        if finished >= total:
            taskbar_manager.clear(int(self.winId()))
        else:
            overall = int((finished + active_progress) / max(total, 1) * 100.0)
            taskbar_manager.set_progress(int(self.winId()), overall, 100)

    def update_widget_progress(self, widget: QueueItemWidget, d: dict):
        if widget not in self.download_queue:
            return

        if d['status'] == 'downloading':
            msg = d.get('msg')
            if msg:
                widget.set_status(msg, "Downloading")
                return
            percent_str = d.get('_percent_str', '0.0%').replace('%', '').strip()
            percent_clean = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
            speed_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_speed_str', 'N/A')).strip()
            eta_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_eta_str', 'Unknown')).strip()

            widget.update_progress(percent_clean, speed_clean, eta_clean)
            self._update_taskbar_progress()
        elif d['status'] == 'finished':
            widget.set_status("Post-processing...", "Downloading")

    def task_finished(self, widget: QueueItemWidget, success: bool, error_msg: str = "", was_skipped: bool = False):
        # Remove from active workers
        if widget in self.active_workers:
            del self.active_workers[widget]

        # Calculate duration for dynamic ETA estimation
        start_t = self.widget_start_times.pop(widget, None)
        if start_t and not was_skipped and success:
            dur = time.time() - start_t
            if dur > 0.4:
                self.track_durations.append(dur)

        item_data = widget.item_data
        title = item_data.get('title', 'Unknown')
        author = item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or 'Unknown'
        url = item_data.get('url', '')
        platform = "YouTube"
        if "twitch.tv" in url: platform = "Twitch"
        elif "soundcloud.com" in url: platform = "SoundCloud"
        elif "spotify.com" in url: platform = "Spotify"

        if success:
            widget.is_retry = False
            self.success_count += 1
            if was_skipped:
                self.skipped_count += 1
                widget.set_status("Skipped / Already downloaded", "Success")
                status_text = "Skipped"
            else:
                self.downloaded_count += 1
                widget.set_status("Finished", "Success")
                status_text = "Completed"
        else:
            self.error_count += 1
            if is_platform_unavailable(error_msg):
                widget.set_status("Deleted from platform", "Unavailable")
                status_text = "Deleted from platform"
                self.unavailable_queue.append((item_data, error_msg))
            else:
                friendly = friendly_error(error_msg)
                widget.set_status("Error", "Error")
                self.failed_queue.append((item_data, error_msg))
                status_text = f"Error: {friendly}"
            # Log to app_logs.txt and playlist failed_downloads.txt
            out_dir = item_data.get('playlist_output_dir') or self.settings.get('download_path')
            if out_dir:
                log_failed_download(out_dir, title=title, author=author, url=url, reason=error_msg)

        self.history.add_entry(title, author, platform, status_text, url=url, media_type=widget.format_type)
        self.refresh_history()
        self.update_queue_ui()
        self._update_taskbar_progress()

        # Pick up next item in queue
        self.process_queue()

    def check_post_download_action(self):
        action = self.settings.get('post_download_action', 'Disabled')
        if action == "Shutdown PC":
            self.trigger_countdown_action("Shutdown PC", "shutdown /s /t 0")
        elif action in ("Sleep", "Sleep / Suspend"):
            self.trigger_countdown_action("Sleep", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

    def trigger_countdown_action(self, action_name: str, command: str):
        class CountdownDialog(QDialog):
            def __init__(self, act_name, cmd, parent=None):
                super().__init__(parent)
                self.act_name = act_name
                self.cmd = cmd
                self.seconds_left = 30
                self.setWindowTitle(f"Post-Download Action: {act_name}")
                self.setFixedSize(360, 160)
                layout = QVBoxLayout(self)

                self.lbl = QLabel(f"All downloads finished!\n\nSystem will {act_name.lower()} in {self.seconds_left} seconds...")
                self.lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lbl.setStyleSheet("font-size: 13px; font-weight: 500;")
                layout.addWidget(self.lbl)

                btn_layout = QHBoxLayout()
                self.btn_cancel = QPushButton("Cancel")
                self.btn_now = QPushButton(f"{act_name} Now")
                self.btn_cancel.clicked.connect(self.cancel_action)
                self.btn_now.clicked.connect(self.do_action)
                btn_layout.addWidget(self.btn_cancel)
                btn_layout.addWidget(self.btn_now)
                layout.addLayout(btn_layout)

                self.timer = QTimer(self)
                self.timer.timeout.connect(self.tick)
                self.timer.start(1000)

            def tick(self):
                self.seconds_left -= 1
                self.lbl.setText(f"All downloads finished!\n\nSystem will {self.act_name.lower()} in {self.seconds_left} seconds...")
                if self.seconds_left <= 0:
                    self.timer.stop()
                    self.do_action()

            def cancel_action(self):
                self.timer.stop()
                self.reject()

            def do_action(self):
                self.timer.stop()
                self.accept()
                os.system(self.cmd)

        dlg = CountdownDialog(action_name, command, self)
        dlg.exec()

    def show_unavailable_summary(self):
        if not getattr(self, 'unavailable_queue', None):
            return
        items = list(self.unavailable_queue)
        self.unavailable_queue.clear()
        dlg = UnavailableTracksDialog(items, self)
        dlg.exec()

    def show_failed_summary(self):
        count = len(self.failed_queue)
        if count == 0: return

        first_err = self.failed_queue[0][1]
        friendly = friendly_error(first_err)

        msg = f"Failed to download {count} item(s).\n\n"
        msg += f"Reason: {friendly}\n\n"
        msg += "Would you like to retry the failed downloads?"

        reply = QMessageBox.question(self, "Download Errors", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            to_retry = list(self.failed_queue)
            self.failed_queue.clear()

            for item_data, _ in to_retry:
                url = item_data.get('url')
                media_type = item_data.get('media_type')
                for widget in self.download_queue:
                    if widget.item_data.get('url') == url and widget.item_data.get('media_type') == media_type:
                        widget.is_retry = True
                        widget.set_status("Retrying...", "Pending")

            self.update_queue_ui()
            self.start_queue()
        else:
            self.failed_queue.clear()

    def open_logs_file(self):
        dlg = LogViewerDialog(self)
        dlg.exec()
