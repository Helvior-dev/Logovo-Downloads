import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from core.updater import init_ytdlp_core

# Initialize updated yt-dlp core from AppData if available
init_ytdlp_core()

from ui.main_window import MainWindow

def get_resource_path(relative_path: str) -> Path:
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path

def main():
    try:
        import ctypes
        myappid = 'logovo.downloads.app.1.4.0'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    
    icon_path = get_resource_path("media/icon.ico")
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)
    
    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
