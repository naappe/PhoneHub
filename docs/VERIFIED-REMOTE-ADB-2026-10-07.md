# AndroidBridge Remote ADB Milestone — 2026-10-07

## Status

Verified working end-to-end after a real Samsung reboot and again with the PC and phone on different Internet connections.

### Verified route

```text
Samsung phone
  -> Tailscale auto-start
  -> Samsung Secure restores Wireless Debugging
  -> Android allocates a dynamic secure ADB TLS port
  -> Tailscale IP 100.127.244.20:<dynamic-port>
  -> authenticated ADB
  -> AndroidBridge Lite
  -> scrcpy screen/control
```

## Reboot verification

Pre-reboot boot ID:

```text
ea97bbe9-2549-4473-abdf-da6beea47f3a
```

Post-reboot boot ID:

```text
d4134e25-ea0a-4319-bd16-ac4e2a8f6da9
```

This proves a real reboot occurred.

Before reboot, Wireless Debugging advertised TLS port `35195`.

After reboot, Android advertised a new TLS port:

```text
adb-R5CY20RCX8E-7DcX1T  _adb-tls-connect._tcp  192.168.100.91:45841
```

The new listener was successfully reached through the phone's Tailscale IP:

```text
100.127.244.20:45841   device
```

Remote-only checks returned:

```text
adb get-state        -> device
ro.product.model     -> SM-S938B
boot_id              -> d4134e25-ea0a-4319-bd16-ac4e2a8f6da9
```

USB was not required for the working remote route.

## Cross-network verification

AndroidBridge was subsequently verified while the PC and Samsung were on different Internet connections.

AndroidBridge UI showed:

```text
PHONE CONNECTED
TAILSCALE - REMOTE
100.127.244.20:45841
```

scrcpy displayed the Samsung screen through the same remote route.

## Persistent Wireless Debugging

One-time setup script:

```text
tools/ENABLE-PERSISTENT-WIRELESS-ADB.ps1
```

Verified setup state:

```text
adb_wifi_enabled: 1
WRITE_SECURE_SETTINGS: GRANTED
```

The Samsung Secure boot receiver restores `adb_wifi_enabled=1` after reboot. Tailscale remains configured as Android's always-on VPN provider with lockdown disabled.

## PC controller update

`pc/AndroidBridge-Lite.py` no longer assumes legacy ADB port `:5555`.

The controller now:

- preserves USB -> local Wi-Fi -> Tailscale routing priority;
- discovers the current `_adb-tls-connect._tcp` port when mDNS is available;
- caches the learned TLS port;
- reuses an existing healthy Tailscale ADB transport;
- does not run `adb disconnect`, `adb kill-server`, or reset pairing;
- preserves the existing scrcpy screen/camera/audio profiles.

Relevant controller commits:

```text
1ac7022  Use dynamic secure ADB TLS port after phone reboot
670f833  Keep dynamic ADB status paths non-blocking
```

## Android Wireless Debugging notification

When a remote ADB host is actively connected, Android displays the system notification:

```text
Wireless debugging connected
Tap to turn off wireless debugging
```

This is an Android system security indicator, not a Samsung Secure notification. The current build does not attempt to suppress or bypass it.

## Remaining engineering item

The remote transport itself is proven across different Internet connections.

For fully automatic recovery after a future phone reboot while the PC and phone are on different networks, AndroidBridge still needs an out-of-band way to learn the newly randomized Wireless Debugging TLS port when local mDNS is unavailable. The intended direction is to publish the current TLS port through the existing Samsung Secure / BridgeService path rather than hard-code a port.

Do not regress to classic `adb tcpip 5555`.
