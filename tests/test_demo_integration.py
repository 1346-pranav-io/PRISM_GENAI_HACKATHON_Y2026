"""Hosting/demo integration: reconnects keep context; demo latency is configurable."""

import pytest
from fastapi.testclient import TestClient

from src.agent_runtime.server import app as app_module
from src.agent_runtime.server.app import create_app


def _read_until(ws, event_type):
    for _ in range(50):
        msg = ws.receive_json()
        if msg["event_type"] == event_type:
            return msg
    raise AssertionError(f"{event_type} not received")


def test_websocket_reconnect_keeps_conversation_history():
    with TestClient(create_app()) as client:
        with client.websocket_connect("/ws/reconnect_s1") as ws:
            ws.send_json({"text": "Book a flight to Mumbai"})
            _read_until(ws, "AGENT_FINAL_RESPONSE")
        with client.websocket_connect("/ws/reconnect_s1") as ws:
            ws.send_json({"text": "Actually make it New York"})
            final = _read_until(ws, "AGENT_FINAL_RESPONSE")
        engine = app_module._server_runtime["engine"]
        users = [t["content"] for t in engine._history["reconnect_s1"] if t["role"] == "user"]
        assert users == ["Book a flight to Mumbai", "Actually make it New York"]
        state = client.get("/api/v1/sessions/reconnect_s1/state").json()
        assert state["slots"]["destination"]["value"] == "New York"
        flights = next(r["data"] for r in final["tool_results"] if r["tool_name"] == "search_flights")
        assert flights and {f["to"] for f in flights} == {"New York"}


@pytest.mark.parametrize("env_value, expected", [(None, 0.05), ("1.5", 1.5)])
def test_mock_llm_latency_is_configurable(monkeypatch, env_value, expected):
    if env_value is None:
        monkeypatch.delenv("AGENT_LLM_LATENCY_SECONDS", raising=False)
    else:
        monkeypatch.setenv("AGENT_LLM_LATENCY_SECONDS", env_value)
    with TestClient(create_app()):
        assert app_module._server_runtime["engine"].llm_provider.latency_seconds == expected
