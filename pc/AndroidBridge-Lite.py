import tkinter as tk
from tkinter import messagebox
import subprocess
import json
import socket
import re
import time
import os
import threading
import queue
import shutil
import ctypes
from ctypes import wintypes

# AndroidBridge uses the normal adb.exe from PATH. Never inherit an old
# scrcpy ADB override from an earlier experimental build.
os.environ.pop("ADB", None)
os.environ.pop("ANDROIDBRIDGE_REAL_ADB", None)

HIDE = 0x08000000

# LOCKED WORKING PROFILE
# Normal screen/camera/audio settings below are the verified baseline.
# NIGHT CAMERA is additive only and must not modify those profiles.
STABLE_PROFILE = "2026-10-06-direct-scrcpy-v1"

PHONE_NAME = "jennys-s25-ultra"
TAILSCALE_FALLBACK_IP = "100.127.244.20"
ADB_PORT = "5555"

TAILSCALE_EXE = r"C:\Program Files\Tailscale\tailscale.exe"

current_process = None
screen_process = None
camera_process = None
audio_process = None
audio_boost_process = None
audio_pipe_handle = None
current_mode = "STOPPED"
active_device = None
checking = False

# Tkinter must stay free to process paint/input events. Remote ADB, scrcpy
# startup/shutdown and Tailscale checks can take seconds, so button handlers
# dispatch those operations to workers instead of blocking the Tk event loop.
video_action_lock = threading.Lock()
audio_action_lock = threading.Lock()
ui_queue = queue.Queue()

def _queue_ui(callback):
    """Workers enqueue GUI work; only the Tk main thread executes it."""
    try:
        ui_queue.put_nowait(callback)
    except Exception:
        pass


def _drain_ui_queue():
    try:
        while True:
            callback = ui_queue.get_nowait()
            try:
                callback()
            except Exception:
                pass
    except queue.Empty:
        pass

    try:
        root.after(50, _drain_ui_queue)
    except Exception:
        pass


def _run_locked_async(lock, target, *args, **kwargs):
    def worker():
        if not lock.acquire(blocking=False):
            return
        try:
            target(*args, **kwargs)
        finally:
            lock.release()

    threading.Thread(target=worker, daemon=True).start()


# Offline GPS sync: the Companion stores fixes locally with no Internet.
# When Tailscale/network returns it sends queued JSON records to this port.
LOCATION_SYNC_PORT = 5571
LOCATION_SYNC_BIND = "0.0.0.0"


