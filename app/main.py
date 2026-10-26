"""App entry: QApplication bootstrap"""
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .storage import APP_NAME
from .ui.main_window import MainWindow


def res_path(rel):
    """Resolve an asset path under PyInstaller, Nuitka and plain-python runs"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)          # PyInstaller
    if meipass:
        candidates.append(os.path.join(meipass, rel))
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        # Nuitka (standalone/onefile): data files sit beside the executable
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), rel))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates.append(os.path.join(root, rel))
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[-1]


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setStyle("Fusion")

    icon = QIcon(res_path(os.path.join("assets", "icon.ico")))
    if icon.isNull():
        icon = QIcon(res_path(os.path.join("assets", "icon.png")))
    app.setWindowIcon(icon)

    from .storage import Config
    config = Config.instance()

    win = MainWindow(config, icon)
    if "--minimized" in sys.argv:
        win.hide()
    else:
        win.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
