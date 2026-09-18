import os
import sys
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFrame, QMessageBox, QStackedWidget, QTextEdit, QLineEdit
)

from phone_config import normalize_tailscale_ipv4, is_valid_tailscale_ipv4

APP_VERSION = "v2.8-clean-camera-mode"

DEFAULT_ADB_PORT = 5555
PC_IP = "100.125.11.48"

ROOT = Path(r"C:\PhoneHub")
RUNTIME = ROOT / "runtime"
SCREENSHOT_DIR = RUNTIME / "screenshots"
LOCATION_LOG = RUNTIME / "data" / "location_log.csv"

CONFIG_DIR = Path.home() / ".phone_remote"
CONFIG_FILE = CONFIG_DIR / "config.json"

READABLE_SCREEN = [
    "--no-audio",
    "--video-codec=h264",
    "--max-size=720",
    "--video-bit-rate=1M",
    "--max-fps=15",
    "--video-buffer=0",
    "--window-title=PhoneHub Readable"
]

FAST_SCREEN = [
    "--no-audio",
    "--video-codec=h264",
    "--max-size=360",
    "--video-bit-rate=250K",
    "--max-fps=10",
    "--video-buffer=0",
    "--window-title=PhoneHub Fast"
]

ULTRA_SCREEN = [
    "--no-audio",
    "--video-codec=h264",
    "--max-size=320",
    "--video-bit-rate=160K",
    "--max-fps=8",
    "--video-buffer=0",
    "--window-title=PhoneHub Ultra"
]


def no_window_flag():
    return subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0


def run_quiet(args, timeout=8):
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


def run_bytes(args, timeout=15):
    try:
        return subprocess.check_output(
            args,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            creationflags=no_window_flag()
        )
    except Exception:
        return b""


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


