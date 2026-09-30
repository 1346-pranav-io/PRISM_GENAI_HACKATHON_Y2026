"""Regression tests for tool-task terminal states and cancellable deliberate reasoning."""

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
    bus = EventBus()
    sm = StateManager()
    tm = TaskManager()
    reg = ToolRegistry()
    llm = MockLLMProvider()
    engine = AgentRuntimeEngine(
        event_bus=bus, state_manager=sm, task_manager=tm,
        classifier=FastInterruptionClassifier(), tool_registry=reg,
        tool_executor=ToolExecutor(reg), llm_provider=llm, trace_logger=TraceLogger(),
    )
    events: List[RuntimeEvent] = []

    async def collect(evt: RuntimeEvent) -> None:
        events.append(evt)

    bus.subscribe_all(collect)
    return {"engine": engine, "bus": bus, "sm": sm, "tm": tm, "reg": reg, "llm": llm, "events": events}


def _register(reg, name, fn, timeout=30.0):
    reg.register_tool(
        ToolManifest(
            name=name, description=name, category=ToolCategory.READ_ONLY,
            parameters_schema={"type": "object"}, timeout_seconds=timeout,
        ),
        fn,
    )


def _plan_calling(tool_name, response="ok"):
    return LLMPlan(
        intent="test",
        proposed_tool_calls=[ToolCallRequest(
            call_id=f"call_{tool_name}", tool_name=tool_name, arguments={}, origin_state_version=1,
        )],
        assistant_response=response,
    )


async def _say(bus, sid, text):
    await bus.publish(RuntimeEvent(session_id=sid, event_type=EventType.USER_TEXT, state_version=1, payload={"text": text}))


async def _tasks_of_type(tm, sid, task_type):
    return [t for t in await tm.get_session_tasks(sid) if t.task_type == task_type]


