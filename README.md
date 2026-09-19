# PhoneHub 5

Clean Windows control center for the owner's Android phone.

## Finished MVP
- Tailscale + ADB device connection
- explicit connection state
- model / Android / battery status
- one exclusive scrcpy media-session owner
- screen control
- front/back camera
- screenshots to Pictures/PhoneHub
- read-only diagnostics
- screen quality/FPS settings
- clean shutdown and unit tests

Run `RUN_PHONEHUB.bat`.

Requirements: Python 3.12+, PySide6, adb and scrcpy available in Windows PATH.

The pre-rebuild project is preserved on branch `legacy-before-fresh-rebuild-2026-09-19`.
