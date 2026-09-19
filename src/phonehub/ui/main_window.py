from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from phonehub.core.state import AppState
from phonehub.domain.models import DeviceSnapshot
from phonehub.ui.theme import APP_STYLE


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PhoneHub 5")
        self.resize(1180, 760)
        self.setMinimumSize(960, 620)
        self.setStyleSheet(APP_STYLE)

        self.state = AppState()
        self.state.device_changed.connect(self._render_device)

        shell = QWidget()
        self.setCentralWidget(shell)
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_content(), 1)

        self._render_device(self.state.device)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(218)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(7)

        brand = QLabel("PhoneHub")
        brand.setObjectName("Brand")
        layout.addWidget(brand)

        subtitle = QLabel("Device Command Center")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)
        layout.addSpacing(22)

        self.stack = QStackedWidget()
        self.nav_buttons: list[QPushButton] = []

        pages: list[tuple[str, Callable[[], QWidget]]] = [
            ("Overview", self._overview_page),
            ("Device", lambda: self._placeholder_page("Device", "Pairing, identity and connection health.")),
            ("Screen", lambda: self._placeholder_page("Screen", "A single media-session owner will control mirroring.")),
            ("Camera", lambda: self._placeholder_page("Camera", "Front and rear camera sessions will be isolated from screen mirroring.")),
            ("Files", lambda: self._placeholder_page("Files", "Transfer and capture history will live here.")),
            ("Security", lambda: self._placeholder_page("Security", "Read-only device and transport diagnostics.")),
            ("Settings", lambda: self._placeholder_page("Settings", "Transport, quality and application preferences.")),
        ]

        for index, (label, builder) in enumerate(pages):
            button = QPushButton(label)
            button.setObjectName("Nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self._select_page(i))
            layout.addWidget(button)
            self.nav_buttons.append(button)
            self.stack.addWidget(builder())

        layout.addStretch()

        self.connection_badge = QLabel("● Offline")
        self.connection_badge.setObjectName("Muted")
        layout.addWidget(self.connection_badge)

        self._select_page(0)
        return sidebar

    def _build_content(self) -> QWidget:
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.addWidget(self.stack, 1)
        return content

    def _select_page(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def _card(self, title: str, body: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(9)

        heading = QLabel(title)
        heading.setStyleSheet("font-size:16px;font-weight:750;")
        layout.addWidget(heading)

        text = QLabel(body)
        text.setObjectName("Muted")
        text.setWordWrap(True)
        layout.addWidget(text)
        return card

    def _overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(16)

        title = QLabel("Overview")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        subtitle = QLabel("A clean PhoneHub rebuild with explicit state and isolated services.")
        subtitle.setObjectName("Muted")
        layout.addWidget(subtitle)

        status = QFrame()
        status.setObjectName("Card")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(20, 18, 20, 20)

        self.device_metric = QLabel("Not connected")
        self.device_metric.setObjectName("Metric")
        status_layout.addWidget(self.device_metric)

        self.device_detail = QLabel("Ready for fresh device setup.")
        self.device_detail.setObjectName("Muted")
        self.device_detail.setWordWrap(True)
        status_layout.addWidget(self.device_detail)

        layout.addWidget(status)

        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._card("One session owner", "Screen and camera will never compete for an ADB/scrcpy transport."))
        row.addWidget(self._card("Typed state machine", "Connection transitions are explicit: disconnected, connecting, online, degraded and recovering."))
        row.addWidget(self._card("No legacy code", "Old services, old launchers and compatibility layers are not part of this branch."))
        layout.addLayout(row)

        actions = QHBoxLayout()
        connect = QPushButton("Begin device setup")
        connect.setObjectName("Primary")
        connect.setEnabled(False)
        actions.addWidget(connect)
        actions.addStretch()
        layout.addLayout(actions)

        layout.addStretch()
        return page

    def _placeholder_page(self, title_text: str, description: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)

        title = QLabel(title_text)
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        layout.addWidget(self._card("Fresh module", description))
        layout.addStretch()
        return page

    def _render_device(self, snapshot: DeviceSnapshot) -> None:
        self.device_metric.setText(snapshot.device_name)
        self.device_detail.setText(snapshot.detail)
        self.connection_badge.setText(f"● {snapshot.state.value.title()}")
