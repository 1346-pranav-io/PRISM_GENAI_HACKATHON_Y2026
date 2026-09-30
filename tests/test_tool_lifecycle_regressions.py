"""Regression tests: tool lifecycle under interruptions (uncancellable tools, authority, real tools, sessions)."""

import asyncio
from typing import List

import pytest

from src.agent_runtime.core.classifier import FastInterruptionClassifier
from src.agent_runtime.core.event_bus import EventBus
from src.agent_runtime.core.mock_llm import MockLLMProvider
from src.agent_runtime.core.runtime_engine import AgentRuntimeEngine
from src.agent_runtime.core.state_manager import StateManager
from src.agent_runtime.core.task_manager import TaskManager
from src.agent_runtime.core.tool_executor import ToolExecutor
from src.agent_runtime.core.tool_registry import ToolRegistry
from src.agent_runtime.core.trace_logger import TraceLogger
from src.agent_runtime.models.events import EventType, RuntimeEvent
from src.agent_runtime.models.llm_plan import LLMPlan
from src.agent_runtime.models.tasks import TaskStatus, TaskType
from src.agent_runtime.models.tools import ToolCallRequest, ToolCategory, ToolManifest
from src.agent_runtime.tools import SEARCH_FLIGHTS_TOOL, get_search_flights_executor

OLD = "OLD-MUMBAI-DATA"


@pytest.fixture
def rt():
    bus, sm, tm, reg = EventBus(), StateManager(), TaskManager(), ToolRegistry()
    llm = MockLLMProvider()
    engine = AgentRuntimeEngine(
        event_bus=bus, state_manager=sm, task_manager=tm,
        classifier=FastInterruptionClassifier(), tool_registry=reg,
        tool_executor=ToolExecutor(reg), llm_provider=llm, trace_logger=TraceLogger(),
    )
    events: List[RuntimeEvent] = []

    async def collect(evt):
        events.append(evt)

    bus.subscribe_all(collect)
    return {"engine": engine, "bus": bus, "sm": sm, "tm": tm, "reg": reg, "llm": llm, "events": events}


def _tool(rt, name, fn, category=ToolCategory.READ_ONLY):
    rt["reg"].register_tool(ToolManifest(name=name, description=name, category=category, parameters_schema={}), fn)


def _plan(rt, query, tool_names, response="Here you go."):
    rt["llm"].set_response_for_query(query, LLMPlan(
        intent="test",
        proposed_tool_calls=[
            ToolCallRequest(call_id=f"c_{n}", tool_name=n, arguments={}, origin_state_version=1) for n in tool_names
        ],
        assistant_response=response,
    ))


async def _say(rt, sid, text):
    await rt["bus"].publish(RuntimeEvent(
        session_id=sid, event_type=EventType.USER_TEXT,
        state_version=rt["sm"].get_current_version(sid), payload={"text": text},
    ))


def _finals(rt, sid=None):
    return [e for e in rt["events"] if e.event_type == EventType.AGENT_FINAL_RESPONSE
            and (sid is None or e.session_id == sid)]


def _stubborn(delay, value, log):
    """A tool that ignores cancellation: it swallows CancelledError and returns late anyway."""
    async def fn():
        loop = asyncio.get_running_loop()
        deadline = loop.time() + delay
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await asyncio.sleep(remaining)
            except asyncio.CancelledError:
                log.append("cancel-ignored")
        log.append("returned")
        return value
    return fn


def _shielded(delay, value, log):
    """A tool whose work is shielded from cancellation (non-cancellable third-party I/O)."""
    async def work():
        await asyncio.sleep(delay)
        log.append("work-done")
        return value

    async def fn():
        return await asyncio.shield(work())
    return fn


def _assert_old_data_never_in_finals(rt):
    for f in _finals(rt):
        assert OLD not in str(f.payload)
        for r in f.payload.get("tool_results", []):
            assert r["data"] != OLD


# 1 & 2: uncancellable READ_ONLY tool, then NEW_QUERY / CORRECTION


@pytest.mark.asyncio
@pytest.mark.parametrize("make_tool", [_stubborn, _shielded], ids=["stubborn", "shielded"])
@pytest.mark.parametrize("second", ["What's the weather in Paris", "No wait, change destination to Paris"],
                         ids=["new_query", "correction"])
async def test_uncancellable_readonly_result_never_reaches_final(rt, make_tool, second):
    log: List[str] = []
    _tool(rt, "search", make_tool(0.1, OLD, log))
    _plan(rt, "find flights to mumbai", ["search"])
    await rt["engine"].init_session("u1")
    await _say(rt, "u1", "find flights to mumbai")
    await asyncio.sleep(0.03)
    await _say(rt, "u1", second)
    await asyncio.sleep(0.3)

    finals = _finals(rt)
    assert len(finals) == 1, "only the new request's final response may be emitted"
    assert finals[0].state_version == rt["sm"].get_current_version("u1")
    assert "Paris" in finals[0].payload["text"]
    _assert_old_data_never_in_finals(rt)
    old_tool = [t for t in await rt["tm"].get_session_tasks("u1") if t.tool_name == "search"]
    for t in old_tool:
        assert not (t.status == TaskStatus.COMPLETED and t.result == OLD)


# 3: tool ignores cancellation and returns late after a bare version change


