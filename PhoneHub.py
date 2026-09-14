import sys
import subprocess
import shutil
from device import get_device

from PySide6.QtWidgets import *
from PySide6.QtCore import Qt

class PhoneHub(QWidget):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("📱 PhoneHub")
        self.resize(430,650)

        self.setStyleSheet("""
        QWidget{
            background:#202124;
            color:white;
            font-family:Segoe UI;
            font-size:14px;
        }

        QPushButton{
            background:#2d89ef;
            border:none;
            border-radius:10px;
            padding:12px;
            font-size:15px;
        }

        QPushButton:hover{
            background:#4ea1ff;
        }

        QLabel{
            padding:4px;
        }
        """)

        layout=QVBoxLayout()

        title=QLabel("📱 PhoneHub")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:28px;font-weight:bold;")

        layout.addWidget(title)

        self.info=QLabel()
        layout.addWidget(self.info)

        refresh=QPushButton("🔄 Refresh")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)

        openBtn=QPushButton("📱 Open Phone")
        openBtn.clicked.connect(self.open_phone)
        layout.addWidget(openBtn)

        layout.addWidget(QPushButton("📷 Camera"))
        layout.addWidget(QPushButton("🖼 Photos"))
        layout.addWidget(QPushButton("📁 Files"))
        layout.addWidget(QPushButton("📍 Location"))
        layout.addWidget(QPushButton("⚙ Settings"))

        self.setLayout(layout)

        self.refresh()

    def refresh(self):
        d=get_device()

        txt=f"""
🟢 Connected : {d['connected']}

📱 Device : {d['device']}

🤖 Android : {d['android']}

🔋 Battery : {d['battery']}%

🌐 IP : {d['ip']}
"""

        self.info.setText(txt)

    def open_phone(self):

        scrcpy=shutil.which("scrcpy")

        if not scrcpy:
            QMessageBox.warning(self,"PhoneHub","scrcpy not found")
            return

        subprocess.Popen([
            scrcpy,
            "-s","100.118.102.57:5555",
            "--no-audio",
            "--max-size=480",
            "--video-bit-rate=350K",
            "--max-fps=12"
        ])

app=QApplication(sys.argv)

w=PhoneHub()
w.show()

sys.exit(app.exec())
