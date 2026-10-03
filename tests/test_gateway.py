from phonehub.gateway import EventLedger, EventTokenizer, GatewayEvent


def test_gateway_event_tokenization():
    event = GatewayEvent(
        event_type="network_session",
        device_id="samsung",
        source="tailscale",
        state="connected",
        timestamp="2026-10-03T10:00:00+00:00",
        attributes={"latency_ms": 205, "service": "rustdesk"},
    )
    line = EventTokenizer().encode_line(event)

    assert "<EVT:NETWORK_SESSION>" in line
    assert "<DEV:samsung>" in line
    assert "<SRC:TAILSCALE>" in line
    assert "<STATE:CONNECTED>" in line
    assert "<LATENCY_MS:205>" in line
    assert "<SERVICE:rustdesk>" in line


def test_gateway_ledger_round_trip(tmp_path):
    ledger = EventLedger(tmp_path / "events.jsonl")
    event = GatewayEvent(
        event_type="service_state",
        device_id="samsung",
        source="rustdesk",
        state="active",
        timestamp="2026-10-03T10:00:00+00:00",
    )

    ledger.append(event)
    recent = ledger.read_recent()

    assert len(recent) == 1
    assert recent[0]["event_type"] == "service_state"
    assert recent[0]["device_id"] == "samsung"
    assert recent[0]["source"] == "rustdesk"
