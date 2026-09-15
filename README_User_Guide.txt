PHONEHUB SMART SETUP GUIDE
Version: v2.2-smart-setup

WHAT PHONEHUB DOES
PhoneHub lets the PC connect to your Android phone through Tailscale and ADB.
You can open phone screen, camera, screenshot, apps list, and basic control.

MOBILE REQUIREMENT
Only Tailscale is needed on the mobile.
No PhoneHub Companion app is required.

FIRST-TIME SETUP
1. Install Tailscale on phone.
2. Login with the same Tailscale account/tailnet as the PC.
3. Turn Tailscale ON.
4. Enable Developer Options on phone.
5. Enable USB Debugging.
6. Connect USB cable once.
7. Tap Always allow from this computer.
8. Open PhoneHub.
9. Open Setup New Phone.
10. Click Smart Check.
11. Click Enable Remote.
12. Enter phone Tailscale IP.
13. Click Save IP + Test.
14. When PhoneHub says READY, remove USB cable.

DAILY USE
1. Keep Tailscale ON on PC.
2. Keep Tailscale ON on phone.
3. Open C:\PhoneHub\PhoneHub.bat.
4. Use Dashboard, Screen, Camera, Screenshot, Apps, and Control.

BUTTON GUIDE

Dashboard:
Shows phone online/offline status, Android version, battery, and saved connection.

Setup New Phone:
Checks USB Debugging, Tailscale, phone IP, remote ADB, and tells when USB can be removed.

Smart Check:
Checks what is ready and what is missing.

Open Tailscale:
Opens Tailscale on the phone so you can copy the 100.x.x.x phone IP.

Enable Remote:
Uses the USB connection one time to enable remote ADB.

Save IP + Test:
Saves the phone Tailscale IP and tests remote connection.

Finish Setup:
Confirms whether USB cable can be removed.

Screen:
Opens the phone screen through scrcpy.

Camera:
Opens separate back/front camera window.

Screenshot:
Saves phone screenshot to:
C:\PhoneHub\runtime\screenshots

Files:
Opens screenshot folder and location log.

Apps:
Shows installed phone apps.

Control:
Reconnects ADB, wakes phone, locks phone, or reboots phone.

WHEN USB CAN BE REMOVED
Only remove USB when PhoneHub says:
READY
or
Remote ADB connected
or
USB cable can be removed

WHAT TAILSCALE DOES
Tailscale connects PC and phone privately.
It gives the phone a private 100.x.x.x IP.
It allows PhoneHub to reach the phone remotely.

WHAT TAILSCALE CANNOT DO
Tailscale alone cannot give live GPS.
Tailscale alone cannot approve Android permissions.
Tailscale alone cannot unlock the phone.

TROUBLESHOOTING

Phone offline:
- Check Tailscale ON on PC.
- Check Tailscale ON on phone.
- Open Setup New Phone.
- Click Smart Check.

USB debugging not approved:
- Look at phone screen.
- Tap Always allow from this computer.
- Tap OK.

Remote not connected:
- Check phone Tailscale IP.
- Click Enable Remote while USB is connected.
- Click Save IP + Test.

Screen slow:
- Use Fast Screen or Ultra Screen.
- Readable Screen is clearer but heavier.

Camera not opening:
- Close Screen first.
- Click Back Camera again.
- Camera mode restarts scrcpy.

Live location not moving:
- Normal. Current clean version uses Tailscale only.
- Live GPS needs an extra Android location app, which is not used now.

FINAL STATUS
PhoneHub v2.2 is the stable Tailscale-only version.
