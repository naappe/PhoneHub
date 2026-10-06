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

Audio is deliberately a separate clarity pipeline and must not be merged with the video session:

```text
Samsung microphone
  -> scrcpy audio-only capture (mic-voice-recognition)
  -> Windows named pipe (Opus)
  -> FFplay speech DSP
  -> high-pass / low-pass
  -> adaptive denoise
  -> noise gate
  -> speech-presence EQ
  -> dynamic distant-speech gain
  -> limiter
  -> PC speaker/headphones
```

The custom scrcpy server is reserved for Night Vision Boost.

## Preserved support tools

- `PREPARE-OFFLINE-GPS.ps1` and `tools/offline-location/` — Companion offline GPS/history preparation.
- `tools/nightvision/` and `.github/workflows/build-nightvision-server.yml` — Night Vision Boost server source/build.

## Rules

- Do not add alternate AndroidBridge launchers or numbered copies.
- Do not add ADB proxy/chunk-transfer helpers to the normal media path.
- Keep audio as its own audio-only capture + PC DSP pipeline; do not merge it into Screen/Camera playback.
- Do not run `adb disconnect` or `adb kill-server` from AndroidBridge.
- Keep generated logs, caches and local location-history files out of Git.
