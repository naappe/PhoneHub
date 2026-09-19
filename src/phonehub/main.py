from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from phonehub.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PhoneHub")
    app.setOrganizationName("PhoneHub")
    window = MainWindow()
    window.show()
    return app.exec()