def _save_synced_location(record):
    """Persist both the complete history and a latest-location snapshot."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.dirname(script_dir)
        history_path = os.path.join(repo_root, "location_history.jsonl")
        latest_path = os.path.join(repo_root, "location.json")

        with open(history_path, "a", encoding="utf-8") as history:
            history.write(json.dumps(record, ensure_ascii=False) + "\n")

        with open(latest_path, "w", encoding="utf-8") as latest:
            json.dump(record, latest, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _location_sync_client(conn):
    accepted = 0
    try:
        conn.settimeout(5)
        data = b""
        while len(data) < 1024 * 1024:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk

        for raw in data.decode("utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except Exception:
                continue

            if not isinstance(record, dict):
                continue
            if "latitude" not in record or "longitude" not in record:
                continue

            record["synced_to_pc_at"] = int(time.time() * 1000)
            _save_synced_location(record)
            accepted += 1

        conn.sendall(("ACK " + str(accepted) + "\n").encode("ascii"))
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def location_sync_server():
    """Receive queued offline GPS fixes when the phone becomes reachable."""
    while True:
        server = None
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((LOCATION_SYNC_BIND, LOCATION_SYNC_PORT))
            server.listen(4)

            while True:
                conn, addr = server.accept()
                threading.Thread(
                    target=_location_sync_client,
                    args=(conn,),
                    daemon=True
                ).start()
        except Exception:
            time.sleep(5)
        finally:
            try:
                if server is not None:
                    server.close()
            except Exception:
                pass



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


def adb_quick_state(device, timeout=None):
    """Check an existing ADB route without disconnecting or resetting it."""
    if not device:
        return False

    # Remote ADB over Tailscale can legitimately take several seconds even
    # while scrcpy works. A 2-second cutoff caused false PHONE NOT CONNECTED
    # states on the same route that the verified manual scrcpy command used.
    if timeout is None:
        timeout = 15 if is_tailscale(device) else 3

    try:
        result = subprocess.run(
            ["adb", "-s", device, "get-state"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        return result.returncode == 0 and result.stdout.strip() == "device"

    except Exception:
        return False

def adb_list():
    result = run_hidden(["adb", "devices"], 8)

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

    # Already connected - return immediately. Remote ADB can be slow without
    # being offline, so use the remote-safe timeout.
    if adb_quick_state(target, 15):
        return target

    try:
        subprocess.run(
            ["adb", "connect", target],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception:
        return None

    # Verify without tearing down the session.
    if adb_quick_state(target, 15):
        return target

    return None


def get_device(allow_remote=True):

    global active_device

    # First use an existing ADB route.
    device = choose_existing_device()

    if device:
        active_device = device
        return device

    if allow_remote:
        # The Samsung's established remote ADB endpoint is authoritative for
        # AndroidBridge. Probe it directly before trusting a Tailscale status
        # label. This is the exact serial used by the verified manual scrcpy
        # command.
        known_target = f"{TAILSCALE_FALLBACK_IP}:{ADB_PORT}"

        if adb_quick_state(known_target, 15):
            active_device = known_target
            return known_target

        # If the cached ADB route is absent, ask ADB to reconnect over the
        # existing Tailscale network. Never disconnect, kill-server, or reset
        # the phone.
        device = connect_tailscale()

        if device:
            active_device = device
            return device

    active_device = None
    return None


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

    # VIDEO STOP is deliberately separate from AUDIO OFF.
    # Camera/screen processes never own microphone audio.
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

    _queue_ui(
        lambda: mode_label.config(text="MODE: STOPPED")
    )


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
    # Two simultaneous remote H.264 streams share the same Tailscale/ADB
    # path. Keep the screen deliberately light so camera + screen remain
    # responsive instead of competing for the transport.
    return [
        "--max-size=800",
        "--max-fps=20",
        "--video-bit-rate=1M",
        "--video-buffer=0",
        "--video-codec=h264",
        "--no-audio",
        "--window-title=AndroidBridge SCREEN"
    ]


def scrcpy_camera_args(device, facing, night=False, low_light=False):

    # The Samsung reported camera 0 as back and camera 1 as front.
    # Use those exact IDs instead of asking Android to choose a camera.
    camera_id = "0" if facing == "back" else "1"

    if low_light:
        # Sensor-only low-light test: no torch and no fixed FPS. Leaving the
        # AE target FPS unset lets Android Camera2 choose its own exposure
        # behavior instead of AndroidBridge forcing the verified 15/30 FPS.
        camera_id = "0"
        title = "AndroidBridge NIGHT VISION BOOST"
    elif night:
        # Stable night mode: use the proven rear camera path plus Samsung's
        # physical LED torch. This does not alter the normal camera profiles.
        camera_id = "0"
        title = "AndroidBridge NIGHT CAMERA"
    elif facing == "back":
        title = "AndroidBridge BACK CAMERA"
    else:
        title = "AndroidBridge FRONT CAMERA"

    # USB / LOCAL WIFI
    if is_usb(device) or is_local(device):
        args = [
            "--video-source=camera",
            f"--camera-id={camera_id}",
            "--max-size=1920",
            "--camera-ar=16:9",
            "--video-bit-rate=4M",
            "--video-codec=h264",
            "--no-audio",
            f"--window-title={title}"
        ]
        if not low_light:
            args.insert(4, "--camera-fps=30")
        if night:
            args.insert(2, "--camera-torch")
        return args

    # TAILSCALE REMOTE
    # Do not force 640x360. Samsung may expose a camera but not produce
    # frames for an arbitrary explicit size. Let scrcpy select a declared
    # camera resolution at or below 640 pixels instead.
    args = [
        "--video-source=camera",
        f"--camera-id={camera_id}",
        "--max-size=640",
        "--camera-ar=16:9",
        "--video-bit-rate=450K",
        "--video-buffer=0",
        "--video-codec=h264",
        "--no-audio",
        f"--window-title={title}"
    ]
    if not low_light:
        args.insert(4, "--camera-fps=15")
    if night:
        args.insert(2, "--camera-torch")
    return args


def _set_nightvision_window_title(status):
    """Put the hardware test result on the scrcpy window itself."""
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        FindWindowW = user32.FindWindowW
        FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        FindWindowW.restype = wintypes.HWND
        SetWindowTextW = user32.SetWindowTextW
        SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        SetWindowTextW.restype = wintypes.BOOL

        # The title may already contain a previous state, so find by enumerating
        # top-level windows whose title starts with the AndroidBridge prefix.
        matches = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def enum_proc(hwnd, lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value.startswith("AndroidBridge NIGHT VISION BOOST"):
                    matches.append(hwnd)
            return True

        user32.EnumWindows(enum_proc, 0)
        for hwnd in matches:
            SetWindowTextW(hwnd, "AndroidBridge NIGHT VISION BOOST - " + status)
    except:
        pass


def _watch_nightvision_log(process):
    """Show whether Android's hardware Low Light Boost is actually active."""
    try:
        saw_capability = False
        for raw_line in process.stdout:
            line = raw_line.strip()

            if "AndroidBridge LLB" in line:
                saw_capability = True

            if "AndroidBridge NV diag:" in line:
                match = re.search(
                    r"NIGHT_EXTENSION=(true|false), ISO=(.*?), EXPOSURE_NS=(.*?), FLASH=(true|false|null)",
                    line,
                    re.IGNORECASE
                )
                if match:
                    night_ext, iso_range, exposure_range, flash = match.groups()
                    detail = (
                        "NV SENSOR: Night Extension " + night_ext.upper()
                        + " | ISO " + iso_range
                        + " | Exposure " + exposure_range + " ns"
                    )
                    _queue_ui(
                        lambda value=detail: nv_diag_label.config(text=value)
                    )

            if "AndroidBridge LLB support: true" in line:
                _set_nightvision_window_title("SUPPORTED - WAITING FOR ACTIVE")
                _queue_ui(
                    lambda: mode_label.config(
                        text="MODE: NIGHT VISION BOOST - SUPPORTED"
                    )
                )

            elif "AndroidBridge LLB state: ACTIVE" in line:
                _set_nightvision_window_title("LLB ACTIVE")
                _queue_ui(
                    lambda: mode_label.config(
                        text="MODE: NIGHT VISION BOOST - ACTIVE"
                    )
                )

            elif "AndroidBridge LLB is not exposed" in line or "AndroidBridge LLB support: false" in line:
                _set_nightvision_window_title("LLB NOT SUPPORTED")
                _queue_ui(
                    lambda: mode_label.config(
                        text="MODE: NIGHT VISION BOOST - NOT SUPPORTED"
                    )
                )

        if not saw_capability:
            _set_nightvision_window_title("CAPABILITY UNKNOWN")
            _queue_ui(
                lambda: mode_label.config(
                    text="MODE: NIGHT VISION BOOST - CAPABILITY UNKNOWN"
                )
            )
    except:
        _queue_ui(
            lambda: mode_label.config(
                text="MODE: NIGHT VISION BOOST - STATUS ERROR"
            )
        )


def launch(mode, kind, facing=None, night=False, low_light=False):

    global current_process
    global screen_process
    global camera_process
    global current_mode
    global active_device

    # MEDIA ROUTE:
    # Do not gate scrcpy behind a second Python ADB/Tailscale preflight.
    # The exact command below has already been verified manually against this
    # Samsung endpoint. scrcpy itself is the authority on whether the media
    # session can start.
    device = choose_existing_device()
    if not device:
        device = f"{TAILSCALE_FALLBACK_IP}:{ADB_PORT}"

    active_device = device

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
            facing,
            night=night,
            low_light=low_light
        )

    time.sleep(0.3)

    try:

        scrcpy_env = os.environ.copy()
        scrcpy_env.pop("SCRCPY_SERVER_PATH", None)

        stderr_target = subprocess.DEVNULL

        if low_light:
            _queue_ui(
                lambda: nv_diag_label.config(
                    text="NV SENSOR: reading Samsung camera capabilities..."
                )
            )

            # Only NIGHT VISION BOOST uses the custom scrcpy v4.1 server.
            # Normal SCREEN/BACK/FRONT profiles remain on the stock server.
            custom_server = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "scrcpy-server-v4.1-llb"
            )

            if not os.path.isfile(custom_server):
                _queue_ui(
                    lambda: messagebox.showerror(
                        "AndroidBridge Night Vision",
                        "Low Light Boost engine is missing.\n\n"
                        "Run git pull, then restart AndroidBridge."
                    )
                )
                return

            scrcpy_env["SCRCPY_SERVER_PATH"] = custom_server
            stderr_target = subprocess.PIPE

        # Use stock scrcpy directly. This is intentionally the same path as
        # the verified manual PowerShell command. No ADB proxy, no chunker,
        # no persistent-server interception.
        process = subprocess.Popen(
            [
                "scrcpy",
                "-s",
                device
            ] + args,
            stdout=subprocess.PIPE if low_light else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if low_light else subprocess.DEVNULL,
            text=bool(low_light),
            errors="replace" if low_light else None,
            creationflags=HIDE,
            env=scrcpy_env
        )

        if low_light and process.stdout is not None:
            threading.Thread(
                target=_watch_nightvision_log,
                args=(process,),
                daemon=True
            ).start()

        if kind == "screen":
            screen_process = process
        else:
            camera_process = process

        current_process = process
        current_mode = mode
        active_device = device

        route_text = connection_type(device)
        _queue_ui(
            lambda m=mode, r=route_text, d=device: (
                mode_label.config(text="MODE: " + m),
                route_label.config(text=r),
                device_label.config(text=d)
            )
        )

    except Exception as e:

        current_mode = "ERROR"

        error_text = str(e)
        _queue_ui(
            lambda msg=error_text: messagebox.showerror(
                "AndroidBridge Lite",
                msg
            )
        )


def screen():
    _run_locked_async(
        video_action_lock,
        launch,
        "SCREEN",
        "screen"
    )


def back_camera():
    _run_locked_async(
        video_action_lock,
        launch,
        "BACK CAMERA",
        "camera",
        "back"
    )


def front_camera():
    _run_locked_async(
        video_action_lock,
        launch,
        "FRONT CAMERA",
        "camera",
        "front"
    )


def low_light_test():
    # No torch. This measures what the rear camera can obtain from available
    # visible light using Camera2 automatic exposure behavior.
    _run_locked_async(
        video_action_lock,
        launch,
        "NIGHT VISION BOOST",
        "camera",
        "back",
        low_light=True
    )


def open_phone_data(mode):

    try:

        subprocess.Popen(
            [
                "python",
                os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "AndroidBridge-PhoneData.py"
                ),
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
# SEPARATE AUDIO CLARITY PIPELINE
# scrcpy audio-only -> named pipe -> FFplay speech DSP
# Kept independent from Screen/Camera by design.
# ============================================================


def _audio_boost_relay(pipe_name, ffplay_path, ready_event):
    """Relay scrcpy audio through a speech-focused distant-listening DSP chain."""
    global audio_boost_process
    global audio_pipe_handle

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    CreateNamedPipeW = kernel32.CreateNamedPipeW
    CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID
    ]
    CreateNamedPipeW.restype = wintypes.HANDLE

    ConnectNamedPipe = kernel32.ConnectNamedPipe
    ConnectNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    ConnectNamedPipe.restype = wintypes.BOOL

    ReadFile = kernel32.ReadFile
    ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID
    ]
    ReadFile.restype = wintypes.BOOL

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    PIPE_ACCESS_INBOUND = 0x00000001
    PIPE_TYPE_BYTE = 0x00000000
    PIPE_READMODE_BYTE = 0x00000000
    PIPE_WAIT = 0x00000000
    ERROR_PIPE_CONNECTED = 535
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    handle = CreateNamedPipeW(
        pipe_name,
        PIPE_ACCESS_INBOUND,
        PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
        1,
        65536,
        65536,
        0,
        None
    )

    if handle == INVALID_HANDLE_VALUE:
        ready_event.set()
        return

    audio_pipe_handle = handle
    ready_event.set()

    player = None

    try:
        connected = ConnectNamedPipe(handle, None)
        if not connected and ctypes.get_last_error() != ERROR_PIPE_CONNECTED:
            return

        # Distant-speech DSP:
        # WIND FILTER MAX:
        # 1) cut more sub-speech wind/rumble below 240 Hz,
        # 2) stronger adaptive FFT denoise,
        # 3) mild noise gate before gain so wind is not amplified in pauses,
        # 4) emphasize speech presence around 2.5-4 kHz,
        # 5) dynamically raise cleaned distant speech up to 16x (after wind suppression),
        # 6) peak-limit the result to prevent clipping.
        # Do not append a separate volume filter here: the previous +6 dB stage
        # could make FFplay reject the filter graph and produce no playback.
        player = subprocess.Popen(
            [
                ffplay_path,
                "-nodisp",
                "-autoexit",
                "-loglevel", "error",
                "-fflags", "nobuffer",
                "-flags", "low_delay",
                "-af", "highpass=f=240:p=2,lowpass=f=6800:p=2,afftdn=nr=30:nf=-38:tn=1:gs=16,agate=threshold=0.012:ratio=2.5:attack=12:release=220,equalizer=f=2500:t=q:w=1:g=5,equalizer=f=4000:t=q:w=1:g=2,dynaudnorm=f=160:g=7:p=0.90:m=16:r=0.08:t=0.002,alimiter=limit=0.93:level=0:attack=5:release=100",
                "-i", "pipe:0"
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=HIDE,
            bufsize=0
        )

        audio_boost_process = player

        buffer = ctypes.create_string_buffer(65536)
        count = wintypes.DWORD()

        while player.poll() is None:
            ok = ReadFile(
                handle,
                buffer,
                len(buffer),
                ctypes.byref(count),
                None
            )

            if not ok or count.value == 0:
                break

            try:
                player.stdin.write(buffer.raw[:count.value])
            except (BrokenPipeError, OSError):
                break

    finally:
        if player is not None:
            try:
                if player.stdin:
                    player.stdin.close()
            except:
                pass

            try:
                if player.poll() is None:
                    player.terminate()
            except:
                pass

        audio_boost_process = None
        audio_pipe_handle = None

        try:
            CloseHandle(handle)
        except:
            pass


def start_audio():

    global audio_process
    global active_device

    # Use the same proven media route as screen/camera. Let scrcpy report a
    # genuine transport failure instead of blocking on a separate preflight.
    device = choose_existing_device()
    if not device:
        device = f"{TAILSCALE_FALLBACK_IP}:{ADB_PORT}"

    active_device = device

    # Do not start a second microphone process.
    if audio_process is not None:

        try:
            if audio_process.poll() is None:
                return
        except:
            pass

    ffplay_path = shutil.which("ffplay")

    if not ffplay_path:
        _queue_ui(
            lambda: messagebox.showerror(
                "AndroidBridge Audio Boost",
                "FFplay is required for distant-speech amplification and noise reduction.\n\n"
                "Install once in PowerShell:\n"
                "winget install -e --id Gyan.FFmpeg"
            )
        )
        return

    pipe_name = r"\\.\pipe\AndroidBridgeAudio-" + str(os.getpid()) + "-" + str(time.time_ns())
    ready_event = threading.Event()

    relay = threading.Thread(
        target=_audio_boost_relay,
        args=(pipe_name, ffplay_path, ready_event),
        daemon=True
    )
    relay.start()

    if not ready_event.wait(timeout=2):
        _queue_ui(
            lambda: messagebox.showerror(
                "AndroidBridge Audio Boost",
                "Could not prepare the PC audio boost pipeline."
            )
        )
        return

    try:

        audio_env = os.environ.copy()
        audio_env.pop("SCRCPY_SERVER_PATH", None)

        # Use Samsung's voice-recognition capture path rather than camcorder audio:
        # camcorder preserves ambience (including wind); voice-recognition is a
        # better source for intelligible speech before our PC-side wind filter.
        # scrcpy captures the Samsung microphone but does not play it itself.
        # Its live Opus stream is written to a Windows named pipe. FFplay reads
        # it and applies speech-band filtering, adaptive FFT denoise,
        # presence EQ, dynamic quiet-speech gain and peak limiting.
        audio_process = subprocess.Popen(
            [
                "scrcpy",
                "-s",
                device,
                "--no-video",
                "--no-audio-playback",
                "--audio-source=mic-voice-recognition",
                "--audio-codec=opus",
                "--audio-bit-rate=128K",
                "--audio-buffer=60",
                "--record=" + pipe_name,
                "--record-format=opus"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=HIDE,
            env=audio_env
        )

        active_device = device

        _queue_ui(
            lambda: mode_label.config(
                text="MODE: DISTANT SPEECH MAX - WIND FILTER MAX"
            )
        )

    except Exception as e:

        audio_process = None

        error_text = "Audio boost could not start:\n\n" + str(e)
        _queue_ui(
            lambda msg=error_text: messagebox.showerror(
                "AndroidBridge Lite",
                msg
            )
        )


def stop_audio():

    global audio_process
    global audio_boost_process
    global audio_pipe_handle

    if audio_process is not None:
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

    if audio_boost_process is not None:
        try:
            if audio_boost_process.poll() is None:
                audio_boost_process.terminate()
        except:
            pass

    audio_boost_process = None

    # Closing the server end also releases a relay blocked in ReadFile.
    if audio_pipe_handle is not None:
        try:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(audio_pipe_handle)
        except:
            pass

    audio_pipe_handle = None

    if current_mode == "STOPPED":
        _queue_ui(
            lambda: mode_label.config(text="MODE: STOPPED")
        )

def background_check():

    global checking

    if checking:
        return

    # Do not send status ADB commands while scrcpy is starting or streaming.
    # The verified manual camera path has no competing ADB polling. Keeping the
    # GUI status checker quiet here makes AndroidBridge use the same transport
    # conditions as that known-working command.
    for media_process in (screen_process, camera_process, audio_process):
        try:
            if media_process is not None and media_process.poll() is None:
                return
        except Exception:
            pass

    if video_action_lock.locked() or audio_action_lock.locked():
        return

    checking = True

    try:
        # Do NOT reconnect Tailscale every 5 seconds.
        # First inspect existing connections only.
        device = get_device(False)

        # If nothing exists, try remote once.
        if not device:
            device = get_device(True)

        # Never let the Tailscale CLI overrule a working ADB endpoint. If the
        # Python status probe is inconclusive, show the configured remote route
        # rather than the false "TAILSCALE OFFLINE / Open Tailscale" message.
        ts_state = None
        if not device:
            ts_state = "REMOTE ADB CHECK PENDING"

        _queue_ui(
            lambda d=device, ts=ts_state: display_status(d, ts)
        )

    finally:
        checking = False


def display_status(device, ts_state=None):

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

        if ts_state is None:
            ts_state = "TAILSCALE STATUS UNKNOWN"

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

        elif ts_state == "REMOTE ADB CHECK PENDING":

            status.config(
                text="REMOTE PHONE CONFIGURED"
            )

            route_label.config(
                text="TAILSCALE - REMOTE"
            )

            device_label.config(
                text=f"{TAILSCALE_FALLBACK_IP}:{ADB_PORT}"
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


def _shutdown_processes_no_ui():
    """Best-effort process cleanup after the Tk window has been dismissed."""
    processes = []
    seen = set()

    for process in (
        screen_process,
        camera_process,
        audio_process,
        audio_boost_process
    ):
        if process is None or id(process) in seen:
            continue
        seen.add(id(process))
        processes.append(process)

    # Signal every local helper first. Do not wait on one remote stream before
    # telling the others to exit.
    for process in processes:
        try:
            if process.poll() is None:
                process.terminate()
        except Exception:
            pass

    # Release a relay blocked on the named audio pipe.
    if audio_pipe_handle is not None:
        try:
            ctypes.WinDLL(
                "kernel32",
                use_last_error=True
            ).CloseHandle(audio_pipe_handle)
        except Exception:
            pass

    # Give local helpers a short grace period, then force only the local
    # processes that did not exit. This never disconnects or resets ADB.
    deadline = time.monotonic() + 1.5

    for process in processes:
        try:
            if process.poll() is not None:
                continue

            remaining = deadline - time.monotonic()
            if remaining > 0:
                process.wait(timeout=remaining)

            if process.poll() is None:
                process.kill()
        except Exception:
            try:
                if process.poll() is None:
                    process.kill()
            except Exception:
                pass


def close_app():
    # Never make the Tk event loop wait for scrcpy/audio cleanup. Hide the
    # window immediately, clean local child processes in a non-daemon worker,
    # then destroy Tk. The Python process stays alive only long enough for that
    # short cleanup worker to finish.
    try:
        root.withdraw()
    except Exception:
        pass

    threading.Thread(
        target=_shutdown_processes_no_ui,
        daemon=False
    ).start()

    try:
        root.destroy()
    except Exception:
        pass


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

root.geometry("560x675")

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
    pady=(2, 4)
)


nv_diag_label = tk.Label(
    connection_card,
    text="",
    font=("Segoe UI", 8),
    bg=PANEL,
    fg=MUTED,
    wraplength=500,
    justify="left"
)

nv_diag_label.pack(
    anchor="w",
    padx=20,
    pady=(0, 13)
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
    command=lambda: _run_locked_async(video_action_lock, stop_scrcpy),
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
    text="DISTANT SPEECH MAX",
    command=lambda: _run_locked_async(audio_action_lock, start_audio),
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
    command=lambda: _run_locked_async(audio_action_lock, stop_audio),
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


low_light_button = tk.Button(
    buttons,
    text="NIGHT VISION BOOST",
    command=low_light_test,
    **button_style
)

low_light_button.grid(
    row=3,
    column=0,
    columnspan=2,
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
    row=4,
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
    row=4,
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
    row=5,
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


# Start worker -> GUI dispatch on the Tk main thread.
root.after(50, _drain_ui_queue)

root.after(
    300,
    schedule_check
)

threading.Thread(target=location_sync_server, daemon=True).start()

root.mainloop()