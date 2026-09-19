import sys
import re
import urllib.request
import shutil
import subprocess
import ctypes
import math
import wave
import struct
import signal
import socket
import os
import json
import hashlib
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QListWidget,
    QMenu,
    QSystemTrayIcon,
    QStyle,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from PhoneHub import (
    PhoneHub,
    READABLE_SCREEN,
    connect_remote_adb,
    get_saved_ip,
    save_phone_ip,
    parse_adb_devices,
    run_quiet,
    run_background,
    scrcpy_path,
)
from phone_config import normalize_tailscale_ipv4

APP_VERSION = "v3.42-stable-unlock-recovery"
TAILSCALE_PACKAGE = "com.tailscale.ipn"
TAILSCALE_STABLE_PAGE = "https://pkgs.tailscale.com/stable/"
TAILSCALE_BASE_URL = "https://pkgs.tailscale.com/stable/"
TAILSCALE_APK_DIR = Path(r"C:\\PhoneHub\\runtime\\downloads")
LOCAL_APK_DIR = Path(r"C:\\PhoneHub\\apps")


class AutoDetectBridge(QObject):
    state = Signal(dict)
    wizard = Signal(dict)
    health = Signal(dict)
    notifications = Signal(list)
    notification_push = Signal(dict)
    screen_recovery = Signal(bool)
    screen_guard = Signal(bool)

