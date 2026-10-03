# PhoneHub Connection Layer

## Purpose

This document records the current PhoneHub connection architecture and the first implemented capability.

The goal is a one-time setup followed by automatic reconnection to the user's own or company-managed Android phones over a private Tailscale network.

## Current Scope

Implemented now:

- `ensureRemoteConnection()`
- `executeCapability(action, parameters)`
- `battery` capability

Not implemented yet:

- status
- screen
- camera
- apps
- notifications
- activity

These capabilities must not be added until the connection layer has passed the live battery test.

## Architecture

```text
executeCapability("battery")
      ↓
ensureRemoteConnection()
      ↓
reuse live connection
      │
      └─ if not live:
           Tailscale ping
                ↓
           adb connect
                ↓
           verify device identity
                ↓
READY / PHONE_OFFLINE / CONNECTION_FAILED
```

Tailscale is only the private network path. It is not the main PhoneHub function.

Current transport:

```text
PC Python controller
      ↓
Tailscale
      ↓
ADB over TCP :5555
      ↓
Android phone
```

Long-term transport:

```text
PC / another authorized device
      ↓
Tailscale
      ↓
PhoneHub Companion API
      ↓
Android capabilities
```

ADB is intended to become setup, diagnostics, and recovery only.

## Public API

### ensureRemoteConnection()

Returns exactly one of:

- `READY`
- `PHONE_OFFLINE`
- `CONNECTION_FAILED`

Behavior:

1. Load the saved endpoint from `phonehub_config.json`.
2. Check whether the exact ADB endpoint is already connected.
3. Reuse a live connection instead of reconnecting.
4. Verify phone identity before returning `READY`.
5. If no live connection exists, test Tailscale reachability.
6. If Tailscale is reachable, attempt `adb connect`.
7. Verify ADB state.
8. Verify model and/or serial.
9. Return a controlled status instead of crashing or hanging.

### executeCapability(action, parameters)

All PhoneHub capabilities must enter through this function.

It always calls `ensureRemoteConnection()` first.

Current supported action:

```python
executeCapability("battery")
```

Unsupported actions return a controlled `CONNECTION_FAILED` result.

## Battery Capability

The battery capability is the first end-to-end test of the architecture.

It runs:

```text
adb -s <tailscale-ip>:5555 shell dumpsys battery
```

It returns values such as:

- level
- status code
- health code
- temperature
- voltage
- USB powered
- AC powered
- wireless powered

Example successful response:

```json
{
  "status": "READY",
  "action": "battery",
  "battery": {
    "level": "82",
    "status_code": "2",
    "health_code": "2",
    "temperature_raw": "310",
    "voltage_mv": "4321",
    "usb_powered": "false",
    "ac_powered": "false",
    "wireless_powered": "false"
  }
}
```

## Configuration

`phonehub_config.json` must sit next to `phonehub_connection.py`.

Schema:

```json
{
  "phone": {
    "tailscale_ip": "YOUR_REAL_TAILSCALE_IP",
    "adb_port": 5555,
    "expected_model": "EXACT_STRING_FROM_ADB_GETPROP",
    "expected_serial": ""
  },
  "timeouts": {
    "tailscale": 5,
    "adb_connect": 8,
    "adb_command": 8
  }
}
```

Get the exact phone model with:

```powershell
adb shell getprop ro.product.model
```

If serial verification is desired:

```powershell
adb shell getprop ro.serialno
```

At least one of `expected_model` or `expected_serial` must be populated.

## Hardening Already Applied

The current connection layer includes:

- exact ADB serial matching using `serial == endpoint`
- `_endpoint(config)` inside protected `try/except` blocks
- safe timeout defaults
- subprocess timeouts
- controlled handling of missing commands
- Tailscale IPv4 validation against `100.64.0.0/10`
- explicit Windows Tailscale executable path
- identity verification before `READY`
- live connection reuse
- no hardcoded real phone IP in source code

## Security Notes

ADB-over-TCP on port 5555 is temporary.

PC-side Python code cannot by itself guarantee that TCP/5555 is exposed only on Tailscale. The phone's ADB settings and network configuration determine that exposure.

Current requirements:

- no router port-forwarding for TCP/5555
- use the user's private tailnet
- restrict access with Tailscale ACLs
- verify device identity before accepting the connection

The future PhoneHub Companion API should:

- bind to the Tailscale interface/address
- authenticate authorized controllers
- expose only explicit PhoneHub capabilities
- avoid raw unrestricted ADB as the primary control path

## Test Procedure

From PowerShell:

```powershell
cd C:\PhoneHub-V7

python -m py_compile .\phonehub_connection.py

python -c "import json; print(json.load(open('phonehub_config.json', encoding='utf-8')))"

where.exe adb

Test-Path "C:\Program Files\Tailscale\tailscale.exe"

python .\phonehub_connection.py
```

The final command should produce one controlled result:

- `READY`
- `PHONE_OFFLINE`
- `CONNECTION_FAILED`

If `READY` is achieved, the next capability to add is `status`.

If `PHONE_OFFLINE` or `CONNECTION_FAILED` is returned, fix only the connection layer before adding new capabilities.

## Next Development Order

```text
battery
   ↓
status
   ↓
screen
   ↓
camera
   ↓
apps
```

Each new capability must use:

```text
executeCapability(...)
      ↓
ensureRemoteConnection()
      ↓
capability implementation
```

No capability should call ADB directly outside the connection/capability layer.
