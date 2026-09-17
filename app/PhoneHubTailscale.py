import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
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

APP_VERSION = "v2.8-compact-ui"


class PhoneHubTailscale(PhoneHub):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PhoneHub {APP_VERSION}")

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
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(168)

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(10, 10, 10, 10)
        side.setSpacing(5)

        logo = QLabel("PhoneHub")
        logo.setObjectName("logo")
        side.addWidget(logo)

        sub = QLabel("Tailscale Control")
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
            ("Apps", self.page_apps),
            ("Control", self.page_control),
            ("Settings", self.page_settings),
        ]

        for index, (name, builder) in enumerate(pages):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            btn.setMinimumHeight(34)
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
        main_wrap.setSpacing(5)
        main_wrap.addWidget(self.stack, 1)

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        self.footer.setWordWrap(True)
        self.footer.setMaximumHeight(38)
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
        lay.setContentsMargins(11, 10, 11, 10)
        lay.setSpacing(6)

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
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(7)

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

        # Keep location available without making the first screen excessively tall.
        loc_box, _, self.location_info = self.card("Location History", self._location_text())
        layout.addWidget(loc_box)
        layout.addStretch()

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
