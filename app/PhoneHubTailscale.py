import sys
import re
import urllib.request
from pathlib import Path

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
    parse_adb_devices,
    run_quiet,
    run_background,
)
from phone_config import normalize_tailscale_ipv4

APP_VERSION = "v2.9.1-auto-tailscale-installer-fix"
TAILSCALE_PACKAGE = "com.tailscale.ipn"
TAILSCALE_STABLE_PAGE = "https://pkgs.tailscale.com/stable/"
TAILSCALE_BASE_URL = "https://pkgs.tailscale.com/stable/"
TAILSCALE_APK_DIR = Path(r"C:\\PhoneHub\\runtime\\downloads")


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

    def page_setup_new_phone(self):
        page = super().page_setup_new_phone()
        layout = page.layout()

        tailscale_box, tailscale_layout, self.tailscale_setup_status = self.card(
            "Tailscale on phone",
            "PhoneHub checks the connected USB phone. If Tailscale is missing, you can install the official stable APK directly from PhoneHub without Google Play.",
        )

        row = QHBoxLayout()
        check_btn = QPushButton("Check Tailscale")
        check_btn.clicked.connect(self.check_tailscale_clicked)

        install_btn = QPushButton("Install Tailscale")
        install_btn.setObjectName("primary")
        install_btn.clicked.connect(self.install_tailscale_clicked)

        open_btn = QPushButton("Open Tailscale")
        open_btn.clicked.connect(self.open_tailscale_clicked)

        row.addWidget(check_btn)
        row.addWidget(install_btn)
        row.addWidget(open_btn)
        tailscale_layout.addLayout(row)

        layout.addWidget(tailscale_box)
        return page

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

        self._set_tailscale_status("Downloading official Tailscale APK...")

        def worker():
            try:
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
                    ["adb", "-s", serial, "install", "-r", str(apk_path)],
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
    win = PhoneHubTailscale()
    win.show()
    sys.exit(app.exec())
