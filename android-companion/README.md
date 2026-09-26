# PhoneHub Companion

Android-side component for PhoneHub 7.

This directory is intentionally isolated from the working PhoneHub 6.3 desktop application.

Planned baseline:
- start/recover after reboot using Android-supported lifecycle APIs
- persistent foreground service for active connectivity
- authenticated pairing with the desktop
- LAN discovery and reconnect
- camera access only after Android runtime permission is granted
- no hidden permission bypasses or silent security-setting changes

The first milestone is connection/heartbeat only. Camera and control are layered on after transport stability is proven.
