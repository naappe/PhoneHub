# PhoneHub V6 – Policy UI baseline

This project implements the approved PhoneHub structure:

Home → Apps → App Policy → Policies → Notifications → Settings

Per-app policy controls:
- Keep Installed
- Allow Usage
- Suspend App
- Show Notifications
- Forward to PhoneHub
- Protect from Changes
- Auto Apply on Sync

## Important
Suspend / uninstall-block / managed notification permission controls require PhoneHub to be Device Owner.

For a freshly reset test phone, provisioning from ADB is typically:

```powershell
adb shell dpm set-device-owner com.phonehub.notifier/.PhoneHubDeviceAdminReceiver
```

This only succeeds when Android allows Device Owner provisioning (normally on a freshly provisioned/reset device with no accounts blocking provisioning).

## Build
Open this folder in Android Studio, allow Gradle sync, then Build > Build APK(s).

Package: `com.phonehub.notifier`
Version: `6.0.0`
