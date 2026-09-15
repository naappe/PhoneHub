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

APP_VERSION = "v2.2-smart-setup"

DEFAULT_PHONE_IP = "100.70.94.21"
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
    ip = cfg.get("phone_ip") or DEFAULT_PHONE_IP
    port = int(cfg.get("adb_port", DEFAULT_ADB_PORT))
    return ip.strip(), port


def save_phone_ip(ip, port=5555):
    cfg = read_config()
    cfg["phone_ip"] = ip.strip()
    cfg["adb_port"] = int(port)
    cfg["device_name"] = cfg.get("device_name", "Android Phone")
    write_config(cfg)


def adb_target():
    ip, port = get_saved_ip()
    return f"{ip}:{port}"


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
    run_quiet(["adb", "start-server"], timeout=8)
    devices = adb_devices_raw()

    if f"{target}\tdevice" in devices:
        return True

    run_quiet(["adb", "connect", target], timeout=10)
    time.sleep(0.7)

    devices = adb_devices_raw()
    return f"{target}\tdevice" in devices


def adb_shell(command, timeout=8):
    return run_quiet(["adb", "-s", adb_target(), "shell"] + command, timeout=timeout)


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

    data = run_bytes(["adb", "-s", adb_target(), "exec-out", "screencap", "-p"], timeout=15)

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
        f"Last saved location\n"
        f"Time: {last[0]}\n"
        f"Device: {last[1]}\n"
        f"Latitude: {last[2]}\n"
        f"Longitude: {last[3]}\n"
        f"Accuracy: ± {last[4]} m\n"
        f"Source: {last[5]}\n\n"
        f"Live GPS is disabled. Only Tailscale is installed on mobile."
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

        loc_box, _, self.location_info = self.card("Last Saved Location", read_last_location_text())
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
            "Smart setup. No commands needed.\n\n"
            "PhoneHub checks USB Debugging, Tailscale, saved IP, remote ADB, and tells you when USB can be removed.\n\n"
            "Mobile requirement: Tailscale only."
        )
        layout.addWidget(box)

        ip_box, ip_layout, _ = self.card("Phone Tailscale IP", "")
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
            "Click Smart Check.\n\n"
            "PhoneHub will tell what is missing:\n"
            "- USB connected or not\n"
            "- USB debugging approved or not\n"
            "- Tailscale installed or not\n"
            "- IP saved or missing\n"
            "- Remote ADB ready or not\n"
            "- USB safe to remove or not"
        )
        layout.addWidget(self.setup_log)

        return page

    def page_screen(self):
        page = QWidget()
        layout = QVBoxLayout(page)

        info, _, _ = self.card("Screen", "Readable is clearer. Fast and Ultra are lower resolution.")
        layout.addWidget(info)

        row1 = QHBoxLayout()

        readable = QPushButton("Open Readable Screen")
        readable.setObjectName("primary")
        readable.clicked.connect(lambda: self.open_screen(READABLE_SCREEN, keep_alive=True))

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
        close.clicked.connect(self.disconnect_screen)

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

        text = (
            f"PhoneHub {APP_VERSION}\n\n"
            f"Saved Phone IP: {ip}\n"
            f"ADB Target: {ip}:{port}\n"
            f"PC IP: {PC_IP}\n\n"
            f"Mobile app: Tailscale only.\n"
            f"Live GPS: disabled without Companion APK.\n"
            f"Screen/control: enabled through Tailscale + ADB.\n\n"
            f"Daily use:\n"
            f"1. Keep Tailscale ON on PC\n"
            f"2. Keep Tailscale ON on phone\n"
            f"3. Open PhoneHub\n"
            f"4. Use Screen / Camera / Screenshot"
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
        self.set_footer("Ready." if connected else "Phone offline. Use Setup New Phone.")

        ip, port = get_saved_ip()

        self.device_info.setText(
            f"Status: {'Online' if connected else 'Offline'}\n"
            f"Model: {data.get('model', '-')}\n"
            f"Android: {data.get('android', '-')}\n"
            f"Battery: {data.get('battery', '-')}%\n"
            f"Connection: Tailscale remote\n"
            f"ADB Target: {ip}:{port}\n"
            f"Mode: Tailscale-only"
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
        ip = self.setup_ip_input.text().strip()

        lines = []

        if unauthorized:
            lines.append("USB Debugging: NOT APPROVED")
            lines.append("Action: Look at phone screen and tap Always allow from this computer, then OK.")
        elif usb:
            serial = usb[0]
            model = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=5) or "Android Phone"
            android = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"], timeout=5) or "-"
            lines.append(f"USB Debugging: Connected")
            lines.append(f"Device: {model}")
            lines.append(f"Android: {android}")
            lines.append(f"USB Serial: {serial}")
        else:
            lines.append("USB Debugging: Not connected")
            lines.append("Action: Connect USB cable once, unlock phone, enable USB Debugging.")

        target = usb[0] if usb else adb_target()
        tailscale = run_quiet(["adb", "-s", target, "shell", "pm", "list", "packages", "com.tailscale.ipn"], timeout=6)

        if "com.tailscale.ipn" in tailscale:
            lines.append("Tailscale: Installed")
            lines.append("Action: Make sure Tailscale says Connected on phone.")
        else:
            lines.append("Tailscale: Not confirmed")
            lines.append("Action: Install Tailscale on phone and login same tailnet/account as PC.")

        if ip.startswith("100."):
            lines.append(f"Tailscale IP: Saved/entered {ip}")
        else:
            lines.append("Tailscale IP: Missing")
            lines.append("Action: Open Tailscale on phone and copy the 100.x.x.x IP.")

        remote_target = f"{ip}:5555" if ip else adb_target()

        if remote_target in remote:
            lines.append(f"Remote ADB: Connected {remote_target}")
            lines.append("USB Cable: SAFE TO REMOVE")
        else:
            lines.append("Remote ADB: Not ready")
            lines.append("USB Cable: Keep connected until Test Remote succeeds.")

        self.setup_log.setText("\n".join(lines))
        self.set_footer("Smart check complete.")

    def setup_open_tailscale(self):
        usb, remote, unauthorized, raw = parse_adb_devices()
        target = usb[0] if usb else adb_target()

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
            self.setup_log_add("USB phone not found. Connect USB cable one time before enabling remote mode.")
            return

        serial = usb[0]
        out = run_quiet(["adb", "-s", serial, "tcpip", "5555"], timeout=10)

        self.setup_log_add("Remote ADB enabled on port 5555. Now enter phone Tailscale IP and click Save IP + Test.")

    def setup_save_and_test(self):
        ip = self.setup_ip_input.text().strip()

        if not ip.startswith("100."):
            self.setup_log_add("Invalid IP. Enter phone Tailscale IP like 100.70.94.21")
            return

        save_phone_ip(ip, 5555)

        remote = f"{ip}:5555"
        run_quiet(["adb", "connect", remote], timeout=10)
        time.sleep(0.7)

        devices = adb_devices_raw()

        if f"{remote}\tdevice" in devices:
            self.setup_log_add(f"Remote ADB connected. USB cable can be removed now. {remote}")
            self.refresh_status()
        elif f"{remote}\tunauthorized" in devices:
            self.setup_log_add("Remote found but unauthorized. Approve debugging on phone.")
        else:
            self.setup_log_add("Remote not connected. Check Tailscale ON, same account/tailnet, and IP is correct.")

    def setup_finish(self):
        ip = self.setup_ip_input.text().strip()
        remote = f"{ip}:5555"

        devices = adb_devices_raw()

        if f"{remote}\tdevice" in devices:
            self.setup_log_add("READY. Remove USB now. Daily use: Tailscale ON on PC + phone, then open PhoneHub.")
        else:
            self.setup_log_add("Not ready. Click Save IP + Test first.")

    def open_screen(self, profile, keep_alive=False):
        if keep_alive and scrcpy_running():
            self.set_footer("Screen already open. Keeping it alive.")
            return

        if not connect_remote_adb():
            QMessageBox.warning(self, "PhoneHub", "Phone not connected. Use Setup New Phone.")
            return

        scrcpy = scrcpy_path()
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        if not keep_alive:
            close_scrcpy()

        adb_shell(["input", "keyevent", "224"], timeout=3)

        ok = run_background([scrcpy, "-s", adb_target()] + profile)
        self.current_view = "screen"

        self.set_footer("Opening screen..." if ok else "Could not open screen.")

    def open_camera_direct(self, facing):
        if not connect_remote_adb():
            self.set_footer("Phone not connected.")
            return

        scrcpy = scrcpy_path()
        if not scrcpy:
            QMessageBox.critical(self, "PhoneHub", "scrcpy not found.")
            return

        close_scrcpy()

        args = [
            scrcpy,
            "-s", adb_target(),
            "--video-source=camera",
            f"--camera-facing={facing}",
            "--camera-size=320x240",
            "--camera-fps=8",
            "--video-bit-rate=180K",
            "--no-audio",
            f"--window-title=PhoneHub {facing.title()} Camera"
        ]

        ok = run_background(args)
        self.current_view = f"{facing} camera"

        self.set_footer(f"Opening {facing} camera..." if ok else "Could not open camera.")

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
        close_scrcpy()
        self.current_view = ""
        self.set_footer("Screen/camera disconnected.")

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
