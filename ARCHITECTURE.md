# AndroidBridge Runtime Architecture

## Goal

Provide reliable remote Screen, Camera, microphone audio, phone data and offline-location access to the user's own Samsung phone over the existing Tailscale + ADB route.

## Process model

AndroidBridge Lite (Tkinter)
|
|-- Screen scrcpy process
|-- Camera scrcpy process
|-- Audio scrcpy process
|    \-- adb push child during startup
|    \-- Windows named pipe -> FFplay DSP
|
|-- PhoneData viewer
\-- Offline GPS TCP receiver

Screen/Camera and Audio have separate user controls. VIDEO STOP does not turn Audio off. AUDIO OFF does not stop Screen/Camera.

## scrcpy startup invariant

Every stock scrcpy client first pushes the same device-side file:
  /data/local/tmp/scrcpy-server.jar

The remote route can make that push slow. Concurrent pushes to the same target created stalls and abandoned child processes.

AndroidBridge therefore serializes the server-upload phase with one shared startup lock. A media client may run concurrently only after its server upload is complete.

scrcpy itself supports multiple simultaneous instances on one device using distinct SCIDs/socket names; the collision being prevented here is the shared server-file upload phase, not the later media sockets.

## UI threading

Tkinter stays on the main thread.
Remote/media operations run in worker threads.
Worker UI changes are sent through ui_queue.
Do not put long ADB, scrcpy or Tailscale operations directly in Tk button callbacks.

## Connection policy

Preferred remote serial:
  100.127.244.20:5555

Media launch uses the configured/active route directly rather than repeatedly disconnecting/reconnecting ADB.

Forbidden routine recovery:
- adb disconnect
- adb kill-server

Those commands may destroy the unattended remote path.

## Canonical files

- pc/AndroidBridge-Lite.py
- pc/AndroidBridge-PhoneData.py
- AndroidBridge-Lite.bat
- pc/scrcpy-server-v4.1-llb
- pc/scrcpy-server-v4.1-llb.sha256
- tools/nightvision/patch_scrcpy_llb.py
- tools/offline-location/prepare_offline_gps.py
- PREPARE-OFFLINE-GPS.ps1

Old ADB proxy/chunker architectures are retired and must not be reintroduced unless new evidence requires them.
