# PhoneHub

PhoneHub is a Windows control hub for an Android phone using **Tailscale + ADB/scrcpy**.

## Core scope

- Remote Android screen mirroring and control
- Front and back camera viewing
- Screenshot capture
- File/backend protection and diagnostics
- Remote ADB over the private Tailscale network
- One-click daily launcher
- Safe update behavior from GitHub

## Network

Tailscale is the only remote network layer kept in the project. Experimental custom VPN/WireGuard/USB-web transport work is removed from the main project.

## Daily use

1. Keep Tailscale connected on the PC and phone.
2. Run `C:\PhoneHub\PhoneHub.bat`.
3. PhoneHub reconnects to the saved phone Tailscale address.

USB is only needed for initial Android debugging authorization or repair.

## First setup / repair

Run:

```
C:\PhoneHub\SETUP_PHONEHUB.bat
```

It checks Tailscale, ADB and the bundled scrcpy runtime.

## Cleanup

Run this from PowerShell if old experimental folders are still on the PC:

```powershell
powershell -ExecutionPolicy Bypass -File C:\PhoneHub\scripts\CLEAN_PHONEHUB.ps1
```

Cleanup archives experiments instead of deleting them immediately.

## Kept architecture

```
Phone
  └─ Tailscale
      └─ remote ADB
          ├─ screen/control via scrcpy
          ├─ front/back camera
          └─ PhoneHub backend

PC
  └─ C:\PhoneHub
      ├─ app
      ├─ runtime
      ├─ scripts
      ├─ assets/data/docs
      ├─ tests
      └─ PhoneHub.bat
```