@pytest.mark.asyncio
async def test_late_result_after_version_change_is_not_used(rt):
    log: List[str] = []
    _tool(rt, "search", _stubborn(0.08, OLD, log))
    _plan(rt, "search mumbai", ["search"])
    await rt["engine"].init_session("u3")
    await _say(rt, "u3", "search mumbai")
    await asyncio.sleep(0.02)
    await rt["sm"].apply_delta("u3", slot_deltas={"destination": "Paris"})
    await asyncio.sleep(0.2)

    assert "returned" in log
    assert _finals(rt) == []
    [t] = [t for t in await rt["tm"].get_session_tasks("u3") if t.task_type == TaskType.TOOL_EXECUTION]
    assert t.status != TaskStatus.COMPLETED
    assert t.result != OLD
    _assert_old_data_never_in_finals(rt)


@pytest.mark.asyncio
async def test_stubborn_tool_after_stop_emits_nothing(rt):
    log: List[str] = []
    _tool(rt, "search", _stubborn(0.08, OLD, log))
    _plan(rt, "search mumbai", ["search"])
    await rt["engine"].init_session("u4")
    await _say(rt, "u4", "search mumbai")
    await asyncio.sleep(0.02)
    await _say(rt, "u4", "stop")
    await asyncio.sleep(0.2)
    assert _finals(rt) == []
    assert all(OLD not in str(e.payload) for e in rt["events"])


# 4: only the authoritative request gets a final response


@pytest.mark.asyncio
@pytest.mark.parametrize("second", ["What's the weather in Paris", "No wait, change destination to Paris"])
async def test_only_authoritative_request_gets_final(rt, second):
    async def slow():
        await asyncio.sleep(0.1)
        return OLD

    _tool(rt, "search", slow)
    _plan(rt, "find flights to mumbai", ["search"])
    await rt["engine"].init_session("a1")
    await _say(rt, "a1", "find flights to mumbai")
    await asyncio.sleep(0.03)
    marker = len(rt["events"])
    await _say(rt, "a1", second)
    await asyncio.sleep(0.3)

    after = [e for e in rt["events"][marker:] if e.event_type == EventType.AGENT_FINAL_RESPONSE]
    assert len(after) == 1 and len(_finals(rt)) == 1
    assert after[0].state_version == rt["sm"].get_current_version("a1")
    assert "Paris" in after[0].payload["text"]
    _assert_old_data_never_in_finals(rt)


# 5: end-to-end with the real search_flights tool


@pytest.mark.asyncio
@pytest.mark.parametrize("latency", [0.0, 0.1])
async def test_real_search_flights_correction_end_to_end(rt, latency):
    rt["llm"].latency_seconds = latency
    rt["reg"].register_tool(SEARCH_FLIGHTS_TOOL, await get_search_flights_executor())
    await rt["engine"].init_session("e2e")
    await _say(rt, "e2e", "Book a flight to Mumbai")
    await asyncio.sleep(0.02)
    marker = len(rt["events"])
    await _say(rt, "e2e", "Actually make it New York")
    await asyncio.sleep(0.5 + 2 * latency)

    state = rt["sm"].get_state("e2e") if not asyncio.iscoroutinefunction(rt["sm"].get_state) \
        else await rt["sm"].get_state("e2e")
    assert state.slots["destination"].value == "New York"

    after = [e for e in rt["events"][marker:] if e.event_type == EventType.AGENT_FINAL_RESPONSE]
    assert len(after) == 1 and len(_finals(rt)) == 1
    final = after[0]
    assert final.state_version == rt["sm"].get_current_version("e2e")
    searches = [r for r in final.payload["tool_results"] if r["tool_name"] == "search_flights"]
    assert searches and all(r["status"] == "COMPLETED" for r in searches)
    flights = [flight for r in searches for flight in r["data"]]
    assert flights, "search for New York must return flights"
    assert all(flight["to"] == "New York" for flight in flights)
    for f in _finals(rt):
        for r in f.payload.get("tool_results", []):
            assert all(fl.get("to") != "Mumbai" for fl in (r["data"] or []))

    own = {t.task_id: t for t in await rt["tm"].get_session_tasks("e2e")}
    for r in final.payload["tool_results"]:
        assert own[r["task_id"]].origin_state_version == final.state_version


# 6: concurrent sessions do not share tool results


@pytest.mark.asyncio
async def test_concurrent_sessions_tool_results_are_isolated(rt):
    async def weather():
        await asyncio.sleep(0.05)
        return {"temp_c": 7}

    _tool(rt, "weather", weather)
    _plan(rt, "oslo weather", ["weather"])
    for sid in ("sa", "sb"):
        await rt["engine"].init_session(sid)
    await asyncio.gather(_say(rt, "sa", "oslo weather"), _say(rt, "sb", "oslo weather"))
    await asyncio.sleep(0.2)

    for sid in ("sa", "sb"):
        [final] = _finals(rt, sid)
        own_ids = {t.task_id for t in await rt["tm"].get_session_tasks(sid)}
        assert final.payload["tool_results"]
        for r in final.payload["tool_results"]:
            assert r["task_id"] in own_ids
    ids_a = {r["task_id"] for r in _finals(rt, "sa")[0].payload["tool_results"]}
    ids_b = {r["task_id"] for r in _finals(rt, "sb")[0].payload["tool_results"]}
    assert ids_a.isdisjoint(ids_b)
