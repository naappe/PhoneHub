# PhoneHub Link View-Only v0.1 Design

## Goal
Build a small Android companion and browser viewer that lets the user view the Android screen live from a PC on a completely different network, without USB, ADB, or the Tailscale app for normal use.

## Scope
This is a proof-of-concept for view-only screen sharing. It intentionally excludes remote touch/control, audio, file transfer, camera switching, account management, TURN relay infrastructure, and background unattended capture.

## Architecture

Android PhoneHub Link captures the screen using Android MediaProjection, encodes/sends the screen as a WebRTC video track, and exchanges WebRTC signaling messages through Supabase Realtime Broadcast. A static browser viewer hosted from GitHub Pages joins the same temporary room, exchanges offer/answer/ICE messages, and displays the remote video track. Media should travel peer-to-peer when NAT traversal succeeds; Supabase carries signaling only.

## Components

### `android-link/`
Native Android Kotlin app, minSdk 26, target/compile SDK 35. The app exposes a simple screen with Start Screen Share, room code, connection state, and Stop Sharing. Starting share launches the system MediaProjection consent prompt. Once approved, the app starts a foreground media-projection service and WebRTC sender.

### `viewer/`
Static HTML/CSS/JavaScript viewer suitable for GitHub Pages. It accepts a six-digit room code, subscribes to the Supabase Realtime channel for that room, creates the WebRTC peer connection, and renders the incoming video track.

### Supabase Realtime
Use the existing Supabase project `tmupbruwmwlrmewhoodn` and its publishable key. Broadcast topics are temporary room-scoped channels. No database tables are required for v0.1. Signaling messages are JSON only: `viewer-ready`, `offer`, `answer`, `ice`, `stop`.

### GitHub Actions
A workflow builds the Android debug APK on pushes to the feature branch and on manual dispatch, uploads the APK as an artifact, and packages the static viewer as a Pages artifact. A later release workflow can attach a signed APK after the spike is validated.

## Session flow
1. User opens PhoneHub Link on Android.
2. User taps Start Screen Share.
3. Android shows MediaProjection consent; user approves.
4. App generates a random six-digit room code and a random long session token.
5. App joins Supabase Realtime channel `phonehub-link:<room-code>`.
6. PC opens the viewer and enters the room code.
7. Viewer joins the channel and broadcasts `viewer-ready`.
8. Android creates a WebRTC offer and broadcasts `offer` with SDP.
9. Viewer sets the remote offer, creates an answer, and broadcasts `answer`.
10. Both sides exchange ICE candidates using `ice` messages.
11. When ICE connects, the browser displays the phone screen.
12. Stop Sharing ends MediaProjection, closes the peer connection, broadcasts `stop`, and invalidates the session.

## WebRTC configuration
Use a STUN-only configuration for the spike, beginning with `stun:stun.l.google.com:19302`. No TURN credentials or relay service are included in v0.1. The acceptance test must explicitly include phone on mobile data and PC on a different Wi-Fi connection. If ICE fails on that test, the result of the spike is that TURN is required for reliable deployment.

## Android permissions and service
Required manifest permissions: INTERNET, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MEDIA_PROJECTION, and POST_NOTIFICATIONS on Android 13+. The foreground service declares `mediaProjection` as its type. No camera, microphone, storage, accessibility, or location permission is requested in v0.1.

## Security
The Supabase publishable key is public by design and may be embedded in the Android app and browser viewer. The room code is only a short locator; each sender session also creates a long random token and includes it in signaling payloads. The viewer must present the token if it is provided through the generated share URL. For the manual six-digit code path, v0.1 is considered a test-only mode and must not be treated as production authorization. Media transport uses WebRTC DTLS-SRTP.

## Failure handling
The Android UI shows `Waiting for viewer`, `Connecting`, `Connected`, `Disconnected`, and `Error`. If signaling subscription fails, the sender stops and shows an actionable error. If ICE does not reach connected/completed within 20 seconds after answer exchange, the app reports that the current networks may require TURN. If MediaProjection is revoked, screen sharing stops immediately.

## Build automation
The Android project is built on GitHub Actions using JDK 17, Android SDK 35, Gradle 8.x, Android Gradle Plugin 8.7.x, and Kotlin 2.x. The WebRTC AAR comes from Maven Central using `io.github.webrtc-sdk:android:150.7871.01`. Supabase Kotlin Realtime uses the current 3.8.x line with a Ktor WebSocket-capable Android engine.

## Acceptance criteria
- GitHub Actions produces an installable debug APK without Android Studio.
- Android app can request screen-capture permission and enter active-sharing state.
- Browser viewer can join the same room through Supabase Realtime.
- Offer/answer/ICE exchange occurs without a custom server.
- On at least one test where phone and PC are on different networks, the browser displays the live Android screen.
- If that different-network test cannot establish ICE, the app clearly reports that TURN is required rather than falsely reporting success.

## Non-goals for v0.1
No remote input/control, no audio, no camera capture, no file access, no hidden capture, no lock-screen bypass, no unattended screen capture, no custom VPN, and no replacement for Tailscale outside PhoneHub Link.