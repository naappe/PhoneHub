# PhoneHub Link View-Only v0.1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prove that an Android phone on mobile data can stream its screen to a PC on a different network without USB or ADB.

**Architecture:** Android MediaProjection feeds a WebRTC video track. Supabase Realtime Broadcast carries signaling only. A static browser viewer receives the WebRTC track. GitHub Actions builds the APK automatically.

**Tech Stack:** Kotlin, Android SDK 35, JDK 17, WebRTC Android SDK, Supabase Kotlin Realtime, HTML/JavaScript, supabase-js, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-16-phonehub-link-view-design.md`

## Global Constraints
- View only.
- No USB or ADB in the streaming path.
- User must approve Android MediaProjection.
- STUN only for the first test; if different-network ICE fails, TURN is the next step.
- Use existing Supabase project and publishable key.
- GitHub Actions must produce the APK.

### Task 1: Android sender
- [ ] Scaffold Gradle Android project.
- [ ] Add room generation unit test, then implementation.
- [ ] Add MediaProjection foreground service.
- [ ] Add Supabase Realtime signaling.
- [ ] Add WebRTC screen sender.
- [ ] Build debug APK.

### Task 2: Browser viewer
- [ ] Add room-code viewer UI.
- [ ] Add Supabase Realtime signaling.
- [ ] Add WebRTC receiver and remote video element.

### Task 3: Automation and verification
- [ ] Add GitHub Actions APK build and viewer artifact workflow.
- [ ] Run unit tests and assembleDebug.
- [ ] Download APK to phone and test phone mobile data vs PC Wi-Fi.
- [ ] Record whether direct STUN ICE succeeds; if not, add TURN in the next iteration.