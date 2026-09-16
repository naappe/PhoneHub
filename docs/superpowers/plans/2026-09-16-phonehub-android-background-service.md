# PhoneHub Android Background Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a transparent Android companion backend that stays available in the background, reconnects automatically, authenticates a paired PC, and lets PhoneHub operate over the private Tailscale route without requiring ADB for supported functions.

**Architecture:** Extend the existing `android-link` Kotlin app rather than starting over. Add a dedicated foreground `PhoneHubService` for long-lived connectivity and command routing, keep MediaProjection isolated in `ScreenShareService`, add boot/recovery support, and integrate a paired/authenticated service path into the existing PySide6 desktop app while preserving ADB as explicit fallback.

**Tech Stack:** Kotlin, Android SDK 35, minSdk 26, Android foreground services, WorkManager, Android Keystore, Kotlin coroutines, Ktor/WebSockets or a small authenticated TCP/WebSocket endpoint over Tailscale, existing WebRTC sender, existing Supabase Realtime signaling for screen negotiation, Python 3/PySide6 desktop app, unittest/pytest-style Python tests, Android/JUnit tests.

**Spec:** `docs/superpowers/specs/2026-09-16-phonehub-android-background-service-design.md`

## Global Constraints

- The Android companion must be user-visible and must not hide its persistent service activity.
- The persistent backend must use an ongoing foreground-service notification.
- Screen sharing must continue to use Android MediaProjection consent; do not bypass system consent.
- Accessibility-based control must require explicit user enablement and is outside this first implementation milestone.
- No private keys, service-role keys, admin passwords, or long-lived secrets may be committed to GitHub.
- ADB remains available only as explicit fallback during migration.
- The first production milestone must work with USB disconnected and USB debugging disabled for supported non-ADB service commands.
- Unknown clients must be rejected; network reachability alone is not authentication.
- Build on the existing `android-link` branch implementation of `MainActivity`, `ScreenShareService`, WebRTC, and signaling rather than replacing it wholesale.

---

## File Structure

Create or modify the following focused units:

- `android-link/app/src/main/java/mv/phonehub/link/PhoneHubService.kt` — long-lived foreground service, lifecycle, connection ownership, notification state.
- `android-link/app/src/main/java/mv/phonehub/link/BootReceiver.kt` — receives boot/package-replaced events and schedules recovery.
- `android-link/app/src/main/java/mv/phonehub/link/RecoveryWorker.kt` — WorkManager retry/backoff for safe service recovery.
- `android-link/app/src/main/java/mv/phonehub/link/PairingStore.kt` — paired-PC metadata and Android Keystore-backed secret material.
- `android-link/app/src/main/java/mv/phonehub/link/AuthProtocol.kt` — nonce/HMAC request validation and response signing.
- `android-link/app/src/main/java/mv/phonehub/link/CommandRouter.kt` — authenticated command dispatch and capability responses.
- `android-link/app/src/main/java/mv/phonehub/link/DeviceInfoController.kt` — battery/model/network/service-state response.
- `android-link/app/src/main/java/mv/phonehub/link/PhoneHubServer.kt` — private-network WebSocket endpoint on a fixed application port.
- `android-link/app/src/main/java/mv/phonehub/link/MainActivity.kt` — setup/status UI, pairing code, service enable/disable, permission guidance.
- `android-link/app/src/main/java/mv/phonehub/link/ScreenShareService.kt` — wire authenticated screen requests into existing MediaProjection flow without changing consent semantics.
- `android-link/app/src/main/AndroidManifest.xml` — service, boot receiver, permissions.
- `android-link/app/build.gradle.kts` — WorkManager and any required Ktor server dependency.
- `android-link/app/src/test/java/mv/phonehub/link/*Test.kt` — protocol, pairing, routing, recovery tests.
- `app/phonehub_service_client.py` — desktop authenticated client for the Android PhoneHub service.
- `app/PhoneHub.py` — prefer PhoneHub service connection, expose state, retain explicit ADB fallback.
- `tests/test_phonehub_service_client.py` — Python protocol/auth tests.
- `tests/test_phonehub_service_ui.py` — desktop integration/launcher assertions.
- `.github/workflows/phone-ip-tests.yml` — include new Python tests and compile checks.

---

