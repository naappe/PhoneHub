import sys

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PhoneHub import (
    PhoneHub,
    READABLE_SCREEN,
    connect_remote_adb,
    get_saved_ip,
    save_phone_ip,
)
from phone_config import normalize_tailscale_ipv4

APP_VERSION = "v2.7-tailscale-dashboard"


class PhoneHubTailscale(PhoneHub):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PhoneHub {APP_VERSION}")

    def page_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)

        ip_box, ip_layout, _ = self.card(
            "Phone Tailscale IP",
            "Enter the phone Tailscale IP here. This saved IP is used by Screen, Camera, Files, Apps, Control, Screenshot, Wake and Lock.",
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

        ip_actions.addWidget(save_connect)
        ip_actions.addWidget(refresh)
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
    win = PhoneHubTailscale()
    win.show()
    sys.exit(app.exec())
