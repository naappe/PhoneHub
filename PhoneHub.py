import sys
import os
import json
import shutil
import subprocess
import threading
import time

from device import get_device

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QGridLayout, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, QObject, Signal


APP_VERSION = "v0.8"

SCRCPY_PROFILE = [
    "--no-audio",
    "--video-codec=h264",
    "--max-size=480",
    "--video-bit-rate=350K",
    "--max-fps=12",
    "--video-buffer=0",
]


def no_window_flag():
    if sys.platform.startswith("win"):
        return subprocess.CREATE_NO_WINDOW
    return 0


def run_background(args):
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=no_window_flag()
        )
        return True
    except Exception:
        return False


def run_quiet(args, timeout=5):
    try:
        return subprocess.check_output(
            args,
            text=True,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=no_window_flag()
        ).strip()
    except Exception:
        return ""


def is_scrcpy_running():
    out = run_quiet(["tasklist"], timeout=5)
    return "scrcpy.exe" in out.lower()


def close_scrcpy():
    if not is_scrcpy_running():
        return True

    run_quiet(["taskkill", "/IM", "scrcpy.exe", "/F"], timeout=5)
    time.sleep(0.5)
    return not is_scrcpy_running()


def adb_shell(target, command):
    adb = shutil.which("adb")
    if not adb or not target:
        return False
    return run_background([adb, "-s", target, "shell"] + command)


def get_phonehub_config():
    config_path = os.path.expanduser(r"~\.phone_remote\config.json")
    if not os.path.exists(config_path):
        return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def fix_adb_connection():
    cfg = get_phonehub_config()

    phone_ip = cfg.get("phone_ip", "")
    adb_port = cfg.get("adb_port", 5555)
    usb_serial = cfg.get("usb_serial", "")

    if not phone_ip:
        return "Config missing phone IP."

    remote = f"{phone_ip}:{adb_port}"

    run_quiet(["adb", "start-server"], timeout=8)

    devices = run_quiet(["adb", "devices"], timeout=5)
    if f"{remote}\tdevice" in devices:
        return "Remote phone already connected."

    run_quiet(["adb", "connect", remote], timeout=8)
    time.sleep(1)

    devices = run_quiet(["adb", "devices"], timeout=5)
    if f"{remote}\tdevice" in devices:
        return "Remote phone connected."

    if usb_serial and f"{usb_serial}\tdevice" in devices:
        run_quiet(["adb", "-s", usb_serial, "tcpip", str(adb_port)], timeout=8)
        time.sleep(2)
        run_quiet(["adb", "connect", remote], timeout=8)
        time.sleep(1)

        devices = run_quiet(["adb", "devices"], timeout=5)
        if f"{remote}\tdevice" in devices:
            return "USB fixed remote connection."

        return "USB found, but remote connect failed."

    return "Phone not found. Connect USB, unlock phone, then press FIX CONNECTION again."


class Bridge(QObject):
    device_ready = Signal(dict)
    fix_ready = Signal(str)


class Card(QFrame):
    def __init__(self, title, value="-"):
        super().__init__()
        self.setObjectName("card")

        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)

        t = QLabel(title)
        t.setObjectName("cardTitle")

        self.v = QLabel(value)
        self.v.setObjectName("cardValue")

        box.addWidget(t)
        box.addWidget(self.v)

    def set_value(self, value):
        self.v.setText(str(value))


