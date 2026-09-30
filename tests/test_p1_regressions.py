"""Regression tests for P1 fixes: history, corrections, mock planning, and the evaluation package."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from src.agent_runtime.core.classifier import FastInterruptionClassifier
from src.agent_runtime.core.event_bus import EventBus
from src.agent_runtime.core.gemini_live import GeminiLiveProvider
from src.agent_runtime.core.mock_llm import MockLLMProvider
from src.agent_runtime.core.providers.openai_llm import OpenAILLMProvider
from src.agent_runtime.core.runtime_engine import AgentRuntimeEngine
from src.agent_runtime.core.state_manager import StateManager
from src.agent_runtime.core.task_manager import TaskManager
from src.agent_runtime.core.tool_executor import ToolExecutor
from src.agent_runtime.core.tool_registry import ToolRegistry
from src.agent_runtime.core.trace_logger import TraceLogger
from src.agent_runtime.eval import runner as scenario_runner
from src.agent_runtime.eval.metrics import MetricsCalculator
from src.agent_runtime.models.classifier import InterruptionCategory
from src.agent_runtime.models.events import EventType, RuntimeEvent
from src.agent_runtime.models.llm_plan import LLMPlan
from src.agent_runtime.models.state import SessionState, SlotValue
from src.agent_runtime.models.tasks import TaskStatus, TaskType
from src.agent_runtime.models.tools import ToolCallRequest, ToolCategory, ToolManifest
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


async def _say(bus, sm, sid, text):
    await bus.publish(RuntimeEvent(
        session_id=sid, event_type=EventType.USER_TEXT,
        state_version=sm.get_current_version(sid), payload={"text": text},
    ))


def _state_with(**slots):
    now = datetime.now(timezone.utc)
    values = {}
    for i, (key, value) in enumerate(slots.items()):
        values[key] = SlotValue(key=key, value=value, source_state_version=2 + i, updated_at=now + timedelta(seconds=i))
    return SessionState(session_id="s", state_version=1 + len(slots), slots=values)


# ---------------------------------------------------------------------------
# P1.1 — conversation history holds each user turn exactly once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_records_user_turn_once(rt):
    await rt["engine"].init_session("h1")
    await _say(rt["bus"], rt["sm"], "h1", "hello")
    await asyncio.sleep(0.05)
    await _say(rt["bus"], rt["sm"], "h1", "how are you")
    await asyncio.sleep(0.05)
    history = rt["engine"]._history["h1"]
    user_turns = [t["content"] for t in history if t["role"] == "user"]
    assert user_turns == ["hello", "how are you"]
    assert [t["role"] for t in history] == ["user", "assistant", "user", "assistant"]


@pytest.mark.asyncio
async def test_llm_sees_current_turn_once_in_history(rt):
    seen = {}

    class Recorder(MockLLMProvider):
        async def plan_and_reason(self, session_state, conversation_history, available_tools, user_input):
            seen["history"] = [dict(t) for t in conversation_history]
            return await super().plan_and_reason(session_state, conversation_history, available_tools, user_input)

    rt["engine"].llm_provider = Recorder()
    await rt["engine"].init_session("h2")
    await _say(rt["bus"], rt["sm"], "h2", "hello")
    await asyncio.sleep(0.05)
    assert seen["history"] == [{"role": "user", "content": "hello"}]


@pytest.mark.asyncio
async def test_history_bounded_at_intake(rt):
    await rt["engine"].init_session("h3")
    for i in range(30):
        await _say(rt["bus"], rt["sm"], "h3", "uh-huh")  # backchannels never reach the slow path
    assert len(rt["engine"]._history["h3"]) == 20


def test_openai_messages_contain_current_turn_once():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "search flights"},
    ]
    messages = OpenAILLMProvider(api_key=None)._build_messages(_state_with(), history, "search flights")
    assert [m["content"] for m in messages].count("search flights") == 1
    assert messages[-1] == {"role": "user", "content": "search flights"}
    # History is sent as chat turns only, not duplicated into the system context.
    assert "hello" not in messages[1]["content"]


def test_gemini_contents_contain_current_turn_once():
    history = [{"role": "user", "content": "search flights"}]
    contents = GeminiLiveProvider(api_key=None)._build_contents(_state_with(), history, "search flights")
    assert contents[0]["parts"][0]["text"].count("search flights") == 1


# ---------------------------------------------------------------------------
# P1.4 — correction handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("text, expected", [
    ("Actually make it New York", {"destination": "New York"}),
    ("No, London", {"destination": "London"}),
    ("No, to Delhi instead", {"destination": "Delhi"}),
    ("wait, change it to Rome", {"destination": "Rome"}),
    ("Actually Mumbai", {}),                       # same value: nothing to change
    ("actually, can you check hotels", {}),        # not a slot value
    ("No wait, change destination to Paris", {"destination": "Paris"}),
])
async def test_implicit_correction_targets_latest_slot(text, expected):
    result = await FastInterruptionClassifier().classify(text, _state_with(destination="Mumbai"))
    assert result.category == InterruptionCategory.CORRECTION
    assert result.extracted_deltas == expected


@pytest.mark.asyncio
async def test_implicit_correction_picks_most_recent_slot():
    state = _state_with(destination="Mumbai", origin="Delhi")  # origin updated last
    result = await FastInterruptionClassifier().classify("Actually make it Pune", state)
    assert result.extracted_deltas == {"origin": "Pune"}


@pytest.mark.asyncio
async def test_implicit_correction_without_slots_extracts_nothing():
    result = await FastInterruptionClassifier().classify("Actually make it New York", _state_with())
    assert result.category == InterruptionCategory.CORRECTION
    assert result.extracted_deltas == {}


@pytest.mark.asyncio
async def test_go_on_is_backchannel():
    result = await FastInterruptionClassifier().classify("go on", _state_with())
    assert result.category == InterruptionCategory.BACKCHANNEL


@pytest.mark.asyncio
@pytest.mark.parametrize("llm_latency", [0.0, 0.1])
async def test_correction_applies_regardless_of_timing(rt, llm_latency):
    """Whether the correction lands before or after the first plan sets the slot, New York wins."""
    rt["reg"].register_tool(SEARCH_FLIGHTS_TOOL, await get_search_flights_executor())
    rt["llm"].latency_seconds = llm_latency
    sid = f"corr_{llm_latency}"
    await rt["engine"].init_session(sid)
    await _say(rt["bus"], rt["sm"], sid, "Book a flight to Mumbai")
    await asyncio.sleep(0.02)
    await _say(rt["bus"], rt["sm"], sid, "Actually make it New York")
    await asyncio.sleep(0.4)

    state = await rt["sm"].get_state(sid)
    assert state.slots["destination"].value == "New York"
    assert any(e.event_type == EventType.TASK_CANCELLED for e in rt["events"])
    # No response reasoned before the correction may be delivered after it.
    correction_at = next(
        i for i, e in enumerate(rt["events"])
        if e.event_type == EventType.USER_TEXT and e.payload.get("text") == "Actually make it New York"
    )
    finals_after = [e for e in rt["events"][correction_at:] if e.event_type == EventType.AGENT_FINAL_RESPONSE]
    assert len(finals_after) == 1
    assert finals_after[0].state_version == state.state_version
    if llm_latency > 0:
        # The first plan was still thinking when corrected: it must never answer.
        finals = [e for e in rt["events"] if e.event_type == EventType.AGENT_FINAL_RESPONSE]
        assert finals == finals_after
    searches = [t for t in await rt["tm"].get_session_tasks(sid) if t.tool_name == "search_flights"]
    assert searches[-1].status == TaskStatus.COMPLETED
    assert all(t.status == TaskStatus.CANCELLED for t in searches[:-1])


@pytest.mark.asyncio
async def test_correction_without_delta_cancels_inflight_reasoning(rt):
    rt["llm"].latency_seconds = 0.2
    await rt["engine"].init_session("corr_nodelta")
    await _say(rt["bus"], rt["sm"], "corr_nodelta", "tell me something")
    await asyncio.sleep(0.02)
    await _say(rt["bus"], rt["sm"], "corr_nodelta", "No wait")
    await asyncio.sleep(0.3)
    reasoning = [t for t in await rt["tm"].get_session_tasks("corr_nodelta") if t.task_type == TaskType.REASONING]
    assert reasoning[0].status == TaskStatus.CANCELLED
    assert rt["sm"].get_current_version("corr_nodelta") == 2


@pytest.mark.asyncio
async def test_plan_slot_delta_does_not_stale_its_own_state_modifying_tool(rt):
    async def book(flight: str = ""):
        return {"booked": flight}

    rt["reg"].register_tool(
        ToolManifest(name="book", description="b", category=ToolCategory.STATE_MODIFYING, parameters_schema={}),
        book,
    )
    rt["llm"].set_response_for_query("book it", LLMPlan(
        extracted_slots={"destination": "Rome"},
        proposed_tool_calls=[ToolCallRequest(call_id="c1", tool_name="book", arguments={"flight": "AI1"}, origin_state_version=1)],
        assistant_response="Booking.",
    ))
    await rt["engine"].init_session("own_tool")
    await _say(rt["bus"], rt["sm"], "own_tool", "book it")
    await asyncio.sleep(0.1)
    [task] = [t for t in await rt["tm"].get_session_tasks("own_tool") if t.task_type == TaskType.TOOL_EXECUTION]
    assert task.status == TaskStatus.COMPLETED
    assert task.origin_state_version == 2
    assert task.result == {"booked": "AI1"}


@pytest.mark.asyncio
async def test_mock_llm_builds_arguments_from_tool_schema():
    llm = MockLLMProvider()
    plan = await llm.plan_and_reason(
        session_state=_state_with(), conversation_history=[],
        available_tools=[SEARCH_FLIGHTS_TOOL], user_input="Find flights from Seattle to Tokyo",
    )
    assert plan.extracted_slots == {"destination": "Tokyo", "origin": "Seattle"}
    assert plan.proposed_tool_calls[0].arguments == {"destination": "Tokyo", "origin": "Seattle"}

    schemaless = ToolManifest(name="search_flights", description="d", category=ToolCategory.READ_ONLY, parameters_schema={"type": "object"})
    plan = await llm.plan_and_reason(
        session_state=_state_with(), conversation_history=[],
        available_tools=[schemaless], user_input="search flights to Tokyo",
    )
    assert plan.proposed_tool_calls[0].arguments == {"query": "search flights to Tokyo"}


@pytest.mark.asyncio
async def test_mock_llm_does_not_repropose_unchanged_slot():
    plan = await MockLLMProvider().plan_and_reason(
        session_state=_state_with(destination="Paris"), conversation_history=[],
        available_tools=[], user_input="change destination to Paris",
    )
    assert plan.extracted_slots == {}


# ---------------------------------------------------------------------------
# P1.5 — evaluation package and scenario checks
# ---------------------------------------------------------------------------


def test_evaluation_package_imports():
    import evaluation

    assert set(evaluation.list_scenarios()) >= {
        "backchannel_flood", "cancellation_cascade", "explicit_correction", "rapid_barge_in",
    }
    assert callable(evaluation.run_all_scenarios)
    assert evaluation.BenchmarkSuite is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", scenario_runner.list_scenarios())
async def test_json_scenario_passes(name):
    result = await scenario_runner.run_scenario(name)
    failing = [c for c in result["checks"] if not c["passed"]]
    assert result["passed"], failing
    assert result["checks"], "scenario must declare at least one expectation"


def _trace(*event_types):
    from src.agent_runtime.models.trace import SessionTrace

    now = datetime.now(timezone.utc)
    events = [RuntimeEvent(session_id="t", event_type=et, state_version=1) for et in event_types]
    return SessionTrace(session_id="t", events=events, start_time=now, final_state_version=1)


def test_has_agent_response_check_is_real():
    silent = _trace(EventType.USER_TEXT, EventType.FAST_ACK)
    [check] = scenario_runner._evaluate_checks(MetricsCalculator.evaluate_trace(silent), {"has_agent_response": True}, silent)
    assert check["passed"] is False

    answered = _trace(EventType.USER_TEXT, EventType.AGENT_FINAL_RESPONSE)
    [check] = scenario_runner._evaluate_checks(MetricsCalculator.evaluate_trace(answered), {"has_agent_response": True}, answered)
    assert check["passed"] is True


def test_unknown_scenario_expectation_fails():
    trace = _trace(EventType.USER_TEXT)
    [check] = scenario_runner._evaluate_checks(MetricsCalculator.evaluate_trace(trace), {"typo_check": 1}, trace)
    assert check["passed"] is False
