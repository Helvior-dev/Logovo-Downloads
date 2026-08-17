import os
import re
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QTabWidget, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QApplication
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QFont, QColor
from core.settings import get_app_data_dir


class LogViewerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Logs & Activity")
        self.resize(820, 560)
        self.setMinimumSize(600, 420)
        
        self.log_file = get_app_data_dir() / "app_logs.txt"
        self._last_content = ""
        self._setup_ui()
        self.reload_logs(force=True)

        # Live auto-refresh timer (only reloads if log content changed)
        from PyQt6.QtCore import QTimer
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2000)
        self.refresh_timer.timeout.connect(self.reload_logs)
        self.refresh_timer.start()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Tabs: User Logs vs Dev Logs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #334155;
                background-color: #0f172a;
                border-radius: 8px;
            }
            QTabBar::tab {
                background: #1e293b;
                color: #94a3b8;
                padding: 8px 18px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 600;
                font-size: 12px;
            }
            QTabBar::tab:selected {
                background: #0f172a;
                color: #38bdf8;
                border-bottom: 2px solid #38bdf8;
            }
        """)

        # ─── TAB 1: USER FRIENDLY LOGS ───
        self.user_tab = QWidget()
        user_layout = QVBoxLayout(self.user_tab)
        user_layout.setContentsMargins(12, 12, 12, 12)
        user_layout.setSpacing(10)

        # Search / Filter Row
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filter logs by track name or event...")
        self.search_input.textChanged.connect(self._filter_user_logs)
        search_row.addWidget(self.search_input)
        user_layout.addLayout(search_row)

        self.user_table = QTableWidget()
        self.user_table.setColumnCount(4)
        self.user_table.setHorizontalHeaderLabels(["Date & Time", "Event / Track", "Status", "Summary"])
        self.user_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.user_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.user_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.user_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.user_table.verticalHeader().setVisible(False)
        self.user_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.user_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.user_table.setStyleSheet("""
            QTableWidget {
                background-color: #0b1329;
                color: #f8fafc;
                border: 1px solid #1e293b;
                border-radius: 6px;
                gridline-color: #1e293b;
            }
            QHeaderView::section {
                background-color: #1e293b;
                color: #94a3b8;
                padding: 6px;
                border: none;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        user_layout.addWidget(self.user_table)
        self.tabs.addTab(self.user_tab, "📋 User Logs")

        # ─── TAB 2: DEVELOPER RAW LOGS ───
        self.dev_tab = QWidget()
        dev_layout = QVBoxLayout(self.dev_tab)
        dev_layout.setContentsMargins(12, 12, 12, 12)
        dev_layout.setSpacing(10)

        self.text_edit = QPlainTextEdit()
        self.text_edit.setReadOnly(True)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet("""
            QPlainTextEdit {
                background-color: #080d1a;
                color: #cbd5e1;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 10px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
                line-height: 1.4;
            }
        """)
        dev_layout.addWidget(self.text_edit)
        self.tabs.addTab(self.dev_tab, "⚙️ Developer Logs (Raw)")

        main_layout.addWidget(self.tabs, 1)

        # Bottom Toolbar
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(10)

        self.btn_open_folder = QPushButton("Open Logs Folder")
        self.btn_open_folder.clicked.connect(self.open_log_folder)

        self.btn_copy = QPushButton("Copy All Logs")
        self.btn_copy.clicked.connect(self.copy_all_logs)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(lambda: self.reload_logs(force=True))

        self.btn_clear = QPushButton("Clear Logs")
        self.btn_clear.clicked.connect(self.clear_logs)

        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.accept)

        bottom_layout.addWidget(self.btn_open_folder)
        bottom_layout.addWidget(self.btn_copy)
        bottom_layout.addWidget(self.btn_refresh)
        bottom_layout.addWidget(self.btn_clear)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_close)

        main_layout.addLayout(bottom_layout)

    def reload_logs(self, force: bool = False):
        if self.log_file.exists():
            try:
                content = self.log_file.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                content = f"Error reading log file: {e}"
        else:
            content = "No log records found. (app_logs.txt is empty or not yet created)"

        if not force and content == getattr(self, "_last_content", None):
            return

        self._last_content = content

        # Retain developer log scroll position
        dev_sb = self.text_edit.verticalScrollBar()
        dev_was_at_bottom = (dev_sb.value() >= dev_sb.maximum() - 30) if dev_sb else True
        dev_prev_val = dev_sb.value() if dev_sb else 0

        self.text_edit.setPlainText(content)
        if dev_sb:
            if dev_was_at_bottom:
                dev_sb.setValue(dev_sb.maximum())
            else:
                dev_sb.setValue(dev_prev_val)

        # Retain user table scroll position
        tbl_sb = self.user_table.verticalScrollBar()
        tbl_prev_val = tbl_sb.value() if tbl_sb else 0

        self._parsed_records = self._parse_friendly_logs(content)
        self._populate_user_table(self._parsed_records)

        if tbl_sb and tbl_prev_val > 0:
            tbl_sb.setValue(tbl_prev_val)

    def _parse_friendly_logs(self, raw_text: str) -> list[dict]:
        records = []
        lines = raw_text.splitlines()
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Session dividers
            if line_str.startswith("---") and "session:" in line_str.lower():
                m_sess = re.search(r"session:\s*(\d{4})-(\d{2})-(\d{2})\s*(\d{2}:\d{2}:\d{2})", line_str, re.IGNORECASE)
                if m_sess:
                    sess_time = f"{m_sess.group(3)}/{m_sess.group(2)}/{m_sess.group(1)[2:]} {m_sess.group(4)}"
                else:
                    m_gen = re.search(r"session:\s*([^-\s]+(?:\s+[^-\s]+)?)", line_str, re.IGNORECASE)
                    sess_time = m_gen.group(1) if m_gen else ""
                records.append({
                    "time": sess_time,
                    "event": f"Session: {sess_time}",
                    "status": "Session",
                    "summary": "Application session started",
                    "color": "#38bdf8",
                    "is_divider": True
                })
                continue

            if line_str.startswith("---"):
                continue

            # Extract timestamp [YYYY-MM-DD HH:MM:SS] -> convert to DD/MM/YY HH:MM:SS
            time_match = re.match(r"^\[(\d{4})-(\d{2})-(\d{2})\s*(\d{2}:\d{2}:\d{2})\]\s*(.*)", line_str)
            if time_match:
                ts = f"{time_match.group(3)}/{time_match.group(2)}/{time_match.group(1)[2:]} {time_match.group(4)}"
                msg = time_match.group(5)
            else:
                ts = ""
                msg = line_str

            # Check for track tag prefix: "[Artist - Title] ERROR: ..."
            track_tag = ""
            m_track = re.match(r"^\[(.*?)\]\s*(.*)", msg)
            if m_track and not m_track.group(1).lower().startswith("youtube") and not m_track.group(1).lower().startswith("winerror"):
                track_tag = m_track.group(1).strip()
                msg = m_track.group(2).strip()

            # Check for explicit track failures: "Failed to download 'Title': Reason"
            m_fail = re.search(r"Failed to download '([^']+)':\s*(.*)", msg)
            if m_fail:
                records.append({
                    "time": ts,
                    "event": m_fail.group(1),
                    "status": "Failed",
                    "summary": m_fail.group(2),
                    "color": "#ef4444"
                })
                continue

            low = msg.lower()
            if "video unavailable" in low or "has been removed" in low or "copyright removal" in low:
                # Extract video id if present
                m_vid = re.search(r"\[youtube\]\s*([^:]+):", msg)
                vid_tag = f" (ID: {m_vid.group(1)})" if m_vid else ""
                event_name = track_tag or f"Deleted Video{vid_tag}"
                records.append({
                    "time": ts,
                    "event": event_name,
                    "status": "Removed",
                    "summary": "Track was removed from YouTube by copyright holder or channel owner",
                    "color": "#94a3b8"
                })
            elif "sign in to confirm your age" in low or "age-restricted" in low:
                m_vid = re.search(r"\[youtube\]\s*([^:]+):", msg)
                vid_tag = f" (ID: {m_vid.group(1)})" if m_vid else ""
                event_name = track_tag or f"Age-Restricted Track{vid_tag}"
                records.append({
                    "time": ts,
                    "event": event_name,
                    "status": "Cookies Required",
                    "summary": "YouTube age restriction — cookies needed for direct download",
                    "color": "#f59e0b"
                })
            elif "already downloaded" in low or "skipped" in low:
                event_name = track_tag or "Playlist Sync"
                records.append({
                    "time": ts,
                    "event": event_name,
                    "status": "Up to Date",
                    "summary": "Track already verified and present on local disk",
                    "color": "#38bdf8"
                })
            elif "[winerror" in low:
                event_name = track_tag or "Artwork Notice"
                records.append({
                    "time": ts,
                    "event": event_name,
                    "status": "Handled",
                    "summary": "Cover conversion notice handled automatically by internal embedder",
                    "color": "#94a3b8"
                })
            elif "error:" in low:
                clean_err = re.sub(r"^ERROR:\s*", "", msg)
                clean_err = re.sub(r"\[youtube\]\s*", "", clean_err)
                event_name = track_tag or "Download Notice"
                records.append({
                    "time": ts,
                    "event": event_name,
                    "status": "Notice",
                    "summary": clean_err[:140],
                    "color": "#ef4444"
                })
            elif "new session:" in low:
                records.append({
                    "time": ts,
                    "event": "App Session Started",
                    "status": "Info",
                    "summary": "Application opened and initialized",
                    "color": "#38bdf8"
                })

        return list(reversed(records)) # Latest events first

    def _populate_user_table(self, records: list[dict]):
        self.user_table.setRowCount(len(records))
        for row, rec in enumerate(records):
            is_divider = rec.get("is_divider", False)
            item_time = QTableWidgetItem(rec.get("time", ""))
            item_time.setForeground(QColor("#64748b"))
            item_time.setFlags(item_time.flags() & ~Qt.ItemFlag.ItemIsEditable)

            item_event = QTableWidgetItem(rec.get("event", ""))
            item_event.setFlags(item_event.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if is_divider:
                item_event.setForeground(QColor("#38bdf8"))
                f = item_event.font()
                f.setBold(True)
                item_event.setFont(f)
            else:
                item_event.setForeground(QColor("#f8fafc"))

            item_status = QTableWidgetItem(rec.get("status", ""))
            item_status.setForeground(QColor(rec.get("color", "#94a3b8")))
            item_status.setFlags(item_status.flags() & ~Qt.ItemFlag.ItemIsEditable)

            item_summary = QTableWidgetItem(rec.get("summary", ""))
            item_summary.setForeground(QColor("#cbd5e1" if not is_divider else "#64748b"))
            item_summary.setFlags(item_summary.flags() & ~Qt.ItemFlag.ItemIsEditable)

            self.user_table.setItem(row, 0, item_time)
            self.user_table.setItem(row, 1, item_event)
            self.user_table.setItem(row, 2, item_status)
            self.user_table.setItem(row, 3, item_summary)

    def _filter_user_logs(self, query: str):
        q = query.strip().lower()
        if not q:
            self._populate_user_table(getattr(self, "_parsed_records", []))
            return

        filtered = [
            r for r in getattr(self, "_parsed_records", [])
            if q in r.get("event", "").lower() or q in r.get("summary", "").lower() or q in r.get("status", "").lower()
        ]
        self._populate_user_table(filtered)

    def copy_all_logs(self):
        text = self.text_edit.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            clipboard.setText(text)
            self.btn_copy.setText("Copied!")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.btn_copy.setText("Copy All Logs"))

    def clear_logs(self):
        try:
            self.log_file.write_text("", encoding="utf-8")
        except Exception:
            pass
        self.reload_logs()

    def open_log_folder(self):
        log_dir = get_app_data_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_dir)))
