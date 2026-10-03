from __future__ import annotations

import ipaddress
import json
import subprocess
from pathlib import Path
from typing import Any


READY = "READY"
PHONE_OFFLINE = "PHONE_OFFLINE"
CONNECTION_FAILED = "CONNECTION_FAILED"

CONFIG_FILE = Path(__file__).with_name("phonehub_config.json")

# Known install location on Windows. Avoids relying on %PATH%, which
# may not include Tailscale even when it's installed and running.
TAILSCALE_EXE = r"C:\Program Files\Tailscale\tailscale.exe"


# ============================================================
# PRIVATE HELPERS
# These are implementation details.
# Other PhoneHub modules should NOT call ADB directly.
# ============================================================

def _load_config() -> dict:
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as exc:
        raise RuntimeError(f"Cannot load {CONFIG_FILE}: {exc}") from exc

    phone = config.get("phone", {})

    ip = phone.get("tailscale_ip")
    if not ip:
        raise RuntimeError("phone.tailscale_ip is missing from config")

    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid Tailscale IP in config: {ip}"
        ) from exc

    # Tailscale IPv4 address space
    tailscale_net = ipaddress.ip_network("100.64.0.0/10")

    if parsed not in tailscale_net:
        raise RuntimeError(
            f"{ip} is not inside the Tailscale CGNAT range 100.64.0.0/10"
        )

    return config


