from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Callable

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)


class WebRtcScreenClient:
    """Receives PhoneHub Companion's MediaProjection video over WebRTC."""

    def __init__(
        self,
        server,
        on_frame: Callable[[bytes, int, int], None],
        on_state: Callable[[str], None],
        mode: str = "screen",
    ):
        self.server = server
        self.on_frame = on_frame
        self.on_state = on_state
        self.mode = mode
        self._camera_lens = "back"
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="phonehub-webrtc", daemon=True)
        self._thread.start()
        self._pc: RTCPeerConnection | None = None
        self._generation = 0
        self._last_frame = 0.0
        self._terminal_error = False

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self, device, lens: str | None = None):
        if lens in ("front", "back"):
            self._camera_lens = lens
        self._generation += 1
        generation = self._generation
        asyncio.run_coroutine_threadsafe(self._connect(device, generation), self._loop)

    def stop(self, device=None):
        self._generation += 1
        asyncio.run_coroutine_threadsafe(self._close(device), self._loop)

    async def _close(self, device=None):
        pc, self._pc = self._pc, None
        if pc is not None:
            try:
                await pc.close()
            except Exception:
                pass
        if device is not None:
            try:
                if self.mode == "camera":
                    await asyncio.to_thread(self.server.camera_webrtc_stop, device)
                else:
                    await asyncio.to_thread(self.server.webrtc_stop, device)
            except Exception:
                pass

    async def _connect(self, device, generation: int):
        await self._close()
        if generation != self._generation:
            return

        self._terminal_error = False
        if self.mode == "screen":
            # Screen capture is explicitly started on the phone. Do not block
            # negotiation behind a second prepare/status round trip.
            self.on_state("Connecting to active Android screen share…")
        self.on_state("Negotiating direct WebRTC camera…" if self.mode == "camera" else "Negotiating direct WebRTC screen…")
        turn_urls = [u.strip() for u in os.environ.get("PHONEHUB_TURN_URLS", "").split(";") if u.strip()]
        turn_username = os.environ.get("PHONEHUB_TURN_USERNAME", "")
        turn_credential = os.environ.get("PHONEHUB_TURN_CREDENTIAL", "")
        ice_servers = [
            RTCIceServer(urls="stun:stun.l.google.com:19302"),
            RTCIceServer(urls="stun:stun1.l.google.com:19302"),
        ]
        if turn_urls:
            ice_servers.append(
                RTCIceServer(urls=turn_urls, username=turn_username, credential=turn_credential)
            )
            self.on_state(f"TURN enabled • {len(turn_urls)} relay endpoint(s)")
        config = RTCConfiguration(iceServers=ice_servers)
        pc = RTCPeerConnection(configuration=config)
        self._pc = pc
        pc.addTransceiver("video", direction="recvonly")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            state = pc.connectionState
            if generation != self._generation or self._terminal_error:
                return
            if state == "connected":
                self.on_state("LIVE • WebRTC encrypted peer-to-peer")
            elif state in ("failed", "disconnected"):
                self.on_state(f"WebRTC {state}")
            elif state == "closed":
                self.on_state("WebRTC closed")

        @pc.on("iceconnectionstatechange")
        async def on_iceconnectionstatechange():
            if generation != self._generation or self._terminal_error:
                return
            self.on_state(f"ICE {pc.iceConnectionState} • establishing live media…")

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                asyncio.create_task(self._consume_video(track, generation))

        try:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            if generation != self._generation:
                await pc.close()
                return

            local = pc.localDescription
            if local is None:
                raise RuntimeError("PC WebRTC offer was not created")
            pc_ice = self._ice_summary(local.sdp)

            self.on_state(f"Sending offer • PC ICE {pc_ice}")
            if self.mode == "camera":
                answer = await asyncio.to_thread(
                    self.server.camera_webrtc_offer, device, local.sdp, self._camera_lens,
                    turn_urls, turn_username, turn_credential
                )
            else:
                answer = await asyncio.to_thread(self.server.webrtc_offer, device, local.sdp)
            if generation != self._generation:
                await pc.close()
                return
            expected = "camera_webrtc_answer" if self.mode == "camera" else "webrtc_answer"
            if answer.get("type") != expected:
                raise RuntimeError(answer.get("message", "Phone did not return a WebRTC answer"))
            phone_ice = self._ice_summary(answer.get("sdp", ""))
            if phone_ice == "none":
                raise RuntimeError("Phone WebRTC answer contained no ICE candidates")

            self.on_state(f"ICE checking • PC {pc_ice} • Phone {phone_ice}")
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type="answer")
            )

            deadline = time.monotonic() + 20
            while generation == self._generation and pc.connectionState not in ("connected", "failed", "closed"):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"ICE timed out • PC {pc_ice} • Phone {phone_ice}"
                    )
                await asyncio.sleep(0.25)
        except Exception as exc:
            if generation == self._generation:
                self._terminal_error = True
                label = "camera" if self.mode == "camera" else "screen"
                self.on_state(f"Live {label} failed: {exc}")
            try:
                await pc.close()
            except Exception:
                pass
            if self._pc is pc:
                self._pc = None

    async def _consume_video(self, track, generation: int):
        frames = 0
        started = time.monotonic()
        try:
            while generation == self._generation:
                frame = await track.recv()
                array = frame.to_ndarray(format="rgb24")
                height, width = array.shape[:2]
                frames += 1
                now = time.monotonic()
                self._last_frame = now
                self.on_frame(array.tobytes(), width, height)
                if frames % 30 == 0:
                    elapsed = max(0.001, now - started)
                    self.on_state(f"LIVE • WebRTC • {frames / elapsed:.1f} FPS • {width}×{height}")
        except Exception as exc:
            if generation == self._generation:
                label = "Camera" if self.mode == "camera" else "Screen"
                self.on_state(f"{label} stream ended: {exc}")


    @staticmethod
    def _ice_summary(sdp: str) -> str:
        counts = {"host": 0, "srflx": 0, "relay": 0, "prflx": 0}
        for line in (sdp or "").splitlines():
            if not line.startswith("a=candidate:"):
                continue
            parts = line.split()
            try:
                kind = parts[parts.index("typ") + 1]
            except (ValueError, IndexError):
                kind = "other"
            if kind in counts:
                counts[kind] += 1
        shown = [f"{k}={v}" for k, v in counts.items() if v]
        return ",".join(shown) if shown else "none"
