import re
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QProgressBar, QPushButton, QSizePolicy, QComboBox
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QPixmap
import requests

class ThumbnailFetcher(QThread):
    finished = pyqtSignal(QPixmap)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        
    def run(self):
        try:
            response = requests.get(self.url, timeout=5)
            if response.status_code == 200:
                pixmap = QPixmap()
                pixmap.loadFromData(response.content)
                self.finished.emit(pixmap)
        except:
            pass

class QueueItemWidget(QWidget):
    remove_requested = pyqtSignal(object)  # Emits self when X is clicked

    @property
    def format_type(self) -> str:
        return self.item_data.get('format', 'Audio')

    def __init__(self, item_data, settings=None, parent=None):
        super().__init__(parent)
        self.item_data = item_data
        self.settings = settings
        self.status_state = "Pending"
        self.is_retry = False
        self.fetcher = None
        
        self.setObjectName("QueueItemCard")
        self.setMinimumHeight(92)
        self.setMaximumHeight(120)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(15)
        
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(100, 60)
        self.thumbnail_label.setStyleSheet("background-color: #1e293b; border-radius: 4px;")
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.btn_load_preview = QPushButton("Preview")
        self.btn_load_preview.setFixedSize(80, 24)
        self.btn_load_preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load_preview.setStyleSheet("""
            QPushButton {
                background: rgba(30, 41, 59, 0.9);
                color: #e2e8f0;
                border: 1px solid #94a3b8;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
                padding: 2px 0px;
            }
            QPushButton:hover {
                background: #334155;
                color: #ffffff;
                border: 1px solid #cbd5e1;
            }
        """)
        
        # Overlay button inside thumbnail
        self.btn_load_preview.setParent(self.thumbnail_label)
        self.btn_load_preview.move(10, 18) # Center it manually in the 100x60 box
        self.btn_load_preview.clicked.connect(self._on_load_preview)
        
        main_layout.addWidget(self.thumbnail_label)
        
        details_layout = QVBoxLayout()
        details_layout.setSpacing(5)
        
        self.title_label = QLabel(item_data.get('title', 'Unknown Title'))
        self.title_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #f8fafc;")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.title_label.setMinimumWidth(50)
        self.title_label.setWordWrap(False)
        
        platform = "YouTube"
        if "twitch.tv" in item_data.get('url', ''): platform = "Twitch"
        elif "soundcloud" in item_data.get('url', ''): platform = "SoundCloud"
        
        duration = item_data.get('duration')
        dur_str = ""
        if duration:
            try:
                dur = int(duration)
                if dur >= 3600:
                    dur_str = f" • {dur // 3600}:{dur % 3600 // 60:02d}:{dur % 60:02d}"
                else:
                    dur_str = f" • {dur // 60}:{dur % 60:02d}"
            except Exception:
                dur_str = f" • {duration}"
                
        # Include author/channel
        author = item_data.get('uploader') or item_data.get('channel') or item_data.get('artist') or "Unknown Author"
        self.subtitle_label = QLabel(f"{platform}{dur_str} • {author}")
        self.subtitle_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.subtitle_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.subtitle_label.setMinimumWidth(50)
        
        self.status_label = QLabel("Pending")
        self.status_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status_label.setMinimumWidth(50)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #1e293b;
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38bdf8, stop:1 #2563eb);
                border-radius: 3px;
            }
        """)
        self.progress_bar.hide()
        
        details_layout.addWidget(self.title_label)
        details_layout.addWidget(self.subtitle_label)
        details_layout.addWidget(self.status_label)
        details_layout.addWidget(self.progress_bar)
        details_layout.addStretch()
        
        main_layout.addLayout(details_layout, 1)
        
        controls_layout = QVBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls_layout.setSpacing(5)
        
        btn_top_row = QHBoxLayout()
        btn_top_row.addStretch()
        self.btn_remove = QPushButton("✕")
        self.btn_remove.setFixedSize(22, 22)
        self.btn_remove.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                color: #ef4444;
            }
        """)
        self.btn_remove.clicked.connect(self._on_remove)
        btn_top_row.addWidget(self.btn_remove)
        controls_layout.addLayout(btn_top_row)
        
        # Category: Audio or Video
        media_category = item_data.get('media_type_category')
        if not media_category:
            if "video" in str(item_data.get('media_type', '')).lower():
                media_category = "Video"
            else:
                media_category = "Audio"
                
        formats_from_preview = item_data.get('formats_available', [])
        
        self.format_combo = QComboBox()
        self.format_combo.setFixedWidth(145)
        self.format_combo.setFixedHeight(28)
        self.format_combo.setMaxVisibleItems(6)
        
        if media_category == "Audio":
            default_audio = ["Audio (Best)", "Audio (MP3)", "Audio (FLAC)", "Audio (M4A)", "Audio (Opus)", "Audio (WAV)"]
            available = [f for f in formats_from_preview if f.startswith("Audio")] if formats_from_preview else []
            for f in default_audio:
                if f not in available:
                    available.append(f)
            self.format_combo.addItems(available)
            current_fmt = item_data.get('media_type', 'Audio (Best)')
            if current_fmt in available:
                self.format_combo.setCurrentText(current_fmt)
            else:
                self.format_combo.setCurrentText("Audio (Best)")
                self.item_data['media_type'] = "Audio (Best)"
        else:
            default_video = ["Video (Best)", "Video (H.264)", "Video (H.265)"]
            available = [f for f in formats_from_preview if f.startswith("Video")] if formats_from_preview else []
            for f in default_video:
                if f not in available:
                    available.append(f)
            self.format_combo.addItems(available)
            current_fmt = item_data.get('media_type', 'Video (Best)')
            if current_fmt in available:
                self.format_combo.setCurrentText(current_fmt)
            else:
                self.format_combo.setCurrentText("Video (Best)")
                self.item_data['media_type'] = "Video (Best)"
                
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        controls_layout.addWidget(self.format_combo)

        # Per-item Subtitle / Lyrics Language Dropdown
        self.subs_combo = QComboBox()
        self.subs_combo.setFixedWidth(145)
        self.subs_combo.setFixedHeight(28)
        self.subs_combo.setMaxVisibleItems(6)
        self._populate_subs_combo()
        self.subs_combo.currentIndexChanged.connect(self._on_subs_changed)
        controls_layout.addWidget(self.subs_combo)
        
        main_layout.addLayout(controls_layout)

    def _populate_subs_combo(self):
        cur_fmt = self.format_combo.currentText() if hasattr(self, 'format_combo') else str(self.item_data.get('media_type', ''))
        media_category = self.item_data.get('media_type_category')
        if "video" in cur_fmt.lower():
            is_audio = False
        elif "audio" in cur_fmt.lower():
            is_audio = True
        else:
            is_audio = (media_category != "Video")
        
        if self.settings:
            is_enabled = self.settings.get('download_audio_lyrics', False) if is_audio else self.settings.get('download_subtitles', False)
            global_lang = self.settings.get('lyrics_langs', 'orig') if is_audio else self.settings.get('subtitles_langs', 'orig')
        else:
            is_enabled = False
            global_lang = 'orig'

        self.subs_combo.blockSignals(True)
        self.subs_combo.clear()

        if not is_enabled:
            label = "Lyrics: Off" if is_audio else "Subs: Off"
            self.subs_combo.addItem(label, "None")
            self.subs_combo.setEnabled(False)
            self.subs_combo.setToolTip("Subtitles/Lyrics disabled in Settings")
            self.item_data['specific_subs'] = 'None'
            self.subs_combo.blockSignals(False)
            return

        self.subs_combo.setEnabled(True)
        self.subs_combo.setToolTip("Select Subtitle / Lyrics language for this item")
        prefix = "Lyrics" if is_audio else "Subs"

        self.subs_combo.addItem(f"{prefix}: None", "None")
        self.subs_combo.addItem(f"{prefix}: Original", "orig")
        self.subs_combo.addItem(f"{prefix}: All", "all")

        available_subs = self.item_data.get('subtitles_available', [])
        for sub in available_subs:
            self.subs_combo.addItem(f"{prefix}: {sub}", sub)

        for code in ["en", "ru", "uk"]:
            if not any(code in s for s in available_subs):
                self.subs_combo.addItem(f"{prefix}: {code}", code)

        cur_specific = self.item_data.get('specific_subs')
        if cur_specific:
            idx = self.subs_combo.findData(cur_specific)
            if idx >= 0:
                self.subs_combo.setCurrentIndex(idx)
            else:
                self.subs_combo.setCurrentIndex(1)
        else:
            idx = self.subs_combo.findData(global_lang)
            if idx >= 0:
                self.subs_combo.setCurrentIndex(idx)
            else:
                self.subs_combo.setCurrentIndex(1)
            self.item_data['specific_subs'] = self.subs_combo.currentData()

        self.subs_combo.blockSignals(False)

    def _on_subs_changed(self, idx):
        self.item_data['specific_subs'] = self.subs_combo.currentData()

    def set_media_category(self, new_category: str):
        self.item_data['media_type_category'] = new_category
        self.format_combo.blockSignals(True)
        self.format_combo.clear()
        if new_category == "Video":
            items = ["Video (Best)", "Video (H.264)", "Video (H.265)"]
            self.format_combo.addItems(items)
            self.format_combo.setCurrentText("Video (Best)")
            self.item_data['media_type'] = "Video (Best)"
        else:
            items = ["Audio (Best)", "Audio (MP3)", "Audio (FLAC)", "Audio (M4A)", "Audio (Opus)", "Audio (WAV)"]
            self.format_combo.addItems(items)
            self.format_combo.setCurrentText("Audio (Best)")
            self.item_data['media_type'] = "Audio (Best)"
        self.format_combo.blockSignals(False)
        self._populate_subs_combo()

    def _on_format_changed(self, text):
        self.item_data['media_type'] = text
        if "video" in text.lower():
            self.item_data['media_type_category'] = "Video"
        else:
            self.item_data['media_type_category'] = "Audio"
        self._populate_subs_combo()
        
    def _on_load_preview(self):
        self.btn_load_preview.hide()
        
        thumb_url = self.item_data.get('thumbnail')
        url = self.item_data.get('url', '')
        
        # Fallback for YouTube thumbnails if yt-dlp didn't provide one
        if not thumb_url and ('youtube.com' in url or 'youtu.be' in url):
            import re
            match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', url)
            if match:
                video_id = match.group(1)
                thumb_url = f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"
                
        if thumb_url:
            self._load_thumbnail(thumb_url)

    def _load_thumbnail(self, url):
        self.fetcher = ThumbnailFetcher(url)
        self.fetcher.finished.connect(self.set_thumbnail)
        self.fetcher.start()

    def set_thumbnail(self, pixmap):
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.thumbnail_label.width(), 
                self.thumbnail_label.height(), 
                Qt.AspectRatioMode.KeepAspectRatioByExpanding, 
                Qt.TransformationMode.SmoothTransformation
            )
            self.thumbnail_label.setPixmap(scaled)

    def _on_remove(self):
        if self.status_state not in ["Downloading", "Retrying"]:
            self.remove_requested.emit(self)

    def set_status(self, text, state="Pending"):
        self.status_state = state
        self.status_label.setText(text)
        
        if state in ["Downloading", "Retrying"]:
            self.progress_bar.show()
            self.btn_remove.setEnabled(False)
            if state == "Retrying" or getattr(self, "is_retry", False):
                self.status_label.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 500;") # Yellow/Amber
            else:
                self.status_label.setStyleSheet("color: #38bdf8; font-size: 12px;") # Cyan
        elif state in ["Success", "Error"]:
            self.progress_bar.hide()
            self.btn_remove.setEnabled(True)
            if state == "Success":
                self.status_label.setStyleSheet("color: #10b981; font-size: 12px; font-weight: 500;") # Green
            else:
                self.status_label.setStyleSheet("color: #ef4444; font-size: 12px; font-weight: 500;") # Red
        elif state == "Unavailable":
            self.progress_bar.hide()
            self.btn_remove.setEnabled(True)
            self.status_label.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 500;") # Slate neutral
        elif state == "Pending":
            self.progress_bar.hide()
            self.btn_remove.setEnabled(True)
            if getattr(self, "is_retry", False):
                self.status_label.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 500;")
            else:
                self.status_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")

    def update_progress(self, percent, speed_clean, eta_clean):
        try:
            val = int(float(percent))
            self.progress_bar.setValue(val)
        except (ValueError, TypeError):
            val = 0
        if not self.progress_bar.isVisible():
            self.progress_bar.show()
        prefix = "Retrying... " if getattr(self, 'is_retry', False) else "Downloading... "
        self.status_label.setText(f"{prefix}{percent}% | {speed_clean} | ETA: {eta_clean}")
        if getattr(self, 'is_retry', False):
            self.status_label.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 500;")
        else:
            self.status_label.setStyleSheet("color: #38bdf8; font-size: 12px;")
