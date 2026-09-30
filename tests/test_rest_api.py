"""REST API tests: routes are mounted under /api/v1 and share the WebSocket runtime."""

import pytest
from fastapi.testclient import TestClient

from src.agent_runtime.server import app as app_module
from src.agent_runtime.server.app import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready(client):
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {"ready": True, "engine_initialized": True}


def test_session_init_message_state_trace_tasks(client):
    sid = "rest_s01"
    assert client.post(f"/api/v1/sessions/{sid}/init").json() == {"session_id": sid, "status": "initialized"}

    r = client.post(f"/api/v1/sessions/{sid}/message", json={"session_id": sid, "text": "change destination to London"})
    assert r.status_code == 200
    assert r.json()["status"] == "queued"

    state = client.get(f"/api/v1/sessions/{sid}/state").json()
    assert state["session_id"] == sid
    assert state["state_version"] >= 2
    assert state["slots"]["destination"]["value"] == "London"

    trace = client.get(f"/api/v1/sessions/{sid}/trace").json()
    types = [e["event_type"] for e in trace["events"]]
    assert "USER_TEXT" in types and "FAST_ACK" in types

    assert sid in client.get("/api/v1/debug/sessions").json()["active_sessions"]
    tasks = client.get(f"/api/v1/debug/tasks/{sid}").json()["tasks"]
    assert any(t["task_type"] == "REASONING" for t in tasks)


def test_unknown_scenario_is_404(client):
    assert client.post("/api/v1/scenarios/does_not_exist/run").status_code == 404


def test_scenario_endpoint_runs(client):
    r = client.post("/api/v1/scenarios/explicit_correction/run")
    assert r.status_code == 200
    body = r.json()
    assert body["events"] > 0
    assert body["final_version"] >= 3


def test_rest_uses_the_lifespan_runtime(client):
    assert client.app.state.runtime is app_module._server_runtime
    assert client.app.state.runtime is not None


def test_rest_and_websocket_share_sessions(client):
    sid = "shared_s01"
    with client.websocket_connect(f"/ws/{sid}") as ws:
        # Session created by the WebSocket is visible over REST.
        assert sid in client.get("/api/v1/debug/sessions").json()["active_sessions"]

        # A message posted over REST reaches the WebSocket client of that session.
        client.post(f"/api/v1/sessions/{sid}/message", json={"session_id": sid, "text": "via rest"})
        first = ws.receive_json()
        assert first["event_type"] == "USER_TEXT"
        assert first["text"] == "via rest"
        assert first["session_id"] == sid


def test_rest_returns_503_without_runtime():
    app = create_app()
    client = TestClient(app)  # no context manager: lifespan never runs
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/health/ready").status_code == 503
