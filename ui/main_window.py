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
    QSystemTrayIcon, QMenu, QSpinBox, QSlider, QFrame,
    QTextEdit, QTabBar, QLayout
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl, QObject, QEvent, QMimeData, QPropertyAnimation, QPoint, QEasingCurve, QRectF
from PyQt6.QtGui import QPixmap, QDesktopServices, QAction, QIcon, QColor, QPainter, QPen, QDrag, QPainterPath, QFont

from core.preview import get_video_preview
from core.downloader import (
    friendly_error,
    is_platform_unavailable,
    is_rate_limited,
    detect_platform_name,
    set_folder_icon,
    save_playlist_cover_image,
    apply_playlist_cover_settings,
    ensure_nomedia_file,
    clear_failed_log_if_clean,
    cleanup_orphan_files,
    is_file_already_downloaded,
    read_stem_vid_map,
    read_stem_all_vids_map,
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
    read_kept_orphans,
    clear_kept_orphans,
)
from core.constants import APP_VERSION
from core.utils import clean_filename_for_all_devices
from core.settings import SettingsManager, get_app_data_dir
from core.queue_state import load_pending_queue, save_pending_queue
from core.history import (
    HistoryManager,
    get_retryable_error_entries,
    is_retryable_error,
    sanitize_download_options,
    snapshot_download_settings,
)
from core.taskbar import taskbar_manager
from core.backup import export_backup, import_backup
from core.playlists_manager import PlaylistsManager
from core.updater import (
    check_latest_ytdlp_version,
    CheckUpdateThread,
    UpgradeWorker,
)
from ui.styles import (
    configure_combo_popup,
    get_resource_path,
    get_stylesheet,
    get_theme_colors,
    normalize_theme,
    square_combo_popup,
    theme_stylesheet,
)
from ui.dialogs import (
    OnlineDuplicatesDialog,
    PlaylistFormatMismatchDialog,
    PlaylistSyncPreviewDialog,
    PlaylistUpToDateDialog,
    SafeModeDialog,
    UnavailableTracksDialog,
    detect_and_prompt_orphans,
)
from ui.storage_cleanup_dialog import StorageCleanupDialog
from ui.workers import (
    ApplyPlaylistSyncWorker,
    CheckAppUpdateWorker,
    DownloadSettingsOverlay,
    FetchPreviewWorker,
    NetworkDiagnosticsWorker,
    ReindexPlaylistWorker,
    SelfDiagnosticsWorker,
    StartupPlaylistCheckWorker,
    SyncPlaylistWorker,
    WorkerThread,
)
from ui.queue_item import QueueItemWidget
from ui.log_viewer_dialog import LogViewerDialog
from ui.playlist_comparison_dialog import CrossPlaylistComparisonDialog


def _resolve_queue_media_type(selected_media_type, saved_options, item_data):
    """Prefer the format visible on the queue item over a stale retry snapshot."""
    return (
        selected_media_type
        or saved_options.get('media_type')
        or item_data.get('media_type')
        or 'Audio (Best)'
    )


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


class SpinnerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.accent_color = get_theme_colors()["accent"]
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate)
        self.timer.start(30)

    def set_theme(self, theme_name: str):
        self.accent_color = get_theme_colors(theme_name)["accent"]
        self.update()

    def rotate(self):
        self.angle = (self.angle + 15) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(self.angle)
        pen = QPen(QColor(self.accent_color), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
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
                background-color: #0b120d;
                border: 1px solid #91e5a3;
                border-radius: 0px;
            }
        """)

        card_layout = QVBoxLayout(card)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.setSpacing(10)
        card_layout.setContentsMargins(24, 20, 24, 20)

        self.spinner = SpinnerWidget()
        self.title_label = QLabel("Syncing Playlist...")
        self.title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #cbd5cc;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.msg_label = QLabel("Connecting to service...")
        self.msg_label.setStyleSheet("font-size: 12px; color: #aab7aa;")
        self.msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.msg_label.setWordWrap(True)

        self.sub_label = QLabel("Fetching media information in the background...")
        self.sub_label.setStyleSheet("font-size: 11px; color: #849184;")
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sub_label.setWordWrap(True)

        card_layout.addWidget(self.spinner, 0, Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.msg_label)
        card_layout.addWidget(self.sub_label)

        layout.addWidget(card)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(8, 11, 9, 200))
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
            self.setStyleSheet(theme_stylesheet(
                "QWidget#PlaylistCard { border: 2px solid #91e5a3; background-color: #0b120d; }",
                self.property("_ui_theme"),
            ))

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
        self.theme_colors = get_theme_colors()

        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(30)
        self._spinner_timer.timeout.connect(self._on_spinner_tick)

    def set_theme(self, theme_name: str):
        self.theme_colors = get_theme_colors(theme_name)
        self.update()

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

    def wheelEvent(self, event):
        # Keep wheel scrolling from changing the current section.
        event.accept()

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
                    overlay_color = QColor(self.theme_colors["card_bg"])
                    overlay_color.setAlpha(235)
                    p.setBrush(overlay_color)
                else:
                    overlay_color = QColor(self.theme_colors["root_bg"])
                    overlay_color.setAlpha(210)
                    p.setBrush(overlay_color)
                p.drawRect(QRectF(overlay_rect))

                # Centered spinning loader circle directly in the middle of the tab
                cx = rect.center().x()
                cy = rect.center().y()
                p.save()
                p.translate(cx, cy)
                p.rotate(self.spinner_angle)
                pen = QPen(QColor(self.theme_colors["accent"]), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(QRectF(-7, -7, 14, 14), 0, 270 * 16)
                p.restore()
            elif self.pl_has_new or self.pl_has_removed:
                # Clean badges in the upper right corner of the tab pill
                by = rect.top() + 5
                if self.pl_has_new and self.pl_has_removed:
                    bw = 25
                    bx = rect.right() - bw - 4
                    p.setPen(QPen(QColor(self.theme_colors["accent_fill"]), 1))
                    p.setBrush(QColor(self.theme_colors["root_bg"]))
                    p.drawRect(QRectF(bx, by, bw, 14))
                    p.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
                    p.setPen(QColor(self.theme_colors["accent_fill"]))
                    p.drawText(QRectF(bx + 1, by, 11, 14), Qt.AlignmentFlag.AlignCenter, "+")
                    p.setPen(QColor("#d98f86"))
                    p.drawText(QRectF(bx + 12, by, 11, 14), Qt.AlignmentFlag.AlignCenter, "-")
                elif self.pl_has_new:
                    bw = 14
                    bx = rect.right() - bw - 5
                    p.setPen(QPen(QColor(self.theme_colors["accent_fill"]), 1))
                    p.setBrush(QColor(self.theme_colors["new_badge_bg"]))
                    p.drawRect(QRectF(bx, by, bw, 14))
                    p.setPen(QColor(self.theme_colors["accent_fill"]))
                    p.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
                    p.drawText(QRectF(bx, by, bw, 14), Qt.AlignmentFlag.AlignCenter, "+")
                elif self.pl_has_removed:
                    bw = 14
                    bx = rect.right() - bw - 5
                    p.setPen(QPen(QColor("#d98f86"), 1))
                    p.setBrush(QColor("#281715"))
                    p.drawRect(QRectF(bx, by, bw, 14))
                    p.setPen(QColor("#d98f86"))
                    p.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
                    p.drawText(QRectF(bx, by, bw, 14), Qt.AlignmentFlag.AlignCenter, "-")
            p.end()


class SideNotificationToast(QFrame):
    def __init__(self, title: str, message: str, level: str = "warning", action_text: str = None, action_callback=None, parent=None):
        super().__init__(parent)
        self.setObjectName("SideNotificationToast")
        self.setFixedWidth(330)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._accent_color = "#91e5a3" if level != "error" else "#d98f86"

        # Match app's dark slate card theme perfectly
        self.setStyleSheet("""
            QFrame#SideNotificationToast {
                background-color: #0b120d;
                border: 1px solid #354a38;
                border-radius: 0px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # Header Row
        h_row = QHBoxLayout()
        h_row.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #cbd5cc; background: transparent;")
        h_row.addWidget(title_lbl, 1)

        btn_close = QPushButton("x")
        btn_close.setToolTip("Dismiss notification")
        btn_close.setFixedSize(18, 18)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_close.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #849184;
                border: none;
                font-size: 11px;
                font-weight: bold;
                padding: 0px;
            }
            QPushButton:hover {
                color: #cbd5cc;
            }
        """)
        btn_close.clicked.connect(self.close_animated)
        h_row.addWidget(btn_close)
        layout.addLayout(h_row)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setStyleSheet("font-size: 11px; color: #aab7aa; background: transparent; line-height: 1.35;")
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
                    background-color: #14271a;
                    color: #a6efb4;
                    border: 1px solid #91e5a3;
                    border-radius: 0px;
                    font-size: 11px;
                    font-weight: bold;
                    padding: 2px 12px;
                }
                QPushButton:hover {
                    background-color: #1a3422;
                    border-color: #b5f2bf;
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
        self.setMinimumSize(880, 640)
        self.settings = SettingsManager()
        self.ui_theme = normalize_theme(self.settings.get("ui_theme", "green"))
        self.theme_colors = get_theme_colors(self.ui_theme)
        self.setStyleSheet(get_stylesheet(self.ui_theme))

        icon_path = get_resource_path("media/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setup_tray()

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
        self._diagnostics_worker = None
        self.is_downloading = False
        self._stop_requested = False
        self._pause_requested = False
        self._closing_after_pause = False
        self._close_confirmed = False
        self._ending_workers = []
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
        self.custom_tab_bar.set_theme(self.ui_theme)
        self.tabs.setTabBar(self.custom_tab_bar)
        self.layout.addWidget(self.tabs)

        self.setup_downloads_tab()
        self.setup_playlists_tab()
        self.setup_history_tab()
        self.setup_settings_tab()
        self.setup_about_tab()

        self._apply_ui_theme(self.ui_theme)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

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
        self.loading_overlay.spinner.set_theme(self.ui_theme)
        self.loading_overlay.hide()

        # Check cookies configuration on startup
        QTimer.singleShot(700, self.check_cookies_file_validity)

        # Check Logovo Downloads app updates on startup
        if self.settings.get('check_app_updates_on_startup', True):
            QTimer.singleShot(1800, self.check_app_update_background)
        QTimer.singleShot(0, self._offer_queue_restore)

    def _save_queue(self):
        if getattr(self, "_restoring_queue", False):
            return
        items = []
        for widget in self.download_queue:
            if widget.status_state not in ("Success", "Error", "Unavailable"):
                data = dict(widget.item_data)
                data["media_type"] = widget.format_combo.currentText()
                if not data.get("download_options"):
                    media_type = data["media_type"]
                    is_audio = media_type.startswith("Audio")
                    specific_subs = data.get("specific_subs")
                    if not specific_subs or specific_subs in ("Default", "Global", "Default (Settings)"):
                        subtitles = {
                            "download": self.settings.get("download_audio_lyrics" if is_audio else "download_subtitles", False),
                            "langs": self.settings.get("lyrics_langs" if is_audio else "subtitles_langs", "orig"),
                        }
                    else:
                        subtitles = {"download": specific_subs != "None", "langs": specific_subs}
                    source_url = data.get("original_url") or data.get("url")
                    data["download_options"] = {
                        "source_url": source_url,
                        "output_dir": str(data.get("playlist_output_dir") or self.settings.get("download_path")),
                        "quality": self.settings.get_quality(detect_platform_name(source_url)),
                        "subtitles": subtitles,
                        "speed_limit": self.settings.get("speed_limit", "Unlimited"),
                        "naming_pattern": self.settings.get("naming_pattern", "{artist} - {title}") if is_audio else self.settings.get("video_naming_pattern", "{title}"),
                        "format_compat": data.get("format_compat"),
                        "playlist_index": data.get("playlist_index"),
                        "playlist_count": data.get("playlist_count"),
                        "thumbnail": data.get("thumbnail"),
                        "settings": snapshot_download_settings(self.settings),
                    }
                items.append(data)
        if getattr(self, "_restore_deferred", False):
            # A declined restore must survive new work in this session, even after
            # the new queue finishes. Replaced entries should not reappear.
            replaced = getattr(self, "_deferred_replaced_keys", set())
            replaced.update((item.get("url"), item.get("media_type")) for item in items)
            self._deferred_replaced_keys = replaced
            items = [
                item for item in load_pending_queue()
                if (item.get("url"), item.get("media_type")) not in replaced
            ] + items
        try:
            save_pending_queue(items)
        except OSError as exc:
            self.status_label.setText(f"Could not save download queue: {exc}")

    def _offer_queue_restore(self):
        saved = load_pending_queue()
        if not saved:
            return
        choice = QMessageBox.question(
            self, "Resume downloads",
            f"Restore {len(saved)} unfinished download(s) from the previous session?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if choice != QMessageBox.StandardButton.Yes:
            # Leave the snapshot and fragments available on the next launch.
            self._restore_deferred = True
            return
        self._restoring_queue = True
        try:
            for item in saved:
                self._add_single_item_to_queue(item, batch=True, preserve_subtitle_defaults=True)
        finally:
            self._restoring_queue = False
        self._save_queue()
        self.update_queue_ui()
        self.status_label.setText(f"Restored {len(saved)} unfinished download(s).")
        self.start_queue()

    def closeEvent(self, event):
        if getattr(self, "upgrade_worker", None) is not None and self.upgrade_worker.isRunning():
            event.ignore()
            QMessageBox.information(self, "Update in progress", "Wait for the yt-dlp update to finish before exiting.")
            return
        if self.active_workers and not self._close_confirmed:
            choice = QMessageBox.question(
                self, "Exit during download?",
                "A download is still in progress. Exit and save unfinished downloads for next launch?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if choice != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._close_confirmed = True
        self._save_queue()
        if self.active_workers:
            event.ignore()
            self._closing_after_pause = True
            self.pause_download()
            self.status_label.setText("Waiting for active downloads to pause before closing...")
            return
        if any(thread.isRunning() for thread in self._ending_workers):
            event.ignore()
            self._closing_after_pause = True
            self._finish_close_if_ready()
            return
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def _apply_ui_theme_to_widget(self, widget: QWidget):
        widget.setProperty("_ui_theme", self.ui_theme)
        if isinstance(widget, QComboBox):
            configure_combo_popup(widget, self.ui_theme)

        stylesheet = widget.styleSheet()
        themed_stylesheet = theme_stylesheet(stylesheet, self.ui_theme)
        if themed_stylesheet != stylesheet:
            widget.setStyleSheet(themed_stylesheet)

    def _apply_ui_theme(self, theme_name: str):
        self.ui_theme = normalize_theme(theme_name)
        self.theme_colors = get_theme_colors(self.ui_theme)
        self.setStyleSheet(get_stylesheet(self.ui_theme))

        self._apply_ui_theme_to_widget(self)
        for widget in self.findChildren(QWidget):
            self._apply_ui_theme_to_widget(widget)

        if hasattr(self, "custom_tab_bar"):
            self.custom_tab_bar.set_theme(self.ui_theme)
        if hasattr(self, "loading_overlay"):
            self.loading_overlay.spinner.set_theme(self.ui_theme)
        for queue_item in self.findChildren(QueueItemWidget):
            queue_item.set_theme(self.ui_theme)
        if hasattr(self, "history_table"):
            self.refresh_history()

    def _on_ui_theme_changed(self, theme_name: str):
        theme_name = normalize_theme(theme_name)
        if theme_name == self.ui_theme:
            return
        self._apply_ui_theme(theme_name)
        self.settings.set("ui_theme", theme_name)

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "settings_sections")
            and watched is self.settings_sections.tabBar()
            and event.type() == QEvent.Type.Wheel
        ):
            return True
        if (
            isinstance(watched, QFrame)
            and watched.objectName() == "TerminalComboPopup"
            and event.type() in (QEvent.Type.Show, QEvent.Type.Resize)
        ):
            square_combo_popup(watched)
            QTimer.singleShot(0, lambda popup=watched: square_combo_popup(popup))
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget):
            self._apply_ui_theme_to_widget(watched)
        return super().eventFilter(watched, event)

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
            self.cookies_file_input.setStyleSheet("border: 2px solid #d9b66d; background-color: #0b120d;")
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
        quit_action.triggered.connect(self.close)

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
        self.downloads_tab.setObjectName("DownloadsTab")
        layout = QVBoxLayout(self.downloads_tab)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(13)

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

        # Stats (Left) & Format Selection / Add to Queue (Right)
        queue_layout = QHBoxLayout()
        self.stats_label = QLabel("Success: 0 | In queue: 0 | Errors: 0")
        queue_layout.addWidget(self.stats_label)
        queue_layout.addStretch()

        self.btn_clear_queue = QPushButton("Clear Queue")
        self.btn_clear_queue.clicked.connect(self.clear_queue)
        self.btn_clear_queue.setMinimumHeight(30)
        queue_layout.addWidget(self.btn_clear_queue)

        self.lbl_format_type = QLabel("Type:")
        queue_layout.addWidget(self.lbl_format_type)
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
        self.subs_combo.currentTextChanged.connect(self.on_main_subs_combo_changed)
        queue_layout.addWidget(self.subs_combo)
        self.update_main_subs_combo_state()

        self.btn_add_queue = QPushButton("Add to queue")
        self.btn_add_queue.setObjectName("PrimaryButton")
        self.btn_add_queue.clicked.connect(self.add_to_queue_action)
        self.btn_add_queue.setMinimumHeight(30)
        queue_layout.addWidget(self.btn_add_queue)

        layout.addLayout(queue_layout)

        # Status Label below Queue Area
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #aab7aa;")
        layout.addWidget(self.status_label)

        # Global Progress Bar
        self.global_progress = QProgressBar()
        self.global_progress.setFixedHeight(6)
        self.global_progress.setTextVisible(False)
        self.global_progress.setRange(0, 100)
        self.global_progress.setValue(0)
        self.global_progress.setStyleSheet("""
            QProgressBar {
                background-color: #080d09;
                border: none;
                border-radius: 0px;
            }
            QProgressBar::chunk {
                background-color: #91e5a3;
                border-radius: 0px;
            }
        """)
        layout.addWidget(self.global_progress)

        # Bottom Actions Bar (Open Folder & Logs Left, Action Buttons Right)
        bottom_actions = QHBoxLayout()
        self.btn_open_folder = QPushButton("Open Folder")
        self.btn_open_folder.clicked.connect(self.open_downloads_folder)

        self.btn_logs = QPushButton("Logs")
        self.btn_logs.clicked.connect(self.open_logs_file)

        bottom_actions.addWidget(self.btn_open_folder)
        bottom_actions.addWidget(self.btn_logs)
        bottom_actions.addStretch()

        self.btn_download_all = QPushButton("Download")
        self.btn_download_all.setObjectName("PrimaryButton")
        self.btn_download_all.setEnabled(False)
        self.btn_download_all.clicked.connect(self.start_queue)

        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_download)
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.pause_download)

        self.btn_clear_completed = QPushButton("Clear Completed")
        self.btn_clear_completed.clicked.connect(self.clear_completed)

        bottom_actions.addWidget(self.btn_clear_completed)
        bottom_actions.addWidget(self.btn_pause)
        bottom_actions.addWidget(self.btn_stop)
        bottom_actions.addWidget(self.btn_download_all)

        layout.addLayout(bottom_actions)
        self.tabs.addTab(self.downloads_tab, "DOWNLOADS")

    # ─── TAB 2: PLAYLISTS ──────────────────────────────────────────────────────

    def setup_playlists_tab(self):
        self.playlists_tab = QWidget()
        self.playlists_tab.setObjectName("PlaylistsTab")
        layout = QVBoxLayout(self.playlists_tab)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(13)

        # Top Bar
        top_bar = QHBoxLayout()
        btn_track_new = QPushButton("+ Track New Playlist")
        btn_track_new.setObjectName("PrimaryButton")
        btn_compare = QPushButton("Compare Playlists")
        btn_compare.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_compare.setStyleSheet("""
            QPushButton {
                background-color: #0b120d;
                color: #91e5a3;
                border: 1px solid #65c77e;
                border-radius: 0px;
                padding: 6px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1a3422;
                color: #cbd5cc;
            }
        """)

        lbl_sort = QLabel("Sort:")
        lbl_sort.setStyleSheet("font-size: 12px; color: #aab7aa; font-weight: bold; margin-left: 10px;")

        self.combo_playlist_sort = QComboBox()
        self.combo_playlist_sort.setStyleSheet("""
            QComboBox {
                background-color: #0b120d;
                color: #cbd5cc;
                border: 1px solid #354a38;
                border-radius: 0px;
                padding: 5px 12px;
                font-size: 12px;
                font-weight: 500;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #080b09;
                color: #cbd5cc;
                selection-background-color: #1a3020;
                selection-color: #cbd5cc;
            }
        """)
        self.combo_playlist_sort.blockSignals(True)
        self.combo_playlist_sort.addItem("Manual Order (Drag & Drop)", "custom")
        self.combo_playlist_sort.addItem("Name (A → Z)", "name_asc")
        self.combo_playlist_sort.addItem("Name (Z → A)", "name_desc")
        self.combo_playlist_sort.addItem("Tracks (Most → Fewest)", "tracks_desc")
        self.combo_playlist_sort.addItem("Tracks (Fewest → Most)", "tracks_asc")
        self.combo_playlist_sort.addItem("Last Synced (Newest)", "synced_desc")
        self.combo_playlist_sort.addItem("OS Format (Windows First)", "format_win")
        self.combo_playlist_sort.addItem("OS Format (UNIX First)", "format_unix")

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
        self.lbl_playlists_count.setStyleSheet("font-size: 12px; color: #aab7aa;")

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
        self.lbl_pl_stats.setStyleSheet("color: #354a38; font-size: 11px; padding: 4px 8px;")
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
            empty_lbl.setStyleSheet("color: #849184; font-size: 14px; margin-top: 60px;")
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
                    background-color: #0b120d;
                    color: #aab7aa;
                    border: 1px solid #354a38;
                    border-radius: 0px;
                    font-size: 10px;
                    padding: 0px;
                }
                QPushButton:hover:enabled {
                    background-color: #23442c;
                    color: #cbd5cc;
                    border-color: #65c77e;
                }
                QPushButton:disabled {
                    color: #354a38;
                    background-color: #080b09;
                    border-color: #0b120d;
                }
            """)
            card.btn_up = btn_up
            btn_up.clicked.connect(lambda _, c=card: self._move_playlist_item(c.index, c.index - 1))

            drag_hint = QLabel("::")
            drag_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            drag_hint.setToolTip("Drag & drop with mouse to reorder")
            drag_hint.setStyleSheet("color: #849184; font-size: 13px; font-weight: bold;")

            btn_down = QPushButton("▼")
            btn_down.setFixedSize(24, 20)
            btn_down.setToolTip("Move playlist down")
            btn_down.setEnabled(i < len(items) - 1)
            btn_down.setStyleSheet("""
                QPushButton {
                    background-color: #0b120d;
                    color: #aab7aa;
                    border: 1px solid #354a38;
                    border-radius: 0px;
                    font-size: 10px;
                    padding: 0px;
                }
                QPushButton:hover:enabled {
                    background-color: #23442c;
                    color: #cbd5cc;
                    border-color: #65c77e;
                }
                QPushButton:disabled {
                    color: #354a38;
                    background-color: #080b09;
                    border-color: #0b120d;
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
            thumb_lbl.setStyleSheet("background-color: #080b09; border-radius: 0px;")
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
                thumb_lbl.setText(p.get('media_type', 'Audio'))

            card_layout.addWidget(thumb_lbl)

            # Details
            info_layout = QVBoxLayout()
            title_row = QHBoxLayout()
            title_row.setSpacing(8)
            title_row.setContentsMargins(0, 0, 0, 0)
            title_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            title_lbl = QLabel(p.get('title', 'Untitled Playlist'))
            title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #cbd5cc;")
            title_row.addWidget(title_lbl)

            # Format Badge (Windows, UNIX, Unix/Win)
            pl_format = p.get('format_compat')
            if not pl_format and folder_str:
                from core.downloader import read_playlist_format
                pl_format = read_playlist_format(folder_str)
            if not pl_format:
                pl_format = 'windows'

            badge_lbl = QLabel()
            badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if pl_format in ('unix/win', 'mixed'):
                badge_lbl.setText("Unix/Win")
                badge_lbl.setStyleSheet(
                    "background-color: #2b2414; color: #d9b66d; font-size: 10px; font-weight: bold; "
                    "padding: 2px 7px; border-radius: 0px;"
                )
            elif pl_format == 'unix':
                badge_lbl.setText("UNIX")
                badge_lbl.setStyleSheet(
                    "background-color: #2b2414; color: #d9b66d; font-size: 10px; font-weight: bold; "
                    "padding: 2px 7px; border-radius: 0px;"
                )
            else:
                badge_lbl.setText("Windows")
                badge_lbl.setStyleSheet(
                    "background-color: #14271a; color: #a6efb4; font-size: 10px; font-weight: bold; "
                    "padding: 2px 7px; border-radius: 0px;"
                )
            title_row.addWidget(badge_lbl)
            title_row.addStretch()
            info_layout.addLayout(title_row)

            path_lbl = QLabel(p.get('folder_path', ''))
            path_lbl.setStyleSheet("font-size: 11px; color: #aab7aa;")

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
                    count_str = f"<b>{downloaded_count}</b> / <b>{pl_track_count}</b> tracks <span style='color: #aab7aa;'>(Up to date — {', '.join(notes)})</span>"
                else:
                    count_str = f"<b>{downloaded_count}</b> / <b>{pl_track_count}</b> tracks <span style='color: #aab7aa;'>(Up to date)</span>"
                status_color = "#65c77e"
                new_cnt = 0
                if p.get('new_tracks_count', 0) != 0:
                    p['new_tracks_count'] = 0
                    self.playlists_mgr.save()
            else:
                count_str = f"<b>{downloaded_count}</b> / <b>{pl_track_count}</b> tracks"
                status_color = "#91e5a3"
                raw_new = p.get('new_tracks_count', 0)
                missing_upper_bound = max(0, available_track_count - downloaded_count)
                new_cnt = min(raw_new, missing_upper_bound) if raw_new > 0 else 0
                if p.get('new_tracks_count') != new_cnt:
                    p['new_tracks_count'] = new_cnt
                    self.playlists_mgr.save()

            badge_html = f"  <span style='color: #91e5a3; font-weight: bold; background-color: #080b09; padding: 2px 6px; border-radius: 0px; border: 1px solid #65c77e;'>+{new_cnt} new</span>" if new_cnt > 0 else ""
            raw_removed = p.get('removed_tracks_count', 0)
            badge_removed_html = f"  <span style='color: #d98f86; font-weight: bold; background-color: #281715; padding: 2px 6px; border-radius: 0px; border: 1px solid #70413d;'>-{raw_removed} removed</span>" if raw_removed > 0 else ""

            kept_set = read_kept_orphans(folder_str) if folder_str and os.path.exists(folder_str) else set()
            kept_count = len({Path(f).name for f in kept_set if (Path(folder_str) / f).is_file()}) if folder_str else 0
            badge_kept_html = f"  <span style='color: #d9b66d; font-weight: bold; background-color: #2b2414; padding: 2px 6px; border-radius: 0px; border: 1px solid #6e5a29;'>{kept_count} kept</span>" if kept_count > 0 else ""

            last_sync_str = p.get('last_synced', 'Never')
            meta_lbl = QLabel(f"In Folder: {count_str}{badge_html}{badge_removed_html}{badge_kept_html}  <span style='color: #354a38;'>•</span>  <span style='color: #aab7aa;'>Synced: {last_sync_str}</span>")
            meta_lbl.setTextFormat(Qt.TextFormat.RichText)
            meta_lbl.setStyleSheet(f"font-size: 11px; color: {status_color}; font-weight: 500; background: transparent;")
            meta_lbl.setWordWrap(True)

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

            if kept_count > 0:
                btn_kept = QPushButton(f"Kept ({kept_count})")
                btn_kept.setFixedSize(75, 32)
                btn_kept.setToolTip("Click to reset kept tracks list and re-evaluate them on next sync")
                btn_kept.setStyleSheet("""
                    QPushButton {
                        background-color: #2b2414;
                        color: #d9b66d;
                        border: 1px solid #6e5a29;
                        border-radius: 0px;
                        font-size: 11px;
                        font-weight: bold;
                        padding: 0px;
                    }
                    QPushButton:hover {
                        background-color: #433619;
                        color: #cbd5cc;
                    }
                """)
                def _on_reset_kept(folder=folder_str, pl_title=p.get('title'), k_cnt=kept_count):
                    reply = QMessageBox.question(
                        self, "Reset Kept Tracks",
                        f"Reset the list of {k_cnt} kept track(s) in '{pl_title}'?\n\nOn the next Sync, these files will be re-evaluated against the online playlist.",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        clear_kept_orphans(folder)
                        self.refresh_playlists_ui()
                        self.status_label.setText(f"Kept tracks reset for '{pl_title}'.")
                btn_kept.clicked.connect(lambda _, f=folder_str, t=p.get('title'), c=kept_count: _on_reset_kept(f, t, c))
                btn_box.addWidget(btn_kept)

            card.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            def _show_card_context_menu(pos, pl=p, folder=folder_str, k_cnt=kept_count):
                menu = QMenu(self)
                act_sync = menu.addAction("Sync Playlist")
                act_reindex = menu.addAction("Re-index Tracks (1..N)")
                act_redownload = menu.addAction("Re-download from Scratch...")
                act_folder = menu.addAction("Open Folder")
                act_reset_k = None
                if k_cnt > 0:
                    act_reset_k = menu.addAction(f"Reset Kept Tracks ({k_cnt})")
                menu.addSeparator()
                act_del = menu.addAction("Remove from Tracking")
                chosen = menu.exec(card.mapToGlobal(pos))
                if chosen == act_sync:
                    self.sync_tracked_playlist(pl)
                elif chosen == act_reindex:
                    self.reindex_tracked_playlist(pl)
                elif chosen == act_redownload:
                    self.redownload_tracked_playlist(pl)
                elif chosen == act_folder:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
                elif act_reset_k and chosen == act_reset_k:
                    clear_kept_orphans(folder)
                    self.refresh_playlists_ui()
                    self.status_label.setText(f"Kept tracks reset for '{pl.get('title')}'.")
                elif chosen == act_del:
                    self.remove_tracked_playlist(pl.get('url'))

            card.customContextMenuRequested.connect(_show_card_context_menu)

            btn_remove = QPushButton("x")
            btn_remove.setFixedSize(32, 32)
            btn_remove.setToolTip("Remove from tracking")
            btn_remove.setStyleSheet("""
                QPushButton {
                    background-color: #0b120d;
                    color: #d98f86;
                    border: 1px solid #354a38;
                    border-radius: 0px;
                    font-size: 15px;
                    font-weight: bold;
                    padding: 0px;
                }
                QPushButton:hover {
                    background-color: #522723;
                    color: #cbd5cc;
                    border: 1px solid #d98f86;
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
        btn_ok = QPushButton("Save Playlist")
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

            active_compat = self.settings.get('filename_compat', 'windows')
            self.playlists_mgr.add_playlist(
                url=url,
                title=title,
                folder_path=final_folder,
                thumbnail=thumb,
                track_count=count,
                media_type=type_combo.currentText(),
                format_compat=active_compat
            )
            self.refresh_playlists_ui()
            self.status_label.setText(f"Tracked playlist '{title}' added.")

    def remove_tracked_playlist(self, url: str):
        reply = QMessageBox.question(self, "Remove Playlist", "Remove this playlist from tracking?\n(Your downloaded files will not be deleted)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.playlists_mgr.remove_playlist(url)
            self.refresh_playlists_ui()

    def sync_tracked_playlist(
        self,
        p_dict: dict,
        *,
        format_compat_override: str = None,
        playlist_format_update: str = None,
        redownload_from_scratch: bool = False,
        skip_format_dialog: bool = False,
    ):
        url = p_dict.get('url')
        out_dir = p_dict.get('folder_path')
        if not url or not out_dir:
            return

        if not hasattr(self, '_active_sync_urls'):
            self._active_sync_urls = set()
        if url in self._active_sync_urls:
            return

        title = p_dict.get('title', 'Playlist')

        # Check format compatibility mismatch
        from core.downloader import read_playlist_format
        pl_format = p_dict.get('format_compat')
        if not pl_format and out_dir:
            pl_format = read_playlist_format(out_dir)
        if not pl_format:
            pl_format = 'windows'

        global_format = self.settings.get('filename_compat', 'windows')
        chosen_format = format_compat_override or pl_format

        if pl_format != global_format and not skip_format_dialog:
            dlg = PlaylistFormatMismatchDialog(self, pl_title=title, pl_format=pl_format, settings_format=global_format)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
                return  # User cancelled sync
            if dlg.choice == 'keep':
                chosen_format = pl_format
            elif dlg.choice == 'settings':
                chosen_format = global_format
                playlist_format_update = 'unix/win'
            elif dlg.choice == 'redownload':
                set_fmt_label = "Windows" if global_format == "windows" else "UNIX"
                reply = QMessageBox.question(
                    self,
                    "Confirm Re-download from Scratch",
                    f"Are you sure you want to re-download '{title}' from scratch in {set_fmt_label} format?\n\n"
                    f"This will remove existing downloaded media tracks in '{out_dir}' and cleanly re-download all tracks from the online playlist.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

                chosen_format = global_format
                playlist_format_update = global_format
                redownload_from_scratch = True

        self._active_sync_urls.add(url)

        platform = detect_platform_name(url)
        self.status_label.setText(f"Syncing playlist '{title}' in background...")
        self.loading_overlay.show_loading(f"Syncing '{title}'...", f"Connecting to {platform} and comparing tracks...")

        worker = SyncPlaylistWorker(
            p_dict,
            self.settings,
            cookies=self.get_cookies_config(),
            format_compat=chosen_format,
            playlist_format_update=playlist_format_update,
            redownload_from_scratch=redownload_from_scratch,
        )
        worker.finished_signal.connect(self._on_sync_playlist_plan_ready)
        worker.error_signal.connect(self._on_sync_playlist_error)
        if not hasattr(self, '_sync_workers'):
            self._sync_workers = []
        self._sync_workers.append(worker)

        def _cleanup():
            if worker in self._sync_workers:
                self._sync_workers.remove(worker)

        worker.finished.connect(_cleanup)
        worker.start()

    def reindex_tracked_playlist(self, pl: dict):
        url = pl.get('url')
        out_dir = pl.get('folder_path')
        if not out_dir or not os.path.exists(out_dir):
            QMessageBox.warning(self, "Folder Not Found", f"The folder for '{pl.get('title')}' was not found on disk.")
            return

        title = pl.get('title', 'Playlist')
        platform = detect_platform_name(url)
        self.status_label.setText(f"Re-indexing tracks for '{title}'...")
        self.loading_overlay.show_loading(f"Re-indexing '{title}'...", f"Fetching current order from {platform} and updating tags (1..N)...")

        worker = ReindexPlaylistWorker(pl, self.settings, cookies=self.get_cookies_config())
        worker.finished_signal.connect(self._on_reindex_playlist_finished)
        worker.error_signal.connect(self._on_reindex_playlist_error)
        if not hasattr(self, '_reindex_workers'):
            self._reindex_workers = []
        self._reindex_workers.append(worker)

        def _cleanup():
            if worker in self._reindex_workers:
                self._reindex_workers.remove(worker)

        worker.finished.connect(_cleanup)
        worker.start()

    def redownload_tracked_playlist(self, pl: dict):
        url = pl.get('url')
        out_dir = pl.get('folder_path')
        if not out_dir or not os.path.exists(out_dir):
            QMessageBox.warning(self, "Folder Not Found", f"The folder for '{pl.get('title')}' was not found on disk.")
            return

        title = pl.get('title', 'Playlist')
        global_format = self.settings.get('filename_compat', 'windows')
        pl_format = pl.get('format_compat')
        from core.downloader import read_playlist_format
        if not pl_format and out_dir:
            pl_format = read_playlist_format(out_dir)
        if not pl_format:
            pl_format = 'windows'

        if pl_format != global_format:
            dlg = PlaylistFormatMismatchDialog(self, pl_title=title, pl_format=pl_format, settings_format=global_format)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.choice:
                return
            if dlg.choice == 'keep':
                chosen_format = pl_format
            elif dlg.choice == 'settings':
                chosen_format = global_format
                self.sync_tracked_playlist(
                    pl,
                    format_compat_override=chosen_format,
                    playlist_format_update='unix/win',
                    skip_format_dialog=True,
                )
                return
            elif dlg.choice == 'redownload':
                chosen_format = global_format
        else:
            chosen_format = global_format

        set_fmt_label = "Windows" if chosen_format == "windows" else "UNIX"
        reply = QMessageBox.question(
            self,
            "Confirm Re-download from Scratch",
            f"Are you sure you want to re-download '{title}' from scratch in {set_fmt_label} format?\n\n"
            f"This will remove existing downloaded media tracks in '{out_dir}' and cleanly re-download all tracks from the online playlist.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.sync_tracked_playlist(
            pl,
            format_compat_override=chosen_format,
            playlist_format_update=chosen_format,
            redownload_from_scratch=True,
            skip_format_dialog=True,
        )

    def _on_reindex_playlist_finished(self, pl: dict, count: int):
        self.loading_overlay.hide_loading()
        title = pl.get('title', 'Playlist')
        self.status_label.setText(f"Reindexed {count} tracks in '{title}'.")
        self.refresh_playlists_ui()
        QMessageBox.information(
            self,
            "Re-indexing Complete",
            f"Updated track numbers (1..{count}) and metadata in '{title}'."
        )

    def _on_reindex_playlist_error(self, err_msg: str):
        self.loading_overlay.hide_loading()
        self.status_label.setText("Re-indexing failed.")
        QMessageBox.warning(self, "Re-indexing Error", f"Could not re-index playlist:\n{err_msg}")

    def _on_sync_playlist_error(self, err_msg: str, p_dict: dict):
        self.loading_overlay.hide_loading()
        title = p_dict.get('title', 'Playlist') if p_dict else 'Playlist'
        if p_dict and hasattr(self, '_active_sync_urls'):
            self._active_sync_urls.discard(p_dict.get('url'))
        platform = detect_platform_name(p_dict.get('url') if p_dict else '')
        self.status_label.setText(f"Sync error for '{title}'.")
        QMessageBox.warning(self, "Sync Error", f"Could not fetch playlist metadata from {platform}:\n{err_msg}")

    def _on_sync_playlist_plan_ready(self, plan):
        self.loading_overlay.hide_loading()
        url = plan.playlist.get('url')
        title = plan.playlist.get('title', 'Playlist')
        if not (
            plan.missing_entries or plan.orphaned_files or plan.autoheal_pairs
            or plan.cleanup_actions or plan.redownload_from_scratch
            or plan.redownload_files or plan.playlist_format_update
        ):
            if hasattr(self, '_active_sync_urls'):
                self._active_sync_urls.discard(url)
            count = plan.preview.get('count') or len(plan.preview.get('entries', []))
            unavailable_count = len(plan.unavailable_entries)
            duplicates_count = len(plan.online_duplicates)
            self.playlists_mgr.update_sync_info(
                url, track_count=count, status='synced',
                unavailable_count=unavailable_count,
                duplicates_count=duplicates_count, removed_tracks_count=0,
            )
            self.refresh_playlists_ui()
            self.status_label.setText(f"Playlist '{title}' is up to date. No changes needed.")
            PlaylistUpToDateDialog(
                title, count, local_files_count=plan.local_count,
                duplicates=plan.online_duplicates,
                unavailable=plan.unavailable_entries, parent=self,
            ).exec()
            return
        dialog = PlaylistSyncPreviewDialog(plan, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            if hasattr(self, '_active_sync_urls'):
                self._active_sync_urls.discard(url)
            self.status_label.setText(f"Synchronization of '{title}' cancelled. No changes were made.")
            return

        selected_files = dialog.selected_files_to_delete()
        if selected_files:
            preview_names = "\n".join(f"- {name}" for name in selected_files[:5])
            remainder = f"\n... and {len(selected_files) - 5} more" if len(selected_files) > 5 else ""
            reply = QMessageBox.question(
                self, "Delete local files?",
                f"Sync will permanently delete {len(selected_files)} selected local file(s). "
                "They will not go to the Recycle Bin.\n\n"
                f"{preview_names}{remainder}\n\nContinue with sync?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                if hasattr(self, '_active_sync_urls'):
                    self._active_sync_urls.discard(url)
                self.status_label.setText(f"Synchronization of '{title}' cancelled. No changes were made.")
                return

        self.status_label.setText(f"Applying sync plan for '{title}'...")
        self.loading_overlay.show_loading(f"Applying '{title}' sync...", "Updating local files and playlist metadata...")
        worker = ApplyPlaylistSyncWorker(
            plan,
            selected_files,
            self.settings,
        )
        worker.finished_signal.connect(self._on_sync_playlist_committed)
        worker.error_signal.connect(self._on_sync_playlist_commit_error)
        if not hasattr(self, '_sync_commit_workers'):
            self._sync_commit_workers = []
        self._sync_commit_workers.append(worker)

        def _cleanup():
            if worker in self._sync_commit_workers:
                self._sync_commit_workers.remove(worker)

        worker.finished.connect(_cleanup)
        worker.start()

    def _on_sync_playlist_commit_error(self, err_msg: str, p_dict: dict):
        self.loading_overlay.hide_loading()
        url = p_dict.get('url') if p_dict else None
        if hasattr(self, '_active_sync_urls'):
            self._active_sync_urls.discard(url)
        title = p_dict.get('title', 'Playlist') if p_dict else 'Playlist'
        self.status_label.setText(f"Sync failed while applying changes to '{title}'.")
        QMessageBox.warning(self, "Sync Error", f"Could not apply the playlist sync plan:\n{err_msg}")

    def _on_sync_playlist_committed(self, result: dict):
        self.loading_overlay.hide_loading()
        plan = result['plan']
        preview = result['preview']
        url = plan.playlist.get('url')
        if hasattr(self, '_active_sync_urls'):
            self._active_sync_urls.discard(url)

        p_dict = next(
            (item for item in self.playlists_mgr.get_all() if item.get('url') == url),
            plan.playlist,
        )
        count = result['count']
        missing_entries = result['missing_entries']
        online_duplicates = result['online_duplicates']
        unavailable_entries = result['unavailable_entries']
        unavailable_count = len(unavailable_entries)
        duplicates_count = len(online_duplicates)

        p_dict['track_count'] = count
        p_dict['unavailable_count'] = unavailable_count
        p_dict['duplicates_count'] = duplicates_count
        p_dict['removed_tracks_count'] = 0
        if preview.get('thumbnail'):
            p_dict['thumbnail'] = preview['thumbnail']

        for filename in result['deleted_files']:
            stem = Path(filename).stem
            parts = stem.split(" - ", 1)
            self.history.add_entry(
                parts[0],
                parts[1] if len(parts) > 1 else "",
                platform=detect_platform_name(url),
                status="Deleted (Removed from playlist)",
                url=url,
                media_type=p_dict.get('media_type', 'Audio'),
            )

        status = 'pending' if missing_entries else 'synced'
        self.playlists_mgr.update_sync_info(
            url,
            track_count=count,
            status=status,
            unavailable_count=unavailable_count,
            duplicates_count=duplicates_count,
            removed_tracks_count=0,
            format_compat=plan.playlist_format_update,
        )

        if result['delete_failures']:
            failed_names = "\n".join(result['delete_failures'])
            QMessageBox.warning(
                self,
                "Some Files Could Not Be Deleted",
                f"These selected files could not be deleted and were kept locally:\n{failed_names}",
            )

        if not missing_entries:
            self.refresh_playlists_ui()
            available_count = max(0, count - unavailable_count - duplicates_count)
            self.status_label.setText(
                f"No new media to sync. All {available_count} available tracks in '{p_dict.get('title')}' are up to date."
            )
            PlaylistUpToDateDialog(
                p_dict.get('title', 'Playlist'),
                count,
                local_files_count=result['local_count'],
                duplicates=online_duplicates,
                unavailable=unavailable_entries,
                parent=self,
            ).exec()
            return

        # Auto-clear previous completed/finished queue if not downloading
        if self.download_queue and not self.is_downloading:
            all_done = all(w.status_state in ("Success", "Error", "Unavailable", "Completed", "Finished") for w in self.download_queue)
            if all_done:
                self.clear_queue()

        self.queue_container.setUpdatesEnabled(False)
        for entry in missing_entries:
            self._add_single_item_to_queue(entry, batch=True)
        self.queue_container.setUpdatesEnabled(True)
        self._save_queue()

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
        self.history_tab.setObjectName("HistoryTab")
        layout = QVBoxLayout(self.history_tab)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        btn_retry_selected = QPushButton("Retry Selected Error")
        btn_retry_selected.setObjectName("PrimaryButton")
        btn_retry_errors = QPushButton("Retry All Errors")
        btn_refresh = QPushButton("Refresh")
        btn_clear_hist = QPushButton("Clear History")

        btn_retry_selected.clicked.connect(self.retry_selected_history_error)
        btn_retry_errors.clicked.connect(self.retry_history_errors)
        btn_refresh.clicked.connect(self.refresh_history)
        btn_clear_hist.clicked.connect(self.clear_history)

        toolbar.addWidget(btn_retry_selected)
        toolbar.addWidget(btn_retry_errors)
        toolbar.addStretch()
        toolbar.addWidget(btn_refresh)
        toolbar.addWidget(btn_clear_hist)
        layout.addLayout(toolbar)

        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["Date", "Author", "Title", "Platform", "Status"])
        self.history_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        for col in range(5):
            h_item = self.history_table.horizontalHeaderItem(col)
            if h_item:
                h_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
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
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setShowGrid(False)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.history_table.setStyleSheet("""
            QTableWidget {
                background-color: #080d09;
                color: #cbd5cc;
                border: 1px solid #354a38;
                border-radius: 0px;
                gridline-color: #354a38;
                selection-background-color: #1a3020;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #0d150f;
                color: #aab7aa;
                padding: 10px;
                border: none;
                font-weight: bold;
                font-size: 12px;
            }
            QTableWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #354a38;
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
        self.settings_sections = QTabWidget(self.settings_tab)
        self.settings_sections.setObjectName("SettingsSections")

        def add_settings_page(name, description):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setObjectName("SettingsScrollArea")
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            wrapper = QWidget()
            wrapper.setObjectName("SettingsScrollWrapper")
            outer = QHBoxLayout(wrapper)
            outer.setContentsMargins(0, 10, 0, 20)
            content = QWidget()
            content.setObjectName("SettingsContainer")
            content.setMaximumWidth(820)
            page_layout = QVBoxLayout(content)
            page_layout.setSpacing(16)
            page_layout.setContentsMargins(18, 14, 18, 16)
            heading = QLabel(name)
            heading.setStyleSheet("font-size: 18px; font-weight: bold; color: #cbd5cc;")
            page_layout.addWidget(heading)
            hint = QLabel(description)
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #aab7aa; font-size: 12px;")
            page_layout.addWidget(hint)
            outer.addStretch(1)
            outer.addWidget(content)
            outer.addStretch(1)
            scroll.setWidget(wrapper)
            self.settings_sections.addTab(scroll, name.upper())
            return page_layout

        pages = {
            "General": add_settings_page("General", "Appearance, download location, and general behavior."),
            "Audio": add_settings_page("Audio", "Audio naming, artwork, lyrics, and metadata."),
            "Video": add_settings_page("Video", "Video naming, codecs, subtitles, and metadata."),
            "Quality": add_settings_page("Quality", "Default quality for each platform."),
            "Access": add_settings_page("Access", "YouTube authentication and cookie source."),
            "Maintenance": add_settings_page("Maintenance", "Updates, diagnostics, storage cleanup, and backups."),
        }
        layout = pages["General"]

        def make_combo(items=None, min_width=None):
            cb = QComboBox()
            cb.wheelEvent = lambda event: event.ignore()
            cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            if min_width:
                cb.setMinimumWidth(min_width)
            if items:
                cb.addItems(items)
            return cb

        # 0. Appearance
        appearance_layout = QHBoxLayout()
        appearance_layout.addWidget(QLabel("Color Theme:"))
        self.ui_theme_combo = make_combo(min_width=180)
        self.ui_theme_combo.addItem("Green Terminal", "green")
        self.ui_theme_combo.addItem("Blue Terminal", "blue")
        self.ui_theme_combo.addItem("Pink Terminal", "pink")
        self.ui_theme_combo.addItem("Red Terminal", "red")
        self.ui_theme_combo.addItem("Amber Terminal", "amber")
        self.ui_theme_combo.addItem("Cyan Terminal", "cyan")
        self.ui_theme_combo.addItem("Violet Terminal", "violet")
        theme_index = self.ui_theme_combo.findData(self.ui_theme)
        self.ui_theme_combo.setCurrentIndex(theme_index if theme_index >= 0 else 0)
        self.ui_theme_combo.setToolTip("Choose and remember the application's accent color theme.")
        self.ui_theme_combo.currentIndexChanged.connect(
            lambda index: self._on_ui_theme_changed(self.ui_theme_combo.itemData(index))
        )
        appearance_layout.addWidget(self.ui_theme_combo)
        appearance_layout.addStretch()
        appearance_group = QGroupBox("Appearance")
        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)

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
        folder_group = QGroupBox("Download Location")
        folder_group.setLayout(folder_layout)
        layout.addWidget(folder_group)

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
        self.cover_style_combo.addItem("Automatic (crop sidebars; preserve full-frame covers)", "smart")
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

        # Row 5: Create .nomedia file
        self.chk_nomedia = QCheckBox("Create .nomedia file in download and playlist folders (Hides folder from Android gallery and media scanners)")
        self.chk_nomedia.setChecked(self.settings.get('create_nomedia_file', False))
        self.chk_nomedia.toggled.connect(self._toggle_nomedia_setting)
        gen_grid.addWidget(self.chk_nomedia, 5, 0, 1, 2)

        gen_grid.setColumnStretch(1, 1)
        general_group = QGroupBox("Download Behavior")
        general_group.setLayout(gen_grid)
        layout.addWidget(general_group)

        # 3. Audio & Music Settings GroupBox
        layout = pages["Audio"]
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

        # Album Tag Source Row
        album_mode_layout = QHBoxLayout()
        album_mode_layout.addWidget(QLabel("Album Tag (TALB):"))
        self.album_mode_combo = make_combo()
        self.album_mode_combo.addItem("Original Album / Track Title (Recommended — prevents VLC/Player cover conflicts)", "original")
        self.album_mode_combo.addItem("Playlist Folder Name (Groups all tracks under one playlist album)", "playlist")
        cur_alb_mode = self.settings.get('album_tag_mode', 'original')
        idx_am = self.album_mode_combo.findData(cur_alb_mode)
        if idx_am >= 0:
            self.album_mode_combo.setCurrentIndex(idx_am)
        else:
            self.album_mode_combo.setCurrentIndex(0)
        self.album_mode_combo.currentIndexChanged.connect(
            lambda: self.settings.set('album_tag_mode', self.album_mode_combo.currentData())
        )
        album_mode_layout.addWidget(self.album_mode_combo, 1)
        audio_layout.addLayout(album_mode_layout)

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
        meta_section_lbl.setStyleSheet("font-weight: bold; color: #aab7aa; margin-top: 6px;")
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
        layout = pages["Video"]
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
        v_meta_section_lbl.setStyleSheet("font-weight: bold; color: #aab7aa; margin-top: 6px;")
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
        layout = pages["Maintenance"]
        lbl_core = QLabel("Updates & Maintenance")
        lbl_core.setStyleSheet("font-weight: bold; color: #aab7aa; margin-top: 8px; margin-bottom: 2px;")
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

        diagnostics_label = QLabel("Diagnostics")
        diagnostics_label.setStyleSheet("font-weight: bold; color: #aab7aa; margin-top: 8px; margin-bottom: 2px;")
        layout.addWidget(diagnostics_label)

        diagnostics_layout = QHBoxLayout()
        self.btn_self_diagnostics = QPushButton("Run Self-Diagnostics")
        self.btn_self_diagnostics.setToolTip("Check local app components and configuration. Does not access the network.")
        self.btn_self_diagnostics.clicked.connect(self.run_self_diagnostics)
        self.btn_network_diagnostics = QPushButton("Check Network")
        self.btn_network_diagnostics.setToolTip("Separately test access to YouTube, PyPI, and GitHub.")
        self.btn_network_diagnostics.clicked.connect(self.run_network_diagnostics)
        diagnostics_note = QLabel("Local checks and network checks are run separately.")
        diagnostics_note.setStyleSheet("color: #849184; font-size: 11px;")
        diagnostics_layout.addWidget(self.btn_self_diagnostics)
        diagnostics_layout.addWidget(self.btn_network_diagnostics)
        diagnostics_layout.addWidget(diagnostics_note, 1)
        diagnostics_layout.addStretch()
        layout.addLayout(diagnostics_layout)

        cleanup_group = QGroupBox("Storage Cleanup")
        cleanup_layout = QVBoxLayout(cleanup_group)
        cleanup_note = QLabel(
            "Review .part files and old yt-dlp backups with their sizes and dates. "
            "Nothing is removed automatically."
        )
        cleanup_note.setWordWrap(True)
        cleanup_layout.addWidget(cleanup_note)
        btn_storage_cleanup = QPushButton("Review Files...")
        btn_storage_cleanup.clicked.connect(self.open_storage_cleanup)
        cleanup_layout.addWidget(btn_storage_cleanup, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(cleanup_group)

        # 6. Quality Settings
        layout = pages["Quality"]
        lbl_quality = QLabel("Quality Settings")
        lbl_quality.setStyleSheet("font-weight: bold; color: #aab7aa; margin-top: 8px; margin-bottom: 2px;")
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
        layout = pages["Access"]
        lbl_cookies = QLabel("YouTube Authentication & Cookies")
        lbl_cookies.setStyleSheet("font-weight: bold; color: #aab7aa; margin-top: 10px; margin-bottom: 2px;")
        layout.addWidget(lbl_cookies)

        cookies_group = QWidget()
        cookies_layout = QVBoxLayout(cookies_group)
        cookies_layout.setContentsMargins(15, 12, 15, 12)
        cookies_layout.setSpacing(10)
        cookies_group.setStyleSheet("""
            QWidget#CookiesGroup {
                background-color: #0b120d;
                border: 1px solid #354a38;
                border-radius: 0px;
            }
        """)
        cookies_group.setObjectName("CookiesGroup")

        cookies_desc = QLabel(
            "Use your exported cookies.txt file or browser session to download age-restricted (18+), "
            "private, and high-quality YouTube Music tracks without errors."
        )
        cookies_desc.setWordWrap(True)
        cookies_desc.setStyleSheet("font-size: 12px; color: #aab7aa; line-height: 1.4;")
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
            "<b>Export cookies.txt:</b><br>"
            "1. Install a browser extension (e.g. <b>Get cookies.txt LOCALLY</b> or <b>Cookie-Editor</b> for Chrome / Firefox / Edge / Opera).<br>"
            "2. Open <a href='https://music.youtube.com' style='color: #91e5a3;'>music.youtube.com</a> or <a href='https://youtube.com' style='color: #91e5a3;'>youtube.com</a> and make sure you are logged into your Google account.<br>"
            "3. Click the extension icon in your browser toolbar and click <b>Export</b> (in <i>Netscape HTTP Cookie File</i> format).<br>"
            "4. Save the file (e.g. <code>music.youtube.com_cookies.txt</code>) on your computer.<br>"
            "5. Click <b>Browse...</b> above and select the saved file."
        )
        file_instructions.setOpenExternalLinks(True)
        file_instructions.setWordWrap(True)
        file_instructions.setStyleSheet("""
            background-color: #080b09;
            border: 1px solid #354a38;
            border-radius: 0px;
            padding: 10px 12px;
            font-size: 11px;
            color: #cbd5cc;
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
        self.cookies_browser_combo.setCurrentText(self.settings.get('cookies_browser', 'chrome').capitalize())
        self.cookies_browser_combo.currentTextChanged.connect(lambda b: self.settings.set('cookies_browser', b.lower()))
        b_row.addWidget(self.cookies_browser_combo, 1)
        browser_widget_layout.addLayout(b_row)

        browser_warning = QLabel(
            "<b>Browser cookie access:</b><br>"
            "On Windows, Chromium-based browsers may block cookie extraction through <b>App-Bound Encryption</b>.<br><br>"
            "<b>Firefox</b> cookie extraction may work, depending on the browser profile and permissions.<br><br>"
            "If browser extraction fails, export cookies in Netscape format and select <b>Cookies File (cookies.txt)</b>. Treat this file as a credential; do not share it."
        )
        browser_warning.setWordWrap(True)
        browser_warning.setStyleSheet("""
            background-color: #080b09;
            border: 1px solid #d98f86;
            border-radius: 0px;
            padding: 10px 12px;
            font-size: 11px;
            color: #e3aaa3;
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
        layout = pages["Maintenance"]
        lbl_backup = QLabel("Data Backup & Migration")
        lbl_backup.setStyleSheet("font-weight: bold; color: #aab7aa; margin-top: 10px; margin-bottom: 2px;")
        layout.addWidget(lbl_backup)

        backup_group = QWidget()
        backup_layout = QVBoxLayout(backup_group)
        backup_layout.setContentsMargins(15, 12, 15, 12)
        backup_layout.setSpacing(10)
        backup_group.setStyleSheet("""
            QWidget#BackupGroup {
                background-color: #0b120d;
                border: 1px solid #354a38;
                border-radius: 0px;
            }
        """)
        backup_group.setObjectName("BackupGroup")

        backup_desc = QLabel(
            "Export or restore your tracked playlists, custom settings, and download history to transfer between PCs or create backups."
        )
        backup_desc.setWordWrap(True)
        backup_desc.setStyleSheet("font-size: 12px; color: #aab7aa; line-height: 1.4;")
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
        for page_layout in pages.values():
            page_layout.addStretch()
        main_tab_layout = QVBoxLayout(self.settings_tab)
        main_tab_layout.setContentsMargins(0, 0, 0, 0)
        main_tab_layout.addWidget(self.settings_sections)
        self.tabs.addTab(self.settings_tab, "SETTINGS")

    def open_storage_cleanup(self):
        folders = [self.settings.get('download_path')]
        folders.extend(p.get('folder_path') for p in self.playlists_mgr.get_all())

        def busy():
            workers = (
                list(self.active_workers.values())
                + list(getattr(self, '_ending_workers', []))
                + list(getattr(self, '_sync_workers', []))
                + list(getattr(self, '_sync_commit_workers', []))
            )
            upgrade = getattr(self, 'upgrade_worker', None)
            if upgrade is not None:
                workers.append(upgrade)
            return (self.is_downloading or bool(getattr(self, '_active_sync_urls', set()))
                    or any(worker.isRunning() for worker in workers))

        StorageCleanupDialog(folders, get_app_data_dir(), busy, parent=self).exec()

    def export_app_data(self):
        now_date = datetime.datetime.now().strftime("%Y-%m-%d")
        def_name = f"LogovoDownloads_Backup_{now_date}.zip"
        initial_dir = self.settings.get('last_selected_folder') or str(Path.home())
        save_path, _ = QFileDialog.getSaveFileName(self, "Save Data Backup", os.path.join(initial_dir, def_name), "ZIP Archives (*.zip)")
        if save_path:
            ok, msg = export_backup(save_path)
            if ok:
                QMessageBox.information(self, "Backup Exported", f"Backup created:\n{Path(save_path).name}")
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
                    self.settings.reload()
                    self.playlists_mgr.playlists = self.playlists_mgr.load()
                    self.history.history = self.history.load()
                    current_tab = self.tabs.currentWidget()
                    settings_was_current = current_tab is self.settings_tab
                    settings_index = self.tabs.indexOf(self.settings_tab)
                    self.tabs.removeTab(settings_index)
                    self.settings_tab.deleteLater()
                    self.setup_settings_tab()
                    new_settings_index = self.tabs.indexOf(self.settings_tab)
                    self.tabs.removeTab(new_settings_index)
                    self.tabs.insertTab(settings_index, self.settings_tab, "SETTINGS")
                    if settings_was_current:
                        self.tabs.setCurrentWidget(self.settings_tab)
                    elif current_tab is not None:
                        self.tabs.setCurrentWidget(current_tab)
                    self.refresh_playlists_ui()
                    self.refresh_history()
                    QMessageBox.information(self, "Backup Restored", "Backup restored. Playlists and settings reloaded.")
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
            QMessageBox.information(self, "Cookies Loaded", f"Cookies file selected:\n{Path(file).name}")

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
            b_name = self.settings.get('cookies_browser', 'chrome').lower()
            return {'use': True, 'source': 'browser', 'browser': b_name}
        return None

    def insert_naming_token(self, token: str):
        text = self.naming_input.text()
        self.naming_input.setText(text + token)

    def reset_naming_pattern(self):
        default_pattern = "{artist} - {title}"
        self.naming_input.setText(default_pattern)
        self.settings.set('naming_pattern', default_pattern)

    def _toggle_nomedia_setting(self, checked: bool):
        self.settings.set('create_nomedia_file', checked)
        if checked:
            for p in self.playlists_mgr.get_all():
                folder = p.get('folder_path')
                if folder and os.path.exists(folder):
                    ensure_nomedia_file(folder)

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
        self.about_tab.setObjectName("AboutTab")
        layout = QVBoxLayout(self.about_tab)
        layout.addStretch()
        title = QLabel("Logovo Downloads")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #cbd5cc;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel(f"Version {APP_VERSION}")
        version.setStyleSheet("font-size: 13px; color: #91e5a3; font-weight: 600; margin-top: 2px; margin-bottom: 8px;")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        desc = QLabel("Audio and video downloads. Playlist synchronization for Windows.")
        desc.setStyleSheet("font-size: 12px; color: #aab7aa; margin-bottom: 20px;")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        btn_layout = QHBoxLayout()
        github = QPushButton("GitHub Repository")
        github.setMinimumWidth(200)
        github.setMaximumWidth(250)
        github.setStyleSheet("""
            QPushButton {
                background-color: #0b120d;
                color: #cbd5cc;
                border: 1px solid #354a38;
                border-radius: 0px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #354a38;
                border-color: #91e5a3;
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

    def _start_diagnostics_worker(self, worker, title: str, result_handler):
        if self._diagnostics_worker is not None and self._diagnostics_worker.isRunning():
            return

        self._diagnostics_worker = worker
        self.btn_self_diagnostics.setEnabled(False)
        self.btn_network_diagnostics.setEnabled(False)
        self.status_label.setText(f"Running {title.lower()}...")
        worker.finished_signal.connect(result_handler)
        worker.finished.connect(self._diagnostics_worker_finished)
        worker.start()

    def run_self_diagnostics(self):
        self._start_diagnostics_worker(
            SelfDiagnosticsWorker(self.settings),
            "Self-Diagnostics",
            self._on_self_diagnostics_results,
        )

    def run_network_diagnostics(self):
        self._start_diagnostics_worker(
            NetworkDiagnosticsWorker(),
            "Network Check",
            self._on_network_diagnostics_results,
        )

    def _diagnostics_worker_finished(self):
        self._diagnostics_worker = None
        self.btn_self_diagnostics.setEnabled(True)
        self.btn_network_diagnostics.setEnabled(True)

    def _on_self_diagnostics_results(self, results: list[dict]):
        self._show_diagnostics_results("Self-Diagnostics", results)

    def _on_network_diagnostics_results(self, results: list[dict]):
        self._show_diagnostics_results("Network Check", results)

    def _show_diagnostics_results(self, title: str, results: list[dict]):
        results = results if isinstance(results, list) else []
        counts = {
            status: sum(1 for result in results if result.get('status') == status)
            for status in ('OK', 'INFO', 'WARN', 'FAIL')
        }
        summary = (
            f"{counts['OK']} OK, {counts['INFO']} informational, "
            f"{counts['WARN']} warning(s), {counts['FAIL']} failure(s)."
        )
        details = "\n".join(
            f"[{result.get('status', 'INFO')}] {result.get('name', 'Check')}: "
            f"{result.get('details', '')}"
            for result in results
        ) or "No diagnostic results were produced."

        if counts['FAIL']:
            icon = QMessageBox.Icon.Critical
            self.status_label.setText(f"{title} finished with failures.")
        elif counts['WARN']:
            icon = QMessageBox.Icon.Warning
            self.status_label.setText(f"{title} finished with warnings.")
        else:
            icon = QMessageBox.Icon.Information
            self.status_label.setText(f"{title} completed.")

        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(icon)
        box.setText(summary)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDetailedText(details)
        box.exec()

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
                f"yt-dlp update available.\n\nCurrent: {cur_v}\nLatest: {lat_v}\n\nInstall update?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.run_ytdlp_upgrade()
        else:
            QMessageBox.information(self, "Up to Date", f"The yt-dlp downloader core is up to date (v{cur_v}).")
            self.status_label.setText("Downloader core is up to date.")

    def run_ytdlp_upgrade(self):
        if getattr(self, "upgrade_worker", None) is not None and self.upgrade_worker.isRunning():
            return
        if self.active_workers:
            QMessageBox.warning(self, "Downloads in progress", "Pause or finish active downloads before updating yt-dlp.")
            return
        self.status_label.setText("Upgrading yt-dlp core in background...")
        self.upgrade_worker = UpgradeWorker()
        self.upgrade_worker.finished_signal.connect(self.on_upgrade_finished)
        self.upgrade_worker.start()

    def on_upgrade_finished(self, success: bool, msg: str):
        if success:
            QMessageBox.information(self, "Update Complete", msg)
            self.status_label.setText("yt-dlp update ready. Restart the app to activate it.")
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
                self.status_label.setText(f"Version v{latest_ver} is available on GitHub.")
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
        msg = f"Version v{latest_ver} is available.\nInstalled: v{APP_VERSION}.\nRelease notes and downloads are on GitHub."
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
                self._save_queue()
                self.update_queue_ui()
                self.status_label.setText(f"Added {added_count} links from file.")
            except Exception as e:
                self.queue_container.setUpdatesEnabled(True)
                QMessageBox.warning(self, "Error", f"Failed to read file: {e}")

    def clear_queue(self):
        for widget in list(self.download_queue):
            if widget.status_state != "Downloading" and widget not in self.active_workers:
                if hasattr(self, '_queue_url_set'):
                    self._queue_url_set.discard(getattr(widget, '_queue_key', (widget.item_data.get('url'), widget.item_data.get('media_type'))))
                self.queue_container_layout.removeWidget(widget)
                widget.deleteLater()
                self.download_queue.remove(widget)
        self._save_queue()
        self.update_queue_ui()
        self._update_taskbar_progress()
        self.status_label.setText("Queue cleared (except active downloads).")

    def clear_completed(self):
        for widget in list(self.download_queue):
            if widget.status_state in ["Success", "Error"]:
                if hasattr(self, '_queue_url_set'):
                    self._queue_url_set.discard(getattr(widget, '_queue_key', (widget.item_data.get('url'), widget.item_data.get('media_type'))))
                self.queue_container_layout.removeWidget(widget)
                widget.deleteLater()
                self.download_queue.remove(widget)
        self._save_queue()
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
            self._save_queue()

    def on_main_subs_combo_changed(self, text):
        if text and text != "None" and hasattr(self, 'subs_combo') and not self.subs_combo.isHidden():
            self.settings.set('main_subs_choice', text)

    def update_main_subs_combo_state(self):
        current_type = self.format_combo.currentText()
        if current_type == "Audio":
            is_enabled = self.settings.get('download_audio_lyrics', False)
        elif current_type == "Video":
            is_enabled = self.settings.get('download_subtitles', False)
        else:
            is_enabled = self.settings.get('download_subtitles', False) or self.settings.get('download_audio_lyrics', False)

        if hasattr(self, 'lbl_main_subs'):
            self.lbl_main_subs.setVisible(is_enabled)
            self.lbl_main_subs.setEnabled(is_enabled)
        if hasattr(self, 'subs_combo'):
            self.subs_combo.setVisible(is_enabled)
            self.subs_combo.setEnabled(is_enabled)
            self.subs_combo.blockSignals(True)
            if is_enabled:
                saved_choice = self.settings.get('main_subs_choice', 'Default (Settings)')
                idx = self.subs_combo.findText(saved_choice)
                if idx >= 0:
                    self.subs_combo.setCurrentIndex(idx)
                else:
                    self.subs_combo.setCurrentIndex(0)
            else:
                self.subs_combo.setCurrentText("None")
            self.subs_combo.blockSignals(False)

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
            item_date.setData(Qt.ItemDataRole.UserRole, entry)
            item_author = QTableWidgetItem(entry.get('author', 'Unknown'))
            item_title = QTableWidgetItem(entry.get('title', 'Unknown'))
            item_plat = QTableWidgetItem(entry.get('platform', 'Unknown'))
            status = entry.get('status', 'Unknown')
            item_status = QTableWidgetItem(status)

            for it in (item_date, item_author, item_title, item_plat, item_status):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            if status in ["Completed", "Success"]:
                completed += 1
                item_status.setForeground(QColor(self.theme_colors["accent_fill"]))
            elif "Error" in status:
                errors += 1
                item_status.setForeground(QColor("#d98f86"))
            elif status == "Skipped":
                item_status.setForeground(QColor(self.theme_colors["text_secondary"]))

            self.history_table.setItem(i, 0, item_date)
            self.history_table.setItem(i, 1, item_author)
            self.history_table.setItem(i, 2, item_title)
            self.history_table.setItem(i, 3, item_plat)
            self.history_table.setItem(i, 4, item_status)

        self.history_stats_label.setText(f"Total: {len(entries)} | Completed: {completed} | Errors: {errors}")

    def clear_history(self):
        self.history.clear()
        self.refresh_history()

    def _history_entry_to_queue_item(self, entry: dict) -> dict:
        options = sanitize_download_options(entry.get('download_options')) or {}
        source_url = options.get('source_url') or entry.get('url', '')
        media_type = options.get('media_type') or entry.get('type') or 'Audio (Best)'
        media_type_text = str(media_type)
        if media_type_text.lower() == 'audio':
            media_type_text = 'Audio (Best)'
        elif media_type_text.lower() == 'video':
            media_type_text = 'Video (Best)'
        category = options.get('media_type_category')
        if category not in ('Audio', 'Video'):
            category = 'Video' if media_type_text.lower().startswith('video') else 'Audio'

        item_data = {
            'url': source_url,
            'original_url': source_url,
            'title': options.get('title') or entry.get('title') or 'Unknown',
            'uploader': options.get('author') or entry.get('author') or 'Unknown',
            'platform': entry.get('platform'),
            'media_type': media_type_text,
            'media_type_category': category,
            'playlist_index': options.get('playlist_index'),
            'playlist_count': options.get('playlist_count'),
            'format_compat': options.get('format_compat'),
            'thumbnail': options.get('thumbnail'),
        }
        if options:
            item_data['download_options'] = options
            if options.get('output_dir'):
                item_data['playlist_output_dir'] = options['output_dir']
        return item_data

    @staticmethod
    def _queue_item_source_url(item_data: dict) -> str:
        options = item_data.get('download_options')
        if isinstance(options, dict) and options.get('source_url'):
            return options['source_url']
        return item_data.get('original_url') or item_data.get('url', '')

    def _queue_history_error_entry(self, entry: dict) -> bool:
        if not is_retryable_error(entry):
            return False

        item_data = self._history_entry_to_queue_item(entry)
        source_url = item_data['url']
        media_type = item_data['media_type']

        if getattr(self, 'failed_queue', None):
            self.failed_queue = [
                (failed_data, error)
                for failed_data, error in self.failed_queue
                if not (
                    self._queue_item_source_url(failed_data) == source_url
                    and failed_data.get('media_type', 'Audio (Best)') == media_type
                )
            ]

        for widget in self.download_queue:
            current_data = widget.item_data
            current_url = self._queue_item_source_url(current_data)
            current_media_type = current_data.get('media_type', 'Audio (Best)')
            if current_url != source_url or current_media_type != media_type:
                continue
            if widget in self.active_workers or widget.status_state in ('Pending', 'Downloading', 'Retrying'):
                return False

            current_data.pop('specific_subs', None)
            if 'download_options' not in item_data:
                current_data.pop('download_options', None)
                current_data.pop('playlist_output_dir', None)
            current_data.update(item_data)
            widget.is_retry = True
            if widget.format_combo.findText(media_type) >= 0:
                widget.format_combo.setCurrentText(media_type)
            widget._populate_subs_combo()
            widget.progress_bar.setValue(0)
            widget.set_status('Retrying...', 'Pending')
            self._save_queue()
            self.update_queue_ui()
            return True

        previous_count = len(self.download_queue)
        self._add_single_item_to_queue(
            item_data,
            batch=True,
            preserve_subtitle_defaults=True,
        )
        self._save_queue()
        return len(self.download_queue) > previous_count

    def retry_selected_history_error(self):
        row = self.history_table.currentRow()
        if row < 0:
            QMessageBox.information(self, 'Retry Download', 'Select an error entry in history first.')
            return
        item = self.history_table.item(row, 0)
        entry = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not is_retryable_error(entry):
            QMessageBox.information(self, 'Retry Download', 'The selected history entry is not a retryable error.')
            return
        if not self._queue_history_error_entry(entry):
            self.status_label.setText('This download is already queued or running.')
            return
        self.tabs.setCurrentIndex(0)
        self.update_queue_ui()
        self.start_queue()

    def retry_history_errors(self):
        errors = get_retryable_error_entries(self.history.get_all())
        if not errors:
            QMessageBox.information(self, 'Retry Errors', 'There are no retryable errors in history.')
            return

        reply = QMessageBox.question(
            self,
            'Retry All Errors',
            f'Retry {len(errors)} failed history entry/entries? Unavailable tracks will not be retried.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        queued = 0
        seen = set()
        for entry in errors:
            item_data = self._history_entry_to_queue_item(entry)
            key = (item_data['url'], item_data['media_type'])
            if key in seen:
                continue
            seen.add(key)
            if self._queue_history_error_entry(entry):
                queued += 1

        if queued:
            self.tabs.setCurrentIndex(0)
            self.status_label.setText(f'Queued {queued} failed download(s) for retry.')
            self.update_queue_ui()
            self.start_queue()
        else:
            self.status_label.setText('All matching failed downloads are already queued or running.')

    def highlight_format_combo(self):
        if hasattr(self, '_pulse_timer') and self._pulse_timer.isActive():
            self._pulse_timer.stop()

        self._pulse_step = 0
        self._pulse_timer = QTimer(self)

        def do_pulse():
            import math
            self._pulse_step += 1
            t = (math.sin(self._pulse_step * 0.3) + 1.0) / 2.0
            alpha = int(120 + 135 * t)
            border_color = self.theme_colors["accent"] if alpha >= 188 else self.theme_colors["accent_hover"]

            self.format_combo.setStyleSheet("""
                QComboBox {
                    background-color: %s;
                    border: 1px solid %s;
                    color: %s;
                    font-weight: bold;
                    border-radius: 0px;
                }
            """ % (self.theme_colors["input_bg"], border_color, self.theme_colors["accent"]))

            if self._pulse_step >= 24:
                self._pulse_timer.stop()
                self.format_combo.setStyleSheet("""
                    QComboBox {
                        background-color: %s;
                        border: 1px solid %s;
                        color: %s;
                        font-weight: bold;
                        border-radius: 0px;
                    }
                """ % (
                    self.theme_colors["input_bg"],
                    self.theme_colors["accent"],
                    self.theme_colors["accent"],
                ))

        self._pulse_timer.timeout.connect(do_pulse)
        self._pulse_timer.start(50)

    def clear_format_combo_highlight(self):
        if hasattr(self, '_pulse_timer') and self._pulse_timer.isActive():
            self._pulse_timer.stop()
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
                "Please select 'Audio' or 'Video' in the Type selector (highlighted) before adding to queue."
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

                if self.settings and self.settings.get('create_nomedia_file', False):
                    ensure_nomedia_file(out_dir)

                # Re-index existing tracks so numbers 1..N match current playlist count without gaps
                reindex_existing_playlist_files(out_dir, preview.get('entries', []), settings=self.settings)

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
                self._save_queue()
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

    def _add_single_item_to_queue(self, info_dict, batch=False, preserve_subtitle_defaults=False):
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

        if not preserve_subtitle_defaults and hasattr(self, 'subs_combo') and not self.subs_combo.isHidden():
            chosen_subs = self.subs_combo.currentText()
        else:
            chosen_subs = "None"
        if chosen_subs and chosen_subs not in ("Default (Settings)", "", "None"):
            info_dict['specific_subs'] = chosen_subs

        widget = QueueItemWidget(info_dict, settings=self.settings, theme_name=self.ui_theme)
        widget._queue_key = queue_key
        widget.remove_requested.connect(self.remove_queue_item)
        widget.format_combo.currentTextChanged.connect(lambda _: self._save_queue())
        widget.subs_combo.currentIndexChanged.connect(lambda _: self._save_queue())

        self.queue_container_layout.addWidget(widget)
        self.download_queue.append(widget)
        if not batch:
            self._save_queue()
            self.update_queue_ui()

    def remove_queue_item(self, widget):
        if widget in self.download_queue and widget not in self.active_workers:
            if hasattr(self, '_queue_url_set'):
                self._queue_url_set.discard(getattr(widget, '_queue_key', (widget.item_data.get('url'), widget.item_data.get('media_type'))))
            self.queue_container_layout.removeWidget(widget)
            widget.deleteLater()
            self.download_queue.remove(widget)
            self._save_queue()
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
                f"<span style='color: #91e5a3;'>Estimated size: {size_str}</span>&nbsp;&nbsp;&nbsp;&nbsp;"
                f"<span style='color: #d9b66d;'>{time_str}</span>"
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
        self.btn_pause.setEnabled(True)
        self._pause_requested = False
        self._stop_requested = False

        self.process_queue()

    def pause_download(self):
        if not self.is_downloading or self._pause_requested:
            return
        self._pause_requested = True
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_download_all.setEnabled(False)
        for widget, worker in list(self.active_workers.items()):
            worker.requestInterruption()
            widget.set_status("Pausing...", "Downloading")
        self.status_label.setText("Pausing active downloads...")
        self._save_queue()
        if not self.active_workers:
            self.process_queue()

    def stop_download(self):
        if not self.is_downloading or self._stop_requested:
            return

        self._stop_requested = True
        for widget, worker in list(self.active_workers.items()):
            try:
                worker.progress_signal.disconnect()
            except Exception:
                pass
            worker.requestInterruption()
            widget.set_status("Stopping...", "Downloading")

        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        if self.active_workers:
            self.status_label.setText("Stopping active downloads...")
        else:
            self._stop_requested = False
            self.is_downloading = False
            self.btn_pause.setEnabled(False)
            self.status_label.setText("Download stopped.")
        self.update_queue_ui()

    def process_queue(self):
        if self._pause_requested:
            if not self.active_workers:
                self.is_downloading = False
                self._pause_requested = False
                self.btn_pause.setEnabled(False)
                self.btn_stop.setEnabled(False)
                self.status_label.setText("Queue paused. Press Download to resume.")
                self._save_queue()
                self.update_queue_ui()
                if self._closing_after_pause:
                    self._finish_close_if_ready()
            return
        if self._stop_requested:
            if not self.active_workers:
                self._stop_requested = False
                self.is_downloading = False
                self.btn_stop.setEnabled(False)
                self.btn_pause.setEnabled(False)
                self.global_progress.setValue(0)
                self.status_label.setText("Download stopped.")
            self.update_queue_ui()
            return

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
                    self.btn_pause.setEnabled(False)
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
                            self.status_label.setText(f"Queue completed: {self.downloaded_count} downloaded, {unavail_count} unavailable.")
                        else:
                            self.status_label.setText("Queue completed.")
                        if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                            if self.downloaded_count > 0 and self.skipped_count > 0:
                                msg = f"Queue completed: {self.downloaded_count} downloaded, {self.skipped_count} skipped."
                            elif self.downloaded_count > 0:
                                msg = f"Queue completed: {self.downloaded_count} downloaded."
                            else:
                                msg = f"Queue completed: {self.success_count} checked."
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
                        cleanup_orphan_files(d, is_audio_playlist=False, preserve_partials=True)
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
                    self._save_queue()
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
        saved_options = sanitize_download_options(item_data.get('download_options')) or {}
        has_saved_options = bool(saved_options)
        source_url = (
            saved_options.get('source_url')
            or item_data.get('original_url')
            or item_data['url']
        )
        url = source_url
        if "spotify.com" in str(url):
            title = item_data.get('title', '')
            author = item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or ''
            query = f"{author} - {title}".strip(" - ") if (author or title) else title
            if query:
                url = f"ytsearch1:{query}"
                item_data['url'] = url

        format_combo = getattr(widget, 'format_combo', None)
        selected_media_type = format_combo.currentText() if format_combo is not None else None
        media_type = _resolve_queue_media_type(selected_media_type, saved_options, item_data)
        item_data['media_type'] = media_type
        media_type_category = 'Video' if str(media_type).lower().startswith('video') else 'Audio'
        item_data['media_type_category'] = media_type_category
        if has_saved_options:
            saved_options['media_type'] = media_type
            saved_options['media_type_category'] = media_type_category
            item_data['download_options'] = saved_options
        output_dir = (
            saved_options.get('output_dir')
            if has_saved_options and 'output_dir' in saved_options
            else item_data.get('playlist_output_dir') or self.settings.get('download_path')
        )

        platform = detect_platform_name(source_url)
        quality = (
            saved_options.get('quality')
            if has_saved_options and 'quality' in saved_options
            else self.settings.get_quality(platform)
        )
        
        is_audio = media_type.startswith("Audio")
        global_subs_enabled = self.settings.get('download_audio_lyrics', False) if is_audio else self.settings.get('download_subtitles', False)
        global_subs_lang = self.settings.get('lyrics_langs', 'orig') if is_audio else self.settings.get('subtitles_langs', 'orig')

        specific_subs = item_data.get('specific_subs')
        if has_saved_options and isinstance(saved_options.get('subtitles'), dict):
            subtitles_cfg = dict(saved_options['subtitles'])
        elif not specific_subs or specific_subs in ('Default', 'Global', 'Default (Settings)'):
            subtitles_cfg = {'download': global_subs_enabled, 'langs': global_subs_lang}
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

        speed_limit = (
            saved_options.get('speed_limit')
            if has_saved_options and 'speed_limit' in saved_options
            else self.settings.get('speed_limit', 'Unlimited')
        )
        naming_pattern = (
            saved_options.get('naming_pattern')
            if has_saved_options and 'naming_pattern' in saved_options
            else self.settings.get('naming_pattern', '{artist} - {title}')
            if is_audio else self.settings.get('video_naming_pattern', '{title}')
        )
        format_compat = (
            saved_options.get('format_compat')
            if has_saved_options and 'format_compat' in saved_options
            else item_data.get('format_compat')
        )
        download_settings = self.settings
        if has_saved_options and isinstance(saved_options.get('settings'), dict):
            download_settings = DownloadSettingsOverlay(self.settings, saved_options['settings'])

        if not has_saved_options:
            item_data['download_options'] = {
                'source_url': source_url,
                'output_dir': str(output_dir) if output_dir is not None else None,
                'media_type': media_type,
                'media_type_category': media_type_category,
                'quality': quality,
                'subtitles': subtitles_cfg,
                'speed_limit': speed_limit,
                'naming_pattern': naming_pattern,
                'format_compat': format_compat,
                'playlist_index': item_data.get('playlist_index'),
                'playlist_count': item_data.get('playlist_count'),
                'title': item_data.get('title'),
                'author': item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or item_data.get('author'),
                'thumbnail': item_data.get('thumbnail'),
                'settings': snapshot_download_settings(self.settings),
            }

        thread = WorkerThread(
            url=url,
            media_type=media_type,
            output_dir=output_dir,
            quality=quality,
            cookies=cookies,
            subtitles=subtitles_cfg,
            playlist_index=saved_options.get('playlist_index', item_data.get('playlist_index')),
            playlist_count=saved_options.get('playlist_count', item_data.get('playlist_count')),
            title=item_data.get('title'),
            author=item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or item_data.get('author'),
            speed_limit=speed_limit,
            naming_pattern=naming_pattern,
            settings=download_settings,
            thumbnail=saved_options.get('thumbnail', item_data.get('thumbnail')),
            format_compat=format_compat,
        )

        self.widget_start_times[widget] = time.time()
        self.active_workers[widget] = thread
        widget.set_status("Starting download...", "Downloading")
        thread.progress_signal.connect(lambda d, w=widget: self.update_widget_progress(w, d))
        thread.finished_signal.connect(lambda s, e, sk, cancelled, w=widget: self.task_finished(w, s, e, sk, cancelled))
        thread.finished.connect(lambda worker=thread: self._worker_exited(worker))
        thread.start()
        self._save_queue()

    def _worker_exited(self, worker):
        self._ending_workers = [w for w in self._ending_workers if w.isRunning()]
        self._finish_close_if_ready()

    def _finish_close_if_ready(self):
        if not self._closing_after_pause or self.active_workers:
            return
        if any(worker.isRunning() for worker in getattr(self, "_ending_workers", [])):
            QTimer.singleShot(50, self._finish_close_if_ready)
            return
        self._closing_after_pause = False
        QTimer.singleShot(0, self.close)

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
        if self._stop_requested:
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

    def task_finished(self, widget: QueueItemWidget, success: bool, error_msg: str = "", was_skipped: bool = False, was_cancelled: bool = False):
        # Remove from active workers
        if widget in self.active_workers:
            worker = self.active_workers.pop(widget)
            if worker.isRunning():
                self._ending_workers.append(worker)

        # Calculate duration for dynamic ETA estimation
        start_t = self.widget_start_times.pop(widget, None)
        if was_cancelled:
            widget.set_status("Paused" if self._pause_requested else "Stopped", "Pending")
            self._save_queue()
            self.update_queue_ui()
            self._update_taskbar_progress()
            self.process_queue()
            return

        if start_t and not was_skipped and success:
            dur = time.time() - start_t
            if dur > 0.4:
                self.track_durations.append(dur)

        item_data = widget.item_data
        title = item_data.get('title', 'Unknown')
        author = item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or 'Unknown'
        download_options = sanitize_download_options(item_data.get('download_options')) or {}
        url = (
            download_options.get('source_url')
            or item_data.get('original_url')
            or item_data.get('url', '')
        )
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

        self.history.add_entry(
            title,
            author,
            platform,
            status_text,
            url=url,
            media_type=item_data.get('media_type', 'Audio'),
            download_options=download_options,
        )
        self.refresh_history()
        self._save_queue()
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

                self.lbl = QLabel(f"Queue completed.\n\nScheduled action: {act_name}.\nTime remaining: {self.seconds_left} seconds.")
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
                self.lbl.setText(f"Queue completed.\n\nScheduled action: {self.act_name}.\nTime remaining: {self.seconds_left} seconds.")
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