class PhoneHubTailscale(PhoneHub):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PhoneHub {APP_VERSION}")

        # Automatically detect USB/remote connection changes so the Setup page
        # changes to Connected without requiring the user to press Smart Check.
        self._last_connection_signature = None
        self._auto_unlock_waiting = False
        self._auto_unlock_serial = ""
        self._auto_detect_busy = False

        self.auto_bridge = AutoDetectBridge()
        self.auto_bridge.screen_recovery.connect(self._finish_screen_recovery)
        self.auto_bridge.screen_guard.connect(self._screen_adb_guard_done)
        self.auto_bridge.state.connect(self._apply_auto_detect_state)
        self.auto_bridge.wizard.connect(self._apply_wizard_result)
        self.auto_bridge.health.connect(self._apply_health_results)
        self.auto_bridge.notifications.connect(self._apply_notification_results)
        self.auto_bridge.notification_push.connect(self._apply_companion_notification)

        self.wizard_step = 1
        self.wizard_serial = ""
        self.wizard_detected_ip = ""
        self.wizard_remote_connected = False
        self._wizard_busy = False
        self._health_busy = False
        self.audio_process = None
        self.audio_recording = False
        self.audio_record_path = ""
        self.audio_source = "mic-voice-communication"
        self.audio_log_handle = None
        self.audio_log_path = ""
        self.audio_buffer_ms = 50
        self.audio_output_buffer_ms = 10
        self.audio_codec = "aac"
        self.audio_bit_rate = "128K"
        self.audio_dup = False
        self.audio_no_playback = False
        self.audio_listen_requested = False
        self.audio_monitor_window = None
        self.audio_monitor_status = None
        self._call_was_active = False
        self.audio_level_text = "Level: No recording analyzed yet"

        self.notification_feed_enabled = True
        self.notification_poll_busy = False
        self.notification_seen = set()
        self.notification_baseline_ready = False
        self.notification_items = []
        self.notification_filter = "all"
        self.notification_store = Path(r"C:\PhoneHub\runtime\notifications\feed.jsonl")
        self.notification_store.parent.mkdir(parents=True, exist_ok=True)
        self.notification_token_file = self.notification_store.parent / "pairing_token.txt"
        self.notification_pairing_token = self._load_or_create_notification_token()
        self.notification_receiver_server = None
        self.notification_receiver_thread = None
        self.notification_receiver_url = ""
        self.screen_profile_name = "Balanced"
        self.screen_profile_args = ["--max-size=1024", "--video-bit-rate=4M", "--max-fps=30", "--video-codec=h264", "--video-buffer=100", "--no-audio"]
        self._force_exit = False
        self.tray_icon = None

        # Keep a remote screen session alive across short ADB/Tailscale drops
        # that can happen while Android changes lock/unlock state.
        self._screen_session_requested = False
        self._screen_recovery_busy = False
        self._screen_recovery_attempts = 0
        self._screen_last_args = []
        self._screen_log_handle = None
        self._screen_log_path = Path(r"C:\PhoneHub\logs\scrcpy_screen.log")
        self._screen_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.screen_watchdog_timer = QTimer(self)
        self.screen_watchdog_timer.setInterval(1000)
        self.screen_watchdog_timer.timeout.connect(self._screen_watchdog)
        self.screen_watchdog_timer.start()

        # Some Android ROMs briefly drop TCP ADB when the secure lock screen
        # changes state. Keep an independent remote-ADB heartbeat while a screen
        # session is requested, so recovery is based on a real shell probe
        # instead of stale 'adb devices' state.
        self._screen_adb_guard_busy = False
        self._screen_adb_failures = 0
        self.screen_adb_guard_timer = QTimer(self)
        self.screen_adb_guard_timer.setInterval(1200)
        self.screen_adb_guard_timer.timeout.connect(self._screen_adb_guard_tick)
        self.screen_adb_guard_timer.start()

        self.app_status_timer = QTimer(self)
        self.app_status_timer.setSingleShot(True)
        self.app_status_timer.setInterval(500)
        self.app_status_timer.timeout.connect(self.check_selected_app_status)

        # Detection now runs in a background thread. The old implementation ran
        # several adb commands on the UI thread every 3 seconds, which caused
        # visible freezing/slowness.
        self.connection_timer = QTimer(self)
        self.connection_timer.setInterval(7000)
        self.connection_timer.timeout.connect(self.auto_refresh_connection_state)
        self.connection_timer.start()
        QTimer.singleShot(700, self.auto_refresh_connection_state)

        self.unlock_timer = QTimer(self)
        self.unlock_timer.setInterval(2500)
        self.unlock_timer.timeout.connect(self._check_unlock_progress)

        self.call_monitor_timer = QTimer(self)
        self.call_monitor_timer.setInterval(2000)
        self.call_monitor_timer.timeout.connect(self._monitor_call_audio_state)
        self.call_monitor_timer.start()

        self.notification_timer = QTimer(self)
        self.notification_timer.setInterval(8000)
        self.notification_timer.timeout.connect(self.poll_notifications)
        self.notification_timer.start()
        QTimer.singleShot(1800, self.poll_notifications)

        self._setup_system_tray()
        QTimer.singleShot(1200, self.start_notification_receiver)

        # Keep the window inside the visible desktop area on smaller laptops.
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            width = min(980, max(760, int(area.width() * 0.92)))
            height = min(640, max(520, int(area.height() * 0.88)))
            self.resize(width, height)

    def build_ui(self):
        """Compact PhoneHub shell.

        All existing PhoneHub functions are preserved, but every content page is
        placed inside a scroll area so controls at the bottom remain reachable on
        short laptop screens.
        """
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(176)

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(8)

        logo = QLabel("PhoneHub")
        logo.setObjectName("logo")
        side.addWidget(logo)

        sub = QLabel("Private Device Control")
        sub.setObjectName("muted")
        side.addWidget(sub)

        self.stack = QStackedWidget()
        self.nav_buttons = []

        pages = [
            ("Home", self.page_dashboard),
            ("Setup", self.page_setup_new_phone),
            ("Screen", self.page_screen),
            ("Camera", self.page_camera),
            ("Files", self.page_files),
            ("Protection", self.page_security),
        ]

        for index, (name, builder) in enumerate(pages):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            btn.setMinimumHeight(38)
            side.addWidget(btn)
            self.nav_buttons.append(btn)

            page = builder()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)

        side.addStretch()

        self.side_status = QLabel("Checking")
        self.side_status.setObjectName("sideStatus")
        self.side_status.setWordWrap(True)
        side.addWidget(self.side_status)

        main_wrap = QVBoxLayout()
        main_wrap.setContentsMargins(0, 0, 0, 0)
        main_wrap.setSpacing(8)
        main_wrap.addWidget(self.stack, 1)

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        self.footer.setWordWrap(False)
        self.footer.setMaximumHeight(24)
        main_wrap.addWidget(self.footer)

        root.addWidget(sidebar)
        root.addLayout(main_wrap, 1)

        self.show_page(0)

        self.setStyleSheet("""
            QWidget {
                background: #07111f;
                color: #f8fafc;
                font-family: Segoe UI;
                font-size: 13px;
            }

            QFrame#sidebar, QFrame#card {
                background: #0d1b2d;
                border: 1px solid #1f3654;
                border-radius: 11px;
            }

            QLabel#logo {
                font-size: 22px;
                font-weight: 900;
            }

            QLabel#title {
                font-size: 18px;
                font-weight: 800;
                color: #e0f2fe;
            }

            QLabel#muted, QLabel#footer {
                color: #94a3b8;
            }

            QLabel#big {
                font-size: 13px;
                color: #dbeafe;
            }

            QLabel#sideStatus {
                color: #86efac;
                font-weight: 800;
            }

            QPushButton {
                background: #13243a;
                color: #f8fafc;
                border: 1px solid #254363;
                border-radius: 8px;
                padding: 7px 9px;
                font-weight: 700;
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
                font-size: 13px;
                padding: 9px;
            }

            QPushButton#danger {
                background: #991b1b;
                border: none;
            }

            QTextEdit {
                background: #06101d;
                color: #dbeafe;
                border: 1px solid #1f3654;
                border-radius: 8px;
                padding: 7px;
            }

            QLineEdit {
                background: #06101d;
                color: #ffffff;
                border: 1px solid #1f3654;
                border-radius: 8px;
                padding: 8px;
                font-size: 14px;
            }

            QScrollArea {
                border: none;
                background: transparent;
            }

            QScrollBar:vertical {
                background: #07111f;
                width: 10px;
                margin: 2px;
            }

            QScrollBar::handle:vertical {
                background: #334155;
                min-height: 28px;
                border-radius: 5px;
            }
        """)

    def card(self, title, text=""):
        box = QFrame()
        box.setObjectName("card")

        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        t = QLabel(title)
        t.setObjectName("title")
        lay.addWidget(t)

        lbl = QLabel(text)
        lbl.setObjectName("big")
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lbl)

        return box, lay, lbl

    def _close_screen_log(self):
        handle = getattr(self, "_screen_log_handle", None)
        if handle:
            try:
                handle.flush()
                handle.close()
            except Exception:
                pass
        self._screen_log_handle = None

    def _screen_error_tail(self):
        try:
            if self._screen_log_handle:
                self._screen_log_handle.flush()
            if not self._screen_log_path.exists():
                return ""
            lines = self._screen_log_path.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines()
            useful = [line.strip() for line in lines[-25:] if line.strip()]
            return useful[-1] if useful else ""
        except Exception:
            return ""

    def _launch_screen_process(self, profile, wake=False):
        scrcpy = scrcpy_path()
        if not scrcpy:
            self.set_footer("scrcpy not found.")
            return False

        target = self._device_target()
        if not target:
            self.set_footer("Phone remote ADB is not connected.")
            return False

        if wake:
            run_background([
                "adb", "-s", target, "shell", "input", "keyevent", "224"
            ])

        args = [scrcpy, "-s", target] + list(profile)

        self._close_screen_log()
        try:
            self._screen_log_handle = self._screen_log_path.open(
                "a", encoding="utf-8", buffering=1
            )
            self._screen_log_handle.write(
                f"\n[{datetime.now().isoformat(timespec='seconds')}] "
                f"START target={target} args={' '.join(args[3:])}\n"
            )
            self._screen_log_handle.flush()
            self.screen_process = subprocess.Popen(
                args,
                stdout=self._screen_log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if sys.platform.startswith("win") else 0
                ),
            )
        except Exception as exc:
            self._close_screen_log()
            self.screen_process = None
            self.set_footer(f"Could not open screen: {exc}")
            return False

        self.current_view = "screen"
        return True

    def open_screen(self, profile, keep_alive=False):
        # One screen session at a time. The remote Tailscale ADB target is used
        # directly; USB is only a fallback inside _device_target().
        if self._proc_alive(getattr(self, "screen_process", None)):
            self.set_footer("Screen already open.")
            return

        self._screen_session_requested = True
        self._screen_last_args = list(profile)
        self._screen_recovery_attempts = 0
        self._screen_recovery_busy = False

        if self._launch_screen_process(profile, wake=True):
            self.set_footer("Opening screen...")
        else:
            # Leave the session requested: the watchdog will retry if the remote
            # ADB transport is temporarily unavailable.
            self.set_footer("Screen start failed. Retrying remote connection...")

    def disconnect_screen(self):
        # This is the only action that intentionally disables auto-recovery.
        self._screen_session_requested = False
        self._screen_recovery_busy = False
        self._screen_recovery_attempts = 0

        proc = getattr(self, "screen_process", None)
        self._stop_proc(proc)
        self.screen_process = None
        self._close_screen_log()

        if self.current_view == "screen":
            self.current_view = ""
        self.set_footer("Screen disconnected.")

    def _screen_remote_target(self):
        ip, port = get_saved_ip()
        return f"{ip}:{port}" if ip else ""

    def _screen_adb_guard_tick(self):
        if not getattr(self, "_screen_session_requested", False):
            self._screen_adb_failures = 0
            return
        if getattr(self, "_screen_adb_guard_busy", False):
            return
        if getattr(self, "_screen_recovery_busy", False):
            return

        target = self._screen_remote_target()
        if not target:
            return

        self._screen_adb_guard_busy = True

        def worker():
            # A real shell round-trip is the health check. 'adb devices' can
            # temporarily report a transport as present even when it can no
            # longer carry commands.
            probe = run_quiet(
                ["adb", "-s", target, "shell", "echo", "PHONEHUB_OK"],
                timeout=3,
            ).strip()
            ok = probe == "PHONEHUB_OK"

            if not ok:
                run_quiet(["adb", "disconnect", target], timeout=3)
                run_quiet(["adb", "connect", target], timeout=5)
                probe = run_quiet(
                    ["adb", "-s", target, "shell", "echo", "PHONEHUB_OK"],
                    timeout=3,
                ).strip()
                ok = probe == "PHONEHUB_OK"

            self.auto_bridge.screen_guard.emit(ok)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _screen_adb_guard_done(self, ok):
        self._screen_adb_guard_busy = False

        if ok:
            self._screen_adb_failures = 0
            return

        self._screen_adb_failures += 1
        if self._screen_adb_failures == 1:
            self.set_footer("Wireless ADB changed during lock/unlock. Waiting for it to stabilize...")

    def _screen_watchdog(self):
        if not getattr(self, "_screen_session_requested", False):
            return
        if getattr(self, "_screen_recovery_busy", False):
            return

        proc = getattr(self, "screen_process", None)

        # A running scrcpy process is healthy from PhoneHub's point of view.
        if proc is not None and proc.poll() is None:
            return

        exit_code = proc.poll() if proc is not None else None

        # Closing the scrcpy window normally returns 0. Do not reopen it.
        if proc is not None and exit_code == 0:
            self._screen_session_requested = False
            self.screen_process = None
            self._close_screen_log()
            self.set_footer("Screen closed.")
            return

        self.screen_process = None
        self._close_screen_log()

        if self._screen_recovery_attempts >= 5:
            self._screen_session_requested = False
            detail = self._screen_error_tail()
            self.set_footer(
                "Screen could not recover."
                + (f" scrcpy: {detail}" if detail else "")
            )
            return

        self._screen_recovery_attempts += 1
        self._screen_recovery_busy = True
        self.set_footer(
            f"Screen stream dropped. Recovering "
            f"({self._screen_recovery_attempts}/5)..."
        )

        def worker():
            ip, port = get_saved_ip()
            target = f"{ip}:{port}" if ip else ""
            if not target:
                self.auto_bridge.screen_recovery.emit(False)
                return

            # Android/OxygenOS may restart wireless adbd during secure
            # lock/unlock. Do not reopen scrcpy on the first transient success.
            # Require two consecutive working shell round-trips first.
            stable_hits = 0
            for attempt in range(8):
                probe = run_quiet(
                    ["adb", "-s", target, "shell", "echo", "PHONEHUB_OK"],
                    timeout=3,
                ).strip()

                if probe == "PHONEHUB_OK":
                    stable_hits += 1
                    if stable_hits >= 2:
                        self.auto_bridge.screen_recovery.emit(True)
                        return
                else:
                    stable_hits = 0
                    run_quiet(["adb", "disconnect", target], timeout=2)
                    run_quiet(["adb", "connect", target], timeout=4)

                import time
                time.sleep(0.55)

            self.auto_bridge.screen_recovery.emit(False)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _finish_screen_recovery(self, connected):
        # This signal is used by both the screen watchdog and the wireless-ADB
        # guard. Always clear both busy flags safely.
        self._screen_recovery_busy = False
        self._screen_adb_guard_busy = False

        if not self._screen_session_requested:
            return

        if not connected:
            self._screen_adb_failures += 1
            self.set_footer("Wireless ADB unavailable. Retrying...")
            return

        self._screen_adb_failures = 0

        # If scrcpy is already running, the ADB guard has done its job.
        if self._proc_alive(getattr(self, "screen_process", None)):
            return

        args = list(getattr(self, "_screen_last_args", []))
        if not args:
            args = [
                "--max-size=1024",
                "--video-bit-rate=4M",
                "--max-fps=30",
                "--video-codec=h264",
                "--video-buffer=100",
                "--no-audio",
            ]

        # Give the ROM a short moment after ADB comes back, then launch scrcpy.
        QTimer.singleShot(
            900, lambda a=args: self._restart_screen_after_reconnect(a)
        )

    def _restart_screen_after_reconnect(self, args):
        if not self._screen_session_requested:
            return
        if self._proc_alive(getattr(self, "screen_process", None)):
            return

        if self._launch_screen_process(args, wake=False):
            # Verify that scrcpy survives startup before declaring recovery.
            QTimer.singleShot(900, self._verify_recovered_screen)
        else:
            self.set_footer("scrcpy restart failed. Retrying...")

    def _verify_recovered_screen(self):
        proc = getattr(self, "screen_process", None)
        if self._proc_alive(proc):
            self._screen_recovery_attempts = 0
            self.set_footer("Screen reconnected.")
            return

        # Keep session requested. The watchdog will retry and preserve the log.
        code = proc.poll() if proc is not None else "?"
        self.set_footer(f"scrcpy restart exited ({code}). Retrying...")

    def page_screen(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        main_box, main_layout, _ = self.card(
            "Screen Control",
            "Open and control your phone through the private Tailscale connection.",
        )

        row = QHBoxLayout()

        open_btn = QPushButton("Open Screen")
        open_btn.setObjectName("primary")
        open_btn.setMinimumHeight(46)
        open_btn.clicked.connect(self.open_selected_screen_profile)

        screen_off = QPushButton("Open + Phone Screen Off")
        screen_off.clicked.connect(self.open_screen_phone_off)

        close_btn = QPushButton("Disconnect")
        close_btn.setObjectName("danger")
        close_btn.clicked.connect(self.disconnect_screen)

        row.addWidget(open_btn, 2)
        row.addWidget(screen_off, 2)
        row.addWidget(close_btn, 1)
        main_layout.addLayout(row)
        layout.addWidget(main_box)

        tools_box, tools_layout, _ = self.card(
            "Essential Controls",
            "Only the controls needed during normal remote use.",
        )

        tools = QHBoxLayout()

        shot = QPushButton("Screenshot")
        shot.clicked.connect(self.screenshot_async)

        wake = QPushButton("Wake")
        wake.clicked.connect(self.wake_phone)

        lock = QPushButton("Lock")
        lock.clicked.connect(self.lock_phone)

        home = QPushButton("Home")
        home.clicked.connect(lambda: self.screen_adb_key("3", "Home"))

        back = QPushButton("Back")
        back.clicked.connect(lambda: self.screen_adb_key("4", "Back"))

        tools.addWidget(shot)
        tools.addWidget(wake)
        tools.addWidget(lock)
        tools.addWidget(home)
        tools.addWidget(back)
        tools_layout.addLayout(tools)

        layout.addWidget(tools_box)
        layout.addStretch()
        return page

    def page_files(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        box, box_layout, _ = self.card(
            "PhoneHub Files",
            "Keep PhoneHub captures and evidence organized. No location-history tools are shown.",
        )

        row = QHBoxLayout()

        screenshots = QPushButton("Open Screenshots")
        screenshots.setObjectName("primary")
        screenshots.clicked.connect(self.open_screenshots)

        evidence = QPushButton("Open Protection Evidence")
        evidence.clicked.connect(self.open_security_evidence)

        row.addWidget(screenshots)
        row.addWidget(evidence)
        box_layout.addLayout(row)

        layout.addWidget(box)
        layout.addStretch()
        return page

    def set_screen_profile(self, name, args, description):
        self.screen_profile_name = name
        self.screen_profile_args = list(args)
        if hasattr(self, "screen_profile_label"):
            self.screen_profile_label.setText(f"Profile: {name} · {description}")
        self.set_footer(f"Screen profile set to {name}.")

    def open_selected_screen_profile(self):
        args = list(getattr(
            self,
            "screen_profile_args",
            ["--max-size=1024", "--video-bit-rate=4M", "--max-fps=30", "--video-codec=h264", "--video-buffer=100", "--no-audio"],
        ))
        if "--no-audio" not in args:
            args.append("--no-audio")
        self.open_screen(args, keep_alive=True)

    def open_screen_phone_off(self):
        args = list(getattr(
            self,
            "screen_profile_args",
            ["--max-size=1024", "--video-bit-rate=4M", "--max-fps=30", "--video-codec=h264", "--video-buffer=100", "--no-audio"],
        ))
        if "--no-audio" not in args:
            args.append("--no-audio")
        args.extend(["--turn-screen-off", "--keep-active"])
        self.open_screen(args, keep_alive=True)

    def _screen_target(self):
        return self._device_target()

    def screen_adb_key(self, keycode, label):
        target = self._screen_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return
        run_background(["adb", "-s", target, "shell", "input", "keyevent", str(keycode)])
        self.set_footer(f"{label} sent.")

    def expand_android_notifications(self):
        target = self._screen_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return
        run_background(["adb", "-s", target, "shell", "cmd", "statusbar", "expand-notifications"])
        self.set_footer("Android notification shade opened.")

    def collapse_android_notifications(self):
        target = self._screen_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return
        run_background(["adb", "-s", target, "shell", "cmd", "statusbar", "collapse"])
        self.set_footer("Android notification shade collapsed.")

    def screen_list_encoders(self):
        scrcpy = scrcpy_path()
        if not scrcpy:
            self.set_footer("scrcpy not found.")
            return
        output = run_quiet([scrcpy, "--list-encoders"], timeout=15)
        if hasattr(self, "screen_diagnostics"):
            self.screen_diagnostics.setText(output or "No encoder information returned.")
        self.set_footer("Encoder list refreshed.")

    def screen_list_displays(self):
        scrcpy = scrcpy_path()
        if not scrcpy:
            self.set_footer("scrcpy not found.")
            return
        output = run_quiet([scrcpy, "--list-displays"], timeout=12)
        if hasattr(self, "screen_diagnostics"):
            self.screen_diagnostics.setText(output or "No display information returned.")
        self.set_footer("Display list refreshed.")

    def screen_fps_test(self):
        scrcpy = scrcpy_path()
        target = self._screen_target()
        if not scrcpy or not target:
            self.set_footer("scrcpy or phone connection unavailable.")
            return

        args = [
            scrcpy, "--serial", target,
            "--max-size=720",
            "--video-codec=h264",
            "--video-bit-rate=2M",
            "--max-fps=30",
            "--video-buffer=100",
            "--print-fps",
            "--window-title=PhoneHub FPS Test",
        ]
        try:
            subprocess.Popen(args)
            if hasattr(self, "screen_diagnostics"):
                self.screen_diagnostics.setText(
                    "FPS Test opened in a separate scrcpy window.\n"
                    "Close that test window when finished."
                )
            self.set_footer("FPS test started.")
        except Exception as exc:
            self.set_footer(f"FPS test failed: {exc}")

    def page_audio(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        box, box_layout, _ = self.card(
            "Phone Microphone",
            "Listen live to the microphone on your connected Android phone. "
            "Recording is optional and starts only when you press Record.",
        )

        self.audio_status = QLabel("Status: Idle")
        self.audio_status.setObjectName("sideStatus")
        self.audio_status.setWordWrap(True)
        box_layout.addWidget(self.audio_status)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        start_btn = QPushButton("Start Listening")
        start_btn.setObjectName("primary")
        start_btn.setMinimumHeight(44)
        start_btn.clicked.connect(self.start_live_audio)

        self.audio_record_button = QPushButton("Record")
        self.audio_record_button.setMinimumHeight(44)
        self.audio_record_button.clicked.connect(self.toggle_audio_recording)

        stop_btn = QPushButton("Stop")
        stop_btn.setMinimumHeight(44)
        stop_btn.clicked.connect(self.stop_live_audio)

        actions.addWidget(start_btn)
        actions.addWidget(self.audio_record_button)
        actions.addWidget(stop_btn)
        box_layout.addLayout(actions)

        echo_free_actions = QHBoxLayout()
        echo_free_actions.setSpacing(8)

        echo_free_record = QPushButton("Echo-Free Record")
        echo_free_record.setObjectName("primary")
        echo_free_record.clicked.connect(self.start_echo_free_recording)

        monitor_note = QLabel("For clear speech without delayed feedback: record with PC playback OFF.")
        monitor_note.setObjectName("big")
        monitor_note.setWordWrap(True)

        echo_free_actions.addWidget(echo_free_record)
        box_layout.addLayout(echo_free_actions)
        box_layout.addWidget(monitor_note)

        source_box, source_layout, _ = self.card(
            "Audio Source",
            "Choose what Android audio source PhoneHub should monitor.",
        )

        self.audio_source_combo = QComboBox()
        self.audio_source_combo.addItem("Clear Speech", "mic-voice-communication")
        self.audio_source_combo.addItem("Natural Mic", "mic")
        self.audio_source_combo.addItem("Raw Mic", "mic-unprocessed")
        self.audio_source_combo.addItem("Camera Mic", "mic-camcorder")
        self.audio_source_combo.addItem("Voice Recognition", "mic-voice-recognition")
        self.audio_source_combo.addItem("Phone Audio Output", "output")
        self.audio_source_combo.addItem("App Playback", "playback")
        self.audio_source_combo.addItem("Call - Other Side", "voice-call-downlink")
        self.audio_source_combo.addItem("Call - My Side", "voice-call-uplink")
        self.audio_source_combo.addItem("Call - Both", "voice-call")
        self.audio_source_combo.addItem("Voice Performance", "voice-performance")
        self.audio_source_combo.currentIndexChanged.connect(self.on_audio_source_changed)
        source_layout.addWidget(self.audio_source_combo)

        source_row = QHBoxLayout()
        dup_btn = QPushButton("Playback + Keep Sound on Phone")
        dup_btn.clicked.connect(self.toggle_audio_dup)

        encoders_btn = QPushButton("List Audio Encoders")
        encoders_btn.clicked.connect(self.list_audio_encoders)

        source_row.addWidget(dup_btn)
        source_row.addWidget(encoders_btn)
        source_layout.addLayout(source_row)

        self.audio_encoder_info = QLabel("Encoder: Auto")
        self.audio_encoder_info.setObjectName("big")
        self.audio_encoder_info.setWordWrap(True)
        source_layout.addWidget(self.audio_encoder_info)
        box_layout.addWidget(source_box)

        quality_box, quality_layout, _ = self.card(
            "Audio Quality",
            "AAC is the safest Windows-compatible default. Opus, FLAC and RAW are available for testing.",
        )

        quality_row = QHBoxLayout()
        self.audio_codec_combo = QComboBox()
        self.audio_codec_combo.addItem("AAC", "aac")
        self.audio_codec_combo.addItem("Opus", "opus")
        self.audio_codec_combo.addItem("FLAC", "flac")
        self.audio_codec_combo.addItem("RAW", "raw")
        self.audio_codec_combo.currentIndexChanged.connect(self.on_audio_codec_changed)

        q96 = QPushButton("Voice 96K")
        q96.clicked.connect(lambda: self.set_audio_quality("96K"))
        q128 = QPushButton("Standard 128K")
        q128.setObjectName("primary")
        q128.clicked.connect(lambda: self.set_audio_quality("128K"))
        q192 = QPushButton("High 192K")
        q192.clicked.connect(lambda: self.set_audio_quality("192K"))

        quality_row.addWidget(self.audio_codec_combo)
        quality_row.addWidget(q96)
        quality_row.addWidget(q128)
        quality_row.addWidget(q192)
        quality_layout.addLayout(quality_row)

        self.audio_quality_label = QLabel("Quality: AAC · 128K")
        self.audio_quality_label.setObjectName("big")
        quality_layout.addWidget(self.audio_quality_label)
        box_layout.addWidget(quality_box)

        latency_box, latency_layout, _ = self.card(
            "Latency / Stability",
            "Use Low for responsiveness, Balanced for normal listening, and Stable/Smooth if audio breaks up.",
        )

        latency_row = QHBoxLayout()
        low = QPushButton("Low 40ms")
        low.clicked.connect(lambda: self.set_audio_latency(40, "Low"))
        balanced = QPushButton("Balanced 50ms")
        balanced.setObjectName("primary")
        balanced.clicked.connect(lambda: self.set_audio_latency(50, "Balanced"))
        stable = QPushButton("Stable 100ms")
        stable.clicked.connect(lambda: self.set_audio_latency(100, "Stable"))
        smooth = QPushButton("Smooth 200ms")
        smooth.clicked.connect(lambda: self.set_audio_latency(200, "Smooth"))

        latency_row.addWidget(low)
        latency_row.addWidget(balanced)
        latency_row.addWidget(stable)
        latency_row.addWidget(smooth)
        latency_layout.addLayout(latency_row)

        self.audio_latency_label = QLabel("Latency: Balanced · 50 ms stream · 10 ms output")
        self.audio_latency_label.setObjectName("big")
        latency_layout.addWidget(self.audio_latency_label)
        box_layout.addWidget(latency_box)

        voice_actions = QHBoxLayout()
        voice_actions.setSpacing(8)

        anti_echo = QPushButton("Anti Echo")
        anti_echo.setObjectName("primary")
        anti_echo.clicked.connect(self.set_anti_echo_mode)

        clear_voice = QPushButton("Clear Voice")
        clear_voice.setObjectName("primary")
        clear_voice.clicked.connect(lambda: self.set_audio_source("mic-voice-communication", "Clear Voice"))

        natural_voice = QPushButton("Natural Mic")
        natural_voice.clicked.connect(lambda: self.set_audio_source("mic", "Natural Mic"))

        voice_actions.addWidget(anti_echo)
        voice_actions.addWidget(clear_voice)
        voice_actions.addWidget(natural_voice)
        box_layout.addLayout(voice_actions)

        call_actions = QHBoxLayout()
        call_actions.setSpacing(8)

        open_dialer = QPushButton("Open Dialer")
        open_dialer.setObjectName("primary")
        open_dialer.clicked.connect(self.open_phone_dialer)

        call_both = QPushButton("Call Both")
        call_both.clicked.connect(lambda: self.set_audio_source("voice-call", "Call Both"))

        call_other = QPushButton("Other Side")
        call_other.clicked.connect(lambda: self.set_audio_source("voice-call-downlink", "Call Other Side"))

        call_me = QPushButton("My Side")
        call_me.clicked.connect(lambda: self.set_audio_source("voice-call-uplink", "Call My Side"))

        call_actions.addWidget(open_dialer)
        call_actions.addWidget(call_both)
        call_actions.addWidget(call_other)
        call_actions.addWidget(call_me)
        box_layout.addLayout(call_actions)

        self.call_test_note = QLabel(
            "Call test: first press Open Dialer, place or answer the call on the phone, then choose Call Both / Other Side / My Side and press Start Listening. "
            "These buttons select the audio source; they do not place the call themselves. PhoneHub stops call audio automatically when the call ends."
        )
        self.call_test_note.setObjectName("big")
        self.call_test_note.setWordWrap(True)
        box_layout.addWidget(self.call_test_note)

        self.audio_mode_label = QLabel("Voice mode: Clear Speech · Android voice processing · Balanced buffer")
        self.audio_mode_label.setObjectName("big")
        self.audio_mode_label.setWordWrap(True)
        box_layout.addWidget(self.audio_mode_label)

        self.audio_record_file = QLabel("Recording file: None")
        self.audio_record_file.setObjectName("big")
        self.audio_record_file.setWordWrap(True)
        self.audio_record_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box_layout.addWidget(self.audio_record_file)

        self.audio_level_label = QLabel("Level: No recording analyzed yet")
        self.audio_level_label.setObjectName("big")
        self.audio_level_label.setWordWrap(True)
        box_layout.addWidget(self.audio_level_label)

        level_actions = QHBoxLayout()
        level_actions.setSpacing(8)

        analyze_btn = QPushButton("Analyze Last Recording")
        analyze_btn.clicked.connect(self.analyze_last_audio_recording)

        vol_down = QPushButton("Volume -")
        vol_down.clicked.connect(lambda: self.adjust_windows_volume(-3))

        vol_up = QPushButton("Volume +")
        vol_up.clicked.connect(lambda: self.adjust_windows_volume(3))

        mixer = QPushButton("Volume Mixer")
        mixer.clicked.connect(self.open_windows_volume_mixer)

        level_actions.addWidget(analyze_btn)
        level_actions.addWidget(vol_down)
        level_actions.addWidget(vol_up)
        level_actions.addWidget(mixer)
        box_layout.addLayout(level_actions)

        open_folder = QPushButton("Open Recordings Folder")
        open_folder.clicked.connect(self.open_audio_recordings_folder)
        box_layout.addWidget(open_folder)

        layout.addWidget(box)

        info, _, _ = self.card(
            "How it works",
            "Clear Speech is the recommended voice mode. It uses Android voice-communication processing when available. "
            "Balanced audio uses 50 ms stream buffering and scrcpy's normal 10 ms output buffer. "

            "For active calls, try Other Side first. Call Both may sound doubled or echo-like on some phones because it includes both uplink and downlink paths. "
            "Call Both / Other Side / My Side use Android call-audio sources when the device permits it. "
            "This can reduce delayed echo and may use Android echo cancellation / automatic gain control when supported. "
            "Natural Mic uses the raw normal microphone path. When Record is enabled, "
            "PhoneHub restarts the same selected microphone stream with scrcpy recording enabled and saves "
            "an AAC/M4A audio file under C:\\PhoneHub\\runtime\\audio. "
            "Press Record again to stop recording while continuing live listening. "
            "Live listening always has some transport delay. If the phone microphone hears the PC speaker, that delayed sound returns as echo. "
            "Echo-Free Record disables PC audio playback while recording, which removes that feedback path and gives the cleanest saved speech. "
            "For live monitoring, use headphones on the PC. "
            "Recordings are saved as AAC audio in an M4A container for Windows playback. PhoneHub now stops scrcpy gracefully so the file is finalized correctly. Peak analysis uses FFmpeg when available.",
        )
        layout.addWidget(info)
        layout.addStretch()
        return page

    def set_anti_echo_mode(self):
        self.audio_source = "mic-voice-communication"
        self.audio_buffer_ms = 40
        self.audio_output_buffer_ms = 10

        if hasattr(self, "audio_mode_label"):
            self.audio_mode_label.setText(
                "Voice mode: Clear Speech · 40 ms stream · 10 ms output · Android voice processing"
            )

        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            was_recording = getattr(self, "audio_recording", False)
            record_path = self.audio_record_path if was_recording else ""
            self._stop_audio_process_only()
            self.set_footer("Applying Anti Echo mode...")
            self._launch_live_audio(record_path)
        else:
            self.set_footer("Anti Echo mode selected.")

    def on_audio_source_changed(self):
        if not hasattr(self, "audio_source_combo"):
            return
        source = self.audio_source_combo.currentData()
        label = self.audio_source_combo.currentText()
        if source:
            self.set_audio_source(source, label)

    def on_audio_codec_changed(self):
        if not hasattr(self, "audio_codec_combo"):
            return
        codec = self.audio_codec_combo.currentData()
        if codec:
            self.audio_codec = codec
            if hasattr(self, "audio_quality_label"):
                rate = "PCM" if codec == "raw" else self.audio_bit_rate
                self.audio_quality_label.setText(f"Quality: {codec.upper()} · {rate}")
            self.set_footer(f"Audio codec set to {codec.upper()}.")

    def set_audio_quality(self, bit_rate):
        self.audio_bit_rate = bit_rate
        if hasattr(self, "audio_quality_label"):
            codec = getattr(self, "audio_codec", "aac")
            rate = "PCM" if codec == "raw" else bit_rate
            self.audio_quality_label.setText(f"Quality: {codec.upper()} · {rate}")
        self.set_footer(f"Audio bitrate set to {bit_rate}.")

    def set_audio_latency(self, buffer_ms, label):
        self.audio_buffer_ms = int(buffer_ms)
        self.audio_output_buffer_ms = 10
        if hasattr(self, "audio_latency_label"):
            self.audio_latency_label.setText(
                f"Latency: {label} · {buffer_ms} ms stream · 10 ms output"
            )

        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            was_recording = getattr(self, "audio_recording", False)
            record_path = self.audio_record_path if was_recording else ""
            self._stop_audio_process_only()
            self._launch_live_audio(record_path)
        self.set_footer(f"Audio latency preset: {label}.")

    def toggle_audio_dup(self):
        self.audio_dup = not getattr(self, "audio_dup", False)
        if self.audio_dup:
            self.audio_source = "playback"
            if hasattr(self, "audio_source_combo"):
                index = self.audio_source_combo.findData("playback")
                if index >= 0:
                    self.audio_source_combo.blockSignals(True)
                    self.audio_source_combo.setCurrentIndex(index)
                    self.audio_source_combo.blockSignals(False)
            self.set_footer("Audio duplication ON: playback stays on the phone when Android/app permits it.")
        else:
            self.set_footer("Audio duplication OFF.")

        if hasattr(self, "audio_encoder_info"):
            self.audio_encoder_info.setText(
                "Audio duplication: ON · Android 13+"
                if self.audio_dup else
                "Encoder: Auto · Audio duplication OFF"
            )

    def list_audio_encoders(self):
        scrcpy = scrcpy_path()
        if not scrcpy:
            self.set_footer("scrcpy not found.")
            return

        output = run_quiet([scrcpy, "--list-encoders"], timeout=12)
        lines = [
            line.strip() for line in output.splitlines()
            if "audio" in line.lower() or "opus" in line.lower() or "aac" in line.lower() or "flac" in line.lower()
        ]
        shown = "\n".join(lines[:12]) if lines else (output[:1200] or "No encoder information returned.")
        if hasattr(self, "audio_encoder_info"):
            self.audio_encoder_info.setText(shown)
        self.set_footer("Audio encoder list refreshed.")

    def open_phone_dialer(self):
        target = self._audio_target()
        if not target:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Error — phone is not connected")
            self.set_footer("Connect the phone first, then open the dialer.")
            return

        result = run_quiet(
            ["adb", "-s", target, "shell", "am", "start", "-a", "android.intent.action.DIAL"],
            timeout=6,
        )
        if "error" in result.lower() or "exception" in result.lower():
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Dialer could not open")
            self.set_footer("Android did not allow PhoneHub to open the dialer.")
        else:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Dialer opened — start/answer the call on the phone")
            self.set_footer("Dialer opened. Place or answer the call, then select a call audio source.")

    def _android_call_state(self):
        source = getattr(self, "audio_source", "")
        if not source.startswith("voice-call"):
            return "not-call-mode"

        target = self._audio_target()
        if not target:
            return "unknown"

        text = run_quiet(
            ["adb", "-s", target, "shell", "dumpsys", "telephony.registry"],
            timeout=5,
        )

        # Android TelephonyManager: 0=IDLE, 1=RINGING, 2=OFFHOOK.
        matches = re.findall(r"mCallState\s*=\s*(\d+)", text)
        if matches:
            states = {int(v) for v in matches}
            if 2 in states or 1 in states:
                return "active"
            if states == {0}:
                return "idle"

        telecom = run_quiet(
            ["adb", "-s", target, "shell", "dumpsys", "telecom"],
            timeout=5,
        ).lower()
        if "isincall: true" in telecom or "mcallstate=2" in telecom or "state=active" in telecom:
            return "active"
        if "isincall: false" in telecom:
            return "idle"
        return "unknown"

    def _monitor_call_audio_state(self):
        source = getattr(self, "audio_source", "")
        if not source.startswith("voice-call"):
            self._call_was_active = False
            return

        if not getattr(self, "audio_listen_requested", False):
            return

        # Run the dumpsys checks away from the UI thread.
        def worker():
            state = self._android_call_state()
            QTimer.singleShot(0, lambda s=state: self._apply_call_state(s))

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_call_state(self, state):
        if state == "active":
            self._call_was_active = True
            return

        if state == "idle" and self._call_was_active:
            self._call_was_active = False
            self._stop_audio_process_only()
            self.audio_recording = False
            self.audio_no_playback = False
            if hasattr(self, "audio_record_button"):
                self.audio_record_button.setText("Record")
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Idle — call ended")
            self.set_footer("Call ended. Call audio stopped automatically.")

    def set_audio_source(self, source, label):
        self.audio_source = source
        if not source.startswith("voice-call"):
            self._call_was_active = False
        self.audio_output_buffer_ms = 10
        if hasattr(self, "audio_mode_label"):
            labels = {
                "mic-voice-communication": "Voice mode: Clear Voice + Low Echo",
                "mic": "Voice mode: Natural Mic",
                "voice-call": "Voice mode: Call Both Sides",
                "voice-call-downlink": "Voice mode: Call Other Side (downlink)",
                "voice-call-uplink": "Voice mode: Call My Side (uplink)",
            }
            self.audio_mode_label.setText(labels.get(source, f"Voice mode: {label}"))

        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            was_recording = getattr(self, "audio_recording", False)
            record_path = self.audio_record_path if was_recording else ""
            self._stop_audio_process_only()
            self.set_footer(f"Switching audio mode to {label}...")
            self._launch_live_audio(record_path)
        else:
            self.set_footer(f"Audio mode set to {label}.")

    def _audio_target(self):
        ip, port = get_saved_ip()
        target = f"{ip}:{port}" if ip else ""
        usb, remote, unauthorized, _ = parse_adb_devices()

        if target and target in remote:
            return target

        if target:
            run_quiet(["adb", "connect", target], timeout=6)
            usb, remote, unauthorized, _ = parse_adb_devices()
            if target in remote:
                return target

        if usb:
            return usb[0]
        return ""

    def _launch_live_audio(self, record_path=""):
        scrcpy = scrcpy_path()
        if not scrcpy:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Error — scrcpy not found")
            self.set_footer("scrcpy is required for live microphone audio.")
            return False

        help_text = run_quiet([scrcpy, "--help"], timeout=5)
        if "--audio-source" not in help_text:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Error — this scrcpy build does not support microphone audio")
            self.set_footer("Update scrcpy to use PhoneHub live audio.")
            return False

        target = self._audio_target()
        if not target:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Error — phone is not connected")
            self.set_footer("Connect the phone through USB or Tailscale ADB first.")
            return False

        args = [
            scrcpy,
            "--serial", target,
            f"--audio-source={getattr(self, 'audio_source', 'mic-voice-communication')}",
            "--no-video",
            "--no-control",
            f"--audio-buffer={getattr(self, 'audio_buffer_ms', 50)}",
            f"--audio-output-buffer={getattr(self, 'audio_output_buffer_ms', 10)}",
            f"--audio-codec={getattr(self, 'audio_codec', 'aac')}",
        ]

        if getattr(self, "audio_codec", "aac") != "raw":
            args.append(f"--audio-bit-rate={getattr(self, 'audio_bit_rate', '128K')}")

        if getattr(self, "audio_dup", False):
            args.append("--audio-dup")
        if record_path:
            args = [arg for arg in args if not arg.startswith("--audio-codec=") and not arg.startswith("--audio-bit-rate=")]
            args.extend([
                "--audio-codec=aac",
                "--audio-bit-rate=128K",
                "--require-audio",
                f"--record={record_path}",
            ])
            if getattr(self, "audio_no_playback", False):
                args.append("--no-audio-playback")

        log_dir = Path(r"C:\PhoneHub\runtime\logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        self.audio_log_path = str(log_dir / f"audio_{log_stamp}.log")

        try:
            if self.audio_log_handle:
                try:
                    self.audio_log_handle.close()
                except Exception:
                    pass
            self.audio_log_handle = open(self.audio_log_path, "w", encoding="utf-8", errors="ignore")
            self.audio_process = subprocess.Popen(
                args,
                stdout=self.audio_log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=(
                    (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
                    if sys.platform.startswith("win") else 0
                ),
            )
        except Exception as exc:
            self.audio_process = None
            if hasattr(self, "audio_status"):
                self.audio_status.setText(f"Status: Error — {exc}")
            self.set_footer("Could not start phone microphone audio.")
            return False

        if hasattr(self, "audio_status"):
            self.audio_status.setText(
                f"Status: Connecting + Recording — {target}"
                if record_path else
                f"Status: Connecting — {target}"
            )
        self.set_footer(
            "Starting live microphone recording..."
            if record_path else
            "Starting live phone microphone audio..."
        )
        QTimer.singleShot(1500, self._verify_live_audio)
        return True

    def _show_audio_monitor(self):
        if self.audio_monitor_window is None:
            win = QWidget()
            win.setWindowTitle("PhoneHub Audio Monitor")
            win.resize(430, 190)

            lay = QVBoxLayout(win)
            lay.setContentsMargins(18, 18, 18, 18)
            lay.setSpacing(12)

            title = QLabel("Live Phone Audio")
            title.setObjectName("title")
            lay.addWidget(title)

            self.audio_monitor_status = QLabel("Connecting...")
            self.audio_monitor_status.setWordWrap(True)
            lay.addWidget(self.audio_monitor_status)

            row = QHBoxLayout()
            down = QPushButton("Volume -")
            down.clicked.connect(lambda: self.adjust_windows_volume(-2))
            up = QPushButton("Volume +")
            up.clicked.connect(lambda: self.adjust_windows_volume(2))
            stop = QPushButton("Stop Listening")
            stop.setObjectName("danger")
            stop.clicked.connect(self.stop_live_audio)

            row.addWidget(down)
            row.addWidget(up)
            row.addWidget(stop)
            lay.addLayout(row)

            win.setStyleSheet(self.styleSheet())
            self.audio_monitor_window = win

        self.audio_monitor_window.show()
        self.audio_monitor_window.raise_()
        self.audio_monitor_window.activateWindow()

    def _set_audio_monitor_status(self, text):
        if self.audio_monitor_status is not None:
            self.audio_monitor_status.setText(text)

    def start_live_audio(self):
        self.audio_listen_requested = True
        self._show_audio_monitor()

        existing = getattr(self, "audio_process", None)
        if existing and existing.poll() is None:
            if hasattr(self, "audio_status"):
                self.audio_status.setText(
                    "Status: Listening + Recording"
                    if getattr(self, "audio_recording", False)
                    else "Status: Listening"
                )
            self._set_audio_monitor_status("Listening")
            self.set_footer("Phone microphone is already streaming.")
            return

        self.audio_recording = False

        source = getattr(self, "audio_source", "")
        if source.startswith("voice-call") and self._android_call_state() != "active":
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Waiting for active call")
            self._set_audio_monitor_status(
                "Waiting for an active call. Start or answer the call on the phone."
            )
            self.set_footer("Waiting for active call before starting call audio.")
            return

        self._set_audio_monitor_status("Connecting to phone audio...")
        self._launch_live_audio("")

    def _verify_live_audio(self):
        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            if hasattr(self, "audio_status"):
                self.audio_status.setText(
                    "Status: Listening + Recording"
                    if getattr(self, "audio_recording", False)
                    else "Status: Listening"
                )
            self._set_audio_monitor_status(
                "Listening + Recording"
                if getattr(self, "audio_recording", False)
                else "Listening"
            )
            self.set_footer(
                "Live microphone is playing and recording."
                if getattr(self, "audio_recording", False)
                else "Live phone microphone audio is playing on this PC."
            )
        else:
            self.audio_process = None
            detail = ""
            try:
                if self.audio_log_handle:
                    self.audio_log_handle.flush()
                log_path = Path(getattr(self, "audio_log_path", ""))
                if log_path.exists():
                    lines = log_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                    if lines:
                        detail = lines[-1][:180]
            except Exception:
                pass

            if hasattr(self, "audio_status"):
                self.audio_status.setText(
                    "Status: Error — " + (detail or "microphone stream could not start")
                )
            self._set_audio_monitor_status(
                "Audio stream stopped. PhoneHub will retry automatically."
            )
            self.set_footer(
                "Recording failed. PhoneHub saved the scrcpy error log for diagnosis."
                if getattr(self, "audio_recording", False)
                else "Audio stream stopped. Reconnecting automatically."
            )
            if getattr(self, "audio_listen_requested", False) and not getattr(self, "audio_recording", False):
                QTimer.singleShot(1800, self._retry_audio_stream)

    def _retry_audio_stream(self):
        if not getattr(self, "audio_listen_requested", False):
            return

        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            return

        source = getattr(self, "audio_source", "")
        if source.startswith("voice-call") and self._android_call_state() != "active":
            self._set_audio_monitor_status("Waiting for active call...")
            return

        self._set_audio_monitor_status("Reconnecting audio...")
        self._launch_live_audio("")

    def _stop_audio_process_only(self):
        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            graceful = False

            # scrcpy must exit cleanly so MP4/M4A can write its final moov index.
            # On Windows, CTRL_BREAK reaches the new process group without
            # abruptly killing the recorder.
            if sys.platform.startswith("win"):
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                    proc.wait(timeout=5)
                    graceful = True
                except Exception:
                    graceful = False
            else:
                try:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=5)
                    graceful = True
                except Exception:
                    graceful = False

            if not graceful and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        self.audio_process = None

        if self.audio_log_handle:
            try:
                self.audio_log_handle.flush()
                self.audio_log_handle.close()
            except Exception:
                pass
            self.audio_log_handle = None

    def start_echo_free_recording(self):
        recordings = Path(r"C:\PhoneHub\runtime\audio")
        recordings.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        record_path = recordings / f"phone_mic_{stamp}.m4a"

        self._stop_audio_process_only()
        self.audio_recording = True
        self.audio_no_playback = True
        self.audio_record_path = str(record_path)

        if hasattr(self, "audio_record_button"):
            self.audio_record_button.setText("Stop Recording")
        if hasattr(self, "audio_record_file"):
            self.audio_record_file.setText(f"Recording file: {record_path}")
        if hasattr(self, "audio_status"):
            self.audio_status.setText("Status: Echo-Free Recording — PC playback OFF")

        if not self._launch_live_audio(str(record_path)):
            self.audio_recording = False
            self.audio_no_playback = False
            if hasattr(self, "audio_record_button"):
                self.audio_record_button.setText("Record")
            return

        self.set_footer("Echo-Free Recording started. PC playback is disabled to prevent feedback.")

    def toggle_audio_recording(self):
        if getattr(self, "audio_recording", False):
            was_echo_free = getattr(self, "audio_no_playback", False)
            self._stop_audio_process_only()
            self.audio_recording = False
            self.audio_no_playback = False
            if hasattr(self, "audio_record_button"):
                self.audio_record_button.setText("Record")
            self.analyze_last_audio_recording()

            if was_echo_free:
                if hasattr(self, "audio_status"):
                    self.audio_status.setText("Status: Idle — Echo-Free Recording saved")
                self.set_footer("Echo-Free Recording saved. Playback stayed off, so no PC-speaker feedback was added.")
            else:
                if hasattr(self, "audio_status"):
                    self.audio_status.setText("Status: Restarting live listening...")
                self.set_footer("Recording saved. Analyzing level, then continuing live listening...")
                self._launch_live_audio("")
            return

        recordings = Path(r"C:\PhoneHub\runtime\audio")
        recordings.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        record_path = recordings / f"phone_mic_{stamp}.m4a"

        self._stop_audio_process_only()
        self.audio_recording = True
        self.audio_no_playback = False
        self.audio_record_path = str(record_path)

        if hasattr(self, "audio_record_button"):
            self.audio_record_button.setText("Stop Recording")
        if hasattr(self, "audio_record_file"):
            self.audio_record_file.setText(f"Recording file: {record_path}")

        if not self._launch_live_audio(str(record_path)):
            self.audio_recording = False
            if hasattr(self, "audio_record_button"):
                self.audio_record_button.setText("Record")

    def adjust_windows_volume(self, steps):
        if not sys.platform.startswith("win"):
            self.set_footer("Volume buttons are available on Windows.")
            return

        vk = 0xAF if steps > 0 else 0xAE  # VK_VOLUME_UP / VK_VOLUME_DOWN
        count = max(1, abs(int(steps)))
        try:
            for _ in range(count):
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            self.set_footer(
                "Windows output volume increased."
                if steps > 0 else
                "Windows output volume decreased."
            )
        except Exception as exc:
            self.set_footer(f"Could not change Windows volume: {exc}")

    def open_windows_volume_mixer(self):
        try:
            subprocess.Popen(["sndvol.exe"])
            self.set_footer("Opened Windows Volume Mixer.")
        except Exception as exc:
            self.set_footer(f"Could not open Volume Mixer: {exc}")

    def analyze_last_audio_recording(self):
        path_text = getattr(self, "audio_record_path", "")
        if not path_text:
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText("Level: No recording available")
            self.set_footer("No PhoneHub audio recording is available to analyze.")
            return

        path = Path(path_text)
        if not path.exists():
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText("Level: Recording file not found")
            self.set_footer("The last recording file could not be found.")
            return

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            text = "Level: Recording saved as M4A/AAC. Install FFmpeg for peak analysis."
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText(text)
            self.set_footer(text)
            return

        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-i", str(path),
                    "-af", "volumedetect",
                    "-f", "null",
                    "NUL" if sys.platform.startswith("win") else "/dev/null",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0),
            )
            report = (result.stdout or "") + "\n" + (result.stderr or "")
            mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", report)
            max_match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", report)

            if not max_match:
                raise ValueError("FFmpeg did not return a peak level.")

            peak_db = float(max_match.group(1))
            mean_db = float(mean_match.group(1)) if mean_match else None

            if peak_db >= -0.5:
                state = "PEAKING / clipping risk"
            elif peak_db >= -3.0:
                state = "Very loud / close to peak"
            elif peak_db >= -12.0:
                state = "Good voice level"
            elif peak_db >= -20.0:
                state = "A little low"
            else:
                state = "Too low"

            text = f"Level: {state} | Peak {peak_db:.1f} dBFS"
            if mean_db is not None:
                text += f" | Average {mean_db:.1f} dBFS"

            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText(text)
            self.set_footer(text)
        except Exception as exc:
            text = f"Level: Recording plays normally; analysis unavailable — {exc}"
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText(text)
            self.set_footer(text)

    def open_audio_recordings_folder(self):
        folder = Path(r"C:\PhoneHub\runtime\audio")
        folder.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["explorer", str(folder)])
        except Exception:
            self.set_footer(f"Recordings folder: {folder}")

    def stop_live_audio(self):
        self.audio_listen_requested = False
        self._stop_audio_process_only()
        was_recording = getattr(self, "audio_recording", False)
        self.audio_recording = False
        self.audio_no_playback = False
        if hasattr(self, "audio_record_button"):
            self.audio_record_button.setText("Record")
        if hasattr(self, "audio_status"):
            self.audio_status.setText("Status: Idle")
        self._set_audio_monitor_status("Stopped")
        if self.audio_monitor_window is not None:
            self.audio_monitor_window.hide()
        self.set_footer(
            "Phone microphone stopped. Recording saved."
            if was_recording else
            "Phone microphone audio stopped."
        )
        if was_recording:
            self.analyze_last_audio_recording()

    def closeEvent(self, event):
        if getattr(self, "_force_exit", False) or not self.tray_icon:
            try:
                self.stop_live_audio()
            except Exception:
                pass
            event.accept()
            return

        # Keep background notification feed alive in the Windows tray.
        self.hide()
        if self.tray_icon:
            self.tray_icon.showMessage(
                "PhoneHub is still running",
                "Notification Feed continues in the background. Use the tray icon to reopen or quit.",
                QSystemTrayIcon.Information,
                5000,
            )
        event.ignore()

    def page_device_tools(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        mirror_box, mirror_layout, _ = self.card(
            "Temporary scrcpy device controls",
            "These options apply while that scrcpy session is running and are restored when it closes.",
        )

        row1 = QHBoxLayout()
        keep_active = QPushButton("Keep Active")
        keep_active.setObjectName("primary")
        keep_active.clicked.connect(lambda: self.start_device_scrcpy(["--keep-active"], "Keep Active"))

        screen_off = QPushButton("Mirror + Screen Off")
        screen_off.clicked.connect(
            lambda: self.start_device_scrcpy(["--turn-screen-off", "--keep-active"], "Mirror + Screen Off")
        )

        timeout5 = QPushButton("5 Min Screen Timeout")
        timeout5.clicked.connect(
            lambda: self.start_device_scrcpy(["--screen-off-timeout=300"], "5 Minute Timeout")
        )

        touches = QPushButton("Show Touches")
        touches.clicked.connect(
            lambda: self.start_device_scrcpy(["--show-touches"], "Show Touches")
        )

        row1.addWidget(keep_active)
        row1.addWidget(screen_off)
        row1.addWidget(timeout5)
        row1.addWidget(touches)
        mirror_layout.addLayout(row1)
        layout.addWidget(mirror_box)

        adb_box, adb_layout, _ = self.card(
            "Android device settings",
            "These are direct Android settings. Unlike the temporary scrcpy options above, they stay changed until you change them back.",
        )

        row2 = QHBoxLayout()

        stay_on = QPushButton("Stay Awake ON")
        stay_on.clicked.connect(lambda: self.device_setting(
            ["settings", "put", "global", "stay_on_while_plugged_in", "7"],
            "Stay awake while plugged in: ON"
        ))

        stay_off = QPushButton("Stay Awake OFF")
        stay_off.clicked.connect(lambda: self.device_setting(
            ["settings", "put", "global", "stay_on_while_plugged_in", "0"],
            "Stay awake while plugged in: OFF"
        ))

        touch_on = QPushButton("Touches ON")
        touch_on.clicked.connect(lambda: self.device_setting(
            ["settings", "put", "system", "show_touches", "1"],
            "Show touches: ON"
        ))

        touch_off = QPushButton("Touches OFF")
        touch_off.clicked.connect(lambda: self.device_setting(
            ["settings", "put", "system", "show_touches", "0"],
            "Show touches: OFF"
        ))

        row2.addWidget(stay_on)
        row2.addWidget(stay_off)
        row2.addWidget(touch_on)
        row2.addWidget(touch_off)
        adb_layout.addLayout(row2)

        row3 = QHBoxLayout()

        timeout30 = QPushButton("Timeout 30 sec")
        timeout30.clicked.connect(lambda: self.device_setting(
            ["settings", "put", "system", "screen_off_timeout", "30000"],
            "Screen timeout set to 30 seconds"
        ))

        timeout300 = QPushButton("Timeout 5 min")
        timeout300.clicked.connect(lambda: self.device_setting(
            ["settings", "put", "system", "screen_off_timeout", "300000"],
            "Screen timeout set to 5 minutes"
        ))

        read_values = QPushButton("Read Current Settings")
        read_values.setObjectName("primary")
        read_values.clicked.connect(self.read_device_settings)

        row3.addWidget(timeout30)
        row3.addWidget(timeout300)
        row3.addWidget(read_values)
        adb_layout.addLayout(row3)

        self.device_settings_status = QLabel("Status: Ready")
        self.device_settings_status.setObjectName("big")
        self.device_settings_status.setWordWrap(True)
        adb_layout.addWidget(self.device_settings_status)

        layout.addWidget(adb_box)

        app_box, app_layout, _ = self.card(
            "Start Android app",
            "Enter an Android package name, for example org.mozilla.firefox.",
        )

        self.device_app_input = QLineEdit()
        self.device_app_input.setPlaceholderText("com.example.app")
        app_layout.addWidget(self.device_app_input)

        launch = QPushButton("Start App")
        launch.setObjectName("primary")
        launch.clicked.connect(self.start_android_app_from_device_page)
        app_layout.addWidget(launch)

        layout.addWidget(app_box)
        layout.addStretch()
        return page

    def _device_target(self):
        ip, port = get_saved_ip()
        target = f"{ip}:{port}" if ip else ""
        usb, remote, unauthorized, _ = parse_adb_devices()

        if target and target in remote:
            return target
        if usb:
            return usb[0]
        return ""

    def start_device_scrcpy(self, extra_args, label):
        scrcpy = scrcpy_path()
        target = self._device_target()

        if not scrcpy:
            self.set_footer("scrcpy not found.")
            return
        if not target:
            self.set_footer("Phone is not connected.")
            return

        args = [scrcpy, "--serial", target] + list(extra_args)
        try:
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0),
            )
            self.set_footer(f"{label} started.")
        except Exception as exc:
            self.set_footer(f"{label} failed: {exc}")

    def device_setting(self, shell_args, success_text):
        target = self._device_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return

        result = run_quiet(["adb", "-s", target, "shell"] + shell_args, timeout=6)
        if hasattr(self, "device_settings_status"):
            self.device_settings_status.setText(success_text if result == "" else f"{success_text}\n{result}")
        self.set_footer(success_text)

    def read_device_settings(self):
        target = self._device_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return

        stay = run_quiet(
            ["adb", "-s", target, "shell", "settings", "get", "global", "stay_on_while_plugged_in"],
            timeout=5,
        )
        timeout = run_quiet(
            ["adb", "-s", target, "shell", "settings", "get", "system", "screen_off_timeout"],
            timeout=5,
        )
        touches = run_quiet(
            ["adb", "-s", target, "shell", "settings", "get", "system", "show_touches"],
            timeout=5,
        )

        text = (
            f"stay_on_while_plugged_in: {stay or 'unknown'}\n"
            f"screen_off_timeout: {timeout or 'unknown'} ms\n"
            f"show_touches: {touches or 'unknown'}"
        )
        if hasattr(self, "device_settings_status"):
            self.device_settings_status.setText(text)
        self.set_footer("Read current Android device settings.")

    def start_android_app_from_device_page(self):
        package = self.device_app_input.text().strip() if hasattr(self, "device_app_input") else ""
        if not package:
            self.set_footer("Enter an Android package name.")
            return

        scrcpy = scrcpy_path()
        target = self._device_target()
        if not scrcpy or not target:
            self.set_footer("scrcpy or phone connection is unavailable.")
            return

        try:
            subprocess.Popen(
                [scrcpy, "--serial", target, f"--start-app={package}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0),
            )
            self.set_footer(f"Starting Android app: {package}")
        except Exception as exc:
            self.set_footer(f"Could not start app: {exc}")

    def page_notifications(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        box, box_layout, _ = self.card(
            "Notification Feed",
            "Live RSS-style notification feed. Notifications like the ones visible in your Android notification shade are forwarded to this PC over Tailscale by PhoneHub Notifier. "
            "WhatsApp/SMS messaging-style notifications are decoded for conversation title, sender and latest message. "
            "ADB polling remains only as a fallback. PhoneHub can stay in the Windows tray.",
        )

        self.notification_status = QLabel("Status: Starting background feed...")
        self.notification_status.setObjectName("sideStatus")
        self.notification_status.setWordWrap(True)
        box_layout.addWidget(self.notification_status)

        actions = QHBoxLayout()

        refresh = QPushButton("Refresh Now")
        refresh.setObjectName("primary")
        refresh.clicked.connect(self.poll_notifications)

        self.notification_pause_button = QPushButton("Pause Feed")
        self.notification_pause_button.clicked.connect(self.toggle_notification_feed)

        clear = QPushButton("Clear View")
        clear.clicked.connect(self.clear_notification_view)

        startup = QPushButton("Enable Windows Startup")
        startup.clicked.connect(self.enable_phonehub_startup)

        diagnose = QPushButton("Diagnose Feed")
        diagnose.clicked.connect(self.diagnose_notification_feed)

        actions.addWidget(refresh)
        actions.addWidget(self.notification_pause_button)
        actions.addWidget(clear)
        actions.addWidget(startup)
        actions.addWidget(diagnose)
        box_layout.addLayout(actions)

        companion_row = QHBoxLayout()

        configure_companion = QPushButton("Configure Companion")
        configure_companion.setObjectName("primary")
        configure_companion.clicked.connect(self.configure_notification_companion)

        notification_access = QPushButton("Open Notification Access")
        notification_access.clicked.connect(self.open_notification_access_settings)

        companion_test = QPushButton("Check Companion")
        companion_test.clicked.connect(self.check_notification_companion)

        companion_row.addWidget(configure_companion)
        companion_row.addWidget(notification_access)
        companion_row.addWidget(companion_test)
        box_layout.addLayout(companion_row)

        self.notification_receiver_label = QLabel("Companion receiver: starting...")
        self.notification_receiver_label.setObjectName("big")
        self.notification_receiver_label.setWordWrap(True)
        self.notification_receiver_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box_layout.addWidget(self.notification_receiver_label)

        filters = QHBoxLayout()

        all_btn = QPushButton("All")
        all_btn.setObjectName("primary")
        all_btn.clicked.connect(lambda: self.set_notification_filter("all"))

        sms_btn = QPushButton("SMS")
        sms_btn.clicked.connect(lambda: self.set_notification_filter("sms"))

        wa_btn = QPushButton("WhatsApp")
        wa_btn.clicked.connect(lambda: self.set_notification_filter("whatsapp"))

        calls_btn = QPushButton("Calls")
        calls_btn.clicked.connect(lambda: self.set_notification_filter("calls"))

        filters.addWidget(all_btn)
        filters.addWidget(sms_btn)
        filters.addWidget(wa_btn)
        filters.addWidget(calls_btn)
        box_layout.addLayout(filters)

        self.notification_list = QListWidget()
        self.notification_list.setMinimumHeight(300)
        box_layout.addWidget(self.notification_list)

        self.notification_diag = QLabel("Diagnostics: not run yet")
        self.notification_diag.setObjectName("big")
        self.notification_diag.setWordWrap(True)
        self.notification_diag.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box_layout.addWidget(self.notification_diag)

        note = QLabel(
            "Closing the PhoneHub window now hides it to the Windows system tray instead of stopping it. "
            "New notifications can appear as Windows tray notifications. Feed history stays local in "
            "C:\\PhoneHub\\runtime\\notifications."
        )
        note.setObjectName("big")
        note.setWordWrap(True)
        box_layout.addWidget(note)

        layout.addWidget(box)
        layout.addStretch()
        QTimer.singleShot(100, self._refresh_notification_list)
        return page

    def _setup_system_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        icon = self.windowIcon()
        if icon.isNull():
            icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)

        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip(f"PhoneHub {APP_VERSION}")

        menu = QMenu()
        open_action = menu.addAction("Open PhoneHub")
        open_action.triggered.connect(self.restore_from_tray)

        notifications_action = menu.addAction("Open Notifications")
        notifications_action.triggered.connect(self.open_notifications_page)

        self.tray_pause_action = menu.addAction("Pause Notification Feed")
        self.tray_pause_action.triggered.connect(self.toggle_notification_feed)

        menu.addSeparator()
        quit_action = menu.addAction("Quit PhoneHub")
        quit_action.triggered.connect(self.quit_phonehub)

        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self.tray_icon = tray

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.restore_from_tray()

    def restore_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def open_notifications_page(self):
        self.restore_from_tray()
        names = [
            "Home", "Setup", "Screen", "Camera", "Audio", "Files",
            "Apps", "Control", "Device", "Notifications", "Settings"
        ]
        try:
            self.show_page(names.index("Notifications"))
        except Exception:
            pass

    def quit_phonehub(self):
        self._force_exit = True
        try:
            self.stop_live_audio()
        except Exception:
            pass
        try:
            if self.notification_receiver_server is not None:
                self.notification_receiver_server.shutdown()
                self.notification_receiver_server.server_close()
                self.notification_receiver_server = None
        except Exception:
            pass
        if self.tray_icon:
            self.tray_icon.hide()
        QApplication.quit()

    def toggle_notification_feed(self):
        self.notification_feed_enabled = not self.notification_feed_enabled
        text = "Pause Feed" if self.notification_feed_enabled else "Resume Feed"
        if hasattr(self, "notification_pause_button"):
            self.notification_pause_button.setText(text)
        if hasattr(self, "tray_pause_action"):
            self.tray_pause_action.setText(
                "Pause Notification Feed" if self.notification_feed_enabled else "Resume Notification Feed"
            )
        if hasattr(self, "notification_status"):
            self.notification_status.setText(
                "Status: Background feed active"
                if self.notification_feed_enabled else
                "Status: Feed paused"
            )
        if self.notification_feed_enabled:
            self.poll_notifications()

    def _load_or_create_notification_token(self):
        try:
            if self.notification_token_file.exists():
                token = self.notification_token_file.read_text(encoding="utf-8").strip()
                if token:
                    return token
            token = secrets.token_urlsafe(24)
            self.notification_token_file.write_text(token, encoding="utf-8")
            return token
        except Exception:
            return secrets.token_urlsafe(24)

    def _pc_tailscale_ip(self):
        output = run_quiet(["tailscale", "ip", "-4"], timeout=5)
        for line in output.splitlines():
            value = line.strip()
            if re.match(r"^100\.(?:\d{1,3}\.){2}\d{1,3}$", value):
                return value
        return ""

    def start_notification_receiver(self):
        if self.notification_receiver_server is not None:
            return

        host = self._pc_tailscale_ip()
        if not host:
            self.notification_receiver_url = ""
            if hasattr(self, "notification_receiver_label"):
                self.notification_receiver_label.setText(
                    "Companion receiver: waiting for PC Tailscale IP"
                )
            return

        outer = self
        token = self.notification_pairing_token

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/notify":
                    self.send_response(404)
                    self.end_headers()
                    return

                if self.headers.get("X-PhoneHub-Token", "") != token:
                    self.send_response(403)
                    self.end_headers()
                    return

                try:
                    length = min(int(self.headers.get("Content-Length", "0") or 0), 65536)
                    raw = self.rfile.read(length)
                    payload = json.loads(raw.decode("utf-8", errors="replace"))
                    outer.auto_bridge.notification_push.emit(payload)
                    self.send_response(204)
                    self.end_headers()
                except Exception:
                    self.send_response(400)
                    self.end_headers()

            def log_message(self, format, *args):
                return

        try:
            server = ThreadingHTTPServer((host, 8765), Handler)
        except Exception as exc:
            self.notification_receiver_url = ""
            if hasattr(self, "notification_receiver_label"):
                self.notification_receiver_label.setText(
                    f"Companion receiver error: {exc}"
                )
            return

        self.notification_receiver_server = server
        self.notification_receiver_url = f"http://{host}:8765/notify"

        import threading
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.notification_receiver_thread = thread

        if hasattr(self, "notification_receiver_label"):
            self.notification_receiver_label.setText(
                f"Companion receiver: READY\n{self.notification_receiver_url}"
            )

    def _apply_companion_notification(self, payload):
        if not self.notification_feed_enabled:
            return

        package = str(payload.get("package") or "Android")[:200]
        title = self._clean_notification_value(payload.get("title") or "")
        body = self._clean_notification_value(payload.get("text") or payload.get("body") or "")
        if not title and not body:
            return

        kind = self._notification_kind(package, title, body)
        raw_id = f"{package}|{title}|{body}|{payload.get('posted_at', '')}"
        item = {
            "id": hashlib.sha1(raw_id.encode("utf-8", errors="ignore")).hexdigest(),
            "package": package,
            "app": self._notification_app_label(package, kind),
            "kind": kind,
            "title": title or package,
            "body": body,
            "time": datetime.now().strftime("%H:%M:%S"),
            "source": "companion",
        }

        if item["id"] in self.notification_seen:
            return
        self.notification_seen.add(item["id"])
        self.notification_items.insert(0, item)
        self.notification_items = self.notification_items[:200]
        self._append_notification_history(item)
        self._refresh_notification_list()

        if hasattr(self, "notification_status"):
            self.notification_status.setText(
                f"Status: Live companion feed · {item['app']} received"
            )

        if self.tray_icon:
            self.tray_icon.showMessage(
                f"{item['app']} · {item['title']}",
                item["body"],
                QSystemTrayIcon.Information,
                7000,
            )

    def configure_notification_companion(self):
        self.start_notification_receiver()
        target = self._notification_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return
        if not self.notification_receiver_url:
            self.set_footer("PC Tailscale receiver is not ready.")
            return

        packages = run_quiet(
            ["adb", "-s", target, "shell", "pm", "list", "packages", "com.phonehub.notifier"],
            timeout=6,
        )
        if "com.phonehub.notifier" not in packages:
            self.set_footer("PhoneHub Notifier is not installed on the phone yet.")
            if hasattr(self, "notification_receiver_label"):
                self.notification_receiver_label.setText(
                    "Companion app not installed. Build/install PhoneHubNotifier.apk first."
                )
            return

        result = run_quiet([
            "adb", "-s", target, "shell", "am", "start",
            "-n", "com.phonehub.notifier/.MainActivity",
            "--es", "endpoint", self.notification_receiver_url,
            "--es", "token", self.notification_pairing_token,
        ], timeout=8)

        if "Error" in result or "Exception" in result:
            self.set_footer("Could not configure PhoneHub Notifier.")
        else:
            self.set_footer("Companion configured. Enable Notification Access on the phone.")
            if hasattr(self, "notification_receiver_label"):
                self.notification_receiver_label.setText(
                    f"Companion configured for:\n{self.notification_receiver_url}"
                )

    def open_notification_access_settings(self):
        target = self._notification_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return
        run_background([
            "adb", "-s", target, "shell", "am", "start",
            "-a", "android.settings.ACTION_NOTIFICATION_LISTENER_SETTINGS",
        ])
        self.set_footer("Opened Notification Access settings on the phone.")

    def check_notification_companion(self):
        target = self._notification_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return

        packages = run_quiet(
            ["adb", "-s", target, "shell", "pm", "list", "packages", "com.phonehub.notifier"],
            timeout=6,
        )
        listeners = run_quiet(
            ["adb", "-s", target, "shell", "settings", "get", "secure", "enabled_notification_listeners"],
            timeout=6,
        )

        installed = "com.phonehub.notifier" in packages
        enabled = "com.phonehub.notifier" in listeners
        receiver = bool(self.notification_receiver_url)

        text = (
            "Companion diagnostics:\n"
            f"Installed: {'YES' if installed else 'NO'}\n"
            f"Notification Access: {'ENABLED' if enabled else 'NOT ENABLED'}\n"
            f"PC receiver: {'READY' if receiver else 'NOT READY'}\n"
            f"Receiver URL: {self.notification_receiver_url or 'unavailable'}"
        )
        if hasattr(self, "notification_diag"):
            self.notification_diag.setText(text)
        self.set_footer("Companion check complete.")

    def diagnose_notification_feed(self):
        target = self._notification_target()
        if not target:
            text = "Diagnostics: phone is not connected over ADB/Tailscale."
            if hasattr(self, "notification_diag"):
                self.notification_diag.setText(text)
            self.set_footer("Notification diagnostics: phone not connected.")
            return

        raw = run_quiet(
            ["adb", "-s", target, "shell", "dumpsys", "notification", "--noredact"],
            timeout=12,
        )
        parsed = self._parse_notification_dump(raw)
        packages = sorted({item.get("package", "") for item in parsed if item.get("package")})
        wa = [item for item in parsed if item.get("kind") == "whatsapp"]
        sms = [item for item in parsed if item.get("kind") == "sms"]

        if hasattr(self, "notification_diag"):
            self.notification_diag.setText(
                "Diagnostics:\n"
                f"ADB target: {target}\n"
                f"Parsed notifications: {len(parsed)}\n"
                f"WhatsApp: {len(wa)}\n"
                f"SMS: {len(sms)}\n"
                f"Packages: {', '.join(packages[:12]) if packages else 'none'}"
            )

        self.set_footer("Notification diagnostics complete.")

    def set_notification_filter(self, mode):
        self.notification_filter = mode
        self._refresh_notification_list()
        if hasattr(self, "notification_status"):
            self.notification_status.setText(f"Status: Showing {mode.upper()} feed")

    def _notification_kind(self, package, title, body):
        p = (package or "").lower()
        t = (title or "").lower()
        b = (body or "").lower()

        if "whatsapp" in p:
            return "whatsapp"

        sms_packages = (
            "com.google.android.apps.messaging",
            "com.android.mms",
            "com.samsung.android.messaging",
            "com.oneplus.mms",
            "com.coloros.mms",
        )
        if any(x in p for x in sms_packages) or "sms" in p or "message" in p:
            return "sms"

        call_packages = (
            "com.google.android.dialer",
            "com.android.dialer",
            "com.samsung.android.dialer",
            "com.android.server.telecom",
        )
        if any(x in p for x in call_packages) or "missed call" in t or "missed call" in b:
            return "calls"

        return "other"

    def _notification_app_label(self, package, kind):
        if kind == "whatsapp":
            return "WhatsApp"
        if kind == "sms":
            return "SMS"
        if kind == "calls":
            return "Calls"
        return package or "Android"

    def _notification_target(self):
        ip, port = get_saved_ip()
        target = f"{ip}:{port}" if ip else ""
        usb, remote, unauthorized, _ = parse_adb_devices()

        if target and target in remote:
            return target
        if target:
            run_quiet(["adb", "connect", target], timeout=6)
            usb, remote, unauthorized, _ = parse_adb_devices()
            if target in remote:
                return target
        if usb:
            return usb[0]
        return ""

    def poll_notifications(self):
        if not self.notification_feed_enabled or self.notification_poll_busy:
            return

        self.notification_poll_busy = True

        def worker():
            items = []
            try:
                target = self._notification_target()
                if not target:
                    items = [{"_status": "Phone not connected"}]
                else:
                    raw = run_quiet(
                        ["adb", "-s", target, "shell", "dumpsys", "notification", "--noredact"],
                        timeout=12,
                    )
                    items = self._parse_notification_dump(raw)
                    if not items:
                        if raw.strip():
                            items = [{"_status": "Connected — Android returned notification data, but no readable title/text was parsed. Press Diagnose Feed."}]
                        else:
                            items = [{"_status": "Connected — no notification data returned"}]
            except Exception as exc:
                items = [{"_status": f"Notification check failed: {exc}"}]
            self.auto_bridge.notifications.emit(items)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _parse_notification_dump(self, raw):
        if not raw:
            return []

        blocks = re.split(r"(?=NotificationRecord\(|\n\s*NotificationRecord\{)", raw)
        items = []

        for block in blocks:
            if "NotificationRecord" not in block:
                continue

            pkg_match = re.search(r"(?:pkg=|package=)([^\s,}]+)", block)
            pkg = pkg_match.group(1).strip() if pkg_match else "Android"

            title = self._notification_extra(block, "android.title")
            text = self._notification_extra(block, "android.text")
            big_text = self._notification_extra(block, "android.bigText")
            sub_text = self._notification_extra(block, "android.subText")

            body = big_text or text or sub_text

            # Some Android/OEM builds serialize extras differently.
            if not title:
                m = re.search(r"(?:android\.title|android\.conversationTitle)[^=]*=([^\n,}]+)", block)
                if m:
                    title = m.group(1).strip(" ()\"'")

            if not body:
                m = re.search(r"(?:android\.text|android\.bigText|android\.messages)[^=]*=([^\n}]+)", block)
                if m:
                    body = m.group(1).strip(" ()\"'")

            if not title and not body:
                ticker = re.search(r"tickerText=([^\n]+)", block)
                body = ticker.group(1).strip() if ticker else ""

            title = self._clean_notification_value(title)
            body = self._clean_notification_value(body)

            if not title and not body:
                continue

            key = hashlib.sha1(f"{pkg}|{title}|{body}".encode("utf-8", errors="ignore")).hexdigest()
            kind = self._notification_kind(pkg, title, body)
            items.append({
                "id": key,
                "package": pkg,
                "app": self._notification_app_label(pkg, kind),
                "kind": kind,
                "title": title or pkg,
                "body": body,
                "time": datetime.now().strftime("%H:%M:%S"),
            })

        # dumpsys may contain duplicates in ranking/history sections.
        unique = []
        seen = set()
        for item in items:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            unique.append(item)
        return unique[:80]

    def _notification_extra(self, block, key):
        patterns = [
            rf"{re.escape(key)}=String \((.*?)\)",
            rf"{re.escape(key)}=SpannableString \((.*?)\)",
            rf"{re.escape(key)}=CharSequence \((.*?)\)",
            rf"{re.escape(key)}=\"([^\"]*)\"",
            rf"{re.escape(key)}='([^']*)'",
            rf"{re.escape(key)}=([^\n,}}]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, block, flags=re.DOTALL)
            if match:
                return match.group(1).strip()
        return ""

    def _clean_notification_value(self, value):
        value = str(value or "").replace("\\n", " ").replace("\n", " ").strip()

        # Repair common UTF-8 text that was accidentally decoded as Windows-1252,
        # for example: donâ€™t -> don’t.
        if any(marker in value for marker in ("â€™", "â€œ", "â€", "Ã", "Â")):
            try:
                repaired = value.encode("cp1252", errors="strict").decode("utf-8", errors="strict")
                if repaired:
                    value = repaired
            except Exception:
                pass

        value = re.sub(r"\s+", " ", value)
        if value in ("null", "None"):
            return ""
        return value[:500]

    def _apply_notification_results(self, items):
        self.notification_poll_busy = False

        if items and "_status" in items[0]:
            status = items[0]["_status"]
            if hasattr(self, "notification_status"):
                self.notification_status.setText(f"Status: {status}")
            return

        new_items = []
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            if item_id not in self.notification_seen:
                self.notification_seen.add(item_id)
                new_items.append(item)

        # First poll establishes a baseline so old phone notifications do not all toast at once.
        if not self.notification_baseline_ready:
            self.notification_baseline_ready = True
            self.notification_items = items[:80]
            self._refresh_notification_list()
            if hasattr(self, "notification_status"):
                self.notification_status.setText(
                    f"Status: Background feed active · {len(items)} current notifications"
                )
            return

        if new_items:
            for item in reversed(new_items):
                self.notification_items.insert(0, item)
                self._append_notification_history(item)
            self.notification_items = self.notification_items[:200]

            newest = new_items[0]
            if self.tray_icon and self.notification_feed_enabled:
                self.tray_icon.showMessage(
                    f"{newest.get('app') or 'Phone'} · {newest.get('title') or 'Notification'}",
                    newest.get("body") or "",
                    QSystemTrayIcon.Information,
                    7000,
                )

        self._refresh_notification_list()
        if hasattr(self, "notification_status"):
            self.notification_status.setText(
                f"Status: Background feed active · {len(self.notification_items)} in feed"
            )

    def _append_notification_history(self, item):
        try:
            record = dict(item)
            record["saved_at"] = datetime.now().isoformat(timespec="seconds")
            with self.notification_store.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _refresh_notification_list(self):
        if not hasattr(self, "notification_list"):
            return
        self.notification_list.clear()
        mode = getattr(self, "notification_filter", "all")

        for item in self.notification_items[:200]:
            kind = item.get("kind") or "other"
            if mode != "all" and kind != mode:
                continue

            app = item.get("app") or item.get("package") or "Android"
            title = item.get("title") or "Notification"
            body = item.get("body") or ""
            when = item.get("time") or ""

            self.notification_list.addItem(
                f"[{when}] {app}\n"
                f"{title}\n"
                f"{body}\n"
                f"────────────────────────"
            )

    def clear_notification_view(self):
        self.notification_items = []
        self._refresh_notification_list()
        if hasattr(self, "notification_status"):
            self.notification_status.setText("Status: View cleared · background feed still active")

    def enable_phonehub_startup(self):
        try:
            startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            startup.mkdir(parents=True, exist_ok=True)
            launcher = startup / "PhoneHub_Background.cmd"
            launcher.write_text(
                '@echo off\r\n'
                'cd /d C:\\PhoneHub\r\n'
                'start "" /min C:\\PhoneHub\\PhoneHub.bat\r\n',
                encoding="utf-8",
            )
            self.set_footer("PhoneHub background startup enabled for Windows sign-in.")
            if hasattr(self, "notification_status"):
                self.notification_status.setText("Status: Background feed active · Windows startup enabled")
        except Exception as exc:
            self.set_footer(f"Could not enable Windows startup: {exc}")

    def page_app_control(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        box, box_layout, _ = self.card(
            "Managed App Control",
            "Device Owner mode can suspend selected apps, protect them from uninstall, and restrict app installation. "
            "PhoneHub never enables Device Owner automatically because Android provisioning requirements can affect device setup.",
        )

        self.app_control_status = QLabel("Status: Check Device Owner first")
        self.app_control_status.setObjectName("sideStatus")
        self.app_control_status.setWordWrap(True)
        box_layout.addWidget(self.app_control_status)

        top = QHBoxLayout()

        check = QPushButton("Check Device Owner")
        check.setObjectName("primary")
        check.clicked.connect(self.check_device_owner_status)

        open_companion = QPushButton("Open Companion")
        open_companion.clicked.connect(self.open_phonehub_companion)

        scan = QPushButton("Find Control Packages")
        scan.clicked.connect(self.scan_control_packages)

        top.addWidget(check)
        top.addWidget(open_companion)
        top.addWidget(scan)
        box_layout.addLayout(top)

        provision_box, provision_layout, _ = self.card(
            "New Phone Setup",
            "Use this once on each phone you own/manage. PhoneHub checks the APK, accounts, Device Admin receiver and Device Owner state. "
            "It will not delete accounts or factory-reset the phone automatically.",
        )

        provision_actions = QHBoxLayout()

        provision_check = QPushButton("1. Check New Phone")
        provision_check.setObjectName("primary")
        provision_check.clicked.connect(self.provision_phone_check)

        open_accounts = QPushButton("2. Open Accounts")
        open_accounts.clicked.connect(self.open_android_accounts)

        provision_owner = QPushButton("3. Provision Device Owner")
        provision_owner.setObjectName("primary")
        provision_owner.clicked.connect(self.provision_device_owner)

        verify_owner = QPushButton("4. Verify")
        verify_owner.clicked.connect(self.check_device_owner_status)

        provision_actions.addWidget(provision_check)
        provision_actions.addWidget(open_accounts)
        provision_actions.addWidget(provision_owner)
        provision_actions.addWidget(verify_owner)
        provision_layout.addLayout(provision_actions)

        repair_actions = QHBoxLayout()
        install_companion = QPushButton("Install APK from PhoneHub")
        install_companion.clicked.connect(self.install_latest_companion)

        stale_session = QPushButton("Clear Stale Account Session + Reboot")
        stale_session.clicked.connect(self.clear_stale_account_session)

        repair_actions.addWidget(install_companion)
        repair_actions.addWidget(stale_session)
        provision_layout.addLayout(repair_actions)

        self.provision_status = QTextEdit()
        self.provision_status.setReadOnly(True)
        self.provision_status.setMinimumHeight(135)
        self.provision_status.setText(
            "Connect the phone by USB, authorize USB debugging, then press '1. Check New Phone'.\n"
            "PhoneHub will tell you exactly what is still required."
        )
        provision_layout.addWidget(self.provision_status)
        self.provision_box = provision_box
        box_layout.addWidget(provision_box)

        self.managed_phone_banner = QLabel("Managed phone status: checking...")
        self.managed_phone_banner.setObjectName("big")
        self.managed_phone_banner.setWordWrap(True)
        box_layout.addWidget(self.managed_phone_banner)

        setup_toggle_row = QHBoxLayout()
        self.setup_toggle_btn = QPushButton("Show New Phone Setup")
        self.setup_toggle_btn.clicked.connect(self.toggle_new_phone_setup)
        self.setup_toggle_btn.setVisible(False)
        setup_toggle_row.addWidget(self.setup_toggle_btn)
        setup_toggle_row.addStretch()
        box_layout.addLayout(setup_toggle_row)

        profile_box, profile_layout, _ = self.card(
            "Policy Profiles",
            "One-click groups for a managed phone. Profiles only use Android Device Owner policies and can always be reversed with Full Access.",
        )

        profile_buttons = QHBoxLayout()

        focus_btn = QPushButton("Focus Mode")
        focus_btn.setObjectName("primary")
        focus_btn.clicked.connect(lambda: self.apply_policy_profile("focus"))

        guest_btn = QPushButton("Guest Mode")
        guest_btn.clicked.connect(lambda: self.apply_policy_profile("guest"))

        repair_btn = QPushButton("Repair Mode")
        repair_btn.clicked.connect(lambda: self.apply_policy_profile("repair"))

        full_btn = QPushButton("Full Access")
        full_btn.clicked.connect(lambda: self.apply_policy_profile("full"))

        profile_buttons.addWidget(focus_btn)
        profile_buttons.addWidget(guest_btn)
        profile_buttons.addWidget(repair_btn)
        profile_buttons.addWidget(full_btn)
        profile_layout.addLayout(profile_buttons)

        self.profile_status_label = QLabel(
            "Profile: none applied. Focus blocks entertainment/social; Guest and Repair protect sensitive apps; Full Access restores them."
        )
        self.profile_status_label.setObjectName("sideStatus")
        self.profile_status_label.setWordWrap(True)
        self.profile_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        profile_layout.addWidget(self.profile_status_label)

        copy_profile_status = QPushButton("Copy Profile Status")
        copy_profile_status.clicked.connect(self.copy_profile_status)
        profile_layout.addWidget(copy_profile_status)

        box_layout.addWidget(profile_box)

        self.app_control_package = QLineEdit()
        self.app_control_package.setPlaceholderText("Package name, e.g. com.android.settings")
        self.app_control_package.textChanged.connect(self._schedule_app_status_check)
        box_layout.addWidget(self.app_control_package)

        self.app_status_label = QLabel("App status: enter or select a package")
        self.app_status_label.setObjectName("big")
        self.app_status_label.setWordWrap(True)
        box_layout.addWidget(self.app_status_label)

        presets = QHBoxLayout()
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(lambda: self.app_control_package.setText("com.android.settings"))
        fdroid_btn = QPushButton("F-Droid")
        fdroid_btn.clicked.connect(lambda: self.app_control_package.setText("org.fdroid.fdroid"))
        aurora_btn = QPushButton("Aurora")
        aurora_btn.clicked.connect(lambda: self.app_control_package.setText("com.aurora.store"))
        presets.addWidget(settings_btn)
        presets.addWidget(fdroid_btn)
        presets.addWidget(aurora_btn)
        box_layout.addLayout(presets)

        rules = QHBoxLayout()

        suspend = QPushButton("Suspend App")
        suspend.setObjectName("danger")
        suspend.clicked.connect(lambda: self.send_app_policy("suspend"))

        unsuspend = QPushButton("Unsuspend App")
        unsuspend.clicked.connect(lambda: self.send_app_policy("unsuspend"))

        block_uninstall = QPushButton("Block Uninstall")
        block_uninstall.clicked.connect(lambda: self.send_app_policy("block_uninstall"))

        allow_uninstall = QPushButton("Allow Uninstall")
        allow_uninstall.clicked.connect(lambda: self.send_app_policy("allow_uninstall"))

        self.app_policy_buttons = [suspend, unsuspend, block_uninstall, allow_uninstall]
        for button in self.app_policy_buttons:
            button.setEnabled(False)

        rules.addWidget(suspend)
        rules.addWidget(unsuspend)
        rules.addWidget(block_uninstall)
        rules.addWidget(allow_uninstall)
        box_layout.addLayout(rules)

        installs = QHBoxLayout()

        block_installs = QPushButton("Block App Installs")
        block_installs.setObjectName("danger")
        block_installs.clicked.connect(lambda: self.send_app_policy("block_installs", package_required=False))

        allow_installs = QPushButton("Allow App Installs")
        allow_installs.clicked.connect(lambda: self.send_app_policy("allow_installs", package_required=False))

        self.app_policy_buttons.extend([block_installs, allow_installs])
        for button in (block_installs, allow_installs):
            button.setEnabled(False)

        installs.addWidget(block_installs)
        installs.addWidget(allow_installs)
        box_layout.addLayout(installs)

        self.app_control_mode_label = QLabel("Mode: READ-ONLY until Device Owner is configured")
        self.app_control_mode_label.setObjectName("big")
        self.app_control_mode_label.setWordWrap(True)
        box_layout.addWidget(self.app_control_mode_label)

        self.app_control_packages = QTextEdit()
        self.app_control_packages.setReadOnly(True)
        self.app_control_packages.setMinimumHeight(180)
        self.app_control_packages.setText(
            "Package Installer and system package names vary by Android/OEM.\n"
            "Use Find Control Packages before creating rules.\n\n"
            "Android may refuse to suspend critical system packages; PhoneHub reports that instead of forcing it."
        )
        box_layout.addWidget(self.app_control_packages)

        layout.addWidget(box)

        note, _, _ = self.card(
            "Provisioning requirement",
            "App suspension and install restrictions require PhoneHub Notifier to be Device Owner (or an appropriate managed profile owner). "
            "This is intended for a phone you own/manage. Device Owner provisioning is not performed automatically and may require a freshly provisioned device.",
        )
        layout.addWidget(note)
        layout.addStretch()
        QTimer.singleShot(350, self.check_device_owner_status)
        return page

    def toggle_new_phone_setup(self):
        if not hasattr(self, "provision_box"):
            return
        visible = not self.provision_box.isVisible()
        self.provision_box.setVisible(visible)
        if hasattr(self, "setup_toggle_btn"):
            self.setup_toggle_btn.setText(
                "Hide New Phone Setup" if visible else "Show New Phone Setup"
            )

    def _set_provision_status(self, lines):
        if not isinstance(lines, (list, tuple)):
            lines = [str(lines)]
        text = "\n".join(str(line) for line in lines)
        if hasattr(self, "provision_status"):
            self.provision_status.setText(text)
        self.set_footer(lines[-1] if lines else "Provisioning check complete.")

    def _companion_apk_path(self):
        app_dir = Path(r"C:\PhoneHub\app")

        def version_key(path):
            match = re.search(r"-v(\d+(?:\.\d+)*)\.apk$", path.name, flags=re.IGNORECASE)
            if not match:
                return ()
            return tuple(int(part) for part in match.group(1).split("."))

        versioned = [p for p in app_dir.glob("PhoneHubNotifier-v*.apk") if p.exists()]
        if versioned:
            return max(versioned, key=version_key)

        fallback = app_dir / "PhoneHubNotifier.apk"
        return fallback if fallback.exists() else None

    def _account_count(self, target):
        output = run_quiet(["adb", "-s", target, "shell", "dumpsys", "account"], timeout=12)
        match = re.search(r"^\s*Accounts:\s*(\d+)\s*$", output, flags=re.MULTILINE)
        return (int(match.group(1)) if match else None), output

    def provision_phone_check(self):
        target = self._app_control_target()
        if not target:
            self._set_provision_status([
                "FAIL: No phone connected.",
                "Connect USB and accept the USB debugging prompt on the phone.",
            ])
            return

        lines = [f"Phone: {target}"]

        package_dump = run_quiet(
            ["adb", "-s", target, "shell", "dumpsys", "package", "com.phonehub.notifier"],
            timeout=10,
        )
        installed = "versionName=" in package_dump
        receiver_ready = "PhoneHubDeviceAdminReceiver" in package_dump

        version_match = re.search(r"versionName=([^\s]+)", package_dump)
        version_name = version_match.group(1) if version_match else "not installed"
        lines.append(f"Companion: {'PASS' if installed else 'NEEDS INSTALL'} ({version_name})")
        lines.append(f"Device Admin receiver: {'PASS' if receiver_ready else 'NEEDS UPDATE'}")

        owners = run_quiet(["adb", "-s", target, "shell", "dpm", "list-owners"], timeout=8)
        is_owner = "com.phonehub.notifier/.PhoneHubDeviceAdminReceiver" in owners and "DeviceOwner" in owners
        lines.append(f"Device Owner: {'READY' if is_owner else 'NOT CONFIGURED'}")

        account_count, _ = self._account_count(target)
        if account_count is None:
            lines.append("Accounts: could not read")
        else:
            lines.append(f"Accounts: {account_count} {'(READY)' if account_count == 0 else '(REMOVE TEMPORARILY)'}")

        if is_owner:
            lines.append("READY: This phone is already managed by PhoneHub.")
        elif not installed or not receiver_ready:
            lines.append("NEXT: Press 'Install / Update Companion'.")
        elif account_count and account_count > 0:
            lines.append("NEXT: Press '2. Open Accounts' and temporarily remove all accounts.")
        elif account_count == 0:
            lines.append("NEXT: Press '3. Provision Device Owner'.")
        else:
            lines.append("NEXT: Resolve the failed check above, then run Check New Phone again.")

        self._set_provision_status(lines)

    def install_latest_companion(self):
        target = self._app_control_target()
        if not target:
            self._set_provision_status("FAIL: No phone connected.")
            return

        apk = self._companion_apk_path()
        if not apk:
            self._set_provision_status([
                "FAIL: PhoneHub Notifier APK not found.",
                r"Expected under C:\PhoneHub\app\PhoneHubNotifier-v*.apk",
            ])
            return

        package_dump = run_quiet(
            ["adb", "-s", target, "shell", "dumpsys", "package", "com.phonehub.notifier"],
            timeout=10,
        )
        installed = "versionName=" in package_dump
        version_match = re.search(r"versionName=([^\s]+)", package_dump)
        installed_version = version_match.group(1) if version_match else "not installed"

        owners = run_quiet(["adb", "-s", target, "shell", "dpm", "list-owners"], timeout=8)
        is_owner = (
            "com.phonehub.notifier/.PhoneHubDeviceAdminReceiver" in owners
            and "DeviceOwner" in owners
        )

        if installed and is_owner:
            self._set_provision_status([
                f"PROTECTED: PhoneHub Notifier {installed_version} is already Device Owner.",
                f"Selected APK: {apk.name}",
                "PhoneHub will not replace or uninstall the Device Owner APK automatically.",
                "Use a separate test phone for a differently signed APK.",
            ])
            return

        self._set_provision_status([
            f"Installing from PhoneHub: {apk.name}",
            f"Target phone: {target}",
        ])

        install_args = ["adb", "-s", target, "install"]
        if installed:
            install_args.append("-r")
        install_args.append(str(apk))

        result = run_quiet(install_args, timeout=90)
        if "Success" not in result:
            detail = result or "No output returned."
            if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in detail:
                self._set_provision_status([
                    "APK install blocked: signing key does not match the installed app.",
                    f"Installed version: {installed_version}",
                    f"Selected APK: {apk.name}",
                    "Do not uninstall a Device Owner app to work around this.",
                ])
            else:
                self._set_provision_status(["APK install failed:", detail])
            return

        self._set_provision_status([
            f"PASS: Installed {apk.name}",
            "NEXT: Press '1. Check New Phone'.",
        ])

    def open_android_accounts(self):
        target = self._app_control_target()
        if not target:
            self._set_provision_status("FAIL: No phone connected.")
            return

        run_quiet(
            ["adb", "-s", target, "shell", "am", "start", "-a", "android.settings.SYNC_SETTINGS"],
            timeout=8,
        )
        count, _ = self._account_count(target)
        self._set_provision_status([
            "Accounts settings opened on the phone.",
            f"Current Android account count: {count if count is not None else 'unknown'}",
            "Temporarily remove every listed account. Do not uninstall the apps.",
            "Then press '1. Check New Phone' again.",
        ])

    def clear_stale_account_session(self):
        target = self._app_control_target()
        if not target:
            self._set_provision_status("FAIL: No phone connected.")
            return

        count, output = self._account_count(target)
        if count not in (0, None):
            self._set_provision_status([
                f"Accounts are not empty ({count}).",
                "Remove the accounts first; stale-session repair is only for Accounts: 0.",
            ])
            return

        answer = QMessageBox.question(
            self,
            "Reboot phone?",
            "PhoneHub will force-stop common account apps and reboot the phone to clear stale AccountManager sessions. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        for package in (
            "com.whatsapp",
            "com.viber.voip",
            "com.azure.authenticator",
            "com.twitter.android",
        ):
            run_quiet(["adb", "-s", target, "shell", "am", "force-stop", package], timeout=5)

        run_quiet(["adb", "-s", target, "reboot"], timeout=8)
        self._set_provision_status([
            "Phone reboot requested.",
            "Wait for Android to boot fully and unlock the phone.",
            "Then press '1. Check New Phone' and '3. Provision Device Owner'.",
        ])

    def provision_device_owner(self):
        target = self._app_control_target()
        if not target:
            self._set_provision_status("FAIL: No phone connected.")
            return

        package_dump = run_quiet(
            ["adb", "-s", target, "shell", "dumpsys", "package", "com.phonehub.notifier"],
            timeout=10,
        )
        if "PhoneHubDeviceAdminReceiver" not in package_dump:
            self._set_provision_status([
                "STOP: Device Admin receiver is missing.",
                "Press 'Install / Update Companion' first.",
            ])
            return

        owners = run_quiet(["adb", "-s", target, "shell", "dpm", "list-owners"], timeout=8)
        if "com.phonehub.notifier/.PhoneHubDeviceAdminReceiver" in owners and "DeviceOwner" in owners:
            self._set_provision_status("READY: PhoneHub Notifier is already Device Owner.")
            self.check_device_owner_status()
            return

        count, _ = self._account_count(target)
        if count is None:
            self._set_provision_status("STOP: Could not verify Android account count.")
            return
        if count > 0:
            self._set_provision_status([
                f"STOP: Android still has {count} account(s).",
                "Press '2. Open Accounts' and temporarily remove all accounts first.",
            ])
            return

        answer = QMessageBox.question(
            self,
            "Provision Device Owner",
            "Accounts: 0 and the PhoneHub admin receiver is ready. Set PhoneHub Notifier as Device Owner on this phone?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        result = run_quiet([
            "adb", "-s", target, "shell", "dpm", "set-device-owner",
            "com.phonehub.notifier/.PhoneHubDeviceAdminReceiver",
        ], timeout=15)

        if "Success:" in result:
            verify = run_quiet(["adb", "-s", target, "shell", "dpm", "list-owners"], timeout=8)
            self._set_provision_status([
                "SUCCESS: PhoneHub Notifier is Device Owner.",
                verify or "Owner verification returned no output.",
                "You can now add your accounts back to the phone.",
            ])
            self.check_device_owner_status()
            return

        if "already some accounts" in result.lower():
            self._set_provision_status([
                "Android still reports an account/session even though the visible count may be zero.",
                "Press 'Clear Stale Account Session + Reboot', wait for the phone to boot, then retry.",
            ])
            return

        self._set_provision_status([
            "Device Owner provisioning failed:",
            result or "No output returned.",
        ])

    def _app_control_target(self):
        return self._device_target()

    def check_device_owner_status(self):
        target = self._app_control_target()
        if not target:
            if hasattr(self, "app_control_status"):
                self.app_control_status.setText("Status: Phone not connected")
            return

        owners = run_quiet(["adb", "-s", target, "shell", "dpm", "list-owners"], timeout=8)
        policy = run_quiet(["adb", "-s", target, "shell", "dumpsys", "device_policy"], timeout=12)
        output = owners or policy

        installed = "com.phonehub.notifier" in run_quiet(
            ["adb", "-s", target, "shell", "pm", "list", "packages", "com.phonehub.notifier"],
            timeout=6,
        )

        receiver_dump = run_quiet(
            ["adb", "-s", target, "shell", "dumpsys", "package", "com.phonehub.notifier"],
            timeout=10,
        )
        admin_receiver_present = (
            "PhoneHubDeviceAdminReceiver" in receiver_dump
            or (
                "com.phonehub.notifier/.PhoneHubDeviceAdminReceiver" in owners
                and "DeviceOwner" in owners
            )
        )

        combined = (owners + "\n" + policy)
        combined_lower = combined.lower()

        # Detect an actual Device Owner assignment, not incidental mentions such as
        # "Device Owner Type: -1" or package listings inside dumpsys output.
        owner_patterns = [
            r"device\s+owner[^\n]*com\.phonehub\.notifier",
            r"deviceowner[^\n]*com\.phonehub\.notifier",
            r"owner\s+component[^\n]*com\.phonehub\.notifier",
            r"com\.phonehub\.notifier/\.phonehubdeviceadminreceiver",
        ]
        explicit_owner_match = any(
            re.search(pattern, combined, flags=re.IGNORECASE)
            for pattern in owner_patterns
        )

        explicit_no_owner = bool(
            re.search(r"device\s+owner\s+type\s*:\s*-1", policy, flags=re.IGNORECASE)
            or re.search(r"no\s+device\s+owner", owners, flags=re.IGNORECASE)
        )

        is_owner = explicit_owner_match and not explicit_no_owner

        provisioned = bool(
            "device provisioned: true" in policy.lower()
            or "musersetupcomplete=true" in policy.lower()
            or "musersetupcomplete: true" in policy.lower()
        )

        enabled_admin = bool(
            re.search(
                r"enabled\s+device\s+admins[\s\S]{0,1200}com\.phonehub\.notifier",
                policy,
                flags=re.IGNORECASE,
            )
        )

        if is_owner:
            summary = (
                "Status: Device Owner READY\n"
                f"Companion installed: {'YES' if installed else 'NO'}\n"
                f"Device Admin receiver: {'READY' if admin_receiver_present else 'MISSING / OLD APK'}\n"
                "App suspension: AVAILABLE\n"
                "Install restrictions: AVAILABLE\n"
                "Uninstall protection: AVAILABLE"
            )
        else:
            summary = (
                "Status: Device Owner NOT CONFIGURED\n"
                f"Companion installed: {'YES' if installed else 'NO'}\n"
                f"Device Admin receiver: {'READY' if admin_receiver_present else 'MISSING / OLD APK'}\n"
                f"Device already provisioned: {'YES' if provisioned else 'NO'}\n"
                f"Device Admin enabled: {'YES' if enabled_admin else 'NO'}\n"
                "App suspension: UNAVAILABLE\n"
                "Install restrictions: UNAVAILABLE\n"
                "Uninstall protection: UNAVAILABLE"
            )
            if provisioned:
                summary += (
                    "\n\nThis phone is already provisioned. "
                    "PhoneHub will not attempt Device Owner provisioning automatically."
                )

        if hasattr(self, "app_control_status"):
            self.app_control_status.setText(summary)

        if hasattr(self, "app_policy_buttons"):
            for button in self.app_policy_buttons:
                button.setEnabled(is_owner)

        if hasattr(self, "app_control_mode_label"):
            self.app_control_mode_label.setText(
                "Mode: ACTIVE POLICY CONTROL"
                if is_owner else
                "Mode: READ-ONLY — this phone is already provisioned and PhoneHub is not Device Owner"
            )

        if hasattr(self, "managed_phone_banner"):
            self.managed_phone_banner.setText(
                "Managed phone — Device Owner active. Daily App Control is ready."
                if is_owner else
                "Phone not fully managed yet — use New Phone Setup to finish provisioning."
            )

        if hasattr(self, "provision_box"):
            self.provision_box.setVisible(not is_owner)

        if hasattr(self, "setup_toggle_btn"):
            self.setup_toggle_btn.setVisible(is_owner)
            self.setup_toggle_btn.setText("Show New Phone Setup")

        if hasattr(self, "app_control_packages"):
            report = [
                "PHONEHUB APP CONTROL DIAGNOSTICS",
                "",
                summary,
                "",
                "Android Device Policy Manager:",
                policy[:6000] if policy else "No device_policy output returned.",
            ]
            self.app_control_packages.setText("\n".join(report))

    def open_phonehub_companion(self):
        target = self._app_control_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return

        result = run_quiet([
            "adb", "-s", target, "shell", "am", "start",
            "-n", "com.phonehub.notifier/.MainActivity",
        ], timeout=8)

        if "Error" in result or "Exception" in result:
            self.set_footer("Could not open PhoneHub Notifier.")
        else:
            self.set_footer("PhoneHub Notifier opened on the phone.")

    def scan_control_packages(self):
        target = self._app_control_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return

        output = run_quiet(["adb", "-s", target, "shell", "pm", "list", "packages"], timeout=15)
        keywords = (
            "settings", "packageinstaller", "permissioncontroller",
            "fdroid", "aurora", "vending", "appmarket", "market"
        )

        matches = []
        for line in output.splitlines():
            pkg = line.replace("package:", "").strip()
            if any(word in pkg.lower() for word in keywords):
                matches.append(pkg)

        text = "Detected control/store packages:\n\n" + (
            "\n".join(matches[:80]) if matches else "No matching packages found."
        )
        if hasattr(self, "app_control_packages"):
            self.app_control_packages.setText(text)
        self.set_footer("Package scan complete.")

    def copy_profile_status(self):
        text = self.profile_status_label.text() if hasattr(self, "profile_status_label") else ""
        if not text:
            self.set_footer("No profile status to copy.")
            return
        QApplication.clipboard().setText(text)
        self.set_footer("Profile status copied to clipboard.")

    def _policy_profile_packages(self, name):
        profiles = {
            "focus": [
                "com.google.android.youtube",
                "com.spotify.music",
                "com.twitter.android",
                "com.google.android.apps.youtube.music",
                "com.google.android.videos",
                "com.oplus.games",
                "com.wondershare.filmorago",
            ],
            "guest": [
                "mv.com.bml.mib",
                "mv.com.mib.faisamobile",
                "mv.fahipay",
                "com.azure.authenticator",
                "com.google.android.gm",
                "com.whatsapp",
                "com.viber.voip",
                "com.google.android.apps.photos",
            ],
            "repair": [
                "mv.com.bml.mib",
                "mv.com.mib.faisamobile",
                "mv.fahipay",
                "com.azure.authenticator",
                "com.google.android.gm",
                "com.whatsapp",
                "com.viber.voip",
                "com.google.android.apps.photos",
                "com.microsoft.office.excel",
            ],
        }
        return profiles.get(name, [])

    def _installed_packages(self, target):
        output = run_quiet(["adb", "-s", target, "shell", "pm", "list", "packages"], timeout=15)
        return {
            line.replace("package:", "").strip()
            for line in output.splitlines()
            if line.startswith("package:")
        }

    def apply_policy_profile(self, name):
        target = self._app_control_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return

        owners = run_quiet(["adb", "-s", target, "shell", "dpm", "list-owners"], timeout=8)
        if "com.phonehub.notifier/.PhoneHubDeviceAdminReceiver" not in owners or "DeviceOwner" not in owners:
            self.set_footer("Device Owner is required for policy profiles.")
            return

        installed = self._installed_packages(target)

        if name == "full":
            packages = sorted({
                pkg
                for profile in ("focus", "guest", "repair")
                for pkg in self._policy_profile_packages(profile)
                if pkg in installed
            })
            action = "unsuspend_many"
            block_installs = False
            label = "Full Access"
        else:
            packages = [pkg for pkg in self._policy_profile_packages(name) if pkg in installed]
            action = "suspend_many"
            block_installs = name in ("guest", "repair")
            label = {
                "focus": "Focus Mode",
                "guest": "Guest Mode",
                "repair": "Repair Mode",
            }.get(name, name.title())

        if not packages and name != "full":
            if hasattr(self, "profile_status_label"):
                self.profile_status_label.setText(f"{label}: no matching apps are installed.")
            return

        # Compatibility path: apply one package at a time using the original
        # PhoneHub Notifier v1.1 policy actions. This avoids requiring an APK
        # replacement just to use desktop policy profiles.
        single_action = "unsuspend" if name == "full" else "suspend"
        changed = 0
        refused = []

        for pkg in packages:
            result = run_quiet([
                "adb", "-s", target, "shell", "am", "start",
                "-n", "com.phonehub.notifier/.MainActivity",
                "--es", "policy_action", single_action,
                "--es", "package", pkg,
            ], timeout=10)

            if "Error" in result or "Exception" in result:
                refused.append(pkg)
            else:
                changed += 1

        install_action = "block_installs" if block_installs else "allow_installs"
        install_result = run_quiet([
            "adb", "-s", target, "shell", "am", "start",
            "-n", "com.phonehub.notifier/.MainActivity",
            "--es", "policy_action", install_action,
        ], timeout=10)

        if hasattr(self, "profile_status_label"):
            if name == "full":
                msg = f"Profile: Full Access — restore sent to {changed} managed apps; app installation allowed."
            else:
                install_text = " App installation blocked." if block_installs else ""
                msg = f"Profile: {label} — suspend sent to {changed} installed apps.{install_text}"

            if refused:
                msg += f" Could not send policy to: {', '.join(refused[:4])}"
            self.profile_status_label.setText(msg)

        self.set_footer(f"{label} applied with PhoneHub Notifier v1.1 compatibility.")
        QTimer.singleShot(1600, self.check_device_owner_status)

    def _schedule_app_status_check(self):
        if hasattr(self, "app_status_timer"):
            self.app_status_timer.start()

    def check_selected_app_status(self):
        target = self._app_control_target()
        pkg = self.app_control_package.text().strip() if hasattr(self, "app_control_package") else ""

        if not pkg:
            if hasattr(self, "app_status_label"):
                self.app_status_label.setText("App status: enter or select a package")
            return

        if not target:
            if hasattr(self, "app_status_label"):
                self.app_status_label.setText(f"{pkg}: PHONE NOT CONNECTED")
            return

        path_output = run_quiet(
            ["adb", "-s", target, "shell", "pm", "path", pkg],
            timeout=6,
        )
        installed = bool(path_output and "package:" in path_output)

        if not installed:
            status = "NOT INSTALLED"
        else:
            dump = run_quiet(
                ["adb", "-s", target, "shell", "dumpsys", "package", pkg],
                timeout=10,
            )
            suspended = bool(
                re.search(r"\bsuspended\s*=\s*true\b", dump, flags=re.IGNORECASE)
                or re.search(r"\bsuspended=true\b", dump, flags=re.IGNORECASE)
            )
            enabled_setting = ""
            m = re.search(r"enabled=(\d+)", dump)
            if m:
                enabled_setting = m.group(1)

            if suspended:
                status = "SUSPENDED"
            elif enabled_setting and enabled_setting != "0":
                status = "DISABLED"
            else:
                status = "ACTIVE"

        if hasattr(self, "app_status_label"):
            self.app_status_label.setText(f"App status: {pkg} — {status}")

        return status

    def send_app_policy(self, action, package_required=True):
        target = self._app_control_target()
        if not target:
            self.set_footer("Phone is not connected.")
            return

        owners = run_quiet(["adb", "-s", target, "shell", "dpm", "list-owners"], timeout=8)
        policy = run_quiet(["adb", "-s", target, "shell", "dumpsys", "device_policy"], timeout=10)
        combined = owners + "\n" + policy

        owner_patterns = [
            r"device\s+owner[^\n]*com\.phonehub\.notifier",
            r"deviceowner[^\n]*com\.phonehub\.notifier",
            r"owner\s+component[^\n]*com\.phonehub\.notifier",
            r"com\.phonehub\.notifier/\.phonehubdeviceadminreceiver",
        ]
        actual_owner = any(
            re.search(pattern, combined, flags=re.IGNORECASE)
            for pattern in owner_patterns
        )
        no_owner = bool(
            re.search(r"device\s+owner\s+type\s*:\s*-1", policy, flags=re.IGNORECASE)
            or re.search(r"no\s+device\s+owner", owners, flags=re.IGNORECASE)
        )

        if not actual_owner or no_owner:
            if hasattr(self, "app_control_status"):
                self.app_control_status.setText(
                    "Status: Device Owner NOT CONFIGURED\n"
                    "Policy action not sent. App Control remains read-only on this phone."
                )
            self.set_footer("Device Owner is required before applying App Control policies.")
            return

        pkg = self.app_control_package.text().strip() if hasattr(self, "app_control_package") else ""
        if package_required and not pkg:
            self.set_footer("Enter or select a package first.")
            return

        cmd = [
            "adb", "-s", target, "shell", "am", "start",
            "-n", "com.phonehub.notifier/.MainActivity",
            "--es", "policy_action", action,
        ]
        if pkg:
            cmd.extend(["--es", "package", pkg])

        result = run_quiet(cmd, timeout=10)
        if "Error" in result or "Exception" in result:
            self.set_footer("Policy command could not be sent.")
            return

        label = action.replace("_", " ").title()
        if hasattr(self, "app_control_status"):
            self.app_control_status.setText(f"Status: Sent {label} to companion")

        if package_required and pkg:
            if hasattr(self, "app_status_label"):
                self.app_status_label.setText(f"App status: {pkg} — VERIFYING...")
            QTimer.singleShot(1400, self.check_selected_app_status)

        self.set_footer(f"App Control: {label} sent. Auto-verification running.")

    def page_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        ip, port = get_saved_ip()
        shown_ip = ip or "Not set"
        shown_target = f"{ip}:{port}" if ip else "Not set"

        text = (
            f"PhoneHub {APP_VERSION}\n\n"
            f"Saved Phone IP: {shown_ip}\n"
            f"ADB Target: {shown_target}\n\n"
            f"Mobile requirement: Tailscale only.\n"
            f"Screen/control works through Tailscale + ADB.\n"
            f"Audio page uses scrcpy microphone forwarding.\n"
            f"No audio recording is enabled by default.\n\n"
            f"Daily use:\n"
            f"1. Keep Tailscale ON on PC\n"
            f"2. Keep Tailscale ON on phone\n"
            f"3. Open PhoneHub\n"
            f"4. Use Home / Screen / Camera / Audio / Files / Apps / Control / Device / Notifications / App Control\n\n"
            f"For a new phone or repairs, use Setup."
        )

        info, _, _ = self.card("Settings", text)
        layout.addWidget(info)

        link_box, link_layout, _ = self.card(
            "PhoneHub One Private Link",
            "One-click pairing over USB. PhoneHub generates the keys, detects the PC LAN address, configures both WireGuard peers, starts the PC tunnel, and opens Android's VPN permission screen.",
        )

        pair_link = QPushButton("One-Click Pair PhoneHub One")
        pair_link.setObjectName("primary")
        pair_link.setMinimumHeight(44)
        pair_link.clicked.connect(self.pair_phonehub_one_private_link)
        link_layout.addWidget(pair_link)

        self.private_link_status = QLabel(
            "Status: Connect the phone by USB and install PhoneHub One."
        )
        self.private_link_status.setObjectName("sideStatus")
        self.private_link_status.setWordWrap(True)
        self.private_link_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        link_layout.addWidget(self.private_link_status)

        layout.addWidget(link_box)

        engine_box, engine_layout, _ = self.card(
            "PhoneHub Engine",
            "PhoneHub now prefers its own portable scrcpy/ADB runtime under C:\\PhoneHub\\runtime\\scrcpy instead of depending only on Windows PATH.",
        )

        engine_actions = QHBoxLayout()
        engine_check = QPushButton("Check Engine")
        engine_check.setObjectName("primary")
        engine_check.clicked.connect(self.check_engine_runtime)

        open_runtime = QPushButton("Open Runtime Folder")
        open_runtime.clicked.connect(self.open_engine_runtime_folder)

        engine_actions.addWidget(engine_check)
        engine_actions.addWidget(open_runtime)
        engine_layout.addLayout(engine_actions)

        self.engine_status_label = QLabel("Engine status: not checked yet")
        self.engine_status_label.setObjectName("big")
        self.engine_status_label.setWordWrap(True)
        self.engine_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        engine_layout.addWidget(self.engine_status_label)

        layout.addWidget(engine_box)
        layout.addStretch()
        return page

    def _wireguard_tools(self):
        candidates = [
            (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WireGuard" / "wg.exe",
             Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WireGuard" / "wireguard.exe"),
        ]
        for wg, wireguard in candidates:
            if wg.exists() and wireguard.exists():
                return str(wg), str(wireguard)
        wg = shutil.which("wg")
        wireguard = shutil.which("wireguard")
        return wg, wireguard

    def _detect_lan_ipv4(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except Exception:
            pass
        finally:
            try:
                sock.close()
            except Exception:
                pass
        return ""

    def pair_phonehub_one_private_link(self):
        target = self._app_control_target()
        if not target:
            if hasattr(self, "private_link_status"):
                self.private_link_status.setText("Status: No USB phone detected.")
            self.set_footer("Connect the phone by USB first.")
            return

        packages = run_quiet(
            ["adb", "-s", target, "shell", "pm", "list", "packages", "com.phonehub.one"],
            timeout=8,
        )
        if "com.phonehub.one" not in packages:
            if hasattr(self, "private_link_status"):
                self.private_link_status.setText("Status: PhoneHub One is not installed on the phone.")
            self.set_footer("Install PhoneHub One first.")
            return

        wg, wireguard = self._wireguard_tools()
        if not wg or not wireguard:
            if hasattr(self, "private_link_status"):
                self.private_link_status.setText("Status: WireGuard for Windows is not installed.")
            self.set_footer("Install WireGuard for Windows first.")
            return

        lan_ip = self._detect_lan_ipv4()
        if not lan_ip:
            if hasattr(self, "private_link_status"):
                self.private_link_status.setText("Status: Could not detect the PC LAN IPv4 address.")
            self.set_footer("Could not detect PC LAN address.")
            return

        vpn_dir = Path(r"C:\PhoneHub\runtime\vpn")
        vpn_dir.mkdir(parents=True, exist_ok=True)
        pc_private_path = vpn_dir / "pc_private.key"
        pc_public_path = vpn_dir / "pc_public.key"
        config_path = vpn_dir / "PhoneHubVPN.conf"

        if pc_private_path.exists():
            pc_private = pc_private_path.read_text(encoding="utf-8").strip()
        else:
            pc_private = run_quiet([wg, "genkey"], timeout=8).strip()
            if not pc_private:
                self.set_footer("Could not generate PC WireGuard key.")
                return
            pc_private_path.write_text(pc_private, encoding="utf-8")

        pc_public = run_quiet(
            ["powershell", "-NoProfile", "-Command",
             f"$k='{pc_private.replace("'", "''")}'; $k | & '{wg}' pubkey"],
            timeout=8,
        ).strip()
        if not pc_public:
            self.set_footer("Could not derive PC WireGuard public key.")
            return
        pc_public_path.write_text(pc_public, encoding="utf-8")

        phone_private = run_quiet([wg, "genkey"], timeout=8).strip()
        if not phone_private:
            self.set_footer("Could not generate phone WireGuard key.")
            return

        phone_public = run_quiet(
            ["powershell", "-NoProfile", "-Command",
             f"$k='{phone_private.replace("'", "''")}'; $k | & '{wg}' pubkey"],
            timeout=8,
        ).strip()
        if not phone_public:
            self.set_footer("Could not derive phone WireGuard public key.")
            return

        config = (
            "[Interface]\n"
            f"PrivateKey = {pc_private}\n"
            "Address = 10.77.0.1/24\n"
            "ListenPort = 51820\n\n"
            "[Peer]\n"
            f"PublicKey = {phone_public}\n"
            "AllowedIPs = 10.77.0.2/32\n"
        )
        config_path.write_text(config, encoding="ascii")

        try:
            subprocess.run(
                [wireguard, "/uninstalltunnelservice", "PhoneHubVPN"],
                capture_output=True, text=True, timeout=15,
            )
        except Exception:
            pass

        install = subprocess.run(
            [wireguard, "/installtunnelservice", str(config_path)],
            capture_output=True, text=True, timeout=20,
        )
        if install.returncode != 0:
            detail = (install.stdout or "") + "\n" + (install.stderr or "")
            if hasattr(self, "private_link_status"):
                self.private_link_status.setText(
                    "Status: PC VPN could not start. " + detail.strip()[:300]
                )
            self.set_footer("PC WireGuard tunnel failed to start.")
            return

        cmd = [
            "adb", "-s", target, "shell", "am", "start",
            "-n", "com.phonehub.one/com.phonehub.notifier.MainActivity",
            "--ez", "auto_pair", "true",
            "--ez", "auto_connect", "true",
            "--es", "phone_address", "10.77.0.2/32",
            "--es", "private_key", phone_private,
            "--es", "public_key", phone_public,
            "--es", "pc_public_key", pc_public,
            "--es", "endpoint", f"{lan_ip}:51820",
            "--es", "allowed_ips", "10.77.0.1/32",
            "--es", "keepalive", "25",
        ]
        result = run_quiet(cmd, timeout=12)

        if "Error" in result or "Exception" in result:
            if hasattr(self, "private_link_status"):
                self.private_link_status.setText("Status: Phone pairing command failed.")
            self.set_footer("Could not open PhoneHub One pairing.")
            return

        if hasattr(self, "private_link_status"):
            self.private_link_status.setText(
                "Status: Paired. On the phone, approve the Android VPN permission once. "
                f"PC tunnel 10.77.0.1 ↔ Phone 10.77.0.2 · endpoint {lan_ip}:51820"
            )
        self.set_footer("Private link paired. Approve the VPN permission on the phone.")

    def check_engine_runtime(self):
        scrcpy = scrcpy_path()
        adb = shutil.which("adb")

        lines = []
        lines.append(f"scrcpy path: {scrcpy or 'NOT FOUND'}")
        lines.append(f"adb path: {adb or 'NOT FOUND'}")

        if scrcpy:
            version = run_quiet([scrcpy, "--version"], timeout=8)
            first = version.splitlines()[0] if version else "version unavailable"
            lines.append(f"scrcpy: {first}")

        if adb:
            version = run_quiet([adb, "version"], timeout=8)
            first = version.splitlines()[0] if version else "version unavailable"
            lines.append(f"adb: {first}")

        runtime_dir = Path(r"C:\PhoneHub\runtime\scrcpy")
        required = [
            "scrcpy.exe",
            "scrcpy-server",
            "adb.exe",
            "AdbWinApi.dll",
            "AdbWinUsbApi.dll",
            "SDL2.dll",
        ]
        present = [name for name in required if (runtime_dir / name).exists()]
        missing = [name for name in required if not (runtime_dir / name).exists()]

        lines.append(f"portable runtime: {'READY' if not missing else 'INCOMPLETE'}")
        lines.append(f"present: {', '.join(present) if present else 'none'}")
        if missing:
            lines.append(f"missing: {', '.join(missing)}")

        if hasattr(self, "engine_status_label"):
            self.engine_status_label.setText("\n".join(lines))

        self.set_footer("Engine check complete.")

    def open_engine_runtime_folder(self):
        folder = Path(r"C:\PhoneHub\runtime\scrcpy")
        folder.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(folder))
        except Exception:
            self.set_footer(f"Runtime folder: {folder}")

    def show_page(self, index):
        self.stack.setCurrentIndex(index)

        for i, btn in enumerate(self.nav_buttons):
            btn.setObjectName("navActive" if i == index else "nav")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        names = [
            "Home",
            "Setup",
            "Screen",
            "Camera",
            "Audio",
            "Files",
            "Apps",
            "Control",
            "Device",
            "Notifications",
            "App Control",
            "Settings",
        ]
        if 0 <= index < len(names):
            self.set_footer(f"Opened {names[index]} page.")

    def page_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        ip_box, ip_layout, _ = self.card(
            "Phone",
            "Saved Tailscale IP used for screen and control.",
        )

        self.dashboard_ip_input = QLineEdit()
        ip, _ = get_saved_ip()
        self.dashboard_ip_input.setText(ip)
        self.dashboard_ip_input.setPlaceholderText("100.x.x.x")
        ip_layout.addWidget(self.dashboard_ip_input)

        ip_actions = QHBoxLayout()
        ip_actions.setSpacing(6)

        save_connect = QPushButton("Connect")
        save_connect.setObjectName("primary")
        save_connect.clicked.connect(self.dashboard_save_and_connect)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_status)

        ip_actions.addWidget(save_connect)
        ip_actions.addWidget(refresh)
        ip_layout.addLayout(ip_actions)
        layout.addWidget(ip_box)

        box, _, self.device_info = self.card("Status", "Checking phone...")
        layout.addWidget(box)

        row = QHBoxLayout()
        row.setSpacing(6)

        open_screen = QPushButton("Open Screen")
        open_screen.setObjectName("primary")
        open_screen.clicked.connect(lambda: self.open_screen(READABLE_SCREEN, keep_alive=True))

        setup = QPushButton("Setup")
        setup.clicked.connect(lambda: self.show_page(1))

        row.addWidget(open_screen)
        row.addWidget(setup)
        layout.addLayout(row)

        # Keep the dashboard focused on connection and core device access.
        self.location_info = QLabel("")
        layout.addStretch()

        return page

    def page_setup_new_phone(self):
        """Simple one-path setup wizard.

        Only the action needed for the current step is shown. The wizard
        advances automatically whenever PhoneHub detects that a step is done.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header, header_layout, _ = self.card(
            "PhoneHub Setup",
            "Follow one step at a time. PhoneHub checks each step before moving forward.",
        )

        self.wizard_progress = QLabel("Step 1 of 6")
        self.wizard_progress.setObjectName("title")
        header_layout.addWidget(self.wizard_progress)
        layout.addWidget(header)

        step_box, step_layout, _ = self.card("Current step", "")
        self.wizard_title = QLabel("Connect phone by USB")
        self.wizard_title.setObjectName("title")
        self.wizard_title.setWordWrap(True)

        self.wizard_instruction = QLabel("")
        self.wizard_instruction.setObjectName("big")
        self.wizard_instruction.setWordWrap(True)

        self.wizard_status = QLabel("")
        self.wizard_status.setObjectName("sideStatus")
        self.wizard_status.setWordWrap(True)

        self.wizard_action_button = QPushButton("Check Again")
        self.wizard_action_button.setObjectName("primary")
        self.wizard_action_button.setMinimumHeight(48)
        self.wizard_action_button.clicked.connect(self.wizard_action)

        step_layout.addWidget(self.wizard_title)
        step_layout.addWidget(self.wizard_instruction)
        step_layout.addWidget(self.wizard_status)
        step_layout.addWidget(self.wizard_action_button)
        layout.addWidget(step_box)

        overview, overview_layout, _ = self.card("Setup path", "")
        self.wizard_steps_label = QLabel(
            "1  USB connection\n"
            "2  Unlock phone once\n"
            "3  Tailscale installed\n"
            "4  Tailscale connected + IP detected\n"
            "5  Remote control enabled\n"
            "6  Ready"
        )
        self.wizard_steps_label.setObjectName("big")
        self.wizard_steps_label.setWordWrap(True)
        overview_layout.addWidget(self.wizard_steps_label)
        layout.addWidget(overview)

        health_box, health_layout, _ = self.card(
            "System Check",
            "Check the complete PhoneHub path inside this app: PC tools, Tailscale, USB, phone, remote ADB and Android readiness."
        )

        health_actions = QHBoxLayout()
        health_actions.setSpacing(8)

        self.health_check_button = QPushButton("Run Check All")
        self.health_check_button.setObjectName("primary")
        self.health_check_button.setMinimumHeight(44)
        self.health_check_button.clicked.connect(self.run_health_check)

        refresh_setup = QPushButton("Retry Current Setup Step")
        refresh_setup.setMinimumHeight(44)
        refresh_setup.clicked.connect(self.wizard_action)

        health_actions.addWidget(self.health_check_button)
        health_actions.addWidget(refresh_setup)
        health_layout.addLayout(health_actions)

        self.health_summary = QLabel(
            "1. Platform-Tools      — Not checked\n"
            "2. scrcpy              — Not checked\n"
            "3. Python + PySide6     — Not checked\n"
            "4. PhoneHub + Git       — Not checked\n"
            "5. Tailscale PC         — Not checked\n"
            "6. USB + debugging      — Not checked\n"
            "7. Tailscale phone      — Not checked\n"
            "8. Remote ADB           — Not checked\n"
            "9. Android readiness    — Not checked"
        )
        self.health_summary.setObjectName("big")
        self.health_summary.setWordWrap(True)
        self.health_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        health_layout.addWidget(self.health_summary)

        self.health_overall = QLabel("Status: Not checked")
        self.health_overall.setObjectName("sideStatus")
        self.health_overall.setWordWrap(True)
        health_layout.addWidget(self.health_overall)

        layout.addWidget(health_box)

        layout.addStretch()
        QTimer.singleShot(200, self._render_wizard_step)
        return page

    def _set_wizard_step(self, step, status=""):
        step = max(1, min(6, int(step)))
        changed = step != self.wizard_step
        self.wizard_step = step
        if hasattr(self, "wizard_status") and status:
            self.wizard_status.setText(status)
        if changed or hasattr(self, "wizard_title"):
            self._render_wizard_step()

    def _render_wizard_step(self):
        if not hasattr(self, "wizard_title"):
            return

        step = self.wizard_step
        self.wizard_progress.setText(f"Step {step} of 6")

        if step == 1:
            self.wizard_title.setText("Connect phone by USB")
            self.wizard_instruction.setText(
                "Connect the phone with the USB cable. Keep USB debugging ON. "
                "If Android asks 'Allow USB debugging?', tap Always allow from this computer, then OK."
            )
            self.wizard_action_button.setText("Check Again")
        elif step == 2:
            self.wizard_title.setText("Unlock phone once")
            self.wizard_instruction.setText(
                "PhoneHub will wake the phone. Unlock it normally using fingerprint, face, PIN, pattern, or password. "
                "Then PhoneHub checks that it is unlocked."
            )
            self.wizard_action_button.setText("I Unlocked It - Check")
        elif step == 3:
            self.wizard_title.setText("Install Tailscale")
            self.wizard_instruction.setText(
                "PhoneHub checks whether Tailscale is installed. If it is missing, the local Tailscale APK in "
                "C:\\PhoneHub\\apps is installed automatically."
            )
            self.wizard_action_button.setText("Install / Check Tailscale")
        elif step == 4:
            self.wizard_title.setText("Connect Tailscale")
            self.wizard_instruction.setText(
                "Open Tailscale on the phone, sign in if needed, and turn it ON. "
                "PhoneHub will automatically detect the phone's 100.x.x.x Tailscale IP."
            )
            self.wizard_action_button.setText("Open Tailscale")
        elif step == 5:
            self.wizard_title.setText("Enable remote control")
            self.wizard_instruction.setText(
                "Keep USB connected for this one step. PhoneHub will enable ADB on port 5555 and test the Tailscale connection."
            )
            self.wizard_action_button.setText("Enable Remote + Test")
        else:
            self.wizard_title.setText("Setup complete")
            self.wizard_instruction.setText(
                "PhoneHub can reach the phone through Tailscale. You can now disconnect the USB cable and use Open Screen."
            )
            self.wizard_action_button.setText("Finish Setup")

        self.wizard_action_button.setEnabled(not self._wizard_busy)

    def _wizard_update_from_state(self, state):
        if not hasattr(self, "wizard_status"):
            return

        usb = state.get("usb", [])
        unauthorized = state.get("unauthorized", [])
        installed = state.get("installed", False)
        detected_ip = state.get("detected_ip", "")
        remote = state.get("remote", [])

        if unauthorized:
            self._set_wizard_step(
                1,
                "USB found, but debugging is not approved. Approve the popup on the phone, then press Check Again."
            )
            return

        if not usb:
            if self.wizard_step < 6:
                self._set_wizard_step(
                    1,
                    "Phone not detected by USB. Connect the cable, unlock the phone if needed, then press Check Again."
                )
            return

        self.wizard_serial = usb[0]

        if self.wizard_step == 1:
            self._set_wizard_step(2, f"USB connected: {self.wizard_serial}. Next: unlock the phone once.")

        if installed and self.wizard_step == 3:
            self._set_wizard_step(4, "Tailscale is installed. Next: connect Tailscale on the phone.")

        if detected_ip:
            self.wizard_detected_ip = detected_ip
            save_phone_ip(detected_ip, 5555)
            if self.wizard_step <= 4:
                self._set_wizard_step(5, f"Tailscale connected. IP detected automatically: {detected_ip}")

        if detected_ip:
            target = f"{detected_ip}:5555"
            self.wizard_remote_connected = target in remote
            if self.wizard_remote_connected and self.wizard_step <= 5:
                self._set_wizard_step(6, f"Remote control connected: {target}")

    def wizard_action(self):
        if self._wizard_busy:
            return

        if self.wizard_step == 1:
            self.wizard_status.setText("Checking USB connection...")
            self.auto_refresh_connection_state()
            return

        if self.wizard_step == 2:
            if not self.wizard_serial:
                self._set_wizard_step(1, "USB connection was lost. Connect the phone again.")
                return
            self._wizard_busy = True
            self._render_wizard_step()
            self.wizard_status.setText("Checking whether the phone is unlocked...")

            def worker():
                unlocked = self._is_device_unlocked(self.wizard_serial)
                self.auto_bridge.wizard.emit({"type": "unlock", "ok": unlocked})

            import threading
            threading.Thread(target=worker, daemon=True).start()
            return

        if self.wizard_step == 3:
            serial, error = self._usb_serial()
            if error:
                self._set_wizard_step(1, error)
                return
            if self._tailscale_installed(serial):
                self._set_wizard_step(4, "Tailscale is already installed.")
            else:
                self.install_tailscale_clicked()
                self.wizard_status.setText("Installing Tailscale. Wait for PhoneHub to detect it, then it will move to the next step.")
            return

        if self.wizard_step == 4:
            serial, error = self._usb_serial()
            if error:
                self._set_wizard_step(1, error)
                return
            if not self._tailscale_installed(serial):
                self._set_wizard_step(3, "Tailscale is not installed yet.")
                return
            run_background([
                "adb", "-s", serial, "shell", "monkey",
                "-p", TAILSCALE_PACKAGE,
                "-c", "android.intent.category.LAUNCHER",
                "1",
            ])
            self.wizard_status.setText(
                "Tailscale opened on the phone. Connect it there. PhoneHub will detect the IP automatically."
            )
            return

        if self.wizard_step == 5:
            if not self.wizard_serial:
                self._set_wizard_step(1, "USB connection was lost. Connect the phone again.")
                return
            if not self.wizard_detected_ip:
                self._set_wizard_step(4, "Tailscale IP is not detected yet. Connect Tailscale first.")
                return

            self._wizard_busy = True
            self._render_wizard_step()
            self.wizard_status.setText("Enabling remote ADB and testing connection...")

            serial = self.wizard_serial
            ip = self.wizard_detected_ip

            def worker():
                result = run_quiet(["adb", "-s", serial, "tcpip", "5555"], timeout=12)
                if "restarting in TCP mode" not in result.lower() and "5555" not in result:
                    self.auto_bridge.wizard.emit({
                        "type": "remote",
                        "ok": False,
                        "message": result or "Could not enable remote ADB."
                    })
                    return

                import time
                time.sleep(1.2)
                target = f"{ip}:5555"
                connect_text = run_quiet(["adb", "connect", target], timeout=10)
                devices = run_quiet(["adb", "devices"], timeout=5)
                ok = f"{target}\tdevice" in devices

                self.auto_bridge.wizard.emit({
                    "type": "remote",
                    "ok": ok,
                    "target": target,
                    "message": connect_text,
                })

            import threading
            threading.Thread(target=worker, daemon=True).start()
            return

        if self.wizard_step == 6:
            if self.wizard_detected_ip:
                save_phone_ip(self.wizard_detected_ip, 5555)
            self.wizard_status.setText("Setup saved. USB can now be disconnected.")
            self.set_footer("PhoneHub setup complete.")
            self.show_page(0)

    def _apply_wizard_result(self, result):
        self._wizard_busy = False
        kind = result.get("type")

        if kind == "unlock":
            if result.get("ok"):
                self._set_wizard_step(3, "Phone unlocked successfully. Checking Tailscale next.")
                self.auto_refresh_connection_state()
            else:
                self._set_wizard_step(
                    2,
                    "Phone still appears locked. Unlock it on the phone, then press 'I Unlocked It - Check' again."
                )
        elif kind == "remote":
            if result.get("ok"):
                target = result.get("target", "")
                self.wizard_remote_connected = True
                self._set_wizard_step(6, f"Remote control connected successfully: {target}")
                self.auto_refresh_connection_state()
            else:
                message = result.get("message", "Remote connection failed.")
                self._set_wizard_step(
                    5,
                    f"Remote control did not connect. Keep USB connected and press Enable Remote + Test again. Details: {message}"
                )

        self._render_wizard_step()

    def _health_state_line(self, index, name, state, detail=""):
        suffix = f" — {detail}" if detail else ""
        return f"{index}. {name:<19} — {state}{suffix}"

    def run_health_check(self):
        if self._health_busy:
            return

        self._health_busy = True
        if hasattr(self, "health_check_button"):
            self.health_check_button.setEnabled(False)
            self.health_check_button.setText("Checking...")
        if hasattr(self, "health_overall"):
            self.health_overall.setText("Status: Running all checks...")
        self.set_footer("Running PhoneHub system check in background...")

        def worker():
            results = []

            def add(name, state, detail=""):
                results.append({"name": name, "state": state, "detail": detail})

            # 1. Platform-Tools
            adb = shutil.which("adb")
            fastboot = shutil.which("fastboot")
            if adb and fastboot:
                version = run_quiet([adb, "version"], timeout=4).splitlines()
                add("Platform-Tools", "PASS", version[0] if version else "ADB + Fastboot found")
            elif adb:
                add("Platform-Tools", "WARN", "ADB found; Fastboot missing")
            else:
                add("Platform-Tools", "FAIL", "ADB not found")

            # 2. scrcpy
            scrcpy = scrcpy_path()
            if scrcpy:
                ver = run_quiet([scrcpy, "--version"], timeout=4).splitlines()
                add("scrcpy", "PASS", ver[0] if ver else "Ready")
            else:
                add("scrcpy", "FAIL", "scrcpy not found")

            # 3. Python + PySide6
            try:
                import PySide6
                add("Python + PySide6", "PASS", f"Python {sys.version_info.major}.{sys.version_info.minor}; PySide6 {PySide6.__version__}")
            except Exception:
                add("Python + PySide6", "FAIL", "PySide6 import failed")

            # 4. PhoneHub files + Git
            root = Path(r"C:\PhoneHub")
            launcher = root / "PhoneHub.bat"
            git_dir = root / ".git"
            if not launcher.exists():
                add("PhoneHub + Git", "FAIL", "PhoneHub.bat missing")
            elif not git_dir.exists():
                add("PhoneHub + Git", "WARN", "PhoneHub found; Git repo missing")
            else:
                git = shutil.which("git")
                if not git:
                    add("PhoneHub + Git", "WARN", "Git executable missing")
                else:
                    status = run_quiet([git, "-C", str(root), "status", "--porcelain"], timeout=5)
                    if status:
                        add("PhoneHub + Git", "WARN", "Local changes detected")
                    else:
                        branch = run_quiet([git, "-C", str(root), "branch", "--show-current"], timeout=4) or "main"
                        add("PhoneHub + Git", "PASS", f"Clean working tree; branch {branch}")

            # 5. Tailscale PC
            tailscale = shutil.which("tailscale")
            if not tailscale:
                for candidate in (
                    Path(r"C:\Program Files\Tailscale\tailscale.exe"),
                    Path(r"C:\Program Files (x86)\Tailscale\tailscale.exe"),
                ):
                    if candidate.exists():
                        tailscale = str(candidate)
                        break
            if tailscale:
                pc_ip = run_quiet([tailscale, "ip", "-4"], timeout=5).splitlines()
                if pc_ip:
                    add("Tailscale PC", "PASS", pc_ip[0])
                else:
                    add("Tailscale PC", "WARN", "Installed but not connected")
            else:
                add("Tailscale PC", "FAIL", "Not installed")

            # 6-8. Device path
            usb, remote, unauthorized, _ = parse_adb_devices()
            serial = usb[0] if usb else ""

            if unauthorized:
                add("USB + debugging", "WARN", "USB debugging authorization required")
            elif serial:
                model = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=4) or "Android phone"
                add("USB + debugging", "PASS", f"Connected: {model}")
            else:
                add("USB + debugging", "WARN", "USB not connected")

            detected_ip = ""
            installed = False
            if serial:
                installed = self._tailscale_installed(serial)
                if installed:
                    detected_ip = self._detect_tailscale_ip(serial)

            saved_ip, port = get_saved_ip()
            phone_ip = detected_ip or saved_ip

            if installed and detected_ip:
                add("Tailscale phone", "PASS", detected_ip)
            elif installed:
                add("Tailscale phone", "WARN", "Installed; no active 100.x.x.x IP detected")
            elif serial:
                add("Tailscale phone", "FAIL", "App not detected")
            elif saved_ip:
                add("Tailscale phone", "WARN", f"USB absent; saved IP {saved_ip}")
            else:
                add("Tailscale phone", "FAIL", "Cannot verify")

            target = f"{phone_ip}:{port}" if phone_ip else ""
            remote_ok = bool(target and target in remote)
            if remote_ok:
                add("Remote ADB", "PASS", target)
            elif target:
                add("Remote ADB", "WARN", f"Not connected: {target}")
            else:
                add("Remote ADB", "FAIL", "No phone Tailscale IP")

            # 9. Android readiness. Prefer remote target, then USB.
            check_target = target if remote_ok else serial
            if check_target:
                boot = run_quiet(["adb", "-s", check_target, "shell", "getprop", "sys.boot_completed"], timeout=5).strip()
                shell_echo = run_quiet(["adb", "-s", check_target, "shell", "echo", "PHONEHUB_READY"], timeout=5).strip()
                if boot == "1" and shell_echo == "PHONEHUB_READY":
                    add("Android readiness", "PASS", "Boot complete; ADB shell responsive")
                elif shell_echo == "PHONEHUB_READY":
                    add("Android readiness", "WARN", f"ADB responsive; boot_completed={boot or 'unknown'}")
                else:
                    add("Android readiness", "FAIL", "ADB shell not responsive")
            else:
                add("Android readiness", "FAIL", "No reachable device")

            self.auto_bridge.health.emit({"results": results})

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_health_results(self, payload):
        self._health_busy = False
        results = payload.get("results", [])

        if hasattr(self, "health_check_button"):
            self.health_check_button.setEnabled(True)
            self.health_check_button.setText("Run Check All")

        lines = []
        fail_count = 0
        warn_count = 0

        for index, item in enumerate(results, start=1):
            state = item.get("state", "UNKNOWN")
            name = item.get("name", "Check")
            detail = item.get("detail", "")
            if state == "FAIL":
                fail_count += 1
            elif state == "WARN":
                warn_count += 1
            lines.append(self._health_state_line(index, name, state, detail))

        if hasattr(self, "health_summary"):
            self.health_summary.setText("\n".join(lines))

        if fail_count:
            overall = f"Status: Needs attention — {fail_count} failed, {warn_count} warning(s)"
        elif warn_count:
            overall = f"Status: Ready with {warn_count} warning(s)"
        else:
            overall = "Status: PHONEHUB READY — all checks passed"

        if hasattr(self, "health_overall"):
            self.health_overall.setText(overall)
        self.set_footer(overall)

    def _detect_tailscale_ip(self, serial):
        """Return the phone's active Tailscale IPv4 address, if visible."""
        # Fast path first. Avoid running multiple expensive dumpsys commands
        # unless the normal interface list does not expose the address.
        outputs = [
            run_quiet(["adb", "-s", serial, "shell", "ip", "-4", "addr"], timeout=3),
        ]

        def find_ip(output):
            for match in re.findall(r"\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b", output or ""):
                second, third, fourth = map(int, match)
                if 64 <= second <= 127 and 0 <= third <= 255 and 0 <= fourth <= 255:
                    return f"100.{second}.{third}.{fourth}"
            return ""

        for output in outputs:
            found = find_ip(output)
            if found:
                return found

        # One fallback only.
        fallback = run_quiet(
            ["adb", "-s", serial, "shell", "dumpsys", "connectivity"],
            timeout=4,
        )
        return find_ip(fallback)

    def setup_smart_check(self):
        usb, remote, unauthorized, _ = parse_adb_devices()
        lines = []

        if unauthorized:
            lines.append("USB Debugging: Not approved")
            lines.append("Action: Approve 'Always allow from this computer' on the phone.")
            self.setup_log.setText("\n".join(lines))
            self.set_footer("USB authorization required.")
            return

        serial = usb[0] if usb else ""
        if serial:
            model = run_quiet(
                ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
                timeout=5,
            ) or "Android Phone"
            android = run_quiet(
                ["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"],
                timeout=5,
            ) or "-"

            lines.append("USB Debugging: Connected")
            lines.append(f"Device: {model}")
            lines.append(f"Android: {android}")
            lines.append(f"USB Serial: {serial}")

            installed = self._tailscale_installed(serial)
            detected_ip = self._detect_tailscale_ip(serial) if installed else ""

            if installed and detected_ip:
                lines.append("Tailscale: Connected")
                lines.append(f"Tailscale IP: {detected_ip}")

                # Keep PhoneHub synchronized with the IP reported by the phone.
                save_phone_ip(detected_ip, 5555)
                if hasattr(self, "setup_ip_input"):
                    self.setup_ip_input.setText(detected_ip)
                if hasattr(self, "dashboard_ip_input"):
                    self.dashboard_ip_input.setText(detected_ip)

                target = f"{detected_ip}:5555"
                if target not in remote:
                    run_quiet(["adb", "connect", target], timeout=5)
                    _, remote, _, _ = parse_adb_devices()

                if target in remote:
                    lines.append(f"Remote Control: Connected {target}")
                else:
                    lines.append("Remote Control: Not connected")
                    lines.append("Action: Click Enable Remote once while USB is connected.")
            elif installed:
                lines.append("Tailscale: Installed, waiting for VPN connection")
                saved_ip, _ = get_saved_ip()
                if saved_ip:
                    lines.append(f"Saved Tailscale IP: {saved_ip}")
                lines.append("Action: Open Tailscale on the phone and connect it.")
            else:
                lines.append("Tailscale: Not installed")
                lines.append("Action: Click Install Tailscale.")
        else:
            lines.append("USB Debugging: Not connected")
            saved_ip, port = get_saved_ip()
            if saved_ip:
                target = f"{saved_ip}:{port}"
                if target in remote:
                    lines.append(f"Tailscale IP: {saved_ip}")
                    lines.append(f"Remote Control: Connected {target}")
                else:
                    lines.append(f"Saved Tailscale IP: {saved_ip}")
                    lines.append("Remote Control: Not connected")
            else:
                lines.append("Tailscale IP: Not detected")

        self.setup_log.setText("\n".join(lines))
        self.set_footer("Smart check complete.")

    def auto_refresh_connection_state(self):
        # Never run adb polling on the Qt/UI thread.
        if self._auto_detect_busy:
            return

        self._auto_detect_busy = True

        def worker():
            state = {
                "usb": [],
                "remote": [],
                "unauthorized": [],
                "installed": False,
                "detected_ip": "",
            }
            try:
                usb, remote, unauthorized, _ = parse_adb_devices()
                state["usb"] = usb
                state["remote"] = remote
                state["unauthorized"] = unauthorized

                if usb and not unauthorized:
                    serial = usb[0]
                    state["installed"] = self._tailscale_installed(serial)
                    if state["installed"]:
                        state["detected_ip"] = self._detect_tailscale_ip(serial)
            except Exception:
                pass
            finally:
                self.auto_bridge.state.emit(state)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_auto_detect_state(self, state):
        self._auto_detect_busy = False

        usb = state.get("usb", [])
        remote = state.get("remote", [])
        unauthorized = state.get("unauthorized", [])
        installed = state.get("installed", False)
        detected_ip = state.get("detected_ip", "")

        signature = (
            tuple(sorted(usb)),
            tuple(sorted(remote)),
            tuple(sorted(unauthorized)),
            installed,
            detected_ip,
        )

        self._wizard_update_from_state(state)

        changed = signature != self._last_connection_signature
        if changed:
            self._last_connection_signature = signature

            # Update the visible status without launching another full adb scan.
            lines = []
            if unauthorized:
                lines = [
                    "USB Debugging: Not approved",
                    "Action: Approve 'Always allow from this computer' on the phone.",
                ]
            elif usb:
                serial = usb[0]
                lines.append("USB Debugging: Connected")
                lines.append(f"USB Serial: {serial}")

                if installed and detected_ip:
                    lines.append("Tailscale: Connected")
                    lines.append(f"Tailscale IP: {detected_ip}")
                    save_phone_ip(detected_ip, 5555)
                    if hasattr(self, "setup_ip_input"):
                        self.setup_ip_input.setText(detected_ip)
                    if hasattr(self, "dashboard_ip_input"):
                        self.dashboard_ip_input.setText(detected_ip)

                    target = f"{detected_ip}:5555"
                    lines.append(
                        f"Remote Control: {'Connected ' + target if target in remote else 'Not connected'}"
                    )
                    if target not in remote:
                        lines.append("Action: Click Enable Remote once while USB is connected.")
                elif installed:
                    lines.append("Tailscale: Installed, waiting for VPN connection")
                else:
                    lines.append("Tailscale: Not installed")
            else:
                lines.append("USB Debugging: Not connected")
                saved_ip, port = get_saved_ip()
                if saved_ip:
                    target = f"{saved_ip}:{port}"
                    lines.append(f"Saved Tailscale IP: {saved_ip}")
                    lines.append(
                        f"Remote Control: {'Connected ' + target if target in remote else 'Not connected'}"
                    )

            if hasattr(self, "setup_log"):
                self.setup_log.setText("\n".join(lines))

        if unauthorized:
            self.side_status.setText("USB authorization needed")
        elif remote:
            self.side_status.setText("Phone online")
        elif usb and detected_ip:
            self.side_status.setText("Tailscale connected")
        elif usb:
            self.side_status.setText("USB connected")
        else:
            self.side_status.setText("Phone offline")

    def _is_device_unlocked(self, serial):
        # Android exposes the current lockscreen/keyguard state through dumpsys.
        # We only use this to detect whether the user has completed normal
        # authentication on the phone; PhoneHub never bypasses the lockscreen.
        window = run_quiet(
            ["adb", "-s", serial, "shell", "dumpsys", "window", "policy"],
            timeout=3,
        ).lower()
        power = run_quiet(
            ["adb", "-s", serial, "shell", "dumpsys", "power"],
            timeout=3,
        ).lower()

        locked_markers = (
            "mshowinglockscreen=true",
            "iskeyguardshowing=true",
            "keyguard showing=true",
            "mkeyguardshowing=true",
        )
        if any(marker in window for marker in locked_markers):
            return False

        # If Android's policy output is inconclusive, treat an interactive
        # device without a showing keyguard as unlocked.
        interactive = "minteractive=true" in power or "display power: state=on" in power
        return interactive

    def _begin_unlock_flow(self, serial):
        self._auto_unlock_waiting = True
        self._auto_unlock_serial = serial

        # Wake only. Do not send PIN, pattern, swipe credentials, or any
        # lockscreen-bypass command.
        run_quiet(
            ["adb", "-s", serial, "shell", "input", "keyevent", "224"],
            timeout=3,
        )

        self.side_status.setText("Unlock phone once")
        self.set_footer("Phone detected. Unlock the phone once; PhoneHub will continue automatically.")

        QMessageBox.information(
            self,
            "Unlock phone once",
            "PhoneHub detected the USB-connected phone and woke the screen.\n\n"
            "Please unlock the phone normally using fingerprint, face, PIN, pattern, or password.\n\n"
            "PhoneHub will continue automatically after Android reports that the phone is unlocked.",
        )

        self.unlock_timer.start()
        QTimer.singleShot(1000, self._check_unlock_progress)

    def _check_unlock_progress(self):
        if not self._auto_unlock_waiting or not self._auto_unlock_serial:
            self.unlock_timer.stop()
            return

        # Stop waiting if this USB device disappeared.
        usb, _, _, _ = parse_adb_devices()
        if self._auto_unlock_serial not in usb:
            self._auto_unlock_waiting = False
            self._auto_unlock_serial = ""
            self.unlock_timer.stop()
            return

        if not self._is_device_unlocked(self._auto_unlock_serial):
            self.side_status.setText("Waiting for unlock")
            return

        self.unlock_timer.stop()
        self._auto_unlock_waiting = False
        serial = self._auto_unlock_serial
        self._auto_unlock_serial = ""

        self.side_status.setText("USB connected")
        self.set_footer("Phone unlocked. Continuing setup automatically...")

        # Refresh the setup state immediately. If Tailscale is installed, open
        # it for the next setup step; otherwise leave the Install Tailscale
        # action visible for the user.
        if hasattr(self, "setup_log"):
            self.setup_smart_check()

        if self._tailscale_installed(serial):
            run_background([
                "adb", "-s", serial, "shell", "monkey",
                "-p", TAILSCALE_PACKAGE,
                "-c", "android.intent.category.LAUNCHER",
                "1",
            ])
            self.set_footer("Phone unlocked. Tailscale opened; finish sign-in/VPN approval on the phone.")
        else:
            self.set_footer("Phone unlocked. Tailscale is missing; click Install Tailscale.")

    def _usb_serial(self):
        usb, _, unauthorized, _ = parse_adb_devices()
        if unauthorized:
            return "", "USB debugging is not authorized. Approve the popup on the phone first."
        if not usb:
            return "", "No USB phone detected. Connect the phone with USB and keep USB debugging ON."
        return usb[0], ""

    def _tailscale_installed(self, serial):
        out = run_quiet(
            ["adb", "-s", serial, "shell", "pm", "list", "packages", TAILSCALE_PACKAGE],
            timeout=8,
        )
        return TAILSCALE_PACKAGE in out

    def _set_tailscale_status(self, text):
        if hasattr(self, "tailscale_setup_status"):
            self.tailscale_setup_status.setText(text)
        self.set_footer(text)

    def check_tailscale_clicked(self):
        serial, error = self._usb_serial()
        if error:
            self._set_tailscale_status(error)
            return

        model = run_quiet(
            ["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=5
        ) or "Android phone"

        if self._tailscale_installed(serial):
            self._set_tailscale_status(
                f"Tailscale detected on {model}. Open it, sign in, and turn the Tailscale connection ON."
            )
        else:
            self._set_tailscale_status(
                f"Tailscale is NOT installed on {model}. Click 'Install Tailscale' to download the official stable APK and install it through USB."
            )

    def _latest_tailscale_apk_url(self):
        req = urllib.request.Request(
            TAILSCALE_STABLE_PAGE,
            headers={"User-Agent": "PhoneHub/2.9"},
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            html = response.read().decode("utf-8", errors="ignore")

        matches = re.findall(
            r'tailscale-android-universal-[0-9][0-9A-Za-z.\-]*\\.apk',
            html,
        )
        if not matches:
            raise RuntimeError("Could not find the stable Android APK on the official Tailscale package page.")

        # The stable page normally exposes one current universal Android APK.
        filename = matches[0]
        return TAILSCALE_BASE_URL + filename, filename

    def install_tailscale_clicked(self):
        serial, error = self._usb_serial()
        if error:
            QMessageBox.warning(self, "PhoneHub", error)
            return

        if self._tailscale_installed(serial):
            self._set_tailscale_status(
                "Tailscale is already installed. Click 'Open Tailscale', then sign in and turn it ON."
            )
            return

        answer = QMessageBox.question(
            self,
            "Install Tailscale",
            "PhoneHub will download the official stable universal Tailscale APK from pkgs.tailscale.com and install it on the USB-connected phone.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self._set_tailscale_status("Preparing Tailscale installation...")

        def worker():
            try:
                # Prefer a bundled/local APK first. Older PhoneHub setup scripts
                # already use C:\\PhoneHub\\apps\\*.apk, so this also works
                # when the PC has an APK saved locally but it is not in GitHub.
                apk_path = None
                if LOCAL_APK_DIR.exists():
                    # Prefer a real Tailscale APK by filename. Do not blindly
                    # install another APK such as PhoneHub's small app-debug.apk.
                    preferred = sorted(
                        LOCAL_APK_DIR.glob("tailscale-android-universal-*.apk"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )

                    # Fallback: any APK with "tailscale" in the name and a
                    # realistic package size (>10 MB).
                    fallback = sorted(
                        [
                            p for p in LOCAL_APK_DIR.glob("*.apk")
                            if "tailscale" in p.name.lower()
                            and p.stat().st_size > 10 * 1024 * 1024
                        ],
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )

                    candidates = preferred or fallback
                    if candidates:
                        apk_path = candidates[0]
                        self.bridge.message.emit(
                            f"Using local Tailscale APK: {apk_path.name}"
                        )

                if apk_path is None:
                    self.bridge.message.emit(
                        "No local APK found. Downloading official Tailscale APK..."
                    )
                    TAILSCALE_APK_DIR.mkdir(parents=True, exist_ok=True)
                    url, filename = self._latest_tailscale_apk_url()
                    apk_path = TAILSCALE_APK_DIR / filename

                    req = urllib.request.Request(url, headers={"User-Agent": "PhoneHub/2.9"})
                    with urllib.request.urlopen(req, timeout=90) as response:
                        data = response.read()

                    if len(data) < 1_000_000:
                        raise RuntimeError("Downloaded APK looks incomplete.")

                    apk_path.write_bytes(data)

                result = run_quiet(
                    ["adb", "-s", serial, "install", "-r", "-g", str(apk_path)],
                    timeout=120,
                )

                if "Success" not in result:
                    raise RuntimeError(result or "ADB installation failed.")

                run_background([
                    "adb", "-s", serial, "shell", "monkey",
                    "-p", TAILSCALE_PACKAGE,
                    "-c", "android.intent.category.LAUNCHER",
                    "1",
                ])

                self.bridge.message.emit(
                    "Tailscale installed successfully. On the phone, finish sign-in and approve the VPN connection, then return to PhoneHub and run Smart Check."
                )
            except Exception as exc:
                self.bridge.message.emit(f"Tailscale install failed: {exc}")

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def setup_open_tailscale(self):
        """Override the original Setup button.

        If Tailscale is installed, open it. If it is missing, offer to install
        it immediately instead of sending a silent monkey command that appears
        to do nothing.
        """
        serial, error = self._usb_serial()
        if error:
            QMessageBox.warning(self, "PhoneHub", error)
            return

        if self._tailscale_installed(serial):
            self.open_tailscale_clicked()
            return

        answer = QMessageBox.question(
            self,
            "Tailscale not installed",
            "PhoneHub cannot open Tailscale because it is not installed on this phone.\n\nInstall the official Tailscale APK now?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.install_tailscale_clicked()
        else:
            self._set_tailscale_status("Tailscale is not installed on the phone.")

    def open_tailscale_clicked(self):
        serial, error = self._usb_serial()
        if error:
            QMessageBox.warning(self, "PhoneHub", error)
            return

        if not self._tailscale_installed(serial):
            self._set_tailscale_status(
                "Tailscale is not installed. Click 'Install Tailscale' first."
            )
            return

        run_background([
            "adb", "-s", serial, "shell", "monkey",
            "-p", TAILSCALE_PACKAGE,
            "-c", "android.intent.category.LAUNCHER",
            "1",
        ])
        self._set_tailscale_status(
            "Tailscale opened on the phone. Sign in and approve the VPN connection if Android asks."
        )

    def _location_text(self):
        from PhoneHub import read_last_location_text
        return read_last_location_text()

    def dashboard_save_and_connect(self):
        ip = normalize_tailscale_ipv4(self.dashboard_ip_input.text())
        if not ip:
            QMessageBox.warning(
                self,
                "PhoneHub",
                "Enter a valid Tailscale IPv4 address, for example 100.70.94.21.",
            )
            return

        self.dashboard_ip_input.setText(ip)
        save_phone_ip(ip, 5555)

        if hasattr(self, "setup_ip_input"):
            self.setup_ip_input.setText(ip)

        self.set_footer(f"Saved {ip}. Connecting...")
        connected = connect_remote_adb()

        if connected:
            self.set_footer(f"Connected to {ip}:5555")
        else:
            self.set_footer(
                f"Saved {ip}. Phone is not connected yet; check Tailscale and remote ADB."
            )

        self.refresh_status()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    instance_name = "PhoneHub_Main_Instance"
    probe = QLocalSocket()
    probe.connectToServer(instance_name)

    if probe.waitForConnected(250):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(250)
        sys.exit(0)

    QLocalServer.removeServer(instance_name)
    server = QLocalServer()
    server.listen(instance_name)

    win = PhoneHubTailscale()

    def handle_instance_request():
        socket = server.nextPendingConnection()
        if socket is not None:
            socket.waitForReadyRead(150)
            try:
                win.restore_from_tray()
            except Exception:
                win.show()
                win.raise_()
                win.activateWindow()
            socket.disconnectFromServer()

    server.newConnection.connect(handle_instance_request)
    win._single_instance_server = server

    win.show()
    sys.exit(app.exec())
