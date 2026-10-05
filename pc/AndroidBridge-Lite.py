import tkinter as tk
from tkinter import messagebox
import subprocess
import re
import time
import os
import threading
import shutil

HIDE = 0x08000000

PHONE_NAME = "jennys-s25-ultra"
TAILSCALE_FALLBACK_IP = "100.127.244.20"
ADB_PORT = "5555"

TAILSCALE_EXE = r"C:\Program Files\Tailscale\tailscale.exe"

current_process = None
screen_process = None
camera_process = None
audio_process = None
current_mode = "STOPPED"
active_device = None
checking = False
media_starting = False
media_start_lock = threading.Lock()


# ============================================================
# PROCESS HELPERS
# ============================================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ADB_PROXY_SOURCE = os.path.join(
    SCRIPT_DIR,
    "AndroidBridge-AdbProxy.cs"
)
ADB_PROXY_EXE = os.path.join(
    SCRIPT_DIR,
    "AndroidBridge-AdbProxy.exe"
)


def find_real_adb():
    path = shutil.which("adb")

    if path:
        return os.path.abspath(path)

    return None


def find_csharp_compiler():
    candidates = [
        shutil.which("csc"),
        r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
        r"C:\Windows\Microsoft.NET\Framework\v4.0.30319\csc.exe",
    ]

    for path in candidates:
        if path and os.path.exists(path):
            return path

    return None


def ensure_adb_proxy():
    """
    Build the tiny Windows ADB proxy when required.

    scrcpy officially supports selecting its adb executable through the ADB
    environment variable. AndroidBridge uses that hook only for remote media
    sessions so the normal system adb connection remains untouched.
    """
    real_adb = find_real_adb()

    if not real_adb:
        raise RuntimeError("adb.exe could not be found.")

    if not os.path.exists(ADB_PROXY_SOURCE):
        raise RuntimeError(
            "AndroidBridge-AdbProxy.cs is missing."
        )

    needs_build = (
        not os.path.exists(ADB_PROXY_EXE) or
        os.path.getmtime(ADB_PROXY_EXE) <
        os.path.getmtime(ADB_PROXY_SOURCE)
    )

    if needs_build:
        compiler = find_csharp_compiler()

        if not compiler:
            raise RuntimeError(
                "Windows C# compiler was not found. "
                "AndroidBridge cannot build its remote ADB transport helper."
            )

        result = subprocess.run(
            [
                compiler,
                "/nologo",
                "/target:exe",
                "/optimize+",
                "/out:" + ADB_PROXY_EXE,
                ADB_PROXY_SOURCE,
            ],
            capture_output=True,
            text=True,
            creationflags=HIDE,
            timeout=30
        )

        if result.returncode != 0:
            detail = (
                result.stdout +
                "\n" +
                result.stderr
            ).strip()

            raise RuntimeError(
                "ADB proxy build failed.\n\n" + detail
            )

    return ADB_PROXY_EXE, real_adb


def scrcpy_environment(device):
    env = os.environ.copy()

    if is_tailscale(device):
        proxy, real_adb = ensure_adb_proxy()

        env["ADB"] = proxy
        env["ANDROIDBRIDGE_REAL_ADB"] = real_adb

    return env


def run_hidden(args, timeout=6):
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            creationflags=HIDE,
            timeout=timeout
        )
    except:
        return None