### Task 1: Add Pairing State and Request Authentication

**Files:**
- Create: `android-link/app/src/main/java/mv/phonehub/link/PairingStore.kt`
- Create: `android-link/app/src/main/java/mv/phonehub/link/AuthProtocol.kt`
- Create: `android-link/app/src/test/java/mv/phonehub/link/AuthProtocolTest.kt`
- Modify: `android-link/app/build.gradle.kts`

**Interfaces:**
- Produces: `PairingStore.createPairingCode(): String`
- Produces: `PairingStore.completePairing(pcId: String, pairingCode: String): PairedClient`
- Produces: `PairingStore.getPairedClient(): PairedClient?`
- Produces: `PairingStore.revokePairing()`
- Produces: `AuthProtocol.sign(secret: ByteArray, nonce: String, body: String): String`
- Produces: `AuthProtocol.verify(secret: ByteArray, nonce: String, body: String, signature: String): Boolean`

- [ ] **Step 1: Add failing unit tests for HMAC validation and pairing lifecycle**

```kotlin
package mv.phonehub.link

import org.junit.Assert.*
import org.junit.Test

class AuthProtocolTest {
    @Test
    fun validSignaturePassesAndTamperingFails() {
        val secret = "01234567890123456789012345678901".toByteArray()
        val nonce = "n-123"
        val body = "{\"type\":\"device_status\"}"
        val signature = AuthProtocol.sign(secret, nonce, body)

        assertTrue(AuthProtocol.verify(secret, nonce, body, signature))
        assertFalse(AuthProtocol.verify(secret, nonce, body + "x", signature))
    }

    @Test
    fun pairingCodeIsSixDigits() {
        val code = PairingStore.generateHumanCode()
        assertTrue(code.matches(Regex("\\d{6}")))
    }
}
```

- [ ] **Step 2: Run the Android unit test and verify failure**

Run from `android-link`:

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.AuthProtocolTest
```

Expected: FAIL because `AuthProtocol` and `PairingStore` do not exist.

- [ ] **Step 3: Implement `AuthProtocol` with HMAC-SHA256 and constant-time comparison**

```kotlin
package mv.phonehub.link

import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

object AuthProtocol {
    fun sign(secret: ByteArray, nonce: String, body: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret, "HmacSHA256"))
        val bytes = mac.doFinal("$nonce\n$body".toByteArray(Charsets.UTF_8))
        return bytes.joinToString("") { "%02x".format(it) }
    }

    fun verify(secret: ByteArray, nonce: String, body: String, signature: String): Boolean {
        val expected = sign(secret, nonce, body)
        if (expected.length != signature.length) return false
        var diff = 0
        for (i in expected.indices) diff = diff or (expected[i].code xor signature[i].code)
        return diff == 0
    }
}
```

- [ ] **Step 4: Implement `PairingStore` with Android Keystore-backed secret generation**

Use a `SharedPreferences` record for non-secret metadata (`pc_id`, paired timestamp), and an Android Keystore alias such as `phonehub_pairing_secret_v1` for the key. Expose a pure helper `generateHumanCode()` for unit testing and keep the active six-digit pairing code only in memory with a 5-minute expiry.

- [ ] **Step 5: Re-run unit tests**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.AuthProtocolTest
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add android-link/app/src/main/java/mv/phonehub/link/PairingStore.kt \
        android-link/app/src/main/java/mv/phonehub/link/AuthProtocol.kt \
        android-link/app/src/test/java/mv/phonehub/link/AuthProtocolTest.kt \
        android-link/app/build.gradle.kts
git commit -m "feat: add PhoneHub pairing authentication"
```

---

### Task 2: Add the Persistent Foreground Backend Service

**Files:**
- Create: `android-link/app/src/main/java/mv/phonehub/link/PhoneHubService.kt`
- Modify: `android-link/app/src/main/AndroidManifest.xml`
- Create: `android-link/app/src/test/java/mv/phonehub/link/PhoneHubServiceStateTest.kt`

**Interfaces:**
- Consumes: `PairingStore`
- Produces: `PhoneHubService.ACTION_START`
- Produces: `PhoneHubService.ACTION_STOP`
- Produces: `PhoneHubService.currentState: ServiceState`
- Produces: `ServiceState` values `ACTIVE`, `WAITING_FOR_NETWORK`, `WAITING_FOR_PAIRING`, `CONNECTED`, `ERROR`

