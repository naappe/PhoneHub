from __future__ import annotations

import argparse
import json
import os
import subprocess
import urllib.parse
import urllib.request
import sys
import threading
import time

from phonehub_v7.companion_server import Companion, CompanionServer
from phonehub_v7.webrtc_stream import WebRtcScreenClient


def adb(serial: str, *args: str) -> None:
    subprocess.run(["adb", "-s", serial, *args], check=True)


def load_metered_turn() -> None:
    domain = os.environ.get("PHONEHUB_METERED_DOMAIN", "").strip().removeprefix("https://").rstrip("/")
    api_key = os.environ.get("PHONEHUB_METERED_API_KEY", "").strip()
    if not domain or not api_key:
        return
    url = f"https://{domain}/api/v1/turn/credentials?apiKey={urllib.parse.quote(api_key)}"
    with urllib.request.urlopen(url, timeout=15) as response:
        servers = json.loads(response.read().decode("utf-8"))
    turn_urls = []
    username = ""
    credential = ""
    for server in servers:
        urls = server.get("urls", [])
        if isinstance(urls, str):
            urls = [urls]
        for item in urls:
            if str(item).startswith("turn:") or str(item).startswith("turns:"):
                turn_urls.append(str(item))
                username = server.get("username", username)
                credential = server.get("credential", credential)
    if not turn_urls:
        raise RuntimeError("Metered returned no TURN relay endpoints")
    os.environ["PHONEHUB_TURN_URLS"] = ";".join(turn_urls)
    os.environ["PHONEHUB_TURN_USERNAME"] = username
    os.environ["PHONEHUB_TURN_CREDENTIAL"] = credential
    print(f"TURN: loaded {len(turn_urls)} relay endpoint(s) from Metered")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PhoneHub cross-network WebRTC camera test. ADB is used only for SDP signaling."
    )
    parser.add_argument("--serial", default="YLSOP75PFMQWIJDI")
    parser.add_argument("--lens", choices=("front", "back"), default="front")
    parser.add_argument("--seconds", type=int, default=35)
    args = parser.parse_args()

    load_metered_turn()
    print("TEST MODE: USB/ADB carries signaling only.")
    print("WebRTC camera media must travel over the PC network and the phone's active Internet network.")
    print("For a real cross-network test: phone Wi-Fi OFF, mobile data ON; PC stays on its normal network.")
    print()

    adb(args.serial, "forward", "tcp:47322", "tcp:47322")
    client = None
    try:
        server = CompanionServer()
        enrolled = server.enroll_address("127.0.0.1", 47322)
        device_id = str(enrolled["device_id"])
        device = Companion(device_id, enrolled.get("device_name", "Android"), "127.0.0.1", time.time(), 47322)

        done = threading.Event()
        frames = 0
        first_frame_at = None
        last_state = ""

        def on_state(state: str) -> None:
            nonlocal last_state
            last_state = state
            print("STATE:", state, flush=True)
            if state.startswith("Live camera failed:") or state.startswith("WebRTC failed"):
                done.set()

        def on_frame(_rgb: bytes, width: int, height: int) -> None:
            nonlocal frames, first_frame_at
            frames += 1
            if first_frame_at is None:
                first_frame_at = time.time()
                print(f"FIRST FRAME: {width}x{height}", flush=True)
                done.set()

        client = WebRtcScreenClient(server, on_frame, on_state, mode="camera")
        print(f"Starting {args.lens} camera WebRTC test for up to {args.seconds}s...")
        client.start(device, args.lens)
        done.wait(args.seconds)

        if frames:
            print()
            print("RESULT: DIRECT CROSS-NETWORK WEBRTC PASSED")
            print(f"Frames received: {frames}")
            print("STUN/P2P is sufficient for this tested network pair.")
            return 0

        print()
        print("RESULT: DIRECT CROSS-NETWORK WEBRTC DID NOT CONNECT")
        print("Last state:", last_state or "no WebRTC state")
        print("If both sides had srflx candidates and ICE timed out, this network pair likely needs TURN.")
        return 2
    finally:
        if client is not None:
            try:
                client.stop()
            except Exception:
                pass
        try:
            adb(args.serial, "forward", "--remove", "tcp:47322")
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
