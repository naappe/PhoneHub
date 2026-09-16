import subprocess
import sys
import webbrowser
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

APP_VERSION = "v2.7-phonehub-link"
PHONEHUB_VIEWER_URL = "https://naappe.github.io/PhoneHub/"
PHONEHUB_APK_URL = "https://github.com/naappe/PhoneHub/releases/download/phonehub-link-v0.1-test/PhoneHub-Link-v0.1-debug.apk"
ROOT = Path(r"C:\PhoneHub")
LEGACY_EXE = Path(r"C:\PhoneHub\dist\PhoneHub.exe")


class PhoneHubLink(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PhoneHub {APP_VERSION}")
        self.resize(1040, 680)
        self.build_ui()

    def build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 18, 18, 18)
        side.setSpacing(10)

        logo = QLabel("PhoneHub")
        logo.setObjectName("logo")
        side.addWidget(logo)

        sub = QLabel("PhoneHub Link")
        sub.setObjectName("muted")
        side.addWidget(sub)

        status = QLabel("● Ready")
        status.setObjectName("ready")
        side.addWidget(status)
        side.addStretch()

        version = QLabel(APP_VERSION)
        version.setObjectName("muted")
        side.addWidget(version)

        main = QVBoxLayout()
        main.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("card")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 24, 24, 24)
        hero_layout.setSpacing(12)

        title = QLabel("PhoneHub Link")
        title.setObjectName("title")
        hero_layout.addWidget(title)

        description = QLabel(
            "Connect to your Android phone from this PC using the new PhoneHub Link system.\n"
            "Normal use does not require USB, ADB, or Tailscale."
        )
        description.setWordWrap(True)
        description.setObjectName("body")
        hero_layout.addWidget(description)

        primary_row = QHBoxLayout()

        viewer = QPushButton("Open Phone Viewer")
        viewer.setObjectName("primary")
        viewer.clicked.connect(self.open_viewer)
        primary_row.addWidget(viewer)

        install = QPushButton("Install Phone App")
        install.clicked.connect(self.open_apk)
        primary_row.addWidget(install)

        hero_layout.addLayout(primary_row)
        main.addWidget(hero)

        steps = QFrame()
        steps.setObjectName("card")
        steps_layout = QVBoxLayout(steps)
        steps_layout.setContentsMargins(24, 22, 24, 22)
        steps_layout.setSpacing(10)

        steps_title = QLabel("Connect in 3 steps")
        steps_title.setObjectName("sectionTitle")
        steps_layout.addWidget(steps_title)

        steps_text = QLabel(
            "1. Open PhoneHub Link on the phone and start screen sharing.\n"
            "2. Note the 6-digit room code shown on the phone.\n"
            "3. Open Phone Viewer on this PC, enter the code, and press Connect."
        )
        steps_text.setObjectName("body")
        steps_text.setWordWrap(True)
        steps_layout.addWidget(steps_text)
        main.addWidget(steps)

        legacy = QFrame()
        legacy.setObjectName("card")
        legacy_layout = QVBoxLayout(legacy)
        legacy_layout.setContentsMargins(24, 20, 24, 20)
        legacy_layout.setSpacing(10)

        legacy_title = QLabel("Legacy tools")
        legacy_title.setObjectName("sectionTitle")
        legacy_layout.addWidget(legacy_title)

        legacy_text = QLabel(
            "The previous Tailscale + ADB PhoneHub is kept only as a fallback for older screen, camera, files, apps, and control tools."
        )
        legacy_text.setObjectName("body")
        legacy_text.setWordWrap(True)
        legacy_layout.addWidget(legacy_text)

        legacy_button = QPushButton("Open Legacy PhoneHub")
        legacy_button.clicked.connect(self.open_legacy)
        legacy_layout.addWidget(legacy_button)
        main.addWidget(legacy)
        main.addStretch()

        self.footer = QLabel("Ready — PhoneHub Link is the primary connection mode.")
        self.footer.setObjectName("muted")
        main.addWidget(self.footer)

        root.addWidget(sidebar, 1)
        root.addLayout(main, 4)

        self.setStyleSheet("""
            QWidget {
                background: #07111f;
                color: #f8fafc;
                font-family: Segoe UI;
                font-size: 14px;
            }
            QFrame#sidebar, QFrame#card {
                background: #0d1b2d;
                border: 1px solid #1f3654;
                border-radius: 16px;
            }
            QLabel#logo {
                font-size: 31px;
                font-weight: 900;
            }
            QLabel#title {
                font-size: 30px;
                font-weight: 900;
                color: #e0f2fe;
            }
            QLabel#sectionTitle {
                font-size: 20px;
                font-weight: 800;
                color: #e0f2fe;
            }
            QLabel#body {
                color: #dbeafe;
                font-size: 15px;
                line-height: 1.5;
            }
            QLabel#muted {
                color: #94a3b8;
            }
            QLabel#ready {
                color: #86efac;
                font-weight: 800;
                margin-top: 8px;
            }
            QPushButton {
                background: #13243a;
                color: #f8fafc;
                border: 1px solid #254363;
                border-radius: 12px;
                padding: 14px 18px;
                font-weight: 800;
                min-height: 20px;
            }
            QPushButton:hover {
                background: #1d3553;
            }
            QPushButton#primary {
                background: #2563eb;
                border: none;
                font-size: 16px;
                padding: 16px 20px;
            }
            QPushButton#primary:hover {
                background: #1d4ed8;
            }
        """)

    def open_viewer(self):
        webbrowser.open(PHONEHUB_VIEWER_URL)
        self.footer.setText("Phone Viewer opened in your browser.")

    def open_apk(self):
        webbrowser.open(PHONEHUB_APK_URL)
        self.footer.setText("PhoneHub Link APK download opened in your browser.")

    def open_legacy(self):
        if not LEGACY_EXE.exists():
            QMessageBox.warning(self, "PhoneHub", f"Legacy PhoneHub was not found at:\n{LEGACY_EXE}")
            return

        try:
            subprocess.Popen(
                [str(LEGACY_EXE)],
                cwd=str(ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            self.footer.setText("Legacy Tailscale + ADB PhoneHub opened.")
        except Exception as exc:
            QMessageBox.critical(self, "PhoneHub", f"Could not open legacy PhoneHub:\n{exc}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PhoneHubLink()
    window.show()
    sys.exit(app.exec())
