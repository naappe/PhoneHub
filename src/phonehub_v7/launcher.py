from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget


def project_root() -> Path:
    candidates = []
    if getattr(sys, 'frozen', False):
        candidates.append(Path(sys.executable).resolve().parent)
    candidates.append(Path.cwd().resolve())
    candidates.append(Path(__file__).resolve().parents[2])
    for start in candidates:
        current = start
        for _ in range(5):
            if (current / 'PHONEHUB.ps1').exists():
                return current
            if current.parent == current:
                break
            current = current.parent
    return candidates[0]


class Launcher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.root = project_root()
        self.script = self.root / 'PHONEHUB.ps1'
        self.setWindowTitle('Samsung Secure')
        self.setMinimumSize(620, 520)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(34, 30, 34, 30)
        layout.setSpacing(16)

        title = QLabel('Samsung Secure')
        title.setObjectName('title')
        subtitle = QLabel('One-time phone setup. Secure PC control.')
        subtitle.setObjectName('subtitle')
        info = QLabel(f'Project: {self.root}')
        info.setObjectName('info')
        info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(info)

        card = QFrame()
        card.setObjectName('card')
        grid = QGridLayout(card)
        grid.setContentsMargins(22, 22, 22, 22)
        grid.setSpacing(12)

        actions = [
            ('Setup / Update Phone', 'setup', 0, 0),
            ('Start PhoneHub', 'start', 0, 1),
            ('Build Companion', 'build', 1, 0),
            ('Install Companion', 'install', 1, 1),
            ('Phone / Project Status', 'status', 2, 0),
            ('Backup Phone Baseline', 'backup', 2, 1),
            ('Backup + Remove', 'remove', 3, 0),
            ('Clean Build Waste', 'clean', 3, 1),
            ('Update Source Only', 'update', 4, 0),
            ('Build / Refresh EXE', 'exe', 4, 1),
        ]

        for label, action, row, col in actions:
            button = QPushButton(label)
            button.setMinimumHeight(50)
            button.clicked.connect(lambda _=False, a=action: self.run_action(a))
            grid.addWidget(button, row, col)

        layout.addWidget(card)
        note = QLabel('Commands open in PowerShell so build output, prompts and errors remain visible.')
        note.setWordWrap(True)
        note.setObjectName('note')
        layout.addWidget(note)
        layout.addStretch()

        self.setStyleSheet('''
            QWidget { background:#f5f7fb; color:#182033; font-family:Arial; font-size:14px; }
            #title { font-size:32px; font-weight:700; }
            #subtitle { font-size:16px; color:#526078; }
            #info { color:#7a8599; font-size:12px; }
            #card { background:#ffffff; border:1px solid #e2e8f0; border-radius:16px; }
            QPushButton { background:#ffffff; border:1px solid #dbe3ef; border-radius:10px; padding:10px 14px; text-align:left; font-weight:600; }
            QPushButton:hover { background:#edf4ff; border-color:#b8cdf5; }
            #note { color:#6b7280; }
        ''')

    def run_action(self, action: str):
        if not self.script.exists():
            QMessageBox.critical(self, 'Samsung Secure', f'PHONEHUB.ps1 was not found in:\n{self.root}')
            return
        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(self.script), action]
        flags = getattr(subprocess, 'CREATE_NEW_CONSOLE', 0)
        try:
            subprocess.Popen(command, cwd=str(self.root), creationflags=flags)
        except Exception as exc:
            QMessageBox.critical(self, 'PhoneHub', str(exc))


def main():
    app = QApplication(sys.argv)
    window = Launcher()
    window.show()
    raise SystemExit(app.exec())


if __name__ == '__main__':
    main()