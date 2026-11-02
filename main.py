import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from core.constants import APP_USER_MODEL_ID
from core.updater import init_ytdlp_core

# Initialize updated yt-dlp core from AppData if available
init_ytdlp_core(activate_pending=True)

from ui.main_window import MainWindow

def get_resource_path(relative_path: str) -> Path:
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path

def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
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