async def _wait_for(predicate, timeout=1.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")


# ---------------------------------------------------------------------------
# P0.2 — tool task terminal states
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_tool_task_is_completed(rt):
    async def good():
        return {"value": 42}

    _register(rt["reg"], "good_tool", good)
    rt["llm"].set_response_for_query("run good", _plan_calling("good_tool"))
    await rt["engine"].init_session("s_ok")
    await _say(rt["bus"], "s_ok", "run good")

    async def done():
        tasks = await _tasks_of_type(rt["tm"], "s_ok", TaskType.TOOL_EXECUTION)
        return tasks and tasks[0].status not in (TaskStatus.PENDING, TaskStatus.RUNNING)

    await _wait_for(done)
    [task] = await _tasks_of_type(rt["tm"], "s_ok", TaskType.TOOL_EXECUTION)
    assert task.status == TaskStatus.COMPLETED
    assert task.result == {"value": 42}


@pytest.mark.asyncio
async def test_cancelled_tool_task_is_cancelled_not_completed(rt):
    async def slow():
        await asyncio.sleep(2.0)
        return "should not be returned"

    _register(rt["reg"], "slow_tool", slow)
    rt["llm"].set_response_for_query("run slow", _plan_calling("slow_tool"))
    await rt["engine"].init_session("s_cancel")
    await _say(rt["bus"], "s_cancel", "run slow")

    async def running():
        tasks = await _tasks_of_type(rt["tm"], "s_cancel", TaskType.TOOL_EXECUTION)
        return tasks and tasks[0].status == TaskStatus.RUNNING

    await _wait_for(running)
    await rt["tm"].cancel_all_active("s_cancel", reason="test cancel")
    await asyncio.sleep(0.05)

    [task] = await _tasks_of_type(rt["tm"], "s_cancel", TaskType.TOOL_EXECUTION)
    assert task.status == TaskStatus.CANCELLED
    assert task.result is None


@pytest.mark.asyncio
async def test_raising_tool_task_is_failed(rt):
    async def broken():
        raise RuntimeError("boom")

    _register(rt["reg"], "broken_tool", broken)
    rt["llm"].set_response_for_query("run broken", _plan_calling("broken_tool"))
    await rt["engine"].init_session("s_fail")
    await _say(rt["bus"], "s_fail", "run broken")

    async def done():
        tasks = await _tasks_of_type(rt["tm"], "s_fail", TaskType.TOOL_EXECUTION)
        return tasks and tasks[0].status not in (TaskStatus.PENDING, TaskStatus.RUNNING)

    await _wait_for(done)
    [task] = await _tasks_of_type(rt["tm"], "s_fail", TaskType.TOOL_EXECUTION)
    assert task.status == TaskStatus.FAILED
    assert "boom" in (task.error or "")


@pytest.mark.asyncio
async def test_timed_out_tool_task_is_failed(rt):
    async def hangs():
        await asyncio.sleep(1.0)

    _register(rt["reg"], "hang_tool", hangs, timeout=0.05)
    rt["llm"].set_response_for_query("run hang", _plan_calling("hang_tool"))
    await rt["engine"].init_session("s_timeout")
    await _say(rt["bus"], "s_timeout", "run hang")

    async def done():
        tasks = await _tasks_of_type(rt["tm"], "s_timeout", TaskType.TOOL_EXECUTION)
        return tasks and tasks[0].status not in (TaskStatus.PENDING, TaskStatus.RUNNING)

    await _wait_for(done)
    [task] = await _tasks_of_type(rt["tm"], "s_timeout", TaskType.TOOL_EXECUTION)
    assert task.status == TaskStatus.FAILED
    assert "timed out" in (task.error or "")


@pytest.mark.asyncio
async def test_unregistered_tool_task_is_failed(rt):
    rt["llm"].set_response_for_query("run missing", _plan_calling("missing_tool"))
    await rt["engine"].init_session("s_missing")
    await _say(rt["bus"], "s_missing", "run missing")

    async def done():
        tasks = await _tasks_of_type(rt["tm"], "s_missing", TaskType.TOOL_EXECUTION)
        return tasks and tasks[0].status not in (TaskStatus.PENDING, TaskStatus.RUNNING)

    await _wait_for(done)
    [task] = await _tasks_of_type(rt["tm"], "s_missing", TaskType.TOOL_EXECUTION)
    assert task.status == TaskStatus.FAILED
    assert "not registered" in (task.error or "")


# ---------------------------------------------------------------------------
# P0.3 — deliberate reasoning is tracked, cancellable, and version-checked
# ---------------------------------------------------------------------------


def _final_responses(events):
    return [e for e in events if e.event_type == EventType.AGENT_FINAL_RESPONSE]


@pytest.mark.asyncio
async def test_reasoning_is_tracked_as_reasoning_task(rt):
    await rt["engine"].init_session("s_track")
    await _say(rt["bus"], "s_track", "hello")
    await asyncio.sleep(0.05)
    [task] = await _tasks_of_type(rt["tm"], "s_track", TaskType.REASONING)
    assert task.status == TaskStatus.COMPLETED
    assert task.origin_state_version == 1


@pytest.mark.asyncio
async def test_cancel_suppresses_inflight_response(rt):
    rt["llm"].latency_seconds = 0.2
    await rt["engine"].init_session("s_stop")
    await _say(rt["bus"], "s_stop", "hello there")
    await asyncio.sleep(0.05)
    await _say(rt["bus"], "s_stop", "stop")
    await asyncio.sleep(0.35)

    assert _final_responses(rt["events"]) == []
    [task] = await _tasks_of_type(rt["tm"], "s_stop", TaskType.REASONING)
    assert task.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_correction_suppresses_outdated_response(rt):
    rt["llm"].latency_seconds = 0.2
    await rt["engine"].init_session("s_corr")
    await _say(rt["bus"], "s_corr", "tell me about Tokyo")
    await asyncio.sleep(0.05)
    await _say(rt["bus"], "s_corr", "No wait, change destination to Paris")
    await asyncio.sleep(0.35)

    finals = _final_responses(rt["events"])
    assert len(finals) == 1
    assert "Paris" in finals[0].payload["text"]
    assert finals[0].state_version == 2

    reasoning = await _tasks_of_type(rt["tm"], "s_corr", TaskType.REASONING)
    assert [t.status for t in reasoning] == [TaskStatus.CANCELLED, TaskStatus.COMPLETED]


@pytest.mark.asyncio
async def test_uncancellable_reasoning_result_discarded_when_state_advances(rt):
    """Even if cancellation never reaches the reasoning, its outdated response is dropped."""
    rt["llm"].latency_seconds = 0.1
    engine, sm = rt["engine"], rt["sm"]
    await engine.init_session("s_race")

    # Run the deliberate path directly (not via TaskManager) so nothing can cancel it.
    run = asyncio.create_task(engine._execute_deliberate_path("s_race", "hello", 1))
    await asyncio.sleep(0.02)
    await sm.apply_delta("s_race", slot_deltas={"destination": "Rome"})
    await run

    assert _final_responses(rt["events"]) == []
    stale = [e for e in rt["events"] if e.event_type == EventType.TASK_REJECTED_STALE]
    assert len(stale) == 1
    assert stale[0].payload["task_type"] == TaskType.REASONING.value
    assert stale[0].payload["origin_state_version"] == 1


@pytest.mark.asyncio
async def test_plan_own_slot_delta_does_not_suppress_its_response(rt):
    rt["llm"].set_response_for_query(
        "fly to rome",
        LLMPlan(intent="book", extracted_slots={"destination": "Rome"}, assistant_response="Rome it is."),
    )
    await rt["engine"].init_session("s_own")
    await _say(rt["bus"], "s_own", "fly to rome")
    await asyncio.sleep(0.05)

    finals = _final_responses(rt["events"])
    assert len(finals) == 1
    assert finals[0].payload["text"] == "Rome it is."
    [task] = await _tasks_of_type(rt["tm"], "s_own", TaskType.REASONING)
    assert task.status == TaskStatus.COMPLETED
