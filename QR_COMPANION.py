import socket
import subprocess
import sys
import time
from pathlib import Path

import qrcode
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QMessageBox
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt


BASE_DIR = Path("C:/PhoneHub")
DATA_DIR = BASE_DIR / "data"
QR_FILE = DATA_DIR / "iphone_qr.png"
SERVER_FILE = BASE_DIR / "companion_server.py"
TOKEN_FILE = DATA_DIR / "companion_token.txt"
PYTHON_EXE = r"C:\Users\User\AppData\Local\Python\pythoncore-3.14-64\python.exe"
PORT = 8088


def get_tailscale_ip():
    try:
        out = subprocess.check_output(["tailscale", "ip", "-4"], text=True, timeout=5).strip()
        if out:
            return out.splitlines()[0].strip()
    except Exception:
        pass
    return ""


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def start_server():
    try:
        subprocess.Popen(
            [PYTHON_EXE, str(SERVER_FILE)],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        time.sleep(1)
        return True
    except Exception:
        return False


class QRWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhoneHub QR Companion")
        self.resize(420, 620)

        DATA_DIR.mkdir(exist_ok=True)

        tailscale_ip = get_tailscale_ip()
        local_ip = get_local_ip()

        if TOKEN_FILE.exists():
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        else:
            token = "missing"

        ip = tailscale_ip or local_ip
        self.link = f"http://{ip}:{PORT}/?token={token}&name=Phone"

        img = qrcode.make(self.link)
        img.save(QR_FILE)

        title = QLabel("PhoneHub QR Companion")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:24px;font-weight:700;margin:10px;")

        info = QLabel(
            "Scan this QR from any phone camera.\n"
            "It opens and auto-pairs your PhoneHub Companion.\n\n"
            f"{self.link}"
        )
        info.setAlignment(Qt.AlignCenter)
        info.setWordWrap(True)

        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        qr.setPixmap(QPixmap(str(QR_FILE)).scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        open_folder = QPushButton("Open Upload Folder")
        open_folder.clicked.connect(self.open_upload_folder)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(qr)
        layout.addWidget(info)
        layout.addWidget(open_folder)
        layout.addWidget(close_btn)
        self.setLayout(layout)

    def open_upload_folder(self):
        folder = BASE_DIR / "iphone_uploads"
        folder.mkdir(exist_ok=True)
        subprocess.Popen(["explorer", str(folder)])


if __name__ == "__main__":
    ok = start_server()

    app = QApplication(sys.argv)
    win = QRWindow()
    win.show()

    if ok:
        QMessageBox.information(win, "PhoneHub", "Companion server started. Scan the QR.")
    else:
        QMessageBox.warning(win, "PhoneHub", "Server could not start.")

    sys.exit(app.exec())
