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
        self._terminal_error = False

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

        self._terminal_error = False
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
            answer = await asyncio.to_thread(self.server.webrtc_offer, device, local.sdp)
            if generation != self._generation:
                await pc.close()
                return
            if answer.get("type") != "webrtc_answer":
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
