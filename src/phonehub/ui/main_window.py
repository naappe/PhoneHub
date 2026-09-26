from __future__ import annotations

import socket
import re
import subprocess
from datetime import datetime
from PySide6.QtCore import QThreadPool, QTimer, Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QVBoxLayout, QWidget, QApplication, QScrollArea
)

from phonehub.core.command import SubprocessRunner
from phonehub.core.workers import Worker
from phonehub.services.discovery_service import DiscoveryService
from phonehub.ui.theme import APP_STYLE


class MainWindow(QMainWindow):
    """PhoneHub desktop controller.

    Tailscale provides private discovery/networking. When Android ADB-over-TCP
    has been authorized once, PhoneHub reconnects it quietly and launches
    scrcpy on demand. Android security still requires first-time authorization.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhoneHub 6.3 — Tailscale")
        self.resize(1040, 720)
        self.setMinimumSize(760, 540)
        self.setStyleSheet(APP_STYLE)

        self.runner = SubprocessRunner()
        self.discovery = DiscoveryService(self.runner)
        self.pool = QThreadPool.globalInstance()
        self.workers = set()
        self.peer = None
        self.latencies = []
        self.last_good = None
        self.adb_ready_ip = None

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setCentralWidget(scroll)

        root = QWidget()
        root.setObjectName("Root")
        scroll.setWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(32, 26, 32, 28)
        layout.setSpacing(16)

        brand = QLabel("PhoneHub 6.3")
        brand.setObjectName("PageTitle")
        layout.addWidget(brand)

        subtitle = QLabel("Secure wireless Android control")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        status, sl = self.card("Connection")
        self.pc_status = QLabel("PC Tailscale: checking…")
        self.phone_status = QLabel("Android: searching…")
        self.path_status = QLabel("PC  →  Tailscale  →  Phone")
        self.path_status.setObjectName("Status")
        sl.addWidget(self.pc_status)
        sl.addWidget(self.phone_status)
        sl.addWidget(self.path_status)
        self.quality_status = QLabel("Latency —   •   Route —")
        self.quality_status.setObjectName("Muted")
        self.quality_status.setWordWrap(True)
        sl.addWidget(self.quality_status)

        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setMinimumWidth(90)
        refresh.setObjectName("Primary")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        ping = QPushButton("Ping Phone")
        ping.setMinimumWidth(110)
        ping.clicked.connect(self.ping_phone)
        buttons.addWidget(ping)
        buttons.addStretch()
        sl.addLayout(buttons)
        layout.addWidget(status)

        tools, tl = self.card("Connectivity tools")
        row = QHBoxLayout()
        self.port = QLineEdit()
        self.port.setPlaceholderText("Port, e.g. 8080")
        row.addWidget(self.port)
        test = QPushButton("Test Port")
        test.setMinimumWidth(90)
        test.clicked.connect(self.test_port)
        row.addWidget(test)
        tl.addLayout(row)
        actions = QHBoxLayout()
        copy_ip = QPushButton("Copy IP")
        copy_ip.setMinimumWidth(90)
        copy_ip.clicked.connect(self.copy_ip)
        actions.addWidget(copy_ip)
        ssh = QPushButton("SSH 22")
        ssh.setMinimumWidth(90)
        ssh.clicked.connect(self.open_ssh)
        actions.addWidget(ssh)
        actions.addStretch()
        tl.addLayout(actions)
        self.test_result = QLabel("Select an online Android device first.")
        self.test_result.setObjectName("Muted")
        self.test_result.setWordWrap(True)
        tl.addWidget(self.test_result)
        self.quick = QLabel("Quick links appear when a phone is detected.")
        self.quick.setObjectName("Muted")
        self.quick.setWordWrap(True)
        tl.addWidget(self.quick)
        layout.addWidget(tools)

        remote, rl = self.card("Phone")
        self.remote_status = QLabel("Wireless control: checking…")
        self.remote_status.setObjectName("Muted")
        self.remote_status.setWordWrap(True)
        rl.addWidget(self.remote_status)
        remote_actions = QHBoxLayout()
        screen = QPushButton("Open Screen")
        screen.setObjectName("Primary")
        screen.clicked.connect(self.open_screen)
        remote_actions.addWidget(screen)
        front = QPushButton("Front Camera")
        front.clicked.connect(lambda: self.open_camera("front"))
        remote_actions.addWidget(front)
        back = QPushButton("Back Camera")
        back.clicked.connect(lambda: self.open_camera("back"))
        remote_actions.addWidget(back)
        remote_actions.addStretch()
        rl.addLayout(remote_actions)
        layout.addWidget(remote)

        layout.addStretch()

        self.timer = QTimer(self)
        self.timer.setInterval(7000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

        self.adb_timer = QTimer(self)
        self.adb_timer.setInterval(15000)
        self.adb_timer.timeout.connect(self.auto_reconnect)
        self.adb_timer.start()

        QTimer.singleShot(300, self.refresh)

    def card(self, title):
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        return card, layout

    def work(self, fn, done):
        worker = Worker(fn)
        self.workers.add(worker)
        worker.signals.result.connect(done)
        worker.signals.error.connect(lambda e: self.test_result.setText(e))
        worker.signals.finished.connect(lambda: self.workers.discard(worker))
        self.pool.start(worker)

    def refresh(self):
        self.pc_status.setText("PC Tailscale: checking…")
        self.phone_status.setText("Android: searching tailnet…")
        if not self.latencies:
            self.quality_status.setText("Latency —   •   Route —")
        self.work(self._snapshot, self._render_snapshot)

    def _snapshot(self):
        local = self.runner.run(["tailscale", "status", "--json"], 8)
        if not local.ok:
            return False, None, "Tailscale is not running or not authenticated on this PC."
        peers = self.discovery.android_peers()
        return True, (peers[0] if peers else None), ""

    def _render_snapshot(self, result):
        pc_ok, peer, error = result
        if not pc_ok:
            self.peer = None
            self.pc_status.setText("PC Tailscale: ✕ Not ready")
            self.phone_status.setText("Android: —")
            self.path_status.setText("PC  →  Tailscale unavailable")
            self.test_result.setText(error)
            self.quick.setText("Start/sign in to Tailscale on this PC, then press Refresh.")
            return

        self.pc_status.setText("PC Tailscale: ✓ Connected")
        self.peer = peer
        if peer is None:
            self.phone_status.setText("Android: no online Tailscale device found")
            self.path_status.setText("PC  →  Tailscale  →  waiting for phone")
            self.test_result.setText("Open Tailscale on the phone and make sure it is connected to the same tailnet.")
            if self.last_good:
                self.quick.setText(
                    f"Last seen: {self.last_good['seen']} • {self.last_good['ip']} • "
                    f"{self.last_good['latency']} ms • {self.last_good['transport']}"
                )
            else:
                self.quick.setText("No phone selected.")
            return

        self.phone_status.setText(f"Android: ✓ {peer.name} • {peer.ip}")
        self.path_status.setText("CONNECTED")
        # Do not overwrite Ping/Test Port results during the automatic refresh.
        if self.test_result.text() in {
            "Select an online Android device first.",
            "No online Android Tailscale device found.",
        }:
            self.test_result.setText("Ready")
        self.quick.setText(f"Phone IP: {peer.ip}")
        self.ensure_wireless_adb(peer.ip)

    def auto_reconnect(self):
        """Keep an already-provisioned phone attached quietly in the background."""
        if self.peer is None:
            return
        ip = self.peer.ip
        target = f"{ip}:5555"
        result = self.runner.run(["adb", "devices"], 5)
        if result.ok and any(
            line.strip().startswith(target) and line.strip().endswith("device")
            for line in (result.stdout or "").splitlines()
        ):
            self.adb_ready_ip = ip
            self.remote_status.setText("Wireless screen/control: ✓ Ready")
            return
        self.adb_ready_ip = None
        self.ensure_wireless_adb(ip)

    def ensure_wireless_adb(self, ip):
        """Quietly reconnect an already-authorized Android ADB-over-TCP endpoint."""
        if self.adb_ready_ip == ip:
            return
        self.remote_status.setText("Wireless control: connecting…")
        self.work(lambda: self._adb_connect(ip), lambda result: self._adb_done(ip, result))

    def _adb_connect(self, ip):
        check = self.runner.run(["adb", "connect", f"{ip}:5555"], 8)
        output = ((check.stdout or "") + " " + (check.stderr or "")).strip()
        ok = check.ok and ("connected to" in output.lower() or "already connected" in output.lower())
        return ok, output

    def _adb_done(self, ip, result):
        ok, output = result
        if ok:
            self.adb_ready_ip = ip
            self.remote_status.setText("Wireless screen/control: ✓ Ready")
        else:
            self.adb_ready_ip = None
            detail = output.splitlines()[-1] if output else "ADB 5555 is not available."
            self.remote_status.setText(
                "Wireless control needs one-time setup on this phone. "
                "Connect USB, allow USB debugging, then run: adb tcpip 5555"
            )
            self.test_result.setText(detail)

    def open_screen(self):
        if self.peer is None:
            self.test_result.setText("No online Android Tailscale device found.")
            return
        target = f"{self.peer.ip}:5555"
        if self.adb_ready_ip != self.peer.ip:
            ok, _ = self._adb_connect(self.peer.ip)
            if not ok:
                self.remote_status.setText("Wireless control needs one-time setup on this phone.")
                return
            self.adb_ready_ip = self.peer.ip
        try:
            subprocess.Popen(["scrcpy", "-s", target])
            self.test_result.setText("Opening wireless phone screen…")
        except FileNotFoundError:
            self.test_result.setText("scrcpy is not installed. RUN_PHONEHUB.bat can install it automatically.")
        except Exception as exc:
            self.test_result.setText(f"Could not open screen: {exc}")

    def open_camera(self, facing):
        if self.peer is None:
            self.test_result.setText("No online Android Tailscale device found.")
            return
        target = f"{self.peer.ip}:5555"
        if self.adb_ready_ip != self.peer.ip:
            ok, _ = self._adb_connect(self.peer.ip)
            if not ok:
                self.remote_status.setText("Wireless control needs one-time setup on this phone.")
                return
            self.adb_ready_ip = self.peer.ip
        # scrcpy 4.x camera capture uses Android camera2 through the scrcpy server.
        # Camera permission/availability is still controlled by Android.
        args = ["scrcpy", "-s", target, "--video-source=camera", f"--camera-facing={facing}", "--no-audio"]
        try:
            subprocess.Popen(args)
            self.test_result.setText(f"Opening {facing} camera…")
        except FileNotFoundError:
            self.test_result.setText("scrcpy is not installed.")
        except Exception as exc:
            self.test_result.setText(f"Could not open {facing} camera: {exc}")

    def ping_phone(self):
        if self.peer is None:
            self.test_result.setText("No online Android Tailscale device found.")
            return
        ip = self.peer.ip
        self.test_result.setText(f"Testing Tailscale reachability to {ip}…")
        self.work(lambda: self.runner.run(["tailscale", "ping", ip], 12), self._ping_done)

    def _ping_done(self, result):
        output = (result.stdout or result.stderr or "").strip()
        if "pong from" in output.lower():
            first = next((line.strip() for line in output.splitlines() if "pong from" in line.lower()), "")
            match = re.search(r"in\\s+(\\d+)ms", first, re.I)
            latency = int(match.group(1)) if match else None
            derp = re.search(r"via\\s+DERP\\(([^)]+)\\)", first, re.I)
            transport = f"DERP ({derp.group(1)})" if derp else "Direct"
            if latency is not None:
                self.latencies = (self.latencies + [latency])[-10:]
                avg = round(sum(self.latencies) / len(self.latencies))
                low, high = min(self.latencies), max(self.latencies)
                quality = "Excellent" if avg < 50 else "Good" if avg < 150 else "Usable" if avg <= 300 else "Poor"
                self.quality_status.setText(
                    f"{quality}   •   {latency} ms   •   {transport}   •   min/avg/max {low}/{avg}/{high} ms"
                )
                self.last_good = {
                    "seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ip": self.peer.ip if self.peer else "—",
                    "latency": latency,
                    "transport": transport,
                }
            else:
                self.quality_status.setText(f"Route: {transport}")
            self.test_result.setText("✓ Phone reachable over Tailscale")
        elif result.ok:
            self.test_result.setText("✓ Phone reachable over Tailscale.")
        else:
            detail = output.splitlines()[-1] if output else "No pong received."
            self.test_result.setText(f"✕ Tailscale ping failed • {detail}")

    def copy_ip(self):
        if self.peer is None:
            self.test_result.setText("No online Android Tailscale device found.")
            return
        QApplication.clipboard().setText(self.peer.ip)
        self.test_result.setText("✓ IP copied.")

    def open_ssh(self):
        if self.peer is None:
            self.test_result.setText("No online Android Tailscale device found.")
            return
        # Launch the system SSH client; PhoneHub does not claim that SSH is
        # enabled on Android.
        try:
            subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", "ssh", f"user@{self.peer.ip}"])
            self.test_result.setText("Opened SSH launcher. SSH must already be running on the phone.")
        except Exception as exc:
            self.test_result.setText(f"Could not open SSH: {exc}")

    def test_port(self):
        if self.peer is None:
            self.test_result.setText("No online Android Tailscale device found.")
            return
        try:
            port = int(self.port.text().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            self.test_result.setText("Enter a port from 1 to 65535.")
            return
        ip = self.peer.ip
        self.test_result.setText(f"Testing {ip}:{port}…")
        self.work(lambda: self._tcp_test(ip, port), lambda ok: self._port_done(ip, port, ok))

    @staticmethod
    def _tcp_test(ip, port):
        try:
            with socket.create_connection((ip, port), timeout=3):
                return True
        except OSError:
            return False

    def _port_done(self, ip, port, ok):
        if ok:
            self.test_result.setText(f"✓ {ip}:{port} is open.")
            self.quick.setText(
                f"Open service: http://{ip}:{port}\n"
                f"If this is SSH instead: ssh user@{ip} -p {port}"
            )
        else:
            self.test_result.setText(
                f"{ip}:{port} is closed or no service is listening. "
                "This does not mean the phone is offline."
            )
