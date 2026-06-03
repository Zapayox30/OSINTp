"""Tests for the SSE streaming endpoint (private IP path — no network)."""

from __future__ import annotations


def test_stream_private_ip_emits_events(client):
    resp = client.get("/api/v1/stream", params={"target": "10.0.0.1"})
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    body = resp.text
    # Contract: start -> meta -> result -> summary -> done
    assert "event: start" in body
    assert '"detected_type": "ip"' in body
    assert "event: meta" in body
    assert "event: result" in body
    assert "Classification" in body
    assert "event: summary" in body
    assert "event: done" in body


def test_stream_forced_username_validation_error(client):
    # Forcing an invalid username surfaces an 'error' event, not a 500.
    resp = client.get(
        "/api/v1/stream", params={"target": "bad!name", "type": "username"}
    )
    assert resp.status_code == 200
    assert "event: error" in resp.text
    assert "event: done" in resp.text
