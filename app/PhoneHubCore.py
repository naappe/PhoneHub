import os
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
    QHBoxLayout, QStackedWidget, QLineEdit, QTextEdit, QMessageBox
)

from core_runtime import (
    ROOT, LOG_DIR, SCREENSHOT_DIR, SECURITY_DIR, run, spawn, target,
    save_target, ensure_remote, enable_tcp_on_usb, scrcpy_path,
    device_snapshot, screenshot, shell_probe, connection_mode,
    configured_target, local_hotspot_target
)
from security_monitor import scan_device, summarize_findings

APP_VERSION = "v4.9-single-session"


class Bridge(QObject):
    status = Signal(dict)
    message = Signal(str)
    recovery = Signal(bool)
    security = Signal(str)
    unlock_state = Signal(dict)


class PhoneHubCore(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PhoneHub {APP_VERSION}")
        self.resize(1040, 680)
        self.setMinimumSize(840, 560)

        self.bridge = Bridge()
        self.bridge.status.connect(self.apply_status)
        self.bridge.message.connect(self.set_footer)
        self.bridge.recovery.connect(self.finish_recovery)
        self.bridge.security.connect(self.security_output)
        self.bridge.unlock_state.connect(self.apply_unlock_state)

        self.screen_proc = None
        self.camera_proc = None
        self.camera_requested = False
        self.camera_facing = ""
        self.screen_requested = False
        self.screen_recovering = False
        self.screen_args = []
        self.screen_log = None
        self.camera_log = None
        self.screen_log_path = LOG_DIR / "scrcpy_screen.log"
        self.camera_log_path = LOG_DIR / "scrcpy_camera.log"
        self.screen_log_offset = 0
        self.camera_log_offset = 0
        self._unlock_check_busy = False
        self._last_unlock_state = None
        self._auto_open_on_unlock = True

        self.build_ui()
        self.apply_style()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(5000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

        self.screen_timer = QTimer(self)
        self.screen_timer.setInterval(300)
        self.screen_timer.timeout.connect(self.watch_screen)
        self.screen_timer.start()

        self.camera_timer = QTimer(self)
        self.camera_timer.setInterval(500)
        self.camera_timer.timeout.connect(self.watch_camera)
        self.camera_timer.start()

        self.unlock_state_timer = QTimer(self)
        self.unlock_state_timer.setInterval(1400)
        self.unlock_state_timer.timeout.connect(self.check_unlock_state)
        self.unlock_state_timer.start()

        QTimer.singleShot(300, self.refresh_status)

    def check_unlock_state(self):
        if self._unlock_check_busy or self.screen_recovering:
            return

        serial=target()
        if not serial:
            return

        self._unlock_check_busy=True

        def worker():
            online=shell_probe(serial, timeout=2)
            state={
                "online": online,
                "interactive": False,
                "locked": None,
            }

            if online:
                power=run(
                    ["adb","-s",serial,"shell","dumpsys","power"],
                    timeout=3
                ).lower()
                policy=run(
                    ["adb","-s",serial,"shell","dumpsys","window","policy"],
                    timeout=3
                ).lower()
                trust=run(
                    ["adb","-s",serial,"shell","dumpsys","trust"],
                    timeout=3
                ).lower()

                state["interactive"]=(
                    "minteractive=true" in power
                    or "mwakefulness=awake" in power
                    or "wakefulness=awake" in power
                )

                combined=policy+"\n"+trust
                locked_markers=(
                    "devicelocked=true",
                    "device locked=true",
                    "mshowinglockscreen=true",
                    "iskeyguardshowing=true",
                    "keyguard showing=true",
                    "mkeyguardshowing=true",
                )
                unlocked_markers=(
                    "devicelocked=false",
                    "device locked=false",
                    "mshowinglockscreen=false",
                    "iskeyguardshowing=false",
                    "mkeyguardshowing=false",
                )

                if any(x in combined for x in locked_markers):
                    state["locked"]=True
                elif any(x in combined for x in unlocked_markers):
                    state["locked"]=False

            self.bridge.unlock_state.emit(state)

        threading.Thread(target=worker,daemon=True).start()

    def apply_unlock_state(self,state):
        self._unlock_check_busy=False

        online=bool(state.get("online"))
        interactive=bool(state.get("interactive"))
        locked=state.get("locked")

        if not online:
            current="offline"
        elif not interactive:
            current="asleep"
        elif locked is True:
            current="locked"
        elif locked is False:
            current="unlocked"
        else:
            current="awake"

        previous=self._last_unlock_state
        self._last_unlock_state=current

        # First sample establishes a baseline so starting PhoneHub while the
        # phone is already unlocked does not unexpectedly pop open a screen.
        if previous is None:
            return

        became_unlocked=(
            current=="unlocked"
            and previous in ("locked","asleep","offline","awake")
        )

        if not became_unlocked or not self._auto_open_on_unlock:
            return

        if self.screen_proc is not None and self.screen_proc.poll() is None:
            return

        self.screen_requested=True
        self.screen_args=self._screen_profile(False)
        self.screen_recovering=False
        self.set_footer("Phone unlocked. Opening screen automatically…")
        QTimer.singleShot(250, self.open_screen)

    def apply_style(self):
        self.setStyleSheet("""
        QWidget {
            background:#f4f7fb;
            color:#152238;
            font-family:'Segoe UI';
            font-size:13px;
        }
        QFrame#rail {
            background:#ffffff;
            border-right:1px solid #dbe4ef;
        }
        QFrame#card {
            background:#ffffff;
            border:1px solid #dfe7f0;
            border-radius:18px;
        }
        QLabel#brand {
            font-size:28px;
            font-weight:800;
            color:#10213a;
        }
        QLabel#muted {
            color:#6f8096;
        }
        QLabel#hero {
            font-size:28px;
            font-weight:800;
            color:#10213a;
        }
        QLabel#statusOnline {
            color:#0e9f6e;
            font-weight:700;
        }
        QLabel#statusOffline {
            color:#d14343;
            font-weight:700;
        }
        QPushButton {
            background:#ffffff;
            border:1px solid #d4deea;
            border-radius:12px;
            padding:11px 15px;
            font-weight:650;
            color:#21324a;
        }
        QPushButton:hover {
            background:#f1f5fb;
            border-color:#b8c7d9;
        }
        QPushButton#nav {
            text-align:left;
            border:none;
            padding:12px 14px;
            background:transparent;
        }
        QPushButton#nav:checked {
            background:#e8f0ff;
            color:#1457d9;
            border-left:4px solid #2563eb;
            border-radius:10px;
        }
        QPushButton#primary {
            background:#2563eb;
            border-color:#2563eb;
            color:white;
        }
        QPushButton#primary:hover {
            background:#1f55ca;
        }
        QPushButton#danger {
            background:#fff1f1;
            border-color:#f0b8b8;
            color:#b4232d;
        }
        QLineEdit, QTextEdit {
            background:#fbfdff;
            border:1px solid #d7e1ec;
            border-radius:12px;
            padding:10px;
            color:#17243a;
        }
        QTextEdit {
            selection-background-color:#2563eb;
        }
        """)
    
    def card(self, title, subtitle=""):
        frame = QFrame()
        frame.setObjectName("card")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(10)
        t = QLabel(title)
        t.setStyleSheet("font-size:17px;font-weight:750;")
        lay.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("muted")
            s.setWordWrap(True)
            lay.addWidget(s)
        return frame, lay

    def build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.setSpacing(0)

        rail = QFrame()
        rail.setObjectName("rail")
        rail.setFixedWidth(190)
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(16,18,16,16)
        rl.setSpacing(8)

        brand = QLabel("PhoneHub")
        brand.setObjectName("brand")
        rl.addWidget(brand)
        sub = QLabel("Secure Remote Workspace")
        sub.setObjectName("muted")
        rl.addWidget(sub)
        rl.addSpacing(16)

        self.stack = QStackedWidget()
        self.nav = []
        pages = [
            ("Dashboard", self.page_overview),
            ("Screen", self.page_screen),
            ("Camera", self.page_camera),
            ("Files", self.page_files),
            ("Security", self.page_protection),
            ("Setup", self.page_setup),
        ]
        for i,(name,builder) in enumerate(pages):
            b = QPushButton(name)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.clicked.connect(lambda checked=False, x=i: self.show_page(x))
            rl.addWidget(b)
            self.nav.append(b)
            self.stack.addWidget(builder())
        rl.addStretch()

        self.rail_status = QLabel("Checking…")
        self.rail_status.setObjectName("muted")
        rl.addWidget(self.rail_status)

        content = QFrame()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(24,22,24,14)
        cl.setSpacing(10)
        cl.addWidget(self.stack,1)
        self.footer = QLabel("Ready")
        self.footer.setObjectName("muted")
        cl.addWidget(self.footer)

        root.addWidget(rail)
        root.addWidget(content,1)
        self.show_page(0)

    def show_page(self, index):
        self.stack.setCurrentIndex(index)
        for i,b in enumerate(self.nav):
            b.setChecked(i == index)

    def page_overview(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(14)
        hero=QLabel("PhoneHub Dashboard")
        hero.setObjectName("hero"); l.addWidget(hero)
        hint=QLabel("Private remote control over Tailscale. When the phone wakes and unlocks, the screen opens automatically.")
        hint.setObjectName("muted"); l.addWidget(hint)

        c,cl=self.card("Connection")
        self.overview_state=QLabel("Checking phone…")
        self.overview_state.setWordWrap(True); cl.addWidget(self.overview_state)
        row=QHBoxLayout()
        r=QPushButton("Refresh"); r.setObjectName("primary"); r.clicked.connect(self.refresh_status)
        s=QPushButton("Open Screen"); s.clicked.connect(self.open_screen)
        row.addWidget(r); row.addWidget(s); cl.addLayout(row)
        l.addWidget(c)

        c2,c2l=self.card("Quick actions")
        row2=QHBoxLayout()
        for text,fn in [("Screenshot",self.take_screenshot),("Wake",self.wake),("Screen Off",self.private_screen_off),("Back Camera",lambda:self.open_camera("back"))]:
            b=QPushButton(text); b.clicked.connect(fn); row2.addWidget(b)
        c2l.addLayout(row2); l.addWidget(c2); l.addStretch()
        return w

    def page_screen(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(14)
        hero=QLabel("Screen"); hero.setObjectName("hero"); l.addWidget(hero)
        c,cl=self.card("Remote screen","The screen automatically reopens after the phone wakes and unlocks. Use Screen Off for privacy without entering Android keyguard.")
        row=QHBoxLayout()
        a=QPushButton("Open Screen"); a.setObjectName("primary"); a.clicked.connect(self.open_screen)
        b=QPushButton("Private Screen Off"); b.clicked.connect(self.open_screen_off)
        d=QPushButton("Disconnect"); d.setObjectName("danger"); d.clicked.connect(self.disconnect_screen)
        row.addWidget(a,2); row.addWidget(b,2); row.addWidget(d); cl.addLayout(row)
        l.addWidget(c)
        c2,c2l=self.card(
            "Controls",
            "Use Screen Off when you want privacy without breaking the remote session. Secure Lock uses Android keyguard and may reset wireless ADB on this phone."
        )
        row2=QHBoxLayout()
        for text,fn in [
            ("Screenshot",self.take_screenshot),
            ("Wake",self.wake),
            ("Screen Off",self.private_screen_off),
            ("Home",lambda:self.key("3")),
            ("Back",lambda:self.key("4")),
        ]:
            x=QPushButton(text); x.clicked.connect(fn); row2.addWidget(x)
        c2l.addLayout(row2)

        secure_row=QHBoxLayout()
        secure=QPushButton("Secure Lock")
        secure.setObjectName("danger")
        secure.clicked.connect(self.secure_lock)
        secure_row.addStretch()
        secure_row.addWidget(secure)
        c2l.addLayout(secure_row)

        l.addWidget(c2); l.addStretch()
        return w

    def page_camera(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(14)
        h=QLabel("Camera"); h.setObjectName("hero"); l.addWidget(h)
        c,cl=self.card("Phone camera","Front and back camera run independently from the normal screen.")
        row=QHBoxLayout()
        for text,fn in [("Back Camera",lambda:self.open_camera("back")),("Front Camera",lambda:self.open_camera("front")),("Close Camera",self.close_camera)]:
            b=QPushButton(text); b.clicked.connect(fn); row.addWidget(b)
        cl.addLayout(row); l.addWidget(c); l.addStretch(); return w

    def page_files(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(14)
        h=QLabel("Files"); h.setObjectName("hero"); l.addWidget(h)
        c,cl=self.card("PhoneHub storage","Only current screenshots and security evidence are kept here.")
        row=QHBoxLayout()
        a=QPushButton("Screenshots"); a.setObjectName("primary"); a.clicked.connect(self.open_screenshots)
        b=QPushButton("Protection Evidence"); b.clicked.connect(self.open_evidence)
        row.addWidget(a); row.addWidget(b); cl.addLayout(row); l.addWidget(c); l.addStretch(); return w

    def page_protection(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(14)
        h=QLabel("Security"); h.setObjectName("hero"); l.addWidget(h)
        c,cl=self.card("Read-only security check","Checks ADB, Tailscale, routes, visible sockets, third-party apps and accessibility services. It does not automatically kill or disable anything.")
        row=QHBoxLayout()
        a=QPushButton("Run Scan"); a.setObjectName("primary"); a.clicked.connect(self.run_security)
        b=QPushButton("Open Evidence"); b.clicked.connect(self.open_evidence)
        row.addWidget(a); row.addWidget(b); cl.addLayout(row)
        self.security_box=QTextEdit(); self.security_box.setReadOnly(True); self.security_box.setText("No scan yet."); cl.addWidget(self.security_box)
        l.addWidget(c); return w

    def page_setup(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(14)
        h=QLabel("Setup"); h.setObjectName("hero"); l.addWidget(h)
        c,cl=self.card("Phone address","Enter the phone's Tailscale IPv4 address.")
        self.ip=QLineEdit()
        saved=target().split(":")[0] if target() else ""
        self.ip.setText(saved); self.ip.setPlaceholderText("100.x.x.x"); cl.addWidget(self.ip)
        row=QHBoxLayout()
        a=QPushButton("Save + Connect"); a.setObjectName("primary"); a.clicked.connect(self.save_connect)
        b=QPushButton("Enable Remote ADB via USB"); b.clicked.connect(self.enable_remote)
        row.addWidget(a); row.addWidget(b); cl.addLayout(row); l.addWidget(c)
        c2,c2l=self.card("Setup status")
        self.setup_box=QTextEdit()
        self.setup_box.setReadOnly(True)
        direct = local_hotspot_target() or "not detected"
        saved_target = configured_target() or "not configured"
        self.setup_box.setText(
            "PhoneHub uses the saved Tailscale target by default.\n\n"
            f"Configured target: {saved_target}\n"
            f"Optional local hotspot target: {direct}\n\n"
            "USB is only needed once to enable adb tcpip 5555."
        )
        c2l.addWidget(self.setup_box)
        l.addWidget(c2); return w

    def set_footer(self,text):
        self.footer.setText(text)

    def refresh_status(self):
        media_active = (
            self.screen_requested
            or self.camera_requested
            or self.screen_recovering
        )
        if media_active:
            return

        self.set_footer("Checking phone…")

        def worker():
            if target() and not shell_probe(target(), timeout=2):
                ensure_remote(wait_stable=False)
            self.bridge.status.emit(device_snapshot())

        threading.Thread(target=worker,daemon=True).start()

    def apply_status(self,data):
        online=data.get("online",False)
        self.rail_status.setText("● Phone online" if online else "● Phone offline")
        self.rail_status.setObjectName("statusOnline" if online else "statusOffline")
        self.rail_status.style().unpolish(self.rail_status); self.rail_status.style().polish(self.rail_status)
        mode=data.get("mode","offline")
        mode_label={
            "local-hotspot":"Direct hotspot path",
            "tailscale":"Tailscale path",
            "network":"Network path",
            "offline":"Offline",
        }.get(mode, mode)
        text=(
            f"Status: {'Online' if online else 'Offline'}\n"
            f"Path: {mode_label}\n"
            f"Target: {data.get('target') or '-'}\n"
            f"Device: {data.get('model','-')}\n"
            f"Android: {data.get('android','-')}\n"
            f"Battery: {data.get('battery','-')}%"
        )
        self.overview_state.setText(text)
        if online and mode == "local-hotspot":
            self.set_footer("Direct hotspot path active — Tailscale relay bypassed.")
        elif online and mode == "tailscale":
            self.set_footer("Connected through Tailscale.")
        else:
            self.set_footer("Ready" if online else "Phone offline — open Setup if needed.")

    def save_connect(self):
        try:
            save_target(self.ip.text())
        except Exception as exc:
            QMessageBox.warning(self,"PhoneHub",str(exc)); return
        self.setup_box.setText("Saved. Connecting to remote ADB…")
        def worker():
            ok=ensure_remote()
            self.bridge.message.emit("Remote ADB connected." if ok else "Could not connect to remote ADB.")
            QTimer.singleShot(0,self.refresh_status)
        threading.Thread(target=worker,daemon=True).start()

    def enable_remote(self):
        def worker():
            ok,msg=enable_tcp_on_usb()
            self.bridge.message.emit(msg)
            if hasattr(self,"setup_box"):
                self.setup_box.setText(msg)
        threading.Thread(target=worker,daemon=True).start()

    def _screen_profile(self, phone_off=False):
        args=[
            "--no-audio",
            "--video-codec=h264",
            "--max-size=720",
            "--video-bit-rate=1M",
            "--max-fps=15",
            "--video-buffer=0",
            "--keep-active",
            "--window-title=PhoneHub Screen",
        ]
        if phone_off:
            args += ["--turn-screen-off"]
        return args

    def _start_screen(self,args,wake=True):
        exe=scrcpy_path()
        serial=target()
        if not exe or not serial:
            self.bridge.message.emit("scrcpy or phone target is missing.")
            return False

        if not shell_probe(serial, timeout=3):
            if not ensure_remote(wait_stable=False):
                self.bridge.message.emit("Phone ADB is offline.")
                return False

        if wake:
            run(["adb","-s",serial,"shell","input","keyevent","224"],timeout=3)

        LOG_DIR.mkdir(parents=True,exist_ok=True)
        log_path=self.screen_log_path
        try:
            self.screen_log=open(log_path,"a",encoding="utf-8",buffering=1)
            self.screen_log.write(f"\nSTART {time.strftime('%Y-%m-%d %H:%M:%S')} {serial}\n")
            self.screen_log.flush()
            self.screen_log_offset=self.screen_log.tell()
            self.screen_proc=spawn(
                [exe,"-s",serial]+args,
                stdout=self.screen_log,
                stderr=self.screen_log
            )
        except Exception:
            self.screen_proc=None
        return self.screen_proc is not None

    def open_screen(self):
        if self.screen_proc and self.screen_proc.poll() is None:
            self.set_footer("Screen already open."); return
        self.screen_requested=True
        self.screen_args=self._screen_profile(False)
        self.screen_recovering=False
        if self._start_screen(self.screen_args,True):
            self.set_footer("Opening screen…")
        else:
            self.set_footer("Screen start failed.")

    def open_screen_off(self):
        if self.screen_proc and self.screen_proc.poll() is None:
            self.disconnect_screen()
        self.screen_requested=True
        self.screen_args=self._screen_profile(True)
        self.screen_recovering=False
        if self._start_screen(self.screen_args,True):
            self.set_footer("Opening screen with phone display off…")

    def disconnect_screen(self):
        self.screen_requested=False
        self.screen_recovering=False
        p=self.screen_proc
        self.screen_proc=None
        if p and p.poll() is None:
            try: p.terminate()
            except Exception: pass
        if self.screen_log:
            try: self.screen_log.close()
            except Exception: pass
            self.screen_log=None
        self.set_footer("Screen disconnected.")

    def _read_new_log_text(self, path, attr_name):
        try:
            offset=getattr(self, attr_name, 0)
            if not path.exists():
                return ""
            with open(path,"r",encoding="utf-8",errors="ignore") as fh:
                fh.seek(offset)
                text=fh.read()
                setattr(self, attr_name, fh.tell())
                return text
        except Exception:
            return ""

    def _screen_disconnect_logged(self):
        text=self._read_new_log_text(
            self.screen_log_path, "screen_log_offset"
        ).lower()
        return (
            "device disconnected" in text
            or "server disconnected" in text
            or "connection reset" in text
            or "broken pipe" in text
        )

    def _camera_disconnect_logged(self):
        text=self._read_new_log_text(
            self.camera_log_path, "camera_log_offset"
        ).lower()
        return (
            "device disconnected" in text
            or "server disconnected" in text
            or "connection reset" in text
            or "broken pipe" in text
        )

    def _begin_screen_recovery(self, reason):
        if not self.screen_requested or self.screen_recovering:
            return

        self.screen_recovering=True
        p=self.screen_proc
        self.screen_proc=None
        if p and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

        if self.screen_log:
            try:
                self.screen_log.write(
                    f"RECOVERY reason={reason} at {time.strftime('%H:%M:%S')}\n"
                )
                self.screen_log.close()
            except Exception:
                pass
            self.screen_log=None

        self.set_footer("Phone unlock reset ADB. Restoring screen…")

        def worker():
            ok=ensure_remote(wait_stable=True, timeout_seconds=35)
            self.bridge.recovery.emit(ok)

        threading.Thread(target=worker,daemon=True).start()

    def watch_screen(self):
        if not self.screen_requested or self.screen_recovering:
            return

        p=self.screen_proc
        if p is None:
            self._begin_screen_recovery("screen process missing")
            return

        # scrcpy 4.1 keeps its window visible for about two seconds after ADB
        # disappears and renders the large disconnected-phone icon. Detect the
        # warning in scrcpy's live log immediately instead of waiting for the
        # process/window to close.
        if p.poll() is None:
            if self._screen_disconnect_logged():
                self._begin_screen_recovery("scrcpy reported device disconnected")
            return

        self._begin_screen_recovery(f"scrcpy exited code {p.poll()}")

    def finish_recovery(self,ok):
        if not self.screen_requested:
            self.screen_recovering=False; return
        if not ok:
            self.set_footer("Android ADB is still authorizing. Waiting before another recovery check…")
            QTimer.singleShot(2500, self.retry_screen_recovery)
            return
        QTimer.singleShot(700,self.restart_screen)

    def retry_screen_recovery(self):
        if not self.screen_requested:
            self.screen_recovering=False
            return

        def worker():
            ok=ensure_remote(wait_stable=True, timeout_seconds=35)
            self.bridge.recovery.emit(ok)

        threading.Thread(target=worker,daemon=True).start()

    def restart_screen(self):
        if not self.screen_requested:
            self.screen_recovering=False; return
        if self._start_screen(self.screen_args,False):
            self.set_footer("Screen reconnected.")
        else:
            self.set_footer("Screen restart failed.")
        self.screen_recovering=False

    def open_camera(self,facing):
        exe=scrcpy_path()
        serial=target()
        if not exe or not serial:
            self.set_footer("scrcpy or phone target is missing.")
            return

        self.camera_requested=True
        self.camera_facing=facing

        # A locked OnePlus may briefly reset wireless ADB. Wait for a stable
        # transport instead of immediately reporting the camera as offline.
        if not shell_probe(serial, timeout=3):
            if not ensure_remote(wait_stable=True):
                self.set_footer("Camera waiting for wireless ADB…")
                QTimer.singleShot(1200, lambda f=facing: self.open_camera(f))
                return

        self._close_camera_process_only()

        LOG_DIR.mkdir(parents=True,exist_ok=True)
        log_path=self.camera_log_path

        args=[
            exe,"-s",serial,
            "--video-source=camera",
            f"--camera-facing={facing}",
            "--camera-size=640x480",
            "--camera-fps=15",
            "--video-bit-rate=500K",
            "--video-buffer=0",
            "--no-audio",
            "--window-title=PhoneHub Camera",
        ]

        try:
            self.camera_log=open(log_path,"a",encoding="utf-8",buffering=1)
            self.camera_log.write(
                f"\nSTART {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"{serial} facing={facing}\n"
            )
            self.camera_log.flush()
            self.camera_log_offset=self.camera_log.tell()
            self.camera_proc=spawn(
                args,
                stdout=self.camera_log,
                stderr=self.camera_log
            )
        except Exception:
            self.camera_proc=None

        if self.camera_proc:
            self.set_footer(f"{facing.title()} camera opening…")
        else:
            self.set_footer("Could not open camera.")

    def _close_camera_process_only(self):
        if self.camera_proc and self.camera_proc.poll() is None:
            try:
                self.camera_proc.terminate()
            except Exception:
                pass
        self.camera_proc=None
        if self.camera_log:
            try:
                self.camera_log.close()
            except Exception:
                pass
            self.camera_log=None

    def close_camera(self):
        self.camera_requested=False
        self.camera_facing=""
        self._close_camera_process_only()
        self.set_footer("Camera closed.")

    def watch_camera(self):
        if not self.camera_requested:
            return

        p=self.camera_proc
        if p is None:
            facing=self.camera_facing or "back"
            QTimer.singleShot(900, lambda f=facing: self.open_camera(f))
            return

        if p.poll() is None:
            if not self._camera_disconnect_logged():
                return

            # Kill the stale disconnected-icon window immediately. The normal
            # camera reopen path waits for ADB to stabilize before relaunching.
            try:
                p.terminate()
            except Exception:
                pass
            self.camera_proc=None
            if self.camera_log:
                try:
                    self.camera_log.close()
                except Exception:
                    pass
                self.camera_log=None

            facing=self.camera_facing or "back"
            self.set_footer("Camera connection reset. Restoring camera…")
            QTimer.singleShot(900, lambda f=facing: self.open_camera(f))
            return

        facing=self.camera_facing or "back"
        self.camera_proc=None
        if self.camera_log:
            try:
                self.camera_log.close()
            except Exception:
                pass
            self.camera_log=None
        self.set_footer("Camera stream ended. Reopening automatically…")
        QTimer.singleShot(900, lambda f=facing: self.open_camera(f))

    def key(self,keycode):
        serial=target()
        if serial and shell_probe(serial):
            spawn(["adb","-s",serial,"shell","input","keyevent",keycode])

    def wake(self):
        self.key("224")

    def private_screen_off(self):
        # Do not send POWER/LOCK. On this OnePlus, secure lock resets wireless
        # ADB. Instead restart scrcpy with --turn-screen-off so the physical
        # display is black while remote control remains active.
        was_requested=self.screen_requested
        if self.screen_proc and self.screen_proc.poll() is None:
            self.disconnect_screen()
        self.screen_requested=True
        self.screen_args=self._screen_profile(True)
        self.screen_recovering=False
        if self._start_screen(self.screen_args,False):
            self.set_footer("Phone display off; remote control stays active.")
        else:
            self.screen_requested=was_requested
            self.set_footer("Could not switch to private screen-off mode.")

    def secure_lock(self):
        # Real Android keyguard. The device ROM may reset wireless ADB here;
        # PhoneHub recovery will reconnect when Android exposes ADB again.
        self.key("26")
        self.set_footer("Secure Lock sent. This phone may reset wireless ADB during keyguard.")

    def lock(self):
        self.secure_lock()

    def take_screenshot(self):
        def worker():
            ok,msg=screenshot()
            self.bridge.message.emit(("Screenshot saved: "+msg) if ok else msg)
        threading.Thread(target=worker,daemon=True).start()

    def open_screenshots(self):
        SCREENSHOT_DIR.mkdir(parents=True,exist_ok=True); os.startfile(str(SCREENSHOT_DIR))

    def open_evidence(self):
        SECURITY_DIR.mkdir(parents=True,exist_ok=True); os.startfile(str(SECURITY_DIR))

    def run_security(self):
        serial=target()
        if not serial:
            self.security_box.setText("Phone target is not configured."); return
        self.security_box.setText("Scanning…")
        def worker():
            if not ensure_remote(wait_stable=False):
                self.bridge.security.emit("Phone is offline."); return
            try:
                self.bridge.security.emit(summarize_findings(scan_device(serial)))
            except Exception as exc:
                self.bridge.security.emit(f"Security scan failed: {exc}")
        threading.Thread(target=worker,daemon=True).start()

    def security_output(self,text):
        self.security_box.setText(text)
        self.set_footer("Protection scan complete.")

    def closeEvent(self,event):
        self.screen_requested=False
        self.disconnect_screen()
        self.close_camera()
        event.accept()


if __name__ == "__main__":
    app=QApplication(sys.argv)
    win=PhoneHubCore()
    win.show()
    sys.exit(app.exec())
