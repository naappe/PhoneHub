import sys
import re
import urllib.request
import shutil
import subprocess
import ctypes
import math
import wave
import struct
import signal
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QObject, Signal
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
    scrcpy_path,
)
from phone_config import normalize_tailscale_ipv4

APP_VERSION = "v3.12-call-audio-test"
TAILSCALE_PACKAGE = "com.tailscale.ipn"
TAILSCALE_STABLE_PAGE = "https://pkgs.tailscale.com/stable/"
TAILSCALE_BASE_URL = "https://pkgs.tailscale.com/stable/"
TAILSCALE_APK_DIR = Path(r"C:\\PhoneHub\\runtime\\downloads")
LOCAL_APK_DIR = Path(r"C:\\PhoneHub\\apps")


class AutoDetectBridge(QObject):
    state = Signal(dict)
    wizard = Signal(dict)
    health = Signal(dict)

class PhoneHubTailscale(PhoneHub):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"PhoneHub {APP_VERSION}")

        # Automatically detect USB/remote connection changes so the Setup page
        # changes to Connected without requiring the user to press Smart Check.
        self._last_connection_signature = None
        self._auto_unlock_waiting = False
        self._auto_unlock_serial = ""
        self._auto_detect_busy = False

        self.auto_bridge = AutoDetectBridge()
        self.auto_bridge.state.connect(self._apply_auto_detect_state)
        self.auto_bridge.wizard.connect(self._apply_wizard_result)
        self.auto_bridge.health.connect(self._apply_health_results)

        self.wizard_step = 1
        self.wizard_serial = ""
        self.wizard_detected_ip = ""
        self.wizard_remote_connected = False
        self._wizard_busy = False
        self._health_busy = False
        self.audio_process = None
        self.audio_recording = False
        self.audio_record_path = ""
        self.audio_source = "mic-voice-communication"
        self.audio_log_handle = None
        self.audio_log_path = ""
        self.audio_level_text = "Level: No recording analyzed yet"

        # Detection now runs in a background thread. The old implementation ran
        # several adb commands on the UI thread every 3 seconds, which caused
        # visible freezing/slowness.
        self.connection_timer = QTimer(self)
        self.connection_timer.setInterval(7000)
        self.connection_timer.timeout.connect(self.auto_refresh_connection_state)
        self.connection_timer.start()
        QTimer.singleShot(700, self.auto_refresh_connection_state)

        self.unlock_timer = QTimer(self)
        self.unlock_timer.setInterval(2500)
        self.unlock_timer.timeout.connect(self._check_unlock_progress)

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
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(176)

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        side.setSpacing(8)

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
            ("Audio", self.page_audio),
            ("Files", self.page_files),
            ("Apps", self.page_apps),
            ("Control", self.page_control),
            ("Settings", self.page_settings),
        ]

        for index, (name, builder) in enumerate(pages):
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            btn.setMinimumHeight(38)
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
        main_wrap.setSpacing(8)
        main_wrap.addWidget(self.stack, 1)

        self.footer = QLabel("Ready")
        self.footer.setObjectName("footer")
        self.footer.setWordWrap(False)
        self.footer.setMaximumHeight(24)
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
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        t = QLabel(title)
        t.setObjectName("title")
        lay.addWidget(t)

        lbl = QLabel(text)
        lbl.setObjectName("big")
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lbl)

        return box, lay, lbl

    def page_audio(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        box, box_layout, _ = self.card(
            "Phone Microphone",
            "Listen live to the microphone on your connected Android phone. "
            "Recording is optional and starts only when you press Record.",
        )

        self.audio_status = QLabel("Status: Idle")
        self.audio_status.setObjectName("sideStatus")
        self.audio_status.setWordWrap(True)
        box_layout.addWidget(self.audio_status)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        start_btn = QPushButton("Start Listening")
        start_btn.setObjectName("primary")
        start_btn.setMinimumHeight(44)
        start_btn.clicked.connect(self.start_live_audio)

        self.audio_record_button = QPushButton("Record")
        self.audio_record_button.setMinimumHeight(44)
        self.audio_record_button.clicked.connect(self.toggle_audio_recording)

        stop_btn = QPushButton("Stop")
        stop_btn.setMinimumHeight(44)
        stop_btn.clicked.connect(self.stop_live_audio)

        actions.addWidget(start_btn)
        actions.addWidget(self.audio_record_button)
        actions.addWidget(stop_btn)
        box_layout.addLayout(actions)

        voice_actions = QHBoxLayout()
        voice_actions.setSpacing(8)

        clear_voice = QPushButton("Clear Voice")
        clear_voice.setObjectName("primary")
        clear_voice.clicked.connect(lambda: self.set_audio_source("mic-voice-communication", "Clear Voice"))

        natural_voice = QPushButton("Natural Mic")
        natural_voice.clicked.connect(lambda: self.set_audio_source("mic", "Natural Mic"))

        voice_actions.addWidget(clear_voice)
        voice_actions.addWidget(natural_voice)
        box_layout.addLayout(voice_actions)

        call_actions = QHBoxLayout()
        call_actions.setSpacing(8)

        call_both = QPushButton("Call Both")
        call_both.clicked.connect(lambda: self.set_audio_source("voice-call", "Call Both"))

        call_other = QPushButton("Other Side")
        call_other.clicked.connect(lambda: self.set_audio_source("voice-call-downlink", "Call Other Side"))

        call_me = QPushButton("My Side")
        call_me.clicked.connect(lambda: self.set_audio_source("voice-call-uplink", "Call My Side"))

        call_actions.addWidget(call_both)
        call_actions.addWidget(call_other)
        call_actions.addWidget(call_me)
        box_layout.addLayout(call_actions)

        self.call_test_note = QLabel(
            "Call test: use only on your own phone/calls. Android or the dialer may block call-audio capture. "
            "If blocked, PhoneHub will show an error instead of pretending it worked."
        )
        self.call_test_note.setObjectName("big")
        self.call_test_note.setWordWrap(True)
        box_layout.addWidget(self.call_test_note)

        self.audio_mode_label = QLabel("Voice mode: Clear Voice + Low Echo (40 ms buffer; Android echo cancellation when supported)")
        self.audio_mode_label.setObjectName("big")
        self.audio_mode_label.setWordWrap(True)
        box_layout.addWidget(self.audio_mode_label)

        self.audio_record_file = QLabel("Recording file: None")
        self.audio_record_file.setObjectName("big")
        self.audio_record_file.setWordWrap(True)
        self.audio_record_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box_layout.addWidget(self.audio_record_file)

        self.audio_level_label = QLabel("Level: No recording analyzed yet")
        self.audio_level_label.setObjectName("big")
        self.audio_level_label.setWordWrap(True)
        box_layout.addWidget(self.audio_level_label)

        level_actions = QHBoxLayout()
        level_actions.setSpacing(8)

        analyze_btn = QPushButton("Analyze Last Recording")
        analyze_btn.clicked.connect(self.analyze_last_audio_recording)

        vol_down = QPushButton("Volume -")
        vol_down.clicked.connect(lambda: self.adjust_windows_volume(-3))

        vol_up = QPushButton("Volume +")
        vol_up.clicked.connect(lambda: self.adjust_windows_volume(3))

        mixer = QPushButton("Volume Mixer")
        mixer.clicked.connect(self.open_windows_volume_mixer)

        level_actions.addWidget(analyze_btn)
        level_actions.addWidget(vol_down)
        level_actions.addWidget(vol_up)
        level_actions.addWidget(mixer)
        box_layout.addLayout(level_actions)

        open_folder = QPushButton("Open Recordings Folder")
        open_folder.clicked.connect(self.open_audio_recordings_folder)
        box_layout.addWidget(open_folder)

        layout.addWidget(box)

        info, _, _ = self.card(
            "How it works",
            "Clear Voice uses Android's voice-communication microphone processing and a low-latency 40 ms buffer. "
            "Call Both / Other Side / My Side use Android call-audio sources for testing an active call when the device permits it. "
            "This can reduce delayed echo and may use Android echo cancellation / automatic gain control when supported. "
            "Natural Mic uses the raw normal microphone path. When Record is enabled, "
            "PhoneHub restarts the same selected microphone stream with scrcpy recording enabled and saves "
            "an Opus audio file under C:\\PhoneHub\\runtime\\audio. "
            "Press Record again to stop recording while continuing live listening. "
            "For the strongest echo reduction, use headphones on the PC or keep PC speaker volume low so the phone microphone does not hear the delayed PC playback. "
            "Recordings are saved as AAC audio in an M4A container for Windows playback. PhoneHub now stops scrcpy gracefully so the file is finalized correctly. Peak analysis uses FFmpeg when available.",
        )
        layout.addWidget(info)
        layout.addStretch()
        return page

    def set_audio_source(self, source, label):
        self.audio_source = source
        if hasattr(self, "audio_mode_label"):
            labels = {
                "mic-voice-communication": "Voice mode: Clear Voice + Low Echo",
                "mic": "Voice mode: Natural Mic",
                "voice-call": "Voice mode: Call Both Sides",
                "voice-call-downlink": "Voice mode: Call Other Side (downlink)",
                "voice-call-uplink": "Voice mode: Call My Side (uplink)",
            }
            self.audio_mode_label.setText(labels.get(source, f"Voice mode: {label}"))

        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            was_recording = getattr(self, "audio_recording", False)
            record_path = self.audio_record_path if was_recording else ""
            self._stop_audio_process_only()
            self.set_footer(f"Switching audio mode to {label}...")
            self._launch_live_audio(record_path)
        else:
            self.set_footer(f"Audio mode set to {label}.")

    def _audio_target(self):
        ip, port = get_saved_ip()
        target = f"{ip}:{port}" if ip else ""
        usb, remote, unauthorized, _ = parse_adb_devices()

        if target and target in remote:
            return target
        if usb:
            return usb[0]
        return ""

    def _launch_live_audio(self, record_path=""):
        scrcpy = scrcpy_path()
        if not scrcpy:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Error — scrcpy not found")
            self.set_footer("scrcpy is required for live microphone audio.")
            return False

        help_text = run_quiet([scrcpy, "--help"], timeout=5)
        if "--audio-source" not in help_text:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Error — this scrcpy build does not support microphone audio")
            self.set_footer("Update scrcpy to use PhoneHub live audio.")
            return False

        target = self._audio_target()
        if not target:
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Error — phone is not connected")
            self.set_footer("Connect the phone through USB or Tailscale ADB first.")
            return False

        args = [
            scrcpy,
            "--serial", target,
            f"--audio-source={getattr(self, 'audio_source', 'mic-voice-communication')}",
            "--no-video",
            "--no-control",
            "--audio-buffer=40",
        ]
        if record_path:
            args.extend([
                "--audio-codec=aac",
                "--audio-bit-rate=128K",
                "--require-audio",
                f"--record={record_path}",
            ])

        log_dir = Path(r"C:\PhoneHub\runtime\logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
        self.audio_log_path = str(log_dir / f"audio_{log_stamp}.log")

        try:
            if self.audio_log_handle:
                try:
                    self.audio_log_handle.close()
                except Exception:
                    pass
            self.audio_log_handle = open(self.audio_log_path, "w", encoding="utf-8", errors="ignore")
            self.audio_process = subprocess.Popen(
                args,
                stdout=self.audio_log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=(
                    (subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)
                    if sys.platform.startswith("win") else 0
                ),
            )
        except Exception as exc:
            self.audio_process = None
            if hasattr(self, "audio_status"):
                self.audio_status.setText(f"Status: Error — {exc}")
            self.set_footer("Could not start phone microphone audio.")
            return False

        if hasattr(self, "audio_status"):
            self.audio_status.setText(
                f"Status: Connecting + Recording — {target}"
                if record_path else
                f"Status: Connecting — {target}"
            )
        self.set_footer(
            "Starting live microphone recording..."
            if record_path else
            "Starting live phone microphone audio..."
        )
        QTimer.singleShot(1500, self._verify_live_audio)
        return True

    def start_live_audio(self):
        existing = getattr(self, "audio_process", None)
        if existing and existing.poll() is None:
            if hasattr(self, "audio_status"):
                self.audio_status.setText(
                    "Status: Listening + Recording"
                    if getattr(self, "audio_recording", False)
                    else "Status: Listening"
                )
            self.set_footer("Phone microphone is already streaming.")
            return

        self.audio_recording = False
        self._launch_live_audio("")

    def _verify_live_audio(self):
        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            if hasattr(self, "audio_status"):
                self.audio_status.setText(
                    "Status: Listening + Recording"
                    if getattr(self, "audio_recording", False)
                    else "Status: Listening"
                )
            self.set_footer(
                "Live microphone is playing and recording."
                if getattr(self, "audio_recording", False)
                else "Live phone microphone audio is playing on this PC."
            )
        else:
            self.audio_process = None
            detail = ""
            try:
                if self.audio_log_handle:
                    self.audio_log_handle.flush()
                log_path = Path(getattr(self, "audio_log_path", ""))
                if log_path.exists():
                    lines = log_path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
                    if lines:
                        detail = lines[-1][:180]
            except Exception:
                pass

            if hasattr(self, "audio_status"):
                self.audio_status.setText(
                    "Status: Error — " + (detail or "microphone stream could not start")
                )
            self.set_footer(
                "Recording failed. PhoneHub saved the scrcpy error log for diagnosis."
                if getattr(self, "audio_recording", False)
                else "Live audio failed. Check phone connection and scrcpy audio support."
            )

    def _stop_audio_process_only(self):
        proc = getattr(self, "audio_process", None)
        if proc and proc.poll() is None:
            graceful = False

            # scrcpy must exit cleanly so MP4/M4A can write its final moov index.
            # On Windows, CTRL_BREAK reaches the new process group without
            # abruptly killing the recorder.
            if sys.platform.startswith("win"):
                try:
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                    proc.wait(timeout=5)
                    graceful = True
                except Exception:
                    graceful = False
            else:
                try:
                    proc.send_signal(signal.SIGINT)
                    proc.wait(timeout=5)
                    graceful = True
                except Exception:
                    graceful = False

            if not graceful and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=2)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        self.audio_process = None

        if self.audio_log_handle:
            try:
                self.audio_log_handle.flush()
                self.audio_log_handle.close()
            except Exception:
                pass
            self.audio_log_handle = None

    def toggle_audio_recording(self):
        if getattr(self, "audio_recording", False):
            self._stop_audio_process_only()
            self.audio_recording = False
            if hasattr(self, "audio_record_button"):
                self.audio_record_button.setText("Record")
            if hasattr(self, "audio_status"):
                self.audio_status.setText("Status: Restarting live listening...")
            self.set_footer("Recording saved. Analyzing level, then continuing live listening...")
            self.analyze_last_audio_recording()
            self._launch_live_audio("")
            return

        recordings = Path(r"C:\PhoneHub\runtime\audio")
        recordings.mkdir(parents=True, exist_ok=True)

        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        record_path = recordings / f"phone_mic_{stamp}.m4a"

        self._stop_audio_process_only()
        self.audio_recording = True
        self.audio_record_path = str(record_path)

        if hasattr(self, "audio_record_button"):
            self.audio_record_button.setText("Stop Recording")
        if hasattr(self, "audio_record_file"):
            self.audio_record_file.setText(f"Recording file: {record_path}")

        if not self._launch_live_audio(str(record_path)):
            self.audio_recording = False
            if hasattr(self, "audio_record_button"):
                self.audio_record_button.setText("Record")

    def adjust_windows_volume(self, steps):
        if not sys.platform.startswith("win"):
            self.set_footer("Volume buttons are available on Windows.")
            return

        vk = 0xAF if steps > 0 else 0xAE  # VK_VOLUME_UP / VK_VOLUME_DOWN
        count = max(1, abs(int(steps)))
        try:
            for _ in range(count):
                ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            self.set_footer(
                "Windows output volume increased."
                if steps > 0 else
                "Windows output volume decreased."
            )
        except Exception as exc:
            self.set_footer(f"Could not change Windows volume: {exc}")

    def open_windows_volume_mixer(self):
        try:
            subprocess.Popen(["sndvol.exe"])
            self.set_footer("Opened Windows Volume Mixer.")
        except Exception as exc:
            self.set_footer(f"Could not open Volume Mixer: {exc}")

    def analyze_last_audio_recording(self):
        path_text = getattr(self, "audio_record_path", "")
        if not path_text:
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText("Level: No recording available")
            self.set_footer("No PhoneHub audio recording is available to analyze.")
            return

        path = Path(path_text)
        if not path.exists():
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText("Level: Recording file not found")
            self.set_footer("The last recording file could not be found.")
            return

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            text = "Level: Recording saved as M4A/AAC. Install FFmpeg for peak analysis."
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText(text)
            self.set_footer(text)
            return

        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-i", str(path),
                    "-af", "volumedetect",
                    "-f", "null",
                    "NUL" if sys.platform.startswith("win") else "/dev/null",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0),
            )
            report = (result.stdout or "") + "\n" + (result.stderr or "")
            mean_match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", report)
            max_match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", report)

            if not max_match:
                raise ValueError("FFmpeg did not return a peak level.")

            peak_db = float(max_match.group(1))
            mean_db = float(mean_match.group(1)) if mean_match else None

            if peak_db >= -0.5:
                state = "PEAKING / clipping risk"
            elif peak_db >= -3.0:
                state = "Very loud / close to peak"
            elif peak_db >= -12.0:
                state = "Good voice level"
            elif peak_db >= -20.0:
                state = "A little low"
            else:
                state = "Too low"

            text = f"Level: {state} | Peak {peak_db:.1f} dBFS"
            if mean_db is not None:
                text += f" | Average {mean_db:.1f} dBFS"

            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText(text)
            self.set_footer(text)
        except Exception as exc:
            text = f"Level: Recording plays normally; analysis unavailable — {exc}"
            if hasattr(self, "audio_level_label"):
                self.audio_level_label.setText(text)
            self.set_footer(text)

    def open_audio_recordings_folder(self):
        folder = Path(r"C:\PhoneHub\runtime\audio")
        folder.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.Popen(["explorer", str(folder)])
        except Exception:
            self.set_footer(f"Recordings folder: {folder}")

    def stop_live_audio(self):
        self._stop_audio_process_only()
        was_recording = getattr(self, "audio_recording", False)
        self.audio_recording = False
        if hasattr(self, "audio_record_button"):
            self.audio_record_button.setText("Record")
        if hasattr(self, "audio_status"):
            self.audio_status.setText("Status: Idle")
        self.set_footer(
            "Phone microphone stopped. Recording saved."
            if was_recording else
            "Phone microphone audio stopped."
        )
        if was_recording:
            self.analyze_last_audio_recording()

    def closeEvent(self, event):
        self.stop_live_audio()
        event.accept()

    def page_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        ip, port = get_saved_ip()
        shown_ip = ip or "Not set"
        shown_target = f"{ip}:{port}" if ip else "Not set"

        text = (
            f"PhoneHub {APP_VERSION}\n\n"
            f"Saved Phone IP: {shown_ip}\n"
            f"ADB Target: {shown_target}\n\n"
            f"Mobile requirement: Tailscale only.\n"
            f"Screen/control works through Tailscale + ADB.\n"
            f"Audio page uses scrcpy microphone forwarding.\n"
            f"No audio recording is enabled by default.\n\n"
            f"Daily use:\n"
            f"1. Keep Tailscale ON on PC\n"
            f"2. Keep Tailscale ON on phone\n"
            f"3. Open PhoneHub\n"
            f"4. Use Home / Screen / Camera / Audio / Files / Apps / Control\n\n"
            f"For a new phone or repairs, use Setup."
        )

        info, _, _ = self.card("Settings", text)
        layout.addWidget(info)
        layout.addStretch()
        return page

    def show_page(self, index):
        self.stack.setCurrentIndex(index)

        for i, btn in enumerate(self.nav_buttons):
            btn.setObjectName("navActive" if i == index else "nav")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        names = [
            "Home",
            "Setup",
            "Screen",
            "Camera",
            "Audio",
            "Files",
            "Apps",
            "Control",
            "Settings",
        ]
        if 0 <= index < len(names):
            self.set_footer(f"Opened {names[index]} page.")

    def page_dashboard(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

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
        """Simple one-path setup wizard.

        Only the action needed for the current step is shown. The wizard
        advances automatically whenever PhoneHub detects that a step is done.
        """
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header, header_layout, _ = self.card(
            "PhoneHub Setup",
            "Follow one step at a time. PhoneHub checks each step before moving forward.",
        )

        self.wizard_progress = QLabel("Step 1 of 6")
        self.wizard_progress.setObjectName("title")
        header_layout.addWidget(self.wizard_progress)
        layout.addWidget(header)

        step_box, step_layout, _ = self.card("Current step", "")
        self.wizard_title = QLabel("Connect phone by USB")
        self.wizard_title.setObjectName("title")
        self.wizard_title.setWordWrap(True)

        self.wizard_instruction = QLabel("")
        self.wizard_instruction.setObjectName("big")
        self.wizard_instruction.setWordWrap(True)

        self.wizard_status = QLabel("")
        self.wizard_status.setObjectName("sideStatus")
        self.wizard_status.setWordWrap(True)

        self.wizard_action_button = QPushButton("Check Again")
        self.wizard_action_button.setObjectName("primary")
        self.wizard_action_button.setMinimumHeight(48)
        self.wizard_action_button.clicked.connect(self.wizard_action)

        step_layout.addWidget(self.wizard_title)
        step_layout.addWidget(self.wizard_instruction)
        step_layout.addWidget(self.wizard_status)
        step_layout.addWidget(self.wizard_action_button)
        layout.addWidget(step_box)

        overview, overview_layout, _ = self.card("Setup path", "")
        self.wizard_steps_label = QLabel(
            "1  USB connection\n"
            "2  Unlock phone once\n"
            "3  Tailscale installed\n"
            "4  Tailscale connected + IP detected\n"
            "5  Remote control enabled\n"
            "6  Ready"
        )
        self.wizard_steps_label.setObjectName("big")
        self.wizard_steps_label.setWordWrap(True)
        overview_layout.addWidget(self.wizard_steps_label)
        layout.addWidget(overview)

        health_box, health_layout, _ = self.card(
            "System Check",
            "Check the complete PhoneHub path inside this app: PC tools, Tailscale, USB, phone, remote ADB and Android readiness."
        )

        health_actions = QHBoxLayout()
        health_actions.setSpacing(8)

        self.health_check_button = QPushButton("Run Check All")
        self.health_check_button.setObjectName("primary")
        self.health_check_button.setMinimumHeight(44)
        self.health_check_button.clicked.connect(self.run_health_check)

        refresh_setup = QPushButton("Retry Current Setup Step")
        refresh_setup.setMinimumHeight(44)
        refresh_setup.clicked.connect(self.wizard_action)

        health_actions.addWidget(self.health_check_button)
        health_actions.addWidget(refresh_setup)
        health_layout.addLayout(health_actions)

        self.health_summary = QLabel(
            "1. Platform-Tools      — Not checked\n"
            "2. scrcpy              — Not checked\n"
            "3. Python + PySide6     — Not checked\n"
            "4. PhoneHub + Git       — Not checked\n"
            "5. Tailscale PC         — Not checked\n"
            "6. USB + debugging      — Not checked\n"
            "7. Tailscale phone      — Not checked\n"
            "8. Remote ADB           — Not checked\n"
            "9. Android readiness    — Not checked"
        )
        self.health_summary.setObjectName("big")
        self.health_summary.setWordWrap(True)
        self.health_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        health_layout.addWidget(self.health_summary)

        self.health_overall = QLabel("Status: Not checked")
        self.health_overall.setObjectName("sideStatus")
        self.health_overall.setWordWrap(True)
        health_layout.addWidget(self.health_overall)

        layout.addWidget(health_box)

        layout.addStretch()
        QTimer.singleShot(200, self._render_wizard_step)
        return page

    def _set_wizard_step(self, step, status=""):
        step = max(1, min(6, int(step)))
        changed = step != self.wizard_step
        self.wizard_step = step
        if hasattr(self, "wizard_status") and status:
            self.wizard_status.setText(status)
        if changed or hasattr(self, "wizard_title"):
            self._render_wizard_step()

    def _render_wizard_step(self):
        if not hasattr(self, "wizard_title"):
            return

        step = self.wizard_step
        self.wizard_progress.setText(f"Step {step} of 6")

        if step == 1:
            self.wizard_title.setText("Connect phone by USB")
            self.wizard_instruction.setText(
                "Connect the phone with the USB cable. Keep USB debugging ON. "
                "If Android asks 'Allow USB debugging?', tap Always allow from this computer, then OK."
            )
            self.wizard_action_button.setText("Check Again")
        elif step == 2:
            self.wizard_title.setText("Unlock phone once")
            self.wizard_instruction.setText(
                "PhoneHub will wake the phone. Unlock it normally using fingerprint, face, PIN, pattern, or password. "
                "Then PhoneHub checks that it is unlocked."
            )
            self.wizard_action_button.setText("I Unlocked It - Check")
        elif step == 3:
            self.wizard_title.setText("Install Tailscale")
            self.wizard_instruction.setText(
                "PhoneHub checks whether Tailscale is installed. If it is missing, the local Tailscale APK in "
                "C:\\PhoneHub\\apps is installed automatically."
            )
            self.wizard_action_button.setText("Install / Check Tailscale")
        elif step == 4:
            self.wizard_title.setText("Connect Tailscale")
            self.wizard_instruction.setText(
                "Open Tailscale on the phone, sign in if needed, and turn it ON. "
                "PhoneHub will automatically detect the phone's 100.x.x.x Tailscale IP."
            )
            self.wizard_action_button.setText("Open Tailscale")
        elif step == 5:
            self.wizard_title.setText("Enable remote control")
            self.wizard_instruction.setText(
                "Keep USB connected for this one step. PhoneHub will enable ADB on port 5555 and test the Tailscale connection."
            )
            self.wizard_action_button.setText("Enable Remote + Test")
        else:
            self.wizard_title.setText("Setup complete")
            self.wizard_instruction.setText(
                "PhoneHub can reach the phone through Tailscale. You can now disconnect the USB cable and use Open Screen."
            )
            self.wizard_action_button.setText("Finish Setup")

        self.wizard_action_button.setEnabled(not self._wizard_busy)

    def _wizard_update_from_state(self, state):
        if not hasattr(self, "wizard_status"):
            return

        usb = state.get("usb", [])
        unauthorized = state.get("unauthorized", [])
        installed = state.get("installed", False)
        detected_ip = state.get("detected_ip", "")
        remote = state.get("remote", [])

        if unauthorized:
            self._set_wizard_step(
                1,
                "USB found, but debugging is not approved. Approve the popup on the phone, then press Check Again."
            )
            return

        if not usb:
            if self.wizard_step < 6:
                self._set_wizard_step(
                    1,
                    "Phone not detected by USB. Connect the cable, unlock the phone if needed, then press Check Again."
                )
            return

        self.wizard_serial = usb[0]

        if self.wizard_step == 1:
            self._set_wizard_step(2, f"USB connected: {self.wizard_serial}. Next: unlock the phone once.")

        if installed and self.wizard_step == 3:
            self._set_wizard_step(4, "Tailscale is installed. Next: connect Tailscale on the phone.")

        if detected_ip:
            self.wizard_detected_ip = detected_ip
            save_phone_ip(detected_ip, 5555)
            if self.wizard_step <= 4:
                self._set_wizard_step(5, f"Tailscale connected. IP detected automatically: {detected_ip}")

        if detected_ip:
            target = f"{detected_ip}:5555"
            self.wizard_remote_connected = target in remote
            if self.wizard_remote_connected and self.wizard_step <= 5:
                self._set_wizard_step(6, f"Remote control connected: {target}")

    def wizard_action(self):
        if self._wizard_busy:
            return

        if self.wizard_step == 1:
            self.wizard_status.setText("Checking USB connection...")
            self.auto_refresh_connection_state()
            return

        if self.wizard_step == 2:
            if not self.wizard_serial:
                self._set_wizard_step(1, "USB connection was lost. Connect the phone again.")
                return
            self._wizard_busy = True
            self._render_wizard_step()
            self.wizard_status.setText("Checking whether the phone is unlocked...")

            def worker():
                unlocked = self._is_device_unlocked(self.wizard_serial)
                self.auto_bridge.wizard.emit({"type": "unlock", "ok": unlocked})

            import threading
            threading.Thread(target=worker, daemon=True).start()
            return

        if self.wizard_step == 3:
            serial, error = self._usb_serial()
            if error:
                self._set_wizard_step(1, error)
                return
            if self._tailscale_installed(serial):
                self._set_wizard_step(4, "Tailscale is already installed.")
            else:
                self.install_tailscale_clicked()
                self.wizard_status.setText("Installing Tailscale. Wait for PhoneHub to detect it, then it will move to the next step.")
            return

        if self.wizard_step == 4:
            serial, error = self._usb_serial()
            if error:
                self._set_wizard_step(1, error)
                return
            if not self._tailscale_installed(serial):
                self._set_wizard_step(3, "Tailscale is not installed yet.")
                return
            run_background([
                "adb", "-s", serial, "shell", "monkey",
                "-p", TAILSCALE_PACKAGE,
                "-c", "android.intent.category.LAUNCHER",
                "1",
            ])
            self.wizard_status.setText(
                "Tailscale opened on the phone. Connect it there. PhoneHub will detect the IP automatically."
            )
            return

        if self.wizard_step == 5:
            if not self.wizard_serial:
                self._set_wizard_step(1, "USB connection was lost. Connect the phone again.")
                return
            if not self.wizard_detected_ip:
                self._set_wizard_step(4, "Tailscale IP is not detected yet. Connect Tailscale first.")
                return

            self._wizard_busy = True
            self._render_wizard_step()
            self.wizard_status.setText("Enabling remote ADB and testing connection...")

            serial = self.wizard_serial
            ip = self.wizard_detected_ip

            def worker():
                result = run_quiet(["adb", "-s", serial, "tcpip", "5555"], timeout=12)
                if "restarting in TCP mode" not in result.lower() and "5555" not in result:
                    self.auto_bridge.wizard.emit({
                        "type": "remote",
                        "ok": False,
                        "message": result or "Could not enable remote ADB."
                    })
                    return

                import time
                time.sleep(1.2)
                target = f"{ip}:5555"
                connect_text = run_quiet(["adb", "connect", target], timeout=10)
                devices = run_quiet(["adb", "devices"], timeout=5)
                ok = f"{target}\tdevice" in devices

                self.auto_bridge.wizard.emit({
                    "type": "remote",
                    "ok": ok,
                    "target": target,
                    "message": connect_text,
                })

            import threading
            threading.Thread(target=worker, daemon=True).start()
            return

        if self.wizard_step == 6:
            if self.wizard_detected_ip:
                save_phone_ip(self.wizard_detected_ip, 5555)
            self.wizard_status.setText("Setup saved. USB can now be disconnected.")
            self.set_footer("PhoneHub setup complete.")
            self.show_page(0)

    def _apply_wizard_result(self, result):
        self._wizard_busy = False
        kind = result.get("type")

        if kind == "unlock":
            if result.get("ok"):
                self._set_wizard_step(3, "Phone unlocked successfully. Checking Tailscale next.")
                self.auto_refresh_connection_state()
            else:
                self._set_wizard_step(
                    2,
                    "Phone still appears locked. Unlock it on the phone, then press 'I Unlocked It - Check' again."
                )
        elif kind == "remote":
            if result.get("ok"):
                target = result.get("target", "")
                self.wizard_remote_connected = True
                self._set_wizard_step(6, f"Remote control connected successfully: {target}")
                self.auto_refresh_connection_state()
            else:
                message = result.get("message", "Remote connection failed.")
                self._set_wizard_step(
                    5,
                    f"Remote control did not connect. Keep USB connected and press Enable Remote + Test again. Details: {message}"
                )

        self._render_wizard_step()

    def _health_state_line(self, index, name, state, detail=""):
        suffix = f" — {detail}" if detail else ""
        return f"{index}. {name:<19} — {state}{suffix}"

    def run_health_check(self):
        if self._health_busy:
            return

        self._health_busy = True
        if hasattr(self, "health_check_button"):
            self.health_check_button.setEnabled(False)
            self.health_check_button.setText("Checking...")
        if hasattr(self, "health_overall"):
            self.health_overall.setText("Status: Running all checks...")
        self.set_footer("Running PhoneHub system check in background...")

        def worker():
            results = []

            def add(name, state, detail=""):
                results.append({"name": name, "state": state, "detail": detail})

            # 1. Platform-Tools
            adb = shutil.which("adb")
            fastboot = shutil.which("fastboot")
            if adb and fastboot:
                version = run_quiet([adb, "version"], timeout=4).splitlines()
                add("Platform-Tools", "PASS", version[0] if version else "ADB + Fastboot found")
            elif adb:
                add("Platform-Tools", "WARN", "ADB found; Fastboot missing")
            else:
                add("Platform-Tools", "FAIL", "ADB not found")

            # 2. scrcpy
            scrcpy = scrcpy_path()
            if scrcpy:
                ver = run_quiet([scrcpy, "--version"], timeout=4).splitlines()
                add("scrcpy", "PASS", ver[0] if ver else "Ready")
            else:
                add("scrcpy", "FAIL", "scrcpy not found")

            # 3. Python + PySide6
            try:
                import PySide6
                add("Python + PySide6", "PASS", f"Python {sys.version_info.major}.{sys.version_info.minor}; PySide6 {PySide6.__version__}")
            except Exception:
                add("Python + PySide6", "FAIL", "PySide6 import failed")

            # 4. PhoneHub files + Git
            root = Path(r"C:\PhoneHub")
            launcher = root / "PhoneHub.bat"
            git_dir = root / ".git"
            if not launcher.exists():
                add("PhoneHub + Git", "FAIL", "PhoneHub.bat missing")
            elif not git_dir.exists():
                add("PhoneHub + Git", "WARN", "PhoneHub found; Git repo missing")
            else:
                git = shutil.which("git")
                if not git:
                    add("PhoneHub + Git", "WARN", "Git executable missing")
                else:
                    status = run_quiet([git, "-C", str(root), "status", "--porcelain"], timeout=5)
                    if status:
                        add("PhoneHub + Git", "WARN", "Local changes detected")
                    else:
                        branch = run_quiet([git, "-C", str(root), "branch", "--show-current"], timeout=4) or "main"
                        add("PhoneHub + Git", "PASS", f"Clean working tree; branch {branch}")

            # 5. Tailscale PC
            tailscale = shutil.which("tailscale")
            if not tailscale:
                for candidate in (
                    Path(r"C:\Program Files\Tailscale\tailscale.exe"),
                    Path(r"C:\Program Files (x86)\Tailscale\tailscale.exe"),
                ):
                    if candidate.exists():
                        tailscale = str(candidate)
                        break
            if tailscale:
                pc_ip = run_quiet([tailscale, "ip", "-4"], timeout=5).splitlines()
                if pc_ip:
                    add("Tailscale PC", "PASS", pc_ip[0])
                else:
                    add("Tailscale PC", "WARN", "Installed but not connected")
            else:
                add("Tailscale PC", "FAIL", "Not installed")

            # 6-8. Device path
            usb, remote, unauthorized, _ = parse_adb_devices()
            serial = usb[0] if usb else ""

            if unauthorized:
                add("USB + debugging", "WARN", "USB debugging authorization required")
            elif serial:
                model = run_quiet(["adb", "-s", serial, "shell", "getprop", "ro.product.model"], timeout=4) or "Android phone"
                add("USB + debugging", "PASS", f"Connected: {model}")
            else:
                add("USB + debugging", "WARN", "USB not connected")

            detected_ip = ""
            installed = False
            if serial:
                installed = self._tailscale_installed(serial)
                if installed:
                    detected_ip = self._detect_tailscale_ip(serial)

            saved_ip, port = get_saved_ip()
            phone_ip = detected_ip or saved_ip

            if installed and detected_ip:
                add("Tailscale phone", "PASS", detected_ip)
            elif installed:
                add("Tailscale phone", "WARN", "Installed; no active 100.x.x.x IP detected")
            elif serial:
                add("Tailscale phone", "FAIL", "App not detected")
            elif saved_ip:
                add("Tailscale phone", "WARN", f"USB absent; saved IP {saved_ip}")
            else:
                add("Tailscale phone", "FAIL", "Cannot verify")

            target = f"{phone_ip}:{port}" if phone_ip else ""
            remote_ok = bool(target and target in remote)
            if remote_ok:
                add("Remote ADB", "PASS", target)
            elif target:
                add("Remote ADB", "WARN", f"Not connected: {target}")
            else:
                add("Remote ADB", "FAIL", "No phone Tailscale IP")

            # 9. Android readiness. Prefer remote target, then USB.
            check_target = target if remote_ok else serial
            if check_target:
                boot = run_quiet(["adb", "-s", check_target, "shell", "getprop", "sys.boot_completed"], timeout=5).strip()
                shell_echo = run_quiet(["adb", "-s", check_target, "shell", "echo", "PHONEHUB_READY"], timeout=5).strip()
                if boot == "1" and shell_echo == "PHONEHUB_READY":
                    add("Android readiness", "PASS", "Boot complete; ADB shell responsive")
                elif shell_echo == "PHONEHUB_READY":
                    add("Android readiness", "WARN", f"ADB responsive; boot_completed={boot or 'unknown'}")
                else:
                    add("Android readiness", "FAIL", "ADB shell not responsive")
            else:
                add("Android readiness", "FAIL", "No reachable device")

            self.auto_bridge.health.emit({"results": results})

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_health_results(self, payload):
        self._health_busy = False
        results = payload.get("results", [])

        if hasattr(self, "health_check_button"):
            self.health_check_button.setEnabled(True)
            self.health_check_button.setText("Run Check All")

        lines = []
        fail_count = 0
        warn_count = 0

        for index, item in enumerate(results, start=1):
            state = item.get("state", "UNKNOWN")
            name = item.get("name", "Check")
            detail = item.get("detail", "")
            if state == "FAIL":
                fail_count += 1
            elif state == "WARN":
                warn_count += 1
            lines.append(self._health_state_line(index, name, state, detail))

        if hasattr(self, "health_summary"):
            self.health_summary.setText("\n".join(lines))

        if fail_count:
            overall = f"Status: Needs attention — {fail_count} failed, {warn_count} warning(s)"
        elif warn_count:
            overall = f"Status: Ready with {warn_count} warning(s)"
        else:
            overall = "Status: PHONEHUB READY — all checks passed"

        if hasattr(self, "health_overall"):
            self.health_overall.setText(overall)
        self.set_footer(overall)

    def _detect_tailscale_ip(self, serial):
        """Return the phone's active Tailscale IPv4 address, if visible."""
        # Fast path first. Avoid running multiple expensive dumpsys commands
        # unless the normal interface list does not expose the address.
        outputs = [
            run_quiet(["adb", "-s", serial, "shell", "ip", "-4", "addr"], timeout=3),
        ]

        def find_ip(output):
            for match in re.findall(r"\b100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b", output or ""):
                second, third, fourth = map(int, match)
                if 64 <= second <= 127 and 0 <= third <= 255 and 0 <= fourth <= 255:
                    return f"100.{second}.{third}.{fourth}"
            return ""

        for output in outputs:
            found = find_ip(output)
            if found:
                return found

        # One fallback only.
        fallback = run_quiet(
            ["adb", "-s", serial, "shell", "dumpsys", "connectivity"],
            timeout=4,
        )
        return find_ip(fallback)

    def setup_smart_check(self):
        usb, remote, unauthorized, _ = parse_adb_devices()
        lines = []

        if unauthorized:
            lines.append("USB Debugging: Not approved")
            lines.append("Action: Approve 'Always allow from this computer' on the phone.")
            self.setup_log.setText("\n".join(lines))
            self.set_footer("USB authorization required.")
            return

        serial = usb[0] if usb else ""
        if serial:
            model = run_quiet(
                ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
                timeout=5,
            ) or "Android Phone"
            android = run_quiet(
                ["adb", "-s", serial, "shell", "getprop", "ro.build.version.release"],
                timeout=5,
            ) or "-"

            lines.append("USB Debugging: Connected")
            lines.append(f"Device: {model}")
            lines.append(f"Android: {android}")
            lines.append(f"USB Serial: {serial}")

            installed = self._tailscale_installed(serial)
            detected_ip = self._detect_tailscale_ip(serial) if installed else ""

            if installed and detected_ip:
                lines.append("Tailscale: Connected")
                lines.append(f"Tailscale IP: {detected_ip}")

                # Keep PhoneHub synchronized with the IP reported by the phone.
                save_phone_ip(detected_ip, 5555)
                if hasattr(self, "setup_ip_input"):
                    self.setup_ip_input.setText(detected_ip)
                if hasattr(self, "dashboard_ip_input"):
                    self.dashboard_ip_input.setText(detected_ip)

                target = f"{detected_ip}:5555"
                if target not in remote:
                    run_quiet(["adb", "connect", target], timeout=5)
                    _, remote, _, _ = parse_adb_devices()

                if target in remote:
                    lines.append(f"Remote Control: Connected {target}")
                else:
                    lines.append("Remote Control: Not connected")
                    lines.append("Action: Click Enable Remote once while USB is connected.")
            elif installed:
                lines.append("Tailscale: Installed, waiting for VPN connection")
                saved_ip, _ = get_saved_ip()
                if saved_ip:
                    lines.append(f"Saved Tailscale IP: {saved_ip}")
                lines.append("Action: Open Tailscale on the phone and connect it.")
            else:
                lines.append("Tailscale: Not installed")
                lines.append("Action: Click Install Tailscale.")
        else:
            lines.append("USB Debugging: Not connected")
            saved_ip, port = get_saved_ip()
            if saved_ip:
                target = f"{saved_ip}:{port}"
                if target in remote:
                    lines.append(f"Tailscale IP: {saved_ip}")
                    lines.append(f"Remote Control: Connected {target}")
                else:
                    lines.append(f"Saved Tailscale IP: {saved_ip}")
                    lines.append("Remote Control: Not connected")
            else:
                lines.append("Tailscale IP: Not detected")

        self.setup_log.setText("\n".join(lines))
        self.set_footer("Smart check complete.")

    def auto_refresh_connection_state(self):
        # Never run adb polling on the Qt/UI thread.
        if self._auto_detect_busy:
            return

        self._auto_detect_busy = True

        def worker():
            state = {
                "usb": [],
                "remote": [],
                "unauthorized": [],
                "installed": False,
                "detected_ip": "",
            }
            try:
                usb, remote, unauthorized, _ = parse_adb_devices()
                state["usb"] = usb
                state["remote"] = remote
                state["unauthorized"] = unauthorized

                if usb and not unauthorized:
                    serial = usb[0]
                    state["installed"] = self._tailscale_installed(serial)
                    if state["installed"]:
                        state["detected_ip"] = self._detect_tailscale_ip(serial)
            except Exception:
                pass
            finally:
                self.auto_bridge.state.emit(state)

        import threading
        threading.Thread(target=worker, daemon=True).start()

    def _apply_auto_detect_state(self, state):
        self._auto_detect_busy = False

        usb = state.get("usb", [])
        remote = state.get("remote", [])
        unauthorized = state.get("unauthorized", [])
        installed = state.get("installed", False)
        detected_ip = state.get("detected_ip", "")

        signature = (
            tuple(sorted(usb)),
            tuple(sorted(remote)),
            tuple(sorted(unauthorized)),
            installed,
            detected_ip,
        )

        self._wizard_update_from_state(state)

        changed = signature != self._last_connection_signature
        if changed:
            self._last_connection_signature = signature

            # Update the visible status without launching another full adb scan.
            lines = []
            if unauthorized:
                lines = [
                    "USB Debugging: Not approved",
                    "Action: Approve 'Always allow from this computer' on the phone.",
                ]
            elif usb:
                serial = usb[0]
                lines.append("USB Debugging: Connected")
                lines.append(f"USB Serial: {serial}")

                if installed and detected_ip:
                    lines.append("Tailscale: Connected")
                    lines.append(f"Tailscale IP: {detected_ip}")
                    save_phone_ip(detected_ip, 5555)
                    if hasattr(self, "setup_ip_input"):
                        self.setup_ip_input.setText(detected_ip)
                    if hasattr(self, "dashboard_ip_input"):
                        self.dashboard_ip_input.setText(detected_ip)

                    target = f"{detected_ip}:5555"
                    lines.append(
                        f"Remote Control: {'Connected ' + target if target in remote else 'Not connected'}"
                    )
                    if target not in remote:
                        lines.append("Action: Click Enable Remote once while USB is connected.")
                elif installed:
                    lines.append("Tailscale: Installed, waiting for VPN connection")
                else:
                    lines.append("Tailscale: Not installed")
            else:
                lines.append("USB Debugging: Not connected")
                saved_ip, port = get_saved_ip()
                if saved_ip:
                    target = f"{saved_ip}:{port}"
                    lines.append(f"Saved Tailscale IP: {saved_ip}")
                    lines.append(
                        f"Remote Control: {'Connected ' + target if target in remote else 'Not connected'}"
                    )

            if hasattr(self, "setup_log"):
                self.setup_log.setText("\n".join(lines))

        if unauthorized:
            self.side_status.setText("USB authorization needed")
        elif remote:
            self.side_status.setText("Phone online")
        elif usb and detected_ip:
            self.side_status.setText("Tailscale connected")
        elif usb:
            self.side_status.setText("USB connected")
        else:
            self.side_status.setText("Phone offline")

    def _is_device_unlocked(self, serial):
        # Android exposes the current lockscreen/keyguard state through dumpsys.
        # We only use this to detect whether the user has completed normal
        # authentication on the phone; PhoneHub never bypasses the lockscreen.
        window = run_quiet(
            ["adb", "-s", serial, "shell", "dumpsys", "window", "policy"],
            timeout=3,
        ).lower()
        power = run_quiet(
            ["adb", "-s", serial, "shell", "dumpsys", "power"],
            timeout=3,
        ).lower()

        locked_markers = (
            "mshowinglockscreen=true",
            "iskeyguardshowing=true",
            "keyguard showing=true",
            "mkeyguardshowing=true",
        )
        if any(marker in window for marker in locked_markers):
            return False

        # If Android's policy output is inconclusive, treat an interactive
        # device without a showing keyguard as unlocked.
        interactive = "minteractive=true" in power or "display power: state=on" in power
        return interactive

    def _begin_unlock_flow(self, serial):
        self._auto_unlock_waiting = True
        self._auto_unlock_serial = serial

        # Wake only. Do not send PIN, pattern, swipe credentials, or any
        # lockscreen-bypass command.
        run_quiet(
            ["adb", "-s", serial, "shell", "input", "keyevent", "224"],
            timeout=3,
        )

        self.side_status.setText("Unlock phone once")
        self.set_footer("Phone detected. Unlock the phone once; PhoneHub will continue automatically.")

        QMessageBox.information(
            self,
            "Unlock phone once",
            "PhoneHub detected the USB-connected phone and woke the screen.\n\n"
            "Please unlock the phone normally using fingerprint, face, PIN, pattern, or password.\n\n"
            "PhoneHub will continue automatically after Android reports that the phone is unlocked.",
        )

        self.unlock_timer.start()
        QTimer.singleShot(1000, self._check_unlock_progress)

    def _check_unlock_progress(self):
        if not self._auto_unlock_waiting or not self._auto_unlock_serial:
            self.unlock_timer.stop()
            return

        # Stop waiting if this USB device disappeared.
        usb, _, _, _ = parse_adb_devices()
        if self._auto_unlock_serial not in usb:
            self._auto_unlock_waiting = False
            self._auto_unlock_serial = ""
            self.unlock_timer.stop()
            return

        if not self._is_device_unlocked(self._auto_unlock_serial):
            self.side_status.setText("Waiting for unlock")
            return

        self.unlock_timer.stop()
        self._auto_unlock_waiting = False
        serial = self._auto_unlock_serial
        self._auto_unlock_serial = ""

        self.side_status.setText("USB connected")
        self.set_footer("Phone unlocked. Continuing setup automatically...")

        # Refresh the setup state immediately. If Tailscale is installed, open
        # it for the next setup step; otherwise leave the Install Tailscale
        # action visible for the user.
        if hasattr(self, "setup_log"):
            self.setup_smart_check()

        if self._tailscale_installed(serial):
            run_background([
                "adb", "-s", serial, "shell", "monkey",
                "-p", TAILSCALE_PACKAGE,
                "-c", "android.intent.category.LAUNCHER",
                "1",
            ])
            self.set_footer("Phone unlocked. Tailscale opened; finish sign-in/VPN approval on the phone.")
        else:
            self.set_footer("Phone unlocked. Tailscale is missing; click Install Tailscale.")

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

        self._set_tailscale_status("Preparing Tailscale installation...")

        def worker():
            try:
                # Prefer a bundled/local APK first. Older PhoneHub setup scripts
                # already use C:\\PhoneHub\\apps\\*.apk, so this also works
                # when the PC has an APK saved locally but it is not in GitHub.
                apk_path = None
                if LOCAL_APK_DIR.exists():
                    # Prefer a real Tailscale APK by filename. Do not blindly
                    # install another APK such as PhoneHub's small app-debug.apk.
                    preferred = sorted(
                        LOCAL_APK_DIR.glob("tailscale-android-universal-*.apk"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )

                    # Fallback: any APK with "tailscale" in the name and a
                    # realistic package size (>10 MB).
                    fallback = sorted(
                        [
                            p for p in LOCAL_APK_DIR.glob("*.apk")
                            if "tailscale" in p.name.lower()
                            and p.stat().st_size > 10 * 1024 * 1024
                        ],
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )

                    candidates = preferred or fallback
                    if candidates:
                        apk_path = candidates[0]
                        self.bridge.message.emit(
                            f"Using local Tailscale APK: {apk_path.name}"
                        )

                if apk_path is None:
                    self.bridge.message.emit(
                        "No local APK found. Downloading official Tailscale APK..."
                    )
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
                    ["adb", "-s", serial, "install", "-r", "-g", str(apk_path)],
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

    def setup_open_tailscale(self):
        """Override the original Setup button.

        If Tailscale is installed, open it. If it is missing, offer to install
        it immediately instead of sending a silent monkey command that appears
        to do nothing.
        """
        serial, error = self._usb_serial()
        if error:
            QMessageBox.warning(self, "PhoneHub", error)
            return

        if self._tailscale_installed(serial):
            self.open_tailscale_clicked()
            return

        answer = QMessageBox.question(
            self,
            "Tailscale not installed",
            "PhoneHub cannot open Tailscale because it is not installed on this phone.\n\nInstall the official Tailscale APK now?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.install_tailscale_clicked()
        else:
            self._set_tailscale_status("Tailscale is not installed on the phone.")

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
