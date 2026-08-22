import sys
import time
import datetime
import requests
import re
import os
from pathlib import Path

try:
    import sip
except ImportError:
    sip = None

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QProgressBar, 
    QComboBox, QMessageBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QFileDialog, QFormLayout,
    QApplication, QRadioButton, QButtonGroup, QGroupBox, QScrollArea, QDialog,
    QSystemTrayIcon, QMenu, QSpinBox, QSlider, QFrame, QGraphicsDropShadowEffect,
    QTextEdit, QGraphicsBlurEffect, QTabBar
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QObject, QEvent, QMimeData, QPropertyAnimation, QPoint, QEasingCurve, QRectF
from PyQt6.QtGui import QPixmap, QDesktopServices, QAction, QIcon, QColor, QPainter, QPen, QDrag, QPainterPath, QFont

from core.preview import get_video_preview
from core.downloader import (
    MediaDownloader,
    friendly_error,
    is_platform_unavailable,
    is_rate_limited,
    detect_platform_name,
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
    translit_ru_to_en,
    extract_significant_version_tags,
    _author_and_title_match,
    build_local_files_index,
    is_entry_in_index,
    detect_online_playlist_duplicates,
    detect_orphan_files_in_folder,
)
from core.constants import APP_VERSION
from core.utils import clean_filename_for_all_devices
from core.settings import SettingsManager, get_app_data_dir
from core.history import HistoryManager
from core.taskbar import taskbar_manager
from core.backup import export_backup, import_backup
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
from ui.playlist_comparison_dialog import CrossPlaylistComparisonDialog


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
                platform = detect_platform_name(self.url)
                self.error_signal.emit(f"Could not fetch media metadata from {platform}.", self.context)
        except Exception as e:
            self.error_signal.emit(str(e), self.context)


class CheckAppUpdateWorker(QThread):
    finished_signal = pyqtSignal(bool, str, str, str)  # has_update, latest_ver, release_url, release_notes

    def __init__(self, current_ver: str, repo: str = "Helvior-dev/Logovo-Downloads"):
        super().__init__()
        self.current_ver = current_ver
        self.repo = repo

    def run(self):
        import requests
        import re
        try:
            headers = {
                "User-Agent": f"Logovo-Downloads/{self.current_ver}",
                "Accept": "application/vnd.github.v3+json"
            }
            url = f"https://api.github.com/repos/{self.repo}/releases/latest"
            r = requests.get(url, headers=headers, timeout=6)
            if r.status_code == 200:
                data = r.json()
                tag = data.get("tag_name", "")
                rel_url = data.get("html_url", f"https://github.com/{self.repo}/releases/latest")
                body = data.get("body", "") or ""

                def parse_v(v_str):
                    clean = str(v_str).lstrip("v").strip()
                    parts = [int(p) for p in re.findall(r"\d+", clean)]
                    return parts or [0]

                has_update = parse_v(tag) > parse_v(self.current_ver)
                clean_tag = tag.lstrip("v")
                self.finished_signal.emit(has_update, clean_tag, rel_url, body)
            else:
                self.finished_signal.emit(False, "", "", "")
        except Exception:
            self.finished_signal.emit(False, "", "", "")


class StartupPlaylistCheckWorker(QThread):
    finished_signal = pyqtSignal()

    def __init__(self, playlists_mgr, cookies=None):
        super().__init__()
        self.playlists_mgr = playlists_mgr
        self.cookies = cookies

    def run(self):
        from core.logger import get_logger
        logger = get_logger("logovo.startup_check")
        try:
            valid_media_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac", ".mp4", ".mkv", ".webm"}
            items = self.playlists_mgr.get_all()
            for p in items:
                out_dir = p.get('folder_path')
                url = p.get('url')
                if not out_dir or not url or not os.path.exists(out_dir):
                    continue

                preview = get_video_preview(url, cookies=self.cookies)
                if not preview or not preview.get('entries'):
                    continue

                is_audio = (p.get('media_type', 'Audio') == 'Audio')
                combined_vid_set, title_index, local_cnt = build_local_files_index(out_dir, is_audio=is_audio)

                missing_cnt = 0
                for entry in preview.get('entries', []):
                    if entry.get('is_unavailable') or "unavailable / deleted" in str(entry.get('title', '')).lower():
                        continue
                    vid = entry.get('url', '').split('v=')[-1].split('&')[0]
                    author = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ""
                    title = entry.get('title') or ""

                    already = is_entry_in_index(vid, title, author, combined_vid_set, title_index)
                    if not already:
                        missing_cnt += 1

                dupes = detect_online_playlist_duplicates(preview.get('entries', []))
                dupes_cnt = len(dupes)
                unavail_cnt = sum(1 for entry in preview.get('entries', []) if entry.get('is_unavailable') or "unavailable / deleted" in str(entry.get('title', '')).lower())
                total_cnt = preview.get('count', 0)
                orphans = detect_orphan_files_in_folder(out_dir, preview.get('entries', []), is_audio=is_audio)
                orphans_cnt = len(orphans)

                p['unavailable_count'] = unavail_cnt
                p['duplicates_count'] = dupes_cnt
                p['track_count'] = total_cnt
                p['new_tracks_count'] = missing_cnt
                p['removed_tracks_count'] = orphans_cnt

            self.playlists_mgr.save()
            self.finished_signal.emit()
        except Exception as e:
            try:
                from core.logger import get_logger
                get_logger("logovo.startup_check").exception("StartupPlaylistCheckWorker failed: %s", e)
            except Exception:
                pass


class SyncPlaylistWorker(QThread):
    finished_signal = pyqtSignal(dict, dict, list, int, list, list, list)
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
                platform = detect_platform_name(url)
                self.error_signal.emit(f"Invalid playlist response from {platform}.", self.p_dict)
                return

            count = preview.get('count', 0)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir, exist_ok=True)

            # Cleanup orphan files and leftover raw .mp4 before sync
            cleanup_orphan_files(out_dir, is_audio_playlist=(media_type_category == "Audio"))

            cover_mode = self.settings.get('playlist_cover_mode', 'both') if self.settings else 'both'
            if preview.get('thumbnail') and cover_mode != 'none':
                apply_playlist_cover_settings(out_dir, preview.get('thumbnail'), mode=cover_mode)

            # Restore dates from .playlist_order.json if needed
            restore_dates_from_order(out_dir)

            # 1. Build local index
            combined_vid_set, title_index, local_cnt = build_local_files_index(
                out_dir, is_audio=(media_type_category == "Audio")
            )

            # 2. Check each online entry
            missing_entries = []
            unavailable_entries = []
            for i, entry in enumerate(preview.get('entries', [])):
                entry['playlist_output_dir'] = out_dir
                entry['playlist_index'] = count - i
                entry['playlist_count'] = count
                entry['media_type_category'] = media_type_category
                entry['media_type'] = "Audio (Best)" if media_type_category == "Audio" else "Video (Best)"

                vid = entry.get('url', '').split('v=')[-1].split('&')[0]
                author = entry.get('uploader') or entry.get('channel') or entry.get('artist') or ""
                title = entry.get('title') or ""

                if entry.get('is_unavailable') or "unavailable / deleted" in str(title).lower():
                    unavailable_entries.append((entry, "Removed from online platform / Copyright Claim"))
                    continue

                already = is_entry_in_index(vid, title, author, combined_vid_set, title_index)
                if not already:
                    missing_entries.append(entry)

            # 3. Duplicate detection in online playlist
            online_duplicates = detect_online_playlist_duplicates(preview.get('entries', []))

            # 4. Check for orphan/removed files in local folder
            orphaned_files = detect_orphan_files_in_folder(
                out_dir,
                preview.get('entries', []),
                is_audio=(media_type_category == "Audio")
            )

            self.finished_signal.emit(
                preview,
                self.p_dict,
                missing_entries,
                local_cnt,
                online_duplicates,
                unavailable_entries,
                orphaned_files
            )
        except Exception as e:
            self.error_signal.emit(str(e), self.p_dict)


class SpinnerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)
        self.timer.start(30)

    def rotate(self):
        self.angle = (self.angle + 15) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)
        pen = QPen(QColor("#38bdf8"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(-15, -15, 30, 30, 0, 270 * 16)
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

        self.msg_label = QLabel("Connecting to service...")
        self.msg_label.setStyleSheet("font-size: 12px; color: #94a3b8;")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setWordWrap(True)

        self.sub_label = QLabel("Fetching media information in the background...")
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

    def show_loading(self, title="Loading Media...", message="Connecting to service..."):
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
        self.setStyleSheet("QDialog { background-color: #0b0e14; }")
        self.setMinimumSize(700, 440)
        self.resize(700, 440)
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
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 140)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(50)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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
                padding: 0px 8px;
                border-bottom: 1px solid #1e293b;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #334155;
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
            item_vid.setForeground(QColor("#38bdf8"))
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
        return deleted
    return []


class OnlineDuplicatesDialog(QDialog):
    def __init__(self, duplicate_items: list[dict], playlist_title: str = "Playlist", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Online Duplicates Detected")
        self.setStyleSheet("QDialog { background-color: #0b0e14; }")
        self.setMinimumSize(840, 460)
        self.resize(840, 460)

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
                background-color: #0f172a;
                border: 1px solid #1e293b;
                border-radius: 8px;
                color: #f1f5f9;
                gridline-color: transparent;
                outline: none;
            }
            QTableWidget::item {
                padding: 0px 8px;
                border-bottom: 1px solid #1e293b;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                font-weight: bold;
                font-size: 12px;
                padding: 6px;
                border: none;
                border-bottom: 1px solid #334155;
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
            item_orig.setForeground(QColor("#10b981"))
            item_orig.setFlags(item_orig.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, item_orig)

            item_dupe = QTableWidgetItem(dupe_display)
            item_dupe.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            item_dupe.setForeground(QColor("#38bdf8"))
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
                btn_link.clicked.connect(lambda _, u=dupe_url: QDesktopServices.openUrl(QUrl(u)))
                btn_layout.addWidget(btn_link)
                self.table.setCellWidget(row, 2, btn_widget)

        self.duplicate_items = duplicate_items
        layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        btn_copy = QPushButton("📋 Copy Duplicates List")
        btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_copy.setStyleSheet("background-color: #3b82f6; color: white; border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 12px;")
        btn_copy.clicked.connect(self._copy_list)
        btn_box.addWidget(btn_copy)
        btn_box.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setFixedWidth(100)
        btn_close.setStyleSheet("background-color: #334155; color: white; border-radius: 6px; padding: 6px 14px; font-weight: bold; font-size: 12px;")
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
        QMessageBox.information(self, "Copied", "Duplicates list copied to clipboard!")


class PlaylistUpToDateDialog(QDialog):
    def __init__(self, title: str, count: int, local_files_count: Optional[int] = None, duplicates: Optional[list] = None, unavailable: Optional[list] = None, parent=None):
        super().__init__(parent)
        self.duplicates = duplicates or []
        self.unavailable = unavailable or []
        self.playlist_title = title
        self.local_files_count = local_files_count
        self.setWindowTitle("Sync Complete")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        extra_btns = (1 if self.duplicates else 0) + (1 if self.unavailable else 0)
        h = 280 + extra_btns * 45
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

        dupes_cnt = len(self.duplicates) if self.duplicates else 0
        unavail_cnt = len(self.unavailable) if self.unavailable else 0

        details_parts = []
        if unavail_cnt > 0:
            details_parts.append(f"{unavail_cnt} removed on YouTube")
        if dupes_cnt > 0:
            details_parts.append(f"{dupes_cnt} internal duplicate{'s' if dupes_cnt > 1 else ''}")

        details_str = f"<br><span style='font-size: 11px; color: #94a3b8;'>({', '.join(details_parts)})</span>" if details_parts else ""

        if self.local_files_count is not None and self.local_files_count < count:
            desc_text = f"<b>{self.local_files_count}</b> of <b>{count}</b> tracks in playlist<br><span style='color: #e2e8f0; font-size: 14px;'>{title}</span><br>are downloaded.{details_str}"
        else:
            desc_text = f"All <b>{count}</b> tracks in playlist<br><span style='color: #e2e8f0; font-size: 14px;'>{title}</span><br>are already verified and downloaded.{details_str}"

        desc_lbl = QLabel(desc_text)
        desc_lbl.setStyleSheet("font-size: 13px; color: #94a3b8; line-height: 1.4; background: transparent;")
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_lbl.setWordWrap(True)

        layout.addWidget(icon_lbl)
        layout.addWidget(h_lbl)
        layout.addWidget(desc_lbl)

        if self.duplicates:
            btn_dupes = QPushButton(f"📋 {len(self.duplicates)} Playlist Duplicate(s) — View List", card)
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

        if self.unavailable:
            btn_unavail = QPushButton(f"⚠️ {len(self.unavailable)} Unavailable Track(s) — View List", card)
            btn_unavail.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_unavail.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #fbbf24;
                    border: 1px solid #d97706;
                    border-radius: 6px;
                    font-weight: bold;
                    font-size: 12px;
                    padding: 6px 14px;
                }
                QPushButton:hover {
                    background-color: #d97706;
                    color: #ffffff;
                }
            """)
            btn_unavail.clicked.connect(self._show_unavailable)
            layout.addWidget(btn_unavail, 0, Qt.AlignmentFlag.AlignCenter)

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

    def _show_unavailable(self):
        UnavailableTracksDialog(self.unavailable, parent=self).exec()


class UnavailableTracksDialog(QDialog):
    def __init__(self, items: list[tuple[dict, str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unavailable Tracks on YouTube")
        self.setMinimumSize(660, 520)
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

        # Step-by-step guide banner
        guide_box = QFrame()
        guide_box.setStyleSheet("""
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        guide_layout = QVBoxLayout(guide_box)
        guide_layout.setContentsMargins(12, 10, 12, 10)
        guide_layout.setSpacing(6)

        guide_title = QLabel("💡 <b>How to remove unavailable videos from your YouTube playlist:</b>")
        guide_title.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: bold; background: transparent; border: none;")
        
        guide_body = QLabel(
            "1. Open your playlist on YouTube or YouTube Music.<br>"
            "2. Click the <b>three dots menu (⋮)</b> under the playlist title/cover and select <b>'Show unavailable videos'</b>.<br>"
            "3. The hidden/deleted items will appear grayed out in your playlist.<br>"
            "4. Click the <b>three dots (⋮)</b> next to each unavailable video and choose <b>'Remove from playlist'</b>."
        )
        guide_body.setWordWrap(True)
        guide_body.setStyleSheet("color: #cbd5e1; font-size: 11px; line-height: 1.45; background: transparent; border: none;")

        guide_layout.addWidget(guide_title)
        guide_layout.addWidget(guide_body)
        layout.addWidget(guide_box)

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


class SafeModeDialog(QDialog):
    def __init__(self, count: int, concurrency: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Large Queue Optimization")
        self.setFixedWidth(480)
        self.setStyleSheet("""
            QDialog { background-color: #0b1120; color: #f8fafc; }
            QPushButton { border-radius: 6px; padding: 9px 16px; font-weight: bold; font-size: 12px; }
            QCheckBox { color: #94a3b8; font-size: 11px; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        icon_lbl = QLabel("🛡️")
        icon_lbl.setStyleSheet("font-size: 32px;")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_lbl)

        title_lbl = QLabel(f"Large Download Queue ({count} tracks)")
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #38bdf8;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)

        desc_lbl = QLabel(
            f"You have <b>{count}</b> tracks in queue with <b>{concurrency} concurrent threads</b>.<br><br>"
            "Downloading huge playlists at maximum speed may trigger temporary <b>YouTube rate-limiting</b>.<br><br>"
            "<b>Safe Mode</b> uses <b>3 threads</b> with smart pacing to ensure 100% reliable downloads without bans or interruptions."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet("font-size: 12px; color: #cbd5e1; line-height: 1.45;")
        layout.addWidget(desc_lbl)

        self.chk_remember = QCheckBox("Remember choice for this session")
        layout.addWidget(self.chk_remember)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.btn_full = QPushButton(f"🚀 Full Speed ({concurrency} Threads)")
        self.btn_full.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_full.setStyleSheet("""
            QPushButton {
                background-color: #334155;
                color: #f1f5f9;
                border: 1px solid #475569;
            }
            QPushButton:hover { background-color: #475569; }
        """)
        self.btn_full.clicked.connect(self._choose_full)

        self.btn_safe = QPushButton("🛡️ Enable Safe Mode (Recommended)")
        self.btn_safe.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_safe.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: #ffffff;
                border: none;
            }
            QPushButton:hover { background-color: #059669; }
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
class DraggablePlaylistCard(QWidget):
    def __init__(self, index: int, parent_view, parent=None):
        super().__init__(parent)
        self.index = index
        self.parent_view = parent_view
        self.setObjectName("PlaylistCard")
        self.setAcceptDrops(True)
        self._drag_start_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self._drag_start_pos:
            return
        if (event.pos() - self._drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.index))
        drag.setMimeData(mime)

        # Smooth, lightweight card preview during drag
        try:
            pix = self.grab()
            if pix.width() > 460:
                pix = pix.scaledToWidth(460, Qt.TransformationMode.SmoothTransformation)
            drag_pix = QPixmap(pix.size())
            drag_pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(drag_pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setOpacity(0.85)
            p.drawPixmap(0, 0, pix)
            p.end()
            drag.setPixmap(drag_pix)
            drag.setHotSpot(QPoint(min(pix.width() // 2, event.pos().x()), min(pix.height() // 2, event.pos().y())))
        except Exception:
            pass

        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText() and event.mimeData().text().isdigit():
            event.acceptProposedAction()
            # Apply border strictly to the outer PlaylistCard container only
            self.setStyleSheet("QWidget#PlaylistCard { border: 2px solid #38bdf8 !important; background-color: #273549; }")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("")

    def dropEvent(self, event):
        self.setStyleSheet("")
        if event.mimeData().hasText() and event.mimeData().text().isdigit():
            src_idx = int(event.mimeData().text())
            dst_idx = self.index
            event.acceptProposedAction()
            if src_idx != dst_idx:
                # Defer the card reorder asynchronously so the drag release finishes immediately without stutter
                QTimer.singleShot(0, lambda s=src_idx, d=dst_idx: self.parent_view._move_playlist_item(s, d))


class CustomTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setDrawBase(False)
        self.pl_syncing = False
        self.pl_has_new = False
        self.pl_has_removed = False
        self.spinner_angle = 0

        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(30)
        self._spinner_timer.timeout.connect(self._on_spinner_tick)

    def set_pl_syncing(self, syncing: bool):
        self.pl_syncing = syncing
        if syncing:
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        else:
            if self._spinner_timer.isActive():
                self._spinner_timer.stop()
        self.update()

    def set_pl_badges(self, has_new: bool, has_removed: bool):
        self.pl_syncing = False
        if self._spinner_timer.isActive():
            self._spinner_timer.stop()
        self.pl_has_new = has_new
        self.pl_has_removed = has_removed
        self.update()

    def _on_spinner_tick(self):
        self.spinner_angle = (self.spinner_angle + 16) % 360
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        # Custom centered spinner & badge overlays for PLAYLISTS tab (tab index 1)
        if self.count() > 1:
            rect = self.tabRect(1)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            if self.pl_syncing:
                # Soft blurred & dimmed overlay strictly centered over PLAYLISTS tab
                overlay_rect = rect.adjusted(4, 4, -4, -4)
                p.setPen(Qt.PenStyle.NoPen)
                if self.currentIndex() == 1:
                    p.setBrush(QColor(30, 41, 59, 235))
                else:
                    p.setBrush(QColor(11, 14, 20, 210))
                p.drawRoundedRect(QRectF(overlay_rect), 6, 6)

                # Centered spinning loader circle directly in the middle of the tab
                cx = rect.center().x()
                cy = rect.center().y()
                p.save()
                p.translate(cx, cy)
                p.rotate(self.spinner_angle)
                pen = QPen(QColor("#38bdf8"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(QRectF(-7, -7, 14, 14), 0, 270 * 16)
                p.restore()
            elif self.pl_has_new or self.pl_has_removed:
                # Clean badges in the upper right corner of the tab pill
                by = rect.top() + 5
                if self.pl_has_new and self.pl_has_removed:
                    bw = 25
                    bx = rect.right() - bw - 4
                    p.setPen(QPen(QColor("#0284c7"), 1))
                    p.setBrush(QColor("#0f172a"))
                    p.drawRoundedRect(QRectF(bx, by, bw, 14), 3, 3)
                    p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                    p.setPen(QColor("#10b981"))
                    p.drawText(QRectF(bx + 1, by, 11, 14), Qt.AlignmentFlag.AlignCenter, "+")
                    p.setPen(QColor("#f87171"))
                    p.drawText(QRectF(bx + 12, by, 11, 14), Qt.AlignmentFlag.AlignCenter, "-")
                elif self.pl_has_new:
                    bw = 14
                    bx = rect.right() - bw - 5
                    p.setPen(QPen(QColor("#10b981"), 1))
                    p.setBrush(QColor("#064e3b"))
                    p.drawRoundedRect(QRectF(bx, by, bw, 14), 3, 3)
                    p.setPen(QColor("#10b981"))
                    p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                    p.drawText(QRectF(bx, by, bw, 14), Qt.AlignmentFlag.AlignCenter, "+")
                elif self.pl_has_removed:
                    bw = 14
                    bx = rect.right() - bw - 5
                    p.setPen(QPen(QColor("#f87171"), 1))
                    p.setBrush(QColor("#450a0a"))
                    p.drawRoundedRect(QRectF(bx, by, bw, 14), 3, 3)
                    p.setPen(QColor("#f87171"))
                    p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
                    p.drawText(QRectF(bx, by, bw, 14), Qt.AlignmentFlag.AlignCenter, "-")
            p.end()


class SideNotificationToast(QFrame):
    def __init__(self, title: str, message: str, level: str = "warning", action_text: str = None, action_callback=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SideNotificationToast")
        self.setFixedWidth(330)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._accent_color = "#38bdf8" if level != "error" else "#ef4444"

        # Match app's dark slate card theme perfectly
        self.setStyleSheet("""
            QFrame#SideNotificationToast {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header Row
        h_row = QHBoxLayout()
        h_row.setSpacing(8)

        icon_char = "🍪" if "cookie" in title.lower() else ("🚀" if "update" in title.lower() or "version" in title.lower() else ("⚠️" if level == "warning" else ("❌" if level == "error" else "ℹ️")))
        icon_lbl = QLabel(icon_char)
        icon_lbl.setStyleSheet("font-size: 15px; background: transparent;")
        h_row.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #f8fafc; background: transparent;")
        h_row.addWidget(title_lbl, 1)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(18, 18)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #64748b;
                border: none;
                font-size: 11px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                color: #ffffff;
            }
        """)
        btn_close.clicked.connect(self.close_animated)
        h_row.addWidget(btn_close)
        layout.addLayout(h_row)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet("font-size: 11px; color: #94a3b8; background: transparent; line-height: 1.35;")
        layout.addWidget(msg_lbl)

        # Action Buttons Row
        if action_text and action_callback:
            btn_row = QHBoxLayout()
            btn_row.addStretch()

            btn_action = QPushButton(action_text)
            btn_action.setFixedHeight(26)
            btn_action.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_action.setStyleSheet("""
                QPushButton {
                    background-color: #0284c7;
                    color: #ffffff;
                    border: 1px solid #38bdf8;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 2px 12px;
                }
                QPushButton:hover {
                    background-color: #0369a1;
                    border-color: #7dd3fc;
                }
            """)
            def _on_action():
                self.close_animated()
                action_callback()
            btn_action.clicked.connect(_on_action)
            btn_row.addWidget(btn_action)
            layout.addLayout(btn_row)

        # KDE Plasma style smooth countdown timer (line recedes from left to right)
        self._total_duration_ms = 7000
        self._remaining_ms = 7000

        self._timer = QTimer(self)
        self._timer.setInterval(25)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

        # Play pleasant Windows notification sound
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass

    def _on_tick(self):
        self._remaining_ms -= 25
        self.update()
        if self._remaining_ms <= 0:
            self._timer.stop()
            self.close_animated()

    def paintEvent(self, event):
        super().paintEvent(event)
        # Draw KDE Plasma countdown bar at the top edge, perfectly clipped to 8px rounded corners
        if self._total_duration_ms > 0 and self._remaining_ms > 0:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            clip_path = QPainterPath()
            clip_path.addRoundedRect(0.0, 0.0, float(self.width()), float(self.height()), 8.0, 8.0)
            painter.setClipPath(clip_path)

            progress = max(0.0, min(1.0, self._remaining_ms / self._total_duration_ms))
            x_start = int(self.width() * (1.0 - progress))
            bar_w = self.width() - x_start
            if bar_w > 0:
                painter.fillRect(x_start, 0, bar_w, 3, QColor(self._accent_color))
            painter.end()

    def reposition(self):
        if self.parent():
            pw = self.parent().width()
            ph = self.parent().height()
            self.move(pw - self.width() - 20, ph - self.height() - 28)

    def show_animated(self):
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        end_pos = self.pos()
        start_pos = QPoint(end_pos.x() + 50, end_pos.y())
        self._anim.setStartValue(start_pos)
        self._anim.setEndValue(end_pos)
        self._anim.start()

    def close_animated(self):
        if getattr(self, '_is_closing', False):
            return
        self._is_closing = True
        if hasattr(self, '_timer') and self._timer.isActive():
            self._timer.stop()

        # Smooth slide-out to the right on close
        self._close_anim = QPropertyAnimation(self, b"pos")
        self._close_anim.setDuration(200)
        self._close_anim.setEasingCurve(QEasingCurve.Type.InQuad)
        start_pos = self.pos()
        end_pos = QPoint(start_pos.x() + 60, start_pos.y())
        self._close_anim.setStartValue(start_pos)
        self._close_anim.setEndValue(end_pos)
        self._close_anim.finished.connect(self.close)
        self._close_anim.start()

    def closeEvent(self, event):
        try:
            if self.parent() and getattr(self.parent(), '_active_toast', None) is self:
                self.parent()._active_toast = None
        except Exception:
            pass
        super().closeEvent(event)


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
        self._pl_dirty = True  # Flag: playlists tab needs refresh
        self._current_pl_sort = self.settings.get('playlist_sort_mode', 'custom')

        self.success_count = 0
        self.error_count = 0
        self.downloaded_count = 0
        self.skipped_count = 0
        self.track_durations = []

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.custom_tab_bar = CustomTabBar(self.tabs)
        self.tabs.setTabBar(self.custom_tab_bar)
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

        # Startup playlists check for new tracks
        if self.settings.get('check_playlists_on_startup', False):
            self.custom_tab_bar.set_pl_syncing(True)
            self.startup_playlist_thread = StartupPlaylistCheckWorker(self.playlists_mgr, cookies=self.get_cookies_config())
            self.startup_playlist_thread.finished_signal.connect(self._on_startup_playlists_check_finished)
            self.startup_playlist_thread.start()
        else:
            self.update_playlists_tab_badge()

        # Loading overlay for smooth non-blocking operations
        self.loading_overlay = LoadingOverlay(self)
        self.loading_overlay.hide()

        # Check cookies configuration on startup
        QTimer.singleShot(700, self.check_cookies_file_validity)

        # Check Logovo Downloads app updates on startup
        if self.settings.get('check_app_updates_on_startup', True):
            QTimer.singleShot(1800, self.check_app_update_background)

    def show_side_notification(self, title: str, message: str, level: str = "warning", action_text: str = None, action_callback = None):
        now = time.time()
        if not hasattr(self, '_last_toast_times'):
            self._last_toast_times = {}
        last_time = self._last_toast_times.get(title, 0)
        if now - last_time < 3.0:
            return  # Debounce duplicate popups within 3 seconds
        self._last_toast_times[title] = now

        old_toast = getattr(self, '_active_toast', None)
        if old_toast:
            try:
                old_toast.close()
            except Exception:
                pass
            self._active_toast = None

        toast = SideNotificationToast(
            title=title,
            message=message,
            level=level,
            action_text=action_text,
            action_callback=action_callback,
            parent=self
        )
        toast.destroyed.connect(lambda: setattr(self, '_active_toast', None))
        self._active_toast = toast
        toast.show_animated()

    def check_cookies_file_validity(self) -> bool:
        # Do not show toast if user is already on the SETTINGS tab
        if hasattr(self, 'tabs') and self.tabs.currentIndex() == 3:
            return True
        cookies_source = self.settings.get('cookies_source', 'none')
        if cookies_source == 'file':
            c_file = self.settings.get('cookies_file', '')
            if not c_file or not os.path.exists(c_file) or not os.path.isfile(c_file):
                disp_path = c_file if c_file else "(No file path specified)"
                self.show_side_notification(
                    title="Cookies File Not Found",
                    message=f"The cookies file specified in Settings does not exist:\n{disp_path}\nAuthenticated downloads might fail.",
                    level="warning",
                    action_text="Open Settings",
                    action_callback=self._go_to_cookies_settings
                )
                return False
        return True

    def _go_to_cookies_settings(self):
        self.tabs.setCurrentIndex(3)  # SETTINGS tab
        if hasattr(self, 'cookies_file_input'):
            self.cookies_file_input.setFocus()
            self.cookies_file_input.setStyleSheet("border: 2px solid #f59e0b; background-color: #1e293b;")
            QTimer.singleShot(2500, lambda: self.cookies_file_input.setStyleSheet("") if hasattr(self, 'cookies_file_input') else None)

    def _on_startup_playlists_check_finished(self):
        if hasattr(self, 'custom_tab_bar'):
            self.custom_tab_bar.set_pl_syncing(False)
        self._mark_pl_dirty_and_refresh()
        self.update_playlists_tab_badge()

    def update_playlists_tab_badge(self):
        if not hasattr(self, 'custom_tab_bar'):
            return
        # If background startup check is currently running, keep the syncing spinner active!
        if hasattr(self, 'startup_playlist_thread') and self.startup_playlist_thread and self.startup_playlist_thread.isRunning():
            self.custom_tab_bar.set_pl_syncing(True)
            return

        total_new = sum(p.get('new_tracks_count', 0) for p in self.playlists_mgr.get_all())
        total_removed = sum(p.get('removed_tracks_count', 0) for p in self.playlists_mgr.get_all())
        has_new = (total_new > 0)
        has_removed = (total_removed > 0)
        self.custom_tab_bar.set_pl_badges(has_new, has_removed)

    def _mark_pl_dirty_and_refresh(self):
        """Mark playlists as dirty and refresh if currently on the playlists tab."""
        self._pl_dirty = True
        if self.tabs.currentIndex() == 1:
            self._pl_dirty = False
            self.refresh_playlists_ui()
        else:
            self.update_playlists_tab_badge()

    def _on_tab_changed(self, index: int):
        if index == 1 and self._pl_dirty:
            # If background sync is running, do not prematurely refresh or cancel spinner
            if not (hasattr(self, 'startup_playlist_thread') and self.startup_playlist_thread and self.startup_playlist_thread.isRunning()):
                self._pl_dirty = False
                self.refresh_playlists_ui()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay') and self.loading_overlay:
            self.loading_overlay.resize(self.size())
        toast = getattr(self, '_active_toast', None)
        if toast:
            try:
                if toast.isVisible():
                    toast.reposition()
            except (RuntimeError, Exception):
                self._active_toast = None

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
        self.url_input.setPlaceholderText("Enter YouTube, Spotify, SoundCloud, Bandcamp, or any media URL...")
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
        btn_compare = QPushButton("🔍 Compare Playlists")
        btn_compare.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_compare.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #38bdf8;
                border: 1px solid #0284c7;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0369a1;
                color: #ffffff;
            }
        """)

        lbl_sort = QLabel("Sort:")
        lbl_sort.setStyleSheet("font-size: 12px; color: #94a3b8; font-weight: bold; margin-left: 10px;")

        self.combo_playlist_sort = QComboBox()
        self.combo_playlist_sort.setStyleSheet("""
            QComboBox {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #0f172a;
                color: #f8fafc;
                selection-background-color: #3b82f6;
                selection-color: #ffffff;
            }
        """)
        self.combo_playlist_sort.blockSignals(True)
        self.combo_playlist_sort.addItem("Manual Order (Drag & Drop)", "custom")
        self.combo_playlist_sort.addItem("Name (A → Z)", "name_asc")
        self.combo_playlist_sort.addItem("Name (Z → A)", "name_desc")
        self.combo_playlist_sort.addItem("Tracks (Most → Fewest)", "tracks_desc")
        self.combo_playlist_sort.addItem("Tracks (Fewest → Most)", "tracks_asc")
        self.combo_playlist_sort.addItem("Last Synced (Newest)", "synced_desc")

        saved_sort = self.settings.get('playlist_sort_mode', 'custom')
        self._current_pl_sort = saved_sort
        # Find and set the matching index
        for i in range(self.combo_playlist_sort.count()):
            if self.combo_playlist_sort.itemData(i) == saved_sort:
                self.combo_playlist_sort.setCurrentIndex(i)
                break
        self.combo_playlist_sort.blockSignals(False)

        self.combo_playlist_sort.currentIndexChanged.connect(self._on_playlist_sort_changed)

        self.lbl_playlists_count = QLabel("Tracked Playlists: 0")
        self.lbl_playlists_count.setStyleSheet("font-size: 12px; color: #94a3b8;")

        btn_track_new.clicked.connect(self.track_new_playlist_dialog)
        btn_compare.clicked.connect(self.open_playlist_comparison_dialog)

        top_bar.addWidget(btn_track_new)
        top_bar.addWidget(btn_compare)
        top_bar.addWidget(lbl_sort)
        top_bar.addWidget(self.combo_playlist_sort)
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

        self.lbl_pl_stats = QLabel("")
        self.lbl_pl_stats.setStyleSheet("color: #475569; font-size: 11px; padding: 4px 8px;")
        self.lbl_pl_stats.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.lbl_pl_stats)

        self.refresh_playlists_ui()
        self.tabs.addTab(self.playlists_tab, "PLAYLISTS")

    def _on_playlist_sort_changed(self):
        val = self.combo_playlist_sort.currentData() or 'custom'
        self.settings.set('playlist_sort_mode', val)
        self._current_pl_sort = val
        self._mark_pl_dirty_and_refresh()

    def _move_playlist_item(self, from_idx: int, to_idx: int):
        if from_idx < 0 or to_idx < 0:
            return
        items = self.playlists_mgr.get_all()
        if from_idx >= len(items) or to_idx >= len(items) or from_idx == to_idx:
            return
        self.playlists_mgr.move_playlist(from_idx, to_idx)
        self._current_pl_sort = "custom"
        self.settings.set('playlist_sort_mode', 'custom')
        if hasattr(self, 'combo_playlist_sort'):
            self.combo_playlist_sort.blockSignals(True)
            self.combo_playlist_sort.setCurrentIndex(0)
            self.combo_playlist_sort.blockSignals(False)

        # Instant in-place layout reordering with zero delay (0 ms)
        try:
            item = self.playlists_container_layout.takeAt(from_idx)
            if item and item.widget():
                self.playlists_container_layout.insertWidget(to_idx, item.widget())

            cnt = self.playlists_container_layout.count()
            for i in range(cnt):
                w = self.playlists_container_layout.itemAt(i).widget()
                if isinstance(w, DraggablePlaylistCard):
                    w.index = i
                    if hasattr(w, 'btn_up') and w.btn_up:
                        w.btn_up.setEnabled(i > 0)
                    if hasattr(w, 'btn_down') and w.btn_down:
                        w.btn_down.setEnabled(i < cnt - 1)
        except Exception:
            self.refresh_playlists_ui(rescan_disk_stats=False)

    def open_playlist_comparison_dialog(self):
        dlg = CrossPlaylistComparisonDialog(self.playlists_mgr, default_target="Trash", parent=self)
        dlg.exec()
        self._mark_pl_dirty_and_refresh()

    def refresh_playlists_ui(self, rescan_disk_stats: bool = False):
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

        sort_mode = getattr(self, '_current_pl_sort', 'custom')
        items = self.playlists_mgr.get_sorted(sort_mode)
        self.lbl_playlists_count.setText(f"Tracked Playlists: {len(items)}")

        if not items:
            empty_lbl = QLabel("No playlists tracked yet.\nClick '+ Track New Playlist' to save and sync playlists in 1 click.")
            empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_lbl.setStyleSheet("color: #64748b; font-size: 14px; margin-top: 60px;")
            self.playlists_container_layout.addWidget(empty_lbl)
            return

        for i, p in enumerate(items):
            card = DraggablePlaylistCard(i, self)
            card_layout = QHBoxLayout(card)
            card_layout.setContentsMargins(10, 10, 12, 10)
            card_layout.setSpacing(12)

            # Reorder controls (Move Up / Move Down & Drag handle)
            reorder_box = QVBoxLayout()
            reorder_box.setSpacing(2)
            reorder_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

            btn_up = QPushButton("▲")
            btn_up.setFixedSize(24, 20)
            btn_up.setToolTip("Move playlist up")
            btn_up.setEnabled(i > 0)
            btn_up.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #94a3b8;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    font-size: 10px;
                    padding: 0px;
                }
                QPushButton:hover:enabled {
                    background-color: #3b82f6;
                    color: #ffffff;
                    border-color: #3b82f6;
                }
                QPushButton:disabled {
                    color: #475569;
                    background-color: #0f172a;
                    border-color: #1e293b;
                }
            """)
            card.btn_up = btn_up
            btn_up.clicked.connect(lambda _, c=card: self._move_playlist_item(c.index, c.index - 1))

            drag_hint = QLabel("☰")
            drag_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            drag_hint.setToolTip("Drag & drop with mouse to reorder")
            drag_hint.setStyleSheet("color: #64748b; font-size: 13px; font-weight: bold;")

            btn_down = QPushButton("▼")
            btn_down.setFixedSize(24, 20)
            btn_down.setToolTip("Move playlist down")
            btn_down.setEnabled(i < len(items) - 1)
            btn_down.setStyleSheet("""
                QPushButton {
                    background-color: #1e293b;
                    color: #94a3b8;
                    border: 1px solid #334155;
                    border-radius: 4px;
                    font-size: 10px;
                    padding: 0px;
                }
                QPushButton:hover:enabled {
                    background-color: #3b82f6;
                    color: #ffffff;
                    border-color: #3b82f6;
                }
                QPushButton:disabled {
                    color: #475569;
                    background-color: #0f172a;
                    border-color: #1e293b;
                }
            """)
            card.btn_down = btn_down
            btn_down.clicked.connect(lambda _, c=card: self._move_playlist_item(c.index, c.index + 1))

            reorder_box.addWidget(btn_up)
            reorder_box.addWidget(drag_hint)
            reorder_box.addWidget(btn_down)
            card_layout.addLayout(reorder_box)

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
                        if target_lbl and sip and not sip.isdeleted(target_lbl):
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
            unavail_count = p.get('unavailable_count', 0)
            duplicates_count = p.get('duplicates_count', 0)
            available_track_count = max(0, pl_track_count - unavail_count - duplicates_count)

            if downloaded_count >= available_track_count and (available_track_count > 0 or pl_track_count > 0):
                notes = []
                if unavail_count > 0:
                    notes.append(f"{unavail_count} unavailable online")
                if duplicates_count > 0:
                    notes.append(f"{duplicates_count} duplicate{'s' if duplicates_count > 1 else ''}")

                if notes:
                    count_str = f"<b>{downloaded_count}</b> / <b>{pl_track_count}</b> tracks <span style='color: #94a3b8;'>(Up to date — {', '.join(notes)})</span>"
                else:
                    count_str = f"<b>{downloaded_count}</b> / <b>{pl_track_count}</b> tracks <span style='color: #94a3b8;'>(Up to date)</span>"
                status_color = "#10b981"
                new_cnt = 0
                if p.get('new_tracks_count', 0) != 0:
                    p['new_tracks_count'] = 0
                    self.playlists_mgr.save()
            else:
                count_str = f"<b>{downloaded_count}</b> / <b>{pl_track_count}</b> tracks"
                status_color = "#38bdf8"
                raw_new = p.get('new_tracks_count', 0)
                missing_upper_bound = max(0, available_track_count - downloaded_count)
                new_cnt = min(raw_new, missing_upper_bound) if raw_new > 0 else 0
                if p.get('new_tracks_count') != new_cnt:
                    p['new_tracks_count'] = new_cnt
                    self.playlists_mgr.save()

            badge_html = f"  <span style='color: #38bdf8; font-weight: bold; background-color: #0f172a; padding: 2px 6px; border-radius: 4px; border: 1px solid #0284c7;'>+{new_cnt} new</span>" if new_cnt > 0 else ""
            raw_removed = p.get('removed_tracks_count', 0)
            badge_removed_html = f"  <span style='color: #f87171; font-weight: bold; background-color: #450a0a; padding: 2px 6px; border-radius: 4px; border: 1px solid #b91c1c;'>-{raw_removed} removed</span>" if raw_removed > 0 else ""

            last_sync_str = p.get('last_synced', 'Never')
            meta_lbl = QLabel(f"In Folder: {count_str}{badge_html}{badge_removed_html}  <span style='color: #475569;'>•</span>  <span style='color: #94a3b8;'>Synced: {last_sync_str}</span>")
            meta_lbl.setTextFormat(Qt.TextFormat.RichText)
            meta_lbl.setStyleSheet(f"font-size: 11px; color: {status_color}; font-weight: 500; background: transparent;")
            meta_lbl.setWordWrap(True)

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

        # Update stats bar
        if hasattr(self, 'lbl_pl_stats'):
            total_pls = len(items)
            if rescan_disk_stats or not hasattr(self, '_cached_pl_stats_str') or not self._cached_pl_stats_str:
                total_files = 0
                total_size_bytes = 0
                for p in items:
                    folder = p.get('folder_path', '')
                    if folder and os.path.exists(folder):
                        try:
                            for f in Path(folder).iterdir():
                                if f.is_file() and f.suffix.lower() in {'.mp3', '.flac', '.m4a', '.opus', '.ogg', '.wav', '.aac', '.alac', '.mp4', '.mkv', '.webm'}:
                                    sz = f.stat().st_size
                                    if sz >= 500 * 1024:
                                        total_files += 1
                                        total_size_bytes += sz
                        except Exception:
                            pass
                if total_size_bytes >= 1_073_741_824:
                    size_str = f"{total_size_bytes / 1_073_741_824:.1f} GB"
                else:
                    size_str = f"{total_size_bytes / 1_048_576:.0f} MB"
                self._cached_pl_stats_str = f"{total_pls} playlist{'s' if total_pls != 1 else ''} • {total_files} files • {size_str} on disk"
            self.lbl_pl_stats.setText(self._cached_pl_stats_str)

        # Update tab header badge (+ / - / +-)
        self.update_playlists_tab_badge()

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
        platform = detect_platform_name(url)
        self.status_label.setText(f"Syncing playlist '{title}' in background...")
        self.loading_overlay.show_loading(f"Syncing '{title}'...", f"Connecting to {platform} and comparing tracks...")

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
        platform = detect_platform_name(p_dict.get('url') if p_dict else '')
        self.status_label.setText(f"Sync error for '{title}'.")
        QMessageBox.warning(self, "Sync Error", f"Could not fetch playlist metadata from {platform}:\n{err_msg}")

    def _on_sync_playlist_finished(self, preview: dict, p_dict: dict, missing_entries: list, local_cnt: int, online_duplicates: list = None, unavailable_entries: list = None, orphaned_files: list = None):
        self.loading_overlay.hide_loading()
        url = p_dict.get('url')
        out_dir = p_dict.get('folder_path')
        count = preview.get('count', 0)
        p_dict['track_count'] = count
        if preview.get('thumbnail'):
            p_dict['thumbnail'] = preview.get('thumbnail')
        unavail_cnt = len(unavailable_entries) if unavailable_entries else 0
        p_dict['unavailable_count'] = unavail_cnt
        dupes_cnt = len(online_duplicates) if online_duplicates else 0
        p_dict['duplicates_count'] = dupes_cnt

        # Prompt user if files were removed from online playlist
        remaining_orphans = len(orphaned_files) if orphaned_files else 0
        if orphaned_files:
            dlg = OrphanFilesDialog(orphaned_files, parent=self)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.deleted_files:
                for fn in dlg.deleted_files:
                    fp = os.path.join(out_dir, fn)
                    try:
                        if os.path.exists(fp):
                            os.remove(fp)
                            local_cnt = max(0, local_cnt - 1)
                            # Log deleted file to history and app logs
                            stem = Path(fn).stem
                            parts = stem.split(" - ", 1)
                            t_author = parts[1] if len(parts) > 1 else ""
                            t_title = parts[0]
                            self.history.add_entry(
                                t_title, 
                                t_author, 
                                platform="YouTube", 
                                status="Deleted (Removed from playlist)", 
                                url=url, 
                                media_type=p_dict.get('media_type', 'Audio')
                            )
                    except Exception:
                        pass
                remaining_orphans = max(0, remaining_orphans - len(dlg.deleted_files))
                self.refresh_playlists_ui()

        p_dict['removed_tracks_count'] = remaining_orphans

        if not missing_entries:
            self.playlists_mgr.update_sync_info(url, track_count=count, status='synced', unavailable_count=unavail_cnt, duplicates_count=dupes_cnt, removed_tracks_count=remaining_orphans)
            self.refresh_playlists_ui()
            self.status_label.setText(f"No new media to sync. All {count - unavail_cnt - dupes_cnt} available tracks in '{p_dict.get('title')}' are up to date.")
            PlaylistUpToDateDialog(p_dict.get('title', 'Playlist'), count, local_files_count=local_cnt, duplicates=online_duplicates, unavailable=unavailable_entries, parent=self).exec()
            return
        else:
            self.playlists_mgr.update_sync_info(url, track_count=count, status='pending', unavailable_count=unavail_cnt, duplicates_count=dupes_cnt, removed_tracks_count=remaining_orphans)

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

        if hasattr(self, '_active_sync_urls') and self._active_sync_urls:
            QMessageBox.information(self, "Sync in Progress", 
                "A playlist sync is already in progress. Please wait for it to complete before syncing all.")
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
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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

        # Row 4: Cover Artwork Aspect Ratio (General setting for both audio and video)
        gen_grid.addWidget(QLabel("Cover Aspect Ratio:"), 4, 0)
        self.cover_style_combo = make_combo()
        self.cover_style_combo.addItem("Smart (Auto-detect sidebars: crop 1:1 if pillarboxed, keep 16:9 if full frame) - Default", "smart")
        self.cover_style_combo.addItem("Original Aspect Ratio (16:9 / No Cropping)", "original")
        self.cover_style_combo.addItem("Square (1:1 Force Center-Crop)", "square")
        cur_cover_style = self.settings.get('cover_aspect_ratio') or self.settings.get('audio_cover_style', 'smart')
        idx_cs = self.cover_style_combo.findData(cur_cover_style)
        if idx_cs >= 0:
            self.cover_style_combo.setCurrentIndex(idx_cs)
        else:
            self.cover_style_combo.setCurrentIndex(0)
        self.cover_style_combo.currentIndexChanged.connect(
            lambda: self.settings.set('cover_aspect_ratio', self.cover_style_combo.currentData())
        )
        gen_grid.addWidget(self.cover_style_combo, 4, 1)

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

        # 5. Application & Core Engine Updates
        lbl_core = QLabel("Updates & Maintenance")
        lbl_core.setStyleSheet("font-weight: bold; color: #94a3b8; margin-top: 8px; margin-bottom: 2px;")
        layout.addWidget(lbl_core)

        # App updates row
        app_upd_layout = QHBoxLayout()
        btn_check_app = QPushButton("Check App Updates")
        btn_check_app.clicked.connect(self.manual_check_app_update)

        self.chk_auto_app_update = QCheckBox("Check Logovo Downloads updates on startup")
        self.chk_auto_app_update.setChecked(self.settings.get('check_app_updates_on_startup', True))
        self.chk_auto_app_update.toggled.connect(lambda c: self.settings.set('check_app_updates_on_startup', c))

        app_upd_layout.addWidget(btn_check_app)
        app_upd_layout.addSpacing(20)
        app_upd_layout.addWidget(self.chk_auto_app_update)
        app_upd_layout.addStretch()
        layout.addLayout(app_upd_layout)

        # yt-dlp core row
        core_layout = QHBoxLayout()
        btn_check_update = QPushButton("Check for yt-dlp Updates")
        btn_check_update.clicked.connect(self.manual_check_ytdlp_update)
        core_layout.addWidget(btn_check_update)
        core_layout.addSpacing(20)
        self.chk_auto_update = QCheckBox("Check yt-dlp updates on startup")
        self.chk_auto_update.setChecked(self.settings.get('check_ytdlp_updates_on_startup', True))
        self.chk_auto_update.toggled.connect(lambda c: self.settings.set('check_ytdlp_updates_on_startup', c))
        core_layout.addWidget(self.chk_auto_update)
        core_layout.addSpacing(15)

        self.chk_auto_check_playlists = QCheckBox("Check tracked playlists for new tracks on startup")
        self.chk_auto_check_playlists.setChecked(self.settings.get('check_playlists_on_startup', False))
        self.chk_auto_check_playlists.toggled.connect(lambda c: self.settings.set('check_playlists_on_startup', c))
        core_layout.addWidget(self.chk_auto_check_playlists)

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

        # 8. Data Backup & Migration (Export / Import AppData)
        lbl_backup = QLabel("Data Backup & Migration")
        lbl_backup.setStyleSheet("font-weight: bold; color: #94a3b8; margin-top: 10px; margin-bottom: 2px;")
        layout.addWidget(lbl_backup)

        backup_group = QWidget()
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setContentsMargins(15, 12, 15, 12)
        backup_layout.setSpacing(10)
        backup_group.setStyleSheet("""
            QWidget#BackupGroup {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
            }
        """)
        backup_group.setObjectName("BackupGroup")

        backup_desc = QLabel(
            "Export or restore your tracked playlists, custom settings, and download history to transfer between PCs or create backups."
        )
        backup_desc.setWordWrap(True)
        backup_desc.setStyleSheet("font-size: 12px; color: #94a3b8; line-height: 1.4;")
        backup_layout.addWidget(backup_desc)

        backup_btn_row = QHBoxLayout()
        btn_export_data = QPushButton("Export Backup (.zip)...")
        btn_export_data.setFixedHeight(32)
        btn_export_data.clicked.connect(self.export_app_data)

        btn_import_data = QPushButton("Import Backup (.zip)...")
        btn_import_data.setFixedHeight(32)
        btn_import_data.clicked.connect(self.import_app_data)

        backup_btn_row.addWidget(btn_export_data)
        backup_btn_row.addWidget(btn_import_data)
        backup_btn_row.addStretch()
        backup_layout.addLayout(backup_btn_row)

        layout.addWidget(backup_group)
        layout.addStretch()

        scroll.setWidget(scroll_wrapper)
        main_tab_layout = QVBoxLayout(self.settings_tab)
        main_tab_layout.setContentsMargins(0, 0, 0, 0)
        main_tab_layout.addWidget(scroll)
        self.tabs.addTab(self.settings_tab, "SETTINGS")

    def export_app_data(self):
        now_date = datetime.datetime.now().strftime("%Y-%m-%d")
        def_name = f"LogovoDownloads_Backup_{now_date}.zip"
        initial_dir = self.settings.get('last_selected_folder') or str(Path.home())
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Data Backup", os.path.join(initial_dir, def_name), "ZIP Archives (*.zip)")
        if save_path:
            ok, msg = export_backup(save_path)
            if ok:
                QMessageBox.information(self, "Backup Exported", f"Backup created successfully:\n{Path(save_path).name}")
            else:
                QMessageBox.warning(self, "Export Failed", msg)

    def import_app_data(self):
        initial_dir = self.settings.get('last_selected_folder') or str(Path.home())
        zip_path, _ = QFileDialog.getOpenFileName(self, "Select Backup ZIP File", initial_dir, "ZIP Archives (*.zip)")
        if zip_path:
            reply = QMessageBox.question(
                self,
                "Confirm Restore",
                "Restoring backup will overwrite current settings, playlists, and history.\nDo you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                ok, msg = import_backup(zip_path)
                if ok:
                    self.settings.data = self.settings.load()
                    self.playlists_mgr.playlists = self.playlists_mgr.load()
                    self.history.history = self.history.load()
                    self.refresh_playlists_ui()
                    self.refresh_history()
                    QMessageBox.information(self, "Backup Restored", "Data restored successfully! Your playlists and settings have been reloaded.")
                else:
                    QMessageBox.warning(self, "Restore Failed", msg)

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
        title.setStyleSheet("font-size: 26px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel(f"Version {APP_VERSION}")
        version.setStyleSheet("font-size: 13px; color: #38bdf8; font-weight: 600; margin-top: 2px; margin-bottom: 8px;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        desc = QLabel("Modern, High-Speed Media Downloader & Playlist Sync for Windows")
        desc.setStyleSheet("font-size: 12px; color: #94a3b8; margin-bottom: 20px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        btn_layout = QHBoxLayout()
        github = QPushButton("GitHub Repository")
        github.setMinimumWidth(200)
        github.setMaximumWidth(250)
        github.setStyleSheet("""
            QPushButton {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #334155;
                border-color: #38bdf8;
            }
        """)
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

    # ─── LOGOVO DOWNLOADS APP UPDATER (GITHUB RELEASES) ─────────────────────────

    def check_app_update_background(self):
        if not self.settings.get('check_app_updates_on_startup', True):
            return
        self._app_update_worker = CheckAppUpdateWorker(APP_VERSION)
        self._app_update_worker.finished_signal.connect(self._on_app_update_check_finished)
        self._app_update_worker.start()

    def _on_app_update_check_finished(self, has_update: bool, latest_ver: str, release_url: str, release_notes: str):
        if has_update:
            self.show_app_update_notification(latest_ver, release_url, release_notes)

    def manual_check_app_update(self):
        self.status_label.setText("Checking for Logovo Downloads updates on GitHub...")
        self._manual_app_update_worker = CheckAppUpdateWorker(APP_VERSION)
        def _on_manual_finished(has_update: bool, latest_ver: str, release_url: str, release_notes: str):
            if has_update:
                self.status_label.setText(f"New version v{latest_ver} available on GitHub!")
                self.show_app_update_notification(latest_ver, release_url, release_notes)
            else:
                self.status_label.setText(f"Latest version installed (v{APP_VERSION}).")
                self.show_side_notification(
                    title="Latest Version Installed",
                    message=f"You are using the latest version of Logovo Downloads (v{APP_VERSION}).",
                    level="info"
                )
        self._manual_app_update_worker.finished_signal.connect(_on_manual_finished)
        self._manual_app_update_worker.start()

    def show_app_update_notification(self, latest_ver: str, release_url: str, release_notes: str = ""):
        msg = f"A new version (v{latest_ver}) of Logovo Downloads is available on GitHub!\n(Current: v{APP_VERSION})\nClick below to view the release and download."
        self.show_side_notification(
            title=f"New Version Available: v{latest_ver}",
            message=msg,
            level="info",
            action_text="View Release",
            action_callback=lambda: QDesktopServices.openUrl(QUrl(release_url))
        )

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

                self.queue_container.setUpdatesEnabled(False)
                added_count = 0
                for link in links:
                    if link:
                        platform = detect_platform_name(link)
                        self._add_single_item_to_queue({
                            'url': link,
                            'title': "Fetching media info...", 
                            'uploader': "Loading artist...",
                            'platform': platform,
                            'media_type_category': selected_type,
                            'media_type': "Audio (Best)" if selected_type == "Audio" else "Video (Best)"
                        }, batch=True)
                        added_count += 1
                self.queue_container.setUpdatesEnabled(True)
                self.update_queue_ui()
                self.status_label.setText(f"Added {added_count} links from file.")
            except Exception as e:
                self.queue_container.setUpdatesEnabled(True)
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
        target_folder = None
        for widget in reversed(self.download_queue):
            p_dir = widget.item_data.get('playlist_output_dir')
            if p_dir and os.path.exists(p_dir):
                target_folder = p_dir
                break

        if not target_folder:
            target_folder = self.settings.get('download_path')

        if target_folder and os.path.exists(target_folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target_folder))
        else:
            QMessageBox.warning(self, "Folder Not Found", f"Directory does not exist:\n{target_folder}")

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
                if widget.status_state == "Pending" and hasattr(widget, 'set_media_category'):
                    widget.set_media_category(new_type)

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

            for it in (item_date, item_author, item_title, item_plat, item_status):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)

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

        platform = detect_platform_name(url)
        self.status_label.setText(f"Fetching info from {platform} in background...")
        self.btn_add_queue.setEnabled(False)
        self.loading_overlay.show_loading("Fetching Media Info...", f"Connecting to {platform}...")

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
                search_u = preview.get('url')
                if search_u and str(search_u).startswith('ytsearch'):
                    preview['url'] = search_u
                    preview['original_url'] = url
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
        downloaded_items = [w for w in self.download_queue if w.status_state == "Success" and "Skipped" not in w.status_label.text()]
        skipped_items = [w for w in self.download_queue if w.status_state == "Success" and "Skipped" in w.status_label.text()]
        error_items = [w for w in self.download_queue if w.status_state == "Error"]
        unavail_items = [w for w in self.download_queue if w.status_state == "Unavailable"]
        pending_items = [w for w in self.download_queue if w.status_state in ("Pending", "Downloading", "Retrying")]

        downloaded_count = len(downloaded_items)
        skipped_count = len(skipped_items)
        pending_count = len(pending_items)
        error_count = len(error_items)
        unavail_count = len(unavail_items)

        # Top telemetry text
        if total == 0:
            self.top_telemetry_label.setText("")
        else:
            downloaded_mb = sum(estimate_track_size_mb(w.item_data) for w in downloaded_items + skipped_items)
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

        stats_parts = []
        if downloaded_count > 0 or (skipped_count == 0 and error_count == 0 and unavail_count == 0):
            stats_parts.append(f"Downloaded: {downloaded_count}")
        if skipped_count > 0:
            stats_parts.append(f"Skipped: {skipped_count}")
        stats_parts.append(f"Queue: {pending_count}")
        stats_parts.append(f"Errors: {error_count}")
        if unavail_count > 0:
            stats_parts.append(f"Unavailable: {unavail_count}")

        self.stats_label.setText(" | ".join(stats_parts))
        self.stats_label.setToolTip("\n".join(stats_parts))

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

        pending_count = sum(1 for w in self.download_queue if w.status_state == "Pending")
        current_concurrency = max(1, int(self.settings.get('max_concurrent_downloads', 3)))

        # Prompt for Safe Mode if queue is large (> 150 items) and concurrency > 3
        if pending_count > 150 and current_concurrency > 3 and not getattr(self, '_safe_mode_choice_remembered', False):
            dlg = SafeModeDialog(pending_count, current_concurrency, parent=self)
            if dlg.exec():
                if dlg.chk_remember.isChecked():
                    self._safe_mode_choice_remembered = True
                    self._safe_mode_enabled = dlg.enable_safe_mode
                self._current_session_concurrency = 3 if dlg.enable_safe_mode else current_concurrency
                self._current_session_delay = 1.0 if dlg.enable_safe_mode else 0.2
            else:
                return
        elif getattr(self, '_safe_mode_choice_remembered', False) and getattr(self, '_safe_mode_enabled', False):
            self._current_session_concurrency = 3
            self._current_session_delay = 1.0
        else:
            self._current_session_concurrency = current_concurrency
            self._current_session_delay = 0.2

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

        max_concurrency = getattr(self, '_current_session_concurrency', max(1, int(self.settings.get('max_concurrent_downloads', 3))))

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
                        if p_dir: dirs_to_clean.add(os.path.normpath(p_dir))
                    for d in dirs_to_clean:
                        cleanup_orphan_files(d)
                        clear_failed_log_if_clean(d)

                    # Update playlists sync info if any playlist directory was downloaded
                    for p in self.playlists_mgr.get_all():
                        p_folder = p.get('folder_path')
                        if p_folder and os.path.normpath(p_folder) in dirs_to_clean and os.path.exists(p_folder):
                            media_exts = {".mp3", ".flac", ".m4a", ".opus", ".ogg", ".wav", ".aac", ".alac", ".mp4", ".mkv", ".webm", ".avi", ".mov"}
                            local_cnt = len([f for f in Path(p_folder).iterdir() if f.is_file() and f.suffix.lower() in media_exts and f.stat().st_size >= 500*1024])
                            pl_track_count = p.get('track_count', 0)
                            unavail_cnt = p.get('unavailable_count', 0)
                            avail = max(0, pl_track_count - unavail_cnt)
                            missing_left = max(0, avail - local_cnt)
                            p['new_tracks_count'] = missing_left
                            if missing_left == 0 and (avail > 0 or pl_track_count > 0):
                                p['status'] = 'synced'
                            p['last_synced'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                    self.playlists_mgr.save()

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
            jitter = getattr(self, '_current_session_delay', 0.2)
            time.sleep(jitter)

    def start_worker_for_widget(self, widget: QueueItemWidget):
        item_data = widget.item_data
        url = item_data['url']
        if "spotify.com" in str(url):
            title = item_data.get('title', '')
            author = item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or ''
            query = f"{author} - {title}".strip(" - ") if (author or title) else title
            if query:
                url = f"ytsearch1:{query}"
                item_data['url'] = url

        media_type = widget.format_combo.currentText() if hasattr(widget, 'format_combo') else item_data.get('media_type', 'Audio (Best)')
        item_data['media_type'] = media_type
        output_dir = item_data.get('playlist_output_dir') or self.settings.get('download_path')

        platform = detect_platform_name(url)
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
        platform = detect_platform_name(url)

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
            if is_rate_limited(error_msg):
                widget.set_status("Rate-limited (YouTube)", "Error")
                self.failed_queue.append((item_data, "YouTube Rate Limit — try again later"))
                status_text = "Error: YouTube Rate Limit"
            elif is_platform_unavailable(error_msg):
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
