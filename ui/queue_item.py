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

    def __init__(self, item_data, parent=None):
        super().__init__(parent)
        self.item_data = item_data
        self.status_state = "Pending"
        self.is_retry = False
        self.fetcher = None
        
        self.setObjectName("QueueItemCard")
        self.setMinimumHeight(80)
        self.setMaximumHeight(100)
        
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
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
        
        self.status_label = QLabel("Pending")
        self.status_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        
        details_layout.addWidget(self.title_label)
        details_layout.addWidget(self.subtitle_label)
        details_layout.addWidget(self.status_label)
        details_layout.addWidget(self.progress_bar)
        details_layout.addStretch()
        
        main_layout.addLayout(details_layout, 1)
        
        controls_layout = QVBoxLayout()
        controls_layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls_layout.setSpacing(6)
        
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
        self.format_combo.setFixedWidth(135)
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
        
        main_layout.addLayout(controls_layout)

    def _on_format_changed(self, text):
        self.item_data['media_type'] = text
        
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
        elif state == "Pending":
            self.progress_bar.hide()
            self.btn_remove.setEnabled(True)
            if getattr(self, "is_retry", False):
                self.status_label.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 500;")
            else:
                self.status_label.setStyleSheet("color: #cbd5e1; font-size: 12px;")

    def update_progress(self, percent, speed_clean, eta_clean):
        try:
            self.progress_bar.setValue(int(float(percent)))
        except ValueError:
            pass
        prefix = "Retrying... " if getattr(self, 'is_retry', False) else "Downloading... "
        self.status_label.setText(f"{prefix}{percent}% | {speed_clean} | ETA: {eta_clean}")
        if getattr(self, 'is_retry', False):
            self.status_label.setStyleSheet("color: #fbbf24; font-size: 12px; font-weight: 500;")
