from __future__ import annotations

import socket
import re
import webbrowser
import subprocess
from datetime import datetime
from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QPushButton, QVBoxLayout, QWidget, QApplication
)

from phonehub.core.command import SubprocessRunner
from phonehub.core.workers import Worker
from phonehub.services.discovery_service import DiscoveryService
from phonehub.ui.theme import APP_STYLE


class MainWindow(QMainWindow):
    """Tailscale-only PhoneHub.

    PhoneHub does not install an Android agent and does not use ADB.
    It discovers Android peers already authenticated to the same tailnet,
    verifies network reachability, and provides connection helpers.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhoneHub 6.3 — Tailscale")
        self.resize(980, 700)
        self.setMinimumSize(820, 600)
        self.setStyleSheet(APP_STYLE)

        self.runner = SubprocessRunner()
        self.discovery = DiscoveryService(self.runner)
        self.pool = QThreadPool.globalInstance()
        self.workers = set()
        self.peer = None
        self.latencies = []
        self.last_good = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(16)

        brand = QLabel("PhoneHub")
        brand.setObjectName("PageTitle")
        layout.addWidget(brand)

        subtitle = QLabel("PC ↔ Phone over Tailscale")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        status, sl = self.card("Connection")
        self.pc_status = QLabel("PC Tailscale: checking…")
        self.phone_status = QLabel("Android: searching…")
        self.path_status = QLabel("PC  →  Tailscale  →  Phone")
        self.path_status.setObjectName("Metric")
        sl.addWidget(self.pc_status)
        sl.addWidget(self.phone_status)
        sl.addWidget(self.path_status)
        self.quality_status = QLabel("Latency: —   Transport: —")
        self.quality_status.setObjectName("Muted")
        sl.addWidget(self.quality_status)

        buttons = QHBoxLayout()
        refresh = QPushButton("Refresh")
        refresh.setObjectName("Primary")
        refresh.clicked.connect(self.refresh)
        buttons.addWidget(refresh)
        ping = QPushButton("Ping Phone")
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
        test.clicked.connect(self.test_port)
        row.addWidget(test)
        tl.addLayout(row)
        actions = QHBoxLayout()
        copy_ip = QPushButton("Copy IP")
        copy_ip.clicked.connect(self.copy_ip)
        actions.addWidget(copy_ip)
        http = QPushButton("HTTP 8080")
        http.clicked.connect(self.open_http)
        actions.addWidget(http)
        ssh = QPushButton("SSH 22")
        ssh.clicked.connect(self.open_ssh)
        actions.addWidget(ssh)
        actions.addStretch()
        tl.addLayout(actions)
        self.test_result = QLabel("Select an online Android device first.")
        self.test_result.setObjectName("Muted")
        tl.addWidget(self.test_result)
        self.quick = QLabel("Quick links appear when a phone is detected.")
        self.quick.setObjectName("Muted")
        self.quick.setWordWrap(True)
        tl.addWidget(self.quick)
        layout.addWidget(tools)

        guide, gl = self.card("Setup")
        instructions = QLabel(
            "1. Tailscale ON on PC and phone.\n"
            "2. Use the same Tailscale account.\n"
            "3. Press Refresh.\n"
            "Connected = ready."
        )
        instructions.setWordWrap(True)
        gl.addWidget(instructions)
        layout.addWidget(guide)
        layout.addStretch()

        self.timer = QTimer(self)
        self.timer.setInterval(7000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        QTimer.singleShot(300, self.refresh)

    def card(self, title):
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setStyleSheet("font-size:16px;font-weight:750;")
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
        self.path_status.setText("✓ Connected")
        # Do not overwrite Ping/Test Port results during the automatic refresh.
        if self.test_result.text() in {
            "Select an online Android device first.",
            "No online Android Tailscale device found.",
        }:
            self.test_result.setText("Ready")
        self.quick.setText(f"Phone IP: {peer.ip}")

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
                    f"Latency: {latency} ms • {quality} • {transport} • "
                    f"10-ping window {low}/{avg}/{high} ms"
                )
                self.last_good = {
                    "seen": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ip": self.peer.ip if self.peer else "—",
                    "latency": latency,
                    "transport": transport,
                }
            else:
                self.quality_status.setText(f"Transport: {transport}")
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

    def open_http(self):
        if self.peer is None:
            self.test_result.setText("No online Android Tailscale device found.")
            return
        webbrowser.open(f"http://{self.peer.ip}:8080")
        self.test_result.setText("Opened HTTP 8080 in your browser.")

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