- [ ] **Step 1: Write failing state-mapping tests**

```kotlin
package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class PhoneHubServiceStateTest {
    @Test
    fun notificationCopyReflectsState() {
        assertEquals("Active - waiting for paired PC", ServiceState.WAITING_FOR_PAIRING.notificationText)
        assertEquals("Active - paired PC connected", ServiceState.CONNECTED.notificationText)
    }
}
```

- [ ] **Step 2: Run test and verify failure**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.PhoneHubServiceStateTest
```

Expected: FAIL because `ServiceState` does not exist.

- [ ] **Step 3: Implement `ServiceState` and `PhoneHubService`**

`PhoneHubService` must:

```kotlin
override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    when (intent?.action) {
        ACTION_STOP -> stopBackend()
        else -> startBackend()
    }
    return START_STICKY
}
```

On startup, create notification channel `phonehub_core`, immediately call `startForeground(...)`, then initialize the server. Notification title must be `PhoneHub` and text must come from `ServiceState.notificationText`.

- [ ] **Step 4: Register service and permissions in the manifest**

Add `FOREGROUND_SERVICE`, `POST_NOTIFICATIONS`, `RECEIVE_BOOT_COMPLETED`, and a non-exported `PhoneHubService`. Keep the existing `ScreenShareService` declaration unchanged except for later integration.

- [ ] **Step 5: Re-run tests and compile**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.PhoneHubServiceStateTest
./gradlew assembleDebug
```

Expected: both commands succeed.

- [ ] **Step 6: Commit**

```bash
git add android-link/app/src/main/java/mv/phonehub/link/PhoneHubService.kt \
        android-link/app/src/main/AndroidManifest.xml \
        android-link/app/src/test/java/mv/phonehub/link/PhoneHubServiceStateTest.kt
git commit -m "feat: add persistent PhoneHub foreground service"
```

---

### Task 3: Add Boot Recovery and Backoff

**Files:**
- Create: `android-link/app/src/main/java/mv/phonehub/link/BootReceiver.kt`
- Create: `android-link/app/src/main/java/mv/phonehub/link/RecoveryWorker.kt`
- Create: `android-link/app/src/main/java/mv/phonehub/link/RecoveryPolicy.kt`
- Create: `android-link/app/src/test/java/mv/phonehub/link/RecoveryPolicyTest.kt`
- Modify: `android-link/app/src/main/AndroidManifest.xml`
- Modify: `android-link/app/build.gradle.kts`

**Interfaces:**
- Produces: `RecoveryPolicy.nextDelaySeconds(attempt: Int): Long`
- Produces: `RecoveryWorker.enqueue(context: Context)`
- `BootReceiver` invokes `RecoveryWorker.enqueue(context)` after `BOOT_COMPLETED` and `MY_PACKAGE_REPLACED`.

- [ ] **Step 1: Write failing exponential-backoff tests**

```kotlin
package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class RecoveryPolicyTest {
    @Test
    fun backoffIsBounded() {
        assertEquals(15L, RecoveryPolicy.nextDelaySeconds(0))
        assertEquals(30L, RecoveryPolicy.nextDelaySeconds(1))
        assertEquals(60L, RecoveryPolicy.nextDelaySeconds(2))
        assertEquals(900L, RecoveryPolicy.nextDelaySeconds(20))
    }
}
```

- [ ] **Step 2: Run test and verify failure**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.RecoveryPolicyTest
```

Expected: FAIL because `RecoveryPolicy` does not exist.

- [ ] **Step 3: Add WorkManager dependency and implement recovery units**

Add:

```kotlin
implementation("androidx.work:work-runtime-ktx:2.10.0")
```

Implement `RecoveryPolicy.nextDelaySeconds` as `min(15 * 2^attempt, 900)` without integer overflow. `RecoveryWorker` should check whether PhoneHub has previously been enabled, then request a foreground-service start using `ContextCompat.startForegroundService` where Android allows it; otherwise return `Result.retry()`.

- [ ] **Step 4: Register boot receiver**

Receiver must be `android:exported="false"` and listen only for `BOOT_COMPLETED` and `MY_PACKAGE_REPLACED`.

- [ ] **Step 5: Run tests and build**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.RecoveryPolicyTest
./gradlew assembleDebug
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add android-link/app/src/main/java/mv/phonehub/link/BootReceiver.kt \
        android-link/app/src/main/java/mv/phonehub/link/RecoveryWorker.kt \
        android-link/app/src/main/java/mv/phonehub/link/RecoveryPolicy.kt \
        android-link/app/src/test/java/mv/phonehub/link/RecoveryPolicyTest.kt \
        android-link/app/src/main/AndroidManifest.xml android-link/app/build.gradle.kts
git commit -m "feat: add PhoneHub boot recovery"
```