class PhoneHub(QWidget):
    def __init__(self):
        super().__init__()

        self.device = {}
        self.loading = False
        self.bridge = Bridge()
        self.bridge.device_ready.connect(self.apply_device)
        self.bridge.fix_ready.connect(self.apply_fix_result)

        self.setWindowTitle(f"PhoneHub {APP_VERSION}")
        self.resize(480, 780)

        self.build_ui()
        self.refresh_async()

    def build_ui(self):
        main = QVBoxLayout(self)
        main.setSpacing(14)
        main.setContentsMargins(20, 20, 20, 20)

        header = QHBoxLayout()

        title = QLabel("📱 PhoneHub")
        title.setObjectName("title")

        self.status = QLabel("Checking...")
        self.status.setObjectName("statusChecking")
        self.status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status)

        main.addLayout(header)

        sub = QLabel("Remote phone dashboard")
        sub.setObjectName("subtitle")
        main.addWidget(sub)

        grid = QGridLayout()
        grid.setSpacing(12)

        self.card_device = Card("Device")
        self.card_android = Card("Android")
        self.card_battery = Card("Battery")
        self.card_ip = Card("IP Address")
        self.card_mode = Card("Mode")
        self.card_target = Card("Target")

        grid.addWidget(self.card_device, 0, 0)
        grid.addWidget(self.card_android, 0, 1)
        grid.addWidget(self.card_battery, 1, 0)
        grid.addWidget(self.card_ip, 1, 1)
        grid.addWidget(self.card_mode, 2, 0)
        grid.addWidget(self.card_target, 2, 1)

        main.addLayout(grid)

        self.open_btn = QPushButton("📱 OPEN PHONE")
        self.open_btn.setObjectName("primaryButton")
        self.open_btn.clicked.connect(self.open_phone)
        main.addWidget(self.open_btn)

        control_row = QGridLayout()
        control_row.setSpacing(10)

        close_btn = QPushButton("❌ Close Phone")
        restart_btn = QPushButton("🔁 Restart Phone Screen")
        refresh_btn = QPushButton("🔄 Refresh")

        close_btn.clicked.connect(self.close_phone)
        restart_btn.clicked.connect(self.restart_phone)
        refresh_btn.clicked.connect(self.refresh_async)

        control_row.addWidget(close_btn, 0, 0)
        control_row.addWidget(restart_btn, 0, 1)
        control_row.addWidget(refresh_btn, 1, 0, 1, 2)

        main.addLayout(control_row)

        actions = QGridLayout()
        actions.setSpacing(10)

        camera = QPushButton("📷 Camera")
        photos = QPushButton("🖼 Photos")
        files = QPushButton("📁 Files")
        location = QPushButton("📍 Location")
        settings = QPushButton("⚙ Settings")

        camera.clicked.connect(self.open_camera)
        photos.clicked.connect(self.open_photos)
        files.clicked.connect(self.open_files)
        location.clicked.connect(self.show_location)
        settings.clicked.connect(self.open_settings)

        actions.addWidget(camera, 0, 0)
        actions.addWidget(photos, 0, 1)
        actions.addWidget(files, 1, 0)
        actions.addWidget(location, 1, 1)
        actions.addWidget(settings, 2, 0, 1, 2)

        main.addLayout(actions)
        main.addStretch()

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        main.addWidget(self.footer)

        self.setStyleSheet("""
            QWidget {
                background: #111827;
                color: #F9FAFB;
                font-family: Segoe UI;
                font-size: 14px;
            }

            QLabel#title {
                font-size: 30px;
                font-weight: 800;
            }

            QLabel#subtitle {
                color: #9CA3AF;
                font-size: 13px;
                padding-bottom: 8px;
            }

            QLabel#statusChecking {
                background: #374151;
                color: #FBBF24;
                padding: 8px 12px;
                border-radius: 12px;
                font-weight: 700;
            }

            QLabel#statusConnected {
                background: #064E3B;
                color: #34D399;
                padding: 8px 12px;
                border-radius: 12px;
                font-weight: 700;
            }

            QLabel#statusOffline {
                background: #7F1D1D;
                color: #FCA5A5;
                padding: 8px 12px;
                border-radius: 12px;
                font-weight: 700;
            }

            QFrame#card {
                background: #1F2937;
                border: 1px solid #374151;
                border-radius: 16px;
            }

            QLabel#cardTitle {
                color: #9CA3AF;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#cardValue {
                color: #FFFFFF;
                font-size: 17px;
                font-weight: 800;
            }

            QPushButton {
                background: #1F2937;
                color: #F9FAFB;
                border: 1px solid #374151;
                border-radius: 14px;
                padding: 14px;
                font-size: 15px;
                font-weight: 700;
            }

            QPushButton:hover {
                background: #374151;
            }

            QPushButton#primaryButton {
                background: #2563EB;
                border: none;
                font-size: 18px;
                padding: 18px;
            }

            QPushButton#primaryButton:hover {
                background: #3B82F6;
            }

            QPushButton#fixButton {
                background: #F59E0B;
                color: #111827;
                border: none;
                font-size: 17px;
                padding: 16px;
            }

            QPushButton#fixButton:hover {
                background: #FBBF24;
            }

            QLabel#footer {
                color: #9CA3AF;
                font-size: 12px;
                padding-top: 8px;
            }
        """)

    def set_status_style(self, name):
        self.status.setObjectName(name)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def refresh_async(self):
        if self.loading:
            return

        self.loading = True
        self.footer.setText("Refreshing in background...")
        self.status.setText("Checking...")
        self.set_status_style("statusChecking")

        t = threading.Thread(target=self.refresh_worker, daemon=True)
        t.start()

    def refresh_worker(self):
        d = get_device()
        self.bridge.device_ready.emit(d)

    def apply_device(self, d):
        self.device = d
        self.loading = False

        connected = d.get("connected", False)

        self.card_device.set_value(d.get("device", "Unknown"))
        self.card_android.set_value(d.get("android", "-"))
        self.card_battery.set_value(str(d.get("battery", "-")) + "%")
        self.card_ip.set_value(d.get("ip", "-"))
        self.card_mode.set_value(d.get("mode", "-"))
        self.card_target.set_value(d.get("target", "-"))

        if connected:
            self.status.setText("🟢 Connected")
            self.set_status_style("statusConnected")
            self.footer.setText("Ready")
        else:
            self.status.setText("🔴 Offline")
            self.set_status_style("statusOffline")
            self.footer.setText("Phone offline. Connect USB or enable remote ADB.")

    def require_target(self):
        target = self.device.get("target", "")
        if not target:
            QMessageBox.warning(self, "PhoneHub", "Phone not connected. Press Refresh after connecting.")
            return ""
        return target

    def fix_connection_async(self):
        if self.loading:
            return

        self.loading = True
        self.footer.setText("Fixing connection...")
        self.status.setText("Fixing...")
        self.set_status_style("statusChecking")

        t = threading.Thread(target=self.fix_connection_worker, daemon=True)
        t.start()

    def fix_connection_worker(self):
        message = fix_adb_connection()
        d = get_device()
        self.bridge.device_ready.emit(d)
        self.bridge.fix_ready.emit(message)

    def apply_fix_result(self, message):
        self.loading = False
        self.footer.setText(message)

    def open_phone(self):
        target = self.require_target()
        if not target:
            return

        scrcpy = shutil.which("scrcpy")
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        if is_scrcpy_running():
            self.footer.setText("Phone screen already open.")
            QMessageBox.information(self, "PhoneHub", "Phone screen is already open.\n\nUse Restart Phone Screen to reopen it.")
            return

        ok = run_background([scrcpy, "-s", target] + SCRCPY_PROFILE)
        if ok:
            self.footer.setText("Opening phone screen...")
        else:
            QMessageBox.critical(self, "PhoneHub", "Could not open phone.")

    def close_phone(self):
        self.footer.setText("Closing phone screen...")
        ok = close_scrcpy()

        if ok:
            self.footer.setText("Phone screen closed.")
        else:
            QMessageBox.warning(self, "PhoneHub", "Could not close phone screen.")

    def restart_phone(self):
        target = self.require_target()
        if not target:
            return

        scrcpy = shutil.which("scrcpy")
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        self.footer.setText("Restarting phone screen...")
        QApplication.processEvents()

        close_scrcpy()
        ok = run_background([scrcpy, "-s", target] + SCRCPY_PROFILE)

        if ok:
            self.footer.setText("Phone screen restarted.")
        else:
            QMessageBox.critical(self, "PhoneHub", "Could not restart phone screen.")

    def open_camera(self):
        target = self.require_target()
        if not target:
            return

        scrcpy = shutil.which("scrcpy")
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        # Camera-only mode:
        # PC shows the phone camera feed.
        # The physical phone screen does not need to open the Camera app.
        run_background([
            scrcpy,
            "-s", target,
            "--video-source=camera",
            "--camera-facing=back",
            "--camera-size=640x480",
            "--camera-fps=15",
            "--no-audio",
            "--window-title=PhoneHub Camera"
        ])

        self.footer.setText("Opening camera feed on PC...")

    def open_photos(self):
        target = self.require_target()
        if not target:
            return

        adb_shell(target, ["am", "start", "-a", "android.intent.action.VIEW", "-t", "image/*"])
        self.footer.setText("Opening photos and phone screen...")
        self.restart_phone()

    def open_files(self):
        target = self.require_target()
        if not target:
            return

        adb_shell(target, ["monkey", "-p", "com.google.android.documentsui", "1"])
        self.footer.setText("Opening files and phone screen...")
        self.restart_phone()

    def open_settings(self):
        target = self.require_target()
        if not target:
            return

        adb_shell(target, ["am", "start", "-a", "android.settings.SETTINGS"])
        self.footer.setText("Opening settings and phone screen...")
        self.restart_phone()

    def show_location(self):
        QMessageBox.information(
            self,
            "PhoneHub Location",
            "Location will be added after Camera, Photos, and Files.\n\nFor reliable GPS, we will need a small Android helper app."
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PhoneHub()
    win.show()
    sys.exit(app.exec())
