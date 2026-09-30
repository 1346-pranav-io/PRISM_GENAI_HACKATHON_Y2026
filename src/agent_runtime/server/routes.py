"""FastAPI REST routes for health, debug/trace, and scenario control."""
import asyncio
import json
import logging
import pathlib
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from ..models.events import EventType, RuntimeEvent
logger = logging.getLogger(__name__)
router = APIRouter()

# Project root: two levels up from server/ (server/ -> agent_runtime/ -> src/)
_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent

# ------------------------------------------------------------------
# Runtime access: routes share the runtime built by the app lifespan,
# so REST and WebSocket clients see the same sessions, tasks and traces.
# ------------------------------------------------------------------
def get_runtime(request: Request) -> Dict[str, Any]:
    runtime = getattr(request.app.state, "runtime", None)
    if not runtime:
        raise HTTPException(status_code=503, detail="Runtime not initialized")
    return runtime

# ------------------------------------------------------------------
# Request/response models
# ------------------------------------------------------------------
class UserMessageRequest(BaseModel):
    session_id: str
    text: str

class SessionStateResponse(BaseModel):
    session_id: str
    state_version: int
    status: str
    current_intent: str | None = None
    slots: Dict[str, Any]

# ------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------
@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "agent-runtime"}

@router.get("/health/ready")
async def ready(rt: Dict[str, Any] = Depends(get_runtime)) -> Dict[str, Any]:
    return {"ready": True, "engine_initialized": rt.get("engine") is not None}

@router.post("/sessions/{session_id}/init")
async def init_session(session_id: str, rt: Dict[str, Any] = Depends(get_runtime)) -> Dict[str, str]:
    await rt["engine"].init_session(session_id)
    return {"session_id": session_id, "status": "initialized"}

@router.post("/sessions/{session_id}/message")
async def send_message(session_id: str, body: UserMessageRequest, rt: Dict[str, Any] = Depends(get_runtime)) -> Dict[str, Any]:
    ver = rt["sm"].get_current_version(session_id)
    await rt["bus"].publish(RuntimeEvent(
        session_id=session_id,
        event_type=EventType.USER_TEXT,
        state_version=ver,
        payload={"text": body.text},
    ))
    await asyncio.sleep(0.05)
    state = await rt["sm"].get_state(session_id)
    return {"session_id": session_id, "state_version": state.state_version, "status": "queued"}

@router.get("/sessions/{session_id}/state")
async def get_session_state(session_id: str, rt: Dict[str, Any] = Depends(get_runtime)) -> SessionStateResponse:
    state = await rt["sm"].get_state(session_id)
    return SessionStateResponse(
        session_id=state.session_id,
        state_version=state.state_version,
        status=state.status.value,
        current_intent=state.current_intent,
        slots={k: v.model_dump() for k, v in state.slots.items()},
    )

@router.get("/sessions/{session_id}/trace")
async def get_session_trace(session_id: str, rt: Dict[str, Any] = Depends(get_runtime)) -> Dict[str, Any]:
    trace = await rt["trace"].get_session_trace(session_id)
    return {
        "session_id": session_id,
        "events": [e.model_dump(mode="json") for e in (trace.events if trace else [])],
    }

@router.get("/debug/sessions")
async def list_sessions(rt: Dict[str, Any] = Depends(get_runtime)) -> Dict[str, Any]:
    return {"active_sessions": list(rt["sm"]._states.keys())}

@router.get("/debug/tasks/{session_id}")
async def list_tasks(session_id: str, rt: Dict[str, Any] = Depends(get_runtime)) -> Dict[str, Any]:
    tasks = await rt["tm"].get_session_tasks(session_id)
    return {"tasks": [t.model_dump() for t in tasks]}

@router.post("/scenarios/{scenario_name}/run")
async def run_scenario(scenario_name: str, rt: Dict[str, Any] = Depends(get_runtime)) -> Dict[str, Any]:
    """Run a named scenario from the evaluation/scenarios/ directory."""
    scenario_path = _ROOT / "evaluation" / "scenarios" / f"{scenario_name}.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario_name}' not found")
    data = json.loads(scenario_path.read_text(encoding="utf-8"))
    sid = data.get("session_id", f"scenario_{scenario_name}")
    await rt["engine"].init_session(sid)
    for step in data.get("steps", []):
        await rt["bus"].publish(RuntimeEvent(
            session_id=sid,
            event_type=EventType[step.get("event_type", "USER_TEXT")],
            state_version=rt["sm"].get_current_version(sid),
            payload=step.get("payload", {}),
        ))
        await asyncio.sleep(step.get("delay_seconds", 0.05))
    await asyncio.sleep(data.get("settle_seconds", 0.2))
    trace = await rt["trace"].get_session_trace(sid)
    return {"scenario": scenario_name, "session_id": sid, "events": len(trace.events), "final_version": trace.final_state_version}
