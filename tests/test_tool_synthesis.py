"""The deliberate path waits for its tools and synthesizes the reply from current-version results."""

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
    rt["reg"].register_tool(
        ToolManifest(name=name, description=name, category=category, parameters_schema={}), fn,
    )


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


def _finals(rt):
    return [e for e in rt["events"] if e.event_type == EventType.AGENT_FINAL_RESPONSE]


async def _tool_tasks(rt, sid):
    return [t for t in await rt["tm"].get_session_tasks(sid) if t.task_type == TaskType.TOOL_EXECUTION]


async def _reasoning(rt, sid):
    return [t for t in await rt["tm"].get_session_tasks(sid) if t.task_type == TaskType.REASONING]


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_tool_produces_synthesized_final_response(rt):
    async def weather():
        await asyncio.sleep(0.05)
        return {"city": "Oslo", "temp_c": 7}

    _tool(rt, "weather", weather)
    _plan(rt, "oslo weather", ["weather"])
    await rt["engine"].init_session("s1")
    await _say(rt, "s1", "oslo weather")
    await asyncio.sleep(0.02)
    assert _finals(rt) == [], "reply must wait for the running tool"
    await asyncio.sleep(0.1)

    [final] = _finals(rt)
    [task] = await _tool_tasks(rt, "s1")
    assert task.status == TaskStatus.COMPLETED
    assert task.completed_at <= final.timestamp
    assert final.payload["tool_results"] == [{
        "task_id": task.task_id, "tool_name": "weather", "status": "COMPLETED",
        "data": {"city": "Oslo", "temp_c": 7}, "error": None,
    }]
    assert final.state_version == rt["sm"].get_current_version("s1")


@pytest.mark.asyncio
async def test_tool_result_included_in_final_text_and_history(rt):
    async def weather():
        return {"city": "Oslo", "temp_c": 7}

    _tool(rt, "weather", weather)
    _plan(rt, "oslo weather", ["weather"], response="Weather report:")
    await rt["engine"].init_session("s2")
    await _say(rt, "s2", "oslo weather")
    await asyncio.sleep(0.05)

    [final] = _finals(rt)
    assert final.payload["text"].startswith("Weather report:")
    assert '"temp_c": 7' in final.payload["text"]
    assert rt["engine"]._history["s2"][-1] == {"role": "assistant", "content": final.payload["text"]}


@pytest.mark.asyncio
async def test_multiple_tools_all_awaited_and_synthesized(rt):
    async def fast():
        await asyncio.sleep(0.01)
        return "fast-result"

    async def slow():
        await asyncio.sleep(0.08)
        return "slow-result"

    _tool(rt, "fast", fast)
    _tool(rt, "slow", slow)
    _plan(rt, "both", ["fast", "slow"])
    await rt["engine"].init_session("s3")
    await _say(rt, "s3", "both")
    await asyncio.sleep(0.04)
    assert _finals(rt) == [], "reply must wait for the slowest tool"
    await asyncio.sleep(0.1)

    [final] = _finals(rt)
    by_name = {r["tool_name"]: r for r in final.payload["tool_results"]}
    assert by_name["fast"]["data"] == "fast-result"
    assert by_name["slow"]["data"] == "slow-result"
    assert "fast-result" in final.payload["text"] and "slow-result" in final.payload["text"]


@pytest.mark.asyncio
async def test_tools_without_plan_text_still_get_a_reply(rt):
    async def weather():
        return {"temp_c": 7}

    _tool(rt, "weather", weather)
    _plan(rt, "silent plan", ["weather"], response=None)
    await rt["engine"].init_session("s4")
    await _say(rt, "s4", "silent plan")
    await asyncio.sleep(0.05)
    [final] = _finals(rt)
    assert '"temp_c": 7' in final.payload["text"]


@pytest.mark.asyncio
async def test_provider_synthesize_response_override_is_used(rt):
    seen = {}

    class Synth(MockLLMProvider):
        async def synthesize_response(self, session_state, conversation_history, user_input, plan, tool_results):
            seen["results"] = tool_results
            seen["user_input"] = user_input
            return "custom synthesis"

    async def weather():
        return {"temp_c": 7}

    rt["engine"].llm_provider = Synth()
    rt["engine"].llm_provider.set_response_for_query("oslo weather", LLMPlan(
        proposed_tool_calls=[ToolCallRequest(call_id="c", tool_name="weather", arguments={}, origin_state_version=1)],
        assistant_response="x",
    ))
    _tool(rt, "weather", weather)
    await rt["engine"].init_session("s5")
    await _say(rt, "s5", "oslo weather")
    await asyncio.sleep(0.05)
    [final] = _finals(rt)
    assert final.payload["text"] == "custom synthesis"
    assert seen["user_input"] == "oslo weather"
    assert [r["data"] for r in seen["results"]] == [{"temp_c": 7}]


# ---------------------------------------------------------------------------
# Failure and cancellation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_failure_is_reported_in_final_response(rt):
    async def broken():
        raise RuntimeError("upstream 503")

    _tool(rt, "broken", broken)
    _plan(rt, "try it", ["broken"])
    await rt["engine"].init_session("f1")
    await _say(rt, "f1", "try it")
    await asyncio.sleep(0.05)

    [final] = _finals(rt)
    [result] = final.payload["tool_results"]
    assert result["status"] == "FAILED"
    assert result["data"] is None
    assert "upstream 503" in result["error"]
    assert "broken failed: upstream 503" in final.payload["text"]


