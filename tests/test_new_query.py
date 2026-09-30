"""NEW_QUERY semantics: cancel prior tasks, reset prior intent/slots, the new request is authoritative."""

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
from src.agent_runtime.models.classifier import InterruptionCategory
from src.agent_runtime.models.events import EventType, RuntimeEvent
from src.agent_runtime.models.tasks import TaskRecord, TaskStatus, TaskType
from src.agent_runtime.tools import SEARCH_FLIGHTS_TOOL, get_search_flights_executor


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


async def _say(rt, sid, text):
    await rt["bus"].publish(RuntimeEvent(
        session_id=sid, event_type=EventType.USER_TEXT,
        state_version=rt["sm"].get_current_version(sid), payload={"text": text},
    ))


def _of(events, event_type):
    return [e for e in events if e.event_type == event_type]


@pytest.mark.asyncio
async def test_classifier_treats_independent_request_as_new_query():
    from src.agent_runtime.models.state import SessionState

    result = await FastInterruptionClassifier().classify("What's the weather in Paris", SessionState(session_id="s"))
    assert result.category == InterruptionCategory.NEW_QUERY


@pytest.mark.asyncio
async def test_new_query_cancels_inflight_reasoning_and_suppresses_its_response(rt):
    rt["llm"].latency_seconds = 0.15
    await rt["engine"].init_session("nq1")
    await _say(rt, "nq1", "tell me about Rome")
    await asyncio.sleep(0.03)
    await _say(rt, "nq1", "What's the weather in Paris")
    await asyncio.sleep(0.3)

    reasoning = [t for t in await rt["tm"].get_session_tasks("nq1") if t.task_type == TaskType.REASONING]
    assert [t.status for t in reasoning] == [TaskStatus.CANCELLED, TaskStatus.COMPLETED]
    finals = _of(rt["events"], EventType.AGENT_FINAL_RESPONSE)
    assert len(finals) == 1
    assert "Paris" in finals[0].payload["text"]
    assert finals[0].state_version == rt["sm"].get_current_version("nq1") == 2
    [cancel_evt] = _of(rt["events"], EventType.TASK_CANCELLED)
    assert reasoning[0].task_id in cancel_evt.payload["cancelled_task_ids"]


@pytest.mark.asyncio
async def test_new_query_cancels_running_tool_task(rt):
    async def slow_tool():
        await asyncio.sleep(5)

    await rt["engine"].init_session("nq2")
    await rt["tm"].spawn_task("nq2", TaskRecord(task_id="old_tool", task_type=TaskType.TOOL_EXECUTION, origin_state_version=1), slow_tool())
    await asyncio.sleep(0.01)
    await _say(rt, "nq2", "What's the weather in Paris")
    await asyncio.sleep(0.05)
    assert (await rt["tm"].get_task("old_tool")).status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_new_query_resets_prior_slots_and_intent(rt):
    rt["reg"].register_tool(SEARCH_FLIGHTS_TOOL, await get_search_flights_executor())
    await rt["engine"].init_session("nq3")
    await rt["sm"].apply_delta("nq3", slot_deltas={"origin": "Delhi", "destination": "Mumbai"}, intent="book_flight")
    await _say(rt, "nq3", "search flights to Tokyo")
    await asyncio.sleep(0.15)

    state = await rt["sm"].get_state("nq3")
    assert {k: v.value for k, v in state.slots.items()} == {"destination": "Tokyo"}
    assert state.current_intent is None
    [search] = [t for t in await rt["tm"].get_session_tasks("nq3") if t.tool_name == "search_flights"]
    assert search.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_new_query_tool_arguments_come_only_from_new_request(rt):
    seen = {}

    class Recorder(MockLLMProvider):
        async def plan_and_reason(self, session_state, conversation_history, available_tools, user_input):
            plan = await super().plan_and_reason(session_state, conversation_history, available_tools, user_input)
            seen["args"] = [c.arguments for c in plan.proposed_tool_calls]
            seen["slots_seen"] = {k: v.value for k, v in session_state.slots.items()}
            return plan

    rt["engine"].llm_provider = Recorder()
    rt["reg"].register_tool(SEARCH_FLIGHTS_TOOL, await get_search_flights_executor())
    await rt["engine"].init_session("nq4")
    await rt["sm"].apply_delta("nq4", slot_deltas={"origin": "Delhi", "destination": "Mumbai"})
    await _say(rt, "nq4", "search flights to Tokyo")
    await asyncio.sleep(0.1)
    assert seen["slots_seen"] == {}
    assert seen["args"] == [{"destination": "Tokyo"}]


