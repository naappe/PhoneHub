#!/usr/bin/env python3
"""Read-only Samsung Secure BridgeService status receiver (no commands sent).

Peer IP is only a network filter, NOT authentication. Any received data
is unverified. Never use this listener to authorize camera/screen commands.
"""
import argparse
import ipaddress
import json
import socket
import sys
import threading

DEFAULT_BIND = "100.113.209.27"
DEFAULT_PHONE = "100.127.244.20"
DEFAULT_PORT = 5570
FIELDS = {"STATUS", "MODEL", "ANDROID", "BATTERY", "NETWORK", "TIME", "READY"}


def collect_status(conn, stop, report, max_line=1024):
    conn.settimeout(1.0)
    data = bytearray()
    fields = {}
    accepted = False
    while not stop.is_set():
        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            continue
        except OSError:
            break
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > 65536:
            report({"state": "rejected", "reason": "excessive_buffer"})
            return
        while b"\n" in data:
            raw, _, tail = data.partition(b"\n")
            data = bytearray(tail)
            if len(raw) > max_line:
                report({"state": "rejected", "reason": "oversize_line"})
                return
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            if not accepted:
                if line != "ANDROIDBRIDGE":
                    report({"state": "rejected", "reason": "unexpected_protocol"})
                    return
                accepted = True
                continue
            if line == "---":
                if fields:
                    report({"state": "heartbeat", "verified": False, "fields": dict(fields)})
                fields.clear()
            elif "=" in line:
                key, value = line.split("=", 1)
                # Deliberately omit DEVICE_ID and all other sensitive payloads.
                if key in FIELDS:
                    fields[key] = value[:120]
            elif line == "ANDROIDBRIDGE":
                fields.clear()
    report({"state": "disconnected"})


def serve(bind=DEFAULT_BIND, phone=DEFAULT_PHONE, port=DEFAULT_PORT,
          stop=None, report=None):
    ipaddress.IPv4Address(bind)
    ipaddress.IPv4Address(phone)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid TCP port")
    if stop is None:
        stop = threading.Event()
    if report is None:
        report = lambda msg: print(json.dumps(msg, ensure_ascii=True), flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((bind, port))
        listener.listen(4)
        listener.settimeout(1.0)
        report({"state": "listening", "bind": bind, "port": port, "expected_peer": phone})
        while not stop.is_set():
            try:
                conn, peer = listener.accept()
            except socket.timeout:
                continue
            with conn:
                if peer[0] != phone:
                    report({"state": "ignored_peer", "peer": peer[0]})
                    continue
                report({"state": "connected", "verified": False, "peer": peer[0]})
                collect_status(conn, stop, report)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bind", default=DEFAULT_BIND)
    p.add_argument("--phone", default=DEFAULT_PHONE)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    a = p.parse_args(argv)
    try:
        serve(a.bind, a.phone, a.port)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
    except (OSError, ValueError) as exc:
        print(f"Receiver could not start: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
