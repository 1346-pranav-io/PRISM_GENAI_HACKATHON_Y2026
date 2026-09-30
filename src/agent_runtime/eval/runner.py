"""Scenario runner that executes JSON scenario fixtures against the runtime.

Loads scenarios from evaluation/scenarios/*.json and drives them through
a fresh runtime instance, returning a structured result.
"""
import asyncio
import json
import pathlib
from typing import Any, Dict, List, Optional
from ..core.event_bus import EventBus
from ..core.runtime_engine import AgentRuntimeEngine
from ..core.state_manager import StateManager
from ..core.task_manager import TaskManager
from ..core.classifier import FastInterruptionClassifier
from ..core.tool_registry import ToolRegistry
from ..core.tool_executor import ToolExecutor
from ..core.mock_llm import MockLLMProvider
from ..core.trace_logger import TraceLogger
from ..models.events import EventType, RuntimeEvent
from ..tools import (
    ADD_CALENDAR_EVENT_TOOL, BOOK_FLIGHT_TOOL, GET_CALENDAR_EVENTS_TOOL, GET_WEATHER_TOOL, SEARCH_FLIGHTS_TOOL,
    get_add_event_executor, get_book_flight_executor, get_calendar_events_executor,
    get_search_flights_executor, get_weather_executor,
)
from ..models.trace import SessionTrace
from .metrics import MetricsCalculator, TraceEvaluationMetrics

# Project root: three levels up from eval/ (eval/ -> agent_runtime/ -> src/ -> project root)
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent.parent
SCENARIO_DIR = _PROJECT_ROOT / "evaluation" / "scenarios"

async def run_scenario(scenario_name: str) -> Dict[str, Any]:
    """Execute a single named scenario and return the result dict."""
    path = SCENARIO_DIR / f"{scenario_name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Scenario not found: {scenario_name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return await _run_scenario_data(scenario_name, data)

async def _run_scenario_data(name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    bus = EventBus()
    sm = StateManager()
    tm = TaskManager()
    clf = FastInterruptionClassifier()
    reg = ToolRegistry()
    # Scenarios run against the real domain tools (with their simulated latency).
    reg.register_tool(SEARCH_FLIGHTS_TOOL, await get_search_flights_executor())
    reg.register_tool(BOOK_FLIGHT_TOOL, await get_book_flight_executor())
    reg.register_tool(GET_WEATHER_TOOL, await get_weather_executor())
    reg.register_tool(ADD_CALENDAR_EVENT_TOOL, await get_add_event_executor())
    reg.register_tool(GET_CALENDAR_EVENTS_TOOL, await get_calendar_events_executor())
    tex = ToolExecutor(reg)
    llm = MockLLMProvider()
    trace = TraceLogger()
    engine = AgentRuntimeEngine(
        event_bus=bus, state_manager=sm, task_manager=tm,
        classifier=clf, tool_registry=reg, tool_executor=tex,
        llm_provider=llm, trace_logger=trace,
    )
    sid = data.get("session_id", f"run_{name}")
    await engine.init_session(sid)
    for step in data.get("steps", []):
        evt_type = EventType[step.get("event_type", "USER_TEXT")]
        ver = sm.get_current_version(sid)
        await bus.publish(RuntimeEvent(session_id=sid, event_type=evt_type, state_version=ver, payload=step.get("payload", {})))
        await asyncio.sleep(step.get("delay_seconds", 0.05))
    await asyncio.sleep(data.get("settle_seconds", 0.2))
    session_trace = await trace.get_session_trace(sid)
    metrics = MetricsCalculator.evaluate_trace(session_trace)
    expected = data.get("expected", {})
    checks = _evaluate_checks(metrics, expected, session_trace)
    return {
        "scenario": name,
        "passed": all(c["passed"] for c in checks),
        "metrics": metrics.model_dump(),
        "checks": checks,
    }

def _evaluate_checks(
    metrics: TraceEvaluationMetrics,
    expected: Dict[str, Any],
    session_trace: Optional[SessionTrace] = None,
) -> List[Dict[str, Any]]:
    events = session_trace.events if session_trace else []
    responses = sum(1 for e in events if e.event_type == EventType.AGENT_FINAL_RESPONSE)
    checks = []
    for key, val in expected.items():
        if key == "min_state_version":
            actual = metrics.final_state_version
            ok = actual >= val
        elif key == "tasks_cancelled":
            actual = metrics.total_tasks_cancelled
            ok = actual == val
        elif key == "version_monotonic":
            actual = metrics.version_strictly_monotonic
            ok = actual == val
        elif key == "has_cancelled_task":
            actual = metrics.total_tasks_cancelled > 0
            ok = actual == val
        elif key == "has_agent_response":
            actual = responses > 0
            ok = actual == val
        else:
            # An unrecognised expectation must not pass silently.
            actual = None
            ok = False
        checks.append({"check": key, "passed": ok, "expected": val, "actual": actual})
    return checks

def list_scenarios() -> List[str]:
    if not SCENARIO_DIR.exists():
        return []
    return [p.stem for p in SCENARIO_DIR.glob("*.json")]

async def run_all_scenarios() -> List[Dict[str, Any]]:
    results = []
    for name in list_scenarios():
        try:
            results.append(await run_scenario(name))
        except Exception as exc:
            results.append({"scenario": name, "passed": False, "error": str(exc)})
    return results
