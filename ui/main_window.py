import sys
import requests
import re
import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QProgressBar, 
    QComboBox, QMessageBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QFileDialog, QFormLayout,
    QApplication, QRadioButton, QButtonGroup, QGroupBox, QScrollArea, QDialog,
    QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QDesktopServices, QAction, QIcon
from PyQt6.QtCore import QUrl

from core.preview import get_video_preview
from core.downloader import MediaDownloader
from core.settings import SettingsManager
from core.history import HistoryManager
from ui.styles import get_stylesheet
from ui.queue_item import QueueItemWidget

class WorkerThread(QThread):
    progress_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool, str, bool)

    def __init__(self, url, media_type, output_dir, quality, cookies, subtitles, playlist_index=None, playlist_count=None):
        super().__init__()
        self.url = url
        self.media_type = media_type
        self.output_dir = output_dir
        self.quality = quality
        self.cookies = cookies
        self.subtitles = subtitles
        self.playlist_index = playlist_index
        self.playlist_count = playlist_count
        
    def run(self):
        downloader = MediaDownloader(output_dir=self.output_dir)
        
        def progress_callback(d):
            self.progress_signal.emit(d)
            
        success, error_msg, was_skipped = downloader.download(
            self.url, 
            media_type=self.media_type,
            quality=self.quality,
            cookies=self.cookies,
            subtitles=self.subtitles,
            progress_callback=progress_callback,
            playlist_index=self.playlist_index,
            playlist_count=self.playlist_count
        )
        self.finished_signal.emit(success, error_msg, was_skipped)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Logovo Downloads")
        self.setMinimumSize(850, 700)
        self.setStyleSheet(get_stylesheet())
        
        self.setup_tray()
        
        self.settings = SettingsManager()
        self.history = HistoryManager()
        
        # Add session divider to logs
        try:
            from core.settings import get_app_data_dir
            import datetime
            log_file = get_app_data_dir() / "app_logs.txt"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'-'*20} New Session: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {'-'*20}\n")
        except:
            pass
        
        self.download_queue = []  # List of QueueItemWidget
        self.failed_queue = []    # List of (item_data, error_msg)
        self.is_downloading = False
        self.current_widget = None
        
        self.success_count = 0
        self.error_count = 0
        
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        self.setup_downloads_tab()
        self.setup_history_tab()
        self.setup_settings_tab()
        self.setup_about_tab()
        
        self.worker = None

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon("media/icon.ico"))
        
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

    def setup_downloads_tab(self):
        self.downloads_tab = QWidget()
        
        layout = QVBoxLayout(self.downloads_tab)
        
        # Top Toolbar
        toolbar = QHBoxLayout()
        self.btn_paste = QPushButton("Paste from clipboard")
        self.btn_load = QPushButton("Load from file")
        self.btn_quick_settings = QPushButton("Quick Settings")
        
        self.btn_paste.clicked.connect(self.paste_from_clipboard)
        self.btn_load.clicked.connect(self.load_from_file)
        self.btn_quick_settings.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        
        toolbar.addWidget(self.btn_paste)
        toolbar.addWidget(self.btn_load)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_quick_settings)
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
        queue_layout.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems([
            "Audio (Best)",
            "Audio (MP3)",
            "Audio (FLAC)",
            "Audio (Opus)",
            "Video (Best)",
            "Video (H.264)",
            "Video (H.265)"
        ])
        self.format_combo.insertSeparator(4)
        queue_layout.addWidget(self.format_combo)
        
        queue_layout.addWidget(QLabel(" Subs:"))
        self.subs_combo = QComboBox()
        self.subs_combo.addItems(["None", "All", "en", "ru", "es", "auto"])
        self.subs_combo.setEnabled(self.settings.get('download_subtitles'))
        queue_layout.addWidget(self.subs_combo)
        
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
        layout.addWidget(self.status_label)
        
        # Bottom Bar
        bottom_bar = QHBoxLayout()
        self.btn_download_all = QPushButton("Download")
        self.btn_download_all.setMinimumHeight(40)
        self.btn_download_all.clicked.connect(self.start_queue)
        self.btn_download_all.setEnabled(False)
        
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_download)
        
        self.btn_clear_completed = QPushButton("Clear Completed")
        self.btn_clear_completed.clicked.connect(self.clear_completed)
        
        btn_open_folder = QPushButton("Open Folder")
        self.btn_logs = QPushButton("Logs")
        self.btn_logs.setFixedWidth(80)
        self.btn_logs.clicked.connect(self.show_logs)
        btn_open_folder.clicked.connect(self.open_downloads_folder)
        
        bottom_bar.addWidget(self.btn_download_all)
        bottom_bar.addWidget(self.btn_stop)
        bottom_bar.addWidget(self.btn_clear_completed)
        bottom_bar.addStretch()
        bottom_bar.addWidget(btn_open_folder)
        bottom_bar.addWidget(self.btn_logs)
        layout.addLayout(bottom_bar)
        
        self.tabs.addTab(self.downloads_tab, "DOWNLOADS")

    # --- history and settings tabs skipped for brevity, just keeping them identical ---
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
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        
        # Hide the vertical header (row numbers) for a cleaner look
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.history_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout.addWidget(self.history_table)
        
        self.history_stats_label = QLabel("Total: 0 | Completed: 0 | Errors: 0")
        layout.addWidget(self.history_stats_label)
        
        self.refresh_history()
        self.tabs.addTab(self.history_tab, "HISTORY")

    def setup_settings_tab(self):
        self.settings_tab = QWidget()
        layout = QVBoxLayout(self.settings_tab)
        
        folder_layout = QHBoxLayout()
        self.folder_input = QLineEdit(self.settings.get('download_path'))
        self.folder_input.setReadOnly(True)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_folder)
        folder_layout.addWidget(QLabel("Download Folder:"))
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(btn_browse)
        layout.addLayout(folder_layout)
        
        self.chk_subtitles = QCheckBox("Download subtitles (if available)")
        self.chk_subtitles.setChecked(self.settings.get('download_subtitles'))
        self.chk_subtitles.toggled.connect(self.toggle_subs_setting)
        layout.addWidget(self.chk_subtitles)
        
        cookie_group = QGroupBox("Cookies")
        cookie_layout = QVBoxLayout()
        self.chk_cookies = QCheckBox("Use Cookies")
        self.chk_cookies.setChecked(self.settings.get('use_cookies'))
        self.chk_cookies.toggled.connect(self.toggle_cookies)
        cookie_layout.addWidget(self.chk_cookies)
        
        self.cookie_options_widget = QWidget()
        cookie_opt_layout = QVBoxLayout(self.cookie_options_widget)
        cookie_opt_layout.setContentsMargins(20, 0, 0, 0)
        
        self.radio_browser = QRadioButton("From browser")
        self.radio_file = QRadioButton("Cookie file")
        
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(["chrome", "edge", "firefox", "opera", "brave", "vivaldi", "safari"])
        self.browser_combo.setCurrentText(self.settings.get('cookie_browser'))
        self.browser_combo.currentTextChanged.connect(lambda t: self.settings.set('cookie_browser', t))
        
        file_layout = QHBoxLayout()
        self.cookie_file_input = QLineEdit(self.settings.get('cookie_file'))
        self.cookie_file_input.setReadOnly(True)
        self.btn_cookie_browse = QPushButton("Select file")
        self.btn_cookie_browse.clicked.connect(self.browse_cookie_file)
        file_layout.addWidget(self.cookie_file_input)
        file_layout.addWidget(self.btn_cookie_browse)
        
        cookie_opt_layout.addWidget(self.radio_browser)
        cookie_opt_layout.addWidget(self.browser_combo)
        cookie_opt_layout.addWidget(self.radio_file)
        cookie_opt_layout.addLayout(file_layout)
        
        self.lbl_cookie_help = QLabel(
            "Instructions:\n"
            "• From browser: The selected browser MUST be closed before downloading starts.\n"
            "• Cookie file: Use the 'Get cookies.txt LOCALLY' extension to export your cookies."
        )
        self.lbl_cookie_help.setStyleSheet("color: #94a3b8; font-size: 11px; padding-top: 5px;")
        cookie_opt_layout.addWidget(self.lbl_cookie_help)
        
        if self.settings.get('cookie_source_type') == 'browser':
            self.radio_browser.setChecked(True)
        else:
            self.radio_file.setChecked(True)
            
        self.radio_browser.toggled.connect(lambda c: self.settings.set('cookie_source_type', 'browser') if c else None)
        self.radio_file.toggled.connect(lambda c: self.settings.set('cookie_source_type', 'file') if c else None)
        
        cookie_group.setLayout(cookie_layout)
        cookie_layout.addWidget(self.cookie_options_widget)
        layout.addWidget(cookie_group)
        self.toggle_cookies(self.chk_cookies.isChecked())
        
        layout.addWidget(QLabel("\nQuality Settings"))
        quality_grid = QGridLayout()
        
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
            combo = QComboBox()
            combo.addItems(options)
            combo.setCurrentText(self.settings.get_quality(plat))
            combo.currentTextChanged.connect(lambda t, p=plat: self.settings.set_quality(p, t))
            quality_grid.addWidget(combo, i // 2, (i % 2) * 3 + 1)
            quality_grid.setColumnStretch((i % 2) * 3 + 2, 1)
            
        layout.addLayout(quality_grid)
        layout.addStretch()
        self.tabs.addTab(self.settings_tab, "SETTINGS")

    def setup_about_tab(self):
        self.about_tab = QWidget()
        layout = QVBoxLayout(self.about_tab)
        layout.addStretch()
        title = QLabel("Logovo Downloads")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #ffffff;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        version = QLabel("Version: 1.0.0-beta")
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

    # --- Actions ---
    
    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text())
        
    def load_from_file(self):
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
                        })
                self.status_label.setText(f"Added links from file.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to read file: {e}")
                
    def clear_queue(self):
        for widget in list(self.download_queue):
            if widget.status_state != "Downloading":
                self.queue_container_layout.removeWidget(widget)
                widget.deleteLater()
                self.download_queue.remove(widget)
        self.update_queue_ui()
        self.status_label.setText("Queue cleared (except active downloads).")
        
    def clear_completed(self):
        for widget in list(self.download_queue):
            if widget.status_state in ["Success", "Error"]:
                self.queue_container_layout.removeWidget(widget)
                widget.deleteLater()
                self.download_queue.remove(widget)
        self.update_queue_ui()
        self.status_label.setText("Completed items removed from queue.")

    def open_downloads_folder(self):
        folder = self.settings.get('download_path')
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if folder:
            self.folder_input.setText(folder)
            self.settings.set('download_path', folder)
            
    def browse_cookie_file(self):
        file, _ = QFileDialog.getOpenFileName(self, "Select Cookie File", "", "Text Files (*.txt);;All Files (*)")
        if file:
            self.cookie_file_input.setText(file)
            self.settings.set('cookie_file', file)
            
    def toggle_cookies(self, checked):
        self.settings.set('use_cookies', checked)
        self.cookie_options_widget.setEnabled(checked)
        
    def toggle_subs_setting(self, checked):
        self.settings.set('download_subtitles', checked)
        self.subs_combo.setEnabled(checked)
        if not checked:
            self.subs_combo.setCurrentText("None")

    def refresh_history(self):
        entries = self.history.get_all()
        self.history_table.setRowCount(len(entries))
        completed = 0
        errors = 0
        for row, entry in enumerate(entries):
            date_item = QTableWidgetItem(entry.get('date', ''))
            date_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(row, 0, date_item)
            
            author_item = QTableWidgetItem(entry.get('author', 'Unknown Author'))
            self.history_table.setItem(row, 1, author_item)
            
            self.history_table.setItem(row, 2, QTableWidgetItem(entry.get('title', '')))
            
            # Determine platform from URL
            url = entry.get('url', '')
            platform = "YouTube" if "youtube.com" in url or "youtu.be" in url else ("Twitch" if "twitch.tv" in url else "Unknown")
            plat_item = QTableWidgetItem(platform)
            plat_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.history_table.setItem(row, 3, plat_item)
            
            status = entry.get('status', '')
            status_item = QTableWidgetItem(status)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if status == "Success":
                status_item.setText("Completed")
                status_item.setForeground(Qt.GlobalColor.green)
                completed += 1
            elif status == "Failed":
                status_item.setText("Error")
                status_item.setForeground(Qt.GlobalColor.red)
                errors += 1
            self.history_table.setItem(row, 4, status_item)
            
        self.history_stats_label.setText(f"Total: {len(entries)} | Completed: {completed} | Errors: {errors}")

    def show_logs(self):
        from PyQt6.QtWidgets import QDialog, QTextEdit
        from core.settings import get_app_data_dir
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Application Logs")
        dialog.resize(600, 400)
        
        layout = QVBoxLayout(dialog)
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setStyleSheet("background-color: #0b0e14; color: #e2e8f0; font-family: monospace;")
        
        log_file = get_app_data_dir() / "app_logs.txt"
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                text_edit.setPlainText(f.read())
        else:
            text_edit.setPlainText("No errors logged yet.")
            
        layout.addWidget(text_edit)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()

    def clear_history(self):
        self.history.clear()
        self.refresh_history()

    def add_to_queue_action(self):
        url = self.url_input.text().strip()
        if not url: return
        self.status_label.setText("Fetching info...")
        self.btn_add_queue.setEnabled(False)
        QApplication.processEvents() # Update UI to show fetching status
        
        preview = get_video_preview(url)
        if preview:
            if preview.get('is_playlist'):
                count = preview.get('count', 0)
                reply = QMessageBox.question(self, "This is a playlist", f"The link contains {count} videos. Add them all to the queue?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply == QMessageBox.StandardButton.Yes:
                    global_path = self.settings.get('download_path')
                    default_path = os.path.join(global_path, preview.get('title', 'Playlist'))
                    
                    msgBox = QMessageBox(self)
                    msgBox.setWindowTitle("Playlist Destination")
                    msgBox.setText(f"Save this playlist to a new folder?\n\n{default_path}")
                    btn_yes = msgBox.addButton("Yes (Auto)", QMessageBox.ButtonRole.YesRole)
                    btn_custom = msgBox.addButton("Choose Custom...", QMessageBox.ButtonRole.AcceptRole)
                    btn_cancel = msgBox.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                    msgBox.exec()
                    
                    if msgBox.clickedButton() == btn_cancel:
                        self.status_label.setText("Playlist addition cancelled.")
                        self.btn_add_queue.setEnabled(True)
                        return
                    elif msgBox.clickedButton() == btn_yes:
                        out_dir = default_path
                    else:
                        out_dir = QFileDialog.getExistingDirectory(self, "Select Playlist Folder", global_path)
                        if not out_dir:
                            self.status_label.setText("Playlist addition cancelled.")
                            self.btn_add_queue.setEnabled(True)
                            return
                            
                    if not os.path.exists(out_dir):
                        os.makedirs(out_dir, exist_ok=True)
                    else:
                        # Orphan detection
                        local_files = [f for f in os.listdir(out_dir) if os.path.isfile(os.path.join(out_dir, f)) and not f.startswith('.')]
                        playlist_ids = {e.get('url').split('v=')[-1].split('&')[0] for e in preview.get('entries', []) if e.get('url')}
                        archive_path = os.path.join(out_dir, ".downloaded_archive.txt")
                        if not os.path.exists(archive_path):
                            archive_path = os.path.join(out_dir, "downloaded_archive.txt")
                        
                        archived_ids = set()
                        if os.path.exists(archive_path):
                            try:
                                with open(archive_path, 'r', encoding='utf-8') as f:
                                    for line in f:
                                        parts = line.strip().split()
                                        if len(parts) >= 2:
                                            archived_ids.add(parts[1])
                            except Exception:
                                pass
                                
                        orphan_ids = archived_ids - playlist_ids
                        if orphan_ids and local_files:
                            current_titles = [e.get('title', '').lower() for e in preview.get('entries', []) if e.get('title')]
                            valid_exts = ('.mp3', '.mp4', '.webm', '.m4a', '.wav', '.flac', '.opus', '.ogg', '.mkv', '.avi')
                            files_to_delete = []
                            for f in local_files:
                                f_lower = f.lower()
                                if not f_lower.endswith(valid_exts):
                                    continue
                                if not any(t in f_lower for t in current_titles if len(t) >= 2):
                                    files_to_delete.append(f)
                            
                            if files_to_delete:
                                links_text = "\n".join([f"https://youtube.com/watch?v={oid}" for oid in orphan_ids])
                                files_text = "\n".join(files_to_delete)
                                
                                msg = f"Found {len(orphan_ids)} tracks in this folder's archive that were removed from the YouTube playlist.\n\n"
                                msg += f"Removed Links:\n{links_text}\n\n"
                                msg += f"Suspected Local Files:\n{files_text}\n\n"
                                msg += "Do you want to delete these local files?"
                                
                                class OrphanDialog(QDialog):
                                    def __init__(self, msg_text, parent=None):
                                        super().__init__(parent)
                                        self.setWindowTitle("Orphan Detection")
                                        self.resize(600, 500)
                                        layout = QVBoxLayout(self)
                                        scroll = QScrollArea()
                                        scroll.setWidgetResizable(True)
                                        content = QWidget()
                                        content_layout = QVBoxLayout(content)
                                        label = QLabel(msg_text)
                                        label.setWordWrap(True)
                                        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                                        content_layout.addWidget(label)
                                        scroll.setWidget(content)
                                        layout.addWidget(scroll)
                                        btn_layout = QHBoxLayout()
                                        btn_yes = QPushButton("Yes, delete them")
                                        btn_no = QPushButton("No, keep them")
                                        btn_yes.clicked.connect(self.accept)
                                        btn_no.clicked.connect(self.reject)
                                        btn_layout.addWidget(btn_yes)
                                        btn_layout.addWidget(btn_no)
                                        layout.addLayout(btn_layout)
                                
                                dialog = OrphanDialog(msg, self)
                                if dialog.exec() == QDialog.DialogCode.Accepted:
                                    deleted_count = 0
                                    for f in files_to_delete:
                                        try:
                                            os.remove(os.path.join(out_dir, f))
                                            deleted_count += 1
                                        except Exception:
                                            pass
                                    QMessageBox.information(self, "Orphans Deleted", f"Deleted {deleted_count} orphaned files.")
                        
                    for i, entry in enumerate(preview.get('entries', [])):
                        entry['playlist_output_dir'] = out_dir
                        # Reverse index: first item gets 'count', last item gets '1'
                        entry['playlist_index'] = count - i
                        entry['playlist_count'] = count
                        self._add_single_item_to_queue(entry)
                    self.status_label.setText(f"Added {count} videos from playlist.")
                else:
                    self.status_label.setText("Playlist addition cancelled.")
            else:
                preview['url'] = url
                self._add_single_item_to_queue(preview)
                self.status_label.setText("Added to queue.")
        else:
            self.status_label.setText("Error fetching info.")
            
        self.btn_add_queue.setEnabled(True)

    def _add_single_item_to_queue(self, info_dict):
        url = info_dict.get('url')
        media_type = self.format_combo.currentText()
        
        # Deduplication
        for widget in self.download_queue:
            if widget.item_data.get('url') == url and widget.item_data.get('media_type') == media_type:
                return # Skip duplicate
        
        # Inject our chosen format and subs into the dict
        info_dict['media_type'] = media_type
        info_dict['specific_subs'] = self.subs_combo.currentText()
        
        widget = QueueItemWidget(info_dict)
        widget.remove_requested.connect(self.remove_queue_item)
        
        self.queue_container_layout.addWidget(widget)
        self.download_queue.append(widget)
        self.update_queue_ui()
        
    def remove_queue_item(self, widget):
        if widget in self.download_queue:
            self.queue_container_layout.removeWidget(widget)
            widget.deleteLater()
            self.download_queue.remove(widget)
            self.update_queue_ui()

    def update_queue_ui(self):
        count = len(self.download_queue)
        pending_count = sum(1 for w in self.download_queue if w.status_state == "Pending")
        self.stats_label.setText(f"Success: {self.success_count} | In queue: {pending_count} | Errors: {self.error_count}")
        
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
            
        if self.settings.get('use_cookies') and self.settings.get('cookie_source_type') == 'browser':
            browser = self.settings.get('cookie_browser')
            import os
            try:
                tasklist = os.popen(f'tasklist | findstr /I "{browser}.exe"').read()
                if tasklist.strip():
                    reply = QMessageBox.question(
                        self, 
                        "Browser Running", 
                        f"To extract cookies from {browser.title()}, it MUST be closed.\n\nDo you want to forcefully close {browser.title()} now?", 
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        os.system(f'taskkill /IM {browser}.exe /F')
                        import time
                        time.sleep(1)
            except Exception:
                pass
                
        self.is_downloading = True
        self.btn_download_all.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.process_next_in_queue()

    def stop_download(self):
        self.is_downloading = False
        self.btn_stop.setEnabled(False)
        self.status_label.setText("Download stopped.")
        # Actually stopping the thread cleanly requires thread flags, but for now we just prevent the next item from starting.

    def process_next_in_queue(self):
        if not self.is_downloading:
            self.update_queue_ui()
            return
            
        # Find next pending widget
        self.current_widget = None
        for widget in self.download_queue:
            if widget.status_state == "Pending":
                self.current_widget = widget
                break
                
        if not self.current_widget:
            self.is_downloading = False
            self.btn_stop.setEnabled(False)
            self.status_label.setText("All downloads finished!")
            self.update_queue_ui()
            
            if hasattr(self, 'tray_icon') and self.tray_icon.isVisible():
                self.tray_icon.showMessage("Logovo Downloads", "All downloads finished!", QSystemTrayIcon.MessageIcon.Information, 3000)
                
            if getattr(self, 'failed_queue', None):
                self.show_failed_summary()
            return
            
        self.update_queue_ui()
        
        self.current_widget.set_status("Starting...", "Downloading")
        
        item_data = self.current_widget.item_data
        url = item_data['url']
        media_type = item_data['media_type']
        output_dir = self.settings.get('download_path')
        
        platform = "YouTube"
        if "twitch.tv" in url: platform = "Twitch"
        elif "soundcloud.com" in url: platform = "SoundCloud"
        elif "spotify.com" in url: platform = "Spotify"
        elif "facebook.com" in url or "fb.watch" in url: platform = "Facebook"
        elif "instagram.com" in url: platform = "Instagram"
        elif "twitter.com" in url or "x.com" in url: platform = "Twitter (X)"
        elif "tiktok.com" in url: platform = "TikTok"
        
        quality = self.settings.get_quality(platform)
        
        cookies = {
            'use': self.settings.get('use_cookies'),
            'source': self.settings.get('cookie_source_type'),
            'browser': self.settings.get('cookie_browser'),
            'file': self.settings.get('cookie_file')
        }
        
        specific_subs = item_data.get('specific_subs', 'None')
        if specific_subs == 'None':
            subs_download = False
            subs_langs = 'all'
        elif specific_subs == 'All':
            subs_download = True
            subs_langs = 'all'
        else:
            subs_download = True
            subs_langs = specific_subs.split(' (auto)')[0]
            
        subtitles = {
            'download': subs_download,
            'langs': subs_langs
        }
        
        # Pull playlist metadata if available
        playlist_index = item_data.get('playlist_index')
        playlist_count = item_data.get('playlist_count')
        out_dir = item_data.get('playlist_output_dir', output_dir)
        
        self.worker = WorkerThread(
            url, media_type, out_dir, quality, cookies, subtitles,
            playlist_index=playlist_index, playlist_count=playlist_count
        )
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.task_finished)
        self.worker.start()

    def update_progress(self, d):
        if not self.current_widget: return
        
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '0.0%').replace('%', '').strip()
            percent_clean = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
            speed_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_speed_str', 'N/A')).strip()
            eta_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_eta_str', 'Unknown')).strip()
            
            self.current_widget.update_progress(percent_clean, speed_clean, eta_clean)
            
        elif d['status'] == 'finished':
            self.current_widget.set_status("Post-processing...", "Downloading")

    def task_finished(self, success, error_msg="", was_skipped=False):
        if not self.current_widget: return
        
        item_data = self.current_widget.item_data
        title = item_data.get('title', 'Unknown')
        author = item_data.get('uploader') or item_data.get('artist') or item_data.get('creator') or item_data.get('channel', 'Unknown')
        url = item_data.get('url')
        media_type = item_data.get('media_type')
        status_text = "Success" if success else "Failed"
        if was_skipped:
            status_text = "Skipped"
        
        if success:
            self.success_count += 1
            if was_skipped:
                self.current_widget.set_status("Skipped / Already downloaded", "Success")
            else:
                self.current_widget.set_status("Finished", "Success")
        else:
            self.error_count += 1
            self.current_widget.set_status("Error", "Error")
            self.failed_queue.append((item_data, error_msg))
            
        self.history.add_entry(title, author, url, media_type, status_text)
        self.refresh_history()
        
        self.current_widget = None
        self.process_next_in_queue()
        
    def show_failed_summary(self):
        if not self.failed_queue: return
        
        msg = f"Failed to download {len(self.failed_queue)} track(s):\n\n"
        for i, (item_data, error) in enumerate(self.failed_queue[:5]):
            msg += f"• {item_data.get('title', 'Unknown')} - {error}\n"
        if len(self.failed_queue) > 5:
            msg += f"... and {len(self.failed_queue) - 5} more.\n"
            
        msg += "\nDo you want to retry the failed tracks now?"
        
        reply = QMessageBox.question(self, "Download Errors", msg, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        
        if reply == QMessageBox.StandardButton.Yes:
            items_to_retry = [item for item, err in self.failed_queue]
            self.failed_queue.clear()
            
            for item in items_to_retry:
                self._add_single_item_to_queue(item)
                
            self.start_queue()
        else:
            self.failed_queue.clear()
