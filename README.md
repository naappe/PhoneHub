# PhoneHub

PhoneHub connects a Windows PC to an Android phone over a private Tailscale route.

## Current direction

PhoneHub now supports two connection paths:

```text
Primary path:
Windows PhoneHub
→ Tailscale
→ PhoneHub Android background service on port 8765
→ authenticated commands
```

```text
Fallback path:
Windows PhoneHub
→ Tailscale
→ ADB on port 5555
→ scrcpy / legacy ADB tools
```

The Android service path is the preferred normal-use path. ADB remains available only as an explicit fallback while the Android backend matures.

## PhoneHub Android service mode

The Android companion app runs a transparent foreground service. Android shows a persistent PhoneHub notification while the backend service is active.

The service provides:

- secure six-digit first pairing
- paired-PC authentication
- replay-resistant signed commands
- `ping` and `device_status` commands over port `8765`
- safe screen-request flow that still requires Android screen-sharing approval
- boot/recovery support where Android allows it

Normal service-mode use:

```text
PC PhoneHub -> Tailscale -> PhoneHub Android service
USB cable: not required
USB debugging: not required for supported PhoneHub-service functions
ADB: legacy fallback only
Screen sharing: Android consent required when starting a new MediaProjection session
```

## Safety boundary

PhoneHub must not hide its background activity. The Android service must remain visible through its foreground-service notification.

PhoneHub must not bypass Android lock screen, MediaProjection consent, Accessibility permission, or device-owner controls. Screen sharing starts only after the phone user approves the Android MediaProjection prompt.

## Desktop behavior

The Windows app checks the PhoneHub Android service first. When service credentials exist and the phone service is reachable on `<phone-tailscale-ip>:8765`, the dashboard shows `Connection: PhoneHub Service`.

When the Android service is not paired, the dashboard shows `Android app not paired`.

ADB is not started silently in the successful Android-service path. Use the explicit `Use ADB Fallback` action for the older `:5555`/scrcpy route.

## Development branch

The Android service milestone is developed on:

```text
feature/android-background-service-v1
```

Do not merge this branch into `main` until Android tests, desktop tests, APK build, and manual phone validation are complete.
