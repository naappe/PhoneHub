# AndroidBridge Project State

Last updated: 2026-10-06

## Source of truth

Repository: naappe/PhoneHub

PC working copy:
- C:\AndroidBridge-Lite
- Runtime: C:\AndroidBridge-Lite\pc\AndroidBridge-Lite.py
- Data viewer: C:\AndroidBridge-Lite\pc\AndroidBridge-PhoneData.py
- Launcher: C:\AndroidBridge-Lite\AndroidBridge-Lite.bat

The launcher pulls GitHub, restores the canonical tracked runtime files, verifies both Python files with py_compile, prints the current Git commit, then starts AndroidBridge.

## Remote phone

- Samsung SM-S938B / S25 Ultra
- Android 16
- Tailscale host: jennys-s25-ultra
- ADB serial: 100.127.244.20:5555
- PC Tailscale IP used by Offline GPS receiver: 100.113.209.27

Do not run adb disconnect or adb kill-server as routine recovery. The remote ADB route is valuable state and should be preserved.

## Working media profiles

Screen:
- stock scrcpy 4.1
- max-size 800
- max-fps 20
- H.264 1M
- no audio

Back camera:
- camera id 0
- max-size 640
- 16:9
- 15 fps
- H.264 450K
- no audio

Front camera:
- camera id 1
- same remote profile as back camera

Audio:
- separate scrcpy microphone session
- mic-voice-recognition
- Opus 128K
- 20 ms target buffer
- named pipe to FFplay
- wind/speech EQ
- adjustable 0..+20 dB gain, default +14 dB
- direct scrcpy fallback if enhanced playback cannot start

## Important startup architecture

scrcpy 4.1 pushes /data/local/tmp/scrcpy-server.jar on every client startup. Screen, Camera and Audio therefore share one startup gate.

Rules:
1. Never allow two scrcpy-server adb pushes to run concurrently.
2. Hold the startup gate until the starting scrcpy client's own push is finished.
3. After the push completes, multiple scrcpy clients may coexist; scrcpy assigns separate SCIDs/sockets.
4. STOP/AUDIO OFF/app shutdown must terminate the tracked scrcpy process and its still-running adb push child.
5. Never reset the ADB server merely to recover a media launch.

This architecture was added after PowerShell diagnostics showed multiple abandoned adb push processes were the cause of AUDIO STARTING stalls.

## Confirmed milestones

- Manual stock scrcpy rear camera succeeded against 100.127.244.20:5555.
- Direct media launch architecture restored working Screen/Camera.
- Audio monitor reached AUDIO ON / WIND CUT + VOICE.
- Stale scrcpy-server child uploads were identified and cleanup added.
- Unified media startup gate added so Screen/Camera/Audio cannot collide during server upload.

## Offline GPS / Companion

Android Companion package: com.androidbridge.calls

Offline GPS design:
- GNSS fixes are stored locally when offline.
- Pending records sync to PC when the network/Tailscale path returns.
- PC receiver port: TCP 5571.
- Location permission and background permission were previously granted.
- Do not confuse transport ACK tests with a confirmed fresh GNSS fix.

## Night vision

Normal rear camera is proven.
Torch mode uses the visible Samsung LED.
Camera2 Low Light Boost reported unsupported on the tested rear camera; do not repeatedly force it.
Custom low-light server files remain in pc/ for diagnostics.

## Recovery principle

GitHub is the permanent project source of truth. A new ChatGPT conversation should read this file and the latest source before making changes. Do not reconstruct AndroidBridge from chat memory when the repository is available.


## 2026-10-06 media repair checkpoint

After Audio reached AUDIO ON, Screen/Camera stopped launching reliably. The media startup code was consolidated again:
- one shared scrcpy startup gate now covers Screen, Back Camera, Front Camera and Audio;
- each client holds the gate until its own adb push child is finished;
- STOP now reaps a still-running video adb push child;
- Audio holds the same gate through its own server upload;
- the launcher removes only abandoned AndroidBridge startup pushes, never the ADB server;
- the launcher runs py_compile before starting the app.

This revision is a repair checkpoint and Screen/Camera should be validated after the PC pulls main. Do not label it fully verified until that test succeeds.


## Verification update: Screen

PC launcher successfully pulled and verified GitHub revision 89f5a71. The user then tested SCREEN and confirmed that screen mirroring works.

Observed startup latency: approximately 60 seconds before the scrcpy screen window becomes usable. Functionality is restored, but startup latency remains an optimization target. Do not trade the now-working remote media path for an unverified fast-start mechanism.

Next verification sequence: STOP -> BACK CAMERA -> STOP -> FRONT CAMERA -> STOP -> Audio.
