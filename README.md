# AndroidBridge Lite

Canonical Windows controller for the owner's Samsung phone.

## Run

```powershell
cd C:\AndroidBridge-Lite
.\AndroidBridge-Lite.bat
```

The launcher updates the repository, restores the canonical runtime files, removes known obsolete generated helpers/caches, verifies Python/ADB/scrcpy, and starts the app.

## Active runtime

```text
AndroidBridge-Lite.bat
pc/
  AndroidBridge-Lite.py
  AndroidBridge-PhoneData.py
  scrcpy-server-v4.1-llb
  scrcpy-server-v4.1-llb.sha256
```

Screen, Back Camera and Front Camera use stock `scrcpy` + stock `adb` directly.

Audio is deliberately separate from video and uses the restored known-good low-latency profile:

```text
Samsung microphone
  -> scrcpy audio-only (mic-voice-recognition)
  -> Opus 96K
  -> 20 ms audio buffer
  -> direct PC playback
```

There is no FFplay relay, named pipe or additional DSP in the normal audio path. Those extra stages were removed because they added buffering/latency.

The custom scrcpy server is reserved for Night Vision Boost.

## Preserved support tools

- `PREPARE-OFFLINE-GPS.ps1` and `tools/offline-location/` — Companion offline GPS/history preparation.
- `tools/nightvision/` and `.github/workflows/build-nightvision-server.yml` — Night Vision Boost server source/build.

## Rules

- Do not add alternate AndroidBridge launchers or numbered copies.
- Do not add ADB proxy/chunk-transfer helpers to the normal media path.
- Keep audio as its own direct audio-only scrcpy process; do not merge it into Screen/Camera playback or add relay/DSP buffering.
- Do not run `adb disconnect` or `adb kill-server` from AndroidBridge.
- Keep generated logs, caches and local location-history files out of Git.