---

### Task 4: Add Authenticated Private-Network Command Server

**Files:**
- Create: `android-link/app/src/main/java/mv/phonehub/link/PhoneHubServer.kt`
- Create: `android-link/app/src/main/java/mv/phonehub/link/CommandRouter.kt`
- Create: `android-link/app/src/main/java/mv/phonehub/link/DeviceInfoController.kt`
- Create: `android-link/app/src/main/java/mv/phonehub/link/ProtocolModels.kt`
- Create: `android-link/app/src/test/java/mv/phonehub/link/CommandRouterTest.kt`
- Modify: `android-link/app/build.gradle.kts`
- Modify: `android-link/app/src/main/java/mv/phonehub/link/PhoneHubService.kt`

**Interfaces:**
- Server listens on application port `8765` bound to the device network interface.
- Request JSON fields: `version`, `pcId`, `nonce`, `timestamp`, `type`, `payload`, `signature`.
- Response JSON fields: `ok`, `type`, `data`, `error`, `timestamp`, `signature`.
- Produces: `CommandRouter.handle(type: String, payload: JsonObject): CommandResult`
- Initial supported commands: `ping`, `device_status`, `screen_request`.

- [ ] **Step 1: Write failing router tests**

```kotlin
package mv.phonehub.link

import kotlinx.serialization.json.buildJsonObject
import org.junit.Assert.*
import org.junit.Test

class CommandRouterTest {
    @Test
    fun unknownCommandIsRejected() {
        val router = CommandRouter(FakeDeviceInfoController())
        val result = router.handle("does_not_exist", buildJsonObject {})
        assertFalse(result.ok)
        assertEquals("unsupported_command", result.error)
    }

    @Test
    fun pingReturnsPong() {
        val router = CommandRouter(FakeDeviceInfoController())
        val result = router.handle("ping", buildJsonObject {})
        assertTrue(result.ok)
        assertEquals("pong", result.data["reply"]?.toString()?.trim('"'))
    }
}
```

- [ ] **Step 2: Run test and verify failure**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.CommandRouterTest
```

Expected: FAIL because protocol/router classes do not exist.

- [ ] **Step 3: Implement protocol models and command router**

`CommandRouter` must not perform authentication itself. It receives only already-verified commands. Add `device_status` using `DeviceInfoController` to return battery percentage, manufacturer/model, Android version, service state, and whether screen sharing is active.

- [ ] **Step 4: Implement `PhoneHubServer`**

Use a lightweight WebSocket server on port `8765`. For every incoming frame:

1. Parse JSON.
2. Reject unsupported protocol versions.
3. Require `pcId` to match the paired client.
4. Reject timestamps older/newer than 60 seconds.
5. Reject a nonce already seen in the in-memory replay cache.
6. Reconstruct the canonical unsigned body.
7. Verify `signature` with `AuthProtocol.verify`.
8. Dispatch to `CommandRouter`.
9. Sign the response before sending.

Keep the last 256 nonces with timestamp eviction.

- [ ] **Step 5: Start/stop server from `PhoneHubService`**

`PhoneHubService.startBackend()` constructs `PairingStore`, `DeviceInfoController`, `CommandRouter`, and `PhoneHubServer`; connection callbacks update `ServiceState`.

- [ ] **Step 6: Run unit tests and build**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.CommandRouterTest
./gradlew assembleDebug
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add android-link/app/src/main/java/mv/phonehub/link/PhoneHubServer.kt \
        android-link/app/src/main/java/mv/phonehub/link/CommandRouter.kt \
        android-link/app/src/main/java/mv/phonehub/link/DeviceInfoController.kt \
        android-link/app/src/main/java/mv/phonehub/link/ProtocolModels.kt \
        android-link/app/src/test/java/mv/phonehub/link/CommandRouterTest.kt \
        android-link/app/src/main/java/mv/phonehub/link/PhoneHubService.kt \
        android-link/app/build.gradle.kts
git commit -m "feat: add authenticated PhoneHub command server"
```

