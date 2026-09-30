"""WebSocket transport tests against the real FastAPI app (lifespan runtime)."""

import time

import pytest
from fastapi.testclient import TestClient

from src.agent_runtime.server import app as app_module
from src.agent_runtime.server.app import create_app


def _read_until(ws, event_type, max_messages=50):
    """Collect messages until one with the given event_type arrives."""
    seen = []
    for _ in range(max_messages):
        msg = ws.receive_json()
        seen.append(msg)
        if msg["event_type"] == event_type:
            return seen
    raise AssertionError(f"{event_type} not received; got {[m['event_type'] for m in seen]}")


def _read_until_text(ws, text, max_messages=50):
    """Collect messages until the USER_TEXT echo carrying `text` arrives."""
    seen = []
    for _ in range(max_messages):
        msg = ws.receive_json()
        seen.append(msg)
        if msg["event_type"] == "USER_TEXT" and msg.get("text") == text:
            return seen
    raise AssertionError(f"USER_TEXT {text!r} not received")


def _global_subscriber_count():
    return len(app_module._server_runtime["bus"]._global_subscribers)


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_ws_connects_and_echoes(client):
    with client.websocket_connect("/ws/conn_s01") as ws:
        ws.send_json({"type": "user_text", "text": "hello"})
        msgs = _read_until(ws, "AGENT_FINAL_RESPONSE")
        assert msgs[0]["event_type"] == "USER_TEXT"
        assert msgs[0]["text"] == "hello"


def test_ws_uses_url_session_id(client):
    with client.websocket_connect("/ws/url_sid_42") as ws:
        ws.send_json({"type": "user_text", "text": "hello"})
        msgs = _read_until(ws, "AGENT_FINAL_RESPONSE")
        assert {m["session_id"] for m in msgs} == {"url_sid_42"}
    sm = app_module._server_runtime["sm"]
    assert "url_sid_42" in sm._states
    assert not any(k.startswith("ws_") for k in sm._states)


def test_ws_event_delivered_exactly_once(client):
    with client.websocket_connect("/ws/once_s01") as ws:
        ws.send_json({"type": "user_text", "text": "hello"})
        _read_until(ws, "AGENT_FINAL_RESPONSE")
        # Any duplicate of the first turn's events would arrive before this marker.
        ws.send_json({"type": "user_text", "text": "marker"})
        msgs = _read_until_text(ws, "marker")
        types = [m["event_type"] for m in msgs]
        assert types == ["USER_TEXT"], f"unexpected extra events: {types}"


def test_ws_first_turn_has_no_duplicates(client):
    with client.websocket_connect("/ws/once_s02") as ws:
        ws.send_json({"type": "user_text", "text": "hello"})
        msgs = _read_until(ws, "AGENT_FINAL_RESPONSE")
        types = [m["event_type"] for m in msgs]
        assert types.count("USER_TEXT") == 1
        assert types.count("FAST_ACK") == 1
        assert types.count("AGENT_FINAL_RESPONSE") == 1


def test_ws_two_sessions_isolated(client):
    with client.websocket_connect("/ws/iso_a") as ws_a, client.websocket_connect("/ws/iso_b") as ws_b:
        ws_a.send_json({"type": "user_text", "text": "from A"})
        msgs_a = _read_until(ws_a, "AGENT_FINAL_RESPONSE")
        assert {m["session_id"] for m in msgs_a} == {"iso_a"}

        # If A's events leaked, they would be queued on B ahead of B's own echo.
        ws_b.send_json({"type": "user_text", "text": "from B"})
        first_b = ws_b.receive_json()
        assert first_b["event_type"] == "USER_TEXT"
        assert first_b["text"] == "from B"
        assert first_b["session_id"] == "iso_b"
        msgs_b = [first_b] + _read_until(ws_b, "AGENT_FINAL_RESPONSE")
        assert {m["session_id"] for m in msgs_b} == {"iso_b"}
        assert all(m.get("text") != "from A" for m in msgs_b)


def test_ws_disconnect_unsubscribes(client):
    baseline = _global_subscriber_count()
    with client.websocket_connect("/ws/cleanup_s01") as ws:
        ws.send_json({"type": "user_text", "text": "hello"})
        _read_until(ws, "AGENT_FINAL_RESPONSE")
        assert _global_subscriber_count() == baseline + 1
    deadline = time.monotonic() + 2.0
    while _global_subscriber_count() != baseline and time.monotonic() < deadline:
        time.sleep(0.01)
    assert _global_subscriber_count() == baseline
    per_type = app_module._server_runtime["bus"]._subscribers
    assert all(
        getattr(h, "__self__", None) is None or type(h.__self__).__name__ != "WebSocketSession"
        for handlers in per_type.values()
        for h in handlers
    )
