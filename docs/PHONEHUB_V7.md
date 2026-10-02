# PhoneHub V7

PhoneHub V7 uses a direct encrypted local-network connection between the Windows PC and the Android Samsung Secure companion.

## Current transport

- Discovery: Android UDP heartbeat on port 47321.
- Commands: direct PC-to-phone TCP on port 47322.
- Security: one-time paired key, HMAC-SHA256 command authentication, AES-256-GCM payload encryption.
- Screen: Android Accessibility screenshot snapshots sent through the encrypted local command channel.
- Camera: existing WebRTC camera path remains experimental and is separate from the core connection.
- Recovery: Android foreground CompanionService plus BootReceiver and WorkManager recovery.
- USB/ADB: installation and one-time enrollment only.

There is no cloud relay or VPN transport in the V7 runtime. The phone and PC must be reachable on the same Wi-Fi/LAN for normal control.

## Development order

Keep the working connection layer small and stable:

1. Pair.
2. Discover on LAN.
3. PING/PONG.
4. Device status.
5. Screen snapshots.
6. Policies/files/notifications.
7. Camera separately.

Do not redesign working screen, policy, or enrollment code while debugging a separate transport feature.
