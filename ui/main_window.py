import sys
import requests
import re
import os
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QProgressBar, 
    QComboBox, QMessageBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox, QFileDialog, QFormLayout,
    QApplication, QRadioButton, QButtonGroup, QGroupBox, QSpacerItem, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QDesktopServices
from PyQt6.QtCore import QUrl

from core.preview import get_video_preview
from core.downloader import MediaDownloader
from core.settings import SettingsManager
from core.history import HistoryManager
from ui.styles import get_stylesheet

class WorkerThread(QThread):
    progress_signal = pyqtSignal(dict)
    finished_signal = pyqtSignal(bool)

    def __init__(self, url, media_type, output_dir, quality, cookies, subtitles):
        super().__init__()
        self.url = url
        self.media_type = media_type
        self.output_dir = output_dir
        self.quality = quality
        self.cookies = cookies
        self.subtitles = subtitles
        
    def run(self):
        downloader = MediaDownloader(output_dir=self.output_dir)
        
        def progress_callback(d):
            self.progress_signal.emit(d)
            
        success = downloader.download(
            self.url, 
            media_type=self.media_type,
            quality=self.quality,
            cookies=self.cookies,
            subtitles=self.subtitles,
            progress_callback=progress_callback
        )
        self.finished_signal.emit(success)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Logovo Downloads")
        self.setMinimumSize(800, 650)
        self.setStyleSheet(get_stylesheet())
        
        self.settings = SettingsManager()
        self.history = HistoryManager()
        
        self.download_queue = []  
        self.is_downloading = False
        self.current_preview_subs = []
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

    def setup_downloads_tab(self):
        self.downloads_tab = QWidget()
        
        # Use top alignment so everything packs tightly and doesn't spread out when maximized
        layout = QVBoxLayout(self.downloads_tab)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
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
        self.preview_btn = QPushButton("Get Preview")
        self.preview_btn.clicked.connect(self.fetch_preview)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.preview_btn)
        layout.addLayout(url_layout)
        
        # Preview Area
        self.preview_label = QLabel("No preview loaded.")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(250)
        self.preview_label.setMaximumHeight(350)
        self.preview_label.setObjectName("CardWidget")
        layout.addWidget(self.preview_label)
        
        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.info_label)
        
        # We place a stretch here so the Top (URL + Preview) stays at the top,
        # and the Bottom (Queue controls, Progress, Download buttons) stays at the bottom.
        layout.addStretch()
        
        # Format Selection & Add to Queue
        queue_layout = QHBoxLayout()
        queue_layout.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(["audio", "video"])
        queue_layout.addWidget(self.format_combo)
        
        queue_layout.addWidget(QLabel(" Subs:"))
        self.subs_combo = QComboBox()
        self.subs_combo.addItem("None")
        self.subs_combo.setEnabled(self.settings.get('download_subtitles'))
        queue_layout.addWidget(self.subs_combo)
        
        self.btn_add_queue = QPushButton("Add to queue")
        self.btn_add_queue.clicked.connect(self.add_to_queue)
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
        
        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        
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
        
        self.btn_clear_completed = QPushButton("Clear Completed")
        btn_open_folder = QPushButton("Open Folder")
        btn_logs = QPushButton("Logs")
        
        btn_open_folder.clicked.connect(self.open_downloads_folder)
        
        bottom_bar.addWidget(self.btn_download_all)
        bottom_bar.addWidget(self.btn_stop)
        bottom_bar.addWidget(self.btn_clear_completed)
        bottom_bar.addStretch()
        bottom_bar.addWidget(btn_open_folder)
        bottom_bar.addWidget(btn_logs)
        layout.addLayout(bottom_bar)
        
        self.tabs.addTab(self.downloads_tab, "DOWNLOADS")

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
        self.history_table.setHorizontalHeaderLabels(["Date", "Title", "URL", "Type", "Status"])
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.history_table)
        
        self.history_stats_label = QLabel("Total: 0 | Completed: 0 | Errors: 0")
        layout.addWidget(self.history_stats_label)
        
        self.refresh_history()
        self.tabs.addTab(self.history_tab, "HISTORY")

    def setup_settings_tab(self):
        self.settings_tab = QWidget()
        layout = QVBoxLayout(self.settings_tab)
        
        # Download Folder
        folder_layout = QHBoxLayout()
        self.folder_input = QLineEdit(self.settings.get('download_path'))
        self.folder_input.setReadOnly(True)
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self.browse_folder)
        folder_layout.addWidget(QLabel("Download Folder:"))
        folder_layout.addWidget(self.folder_input)
        folder_layout.addWidget(btn_browse)
        layout.addLayout(folder_layout)
        
        # Subtitles
        self.chk_subtitles = QCheckBox("Download subtitles (if available)")
        self.chk_subtitles.setChecked(self.settings.get('download_subtitles'))
        self.chk_subtitles.toggled.connect(self.toggle_subs_setting)
        layout.addWidget(self.chk_subtitles)
        
        # Cookies Group
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
        
        # Quality Settings
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
        
        version = QLabel("Version: 1.1.0")
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
                
                added = 0
                for link in links:
                    if link:
                        self.download_queue.append({
                            'url': link,
                            'media_type': self.format_combo.currentText(),
                            'title': link, 
                            'specific_subs': 'None'
                        })
                        added += 1
                self.update_queue_ui()
                self.status_label.setText(f"Added {added} links from file to queue.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to read file: {e}")
                
    def clear_queue(self):
        self.download_queue.clear()
        self.update_queue_ui()
        self.status_label.setText("Queue cleared.")
        
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
            self.history_table.setItem(row, 0, QTableWidgetItem(entry.get('date', '')))
            self.history_table.setItem(row, 1, QTableWidgetItem(entry.get('title', '')))
            self.history_table.setItem(row, 2, QTableWidgetItem(entry.get('url', '')))
            self.history_table.setItem(row, 3, QTableWidgetItem(entry.get('type', '')))
            status = entry.get('status', '')
            self.history_table.setItem(row, 4, QTableWidgetItem(status))
            
            if status == "Success": completed += 1
            elif status == "Failed": errors += 1
            
        self.history_stats_label.setText(f"Total: {len(entries)} | Completed: {completed} | Errors: {errors}")

    def clear_history(self):
        self.history.clear()
        self.refresh_history()

    def fetch_preview(self):
        url = self.url_input.text().strip()
        if not url: return
        self.status_label.setText("Fetching preview...")
        self.preview_btn.setEnabled(False)
        self.preview_label.setText("Loading...")
        
        self.subs_combo.clear()
        self.subs_combo.addItem("None")
        
        preview = get_video_preview(url)
        if preview:
            self.current_preview_title = preview['title']
            duration_str = f"{preview['duration']} sec" if preview.get('duration') else "Unknown"
            self.info_label.setText(f"{preview['title']} ({duration_str})")
            
            if preview.get('subtitles_available'):
                self.subs_combo.addItem("All")
                self.subs_combo.addItems(preview['subtitles_available'])
                
                if self.settings.get('download_subtitles'):
                    self.subs_combo.setCurrentText("All")
            
            if preview.get('thumbnail'):
                try:
                    response = requests.get(preview['thumbnail'])
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    self.original_pixmap = pixmap
                    self.update_preview_image()
                except Exception:
                    self.preview_label.setText("Could not load image.")
            else:
                self.preview_label.setText("No thumbnail available.")
            
            self.status_label.setText("Preview loaded. Ready to add to queue.")
        else:
            self.current_preview_title = "Unknown"
            self.info_label.setText("Failed to load preview.")
            self.preview_label.setText("No preview loaded.")
            self.status_label.setText("Error fetching preview.")
        self.preview_btn.setEnabled(True)

    def update_preview_image(self):
        if hasattr(self, 'original_pixmap') and not self.original_pixmap.isNull():
            scaled = self.original_pixmap.scaled(
                self.preview_label.width() - 4, 
                self.preview_label.height() - 4, 
                Qt.AspectRatioMode.KeepAspectRatio, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview_image()

    def add_to_queue(self):
        url = self.url_input.text().strip()
        if not url: return
        
        media_type = self.format_combo.currentText()
        title = getattr(self, 'current_preview_title', url)
        specific_subs = self.subs_combo.currentText()
        
        # Prevent exact duplication (same URL and media type)
        for item in self.download_queue:
            if item['url'] == url and item['media_type'] == media_type:
                self.status_label.setText("Item already in queue with this format.")
                return
        
        self.download_queue.append({
            'url': url,
            'media_type': media_type,
            'title': title,
            'specific_subs': specific_subs
        })
        
        self.update_queue_ui()
        self.status_label.setText(f"Added to queue: {title}")
        
    def update_queue_ui(self):
        count = len(self.download_queue)
        self.stats_label.setText(f"Success: {self.success_count} | In queue: {count} | Errors: {self.error_count}")
        
        if count == 0:
            self.btn_download_all.setEnabled(False)
            self.btn_download_all.setText("Download")
        elif count == 1:
            self.btn_download_all.setEnabled(not self.is_downloading)
            self.btn_download_all.setText("Download")
        else:
            self.btn_download_all.setEnabled(not self.is_downloading)
            self.btn_download_all.setText("Download All")

    def start_queue(self):
        if not self.download_queue or self.is_downloading:
            return
            
        self.is_downloading = True
        self.btn_download_all.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        self.process_next_in_queue()

    def process_next_in_queue(self):
        if not self.download_queue:
            self.is_downloading = False
            self.btn_stop.setEnabled(False)
            self.status_label.setText("All downloads finished!")
            self.update_queue_ui()
            return
            
        self.current_task = self.download_queue.pop(0)
        self.update_queue_ui()
        
        url = self.current_task['url']
        media_type = self.current_task['media_type']
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
        
        specific_subs = self.current_task.get('specific_subs', 'None')
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
        
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Downloading: {self.current_task['title']}...")
        
        self.worker = WorkerThread(url, media_type, output_dir, quality, cookies, subtitles)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.task_finished)
        self.worker.start()

    def format_time(self, seconds):
        if seconds == 0: return "Unknown"
        if seconds < 60: return f"{seconds}s"
        m, s = divmod(seconds, 60)
        if m < 60: return f"{m}m {s}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m"

    def update_progress(self, d):
        if d['status'] == 'downloading':
            percent_str = d.get('_percent_str', '0.0%').replace('%', '').strip()
            percent_clean = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
            try:
                self.progress_bar.setValue(int(float(percent_clean)))
            except ValueError:
                pass
                
            speed_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_speed_str', 'N/A')).strip()
            eta_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_eta_str', 'Unknown')).strip()
            
            size_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_total_bytes_str', '')).strip()
            if not size_clean:
                size_clean = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_total_bytes_estimate_str', 'Unknown')).strip()
                
            current_eta_sec = 0
            if ':' in eta_clean:
                parts = eta_clean.split(':')
                if len(parts) == 2:
                    current_eta_sec = int(parts[0])*60 + int(parts[1])
                elif len(parts) == 3:
                    current_eta_sec = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
                    
            queue_len = len(self.download_queue)
            total_eta_sec = current_eta_sec * (queue_len + 1)
            total_eta_str = self.format_time(total_eta_sec)
            
            self.status_label.setText(
                f"Downloading: {percent_clean}% at {speed_clean} | "
                f"ETA (current): {eta_clean} | ETA (queue): {total_eta_str} | Size: {size_clean}"
            )
            
        elif d['status'] == 'finished':
            self.progress_bar.setValue(100)
            self.status_label.setText("Download finished, post-processing...")

    def task_finished(self, success):
        title = self.current_task['title']
        url = self.current_task['url']
        media_type = self.current_task['media_type']
        status = "Success" if success else "Failed"
        
        if success:
            self.success_count += 1
        else:
            self.error_count += 1
            
        self.history.add_entry(title, url, media_type, status)
        self.refresh_history()
        
        self.process_next_in_queue()
