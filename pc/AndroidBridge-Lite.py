import tkinter as tk
from tkinter import messagebox
import subprocess
import re
import time
import os
import threading

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


# ============================================================
# PROCESS HELPERS
# ============================================================

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
    global audio_process
    global current_mode

    for process in (screen_process, camera_process, audio_process):

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
    audio_process = None
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
        "--window-title=AndroidBridge SCREEN"
    ]


def scrcpy_camera_args(device, facing):

    # USB / LOCAL WIFI
    if is_usb(device) or is_local(device):
        size = "1920x1080"
        fps = "30"

    # TAILSCALE REMOTE
    else:
        size = "640x360"
        fps = "24"

    if facing == "back":
        title = "AndroidBridge BACK CAMERA"
    else:
        title = "AndroidBridge FRONT CAMERA"

    return [
        "--video-source=camera",
        f"--camera-facing={facing}",
        f"--camera-size={size}",
        f"--camera-fps={fps}",
        "--video-bit-rate=800K",
        "--video-codec=h264",
        "--no-audio",
        f"--window-title={title}"
    ]


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

    time.sleep(0.3)

    try:

        process = subprocess.Popen(
            [
                "scrcpy",
                "-s",
                device
            ] + args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=HIDE
        )

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

        route_label.config(
            text=connection_type(device)
        )

        device_label.config(
            text=device
        )

    except Exception as e:

        current_mode = "ERROR"

        messagebox.showerror(
            "AndroidBridge Lite",
            str(e)
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

        subprocess.Popen(
            [
                "python",
                r"C:\AndroidBridge-Lite\AndroidBridge-PhoneData.py",
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
                return
        except:
            pass

    try:

        audio_process = subprocess.Popen(
            [
                "scrcpy",
                "-s",
                device,
                "--no-video",
                "--audio-source=mic"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=HIDE
        )

        active_device = device

    except Exception as e:

        audio_process = None

        messagebox.showerror(
            "AndroidBridge Lite",
            "Audio could not start:\n\n" + str(e)
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
        # Do NOT reconnect Tailscale every 5 seconds.
        # First inspect existing connections only.
        device = get_device(False)

        # If nothing exists, try remote once.
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

    stop_scrcpy()

    root.destroy()


# ============================================================
# GUI - V1.4 POLISH
# ============================================================

BG = "#111318"
PANEL = "#1A1D24"PANEL_2 = "#20242C"
TEXT = "#F4F6F8"
MUTED = "#969DA8"
ACCENT = "#4F8CFF"
SUCCESS = "#43C783"
DANGER = "#F05A67"
BORDER = "#2A2F39"

root = tk.Tk()

root.title("AndroidBridge Lite")

# Open the controller in the center of the current Windows desktop.
WINDOW_W = 560
WINDOW_H = 650
root.update_idletasks()
screen_w = root.winfo_screenwidth()
screen_h = root.winfo_screenheight()
pos_x = max(0, (screen_w - WINDOW_W) // 2)
pos_y = max(0, (screen_h - WINDOW_H) // 2)
root.geometry(f"{WINDOW_W}x{WINDOW_H}+{pos_x}+{pos_y}")

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
    row=3,
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


# Force the controller to the foreground on startup so it cannot open
# behind a scrcpy camera/screen window or the browser.
root.deiconify()
root.lift()
root.attributes("-topmost", True)
root.focus_force()
root.after(1200, lambda: root.attributes("-topmost", False))

root.after(
    300,
    schedule_check
)

root.mainloop()
