PHONEHUB SMART SETUP GUIDE
Version: Android Service Mode v1

WHAT PHONEHUB DOES
PhoneHub lets a Windows PC connect to your Android phone through Tailscale.

PhoneHub now has two connection paths:

PRIMARY PATH - PHONEHUB ANDROID SERVICE
Windows PhoneHub -> Tailscale -> PhoneHub Android app background service on port 8765

This is the new normal mode.
USB cable is not required after setup.
USB debugging is not required for supported PhoneHub-service commands.
The phone must keep Tailscale ON.
The PhoneHub Android app must have its background service enabled.

FALLBACK PATH - ADB / SCRCPY
Windows PhoneHub -> Tailscale -> ADB on port 5555 -> scrcpy and legacy tools

This is the older emergency fallback mode.
Use it only from the explicit Use ADB Fallback button.

MOBILE REQUIREMENT FOR NEW MODE
1. Install Tailscale on the phone.
2. Login to the same tailnet as the PC.
3. Turn Tailscale ON.
4. Install the PhoneHub Android app.
5. Open PhoneHub Android app once.
6. Enable PhoneHub service.
7. Confirm the persistent PhoneHub notification is visible.
8. Generate the six-digit pairing code.
9. Enter that code on the Windows PhoneHub app.

NORMAL DAILY USE
1. Keep Tailscale ON on PC.
2. Keep Tailscale ON on phone.
3. Keep PhoneHub Android service enabled.
4. Open C:\PhoneHub\PhoneHub.bat on Windows.
5. PhoneHub checks the Android service first on port 8765.
6. If paired and reachable, it uses PhoneHub Service mode.
7. If service is not paired, it shows Android app not paired.
8. Use ADB Fallback only when needed.

WHAT SHOULD SHOW ON WINDOWS
When new mode works:
Connection: PhoneHub Service
PhoneHub Android Service: Connected
ADB Status: Fallback only

When pairing is missing:
Android app not paired
Generate a code on the phone and pair the PC.

SCREEN SHARING RULE
Screen sharing still needs Android approval.
The PC may request screen sharing, but it cannot bypass Android MediaProjection permission.
On the phone, tap Approve PC Screen Request, then approve the Android screen-sharing prompt.

WHAT TAILSCALE DOES
Tailscale creates the private route between PC and phone.
It gives the phone a private 100.x.x.x IP.
PhoneHub uses that IP to reach the Android service on port 8765.

WHAT PHONEHUB ANDROID SERVICE DOES
The Android app is the main backend aeroplane.
It runs as a foreground service.
It shows a persistent notification.
It accepts only authenticated commands from the paired PC.
It rejects unknown clients, bad signatures, and replayed requests.

WHAT ADB DOES NOW
ADB is no longer the primary path for supported service commands.
ADB remains useful for legacy screen/camera/scrcpy tools while migration continues.
ADB uses port 5555.
PhoneHub uses ADB only when you choose Use ADB Fallback.

SAFETY RULES
PhoneHub does not hide its background service.
PhoneHub does not bypass Android lock screen.
PhoneHub does not silently start screen recording.
PhoneHub does not store your phone PIN, password, pattern, or fingerprint.
PhoneHub does not make the device impossible for the rightful owner to control.

TROUBLESHOOTING

PhoneHub Service offline:
- Check Tailscale ON on phone.
- Check Tailscale ON on PC.
- Open PhoneHub Android app.
- Confirm PhoneHub notification is visible.
- Check the phone Tailscale IP.

Android app not paired:
- Open PhoneHub Android app.
- Generate a six-digit pairing code.
- Enter the code in Windows PhoneHub.
- Pairing code expires after a short time, so generate a new one if needed.

Screen does not open:
- Confirm the phone shows Approve PC Screen Request.
- Approve the Android screen-sharing prompt.
- If denied, the core PhoneHub service still remains running.

Need old method:
- Click Use ADB Fallback.
- ADB fallback uses the phone Tailscale IP on port 5555.
- This requires remote ADB to be enabled.

FINAL STATUS
PhoneHub Android Service Mode is the new primary direction.
ADB/scrcpy remains as fallback until every feature is migrated to the Android backend.