def adb_quick_state(device):
    """Fast ADB connection check without triggering a reconnect."""
    if not device:
        return False

    try:
        result = subprocess.run(
            ["adb", "-s", device, "get-state"],
            capture_output=True,
            text=True,
            timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        return result.returncode == 0 and result.stdout.strip() == "device"

    except Exception:
        return False

def adb_list():
    result = run_hidden(["adb", "devices"], 4)

    found = []

    if not result:
        return found

    for line in result.stdout.splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("List of devices"):
            continue

        parts = line.split()

        if len(parts) >= 2:
            found.append((parts[0], parts[1]))

    return found


def usable_devices():
    return [
        serial
        for serial, state in adb_list()
        if state == "device"
    ]


# ============================================================
# DEVICE CLASSIFICATION
# ============================================================

def is_usb(serial):
    return ":" not in serial


def is_tailscale(serial):
    return serial.startswith("100.")


def is_local(serial):

    if is_usb(serial):
        return False

    if is_tailscale(serial):
        return False

    return (
        serial.startswith("192.168.") or
        serial.startswith("10.") or
        serial.startswith("172.")
    )


# ============================================================
# TAILSCALE DISCOVERY
# ============================================================

def tailscale_ip():

    if os.path.exists(TAILSCALE_EXE):

        result = run_hidden(
            [TAILSCALE_EXE, "status"],
            6
        )

        if result:

            for line in result.stdout.splitlines():

                fields = line.split()

                if len(fields) < 2:
                    continue

                ip = fields[0]
                name = fields[1]

                if name.lower() == PHONE_NAME.lower():

                    if re.fullmatch(
                        r"100\.\d+\.\d+\.\d+",
                        ip
                    ):
                        return ip

    return TAILSCALE_FALLBACK_IP


# ============================================================
# SMART ROUTING
#
# PRIORITY:
# 1 USB
# 2 LOCAL WIFI
# 3 TAILSCALE
# ============================================================

def choose_existing_device():
    """
    Fastest available route wins:

    1. USB
    2. Existing local Wi-Fi ADB
    3. Existing Tailscale ADB
    """

    devices = usable_devices()

    # USB first
    for serial in devices:
        if is_usb(serial):
            return serial

    # Direct LAN second
    for serial in devices:
        if is_local(serial):
            return serial

    # Tailscale last
    for serial in devices:
        if is_tailscale(serial):
            return serial

    return None


def connect_tailscale():
    """
    Connect to the known phone through Tailscale.
    Avoid unnecessary adb connect calls when already connected.
    """

    target_ip = tailscale_ip()

    if not target_ip:
        return None

    target = f"{target_ip}:{ADB_PORT}"

    # Already connected - return immediately.
    if adb_quick_state(target):
        return target

    try:
        subprocess.run(
            ["adb", "connect", target],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception:
        return None

    # Quick verification.
    if adb_quick_state(target):
        return target

    return None


def get_device(allow_remote=True):

    global active_device

    # Reuse the known working transport first. This avoids an unnecessary
    # "adb devices" transaction immediately before every media startup.
    if active_device and adb_quick_state(active_device):
        return active_device

    # First use an existing fast connection.
    device = choose_existing_device()

    if device:

        active_device = device
        return device

    # Nothing available locally.
    # Try secure Tailscale remote connection.
    if allow_remote:

        device = connect_tailscale()

        if device:

            active_device = device
            return device

    active_device = None
    return None


def tailscale_phone_state():

    if not os.path.exists(TAILSCALE_EXE):
        return "TAILSCALE NOT INSTALLED"

    result = run_hidden(
        [TAILSCALE_EXE, "status"],
        6
    )

    if not result:
        return "TAILSCALE OFFLINE"

    for line in result.stdout.splitlines():

        fields = line.split()

        if len(fields) < 2:
            continue

        name = fields[1]

        if name.lower() == PHONE_NAME.lower():

            lower = line.lower()

            if "offline" in lower:
                return "TAILSCALE OFFLINE"

            if (
                "active" in lower or
                "direct" in lower or
                "relay" in lower
            ):
                return "TAILSCALE ONLINE"

            return "TAILSCALE ONLINE"

    return "PHONE NOT FOUND IN TAILSCALE"

# ============================================================
# CONNECTION DISPLAY
# ============================================================

def connection_type(device):

    if not device:
        return "DISCONNECTED"

    if is_usb(device):
        return "USB - FAST"

    if is_local(device):
        return "LOCAL WI-FI - FAST"

    if is_tailscale(device):
        return "TAILSCALE - REMOTE"

    return "ADB"


# ============================================================
# SCRCPY CONTROL
# ============================================================

def stop_scrcpy():

    global current_process
    global screen_process
    global camera_process
    global current_mode

    # STOP controls video only. AUDIO OFF controls the independent
    # microphone session so stopping screen/camera does not cut audio.
    for process in (screen_process, camera_process):

        if process is None:
            continue

        try:
            if process.poll() is None:
                process.terminate()

                try:
                    process.wait(timeout=2)
                except:
                    process.kill()

        except:
            pass

    screen_process = None
    camera_process = None
    current_process = None
    current_mode = "STOPPED"

    try:
        mode_label.config(
            text="MODE: STOPPED"
        )
    except:
        pass

def scrcpy_screen_args(device):

    # USB / LOCAL WIFI
    # High quality and responsive.
    if is_usb(device) or is_local(device):
        return [
            "--max-fps=60",
            "--video-codec=h264",
            "--no-audio",
            "--window-title=AndroidBridge SCREEN"
        ]

    # TAILSCALE REMOTE
    # Low latency profile.
    return [
        "--max-size=1024",
        "--max-fps=30",
        "--video-bit-rate=2M",
        "--video-codec=h264",
        "--no-audio",
        "--no-cleanup",
        "--window-title=AndroidBridge SCREEN"
    ]


def scrcpy_camera_args(device, facing):

    # Samsung SM-S938B camera IDs reported by scrcpy:
    # 0 = primary back camera
    # 1 = primary front camera
    camera_id = "0" if facing == "back" else "1"

    # USB / LOCAL WIFI
    if is_usb(device) or is_local(device):
        size = "1920x1080"
        fps = "30"

    # TAILSCALE REMOTE
    else:
        size = "1280x720"
        # Phone reports supported camera FPS values: 15, 24, 30, 60.
        # 12 FPS was not supported, so use the lowest supported remote value.
        fps = "15"

    if facing == "back":
        title = "AndroidBridge BACK CAMERA"
    else:
        title = "AndroidBridge FRONT CAMERA"

    return [
        "--video-source=camera",
        f"--camera-id={camera_id}",
        f"--camera-size={size}",
        f"--camera-fps={fps}",
        "--video-bit-rate=700K",
        "--video-buffer=0",
        "--video-codec=h264",
        "--no-audio",
        "--no-cleanup",
        f"--window-title={title}"
    ]


def ensure_media_connection(device):
    """Verify the existing ADB transport and repair only this device if needed."""
    if adb_quick_state(device):
        return True

    if is_tailscale(device):
        try:
            subprocess.run(
                ["adb", "connect", device],
                capture_output=True,
                text=True,
                timeout=6,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception:
            return False

        time.sleep(0.4)
        return adb_quick_state(device)

    return adb_quick_state(device)


def start_scrcpy_resilient(cmd, log_name, on_started, on_failed):
    """
    Serialize scrcpy startup over remote ADB.

    The remote link can take tens of seconds to push scrcpy-server.jar.
    While that happens, AndroidBridge pauses its periodic ADB status checks
    so they do not compete with the transfer. A session is marked started
    only after the scrcpy server actually reports that the phone is ready.
    """

    global media_starting

    if media_starting:
        try:
            mode_label.config(
                text="MODE: WAIT - MEDIA STARTING"
            )
        except:
            pass
        return

    media_starting = True

    def worker():
        global media_starting

        device = cmd[2]
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            log_name
        )

        def spawn():
            log = open(
                log_path,
                "w",
                encoding="utf-8",
                errors="replace"
            )

            try:
                env = scrcpy_environment(device)

                process = subprocess.Popen(
                    cmd,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=HIDE,
                    env=env
                )

                return process, log

            except:
                try:
                    log.close()
                except:
                    pass
                raise

        def read_log(log):
            try:
                log.flush()
            except:
                pass

            try:
                with open(
                    log_path,
                    "r",
                    encoding="utf-8",
                    errors="replace"
                ) as f:
                    return f.read()
            except:
                return ""

        def wait_for_server(process, log):
            """
            Wait for scrcpy itself to finish startup.

            Do NOT impose a fixed wall-clock timeout here. On this remote
            Tailscale/ADB route the scrcpy-server upload has taken more than
            180 seconds. The previous watchdog killed the scrcpy parent while
            adb push was still active, which could leave a zero-byte
            /data/local/tmp/scrcpy-server.jar and create overlapping retries.
            """
            last_detail = ""
            last_change = time.time()

            while True:
                detail = read_log(log)

                if detail != last_detail:
                    last_detail = detail
                    last_change = time.time()

                lower = detail.lower()

                ready = (
                    "[server] info: device:" in lower or
                    "[server] info: using camera" in lower or
                    "info: renderer:" in lower or
                    "audio playback started" in lower
                )

                if ready:
                    return True, detail

                if process.poll() is not None:
                    return False, detail

                # Keep waiting while scrcpy/adb is alive. The UI remains
                # responsive because this runs in the worker thread.
                # A very long silent period is reported in the UI, but is not
                # force-killed because killing adb mid-push corrupts the
                # remote server file.
                if time.time() - last_change > 30:
                    root.after(
                        0,
                        lambda: mode_label.config(
                            text="MODE: PREPARING REMOTE MEDIA"
                        )
                    )
                    last_change = time.time()

                time.sleep(0.5)

        def is_retryable(detail):
            lower = detail.lower()

            return (
                "connect failed: closed" in lower or
                '"adb push" returned with value 1' in lower or
                "server connection failed" in lower or
                "device offline" in lower or
                "transport error" in lower
            )

        with media_start_lock:
            try:
                if not ensure_media_connection(device):
                    media_starting = False
                    root.after(
                        0,
                        lambda: on_failed(
                            "Phone ADB connection is not ready."
                        )
                    )
                    return

                process, log = spawn()
                ready, detail = wait_for_server(process, log)

                if ready:
                    media_starting = False
                    root.after(
                        0,
                        lambda p=process: on_started(p)
                    )
                    return

                try:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except:
                            pass
                except:
                    pass

                try:
                    log.close()
                except:
                    pass

                # Do not immediately launch a second large scrcpy upload after
                # a transport failure. Preserve one-button/one-session
                # semantics and report the real failure instead.
                media_starting = False

                last = detail[-2200:] if detail else (
                    "scrcpy did not report a ready server. "
                    "See " + log_path
                )

                root.after(
                    0,
                    lambda d=last: on_failed(d)
                )

            except Exception as e:
                media_starting = False
                root.after(
                    0,
                    lambda msg=str(e): on_failed(msg)
                )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()

def launch(mode, kind, facing=None):

    global current_process
    global screen_process
    global camera_process
    global current_mode
    global active_device

    device = get_device(True)

    if not device:
        messagebox.showerror(
            "AndroidBridge Lite",
            "Phone cannot be reached.\n\n"
            "Check USB, Wi-Fi or Tailscale."
        )
        return

    if kind == "screen":
        old_process = screen_process

        if old_process is not None:
            try:
                if old_process.poll() is None:
                    old_process.terminate()
                    try:
                        old_process.wait(timeout=2)
                    except:
                        old_process.kill()
            except:
                pass

        screen_process = None
        args = scrcpy_screen_args(device)
        log_name = "scrcpy-screen.log"

    else:
        old_process = camera_process

        if old_process is not None:
            try:
                if old_process.poll() is None:
                    old_process.terminate()
                    try:
                        old_process.wait(timeout=2)
                    except:
                        old_process.kill()
            except:
                pass

        camera_process = None
        args = scrcpy_camera_args(
            device,
            facing
        )
        log_name = "scrcpy-camera.log"

    current_mode = "STARTING " + mode
    mode_label.config(
        text="MODE: STARTING " + mode
    )
    route_label.config(
        text=connection_type(device)
    )
    device_label.config(
        text=device
    )

    cmd = [
        "scrcpy",
        "-s",
        device
    ] + args

    def started(process):
        global current_process
        global screen_process
        global camera_process
        global current_mode
        global active_device

        if kind == "screen":
            screen_process = process
        else:
            camera_process = process

        current_process = process
        current_mode = mode
        active_device = device

        mode_label.config(
            text="MODE: " + mode
        )

    def failed(detail):
        global current_mode

        current_mode = "ERROR"
        mode_label.config(
            text="MODE: ERROR"
        )

        messagebox.showerror(
            "AndroidBridge Lite",
            "scrcpy could not start.\n\n" + detail
        )

    start_scrcpy_resilient(
        cmd,
        log_name,
        started,
        failed
    )

def screen():
    launch(
        "SCREEN",
        "screen"
    )


def back_camera():
    launch(
        "BACK CAMERA",
        "camera",
        "back"
    )


def front_camera():
    launch(
        "FRONT CAMERA",
        "camera",
        "front"
    )



def open_phone_data(mode):

    try:
        helper = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "AndroidBridge-PhoneData.py"
        )

        if not os.path.exists(helper):
            messagebox.showerror(
                "AndroidBridge Lite",
                "Phone data helper is missing:\n\n" + helper
            )
            return

        subprocess.Popen(
            [
                "python",
                helper,
                mode
            ],
            creationflags=HIDE
        )

    except Exception as e:

        messagebox.showerror(
            "AndroidBridge Lite",
            str(e)
        )

# ============================================================
# STATUS CHECK
# ============================================================


def start_audio():

    global audio_process
    global active_device
    global current_mode

    device = get_device(True)

    if not device:
        messagebox.showerror(
            "AndroidBridge Lite",
            "Phone cannot be reached.\n\n"
            "Check USB, Wi-Fi or Tailscale."
        )
        return

    # Do not start a second microphone process.
    if audio_process is not None:
        try:
            if audio_process.poll() is None:
                current_mode = "AUDIO ON"
                mode_label.config(
                    text="MODE: AUDIO ON"
                )
                return
        except:
            pass

    current_mode = "STARTING AUDIO"
    mode_label.config(
        text="MODE: STARTING AUDIO"
    )

    cmd = [
        "scrcpy",
        "-s",
        device,
        "--no-video",
        "--audio-source=mic-voice-recognition",
        "--audio-codec=opus",
        "--audio-bit-rate=96K",
        "--audio-buffer=20",
        "--no-cleanup"
    ]

    def started(process):
        global audio_process
        global active_device
        global current_mode

        audio_process = process
        active_device = device
        current_mode = "AUDIO ON"

        mode_label.config(
            text="MODE: AUDIO ON"
        )

    def failed(detail):
        global audio_process
        global current_mode

        audio_process = None
        current_mode = "ERROR"

        mode_label.config(
            text="MODE: ERROR"
        )

        messagebox.showerror(
            "AndroidBridge Lite",
            "Audio could not start.\n\n" + detail
        )

    start_scrcpy_resilient(
        cmd,
        "scrcpy-audio.log",
        started,
        failed
    )

def stop_audio():

    global audio_process

    if audio_process is None:
        return

    try:

        if audio_process.poll() is None:

            audio_process.terminate()

            try:
                audio_process.wait(timeout=2)

            except:
                audio_process.kill()

    except:
        pass

    audio_process = None


def background_check():

    global checking

    if checking:
        return

    checking = True

    try:
        # A scrcpy server upload over remote ADB can take a long time.
        # Do not issue competing adb devices/connect checks during startup.
        if media_starting:
            device = active_device
        elif active_device:
            # Keep the UI aligned with the selected route without injecting
            # periodic ADB traffic into a working remote transport.
            device = active_device
        else:
            # Discover/connect only when there is no selected route.
            device = get_device(False)

            if not device:
                device = get_device(True)

        root.after(
            0,
            lambda d=device: display_status(d)
        )

    finally:
        checking = False


def display_status(device):

    if device:

        status.config(
            text="PHONE CONNECTED"
        )

        route_label.config(
            text=connection_type(device)
        )

        device_label.config(
            text=device
        )

    else:

        ts_state = tailscale_phone_state()

        if ts_state == "TAILSCALE OFFLINE":

            status.config(
                text="PHONE NOT CONNECTED"
            )

            route_label.config(
                text="TAILSCALE OFFLINE"
            )

            device_label.config(
                text="Open Tailscale on the phone"
            )

        elif ts_state == "TAILSCALE ONLINE":

            status.config(
                text="PHONE NOT CONNECTED"
            )

            route_label.config(
                text="TAILSCALE ONLINE - ADB NOT CONNECTED"
            )

            device_label.config(
                text="Press RECONNECT PHONE"
            )

        elif ts_state == "TAILSCALE NOT INSTALLED":

            status.config(
                text="PHONE NOT CONNECTED"
            )

            route_label.config(
                text="TAILSCALE NOT AVAILABLE"
            )

            device_label.config(
                text=""
            )

        else:

            status.config(
                text="PHONE NOT CONNECTED"
            )

            route_label.config(
                text=ts_state
            )

            device_label.config(
                text=""
            )

    mode_label.config(
        text="MODE: " + current_mode
    )

    root.after(
        5000,
        schedule_check
    )


def schedule_check():

    threading.Thread(
        target=background_check,
        daemon=True
    ).start()


def reconnect():

    global active_device

    active_device = None

    status.config(
        text="CONNECTING..."
    )

    route_label.config(
        text="CHECKING USB / WI-FI / TAILSCALE"
    )

    schedule_check()


def close_app():

    # Closing AndroidBridge closes every media session. The normal STOP
    # button still leaves audio independent.
    stop_scrcpy()
    stop_audio()

    root.destroy()


# ============================================================
# GUI - V1.4 POLISH
# ============================================================

BG = "#111318"
PANEL = "#1A1D24"
PANEL_2 = "#20242C"
TEXT = "#F4F6F8"
MUTED = "#969DA8"
ACCENT = "#4F8CFF"
SUCCESS = "#43C783"
DANGER = "#F05A67"
BORDER = "#2A2F39"

root = tk.Tk()

root.title("AndroidBridge Lite")

root.geometry("560x650")

root.resizable(False, False)

root.configure(bg=BG)

root.protocol(
    "WM_DELETE_WINDOW",
    close_app
)


# ------------------------------------------------------------
# HEADER
# ------------------------------------------------------------

header = tk.Frame(
    root,
    bg=BG
)

header.pack(
    fill="x",
    padx=30,
    pady=(26, 15)
)


tk.Label(
    header,
    text="AndroidBridge",
    font=("Segoe UI", 24, "bold"),
    bg=BG,
    fg=TEXT
).pack(
    anchor="w"
)


tk.Label(
    header,
    text="Screen & Camera Controller",
    font=("Segoe UI", 10),
    bg=BG,
    fg=MUTED
).pack(
    anchor="w",
    pady=(2, 0)
)


# ------------------------------------------------------------
# CONNECTION CARD
# ------------------------------------------------------------

connection_card = tk.Frame(
    root,
    bg=PANEL,
    highlightbackground=BORDER,
    highlightthickness=1
)

connection_card.pack(
    fill="x",
    padx=30,
    pady=(0, 18)
)


status = tk.Label(
    connection_card,
    text="SEARCHING PHONE",
    font=("Segoe UI", 12, "bold"),
    bg=PANEL,
    fg=SUCCESS
)

status.pack(
    anchor="w",
    padx=20,
    pady=(17, 3)
)


route_label = tk.Label(
    connection_card,
    text="CHECKING CONNECTION",
    font=("Segoe UI", 10, "bold"),
    bg=PANEL,
    fg=TEXT
)

route_label.pack(
    anchor="w",
    padx=20
)


device_label = tk.Label(
    connection_card,
    text="",
    font=("Segoe UI", 9),
    bg=PANEL,
    fg=MUTED
)

device_label.pack(
    anchor="w",
    padx=20,
    pady=(3, 5)
)


mode_label = tk.Label(
    connection_card,
    text="MODE: STOPPED",
    font=("Segoe UI", 9, "bold"),
    bg=PANEL,
    fg=ACCENT
)

mode_label.pack(
    anchor="w",
    padx=20,
    pady=(2, 17)
)


# ------------------------------------------------------------
# CONTROL TITLE
# ------------------------------------------------------------

tk.Label(
    root,
    text="CONTROLS",
    font=("Segoe UI", 9, "bold"),
    bg=BG,
    fg=MUTED
).pack(
    anchor="w",
    padx=31,
    pady=(0, 8)
)


# ------------------------------------------------------------
# BUTTON AREA
# ------------------------------------------------------------

buttons = tk.Frame(
    root,
    bg=BG
)

buttons.pack(
    padx=22
)


button_style = {
    "width": 21,
    "height": 2,
    "font": ("Segoe UI", 10, "bold"),
    "bg": PANEL_2,
    "fg": TEXT,
    "activebackground": ACCENT,
    "activeforeground": "#FFFFFF",
    "relief": "flat",
    "bd": 0,
    "cursor": "hand2"
}


screen_button = tk.Button(
    buttons,
    text="SCREEN",
    command=screen,
    **button_style
)

screen_button.grid(
    row=0,
    column=0,
    padx=7,
    pady=7
)

back_button = tk.Button(
    buttons,
    text="BACK CAMERA",
    command=back_camera,
    **button_style
)

back_button.grid(
    row=0,
    column=1,
    padx=7,
    pady=7
)


front_button = tk.Button(
    buttons,
    text="FRONT CAMERA",
    command=front_camera,
    **button_style
)

front_button.grid(
    row=1,
    column=0,
    padx=7,
    pady=7
)


stop_button = tk.Button(
    buttons,
    text="STOP",
    command=stop_scrcpy,
    width=21,
    height=2,
    font=("Segoe UI", 10, "bold"),
    bg=PANEL_2,
    fg=DANGER,
    activebackground=DANGER,
    activeforeground="#FFFFFF",
    relief="flat",
    bd=0,
    cursor="hand2"
)

stop_button.grid(
    row=1,
    column=1,
    padx=7,
    pady=7
)



# ============================================================
# AUDIO CONTROLS
# ============================================================

audio_on_button = tk.Button(
    buttons,
    text="AUDIO ON",
    command=start_audio,
    **button_style
)

audio_on_button.grid(
    row=2,
    column=0,
    padx=7,
    pady=7
)

audio_off_button = tk.Button(
    buttons,
    text="AUDIO OFF",
    command=stop_audio,
    width=21,
    height=2,
    font=("Segoe UI", 10, "bold"),
    bg=PANEL_2,
    fg=DANGER,
    activebackground=PANEL_2,
    activeforeground=DANGER,
    relief="flat",
    bd=0,
    cursor="hand2"
)

audio_off_button.grid(
    row=2,
    column=1,
    padx=7,
    pady=7
)


calls_button = tk.Button(
    buttons,
    text="CALLS",
    command=lambda: open_phone_data("calls"),
    **button_style
)

calls_button.grid(
    row=3,
    column=0,
    padx=7,
    pady=7
)


activity_button = tk.Button(
    buttons,
    text="PHONE ACTIVITY",
    command=lambda: open_phone_data("activity"),
    **button_style
)

activity_button.grid(
    row=3,
    column=1,
    padx=7,
    pady=7
)


location_button = tk.Button(
    buttons,
    text="LATEST LOCATION",
    command=lambda: open_phone_data("location"),
    width=45,
    height=2,
    font=("Segoe UI", 10, "bold"),
    bg=PANEL_2,
    fg=TEXT,
    activebackground=ACCENT,
    activeforeground="#FFFFFF",
    relief="flat",
    bd=0,
    cursor="hand2"
)

location_button.grid(
    row=4,
    column=0,
    columnspan=2,
    padx=7,
    pady=7
)

# ------------------------------------------------------------
# RECONNECT
# ------------------------------------------------------------

reconnect_button = tk.Button(
    root,
    text="RECONNECT PHONE",
    command=reconnect,
    width=47,
    height=2,
    font=("Segoe UI", 9, "bold"),
    bg=ACCENT,
    fg="#FFFFFF",
    activebackground="#3978E8",
    activeforeground="#FFFFFF",
    relief="flat",
    bd=0,
    cursor="hand2"
)

reconnect_button.pack(
    pady=(15, 8)
)


# ------------------------------------------------------------
# ROUTING FOOTER
# ------------------------------------------------------------

tk.Label(
    root,
    text="USB  >  LOCAL WI-FI  >  TAILSCALE REMOTE",
    font=("Segoe UI", 8),
    bg=BG,
    fg=MUTED
).pack(
    side="bottom",
    pady=18
)


root.after(
    300,
    schedule_check
)

root.mainloop()