---

### Task 5: Update Android Setup UI for Service and Pairing

**Files:**
- Modify: `android-link/app/src/main/java/mv/phonehub/link/MainActivity.kt`
- Create: `android-link/app/src/test/java/mv/phonehub/link/PairingUiStateTest.kt`

**Interfaces:**
- Consumes: `PairingStore`, `PhoneHubService`
- UI states: `Service Off`, `Active - Not Paired`, `Active - Paired`, `Permission Required`.
- Buttons: `Enable PhoneHub`, `Generate Pairing Code`, `Revoke Paired PC`, `Start Screen Share`.

- [ ] **Step 1: Add failing pure-state test**

```kotlin
package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class PairingUiStateTest {
    @Test
    fun pairedActiveStateHasExpectedCopy() {
        val state = PairingUiState(serviceEnabled = true, paired = true)
        assertEquals("Active - Paired", state.title)
    }
}
```

- [ ] **Step 2: Run test and verify failure**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.PairingUiStateTest
```

Expected: FAIL because `PairingUiState` does not exist.

- [ ] **Step 3: Refactor `MainActivity` around the new setup flow**

On first run, request notification permission where required, show service status, and make `Enable PhoneHub` call `ContextCompat.startForegroundService`. `Generate Pairing Code` displays a six-digit code and five-minute expiry. `Revoke Paired PC` clears trust and returns to unpaired state.

Keep the existing MediaProjection launcher and `Start Screen Share` button. Do not auto-trigger MediaProjection from boot or silently from the background.

- [ ] **Step 4: Run tests and assemble**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.PairingUiStateTest
./gradlew assembleDebug
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add android-link/app/src/main/java/mv/phonehub/link/MainActivity.kt \
        android-link/app/src/test/java/mv/phonehub/link/PairingUiStateTest.kt
git commit -m "feat: add PhoneHub service pairing setup UI"
```

---

### Task 6: Integrate Authenticated Screen Requests Without Bypassing Consent

**Files:**
- Modify: `android-link/app/src/main/java/mv/phonehub/link/CommandRouter.kt`
- Modify: `android-link/app/src/main/java/mv/phonehub/link/MainActivity.kt`
- Modify: `android-link/app/src/main/java/mv/phonehub/link/ScreenShareService.kt`
- Create: `android-link/app/src/test/java/mv/phonehub/link/ScreenRequestStateTest.kt`

**Interfaces:**
- `screen_request` returns either `permission_required` or `already_sharing`.
- `MainActivity` observes a locally stored pending screen request and presents the normal Android MediaProjection prompt only after the user opens/acknowledges the screen-share action.
- `ScreenShareService` retains existing room/WebRTC behavior.

- [ ] **Step 1: Write failing screen-request state test**

```kotlin
package mv.phonehub.link

import org.junit.Assert.assertEquals
import org.junit.Test

class ScreenRequestStateTest {
    @Test
    fun inactiveProjectionRequiresPermission() {
        assertEquals("permission_required", ScreenRequestState(isSharing = false).resultCode)
    }
}
```

- [ ] **Step 2: Run test and verify failure**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.ScreenRequestStateTest
```

- [ ] **Step 3: Implement request state and command response**

When the PC sends `screen_request`, never fabricate projection permission. Return a signed response containing `permission_required: media_projection` unless an already-approved active session exists.

- [ ] **Step 4: Wire approved sessions to existing `ScreenShareService`**

Reuse the current `MediaProjectionManager.createScreenCaptureIntent()` and existing extras `EXTRA_ROOM` and `EXTRA_PROJECTION_DATA`. Preserve the foreground notification while sharing.

- [ ] **Step 5: Run tests and build**

```bash
./gradlew testDebugUnitTest --tests mv.phonehub.link.ScreenRequestStateTest
./gradlew assembleDebug
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add android-link/app/src/main/java/mv/phonehub/link/CommandRouter.kt \
        android-link/app/src/main/java/mv/phonehub/link/MainActivity.kt \
        android-link/app/src/main/java/mv/phonehub/link/ScreenShareService.kt \
        android-link/app/src/test/java/mv/phonehub/link/ScreenRequestStateTest.kt
