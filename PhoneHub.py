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


APP_VERSION = "v0.9"

SCREEN_PROFILE = [
    "--no-audio",
    "--video-codec=h264",
    "--max-size=540",
    "--video-bit-rate=700K",
    "--max-fps=20",
    "--video-buffer=0",
    "--window-title=PhoneHub Screen"
]

CAMERA_BASE = [
    "--video-source=camera",
    "--camera-size=1280x720",
    "--camera-fps=20",
    "--no-audio"
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


def run_quiet(args, timeout=6):
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
    time.sleep(0.6)
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
        box.setSpacing(4)

        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")

        self.value = QLabel(value)
        self.value.setObjectName("cardValue")

        box.addWidget(self.title)
        box.addWidget(self.value)

    def set_value(self, value):
        self.value.setText(str(value))


class SectionTitle(QLabel):
    def __init__(self, text):
        super().__init__(text)
        self.setObjectName("sectionTitle")


class PhoneHub(QWidget):
    def __init__(self):
        super().__init__()

        self.device = {}
        self.loading = False
        self.last_view = "screen"

        self.bridge = Bridge()
        self.bridge.device_ready.connect(self.apply_device)
        self.bridge.fix_ready.connect(self.apply_fix_result)

        self.setWindowTitle(f"PhoneHub {APP_VERSION}")
        self.resize(560, 860)

        self.build_ui()
        self.refresh_async()

    def build_ui(self):
        main = QVBoxLayout(self)
        main.setSpacing(14)
        main.setContentsMargins(18, 18, 18, 18)

        header = QHBoxLayout()

        title = QLabel("📱 PhoneHub")
        title.setObjectName("title")

        self.status = QLabel("Checking...")
        self.status.setObjectName("statusChecking")
        self.status.setAlignment(Qt.AlignCenter)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.status)

        main.addLayout(header)

        subtitle = QLabel("Remote phone dashboard")
        subtitle.setObjectName("subtitle")
        main.addWidget(subtitle)

        main.addWidget(SectionTitle("Device Information"))

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

        top_actions = QGridLayout()
        top_actions.setSpacing(10)

        self.fix_btn = QPushButton("🛠 FIX CONNECTION")
        self.fix_btn.setObjectName("fixButton")
        self.fix_btn.clicked.connect(self.fix_connection_async)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.refresh_async)

        top_actions.addWidget(self.fix_btn, 0, 0)
        top_actions.addWidget(self.refresh_btn, 0, 1)

        main.addLayout(top_actions)

        main.addWidget(SectionTitle("Screen & Camera"))

        self.open_btn = QPushButton("📱 OPEN PHONE")
        self.open_btn.setObjectName("primaryButton")
        self.open_btn.clicked.connect(self.open_phone_view)
        main.addWidget(self.open_btn)

        camera_row = QGridLayout()
        camera_row.setSpacing(10)

        self.back_cam_btn = QPushButton("📷 Back Camera")
        self.front_cam_btn = QPushButton("🤳 Front Camera")

        self.back_cam_btn.clicked.connect(lambda: self.open_camera_view("back"))
        self.front_cam_btn.clicked.connect(lambda: self.open_camera_view("front"))

        camera_row.addWidget(self.back_cam_btn, 0, 0)
        camera_row.addWidget(self.front_cam_btn, 0, 1)

        main.addLayout(camera_row)

        control_row = QGridLayout()
        control_row.setSpacing(10)

        self.close_btn = QPushButton("❌ Close View")
        self.restart_btn = QPushButton("🔁 Restart View")

        self.close_btn.clicked.connect(self.close_view)
        self.restart_btn.clicked.connect(self.restart_view)

        control_row.addWidget(self.close_btn, 0, 0)
        control_row.addWidget(self.restart_btn, 0, 1)

        main.addLayout(control_row)

        main.addWidget(SectionTitle("Quick Shortcuts"))

        quick = QGridLayout()
        quick.setSpacing(10)

        photos = QPushButton("🖼 Photos")
        files = QPushButton("📁 Files")
        settings = QPushButton("⚙ Settings")
        location = QPushButton("📍 Location")

        photos.clicked.connect(self.open_photos)
        files.clicked.connect(self.open_files)
        settings.clicked.connect(self.open_settings)
        location.clicked.connect(self.show_location)

        quick.addWidget(photos, 0, 0)
        quick.addWidget(files, 0, 1)
        quick.addWidget(settings, 1, 0)
        quick.addWidget(location, 1, 1)

        main.addLayout(quick)
        main.addStretch()

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        main.addWidget(self.footer)

        self.setStyleSheet("""
            QWidget {
                background: #0B1220;
                color: #F8FAFC;
                font-family: Segoe UI;
                font-size: 14px;
            }

            QLabel#title {
                font-size: 34px;
                font-weight: 800;
                color: #FFFFFF;
            }

            QLabel#subtitle {
                color: #94A3B8;
                font-size: 13px;
                margin-bottom: 4px;
            }

            QLabel#sectionTitle {
                color: #CBD5E1;
                font-size: 14px;
                font-weight: 700;
                padding-top: 2px;
                padding-bottom: 2px;
            }

            QLabel#statusChecking {
                background: #334155;
                color: #FBBF24;
                padding: 10px 14px;
                border-radius: 14px;
                font-weight: 800;
                min-width: 130px;
            }

            QLabel#statusConnected {
                background: #064E3B;
                color: #6EE7B7;
                padding: 10px 14px;
                border-radius: 14px;
                font-weight: 800;
                min-width: 130px;
            }

            QLabel#statusOffline {
                background: #7F1D1D;
                color: #FCA5A5;
                padding: 10px 14px;
                border-radius: 14px;
                font-weight: 800;
                min-width: 130px;
            }

            QFrame#card {
                background: #162033;
                border: 1px solid #283548;
                border-radius: 16px;
            }

            QLabel#cardTitle {
                color: #94A3B8;
                font-size: 12px;
                font-weight: 600;
            }

            QLabel#cardValue {
                color: #FFFFFF;
                font-size: 18px;
                font-weight: 800;
            }

            QPushButton {
                background: #162033;
                color: #F8FAFC;
                border: 1px solid #283548;
                border-radius: 14px;
                padding: 14px;
                font-size: 15px;
                font-weight: 700;
            }

            QPushButton:hover {
                background: #22304A;
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
                font-size: 16px;
                padding: 16px;
            }

            QPushButton#fixButton:hover {
                background: #FBBF24;
            }

            QLabel#footer {
                color: #94A3B8;
                font-size: 12px;
                padding-top: 4px;
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

        threading.Thread(target=self.refresh_worker, daemon=True).start()

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
            self.footer.setText("Phone offline. Use FIX CONNECTION.")

    def require_target(self):
        target = self.device.get("target", "")
        if not target:
            QMessageBox.warning(self, "PhoneHub", "Phone not connected. Press FIX CONNECTION or Refresh.")
            return ""
        return target

    def fix_connection_async(self):
        if self.loading:
            return

        self.loading = True
        self.footer.setText("Fixing connection...")
        self.status.setText("Fixing...")
        self.set_status_style("statusChecking")

        threading.Thread(target=self.fix_connection_worker, daemon=True).start()

    def fix_connection_worker(self):
        message = fix_adb_connection()
        d = get_device()
        self.bridge.device_ready.emit(d)
        self.bridge.fix_ready.emit(message)

    def apply_fix_result(self, message):
        self.loading = False
        self.footer.setText(message)

    def open_scrcpy_view(self, extra_args, view_name):
        target = self.require_target()
        if not target:
            return

        scrcpy = shutil.which("scrcpy")
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        close_scrcpy()
        ok = run_background([scrcpy, "-s", target] + extra_args)

        if ok:
            self.last_view = view_name
            self.footer.setText(f"Opening {view_name}...")
        else:
            QMessageBox.critical(self, "PhoneHub", f"Could not open {view_name}.")

    def open_phone_view(self):
        self.open_scrcpy_view(SCREEN_PROFILE, "phone screen")

    def open_camera_view(self, facing):
        args = CAMERA_BASE + [
            f"--camera-facing={facing}",
            f"--window-title=PhoneHub {facing.title()} Camera"
        ]
        self.open_scrcpy_view(args, f"{facing} camera")

    def close_view(self):
        self.footer.setText("Closing view...")
        ok = close_scrcpy()
        if ok:
            self.footer.setText("View closed.")
        else:
            QMessageBox.warning(self, "PhoneHub", "Could not close view.")

    def restart_view(self):
        if self.last_view == "front camera":
            self.open_camera_view("front")
        elif self.last_view == "back camera":
            self.open_camera_view("back")
        else:
            self.open_phone_view()

    def open_photos(self):
        target = self.require_target()
        if not target:
            return

        adb_shell(target, ["am", "start", "-a", "android.intent.action.VIEW", "-t", "image/*"])
        time.sleep(0.7)
        self.open_phone_view()

    def open_files(self):
        target = self.require_target()
        if not target:
            return

        adb_shell(target, ["monkey", "-p", "com.google.android.documentsui", "1"])
        time.sleep(0.7)
        self.open_phone_view()

    def open_settings(self):
        target = self.require_target()
        if not target:
            return

        adb_shell(target, ["am", "start", "-a", "android.settings.SETTINGS"])
        time.sleep(0.7)
        self.open_phone_view()

    def show_location(self):
        QMessageBox.information(
            self,
            "PhoneHub Location",
            "Location can be added next.\n\nWe will build it as a separate feature."
        )


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PhoneHub()
    win.show()
    sys.exit(app.exec())
