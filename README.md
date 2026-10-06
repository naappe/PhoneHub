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

Audio is deliberately separate from video. The current locked profile restores loud speech while removing the old lag-heavy FFT/dynamic-normalizer stages:

```text
Samsung voice-recognition microphone
  -> scrcpy audio-only / Opus 128K / 20 ms buffer
  -> Windows named pipe
  -> lightweight FFplay DSP
  -> speech-band filter + presence EQ
  -> fixed +12 dB gain
  -> peak limiter
  -> PC speaker/headphones
```

Do not add `afftdn` or `dynaudnorm` to the normal audio path; those older processing stages increased latency.

The UI includes a `SOUND VOLUME` control from 0 to +20 dB (default +14 dB). The selected boost is applied when the audio stream starts; it does not alter or stop Screen/Camera.

The custom scrcpy server is reserved for Night Vision Boost.

## Preserved support tools

- `PREPARE-OFFLINE-GPS.ps1` and `tools/offline-location/` — Companion offline GPS/history preparation.
- `tools/nightvision/` and `.github/workflows/build-nightvision-server.yml` — Night Vision Boost server source/build.

## Rules

- Do not add alternate AndroidBridge launchers or numbered copies.
- Do not add ADB proxy/chunk-transfer helpers to the normal media path.
- Keep audio separate from Screen/Camera. Preserve the 20 ms capture buffer and lightweight fixed-gain DSP; do not restore the lag-heavy FFT/dynamic-normalizer chain.
- Do not run `adb disconnect` or `adb kill-server` from AndroidBridge.
- Keep generated logs, caches and local location-history files out of Git.