@pytest.mark.asyncio
async def test_cancel_while_tool_running_produces_no_final_response(rt):
    async def slow():
        await asyncio.sleep(1)
        return "should never appear"

    _tool(rt, "slow", slow)
    _plan(rt, "run slow", ["slow"])
    await rt["engine"].init_session("c1")
    await _say(rt, "c1", "run slow")
    await asyncio.sleep(0.03)
    await _say(rt, "c1", "stop")
    await asyncio.sleep(0.05)

    assert _finals(rt) == []
    [tool] = await _tool_tasks(rt, "c1")
    [reasoning] = await _reasoning(rt, "c1")
    assert tool.status == TaskStatus.CANCELLED
    assert reasoning.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_individually_cancelled_tool_is_reported_as_cancelled(rt):
    async def slow():
        await asyncio.sleep(1)

    async def quick():
        return "quick-result"

    _tool(rt, "slow", slow)
    _tool(rt, "quick", quick)
    _plan(rt, "two tools", ["slow", "quick"])
    await rt["engine"].init_session("c2")
    await _say(rt, "c2", "two tools")
    await asyncio.sleep(0.03)
    [slow_task] = [t for t in await _tool_tasks(rt, "c2") if t.tool_name == "slow"]
    rt["tm"]._asyncio_tasks[slow_task.task_id].cancel()  # cancel just this tool; the turn stays current
    await asyncio.sleep(0.05)

    [final] = _finals(rt)
    by_name = {r["tool_name"]: r for r in final.payload["tool_results"]}
    assert by_name["slow"]["status"] == "CANCELLED"
    assert by_name["quick"]["data"] == "quick-result"
    assert "slow was cancelled." in final.payload["text"]


# ---------------------------------------------------------------------------
# Staleness: corrections and new queries while tools run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_readonly_result_from_older_version_is_rejected_and_never_synthesized(rt):
    """A READ_ONLY tool that completes after the state moved on is STALE, not COMPLETED."""
    async def search():
        await asyncio.sleep(0.05)
        return "result-for-mumbai"

    _tool(rt, "search", search, category=ToolCategory.READ_ONLY)
    _plan(rt, "search mumbai", ["search"])
    await rt["engine"].init_session("st1")
    await _say(rt, "st1", "search mumbai")
    await asyncio.sleep(0.02)
    # State advances without cancelling anything (e.g. a correction that could not cancel).
    await rt["sm"].apply_delta("st1", slot_deltas={"destination": "Paris"})
    await asyncio.sleep(0.08)

    [tool] = await _tool_tasks(rt, "st1")
    assert tool.status == TaskStatus.STALE
    assert tool.result is None
    stale = [e for e in rt["events"] if e.event_type == EventType.TASK_REJECTED_STALE and e.payload.get("tool_name") == "search"]
    assert len(stale) == 1
    assert _finals(rt) == []
    assert all("result-for-mumbai" not in str(e.payload) for e in rt["events"])


@pytest.mark.asyncio
async def test_correction_while_tool_running_discards_old_turn(rt):
    async def search():
        await asyncio.sleep(0.1)
        return "result-for-mumbai"

    _tool(rt, "search", search)
    _plan(rt, "find flights to mumbai", ["search"])
    await rt["engine"].init_session("st2")
    await _say(rt, "st2", "find flights to mumbai")
    await asyncio.sleep(0.03)
    await _say(rt, "st2", "No wait, change destination to Paris")
    await asyncio.sleep(0.15)

    [old_tool] = await _tool_tasks(rt, "st2")
    assert old_tool.status == TaskStatus.CANCELLED
    reasoning = await _reasoning(rt, "st2")
    assert [t.status for t in reasoning] == [TaskStatus.CANCELLED, TaskStatus.COMPLETED]
    [final] = _finals(rt)
    assert "Paris" in final.payload["text"]
    assert "result-for-mumbai" not in final.payload["text"]
    assert final.state_version == rt["sm"].get_current_version("st2")


@pytest.mark.asyncio
async def test_new_query_while_tool_running_discards_old_turn(rt):
    async def search():
        await asyncio.sleep(0.1)
        return "result-for-mumbai"

    _tool(rt, "search", search)
    _plan(rt, "find flights to mumbai", ["search"])
    await rt["engine"].init_session("st3")
    await _say(rt, "st3", "find flights to mumbai")
    await asyncio.sleep(0.03)
    await _say(rt, "st3", "What's the weather in Paris")
    await asyncio.sleep(0.15)

    [old_tool] = await _tool_tasks(rt, "st3")
    assert old_tool.status == TaskStatus.CANCELLED
    [final] = _finals(rt)
    assert final.payload["text"] == "Processed request: What's the weather in Paris"
    assert all("result-for-mumbai" not in str(e.payload) for e in rt["events"])


# ---------------------------------------------------------------------------
# No-tool plans keep their previous behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_tool_reasoning_is_unchanged(rt):
    await rt["engine"].init_session("n1")
    await _say(rt, "n1", "hello")
    await asyncio.sleep(0.02)
    [final] = _finals(rt)
    assert final.payload == {"text": "Processed request: hello"}
    assert await _tool_tasks(rt, "n1") == []
    [reasoning] = await _reasoning(rt, "n1")
    assert reasoning.status == TaskStatus.COMPLETED
