import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont
from core.settings import get_app_data_dir


class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Logs")
        self.resize(760, 520)
        self.setMinimumSize(520, 360)
        
        self.log_file = get_app_data_dir() / "app_logs.txt"
        self._setup_ui()
        self.reload_logs()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Info
        header_layout = QHBoxLayout()
        header_lbl = QLabel("Application Logs")
        header_lbl.setStyleSheet("font-size: 15px; font-weight: bold; color: #f8fafc;")
        
        self.path_lbl = QLabel(f"Location: {self.log_file}")
        self.path_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
        
        header_layout.addWidget(header_lbl)
        header_layout.addStretch()
        header_layout.addWidget(self.path_lbl)
        layout.addLayout(header_layout)

        # Log Text Box
        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #0b1329;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                line-height: 1.4;
            }
        """)
        layout.addWidget(self.text_edit, 1)

        # Bottom Toolbar
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.btn_open_folder = QPushButton("Open Log Folder")
        self.btn_open_folder.clicked.connect(self.open_log_folder)
        
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.reload_logs)

        self.btn_clear = QPushButton("Clear Logs")
        self.btn_clear.clicked.connect(self.clear_logs)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)

        bottom_layout.addWidget(self.btn_open_folder)
        bottom_layout.addWidget(self.btn_refresh)
        bottom_layout.addWidget(self.btn_clear)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_close)

        layout.addLayout(bottom_layout)

    def reload_logs(self):
        if self.log_file.exists():
            try:
                content = self.log_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                content = f"Error reading log file: {e}"
        else:
            content = "No log records found. (app_logs.txt is empty or not yet created)"

        self.text_edit.setPlainText(content)
        # Scroll to bottom
        scrollbar = self.text_edit.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def clear_logs(self):
        try:
            self.log_file.write_text("", encoding="utf-8")
        except Exception:
            pass
        self.reload_logs()

    def open_log_folder(self):
        log_dir = get_app_data_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
