import sys
import os
import json
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from device import get_device

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton,
    QVBoxLayout, QHBoxLayout, QMessageBox,
    QComboBox, QInputDialog
)
from PySide6.QtCore import Qt, QObject, Signal


APP_VERSION = "v1.3-multi-phone"

CONFIG_DIR = Path.home() / ".phone_remote"
CONFIG_FILE = CONFIG_DIR / "config.json"
PHONES_FILE = CONFIG_DIR / "phones.json"

SCREEN_PROFILE = [
    "--no-audio",
    "--video-codec=h264",
    "--max-size=480",
    "--video-bit-rate=350K",
    "--max-fps=12",
    "--video-buffer=0",
    "--window-title=PhoneHub Screen"
]

CAMERA_BASE = [
    "--video-source=camera",
    "--camera-size=640x480",
    "--camera-fps=12",
    "--video-bit-rate=350K",
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


def run_bytes(args, timeout=12):
    try:
        return subprocess.check_output(
            args,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=no_window_flag()
        )
    except Exception:
        return b""


def read_json(path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return default


def write_json(path, data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_config():
    return read_json(CONFIG_FILE, {})


def save_active_config(phone):
    cfg = {
        "phone_ip": phone.get("phone_ip", ""),
        "adb_port": int(phone.get("adb_port", 5555)),
        "device_name": phone.get("device_name", "Phone"),
        "usb_serial": phone.get("usb_serial", "")
    }
    write_json(CONFIG_FILE, cfg)


def load_phones():
    data = read_json(PHONES_FILE, None)

    if isinstance(data, dict) and isinstance(data.get("phones"), list):
        return data

    old = get_config()

    if old.get("phone_ip"):
        first = {
            "id": old.get("usb_serial") or old.get("phone_ip"),
            "label": old.get("device_name", "My Phone"),
            "device_name": old.get("device_name", "My Phone"),
            "phone_ip": old.get("phone_ip", ""),
            "adb_port": int(old.get("adb_port", 5555)),
            "usb_serial": old.get("usb_serial", "")
        }

        data = {
            "active_id": first["id"],
            "phones": [first]
        }

        write_json(PHONES_FILE, data)
        return data

    data = {
        "active_id": "",
        "phones": []
    }
    write_json(PHONES_FILE, data)
    return data


def save_phones(data):
    write_json(PHONES_FILE, data)


def get_active_phone():
    data = load_phones()
    active_id = data.get("active_id", "")

    for phone in data.get("phones", []):
        if phone.get("id") == active_id:
            return phone

    phones = data.get("phones", [])
    if phones:
        data["active_id"] = phones[0].get("id", "")
        save_phones(data)
        save_active_config(phones[0])
        return phones[0]

    return {}


def set_active_phone(phone_id):
    data = load_phones()

    for phone in data.get("phones", []):
        if phone.get("id") == phone_id:
            data["active_id"] = phone_id
            save_phones(data)
            save_active_config(phone)
            return phone

    return {}


def is_scrcpy_running():
    out = run_quiet(["tasklist"], timeout=5)
    return "scrcpy.exe" in out.lower()


def close_scrcpy():
    if not is_scrcpy_running():
        return True

    run_quiet(["taskkill", "/IM", "scrcpy.exe", "/F"], timeout=5)
    time.sleep(0.5)
    return not is_scrcpy_running()


def fix_adb_connection():
    phone = get_active_phone()

    phone_ip = phone.get("phone_ip", "")
    adb_port = phone.get("adb_port", 5555)
    usb_serial = phone.get("usb_serial", "")

    run_quiet(["adb", "start-server"], timeout=8)
    devices = run_quiet(["adb", "devices"], timeout=5)

    if usb_serial and f"{usb_serial}\tdevice" in devices:
        return "Connected by USB. Remote mode not required."

    if not phone_ip:
        return "USB phone saved, but not connected. Connect USB and unlock phone."

    remote = f"{phone_ip}:{adb_port}"

    run_quiet(["adb", "start-server"], timeout=8)

    devices = run_quiet(["adb", "devices"], timeout=5)

    if f"{remote}\tdevice" in devices:
        return "Connected. Remote phone ready."

    run_quiet(["adb", "connect", remote], timeout=8)
    time.sleep(1)

    devices = run_quiet(["adb", "devices"], timeout=5)

    if f"{remote}\tdevice" in devices:
        return "Connected. Remote phone ready."

    if usb_serial and f"{usb_serial}\tdevice" in devices:
        run_quiet(["adb", "-s", usb_serial, "tcpip", str(adb_port)], timeout=8)
        time.sleep(2)
        run_quiet(["adb", "connect", remote], timeout=8)
        time.sleep(1)

        devices = run_quiet(["adb", "devices"], timeout=5)

        if f"{remote}\tdevice" in devices:
            return "Fixed. USB enabled remote mode."

        return "USB found. Keep phone unlocked and try again."

    return "Phone not found. Connect USB, unlock phone, press FIX."


def detect_usb_phone():
    run_quiet(["adb", "start-server"], timeout=8)
    devices = run_quiet(["adb", "devices"], timeout=5)

    serials = []

    for line in devices.splitlines():
        if "\tdevice" in line:
            serial = line.split()[0]
            if ":" not in serial and not serial.startswith("emulator"):
                serials.append(serial)

    if not serials:
        return None

    serial = serials[0]
    model = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=5)
    android = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"], timeout=5)

    return {
        "serial": serial,
        "model": model or "Android Phone",
        "android": android or "-"
    }


def save_screenshot(target):
    adb = shutil.which("adb")

    if not adb or not target:
        return "Screenshot failed. Phone not connected."

    folder = Path(r"C:\PhoneHub\screenshots")
    folder.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = folder / f"phonehub_{stamp}.png"

    data = run_bytes([adb, "-s", target, "exec-out", "screencap", "-p"], timeout=15)

    if not data or len(data) < 1000:
        return "Screenshot failed. Unlock phone once."

    file_path.write_bytes(data)
    return f"Screenshot saved: {file_path}"


class Bridge(QObject):
    device_ready = Signal(dict)
    message_ready = Signal(str)
    phones_ready = Signal()


class PhoneHub(QWidget):
    def __init__(self):
        super().__init__()

        self.device = {}
        self.loading = False
        self.last_mode = "screen"

        self.bridge = Bridge()
        self.bridge.device_ready.connect(self.apply_device)
        self.bridge.message_ready.connect(self.show_message)
        self.bridge.phones_ready.connect(self.reload_phone_dropdown)

        self.setWindowTitle(f"PhoneHub {APP_VERSION}")
        self.resize(430, 700)

        self.build_ui()
        self.reload_phone_dropdown()
        self.refresh_async()

    def build_ui(self):
        main = QVBoxLayout(self)
        main.setContentsMargins(18, 18, 18, 18)
        main.setSpacing(10)

        top = QHBoxLayout()

        self.title = QLabel("📱 PhoneHub")
        self.title.setObjectName("title")

        self.status = QLabel("Checking")
        self.status.setObjectName("statusChecking")
        self.status.setAlignment(Qt.AlignCenter)

        top.addWidget(self.title)
        top.addStretch()
        top.addWidget(self.status)

        main.addLayout(top)

        self.phone_select = QComboBox()
        self.phone_select.setObjectName("select")
        main.addWidget(self.phone_select)

        phone_row = QHBoxLayout()

        self.add_btn = QPushButton("➕ Add Phone")
        self.connect_btn = QPushButton("🔌 Connect")
        self.delete_btn = QPushButton("🗑 Delete")

        self.add_btn.clicked.connect(self.add_phone)
        self.connect_btn.clicked.connect(self.connect_selected_phone)
        self.delete_btn.clicked.connect(self.delete_selected_phone)

        phone_row.addWidget(self.add_btn)
        phone_row.addWidget(self.connect_btn)
        phone_row.addWidget(self.delete_btn)

        main.addLayout(phone_row)

        self.info = QLabel("Loading phone info...")
        self.info.setObjectName("info")
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        main.addWidget(self.info)

        self.note = QLabel("Unlock phone once. PhoneHub will keep it awake while viewing.")
        self.note.setObjectName("note")
        main.addWidget(self.note)

        self.fix_btn = QPushButton("🛠 FIX CONNECTION")
        self.fix_btn.setObjectName("fix")
        self.fix_btn.clicked.connect(self.fix_async)
        main.addWidget(self.fix_btn)

        self.open_btn = QPushButton("📱 OPEN PHONE")
        self.open_btn.setObjectName("primary")
        self.open_btn.clicked.connect(self.open_phone)
        main.addWidget(self.open_btn)

        row1 = QHBoxLayout()

        self.back_btn = QPushButton("📷 Back Camera")
        self.front_btn = QPushButton("🤳 Front Camera")

        self.back_btn.clicked.connect(lambda: self.open_camera("back"))
        self.front_btn.clicked.connect(lambda: self.open_camera("front"))

        row1.addWidget(self.back_btn)
        row1.addWidget(self.front_btn)

        main.addLayout(row1)

        row2 = QHBoxLayout()

        self.shot_btn = QPushButton("📸 Screenshot")
        self.close_btn = QPushButton("❌ Close")

        self.shot_btn.clicked.connect(self.screenshot_async)
        self.close_btn.clicked.connect(self.close_view)

        row2.addWidget(self.shot_btn)
        row2.addWidget(self.close_btn)

        main.addLayout(row2)

        row3 = QHBoxLayout()

        self.restart_btn = QPushButton("🔁 Restart")
        self.refresh_btn = QPushButton("🔄 Refresh")

        self.restart_btn.clicked.connect(self.restart_view)
        self.refresh_btn.clicked.connect(self.refresh_async)

        row3.addWidget(self.restart_btn)
        row3.addWidget(self.refresh_btn)

        main.addLayout(row3)

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        main.addStretch()
        main.addWidget(self.footer)

        self.setStyleSheet("""
            QWidget {
                background: #0B1220;
                color: #F8FAFC;
                font-family: Segoe UI;
                font-size: 14px;
            }

            QLabel#title {
                font-size: 28px;
                font-weight: 800;
            }

            QComboBox#select {
                background: #111827;
                color: #F8FAFC;
                border: 1px solid #263244;
                border-radius: 12px;
                padding: 10px;
                font-size: 14px;
                font-weight: 700;
            }

            QLabel#statusChecking {
                background: #334155;
                color: #FBBF24;
                border-radius: 12px;
                padding: 8px 12px;
                font-weight: 800;
                min-width: 90px;
            }

            QLabel#statusConnected {
                background: #065F46;
                color: #A7F3D0;
                border-radius: 12px;
                padding: 8px 12px;
                font-weight: 800;
                min-width: 90px;
            }

            QLabel#statusOffline {
                background: #7F1D1D;
                color: #FCA5A5;
                border-radius: 12px;
                padding: 8px 12px;
                font-weight: 800;
                min-width: 90px;
            }

            QLabel#statusBatteryLow {
                background: #78350F;
                color: #FDE68A;
                border-radius: 12px;
                padding: 8px 12px;
                font-weight: 800;
                min-width: 90px;
            }

            QLabel#info {
                background: #111827;
                border: 1px solid #263244;
                border-radius: 14px;
                padding: 14px;
                font-size: 15px;
                line-height: 1.4;
            }

            QLabel#note {
                color: #CBD5E1;
                background: #172033;
                border: 1px solid #263244;
                border-radius: 12px;
                padding: 10px;
                font-size: 12px;
            }

            QPushButton {
                background: #162033;
                color: #F8FAFC;
                border: 1px solid #263244;
                border-radius: 13px;
                padding: 12px;
                font-size: 14px;
                font-weight: 700;
            }

            QPushButton:hover {
                background: #22304A;
            }

            QPushButton#primary {
                background: #2563EB;
                border: none;
                padding: 17px;
                font-size: 17px;
            }

            QPushButton#fix {
                background: #F59E0B;
                color: #111827;
                border: none;
                padding: 15px;
                font-size: 16px;
            }

            QLabel#footer {
                color: #94A3B8;
                font-size: 12px;
            }
        """)

    def reload_phone_dropdown(self):
        self.phone_select.blockSignals(True)
        self.phone_select.clear()

        data = load_phones()
        active_id = data.get("active_id", "")

        for phone in data.get("phones", []):
            label = phone.get("label") or phone.get("device_name") or "Phone"
            ip = phone.get("phone_ip", "")
            item_text = f"{label}  ({ip})"
            self.phone_select.addItem(item_text, phone.get("id", ""))

            if phone.get("id") == active_id:
                self.phone_select.setCurrentIndex(self.phone_select.count() - 1)

        if self.phone_select.count() == 0:
            self.phone_select.addItem("No phone saved. Press Add Phone.", "")

        self.phone_select.blockSignals(False)

    def set_status_style(self, style):
        self.status.setObjectName(style)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def refresh_async(self):
        if self.loading:
            return

        self.loading = True
        self.footer.setText("Refreshing...")
        self.status.setText("Checking")
        self.set_status_style("statusChecking")

        threading.Thread(target=self.refresh_worker, daemon=True).start()

    def refresh_worker(self):
        d = get_device()
        self.bridge.device_ready.emit(d)

    def apply_device(self, d):
        self.device = d
        self.loading = False

        connected = d.get("connected", False)
        battery_text = str(d.get("battery", "-"))

        try:
            battery_num = int(battery_text)
        except Exception:
            battery_num = -1

        if connected and battery_num >= 0 and battery_num < 20:
            self.status.setText("Low Batt")
            self.set_status_style("statusBatteryLow")
            self.footer.setText("Battery low. Charge phone soon.")
        elif connected:
            self.status.setText("Connected")
            self.set_status_style("statusConnected")
            self.footer.setText("Ready")
        else:
            self.status.setText("Offline")
            self.set_status_style("statusOffline")
            self.footer.setText("Use FIX CONNECTION")

        self.info.setText(
            f"Device:  {d.get('device', 'Unknown')}\n"
            f"Android: {d.get('android', '-')}\n"
            f"Battery: {d.get('battery', '-')}%\n"
            f"Mode:    {d.get('mode', '-')}\n"
            f"Target:  {d.get('target', '-')}\n"
            f"IP:      {d.get('ip', '-')}"
        )

    def show_message(self, msg):
        self.loading = False
        self.footer.setText(msg)

    def add_phone(self):
        found = detect_usb_phone()

        if not found:
            QMessageBox.warning(
                self,
                "Add Android Phone",
                "No USB Android phone found.\n\n"
                "To add phone:\n"
                "1. Connect USB cable\n"
                "2. Unlock phone\n"
                "3. Enable USB debugging\n"
                "4. Tap Always allow / OK\n"
                "5. Try Add Phone again"
            )
            return

        serial = found["serial"]
        model = found["model"]
        android = found["android"]

        package_check = run_quiet(
            ["adb", "-s", serial, "shell", "pm", "list", "packages", "com.tailscale.ipn"],
            timeout=5
        )

        tailscale_installed = "com.tailscale.ipn" in package_check

        data = load_phones()
        phone_id = serial
        label = f"{model}"

        def save_usb_phone(ip=""):
            phone = {
                "id": phone_id,
                "label": label,
                "device_name": model,
                "phone_ip": ip,
                "adb_port": 5555,
                "usb_serial": serial,
                "android": android
            }

            phones = [p for p in data.get("phones", []) if p.get("id") != phone_id]
            phones.append(phone)

            data["phones"] = phones
            data["active_id"] = phone_id

            save_phones(data)
            save_active_config(phone)

            self.reload_phone_dropdown()
            self.footer.setText(f"Added phone: {label}")
            self.refresh_async()

        if tailscale_installed:
            msg = QMessageBox(self)
            msg.setWindowTitle("Add Android Phone")
            msg.setIcon(QMessageBox.Question)
            msg.setText(
                f"Detected Android phone:\n\n"
                f"Device: {model}\n"
                f"Android: {android}\n"
                f"USB Serial: {serial}\n\n"
                f"USB Mode: READY\n"
                f"Tailscale: INSTALLED\n\n"
                f"Choose setup mode:"
            )

            remote_btn = msg.addButton("Use USB + Remote", QMessageBox.AcceptRole)
            usb_btn = msg.addButton("Use USB Mode Only", QMessageBox.YesRole)
            cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)

            msg.exec()
            clicked = msg.clickedButton()

            if clicked == cancel_btn:
                return

            if clicked == remote_btn:
                ip, ok = QInputDialog.getText(
                    self,
                    "Remote Mode",
                    "Paste this phone's Tailscale IP:"
                )
                if ok and ip.strip():
                    save_usb_phone(ip.strip())
                    self.fix_async()
                else:
                    save_usb_phone("")
                return

            if clicked == usb_btn:
                save_usb_phone("")
                return

        else:
            msg = QMessageBox(self)
            msg.setWindowTitle("Add Android Phone")
            msg.setIcon(QMessageBox.Question)
            msg.setText(
                f"Detected Android phone:\n\n"
                f"Device: {model}\n"
                f"Android: {android}\n"
                f"USB Serial: {serial}\n\n"
                f"USB Mode: READY\n"
                f"PhoneHub can open/control this phone by USB.\n\n"
                f"Tailscale: NOT INSTALLED\n"
                f"Remote Mode is not ready.\n\n"
                f"What do you want to do?"
            )

            install_btn = msg.addButton("Install Tailscale", QMessageBox.AcceptRole)
            usb_btn = msg.addButton("Use USB Mode Only", QMessageBox.YesRole)
            cancel_btn = msg.addButton("Cancel", QMessageBox.RejectRole)

            msg.exec()
            clicked = msg.clickedButton()

            if clicked == cancel_btn:
                return

            if clicked == usb_btn:
                save_usb_phone("")
                return

            if clicked == install_btn:
                save_usb_phone("")
                script = r"C:\PhoneHub\ANDROID_STATUS_CHECK.bat"
                if os.path.exists(script):
                    subprocess.Popen(["cmd", "/c", "start", "", script], cwd=r"C:\PhoneHub")
                    self.footer.setText("Opened Tailscale installer. Follow instructions.")
                else:
                    QMessageBox.warning(
                        self,
                        "Tailscale Installer",
                        "ANDROID_STATUS_CHECK.bat not found.\n\nUse USB mode now, or run setup manually."
                    )
                return

    def connect_selected_phone(self):
        phone_id = self.phone_select.currentData()

        if not phone_id:
            QMessageBox.warning(self, "Connect Phone", "No phone selected.")
            return

        phone = set_active_phone(phone_id)

        if not phone:
            QMessageBox.warning(self, "Connect Phone", "Selected phone not found.")
            return

        close_scrcpy()
        self.footer.setText(f"Selected: {phone.get('label', 'Phone')}")
        self.fix_async()

    def delete_selected_phone(self):
        phone_id = self.phone_select.currentData()

        if not phone_id:
            return

        data = load_phones()
        phones = data.get("phones", [])

        phone = None
        for p in phones:
            if p.get("id") == phone_id:
                phone = p
                break

        if not phone:
            return

        answer = QMessageBox.question(
            self,
            "Delete Phone",
            f"Delete saved phone?\n\n{phone.get('label', 'Phone')}"
        )

        if answer != QMessageBox.Yes:
            return

        phones = [p for p in phones if p.get("id") != phone_id]
        data["phones"] = phones

        if phones:
            data["active_id"] = phones[0].get("id", "")
            save_active_config(phones[0])
        else:
            data["active_id"] = ""
            write_json(CONFIG_FILE, {})

        save_phones(data)
        self.reload_phone_dropdown()
        self.refresh_async()

    def fix_async(self):
        if self.loading:
            return

        self.loading = True
        self.footer.setText("Fixing connection...")
        self.status.setText("Fixing")
        self.set_status_style("statusChecking")

        threading.Thread(target=self.fix_worker, daemon=True).start()

    def fix_worker(self):
        msg = fix_adb_connection()
        d = get_device()
        self.bridge.device_ready.emit(d)
        self.bridge.message_ready.emit(msg)

    def target(self):
        target = self.device.get("target", "")

        if not target:
            QMessageBox.warning(self, "PhoneHub", "Phone not connected. Press FIX CONNECTION.")
            return ""

        return target

    def open_scrcpy(self, args, mode):
        target = self.target()

        if not target:
            return

        scrcpy = shutil.which("scrcpy")

        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        run_quiet(["adb", "-s", target, "shell", "input", "keyevent", "224"], timeout=3)

        close_scrcpy()

        ok = run_background([scrcpy, "-s", target] + args)

        if ok:
            self.last_mode = mode
            self.footer.setText(f"Opening {mode}...")
        else:
            self.footer.setText(f"Could not open {mode}.")

    def open_phone(self):
        self.open_scrcpy(SCREEN_PROFILE, "screen")

    def open_camera(self, facing):
        args = CAMERA_BASE + [
            f"--camera-facing={facing}",
            f"--window-title=PhoneHub {facing.title()} Camera"
        ]
        self.open_scrcpy(args, f"{facing} camera")

    def close_view(self):
        close_scrcpy()
        self.footer.setText("Closed.")

    def restart_view(self):
        if self.last_mode == "front camera":
            self.open_camera("front")
        elif self.last_mode == "back camera":
            self.open_camera("back")
        else:
            self.open_phone()

    def screenshot_async(self):
        target = self.target()

        if not target:
            return

        self.footer.setText("Taking screenshot...")
        threading.Thread(target=self.screenshot_worker, args=(target,), daemon=True).start()

    def screenshot_worker(self, target):
        msg = save_screenshot(target)
        self.bridge.message_ready.emit(msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PhoneHub()
    win.show()
    sys.exit(app.exec())