git commit -m "feat: connect authenticated screen requests"
```

---

### Task 7: Add Desktop PhoneHub Service Client and Prefer It Over ADB

**Files:**
- Create: `app/phonehub_service_client.py`
- Create: `tests/test_phonehub_service_client.py`
- Modify: `app/PhoneHub.py`
- Create: `tests/test_phonehub_service_ui.py`
- Modify: `.github/workflows/phone-ip-tests.yml`

**Interfaces:**
- Produces: `PhoneHubServiceClient(host: str, port: int = 8765, pc_id: str = ..., secret: bytes = ...)`
- Produces: `client.ping() -> bool`
- Produces: `client.device_status() -> dict`
- Produces: `client.request_screen() -> dict`
- Desktop preference order: `PhoneHub Service` first, `ADB fallback` only when explicitly selected or service unavailable.

- [ ] **Step 1: Write failing Python protocol tests**

```python
import unittest
from app.phonehub_service_client import canonical_body, sign_request


class PhoneHubServiceClientTests(unittest.TestCase):
    def test_signature_is_stable(self):
        secret = b"01234567890123456789012345678901"
        body = canonical_body("pc-1", "nonce-1", 1234567890, "ping", {})
        first = sign_request(secret, "nonce-1", body)
        second = sign_request(secret, "nonce-1", body)
        self.assertEqual(first, second)

    def test_payload_change_changes_signature(self):
        secret = b"01234567890123456789012345678901"
        a = canonical_body("pc-1", "n", 1, "ping", {})
        b = canonical_body("pc-1", "n", 1, "device_status", {})
        self.assertNotEqual(sign_request(secret, "n", a), sign_request(secret, "n", b))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify failure**

```bash
python -m unittest tests.test_phonehub_service_client -v
```

Expected: FAIL because `app.phonehub_service_client` does not exist.

- [ ] **Step 3: Implement canonical JSON + HMAC client**

Use sorted-key compact JSON, `hmac.new(secret, f"{nonce}\n{body}".encode(), hashlib.sha256).hexdigest()`, a 5-second connection timeout, and WebSocket request/response handling. Store `pc_id` and secret in the existing local PhoneHub config directory, never in the repository.

- [ ] **Step 4: Add failing desktop UI assertions**

`tests/test_phonehub_service_ui.py` must assert that `PhoneHub.py` contains visible connection labels for `PhoneHub Service`, a service-first status path, and an explicit `Use ADB Fallback` action rather than silently preferring ADB.

- [ ] **Step 5: Modify `app/PhoneHub.py`**

Dashboard behavior:

1. Load saved phone Tailscale IP.
2. If paired service credentials exist, attempt `PhoneHubServiceClient.ping()` against `<tailscale-ip>:8765`.
3. If successful, display `Connection: PhoneHub Service` and device status from the Android backend.
4. Do not start or connect ADB automatically in this successful service path.
5. Keep existing ADB functions available behind an explicit `Use ADB Fallback` control.
6. If no service pairing exists, show `PhoneHub Android app not paired` and preserve the setup guidance.

- [ ] **Step 6: Update CI workflow**

Add:

```yaml
- name: Run PhoneHub service client tests
  run: python -m unittest tests.test_phonehub_service_client -v

- name: Run PhoneHub service UI tests
  run: python -m unittest tests.test_phonehub_service_ui -v
```

Update compile step to include `app/phonehub_service_client.py`.

- [ ] **Step 7: Run complete desktop test suite**

```bash
python -m unittest tests.test_phone_config -v
python -m unittest tests.test_launcher_update -v
python -m unittest tests.test_phonehub_link_ui -v
python -m unittest tests.test_phonehub_service_client -v
python -m unittest tests.test_phonehub_service_ui -v
python -m py_compile app/PhoneHub.py app/PhoneHubLink.py app/phone_config.py app/phonehub_service_client.py
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/phonehub_service_client.py app/PhoneHub.py \
        tests/test_phonehub_service_client.py tests/test_phonehub_service_ui.py \
        .github/workflows/phone-ip-tests.yml
git commit -m "feat: prefer PhoneHub Android service over ADB"
```

