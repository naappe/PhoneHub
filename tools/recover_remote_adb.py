#!/usr/bin/env python3
"""
AndroidBridge remote ADB recovery.

Android Wireless Debugging binds its TLS server to an OS-selected ephemeral
TCP port. mDNS does not traverse a normal Tailscale routed connection, so after
a remote phone reboot the PC may know the phone's Tailscale IP but not the new
ADB TLS port.

This tool scans only the normal Linux ephemeral range (32768-60999) on the
configured phone, then asks the already-paired local adb client to authenticate
to any open candidates. It never kills/resets/disconnects adb and never changes
phone settings.
"""

from __future__ import annotations

import concurrent.futures
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

PHONE_IP = os.environ.get("ANDROIDBRIDGE_PHONE_IP", "100.127.244.20")
PORT_FIRST = 32768
PORT_LAST = 60999
CONNECT_TIMEOUT = 0.85
WORKERS = 256

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "pc" / ".androidbridge-adb-tls-port"


def tcp_open(port: int) -> int | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(CONNECT_TIMEOUT)
    try:
        if s.connect_ex((PHONE_IP, port)) == 0:
            return port
    except OSError:
        pass
    finally:
        s.close()
    return None


def run(args: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def adb_is_device(target: str) -> bool:
    try:
        state = run(["adb", "-s", target, "get-state"], 7.0)
        return state.returncode == 0 and state.stdout.strip() == "device"
    except (OSError, subprocess.TimeoutExpired):
        return False


def try_adb_port(port: int) -> bool:
    target = f"{PHONE_IP}:{port}"
    print(f"[AndroidBridge] Testing candidate {target} ...", flush=True)
    try:
        result = run(["adb", "connect", target], 10.0)
        message = result.stdout.strip()
        if message:
            print(f"  {message}", flush=True)
    except subprocess.TimeoutExpired:
        return False
    except OSError as exc:
        print(f"ADB could not start: {exc}", file=sys.stderr)
        return False

    if not adb_is_device(target):
        return False

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(str(port), encoding="ascii")
    print("", flush=True)
    print("==============================================", flush=True)
    print(" REMOTE ADB RECOVERED", flush=True)
    print("==============================================", flush=True)
    print(f"Endpoint : {target}", flush=True)
    print(f"Saved    : {CACHE}", flush=True)
    print("No ADB reset/disconnect was performed.", flush=True)
    return True


def main() -> int:
    print("", flush=True)
    print("==============================================", flush=True)
    print(" ANDROIDBRIDGE REMOTE ADB RECOVERY", flush=True)
    print("==============================================", flush=True)
    print(f"Phone     : {PHONE_IP}", flush=True)
    print(f"Port range: {PORT_FIRST}-{PORT_LAST}", flush=True)
    print("Route     : Tailscale", flush=True)
    print("", flush=True)

    # If a previous endpoint is still alive, reuse it immediately.
    if CACHE.exists():
        try:
            cached = int(CACHE.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            cached = 0
        if PORT_FIRST <= cached <= PORT_LAST and try_adb_port(cached):
            return 0

    started = time.monotonic()
    open_ports: list[int] = []
    ports = range(PORT_FIRST, PORT_LAST + 1)

    print("[AndroidBridge] Finding the phone's current Wireless Debugging port...", flush=True)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for found in pool.map(tcp_open, ports, chunksize=32):
                if found is not None:
                    open_ports.append(found)
                    print(f"[AndroidBridge] Open candidate: {PHONE_IP}:{found}", flush=True)
    except KeyboardInterrupt:
        print("\nRecovery cancelled.", flush=True)
        return 130

    elapsed = time.monotonic() - started
    print(f"[AndroidBridge] Scan complete in {elapsed:.1f}s; {len(open_ports)} open candidate(s).", flush=True)

    for port in open_ports:
        if try_adb_port(port):
            return 0

    print("", flush=True)
    print("REMOTE ADB PORT NOT FOUND.", flush=True)
    print("Tailscale may be reachable while Wireless Debugging itself is off,", flush=True)
    print("or Samsung may be using an ephemeral range outside the normal range.", flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