def _run(
    command: list[str],
    timeout: int,
) -> tuple[int, str, str]:
    """
    Run a process safely.

    Always returns:
        return_code, stdout, stderr

    A timeout becomes a controlled failure instead of hanging PhoneHub.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0,
        )

        return (
            result.returncode,
            result.stdout.strip(),
            result.stderr.strip(),
        )

    except subprocess.TimeoutExpired:
        return 124, "", "TIMEOUT"

    except FileNotFoundError:
        return 127, "", f"COMMAND_NOT_FOUND: {command[0]}"

    except Exception as exc:
        return 1, "", str(exc)


def _endpoint(config: dict) -> str:
    phone = config["phone"]

    return (
        f"{phone['tailscale_ip']}:"
        f"{phone.get('adb_port', 5555)}"
    )


def _tailscale_peer_online(config: dict) -> bool:
    """
    Checks basic reachability over the Tailscale path.

    This does NOT establish ADB.
    """
    ip = config["phone"]["tailscale_ip"]
    timeout = config.get("timeouts", {}).get("tailscale", 5)

    code, stdout, stderr = _run(
        [
            TAILSCALE_EXE,
            "ping",
            "--timeout",
            f"{timeout}s",
            ip,
        ],
        timeout + 2,
    )

    return code == 0


def _adb_device_state(
    endpoint: str,
    timeout: int,
) -> str | None:
    """
    Returns:
        device
        offline
        unauthorized
        None
    """
    code, stdout, _ = _run(
        ["adb", "devices"],
        timeout,
    )

    if code != 0:
        return None

    for line in stdout.splitlines():
        parts = line.strip().split()

        if len(parts) < 2:
            continue

        serial, state = parts[0], parts[1]

        if serial == endpoint:
            return state

    return None


def _adb_connect(
    endpoint: str,
    timeout: int,
) -> bool:
    code, stdout, stderr = _run(
        ["adb", "connect", endpoint],
        timeout,
    )

    combined = f"{stdout} {stderr}".lower()

    if code != 0:
        return False

    return (
        "connected to" in combined
        or "already connected" in combined
    )


def _adb_shell(
    endpoint: str,
    command: str,
    timeout: int,
) -> tuple[bool, str]:
    code, stdout, stderr = _run(
        [
            "adb",
            "-s",
            endpoint,
            "shell",
            command,
        ],
        timeout,
    )

    if code != 0:
        message = stderr or stdout or "ADB_COMMAND_FAILED"
        return False, message

    return True, stdout.strip()


def _get_device_identity(
    config: dict,
    endpoint: str,
) -> dict[str, str]:
    timeout = config.get("timeouts", {}).get("adb_command", 8)

    identity = {
        "model": "",
        "serial": "",
    }

    ok, model = _adb_shell(
        endpoint,
        "getprop ro.product.model",
        timeout,
    )

    if ok:
        identity["model"] = model.strip()

    # Different manufacturers expose serial through different properties.
    for prop in (
        "ro.serialno",
        "ro.boot.serialno",
    ):
        ok, value = _adb_shell(
            endpoint,
            f"getprop {prop}",
            timeout,
        )

        if ok and value.strip():
            identity["serial"] = value.strip()
            break

    return identity


def _verify_device_identity(
    config: dict,
    endpoint: str,
) -> bool:
    phone = config["phone"]

    expected_model = (
        phone.get("expected_model") or ""
    ).strip()

    expected_serial = (
        phone.get("expected_serial") or ""
    ).strip()

    # At least one identity constraint must exist.
    if not expected_model and not expected_serial:
        return False

    actual = _get_device_identity(
        config,
        endpoint,
    )

    if expected_serial:
        if actual["serial"] != expected_serial:
            return False

    if expected_model:
        if actual["model"].lower() != expected_model.lower():
            return False

    return True


# ============================================================
# PUBLIC FUNCTION 1
# ============================================================

def ensureRemoteConnection() -> str:
    """
    Establish or reuse the PhoneHub connection.

    Returns exactly one of:

        READY
        PHONE_OFFLINE
        CONNECTION_FAILED
    """

    try:
        config = _load_config()
        endpoint = _endpoint(config)
    except Exception:
        return CONNECTION_FAILED

    timeouts = config.get("timeouts", {})

    adb_timeout = timeouts.get(
        "adb_command",
        8,
    )

    connect_timeout = timeouts.get(
        "adb_connect",
        8,
    )

    # --------------------------------------------------------
    # 1. Reuse an already-live connection.
    # --------------------------------------------------------

    state = _adb_device_state(
        endpoint,
        adb_timeout,
    )

    if state == "device":
        if _verify_device_identity(
            config,
            endpoint,
        ):
            return READY

        # Wrong device or identity mismatch.
        return CONNECTION_FAILED

    # --------------------------------------------------------
    # 2. Before reconnecting, verify the Tailscale path.
    # --------------------------------------------------------

    if not _tailscale_peer_online(config):
        return PHONE_OFFLINE

    # --------------------------------------------------------
    # 3. Tailscale is alive. Attempt ADB recovery transport.
    # --------------------------------------------------------

    if not _adb_connect(
        endpoint,
        connect_timeout,
    ):
        return CONNECTION_FAILED

    # --------------------------------------------------------
    # 4. Check resulting state.
    # --------------------------------------------------------

    state = _adb_device_state(
        endpoint,
        adb_timeout,
    )

    if state != "device":
        return CONNECTION_FAILED

    # --------------------------------------------------------
    # 5. Never say READY until identity has been verified.
    # --------------------------------------------------------

    if not _verify_device_identity(
        config,
        endpoint,
    ):
        return CONNECTION_FAILED

    return READY


# ============================================================
# BATTERY CAPABILITY
# Private implementation.
#
# Future screen/camera/apps handlers will follow the same model.
# ============================================================

def _battery_capability(
    config: dict,
    endpoint: str,
) -> dict[str, Any]:

    timeout = config.get("timeouts", {}).get(
        "adb_command",
        8,
    )

    ok, output = _adb_shell(
        endpoint,
        "dumpsys battery",
        timeout,
    )

    if not ok:
        return {
            "status": CONNECTION_FAILED,
            "action": "battery",
            "error": output,
        }

    battery: dict[str, Any] = {}

    for line in output.splitlines():
        line = line.strip()

        if ":" not in line:
            continue

        key, value = line.split(":", 1)

        key = key.strip()
        value = value.strip()

        battery[key] = value

    return {
        "status": READY,
        "action": "battery",
        "battery": {
            "level": battery.get("level"),
            "status_code": battery.get("status"),
            "health_code": battery.get("health"),
            "temperature_raw": battery.get(
                "temperature"
            ),
            "voltage_mv": battery.get(
                "voltage"
            ),
            "usb_powered": battery.get(
                "USB powered"
            ),
            "ac_powered": battery.get(
                "AC powered"
            ),
            "wireless_powered": battery.get(
                "Wireless powered"
            ),
        },
    }


# ============================================================
# PUBLIC FUNCTION 2
# ============================================================

def executeCapability(
    action: str,
    parameters: dict | None = None,
) -> dict[str, Any]:

    parameters = parameters or {}

    # --------------------------------------------------------
    # CRITICAL ARCHITECTURE RULE:
    # Every capability goes through the connection manager.
    # --------------------------------------------------------

    connection_status = ensureRemoteConnection()

    if connection_status != READY:
        return {
            "status": connection_status,
            "action": action,
            "error": (
                "PhoneHub connection is not ready"
            ),
        }

    try:
        config = _load_config()
        endpoint = _endpoint(config)
    except Exception as exc:
        return {
            "status": CONNECTION_FAILED,
            "action": action,
            "error": str(exc),
        }

    # --------------------------------------------------------
    # Capability dispatcher
    # --------------------------------------------------------

    if action == "battery":
        return _battery_capability(
            config,
            endpoint,
        )

    return {
        "status": CONNECTION_FAILED,
        "action": action,
        "error": (
            f"Unsupported capability: {action}"
        ),
    }


# ============================================================
# FIRST END-TO-END TEST
# ============================================================

if __name__ == "__main__":

    print("PhoneHub connection test")
    print("------------------------")

    result = executeCapability(
        "battery"
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )
