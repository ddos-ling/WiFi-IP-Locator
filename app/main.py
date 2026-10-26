"""App entry: QApplication bootstrap"""
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .storage import APP_NAME
from .ui.main_window import MainWindow


def res_path(rel):
    """Resolve an asset path both in dev and PyInstaller-frozen modes"""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, rel)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, rel)


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