@pytest.mark.asyncio
async def test_uncancellable_prior_result_is_rejected_after_new_query(rt):
    rt["llm"].latency_seconds = 0.1
    await rt["engine"].init_session("nq5")
    await rt["sm"].apply_delta("nq5", slot_deltas={"destination": "Mumbai"})
    # Prior reasoning outside TaskManager, so the new query cannot cancel it.
    prior = asyncio.create_task(rt["engine"]._execute_deliberate_path("nq5", "old request", 2))
    await asyncio.sleep(0.02)
    rt["llm"].latency_seconds = 0.0
    await _say(rt, "nq5", "What's the weather in Paris")
    await prior
    await asyncio.sleep(0.05)

    finals = _of(rt["events"], EventType.AGENT_FINAL_RESPONSE)
    assert [f.payload["text"] for f in finals] == ["Processed request: What's the weather in Paris"]
    stale = [e for e in _of(rt["events"], EventType.TASK_REJECTED_STALE) if e.payload.get("task_type") == "REASONING"]
    assert len(stale) == 1


@pytest.mark.asyncio
async def test_first_query_in_fresh_session_is_not_a_reset(rt):
    await rt["engine"].init_session("nq6")
    await _say(rt, "nq6", "hello")
    await asyncio.sleep(0.05)
    assert rt["sm"].get_current_version("nq6") == 1
    assert _of(rt["events"], EventType.TASK_CANCELLED) == []


@pytest.mark.asyncio
async def test_backchannel_does_not_reset_context(rt):
    await rt["engine"].init_session("nq7")
    await rt["sm"].apply_delta("nq7", slot_deltas={"destination": "Mumbai"}, intent="book_flight")
    await _say(rt, "nq7", "uh-huh")
    await asyncio.sleep(0.05)
    state = await rt["sm"].get_state("nq7")
    assert state.slots["destination"].value == "Mumbai"
    assert state.current_intent == "book_flight"


@pytest.mark.asyncio
async def test_correction_keeps_other_slots(rt):
    await rt["engine"].init_session("nq8")
    await rt["sm"].apply_delta("nq8", slot_deltas={"origin": "Delhi", "destination": "Mumbai"}, intent="book_flight")
    await _say(rt, "nq8", "No wait, change destination to Paris")
    await asyncio.sleep(0.05)
    state = await rt["sm"].get_state("nq8")
    assert {k: v.value for k, v in state.slots.items()} == {"origin": "Delhi", "destination": "Paris"}
    assert state.current_intent == "book_flight"


# ---------------------------------------------------------------------------
# StateManager.apply_delta(reset_context=True)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_context_clears_slots_and_intent_and_bumps_version():
    sm = StateManager()
    await sm.apply_delta("r", slot_deltas={"a": 1, "b": 2}, intent="old")
    state = await sm.apply_delta("r", slot_deltas={"c": 3}, reset_context=True)
    assert set(state.slots) == {"c"}
    assert state.current_intent is None
    assert state.state_version == 3


@pytest.mark.asyncio
async def test_reset_context_on_empty_state_is_noop():
    sm = StateManager()
    await sm.get_state("r0")
    state = await sm.apply_delta("r0", reset_context=True)
    assert state.state_version == 1


@pytest.mark.asyncio
async def test_default_apply_delta_still_merges():
    sm = StateManager()
    await sm.apply_delta("m", slot_deltas={"a": 1}, intent="i")
    state = await sm.apply_delta("m", slot_deltas={"b": 2})
    assert set(state.slots) == {"a", "b"}
    assert state.current_intent == "i"
