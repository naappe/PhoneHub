PHONEHUB USER GUIDE
Version: v3.2

OVERVIEW
PhoneHub connects a Windows PC to an Android phone using Tailscale + ADB.

CURRENT CORE FEATURES
- Guided first-time setup
- Automatic Tailscale IP detection
- Remote ADB connection
- Screen mirroring/control through scrcpy
- Independent front/back camera window
- Screenshot capture
- Installed-app list
- Basic safe controls: reconnect, wake, lock, reboot
- Live connection status card

FIRST-TIME SETUP
1. Keep Tailscale installed and connected on the PC.
2. Enable Developer Options and USB Debugging on the phone.
3. Connect the phone by USB.
4. Open C:\PhoneHub\PhoneHub.bat.
5. Open Setup.
6. Follow the guided setup one step at a time.
7. Approve USB debugging on the phone if Android asks.
8. PhoneHub detects Tailscale and the phone's 100.x.x.x address.
9. Enable remote ADB when prompted.
10. Finish when PhoneHub reports the remote connection is ready.

DAILY USE
1. Keep Tailscale ON on PC and phone.
2. Start C:\PhoneHub\PhoneHub.bat.
3. PhoneHub reconnects using the saved phone Tailscale IP.
4. USB is only needed for initial setup or repair if remote ADB is no longer available.

CONTROL STATUS
The Control page shows:
- Phone Online / Offline
- ADB Connected / Not connected
- Tailscale IP
- USB Connected / Not connected
- Last control action

SCREEN
- Wake + Open Screen: normal daily view
- Fast Screen: lower bandwidth
- Ultra Screen: minimum bandwidth
- Screenshot: saves a phone screenshot
- Lock State Test: diagnostic only

CAMERA
- Back Camera and Front Camera are separate from the normal screen window.
- Switching front/back replaces only the camera stream.
- Closing the camera does not close the screen.

FILES
Screenshots are stored under:
C:\PhoneHub\runtime\screenshots

SETUP / REPAIR
PhoneHub Setup is maintained separately from the working PhoneHub application.
Use the setup/repair utility for Platform-Tools, scrcpy, USB debugging, Tailscale, or remote ADB problems.

CLEAN ARCHITECTURE
The current PhoneHub no longer uses the old QR companion, web viewer, location receiver, control-center prototype, or legacy setup scripts.

IMPORTANT
PhoneHub does not store your PIN/password and does not bypass Android security.
Tailscale authentication and Android security approval remain user-controlled.
