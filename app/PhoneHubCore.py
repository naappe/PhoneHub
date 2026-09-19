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

APP_VERSION = "v4.2-direct-hotspot-path"


class Bridge(QObject):
    status = Signal(dict)
    message = Signal(str)
    recovery = Signal(bool)
    security = Signal(str)


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

        self.screen_proc = None
        self.camera_proc = None
        self.screen_requested = False
        self.screen_recovering = False
        self.screen_args = []
        self.screen_log = None

        self.build_ui()
        self.apply_style()

        self.status_timer = QTimer(self)
        self.status_timer.setInterval(5000)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start()

        self.screen_timer = QTimer(self)
        self.screen_timer.setInterval(900)
        self.screen_timer.timeout.connect(self.watch_screen)
        self.screen_timer.start()

        QTimer.singleShot(300, self.refresh_status)

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
        hint=QLabel("Private remote control over Tailscale. USB is only for initial setup or repair.")
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
        for text,fn in [("Screenshot",self.take_screenshot),("Wake",self.wake),("Lock",self.lock),("Back Camera",lambda:self.open_camera("back"))]:
            b=QPushButton(text); b.clicked.connect(fn); row2.addWidget(b)
        c2l.addLayout(row2); l.addWidget(c2); l.addStretch()
        return w

    def page_screen(self):
        w=QWidget(); l=QVBoxLayout(w); l.setSpacing(14)
        hero=QLabel("Screen"); hero.setObjectName("hero"); l.addWidget(hero)
        c,cl=self.card("Remote screen","Optimized for your Tailscale connection. If Android drops wireless ADB during unlock, PhoneHub waits for it to stabilize and reopens the screen once.")
        row=QHBoxLayout()
        a=QPushButton("Open Screen"); a.setObjectName("primary"); a.clicked.connect(self.open_screen)
        b=QPushButton("Screen Off + Control"); b.clicked.connect(self.open_screen_off)
        d=QPushButton("Disconnect"); d.setObjectName("danger"); d.clicked.connect(self.disconnect_screen)
        row.addWidget(a,2); row.addWidget(b,2); row.addWidget(d); cl.addLayout(row)
        l.addWidget(c)
        c2,c2l=self.card("Controls")
        row2=QHBoxLayout()
        for text,fn in [("Screenshot",self.take_screenshot),("Wake",self.wake),("Lock",self.lock),("Home",lambda:self.key("3")),("Back",lambda:self.key("4"))]:
            x=QPushButton(text); x.clicked.connect(fn); row2.addWidget(x)
        c2l.addLayout(row2); l.addWidget(c2); l.addStretch()
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
            "PhoneHub now tries the direct hotspot gateway first, then Tailscale.\n\n"
            f"Direct hotspot candidate: {direct}\n"
            f"Tailscale fallback: {saved_target}\n\n"
            "USB is only needed once to enable adb tcpip 5555."
        )
        c2l.addWidget(self.setup_box)
        l.addWidget(c2); return w

    def set_footer(self,text):
        self.footer.setText(text)

    def refresh_status(self):
        self.set_footer("Checking phone…")
        def worker():
            if target():
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
        args=["--no-audio","--video-codec=h264","--max-size=720","--video-bit-rate=1M","--max-fps=20","--video-buffer=120","--window-title=PhoneHub Screen"]
        if phone_off:
            args += ["--turn-screen-off","--keep-active"]
        return args

    def _start_screen(self,args,wake=True):
        exe=scrcpy_path()
        serial=target()
        if not exe or not serial:
            self.bridge.message.emit("scrcpy or phone target is missing."); return False
        if wake:
            run(["adb","-s",serial,"shell","input","keyevent","224"],timeout=3)
        LOG_DIR.mkdir(parents=True,exist_ok=True)
        log_path=LOG_DIR/"scrcpy_screen.log"
        try:
            self.screen_log=open(log_path,"a",encoding="utf-8",buffering=1)
            self.screen_log.write(f"\nSTART {time.strftime('%Y-%m-%d %H:%M:%S')} {serial}\n")
            self.screen_proc=spawn([exe,"-s",serial]+args,stdout=self.screen_log,stderr=self.screen_log)
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

    def watch_screen(self):
        if not self.screen_requested or self.screen_recovering:
            return
        p=self.screen_proc
        if p is None or p.poll() is None:
            return
        code=p.poll()
        self.screen_proc=None
        if self.screen_log:
            try: self.screen_log.close()
            except Exception: pass
            self.screen_log=None
        if code == 0:
            self.screen_requested=False
            self.set_footer("Screen closed.")
            return
        self.screen_recovering=True
        self.set_footer("Screen connection changed. Waiting for wireless ADB…")
        def worker():
            ok=ensure_remote(wait_stable=True)
            self.bridge.recovery.emit(ok)
        threading.Thread(target=worker,daemon=True).start()

    def finish_recovery(self,ok):
        if not self.screen_requested:
            self.screen_recovering=False; return
        if not ok:
            self.screen_recovering=False
            self.set_footer("Wireless ADB is not stable yet. Retrying automatically.")
            return
        QTimer.singleShot(700,self.restart_screen)

    def restart_screen(self):
        if not self.screen_requested:
            self.screen_recovering=False; return
        if self._start_screen(self.screen_args,False):
            self.set_footer("Screen reconnected.")
        else:
            self.set_footer("Screen restart failed.")
        self.screen_recovering=False

    def open_camera(self,facing):
        exe=scrcpy_path(); serial=target()
        if not exe or not serial or not shell_probe(serial):
            self.set_footer("Phone is offline."); return
        self.close_camera()
        args=[exe,"-s",serial,"--video-source=camera",f"--camera-facing={facing}","--camera-size=640x480","--camera-fps=15","--video-bit-rate=700K","--video-buffer=120","--no-audio","--window-title=PhoneHub Camera"]
        self.camera_proc=spawn(args)
        self.set_footer(f"{facing.title()} camera opening…")

    def close_camera(self):
        if self.camera_proc and self.camera_proc.poll() is None:
            try:self.camera_proc.terminate()
            except Exception:pass
        self.camera_proc=None

    def key(self,keycode):
        serial=target()
        if serial and shell_probe(serial):
            spawn(["adb","-s",serial,"shell","input","keyevent",keycode])

    def wake(self): self.key("224")
    def lock(self): self.key("26")

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
