# PhoneHub 7 — Companion migration

PhoneHub 7 is developed separately from the working 6.3 Tailscale branch.

## Goal

One-time Android enrollment followed by automatic boot/reconnect and quiet day-to-day operation.

## Transport phases

1. **LAN companion transport** — Android companion advertises itself on the local network and maintains an authenticated connection to PhoneHub.
2. **Tailscale fallback** — retained while the companion transport is being tested. PhoneHub 6.3 remains usable.
3. **Remote transport** — added only after LAN transport is stable. Remote access must use authenticated encryption; no unauthenticated public listening ports.

## Android lifecycle

The companion uses an Android foreground service for persistent work and a boot receiver to request restart after reboot. Android/OxygenOS may still require the user to approve notification/background/autostart behavior. PhoneHub must not bypass Android security controls.

## Pairing

First enrollment must require explicit user approval. A paired PC receives a generated credential; commands from unknown clients are rejected.

## Initial feature order

- connection heartbeat and device identity
- automatic reconnect
- front/back camera
- device status
- screen-control handoff to scrcpy where Android/ADB authorization permits it

Do not remove the existing Tailscale path until the companion path is verified on the target phone.
