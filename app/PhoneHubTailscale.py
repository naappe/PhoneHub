import sys
import threading

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from phonehub_service_client import PhoneHubServiceClient
from PhoneHub import (
    PhoneHub,
    READABLE_SCREEN,
    connect_remote_adb,
    get_saved_ip,
    phone_prop,
    battery_level,
    read_last_location_text,
    save_phone_ip,
)
from phone_config import normalize_tailscale_ipv4

APP_VERSION = "v2.8-phonehub-service-first"


class PhoneHubTailscale(PhoneHub):
    def __init__(self):
        self.use_adb_fallback = False
        super().__init__()
        self.setWindowTitle(f"PhoneHub {APP_VERSION}")

    def page_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        ip_box, ip_layout, _ = self.card(
            "Phone Tailscale IP",
            "Enter the phone Tailscale IP here. PhoneHub Service uses port 8765 first. ADB is kept only as an explicit fallback.",
        )

        self.dashboard_ip_input = QLineEdit()
        ip, _ = get_saved_ip()
        self.dashboard_ip_input.setText(ip)
        self.dashboard_ip_input.setPlaceholderText("Example: 100.70.94.21")
        ip_layout.addWidget(self.dashboard_ip_input)

        ip_actions = QHBoxLayout()

        save_connect = QPushButton("Save & Connect")
        save_connect.setObjectName("primary")
        save_connect.clicked.connect(self.dashboard_save_and_connect)

        refresh = QPushButton("Refresh Status")
        refresh.clicked.connect(self.refresh_status)

        adb_fallback = QPushButton("Use ADB Fallback")
        adb_fallback.clicked.connect(self.enable_adb_fallback)

        ip_actions.addWidget(save_connect)
        ip_actions.addWidget(refresh)
        ip_actions.addWidget(adb_fallback)
        ip_layout.addLayout(ip_actions)
        layout.addWidget(ip_box)

        box, _, self.device_info = self.card("Dashboard", "Checking phone...")
        layout.addWidget(box)

        loc_box, _, self.location_info = self.card("Location Status", self._location_text())
        layout.addWidget(loc_box)

        row = QHBoxLayout()

        open_screen = QPushButton("Open Screen")
        open_screen.setObjectName("primary")
        open_screen.clicked.connect(lambda: self.open_screen(READABLE_SCREEN, keep_alive=True))

        setup = QPushButton("Advanced Setup")
        setup.clicked.connect(lambda: self.show_page(1))

        row.addWidget(open_screen)
        row.addWidget(setup)
        layout.addLayout(row)

        return page

    def _location_text(self):
        return read_last_location_text()

    def enable_adb_fallback(self):
        self.use_adb_fallback = True
        self.set_footer("ADB fallback enabled for this session.")
        self.refresh_status()

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

        self.set_footer(f"Saved {ip}. Checking PhoneHub Service...")
        self.refresh_status()

    def refresh_status(self):
        ip, _ = get_saved_ip()
        if not ip:
            self.side_status.setText("Phone IP not set")
            self.set_footer("Enter the phone Tailscale IP in Setup New Phone.")
            if hasattr(self, "device_info"):
                self.device_info.setText(
                    "Phone Status: Not configured\n"
                    "Connection: PhoneHub Service\n"
                    "Saved Phone IP: Not set\n\n"
                    "Open Setup New Phone and enter the phone's Tailscale 100.x.x.x address."
                )
            return

        self.set_footer("Checking PhoneHub Service...")
        threading.Thread(target=self.refresh_worker, daemon=True).start()

    def refresh_worker(self):
        ip, port = get_saved_ip()
        service_client = PhoneHubServiceClient.from_saved_credentials(ip)

        if service_client and service_client.ping():
            status = service_client.device_status()
            self.bridge.status.emit({
                "connected": True,
                "connection": "PhoneHub Service",
                "adb": False,
                "model": status.get("model") or status.get("device") or "Android Phone",
                "android": status.get("androidVersion") or status.get("android") or "-",
                "battery": status.get("batteryPercent") or status.get("battery") or "-",
                "target": f"{ip}:8765",
                "mobile_mode": "Android background service",
            })
            return

        if not self.use_adb_fallback:
            self.bridge.status.emit({
                "connected": False,
                "connection": "PhoneHub Service",
                "adb": False,
                "model": "-",
                "android": "-",
                "battery": "-",
                "target": f"{ip}:8765",
                "mobile_mode": "Android app not paired",
            })
            return

        ok = connect_remote_adb()
        self.bridge.status.emit({
            "connected": ok,
            "connection": "ADB Fallback",
            "adb": ok,
            "model": phone_prop("ro.product.model") if ok else "-",
            "android": phone_prop("ro.build.version.release") if ok else "-",
            "battery": battery_level() if ok else "-",
            "target": f"{ip}:{port}",
            "mobile_mode": "Tailscale + ADB fallback",
        })

    def apply_status(self, data):
        connected = data.get("connected", False)
        connection = data.get("connection", "PhoneHub Service")
        mobile_mode = data.get("mobile_mode", "Android app not paired")
        target = data.get("target", "-")
        adb = data.get("adb", False)

        self.side_status.setText("Phone online" if connected else "Phone offline")
        if connected:
            self.set_footer("Ready.")
        elif mobile_mode == "Android app not paired":
            self.set_footer("PhoneHub Android app not paired. Generate a code on the phone and pair this PC.")
        else:
            self.set_footer("Phone offline. Check Tailscale and saved phone IP.")

        self.device_info.setText(
            f"Phone Status: {'Online' if connected else 'Offline'}\n"
            f"Device: {data.get('model', '-')}\n"
            f"Android Version: {data.get('android', '-')}\n"
            f"Battery: {data.get('battery', '-')}%\n"
            f"Connection: {connection}\n"
            f"ADB Status: {'Connected' if adb else 'Not Used'}\n"
            f"Service Target: {target}\n"
            f"Mobile Mode: {mobile_mode}"
        )

        self.location_info.setText(read_last_location_text())


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = PhoneHubTailscale()
    win.show()
    sys.exit(app.exec())
