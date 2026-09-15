import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QMessageBox
)
from PySide6.QtCore import Qt


BASE = Path("C:/PhoneHub")
PHONEHUB_EXE = BASE / "dist" / "PhoneHub.exe"
START_PHONEHUB = BASE / "START_PHONEHUB.bat"
START_QR = BASE / "START_QR_COMPANION.bat"
UPLOADS = BASE / "iphone_uploads"
NOTES = BASE / "data" / "iphone_notes.txt"


def open_path(path):
    path = Path(path)
    try:
        if path.exists():
            subprocess.Popen(["explorer", str(path)])
        else:
            QMessageBox.warning(None, "Missing", f"Not found:\n{path}")
    except Exception as e:
        QMessageBox.warning(None, "Error", str(e))


def run_file(path):
    path = Path(path)
    try:
        if not path.exists():
            QMessageBox.warning(None, "Missing", f"Not found:\n{path}")
            return
        subprocess.Popen(
            ["cmd", "/c", "start", "", str(path)],
            cwd=str(BASE),
            shell=False
        )
    except Exception as e:
        QMessageBox.warning(None, "Error", str(e))


class ControlCenter(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhoneHub Control Center")
        self.resize(420, 520)

        title = QLabel("📱 PhoneHub Control Center")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:24px;font-weight:800;margin:12px;")

        sub = QLabel("Choose what you want to open.")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet("color:#64748b;font-size:14px;margin-bottom:12px;")

        btn_main = QPushButton("📲 Open PhoneHub Main App")
        btn_main.clicked.connect(lambda: run_file(PHONEHUB_EXE if PHONEHUB_EXE.exists() else START_PHONEHUB))

        btn_qr = QPushButton("🔳 Start QR Companion")
        btn_qr.clicked.connect(lambda: run_file(START_QR))

        btn_uploads = QPushButton("📁 Open Phone Uploads")
        btn_uploads.clicked.connect(lambda: open_path(UPLOADS))

        btn_notes = QPushButton("📝 Open Phone Notes")
        btn_notes.clicked.connect(self.open_notes)

        btn_folder = QPushButton("🗂 Open PhoneHub Folder")
        btn_folder.clicked.connect(lambda: open_path(BASE))

        btn_close = QPushButton("❌ Close")
        btn_close.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(sub)

        for btn in [btn_main, btn_qr, btn_uploads, btn_notes, btn_folder, btn_close]:
            btn.setMinimumHeight(48)
            btn.setStyleSheet("""
                QPushButton {
                    font-size: 15px;
                    font-weight: 700;
                    border-radius: 12px;
                    padding: 10px;
                    background: #0f172a;
                    color: white;
                }
                QPushButton:hover {
                    background: #1e293b;
                }
            """)
            layout.addWidget(btn)

        self.setLayout(layout)

    def open_notes(self):
        NOTES.parent.mkdir(exist_ok=True)
        if not NOTES.exists():
            NOTES.write_text("", encoding="utf-8")
        subprocess.Popen(["notepad", str(NOTES)])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ControlCenter()
    win.show()
    sys.exit(app.exec())
