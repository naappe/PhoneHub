import os
import sys
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QFrame, QMessageBox, QStackedWidget, QTextEdit, QLineEdit,
    QScrollArea, QSizePolicy, QFileDialog
)

from phone_config import normalize_tailscale_ipv4, is_valid_tailscale_ipv4

APP_VERSION = "v3.4-apk-analysis-lab"

DEFAULT_ADB_PORT = 5555
PC_IP = "100.125.11.48"

ROOT = Path(r"C:\PhoneHub")
RUNTIME = ROOT / "runtime"
SCREENSHOT_DIR = RUNTIME / "screenshots"
LOCATION_LOG = RUNTIME / "data" / "location_log.csv"
APK_LAB_DIR = RUNTIME / "apk_lab"

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
    screen_result = Signal(str)
    service_result = Signal(str)
    apk_result = Signal(str)


class PhoneHub(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle(f"PhoneHub {APP_VERSION}")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
        self.setMinimumSize(720, 480)
        self.resize(960, 620)
        self.current_view = ""
        self.screen_process = None
        self.camera_process = None
        self.camera_facing = ""

        self.bridge = Bridge()
        self.bridge.message.connect(self.set_footer)
        self.bridge.status.connect(self.apply_status)
        self.bridge.screen_result.connect(self.set_screen_result)
        self.bridge.service_result.connect(self.set_service_result)
        self.bridge.apk_result.connect(self.set_apk_result)

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
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.setMinimumSize(0, 0)

        pages = [
            ("Dashboard", self.page_dashboard),
            ("Setup New Phone", self.page_setup_new_phone),
            ("Screen", self.page_screen),
            ("Camera", self.page_camera),
            ("Files", self.page_files),
            ("Apps", self.page_apps),
            ("Control", self.page_control),
            ("Service Lab", self.page_service_lab),
            ("APK Analysis", self.page_apk_analysis),
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

        self.content_scroll = QScrollArea()
        self.content_scroll.setObjectName("contentScroll")
        self.content_scroll.setWidgetResizable(True)
        self.content_scroll.setFrameShape(QFrame.NoFrame)
        self.content_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.content_scroll.setWidget(self.stack)
        main_wrap.addWidget(self.content_scroll, 1)

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        main_wrap.addWidget(self.footer)

        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setObjectName("sidebarScroll")
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QFrame.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.sidebar_scroll.setMinimumWidth(205)
        self.sidebar_scroll.setMaximumWidth(280)
        self.sidebar_scroll.setWidget(sidebar)

        root.addWidget(self.sidebar_scroll, 1)
        root.addLayout(main_wrap, 4)

        self.show_page(0)

        self.setStyleSheet("""
            QWidget {
                background: #07111f;
                color: #f8fafc;
                font-family: Segoe UI;
                font-size: 14px;
            }

            QScrollArea#contentScroll, QScrollArea#sidebarScroll {
                background: transparent;
                border: none;
            }

            QScrollArea#contentScroll > QWidget > QWidget,
            QScrollArea#sidebarScroll > QWidget > QWidget {
                background: transparent;
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
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        info, _, _ = self.card(
            "Screen",
            "Wake + Open Screen is the normal daily method. "
            "Readable gives the clearest view; Fast and Ultra use less bandwidth."
        )
        layout.addWidget(info)

        main_box, main_layout, _ = self.card("Open screen", "Choose one view mode.")
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        readable = QPushButton("Wake + Open Screen")
        readable.setObjectName("primary")
        readable.setMinimumHeight(44)
        readable.clicked.connect(self.wake_and_open_screen)

        fast = QPushButton("Fast Screen")
        fast.setMinimumHeight(44)
        fast.clicked.connect(lambda: self.open_screen(FAST_SCREEN, keep_alive=False))

        ultra = QPushButton("Ultra Screen")
        ultra.setMinimumHeight(44)
        ultra.clicked.connect(lambda: self.open_screen(ULTRA_SCREEN, keep_alive=False))

        row1.addWidget(readable, 2)
        row1.addWidget(fast, 1)
        row1.addWidget(ultra, 1)
        main_layout.addLayout(row1)
        layout.addWidget(main_box)

        tools_box, tools_layout, _ = self.card("Quick controls", "Common screen actions.")
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        shot = QPushButton("Screenshot")
        shot.setMinimumHeight(42)
        shot.clicked.connect(self.screenshot_async)

        wake = QPushButton("Wake")
        wake.setMinimumHeight(42)
        wake.clicked.connect(self.wake_phone)

        lock = QPushButton("Lock")
        lock.setMinimumHeight(42)
        lock.clicked.connect(self.lock_phone)

        close = QPushButton("Disconnect Screen")
        close.setObjectName("danger")
        close.setMinimumHeight(42)
        close.clicked.connect(self.disconnect_screen)

        row2.addWidget(shot)
        row2.addWidget(wake)
        row2.addWidget(lock)
        row2.addWidget(close)
        tools_layout.addLayout(row2)
        layout.addWidget(tools_box)

        diag_box, diag_layout, _ = self.card(
            "Diagnostics",
            "Use this only when checking Android lock-state behavior."
        )

        lock_test = QPushButton("Run Lock State Test")
        lock_test.setMinimumHeight(42)
        lock_test.clicked.connect(self.lock_state_test)
        diag_layout.addWidget(lock_test)

        self.screen_result_label = QLabel("No diagnostic result yet.")
        self.screen_result_label.setObjectName("big")
        self.screen_result_label.setWordWrap(True)
        self.screen_result_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        diag_layout.addWidget(self.screen_result_label)

        layout.addWidget(diag_box)
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
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        info, _, _ = self.card("Control", "Basic safe phone controls through ADB.")
        layout.addWidget(info)

        row = QHBoxLayout()
        row.setSpacing(10)

        reconnect = QPushButton("Reconnect ADB")
        reconnect.setObjectName("primary")
        reconnect.setMinimumHeight(42)
        reconnect.clicked.connect(self.control_reconnect)

        wake = QPushButton("Wake Phone")
        wake.setMinimumHeight(42)
        wake.clicked.connect(self.control_wake_phone)

        lock = QPushButton("Lock Phone")
        lock.setMinimumHeight(42)
        lock.clicked.connect(self.control_lock_phone)

        reboot = QPushButton("Reboot Phone")
        reboot.setObjectName("danger")
        reboot.setMinimumHeight(42)
        reboot.clicked.connect(self.control_reboot_phone)

        row.addWidget(reconnect)
        row.addWidget(wake)
        row.addWidget(lock)
        row.addWidget(reboot)
        layout.addLayout(row)

        status_box, _, self.control_status_label = self.card(
            "Connection Status",
            "Checking current phone connection..."
        )
        layout.addWidget(status_box)

        layout.addStretch()
        QTimer.singleShot(250, self.update_control_status)
        return page

    def update_control_status(self, last_action=None):
        if not hasattr(self, "control_status_label"):
            return

        ip, port = get_saved_ip()
        usb, remote, unauthorized, _ = parse_adb_devices()
        target = f"{ip}:{port}" if ip else "Not set"

        remote_connected = target in remote if ip else False

        lines = [
            f"Phone: {'Online' if remote_connected else 'Offline'}",
            f"ADB: {'Connected' if remote_connected else 'Not connected'}",
            f"Tailscale IP: {ip or 'Not set'}",
            f"USB: {'Unauthorized' if unauthorized else ('Connected' if usb else 'Not connected')}",
        ]

        if last_action:
            lines.append(f"Last action: {last_action}")

        self.control_status_label.setText("\n".join(lines))

    def control_reconnect(self):
        self.set_footer("Reconnecting ADB...")
        self.refresh_status()
        QTimer.singleShot(1200, lambda: self.update_control_status("Reconnect ADB"))

    def control_wake_phone(self):
        self.wake_phone()
        QTimer.singleShot(300, lambda: self.update_control_status("Wake Phone"))

    def control_lock_phone(self):
        self.lock_phone()
        QTimer.singleShot(300, lambda: self.update_control_status("Lock Phone"))

    def control_reboot_phone(self):
        self.reboot_phone()
        QTimer.singleShot(300, lambda: self.update_control_status("Reboot Phone"))


    def page_service_lab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        info, _, _ = self.card(
            "Service Lab",
            "Owner-authorized Android diagnostics and recovery controls. "
            "PhoneHub can identify the device, inspect verified-boot / bootloader state, "
            "open reset settings, and reboot into standard Android service modes. "
            "It does not bypass FRP, Google account verification, screen locks, or vendor authentication."
        )
        layout.addWidget(info)

        row1 = QHBoxLayout()
        row1.setSpacing(10)

        scan = QPushButton("Scan Device")
        scan.setObjectName("primary")
        scan.setMinimumHeight(42)
        scan.clicked.connect(self.service_scan_async)

        boot = QPushButton("Boot / Security State")
        boot.setMinimumHeight(42)
        boot.clicked.connect(self.service_boot_state_async)

        reset_settings = QPushButton("Open Reset Settings")
        reset_settings.setMinimumHeight(42)
        reset_settings.clicked.connect(self.service_open_reset_settings)

        row1.addWidget(scan)
        row1.addWidget(boot)
        row1.addWidget(reset_settings)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        recovery = QPushButton("Reboot Recovery")
        recovery.setMinimumHeight(42)
        recovery.clicked.connect(self.service_reboot_recovery)

        bootloader = QPushButton("Reboot Bootloader")
        bootloader.setMinimumHeight(42)
        bootloader.clicked.connect(self.service_reboot_bootloader)

        system = QPushButton("Reboot System")
        system.setMinimumHeight(42)
        system.clicked.connect(self.service_reboot_system)

        row2.addWidget(recovery)
        row2.addWidget(bootloader)
        row2.addWidget(system)
        layout.addLayout(row2)

        result_box, result_layout, _ = self.card(
            "Service Report",
            "Run Scan Device first. PhoneHub will show only data exposed by standard ADB / Fastboot interfaces."
        )

        self.service_result_box = QTextEdit()
        self.service_result_box.setReadOnly(True)
        self.service_result_box.setMinimumHeight(230)
        self.service_result_box.setText("No service scan yet.")
        result_layout.addWidget(self.service_result_box)

        layout.addWidget(result_box)
        layout.addStretch()
        return page

    def set_service_result(self, text):
        if hasattr(self, "service_result_box"):
            self.service_result_box.setText(text)

    def _service_adb_target(self):
        usb, remote, unauthorized, _ = parse_adb_devices()
        if unauthorized:
            return "", "ADB authorization is waiting on the phone. Approve the USB debugging prompt first."
        if usb:
            return usb[0], ""
        saved = adb_target()
        if saved and saved in remote:
            return saved, ""
        return "", "No authorized ADB device is connected."

    def _service_prop(self, target, prop):
        return run_quiet(["adb", "-s", target, "shell", "getprop", prop], timeout=5) or "-"

    def _fastboot_devices(self):
        if not shutil.which("fastboot"):
            return []
        out = run_quiet(["fastboot", "devices"], timeout=5)
        devices = []
        for line in out.splitlines():
            parts = line.split()
            if parts:
                devices.append(parts[0])
        return devices

    def service_scan_async(self):
        self.set_footer("Scanning Android service information...")
        threading.Thread(target=self.service_scan_worker, daemon=True).start()

    def service_scan_worker(self):
        target, error = self._service_adb_target()
        fastboot = self._fastboot_devices()

        if not target:
            fb_text = ", ".join(fastboot) if fastboot else "none"
            self.bridge.service_result.emit(
                "ADB device: not available\n"
                f"Fastboot device(s): {fb_text}\n\n"
                f"{error}"
            )
            self.bridge.message.emit("Service scan finished.")
            return

        fields = [
            ("Manufacturer", "ro.product.manufacturer"),
            ("Brand", "ro.product.brand"),
            ("Model", "ro.product.model"),
            ("Product", "ro.product.name"),
            ("Device", "ro.product.device"),
            ("Hardware", "ro.hardware"),
            ("Android", "ro.build.version.release"),
            ("SDK", "ro.build.version.sdk"),
            ("Security patch", "ro.build.version.security_patch"),
            ("Build fingerprint", "ro.build.fingerprint"),
            ("Bootloader", "ro.bootloader"),
            ("Verified boot", "ro.boot.verifiedbootstate"),
            ("Flash locked", "ro.boot.flash.locked"),
            ("VBMeta state", "ro.boot.vbmeta.device_state"),
            ("Boot device state", "ro.boot.veritymode"),
            ("Crypto state", "ro.crypto.state"),
            ("Crypto type", "ro.crypto.type"),
        ]

        lines = [
            "PHONEHUB SERVICE REPORT",
            "",
            f"ADB target: {target}",
            f"Fastboot detected: {'yes - ' + ', '.join(fastboot) if fastboot else 'no'}",
            "",
        ]

        for label, prop in fields:
            lines.append(f"{label}: {self._service_prop(target, prop)}")

        serial = run_quiet(["adb", "-s", target, "get-serialno"], timeout=5) or "-"
        lines.append(f"ADB serial: {serial}")
        lines.extend([
            "",
            "FRP / account verification:",
            "Standard ADB does not provide a reliable FRP bypass/status interface.",
            "PhoneHub intentionally does not bypass Google account verification, screen locks, or vendor authorization."
        ])

        self.bridge.service_result.emit("\n".join(lines))
        self.bridge.message.emit("Service scan complete.")

    def service_boot_state_async(self):
        self.set_footer("Checking boot and security state...")
        threading.Thread(target=self.service_boot_state_worker, daemon=True).start()

    def service_boot_state_worker(self):
        target, error = self._service_adb_target()
        fastboot = self._fastboot_devices()

        lines = ["BOOT / SECURITY STATE", ""]

        if target:
            verified = self._service_prop(target, "ro.boot.verifiedbootstate")
            flash_locked = self._service_prop(target, "ro.boot.flash.locked")
            vbmeta = self._service_prop(target, "ro.boot.vbmeta.device_state")
            bootloader = self._service_prop(target, "ro.bootloader")

            lines.extend([
                f"ADB target: {target}",
                f"Verified boot state: {verified}",
                f"Flash locked flag: {flash_locked}",
                f"VBMeta device state: {vbmeta}",
                f"Bootloader version: {bootloader}",
            ])
        else:
            lines.append(f"ADB: unavailable - {error}")

        if fastboot:
            lines.append("")
            lines.append("Fastboot device(s): " + ", ".join(fastboot))
            for serial in fastboot:
                unlocked = run_quiet(["fastboot", "-s", serial, "getvar", "unlocked"], timeout=6)
                secure = run_quiet(["fastboot", "-s", serial, "getvar", "secure"], timeout=6)
                if unlocked:
                    lines.append(f"{serial} unlocked query: {unlocked}")
                if secure:
                    lines.append(f"{serial} secure query: {secure}")
        else:
            lines.extend(["", "Fastboot device: none detected"])

        lines.extend([
            "",
            "This page reads state only. It does not issue bootloader-unlock, FRP-bypass, or authentication-bypass commands."
        ])

        self.bridge.service_result.emit("\n".join(lines))
        self.bridge.message.emit("Boot/security-state check complete.")

    def service_open_reset_settings(self):
        target, error = self._service_adb_target()
        if not target:
            QMessageBox.warning(self, "PhoneHub Service Lab", error)
            return

        answer = QMessageBox.question(
            self,
            "Open Reset Settings",
            "Open Android reset/privacy settings on the connected phone?\n\n"
            "PhoneHub will not confirm or execute a factory reset automatically."
        )
        if answer != QMessageBox.Yes:
            return

        out = run_quiet([
            "adb", "-s", target, "shell", "am", "start",
            "-a", "android.settings.PRIVACY_SETTINGS"
        ], timeout=8)

        if not out:
            run_background([
                "adb", "-s", target, "shell", "am", "start",
                "-a", "android.settings.SETTINGS"
            ])

        self.set_footer("Reset/settings page requested on phone.")

    def _service_reboot(self, mode, label):
        target, error = self._service_adb_target()
        if not target:
            QMessageBox.warning(self, "PhoneHub Service Lab", error)
            return

        answer = QMessageBox.question(
            self,
            label,
            f"Reboot the connected phone into {label.lower()}?"
        )
        if answer != QMessageBox.Yes:
            return

        cmd = ["adb", "-s", target, "reboot"]
        if mode:
            cmd.append(mode)
        run_background(cmd)
        self.set_footer(f"{label} command sent.")

    def service_reboot_recovery(self):
        self._service_reboot("recovery", "Recovery")

    def service_reboot_bootloader(self):
        self._service_reboot("bootloader", "Bootloader")

    def service_reboot_system(self):
        self._service_reboot("", "System")


    def page_apk_analysis(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        info, _, _ = self.card(
            "APK Analysis Lab",
            "Static analysis for APKs you own or are authorized to test. "
            "PhoneHub can inspect an APK with JADX / Apktool, locate RootBeer and other root-detection references, "
            "and show the relevant files. It does not automatically flip conditions, bypass root checks, "
            "or alter third-party app security controls."
        )
        layout.addWidget(info)

        select_box, select_layout, _ = self.card(
            "APK File",
            "Choose an APK from this PC. Analysis files are written under C:\\PhoneHub\\runtime\\apk_lab."
        )

        self.apk_path_input = QLineEdit()
        self.apk_path_input.setPlaceholderText(r"Example: C:\Users\User\Downloads\test-app.apk")
        select_layout.addWidget(self.apk_path_input)

        choose = QPushButton("Choose APK")
        choose.setObjectName("primary")
        choose.clicked.connect(self.apk_choose_file)
        select_layout.addWidget(choose)
        layout.addWidget(select_box)

        row = QHBoxLayout()
        row.setSpacing(10)

        check = QPushButton("Check Tools")
        check.clicked.connect(self.apk_check_tools)

        jadx = QPushButton("JADX Analyze")
        jadx.setObjectName("primary")
        jadx.clicked.connect(self.apk_jadx_async)

        apktool = QPushButton("Apktool Decode")
        apktool.clicked.connect(self.apk_apktool_async)

        rootbeer = QPushButton("Find Root Detection")
        rootbeer.clicked.connect(self.apk_find_root_detection_async)

        row.addWidget(check)
        row.addWidget(jadx)
        row.addWidget(apktool)
        row.addWidget(rootbeer)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)

        open_lab = QPushButton("Open APK Lab Folder")
        open_lab.clicked.connect(self.apk_open_lab_folder)

        clear = QPushButton("Clear Report")
        clear.clicked.connect(lambda: self.set_apk_result("No APK analysis yet."))

        row2.addWidget(open_lab)
        row2.addWidget(clear)
        layout.addLayout(row2)

        result_box, result_layout, _ = self.card(
            "Analysis Report",
            "RootBeer indicators include package/class names such as com.scottyab.rootbeer and calls like isRooted()."
        )

        self.apk_result_box = QTextEdit()
        self.apk_result_box.setReadOnly(True)
        self.apk_result_box.setMinimumHeight(260)
        self.apk_result_box.setText("No APK analysis yet.")
        result_layout.addWidget(self.apk_result_box)

        layout.addWidget(result_box)
        layout.addStretch()
        return page

    def set_apk_result(self, text):
        if hasattr(self, "apk_result_box"):
            self.apk_result_box.setText(text)

    def _apk_selected_path(self):
        if not hasattr(self, "apk_path_input"):
            return None
        raw = self.apk_path_input.text().strip().strip('"')
        if not raw:
            return None
        path = Path(raw)
        if not path.exists() or not path.is_file() or path.suffix.lower() != ".apk":
            return None
        return path

    def _apk_project_dir(self, apk_path, suffix):
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in apk_path.stem)
        return APK_LAB_DIR / f"{safe_name}_{suffix}"

    def apk_choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose APK",
            str(Path.home()),
            "Android APK (*.apk)"
        )
        if path:
            self.apk_path_input.setText(path)
            self.set_footer("APK selected.")

    def apk_check_tools(self):
        jadx = shutil.which("jadx") or shutil.which("jadx.bat")
        jadx_gui = shutil.which("jadx-gui") or shutil.which("jadx-gui.bat")
        apktool = shutil.which("apktool") or shutil.which("apktool.bat")
        java = shutil.which("java")

        lines = [
            "APK ANALYSIS TOOL CHECK",
            "",
            f"JADX CLI: {jadx or 'Not found'}",
            f"JADX GUI: {jadx_gui or 'Not found'}",
            f"Apktool: {apktool or 'Not found'}",
            f"Java: {java or 'Not found'}",
            "",
            "Required for full workflow: Java + JADX + Apktool.",
            "PhoneHub performs analysis only; it does not automate root-check bypass patches."
        ]
        self.set_apk_result("\n".join(lines))
        self.set_footer("APK tool check complete.")

    def apk_jadx_async(self):
        apk_path = self._apk_selected_path()
        if not apk_path:
            QMessageBox.warning(self, "PhoneHub APK Analysis", "Choose a valid APK file first.")
            return

        jadx = shutil.which("jadx") or shutil.which("jadx.bat")
        if not jadx:
            QMessageBox.warning(self, "PhoneHub APK Analysis", "JADX CLI was not found in PATH.")
            return

        self.set_footer("Running JADX analysis...")
        threading.Thread(
            target=self.apk_jadx_worker,
            args=(apk_path, jadx),
            daemon=True
        ).start()

    def apk_jadx_worker(self, apk_path, jadx):
        APK_LAB_DIR.mkdir(parents=True, exist_ok=True)
        out_dir = self._apk_project_dir(apk_path, "jadx")
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)

        try:
            proc = subprocess.run(
                [jadx, "-d", str(out_dir), str(apk_path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
                creationflags=no_window_flag()
            )
            tail = (proc.stdout or "").strip()
            if len(tail) > 3000:
                tail = tail[-3000:]

            lines = [
                "JADX ANALYSIS COMPLETE" if proc.returncode == 0 else "JADX FINISHED WITH WARNINGS",
                "",
                f"APK: {apk_path}",
                f"Output: {out_dir}",
                f"Exit code: {proc.returncode}",
            ]
            if tail:
                lines.extend(["", "JADX output:", tail])

            self.bridge.apk_result.emit("\n".join(lines))
            self.bridge.message.emit("JADX analysis finished.")
        except Exception as exc:
            self.bridge.apk_result.emit(f"JADX failed:\n{exc}")
            self.bridge.message.emit("JADX analysis failed.")

    def apk_apktool_async(self):
        apk_path = self._apk_selected_path()
        if not apk_path:
            QMessageBox.warning(self, "PhoneHub APK Analysis", "Choose a valid APK file first.")
            return

        apktool = shutil.which("apktool") or shutil.which("apktool.bat")
        if not apktool:
            QMessageBox.warning(self, "PhoneHub APK Analysis", "Apktool was not found in PATH.")
            return

        self.set_footer("Decoding APK resources and smali...")
        threading.Thread(
            target=self.apk_apktool_worker,
            args=(apk_path, apktool),
            daemon=True
        ).start()

    def apk_apktool_worker(self, apk_path, apktool):
        APK_LAB_DIR.mkdir(parents=True, exist_ok=True)
        out_dir = self._apk_project_dir(apk_path, "apktool")
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)

        try:
            proc = subprocess.run(
                [apktool, "d", "-f", "-o", str(out_dir), str(apk_path)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=180,
                creationflags=no_window_flag()
            )
            tail = (proc.stdout or "").strip()
            if len(tail) > 3000:
                tail = tail[-3000:]

            lines = [
                "APKTOOL DECODE COMPLETE" if proc.returncode == 0 else "APKTOOL FINISHED WITH WARNINGS",
                "",
                f"APK: {apk_path}",
                f"Output: {out_dir}",
                f"Exit code: {proc.returncode}",
            ]
            if tail:
                lines.extend(["", "Apktool output:", tail])

            self.bridge.apk_result.emit("\n".join(lines))
            self.bridge.message.emit("Apktool decode finished.")
        except Exception as exc:
            self.bridge.apk_result.emit(f"Apktool failed:\n{exc}")
            self.bridge.message.emit("Apktool decode failed.")

    def apk_find_root_detection_async(self):
        apk_path = self._apk_selected_path()
        if not apk_path:
            QMessageBox.warning(self, "PhoneHub APK Analysis", "Choose a valid APK file first.")
            return

        self.set_footer("Searching decoded sources for root-detection indicators...")
        threading.Thread(
            target=self.apk_find_root_detection_worker,
            args=(apk_path,),
            daemon=True
        ).start()

    def apk_find_root_detection_worker(self, apk_path):
        jadx_dir = self._apk_project_dir(apk_path, "jadx")
        apktool_dir = self._apk_project_dir(apk_path, "apktool")
        roots = [p for p in (jadx_dir, apktool_dir) if p.exists()]

        if not roots:
            self.bridge.apk_result.emit(
                "No decoded project was found.\n\n"
                "Run JADX Analyze or Apktool Decode first."
            )
            self.bridge.message.emit("Root-detection search needs decoded files.")
            return

        indicators = (
            "com.scottyab.rootbeer",
            "rootbeer",
            "isrooted(",
            "isrootedwithoutbusyboxcheck(",
            "detectrootmanagementapps",
            "detectpotentiallydangerousapps",
            "checkforsubinary",
            "checkforrwpaths",
            "checkfortestkeys",
            "checkformagiskbinary",
            "magisk",
            "su",
        )

        hits = []
        scanned = 0
        allowed_ext = {".java", ".kt", ".smali", ".xml", ".txt"}

        for root in roots:
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in allowed_ext:
                    continue
                scanned += 1
                if scanned > 20000:
                    break

                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue

                lower = text.lower()
                matched = [item for item in indicators if item in lower]
                if not matched:
                    continue

                rel = str(path.relative_to(root))
                line_numbers = []
                for n, line in enumerate(text.splitlines(), start=1):
                    ll = line.lower()
                    if any(item in ll for item in matched):
                        line_numbers.append(n)
                        if len(line_numbers) >= 8:
                            break

                hits.append((root.name, rel, matched[:5], line_numbers))
                if len(hits) >= 80:
                    break

        lines = [
            "ROOT-DETECTION STATIC ANALYSIS",
            "",
            f"APK: {apk_path.name}",
            f"Files scanned: {scanned}",
            f"Matches: {len(hits)}",
            "",
        ]

        if not hits:
            lines.append("No common RootBeer/root-detection indicators were found in the decoded text.")
        else:
            for source, rel, matched, nums in hits:
                lines.append(f"[{source}] {rel}")
                lines.append("  Indicators: " + ", ".join(matched))
                if nums:
                    lines.append("  Lines: " + ", ".join(str(n) for n in nums))
                lines.append("")

        lines.extend([
            "Analysis note:",
            "A match shows where root-detection logic or related strings appear. "
            "It does not prove that the application blocks rooted devices, and PhoneHub does not automatically modify the decision branch."
        ])

        self.bridge.apk_result.emit("\n".join(lines))
        self.bridge.message.emit("Root-detection search complete.")

    def apk_open_lab_folder(self):
        APK_LAB_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(APK_LAB_DIR))

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

        names = ["Dashboard", "Setup New Phone", "Screen", "Camera", "Files", "Apps", "Control", "Service Lab", "APK Analysis", "Settings"]
        if index < len(names):
            self.set_footer(f"Opened {names[index]} page.")

    def set_footer(self, text):
        self.footer.setText(text)

    def set_screen_result(self, text):
        if hasattr(self, "screen_result_label"):
            self.screen_result_label.setText(text)

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
        self.update_control_status()

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

    def _android_lock_state(self):
        target = adb_target()
        if not target:
            return "unknown", "Phone IP is not configured.", {}

        evidence = {}

        commands = {
            "window_policy": ["adb", "-s", target, "shell", "dumpsys", "window", "policy"],
            "window": ["adb", "-s", target, "shell", "dumpsys", "window"],
            "trust": ["adb", "-s", target, "shell", "dumpsys", "trust"],
            "power": ["adb", "-s", target, "shell", "dumpsys", "power"],
            "device_policy": ["adb", "-s", target, "shell", "dumpsys", "device_policy"],
        }

        for name, cmd in commands.items():
            evidence[name] = run_quiet(cmd, timeout=4).lower()

        combined = "\n".join(evidence.values())

        locked_markers = (
            "devicelocked=true",
            "device locked=true",
            "mshowinglockscreen=true",
            "iskeyguardshowing=true",
            "keyguard showing=true",
            "mkeyguardshowing=true",
            "keyguard=true",
            "showing=true secure=true",
        )

        unlocked_markers = (
            "devicelocked=false",
            "device locked=false",
            "mshowinglockscreen=false",
            "iskeyguardshowing=false",
            "mkeyguardshowing=false",
            "keyguard=false",
        )

        locked_hits = [m for m in locked_markers if m in combined]
        unlocked_hits = [m for m in unlocked_markers if m in combined]

        if locked_hits and not unlocked_hits:
            return "locked", "Android reports the secure keyguard/device is locked.", {
                "locked_hits": locked_hits,
                "unlocked_hits": unlocked_hits,
            }

        if unlocked_hits and not locked_hits:
            return "unlocked", "Android reports the keyguard/device is unlocked.", {
                "locked_hits": locked_hits,
                "unlocked_hits": unlocked_hits,
            }

        power = evidence.get("power", "")
        interactive = "minteractive=true" in power or "display power: state=on" in power
        asleep = "minteractive=false" in power or "display power: state=off" in power

        detail = "Android returned conflicting or vendor-specific lock-state data."
        if interactive:
            detail += " Screen is interactive."
        elif asleep:
            detail += " Screen is not interactive."

        return "unknown", detail, {
            "locked_hits": locked_hits,
            "unlocked_hits": unlocked_hits,
            "interactive": interactive,
            "asleep": asleep,
        }

    def lock_state_test(self):
        self.set_footer("Checking Android lock state...")

        def worker():
            state, detail, evidence = self._android_lock_state()

            locked_hits = ", ".join(evidence.get("locked_hits", [])) or "none"
            unlocked_hits = ", ".join(evidence.get("unlocked_hits", [])) or "none"

            if state == "locked":
                message = (
                    "TEST RESULT: LOCKED\n\n"
                    + detail
                    + f"\n\nLocked markers: {locked_hits}"
                )
            elif state == "unlocked":
                message = (
                    "TEST RESULT: UNLOCKED\n\n"
                    + detail
                    + f"\n\nUnlocked markers: {unlocked_hits}"
                )
            else:
                message = (
                    "TEST RESULT: UNKNOWN\n\n"
                    + detail
                    + f"\n\nLocked markers: {locked_hits}"
                    + f"\nUnlocked markers: {unlocked_hits}"
                    + "\n\nThis phone does not expose a reliable single lock flag through standard ADB dumpsys output."
                )

            self.bridge.screen_result.emit(message)
            self.bridge.message.emit("Lock-state test complete.")

        threading.Thread(target=worker, daemon=True).start()

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
