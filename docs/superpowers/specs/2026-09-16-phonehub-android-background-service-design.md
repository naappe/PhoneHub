# PhoneHub Android Background Service Design

Date: 2026-09-16
Status: Proposed and approved in chat; awaiting written-spec review

## Goal

Replace ADB as the normal remote-control transport with a PhoneHub Android companion app that stays available in the background, reconnects automatically, and communicates with the PhoneHub PC app over the existing private network path. ADB remains only as an optional fallback during migration and troubleshooting.

The Android app must be implemented as a legitimate, user-visible background service. It must not hide its activity, bypass Android consent dialogs, or make itself impossible for the device owner to stop or remove.

## Existing Context

The current desktop app uses a saved Tailscale IP and connects to Android over ADB on port 5555. The existing experimental Android branch already contains a Kotlin app with MediaProjection screen sharing, WebRTC, Supabase Realtime signaling, and a foreground `ScreenShareService`.

The new Android backend should build on that existing Android code rather than starting over.

## Recommended Architecture

### 1. Persistent PhoneHub service

Add a dedicated `PhoneHubService` foreground service that represents the always-available PhoneHub backend. It starts after the user enables PhoneHub once, shows an ongoing notification, reconnects after recoverable failures, and returns `START_STICKY` where appropriate.

The service owns only long-lived connectivity and command routing. Screen capture remains in a separate MediaProjection service because Android applies special lifecycle and consent rules to screen capture.

### 2. Automatic restart and recovery

Add a `BOOT_COMPLETED` receiver. After reboot it schedules safe startup/recovery work using Android-supported background mechanisms. The app also uses `WorkManager` for retry/backoff when the foreground service cannot immediately restore connectivity.

The app should expose a clear status such as `Active`, `Waiting for network`, `Paired PC offline`, or `Permission required`.

### 3. Private transport

Use the existing Tailscale network as the private route when available. The PhoneHub Android service becomes the application-level endpoint that replaces ADB for normal use.

Logical flow:

`PhoneHub PC -> Tailscale/private network -> PhoneHub Android service -> Android APIs`

The design must not depend on ADB port 5555 after pairing and migration are complete.

### 4. Pairing and authentication

Do not trust network reachability alone. The Android app and PC must perform explicit pairing once and store a cryptographic shared trust relationship.

Minimum first-version security:
- one-time pairing code or QR initiated on the phone;
- per-device long-lived key material stored in Android Keystore on the phone;
- matching paired-PC credential stored locally on the PC;
- every command authenticated;
- unknown clients rejected;
- pairing can be revoked from the phone app.

No private key, admin password, or service-role key may be committed to GitHub.

### 5. Capability modules

Keep features isolated behind separate components so each can be enabled and tested independently:

- `CommandRouter`: validates an authenticated command and dispatches it.
- `ScreenShareService`: existing MediaProjection/WebRTC path; starts only after Android screen-share consent.
- `AccessibilityController`: optional remote tap/swipe/back/home actions after the user explicitly enables the Accessibility Service.
- `FileController`: Android Storage Access Framework / app-scoped storage operations within granted access.
- `NotificationBridge`: optional Notification Listener functionality after explicit user enablement.
- `DeviceInfoController`: battery, model, network state, app/service status.
- `RecoveryWorker`: retries background connection after transient failures.

The first implementation plan should prioritize the persistent service, pairing, command channel, device status, and screen request flow. File/control/notification modules should be added only after the base connection is stable.

## Android Permission Model

PhoneHub must follow Android's supported permission model.

### Foreground service

The persistent backend runs as a foreground service with an ongoing notification. The notification cannot be intentionally hidden.

### Screen sharing

MediaProjection remains user-consented. A PC request may prompt the phone user to approve capture. The system must not attempt to bypass the Android MediaProjection consent screen.

### Accessibility control

Remote taps/swipes require the user to explicitly enable the PhoneHub Accessibility Service in Android Settings. The app may guide the user to the correct settings page but must not silently enable it.

### File access

Access only files and folders permitted by Android APIs and user grants.

### Battery optimization

