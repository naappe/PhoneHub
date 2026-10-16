#!/usr/bin/env python3
"""Read-only Samsung Secure relay reachability probe.

This is NOT a remote-control server. It never reads application payloads,
dispatches commands, or changes ADB/Tailscale/phone settings.
"""
import argparse
import ipaddress
import socket
import sys
import time

DEFAULT_PC_IP = "100.113.209.27"
EXPECTED_PHONE_IP = "100.127.244.20"
PORT = 5570


def run_probe(bind_ip=DEFAULT_PC_IP, expected_ip=EXPECTED_PHONE_IP,
              duration=120, port=PORT, output=print):
    """Listen for connections from the configured phone, without reading data."""
    ipaddress.ip_address(bind_ip)
    ipaddress.ip_address(expected_ip)
    if not (0 < duration <= 3600):
        raise ValueError("duration must be 1-3600 seconds")
    if not (1 <= port <= 65535):
        raise ValueError("invalid TCP port")

    deadline = time.monotonic() + duration
    hits = 0
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((bind_ip, port))
        server.listen(4)
        output(f"Listening on {bind_ip}:{port} for up to {duration}s")
        output(f"Expected phone: {expected_ip}; no commands or data are exchanged")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            server.settimeout(min(remaining, 1.0))
            try:
                client, address = server.accept()
            except socket.timeout:
                continue
            with client:
                address_ip = address[0]
                if address_ip == expected_ip:
                    hits += 1
                    output(f"PHONE_CONNECTION from {address_ip} at {time.strftime('%H:%M:%S')}")
                else:
                    output(f"IGNORED_CONNECTION from unexpected peer {address_ip}")
                # Do not interact with unknown or unauthenticated relay commands.
    output(f"Probe finished: {hits} connection(s) from expected phone")
    return hits


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default=DEFAULT_PC_IP,
                        help="Windows Tailscale IPv4 to bind (default: configured PC IP)")
    parser.add_argument("--phone", default=EXPECTED_PHONE_IP,
                        help="Expected Samsung Tailscale IPv4")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args(argv)
    try:
        run_probe(args.bind, args.phone, args.seconds, args.port)
    except (OSError, ValueError) as exc:
        print(f"Probe cannot start: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by operator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