def read_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def write_config(data):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_saved_ip():
    cfg = read_config()
    ip = normalize_tailscale_ipv4(cfg.get("phone_ip"))
    try:
        port = int(cfg.get("adb_port", DEFAULT_ADB_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_ADB_PORT
    return ip, port


def save_phone_ip(ip, port=5555):
    normalized_ip = normalize_tailscale_ipv4(ip)
    if not normalized_ip:
        raise ValueError("A valid Tailscale IPv4 address is required")

    cfg = read_config()
    cfg["phone_ip"] = normalized_ip
    cfg["adb_port"] = int(port)
    cfg["device_name"] = cfg.get("device_name", "Android Phone")
    write_config(cfg)


def adb_target():
    ip, port = get_saved_ip()
    return f"{ip}:{port}" if ip else ""


def scrcpy_path():
    return shutil.which("scrcpy")


def scrcpy_running():
    out = run_quiet(["tasklist"], timeout=5).lower()
    return "scrcpy.exe" in out


def close_scrcpy():
    run_quiet(["taskkill", "/IM", "scrcpy.exe", "/F"], timeout=5)


def adb_devices_raw():
    run_quiet(["adb", "start-server"], timeout=8)
    return run_quiet(["adb", "devices"], timeout=5)


def parse_adb_devices():
    out = adb_devices_raw()
    usb_devices = []
    remote_devices = []
    unauthorized = []

    for line in out.splitlines():
        if "\tdevice" in line:
            serial = line.split()[0]
            if ":" in serial:
                remote_devices.append(serial)
            elif not serial.startswith("emulator"):
                usb_devices.append(serial)

        if "\tunauthorized" in line:
            serial = line.split()[0]
            unauthorized.append(serial)

    return usb_devices, remote_devices, unauthorized, out


def connect_remote_adb():
    target = adb_target()
    if not target:
        return False

    run_quiet(["adb", "start-server"], timeout=8)
    devices = adb_devices_raw()

    if f"{target}\tdevice" in devices:
        return True

    run_quiet(["adb", "connect", target], timeout=10)
    time.sleep(0.7)

    devices = adb_devices_raw()
    return f"{target}\tdevice" in devices


def adb_shell(command, timeout=8):
    target = adb_target()
    if not target:
        return ""
    return run_quiet(["adb", "-s", target, "shell"] + command, timeout=timeout)


def phone_prop(prop):
    return adb_shell(["getprop", prop], timeout=5)


def battery_level():
    out = adb_shell(["dumpsys", "battery"], timeout=6)
    for line in out.splitlines():
        if "level:" in line:
            return line.split(":", 1)[1].strip()
    return "-"


def take_screenshot():
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"phonehub_{stamp}.png"

    target = adb_target()
    if not target:
        return "Screenshot failed. Save the phone Tailscale IP first."

    data = run_bytes(["adb", "-s", target, "exec-out", "screencap", "-p"], timeout=15)

    if len(data) < 1000:
        return "Screenshot failed. Unlock phone once."

    path.write_bytes(data)
    return f"Screenshot saved:\n{path}"


def read_last_location_text():
    if not LOCATION_LOG.exists():
        return "No saved location log."

    lines = LOCATION_LOG.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
    if len(lines) <= 1:
        return "No saved location rows."

    last = lines[-1].split(",")
    if len(last) < 6:
        return lines[-1]

    return (
        f"Old Saved Location Only\n"
        f"Time: {last[0]}\n"
        f"Device: {last[1]}\n"
        f"Latitude: {last[2]}\n"
        f"Longitude: {last[3]}\n"
        f"Accuracy: ± {last[4]} m\n"
        f"Old Source: {last[5]}\n\n"
        f"This is old history from previous testing.\n"
        f"Live GPS is disabled in Tailscale-only mode.\n"
        f"PhoneHub now uses Tailscale only on the mobile."
    )


class Bridge(QObject):
    message = Signal(str)
    status = Signal(dict)


class PhoneHub(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"PhoneHub {APP_VERSION}")
        self.resize(1080, 700)
        self.current_view = ""
        self.screen_process = None
        self.camera_process = None
        self.camera_facing = ""

        self.bridge = Bridge()
        self.bridge.message.connect(self.set_footer)
        self.bridge.status.connect(self.apply_status)

        self.nav_buttons = []
        self.build_ui()
        self.refresh_status()

    def build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 14, 14, 14)
        side.setSpacing(8)

        logo = QLabel("PhoneHub")
        logo.setObjectName("logo")
        side.addWidget(logo)

        sub = QLabel("Smart Tailscale Control")
        sub.setObjectName("muted")
        side.addWidget(sub)

        self.stack = QStackedWidget()

        pages = [
            ("Dashboard", self.page_dashboard),
            ("Setup New Phone", self.page_setup_new_phone),
            ("Screen", self.page_screen),
            ("Camera", self.page_camera),
            ("Files", self.page_files),
            ("Apps", self.page_apps),
            ("Control", self.page_control),
            ("Settings", self.page_settings),
        ]

        for index, (name, builder) in enumerate(pages):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            side.addWidget(btn)
            self.nav_buttons.append(btn)
            self.stack.addWidget(builder())

        side.addStretch()

        self.side_status = QLabel("Checking")
        self.side_status.setObjectName("sideStatus")
        side.addWidget(self.side_status)

        main_wrap = QVBoxLayout()
        main_wrap.setSpacing(10)
        main_wrap.addWidget(self.stack)

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        main_wrap.addWidget(self.footer)

        root.addWidget(sidebar, 1)
        root.addLayout(main_wrap, 4)

        self.show_page(0)

        self.setStyleSheet("""
            QWidget {
                background: #07111f;
                color: #f8fafc;
                font-family: Segoe UI;
                font-size: 14px;
            }

            QFrame#sidebar, QFrame#card {
                background: #0d1b2d;
                border: 1px solid #1f3654;
                border-radius: 16px;
            }

            QLabel#logo {
                font-size: 30px;
                font-weight: 900;
            }

            QLabel#title {
                font-size: 24px;
                font-weight: 900;
                color: #e0f2fe;
            }

            QLabel#muted, QLabel#footer {
                color: #94a3b8;
            }

            QLabel#big {
                font-size: 16px;
                line-height: 1.5;
                color: #dbeafe;
            }

            QLabel#sideStatus {
                color: #86efac;
                font-weight: 900;
            }

            QPushButton {
                background: #13243a;
                color: #f8fafc;
                border: 1px solid #254363;
                border-radius: 12px;
                padding: 13px;
                font-weight: 800;
            }

            QPushButton:hover {
                background: #1d3553;
            }

            QPushButton#nav {
                text-align: left;
                background: #0b1626;
            }

            QPushButton#navActive {
                text-align: left;
                background: #2563eb;
                border: none;
            }

            QPushButton#primary {
                background: #2563eb;
                border: none;
                font-size: 16px;
                padding: 16px;
            }

            QPushButton#danger {
                background: #991b1b;
                border: none;
            }

            QTextEdit {
                background: #06101d;
                color: #dbeafe;
                border: 1px solid #1f3654;
                border-radius: 12px;
                padding: 10px;
            }

            QLineEdit {
                background: #06101d;
                color: #ffffff;
                border: 1px solid #1f3654;
                border-radius: 12px;
                padding: 12px;
                font-size: 16px;
            }
        """)

    def card(self, title, text=""):
        box = QFrame()
        box.setObjectName("card")

        lay = QVBoxLayout(box)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        t = QLabel(title)
        t.setObjectName("title")
        lay.addWidget(t)

        lbl = QLabel(text)
        lbl.setObjectName("big")
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lbl)

        return box, lay, lbl

    def page_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        box, _, self.device_info = self.card("Dashboard", "Checking phone...")
        layout.addWidget(box)

        loc_box, _, self.location_info = self.card("Location Status", read_last_location_text())
        layout.addWidget(loc_box)

        row = QHBoxLayout()

        open_screen = QPushButton("Open Screen")
        open_screen.setObjectName("primary")
        open_screen.clicked.connect(lambda: self.open_screen(READABLE_SCREEN, keep_alive=True))

        setup = QPushButton("Setup New Phone")
        setup.clicked.connect(lambda: self.show_page(1))

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_status)

        row.addWidget(open_screen)
        row.addWidget(setup)
        row.addWidget(refresh)
        layout.addLayout(row)

        return page

    def page_setup_new_phone(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        box, _, self.setup_status = self.card(
            "Setup New Phone",
            "Enter the phone Tailscale IP once and PhoneHub saves it permanently.\n\n"
            "Tailscale = private connection between PC and phone.\n"
            "ADB = Android permission for screen/control.\n\n"
            "Mobile requirement: Tailscale only. No PhoneHub mobile app required.\n\n"
            "After the phone has remote ADB enabled, daily use does not need USB."
        )
        layout.addWidget(box)

        ip_box, ip_layout, _ = self.card("Phone Tailscale IP", "Saved on this PC and loaded automatically next time.")
        self.setup_ip_input = QLineEdit()
        ip, port = get_saved_ip()
        self.setup_ip_input.setText(ip)
        self.setup_ip_input.setPlaceholderText("Example: 100.70.94.21")
        ip_layout.addWidget(self.setup_ip_input)
        layout.addWidget(ip_box)

        row1 = QHBoxLayout()

        smart = QPushButton("Smart Check")
        smart.setObjectName("primary")
        smart.clicked.connect(self.setup_smart_check)

        open_tail = QPushButton("Open Tailscale")
        open_tail.clicked.connect(self.setup_open_tailscale)

        enable = QPushButton("Enable Remote")
        enable.clicked.connect(self.setup_enable_remote_adb)

        row1.addWidget(smart)
        row1.addWidget(open_tail)
        row1.addWidget(enable)
        layout.addLayout(row1)

        row2 = QHBoxLayout()

        save_test = QPushButton("Save IP + Test")
        save_test.setObjectName("primary")
        save_test.clicked.connect(self.setup_save_and_test)

        finish = QPushButton("Finish Setup")
        finish.clicked.connect(self.setup_finish)

        row2.addWidget(save_test)
        row2.addWidget(finish)
        layout.addLayout(row2)

        self.setup_log = QTextEdit()
        self.setup_log.setReadOnly(True)
        self.setup_log.setText(
            "Enter the phone Tailscale IP, then click Save IP + Test.\n\n"
            "PhoneHub stores the IP in your Windows profile and automatically uses it after restart."
        )
        layout.addWidget(self.setup_log)

        return page

    def page_screen(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        info, _, _ = self.card("Screen", "Wake + Open Screen is the safe daily method.\n\nPhoneHub can wake the phone and open the screen on PC.\nFor security, unlock once on the phone if it is locked.\nAfter unlocking once, you can control the phone from PC.\n\nReadable is clearer. Fast and Ultra are lower resolution.")
        layout.addWidget(info)

        row1 = QHBoxLayout()

        readable = QPushButton("Wake + Open Screen")
        readable.setObjectName("primary")
        readable.clicked.connect(self.wake_and_open_screen)

        fast = QPushButton("Open Fast Screen")
        fast.clicked.connect(lambda: self.open_screen(FAST_SCREEN, keep_alive=False))

        ultra = QPushButton("Open Ultra Screen")
        ultra.clicked.connect(lambda: self.open_screen(ULTRA_SCREEN, keep_alive=False))

        row1.addWidget(readable)
        row1.addWidget(fast)
        row1.addWidget(ultra)
        layout.addLayout(row1)

        row2 = QHBoxLayout()

        shot = QPushButton("Screenshot")
        shot.clicked.connect(self.screenshot_async)

        wake = QPushButton("Wake")
        wake.clicked.connect(self.wake_phone)

        lock = QPushButton("Lock")
        lock.clicked.connect(self.lock_phone)

        close = QPushButton("Disconnect Screen")
        close.setObjectName("danger")
        close.clicked.connect(self.disconnect_screen)

        row2.addWidget(shot)
        row2.addWidget(wake)
        row2.addWidget(lock)
        row2.addWidget(close)
        layout.addLayout(row2)

        layout.addStretch()
        return page

    def page_camera(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        info, _, _ = self.card(
            "Camera",
            "Separate camera window. Switching Front/Back restarts camera mode, so a small delay is normal."
        )
        layout.addWidget(info)

        row = QHBoxLayout()

        back = QPushButton("Back Camera")
        back.setObjectName("primary")
        back.clicked.connect(lambda: self.open_camera_direct("back"))

        front = QPushButton("Front Camera")
        front.clicked.connect(lambda: self.open_camera_direct("front"))

        close = QPushButton("Close Camera")
        close.setObjectName("danger")
        close.clicked.connect(self.close_camera_only)

        row.addWidget(back)
        row.addWidget(front)
        row.addWidget(close)

        layout.addLayout(row)

        layout.addStretch()
        return page

    def page_files(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        info, _, _ = self.card("Files", "Open saved screenshots and location log.")
        layout.addWidget(info)

        row = QHBoxLayout()

        screenshots = QPushButton("Open Screenshots Folder")
        screenshots.clicked.connect(self.open_screenshots)

        log = QPushButton("Open Location Log")
        log.clicked.connect(self.open_location_log)

        row.addWidget(screenshots)
        row.addWidget(log)

        layout.addLayout(row)
        layout.addStretch()

        return page

    def page_apps(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        title = QLabel("Apps")
        title.setObjectName("title")
        layout.addWidget(title)

        self.apps_box = QTextEdit()
        self.apps_box.setReadOnly(True)
        self.apps_box.setText("Press Load Apps.")
        layout.addWidget(self.apps_box)

        load = QPushButton("Load Apps")
        load.clicked.connect(self.load_apps)
        layout.addWidget(load)

        return page

    def page_control(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        info, _, _ = self.card("Control", "Basic safe phone controls through ADB.")
        layout.addWidget(info)

        row = QHBoxLayout()

        reconnect = QPushButton("Reconnect ADB")
        reconnect.setObjectName("primary")
        reconnect.clicked.connect(self.refresh_status)

        wake = QPushButton("Wake Phone")
        wake.clicked.connect(self.wake_phone)

        lock = QPushButton("Lock Phone")
        lock.clicked.connect(self.lock_phone)

        reboot = QPushButton("Reboot Phone")
        reboot.setObjectName("danger")
        reboot.clicked.connect(self.reboot_phone)

        row.addWidget(reconnect)
        row.addWidget(wake)
        row.addWidget(lock)
        row.addWidget(reboot)

        layout.addLayout(row)
        layout.addStretch()

        return page

    def page_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        ip, port = get_saved_ip()
        shown_ip = ip or "Not set"
        shown_target = f"{ip}:{port}" if ip else "Not set"

        text = (
            f"PhoneHub {APP_VERSION}\n\n"
            f"Saved Phone IP: {shown_ip}\n"
            f"ADB Target: {shown_target}\n"
            f"PC IP: {PC_IP}\n\n"
            f"Mobile requirement: Tailscale only.\n"
            f"No PhoneHub mobile app required.\n"
            f"No Android Companion APK required.\n"
            f"Live GPS tracking is disabled.\n"
            f"Screen/control works through Tailscale + ADB.\n\n"
            f"Daily use:\n"
            f"1. Keep Tailscale ON on PC\n"
            f"2. Keep Tailscale ON on phone\n"
            f"3. Open PhoneHub\n"
            f"4. Use Dashboard / Screen / Camera / Screenshot\n\n"
            f"New phone:\n"
            f"Open Setup New Phone, enter its Tailscale IP, and save it once."
        )

        info, _, _ = self.card("Settings", text)
        layout.addWidget(info)
        layout.addStretch()

        return page

    def show_page(self, index):
        self.stack.setCurrentIndex(index)

        for i, btn in enumerate(self.nav_buttons):
            btn.setObjectName("navActive" if i == index else "nav")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        names = ["Dashboard", "Setup New Phone", "Screen", "Camera", "Files", "Apps", "Control", "Settings"]
        if index < len(names):
            self.set_footer(f"Opened {names[index]} page.")

    def set_footer(self, text):
        self.footer.setText(text)

    def refresh_status(self):
        ip, _ = get_saved_ip()
        if not ip:
            self.side_status.setText("Phone IP not set")
            self.set_footer("Enter the phone Tailscale IP in Setup New Phone.")
            if hasattr(self, "device_info"):
                self.device_info.setText(
                    "Phone Status: Not configured\n"
                    "Connection: Tailscale Remote\n"
                    "Saved Phone IP: Not set\n\n"
                    "Open Setup New Phone and enter the phone's Tailscale 100.x.x.x address."
                )
            return

        self.set_footer("Checking phone...")
        threading.Thread(target=self.refresh_worker, daemon=True).start()

    def refresh_worker(self):
        ok = connect_remote_adb()

        data = {
            "connected": ok,
            "model": phone_prop("ro.product.model") if ok else "-",
            "android": phone_prop("ro.build.version.release") if ok else "-",
            "battery": battery_level() if ok else "-",
        }

        self.bridge.status.emit(data)

    def apply_status(self, data):
        connected = data.get("connected", False)

        self.side_status.setText("Phone online" if connected else "Phone offline")
        self.set_footer("Ready." if connected else "Phone offline. Check Tailscale and saved phone IP.")

        ip, port = get_saved_ip()

        self.device_info.setText(
            f"Phone Status: {'Online' if connected else 'Offline'}\n"
            f"Device: {data.get('model', '-')}\n"
            f"Android Version: {data.get('android', '-')}\n"
            f"Battery: {data.get('battery', '-')}%\n"
            f"Connection: Tailscale Remote\n"
            f"ADB Status: {'Connected' if connected else 'Not Connected'}\n"
            f"ADB Target: {ip}:{port}\n"
            f"Mobile Mode: Tailscale only"
        )

        self.location_info.setText(read_last_location_text())

    def setup_log_add(self, text):
        old = self.setup_log.toPlainText() if hasattr(self, "setup_log") else ""
        stamp = datetime.now().strftime("%H:%M:%S")
        new = f"[{stamp}] {text}"
        self.setup_log.setText((old + "\n" + new).strip())
        self.setup_log.moveCursor(self.setup_log.textCursor().End)
        self.set_footer(text)

    def setup_smart_check(self):
        usb, remote, unauthorized, raw = parse_adb_devices()
        ip = normalize_tailscale_ipv4(self.setup_ip_input.text())

        lines = []

        if unauthorized:
            lines.append("USB Debugging: Not approved")
            lines.append("Action: Look at phone screen and tap Always allow from this computer, then OK.")
        elif usb:
            serial = usb[0]
            model = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=5) or "Android Phone"
            android = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"], timeout=5) or "-"
            lines.append("USB Debugging: Connected")
            lines.append(f"Device: {model}")
            lines.append(f"Android: {android}")
            lines.append(f"USB Serial: {serial}")
        else:
            lines.append("USB Debugging: Not connected")

        target = usb[0] if usb else adb_target()
        tailscale = ""
        if target:
            tailscale = run_quiet(["adb", "-s", target, "shell", "pm", "list", "packages", "com.tailscale.ipn"], timeout=6)

        if "com.tailscale.ipn" in tailscale:
            lines.append("Tailscale: Installed")
        elif target:
            lines.append("Tailscale: Not confirmed on phone")
        else:
            lines.append("Tailscale: Enter phone IP first")

        if ip:
            lines.append(f"Tailscale IP: Valid {ip}")
        else:
            lines.append("Tailscale IP: Missing or invalid")
            lines.append("Action: Open Tailscale on phone and copy its 100.x.x.x IP.")

        remote_target = f"{ip}:5555" if ip else ""

        if remote_target and remote_target in remote:
            lines.append(f"Remote Control: Connected {remote_target}")
        else:
            lines.append("Remote Control: Not connected")

        self.setup_log.setText("\n".join(lines))
        self.set_footer("Smart check complete.")

    def setup_open_tailscale(self):
        usb, remote, unauthorized, raw = parse_adb_devices()
        target = usb[0] if usb else adb_target()

        if not target:
            self.setup_log_add("Enter and save the phone Tailscale IP first, or connect the phone by USB for this button.")
            return

        run_background([
            "adb", "-s", target, "shell", "monkey",
            "-p", "com.tailscale.ipn",
            "-c", "android.intent.category.LAUNCHER",
            "1"
        ])

        self.setup_log_add("Tailscale open command sent. Copy the phone 100.x.x.x IP into PhoneHub.")

    def setup_enable_remote_adb(self):
        usb, remote, unauthorized, raw = parse_adb_devices()

        if unauthorized:
            self.setup_log_add("USB debugging is not approved. Tap Always allow from this computer → OK on phone.")
            return

        if not usb:
            self.setup_log_add("USB phone not found. Remote ADB must already be enabled before Tailscale-only control can work.")
            return

        serial = usb[0]
        run_quiet(["adb", "-s", serial, "tcpip", "5555"], timeout=10)

        self.setup_log_add("Remote ADB enabled on port 5555. Now enter phone Tailscale IP and click Save IP + Test.")

    def setup_save_and_test(self):
        ip = normalize_tailscale_ipv4(self.setup_ip_input.text())

        if not ip:
            self.setup_log_add("Invalid IP. Enter the phone Tailscale IP, for example 100.70.94.21")
            return

        self.setup_ip_input.setText(ip)
        save_phone_ip(ip, 5555)

        remote = f"{ip}:5555"
        run_quiet(["adb", "connect", remote], timeout=10)
        time.sleep(0.7)

        devices = adb_devices_raw()

        if f"{remote}\tdevice" in devices:
            self.setup_log_add(f"Saved permanently and connected: {remote}")
            self.refresh_status()
        elif f"{remote}\tunauthorized" in devices:
            self.setup_log_add("IP saved. Remote phone found but ADB is unauthorized; approve debugging on the phone.")
        else:
            self.setup_log_add("IP saved permanently. Remote ADB is not connected yet; check Tailscale and remote ADB.")

    def setup_finish(self):
        ip = normalize_tailscale_ipv4(self.setup_ip_input.text())
        if not ip:
            self.setup_log_add("Enter and save a valid Tailscale phone IP first.")
            return

        save_phone_ip(ip, 5555)
        remote = f"{ip}:5555"
        devices = adb_devices_raw()

        if f"{remote}\tdevice" in devices:
            self.setup_log_add("READY. Phone IP is saved. Future PhoneHub starts will use it automatically.")
        else:
            self.setup_log_add("Phone IP saved. Connection is currently offline; PhoneHub will keep using this saved IP next time.")

    def wake_and_open_screen(self):
        if not connect_remote_adb():
            QMessageBox.warning(
                self,
                "PhoneHub",
                "Phone not connected. Check Tailscale and the saved phone IP in Setup New Phone."
            )
            return

        adb_shell(["input", "keyevent", "224"], timeout=3)

        QMessageBox.information(
            self,
            "Safe Unlock Rule",
            "PhoneHub will wake the phone and open the screen.\n\n"
            "If the phone is locked, unlock once on the phone using fingerprint, face unlock, pattern, PIN, or password.\n\n"
            "After that, you can control the phone from PC.\n\n"
            "PhoneHub does not store your PIN and does not bypass Android lock screen."
        )

        self.open_screen(READABLE_SCREEN, keep_alive=True)

    def _proc_alive(self, proc):
        return proc is not None and proc.poll() is None

    def _start_scrcpy(self, args):
        try:
            return subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=no_window_flag()
            )
        except Exception:
            return None

    def _stop_proc(self, proc, wait_seconds=0.15):
        if not self._proc_alive(proc):
            return
        try:
            proc.terminate()
            proc.wait(timeout=wait_seconds)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def open_screen(self, profile, keep_alive=False):
        # Screen and camera are independent processes. Opening the screen never
        # closes the camera window, and an open camera never blocks the screen.
        if self._proc_alive(self.screen_process):
            self.set_footer("Screen already open.")
            return

        scrcpy = scrcpy_path()
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        target = adb_target()
        if not target:
            QMessageBox.warning(self, "PhoneHub", "Phone IP is not configured.")
            return

        # Do not run the slower connect/check path here. scrcpy can attach
        # directly to an already-online adb target, which makes opening faster.
        run_background(["adb", "-s", target, "shell", "input", "keyevent", "224"])

        args = [scrcpy, "-s", target] + profile
        self.screen_process = self._start_scrcpy(args)

        if self.screen_process:
            self.current_view = "screen"
            self.set_footer("Opening screen...")
        else:
            self.set_footer("Could not open screen.")

    def open_camera_direct(self, facing):
        scrcpy = scrcpy_path()
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        target = adb_target()
        if not target:
            self.set_footer("Phone IP is not configured.")
            return

        # Clicking the same camera again does nothing if it is already open.
        if self._proc_alive(self.camera_process) and self.camera_facing == facing:
            self.set_footer(f"{facing.title()} camera already open.")
            return

        # Switching front/back replaces ONLY the camera stream. The separate
        # phone screen window stays open.
        if self._proc_alive(self.camera_process):
            self._stop_proc(self.camera_process, wait_seconds=0.12)

        args = [
            scrcpy,
            "-s", target,
            "--video-source=camera",
            f"--camera-facing={facing}",
            "--camera-size=640x480",
            "--camera-fps=15",
            "--video-bit-rate=500K",
            "--video-buffer=0",
            "--no-audio",
            f"--window-title=PhoneHub Camera"
        ]

        self.camera_process = self._start_scrcpy(args)
        self.camera_facing = facing if self.camera_process else ""

        if self.camera_process:
            self.current_view = f"{facing} camera"
            self.set_footer(f"Switching to {facing} camera...")
        else:
            self.set_footer("Could not open camera.")

    def close_camera_only(self):
        self._stop_proc(self.camera_process)
        self.camera_process = None
        self.camera_facing = ""
        self.set_footer("Camera closed.")

    def screenshot_async(self):
        self.set_footer("Taking screenshot...")
        threading.Thread(target=self.screenshot_worker, daemon=True).start()

    def screenshot_worker(self):
        if not connect_remote_adb():
            self.bridge.message.emit("Phone not connected.")
            return

        self.bridge.message.emit(take_screenshot())

    def wake_phone(self):
        if connect_remote_adb():
            adb_shell(["input", "keyevent", "224"], timeout=3)
            self.set_footer("Phone wake command sent.")
        else:
            self.set_footer("Phone not connected.")

    def lock_phone(self):
        if connect_remote_adb():
            adb_shell(["input", "keyevent", "26"], timeout=3)
            self.set_footer("Phone lock command sent.")
        else:
            self.set_footer("Phone not connected.")

    def reboot_phone(self):
        answer = QMessageBox.question(self, "Reboot Phone", "Reboot the phone now?")
        if answer == QMessageBox.Yes and connect_remote_adb():
            run_background(["adb", "-s", adb_target(), "reboot"])
            self.set_footer("Reboot command sent.")

    def disconnect_screen(self):
        self._stop_proc(self.screen_process)
        self.screen_process = None
        if self.current_view == "screen":
            self.current_view = ""
        self.set_footer("Screen disconnected. Camera stays open.")

    def open_screenshots(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(SCREENSHOT_DIR))

    def open_location_log(self):
        LOCATION_LOG.parent.mkdir(parents=True, exist_ok=True)

        if not LOCATION_LOG.exists():
            LOCATION_LOG.write_text("time,device,latitude,longitude,accuracy_meters,source\n", encoding="utf-8")

        os.startfile(str(LOCATION_LOG))

    def load_apps(self):
        if not connect_remote_adb():
            self.apps_box.setText("Phone not connected.")
            return

        out = adb_shell(["pm", "list", "packages"], timeout=15)
        self.apps_box.setText(out if out else "No apps loaded.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PhoneHub()
    win.show()
    sys.exit(app.exec())
