from __future__ import annotations

import asyncio
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
    ):
        self.server = server
        self.on_frame = on_frame
        self.on_state = on_state
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="phonehub-webrtc", daemon=True)
        self._thread.start()
        self._pc: RTCPeerConnection | None = None
        self._generation = 0
        self._last_frame = 0.0

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def start(self, device):
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
                await asyncio.to_thread(self.server.webrtc_stop, device)
            except Exception:
                pass

    async def _connect(self, device, generation: int):
        await self._close()
        if generation != self._generation:
            return

        self.on_state("Negotiating direct WebRTC screen…")
        config = RTCConfiguration(
            iceServers=[
                RTCIceServer(urls="stun:stun.l.google.com:19302"),
                RTCIceServer(urls="stun:stun1.l.google.com:19302"),
            ]
        )
        pc = RTCPeerConnection(configuration=config)
        self._pc = pc
        pc.addTransceiver("video", direction="recvonly")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            state = pc.connectionState
            if generation != self._generation:
                return
            if state == "connected":
                self.on_state("LIVE • WebRTC encrypted peer-to-peer")
            elif state in ("failed", "closed", "disconnected"):
                self.on_state(f"WebRTC {state}")

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

            self.on_state("Sending encrypted WebRTC offer to phone…")
            answer = await asyncio.to_thread(self.server.webrtc_offer, device, local.sdp)
            if generation != self._generation:
                await pc.close()
                return
            if answer.get("type") != "webrtc_answer":
                raise RuntimeError(answer.get("message", "Phone did not return a WebRTC answer"))

            self.on_state("Connecting live media path…")
            await pc.setRemoteDescription(
                RTCSessionDescription(sdp=answer["sdp"], type="answer")
            )

            deadline = time.monotonic() + 20
            while generation == self._generation and pc.connectionState not in ("connected", "failed", "closed"):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "WebRTC direct path timed out. This network may require a TURN relay."
                    )
                await asyncio.sleep(0.25)
        except Exception as exc:
            if generation == self._generation:
                self.on_state(f"Live screen failed: {exc}")
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
                self.on_state(f"Screen stream ended: {exc}")