---

### Task 8: End-to-End Validation and Migration Gate

**Files:**
- Modify: `README_User_Guide.txt`
- Modify: `README.md`
- Optional test fixture updates only if required by observed failures.

**Interfaces:**
- No new runtime interfaces; this task validates the milestone and documents exact operating procedure.

- [ ] **Step 1: Build the Android APK**

```bash
cd android-link
./gradlew clean testDebugUnitTest assembleDebug
```

Expected: tests PASS and debug APK produced under `app/build/outputs/apk/debug/`.

- [ ] **Step 2: Run all desktop tests**

```bash
cd ..
python -m unittest discover -s tests -v
python -m py_compile app/PhoneHub.py app/PhoneHubLink.py app/phone_config.py app/phonehub_service_client.py
```

Expected: PASS.

- [ ] **Step 3: Perform manual Android service lifecycle test**

Verify on a test phone:

1. Install APK.
2. Open PhoneHub once.
3. Enable PhoneHub service.
4. Confirm persistent `PhoneHub - Active` notification.
5. Pair the PC with the six-digit code.
6. Close the Android activity.
7. Confirm PC can still run `ping` and `device_status`.
8. Turn USB debugging OFF.
9. Disconnect USB.
10. Confirm `ping` and `device_status` still work through the PhoneHub service.

Expected: all supported service commands continue working without ADB.

- [ ] **Step 4: Perform network recovery test**

1. Disable phone Wi-Fi/mobile data briefly.
2. Confirm service shows `Waiting for network`.
3. Restore connectivity/Tailscale.
4. Confirm PC reconnects without re-pairing.

Expected: automatic recovery.

- [ ] **Step 5: Perform reboot recovery test**

1. Reboot phone.
2. Verify PhoneHub recovery is scheduled/started according to Android version restrictions.
3. Confirm notification returns and paired state remains.
4. Confirm PC can reconnect without repeating pairing.

Expected: paired state survives; supported service recovers automatically where Android permits.

- [ ] **Step 6: Validate screen consent boundary**

From PC request screen sharing. Confirm the service returns `permission_required` until Android MediaProjection consent is granted. After user approval, confirm existing WebRTC stream starts. Denying consent must leave the core PhoneHub service running.

- [ ] **Step 7: Update documentation with the new normal-use flow**

Document exactly:

```text
Normal use:
PC PhoneHub -> Tailscale -> PhoneHub Android service
USB cable: not required
USB debugging: not required for supported PhoneHub-service functions
ADB: legacy fallback only
Screen sharing: Android consent required when starting a new MediaProjection session
```

- [ ] **Step 8: Commit milestone documentation**

```bash
git add README.md README_User_Guide.txt
git commit -m "docs: document PhoneHub Android service mode"
```

---

## Deferred to a Separate Plan

The following are intentionally excluded from this implementation plan because they are independent permission-heavy subsystems and should each have their own reviewable design/plan after the service foundation is stable:

- Accessibility-based remote taps/swipes/back/home.
- File browser/write operations through Storage Access Framework.
- Notification Listener bridge.
- Managed-device / Device Owner provisioning and uninstall-policy controls.
- Replacing the browser/WebRTC viewer with a native embedded desktop viewer.

## Final Acceptance Criteria

Before marking this plan complete, verify all of the following:

- Android foreground PhoneHub service remains available when the activity is closed.
- Persistent notification clearly indicates PhoneHub is active.
- Pairing is explicit and only the paired PC can authenticate commands.
- Replay attempts and invalid signatures are rejected.
- PC can run `ping` and `device_status` over the phone Tailscale IP on port 8765.
- Supported commands continue working with USB disconnected and USB debugging disabled.
- Network interruption recovers automatically without re-pairing.
- Reboot preserves pairing and restores service using Android-supported behavior.
- MediaProjection still requires Android consent for new screen-capture sessions.
- Desktop app prefers the PhoneHub Android service and exposes ADB only as an explicit fallback.
- CI and Android build/tests are green.
