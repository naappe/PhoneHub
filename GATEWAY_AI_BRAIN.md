# PhoneHub Gateway + AI Brain V0.1

## Goal

PhoneHub becomes the user's clearance point between observable device/network
signals and the AI brain.

The AI does not receive prose summaries as its primary evidence. It receives
canonical structured events, plus a compact token representation derived from
those events.

## V0.1 architecture

```text
Tailscale / RustDesk / AndroidBridge collectors
                  |
                  v
          GatewayEvent normalizer
                  |
          +-------+--------+
          |                |
          v                v
   append-only ledger   EventTokenizer
          |                |
          +-------+--------+
                  v
               AI Brain
                  |
          reasoning / advice
                  |
             user approval
                  |
             safe action
```

## Important boundary

The gateway does not decrypt third-party encrypted payloads. For RustDesk and
Tailscale it can initially record connection metadata such as service state,
peer, port, timing, latency and byte counts.

Notification, call, GPS, battery and other phone semantics should arrive as
explicit AndroidBridge events collected with Android permissions.

## Canonical event

```json
{
  "event_type": "network_session",
  "device_id": "samsung",
  "source": "tailscale",
  "state": "connected",
  "timestamp": "2026-10-03T10:00:00+00:00",
  "event_id": "...",
  "attributes": {
    "service": "rustdesk",
    "latency_ms": 205
  }
}
```

The tokenizer converts this to a model-facing symbolic stream such as:

```text
<EVT:NETWORK_SESSION> <DEV:samsung> <SRC:TAILSCALE>
<T:2026-10-03T10:00:00+00:00> <STATE:CONNECTED>
<LATENCY_MS:205> <SERVICE:rustdesk>
```

## Control rule

V0.1 is observe-only. The AI can analyze and recommend, but it cannot execute
device actions. Execution will be added later behind explicit policy and user
approval.

## Next implementation order

1. Tailscale reachability collector
2. RustDesk process/session collector
3. AndroidBridge event intake
4. rolling context builder for the AI brain
5. user-approved action dispatcher