PhoneHub may guide the user to Android's battery-optimization settings to improve reliability, but it must not spoof system settings or claim an exemption it does not have.

## Uninstall / Protection Model

Default mode is a normal transparent app. It should be reliable but removable by the device owner.

For a deliberately managed device, PhoneHub may later support Android Device Owner mode. In that mode, Android's official device-policy APIs can apply stronger management policy, including uninstall restrictions where permitted. This is optional and must be clearly provisioned as managed-device functionality.

The app must not implement stealth uninstall resistance, hidden persistence, deceptive overlays, or mechanisms intended to prevent an authorized owner from regaining control.

## User Experience

### Initial setup

1. Install PhoneHub Android app.
2. Open it once.
3. Grant notification permission where required.
4. Enable the PhoneHub background service.
5. Pair the trusted PC using a one-time code or QR.
6. Optionally enable Accessibility and file/notification permissions.
7. Optionally follow the battery-optimization guidance.

After this initial setup, normal connection recovery should be automatic.

### Ongoing notification

Use a low-importance ongoing notification such as:

`PhoneHub - Active - Paired PC connected`

or

`PhoneHub - Active - Waiting for paired PC`

When screen sharing is active, show a distinct screen-sharing foreground notification.

## PC Application Changes

The desktop PhoneHub app remains the primary control UI and still stores the phone's Tailscale IP where useful. It gains a new PhoneHub-service connection path alongside the existing ADB fallback.

Migration sequence:

1. Prefer PhoneHub Android service if paired and reachable.
2. Show service state and supported capabilities.
3. Use ADB only when the user explicitly selects legacy/fallback mode.
4. Once the Android backend reaches feature parity for required functions, remove ADB from the normal startup path.

## Error Handling

- Network unavailable: stay active, show `Waiting for network`, retry with backoff.
- Tailscale unavailable: remain locally active and retry; do not crash-loop.
- PC offline: keep service alive and wait.
- Authentication failure: reject command and record a local security event.
- Permission missing: return `permission_required` with the exact capability name.
- Screen-share consent denied: leave the core service running and report that screen sharing was not started.
- Android kills the process: recovery worker / supported boot recovery restores the core service when allowed.

## Logging and Privacy

Keep operational logs minimal and local by default. Do not log screen content, file contents, authentication secrets, or full tokens. Record only connection state, command type, timestamps, failures, and recovery events needed for troubleshooting.

## Testing Strategy

### Unit tests
- pairing-state validation;
- command authentication and rejection;
- command routing;
- retry/backoff state;
- capability permission-state mapping.

### Android tests
- foreground service starts and posts required notification;
- service survives activity closure;
- boot receiver schedules recovery correctly;
- service reconnects after temporary network loss;
- invalid client commands are rejected;
- MediaProjection still requires and handles consent correctly;
- Accessibility commands are unavailable until the service is enabled.

### Integration tests
- PC pairs with one phone;
- PC reconnects after app restart;
- phone reconnects after network transition;
- phone reconnects after reboot where Android permits automatic recovery;
- screen request prompts for Android consent and then streams;
- ADB can be disabled while the new service path remains connected for supported non-ADB features.

## Delivery Order

Phase 1: persistent foreground service, status notification, boot/recovery path, pairing, authenticated command channel, device-status command.

Phase 2: integrate PC PhoneHub with the new service and keep ADB as explicit fallback.

Phase 3: connect the existing MediaProjection/WebRTC screen flow to authenticated PC requests.

Phase 4: optional Accessibility-based control, file access, notification bridge, and managed-device Device Owner provisioning.

## Success Criteria

The first production milestone is successful when:

- PhoneHub Android can remain available after its activity is closed;
- it restores its service after reboot using supported Android behavior;
- only a paired PC can issue commands;
- the PC can connect over the private network without ADB;
- ADB/USB debugging can be turned off and supported service commands still work;
- the user can always see that PhoneHub is active through Android's notification/service UI;
- screen sharing continues to honor Android MediaProjection consent requirements;
- failures recover automatically without repeated manual reconfiguration.
