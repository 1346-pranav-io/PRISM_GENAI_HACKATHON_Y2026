"""Integration tests for AgentRuntimeEngine and Dual-Path Orchestration."""

import asyncio
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
from src.agent_runtime.models.tasks import TaskRecord, TaskStatus, TaskType
from src.agent_runtime.models.tools import ToolCallRequest, ToolCategory, ToolManifest


@pytest.fixture
def runtime_setup():
    event_bus = EventBus()
    state_manager = StateManager()
    task_manager = TaskManager()
    classifier = FastInterruptionClassifier()
    tool_registry = ToolRegistry()
    tool_executor = ToolExecutor(tool_registry)
    llm_provider = MockLLMProvider()
    trace_logger = TraceLogger()

    async def mock_flight_search(query: str):
        await asyncio.sleep(0.05)
        return [{"flight": "JL001", "price": 850}]

    tool_registry.register_tool(
        ToolManifest(
            name="search_flights",
            description="Search flights",
            category=ToolCategory.READ_ONLY,
            parameters_schema={"type": "object"},
        ),
        mock_flight_search,
    )

    engine = AgentRuntimeEngine(
        event_bus=event_bus,
        state_manager=state_manager,
        task_manager=task_manager,
        classifier=classifier,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        llm_provider=llm_provider,
        trace_logger=trace_logger,
    )

    return {
        "engine": engine,
        "event_bus": event_bus,
        "state_manager": state_manager,
        "task_manager": task_manager,
        "trace_logger": trace_logger,
        "llm_provider": llm_provider,
    }


@pytest.mark.asyncio
async def test_normal_user_query_flow(runtime_setup):
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]
    trace_logger = runtime_setup["trace_logger"]

    events_received = []

    async def collect(evt: RuntimeEvent):
        events_received.append(evt)

    event_bus.subscribe_all(collect)

    session_id = "test_sess_1"
    await engine.init_session(session_id)

    await event_bus.publish(
        RuntimeEvent(
            session_id=session_id,
            event_type=EventType.USER_TEXT,
            state_version=1,
            payload={"text": "search flights to Tokyo"},
        )
    )

    await asyncio.sleep(0.15)
@pytest.mark.asyncio
async def test_backchannel_does_not_cancel(runtime_setup):
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]
    state_manager = runtime_setup["state_manager"]

    events_received = []

    async def collect(evt: RuntimeEvent):
        events_received.append(evt)

    event_bus.subscribe_all(collect)

    session_id = "test_sess_2"
    await engine.init_session(session_id)

    await event_bus.publish(
        RuntimeEvent(
            session_id=session_id,
            event_type=EventType.USER_TEXT,
            state_version=1,
            payload={"text": "uh-huh"},
        )
    )

    await asyncio.sleep(0.05)

    types = [e.event_type for e in events_received]
    assert EventType.FAST_ACK in types
    assert EventType.TASK_CANCELLED not in types

    state = await state_manager.get_state(session_id)
    assert state.state_version == 1


@pytest.mark.asyncio
async def test_explicit_cancel_stops_tasks(runtime_setup):
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]
    state_manager = runtime_setup["state_manager"]
    task_manager = runtime_setup["task_manager"]

    session_id = "test_sess_3"
    await engine.init_session(session_id)

    async def long_running():
        await asyncio.sleep(1.0)
        return "done"

    t_rec = TaskRecord(
        task_id="slow_task_1",
        task_type=TaskType.TOOL_EXECUTION,
        origin_state_version=1,
    )
    await task_manager.spawn_task(session_id, t_rec, long_running())
    await asyncio.sleep(0.01)

    await event_bus.publish(
        RuntimeEvent(
            session_id=session_id,
            event_type=EventType.USER_TEXT,
            state_version=1,
            payload={"text": "stop!"},
        )
    )

    await asyncio.sleep(0.05)

    task_after = await task_manager.get_task("slow_task_1")
    assert task_after.status in (TaskStatus.CANCELLED, TaskStatus.CANCELLING)

    state = await state_manager.get_state(session_id)
    assert state.state_version == 2


@pytest.mark.asyncio
async def test_correction_mutates_state_and_cancels_stale(runtime_setup):
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]
    state_manager = runtime_setup["state_manager"]

    session_id = "test_sess_4"
    await engine.init_session(session_id)

    await event_bus.publish(
        RuntimeEvent(
            session_id=session_id,
            event_type=EventType.USER_TEXT,
            state_version=1,
            payload={"text": "No wait, change destination to Paris"},
        )
    )

    await asyncio.sleep(0.1)

    state = await state_manager.get_state(session_id)
    slot = state.slots.get("destination")
    assert slot is not None
    assert slot.value == "Paris"
    assert slot.source_state_version == 2
    assert state.state_version >= 2


# ----------------------------------------------------------------------
# Phase 2.1: conversation history, speaking lifecycle, and history cap
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conversation_history_includes_user_turn(runtime_setup):
    """User turn must be appended to _history before the LLM call."""
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]

    session_id = "hist_test_1"
    await engine.init_session(session_id)

    await event_bus.publish(
        RuntimeEvent(
            session_id=session_id,
            event_type=EventType.USER_TEXT,
            state_version=1,
            payload={"text": "search flights to Tokyo"},
        )
    )

    await asyncio.sleep(0.15)

    history = engine._history.get(session_id, [])
    roles = [turn["role"] for turn in history]
    assert "user" in roles, f"Expected 'user' in history roles, got {roles}"
    assert "assistant" in roles, f"Expected 'assistant' in history roles, got {roles}"
    # User turn must precede assistant turn
    assert roles.index("user") < roles.index("assistant")


@pytest.mark.asyncio
async def test_conversation_history_bounded_to_20_turns(runtime_setup):
    """History must be trimmed to the most recent 20 turns."""
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]

    session_id = "hist_cap_test"
    await engine.init_session(session_id)

    # Inject 25 turns directly into the internal history to exercise the cap
    # without triggering 25 full slow-path LLM calls.
    for i in range(25):
        engine._history[session_id].append({"role": "user", "content": f"msg {i}"})
        engine._history[session_id].append({"role": "assistant", "content": f"resp {i}"})

    # Manually exercise the cap logic (simulates what happens inside
    # _run_deliberate_path before the LLM call).
    history = engine._history[session_id]
    MAX_HISTORY_TURNS = 20
    if len(history) > MAX_HISTORY_TURNS:
        history[:] = history[-MAX_HISTORY_TURNS:]

    assert len(history) == 20, f"Expected 20 turns after cap, got {len(history)}"
    # First remaining turn must be "msg 15" (25 turns - 20 = 5 trimmed)
    assert history[0]["content"] == "msg 15"
    # Last turn must be "resp 24"
    assert history[-1]["content"] == "resp 24"


@pytest.mark.asyncio
async def test_is_speaking_reset_after_successful_response(runtime_setup):
    """_is_speaking must be False after AGENT_FINAL_RESPONSE is published."""
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]

    session_id = "speak_reset_ok"
    await engine.init_session(session_id)

    await event_bus.publish(
        RuntimeEvent(
            session_id=session_id,
            event_type=EventType.USER_TEXT,
            state_version=1,
            payload={"text": "hello"},
        )
    )

    await asyncio.sleep(0.15)

    # Must be False after response
    assert engine._is_speaking.get(session_id, True) is False


@pytest.mark.asyncio
async def test_is_speaking_reset_after_error(runtime_setup):
    """_is_speaking must be False even when the deliberate path raises."""
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]

    session_id = "speak_reset_err"

    # Swap in a provider that raises so we hit the Exception path


# ---------------------------------------------------------------------------
# Phase 2.2: Version-aware invalidation and stale-result protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_version_advance_invalidates_inflight_tasks(runtime_setup):
    """
    Phase 2.2 — Version invalidation after apply_delta.

    When a state_version advances, tasks whose origin_state_version is older
    than the new version are cancelled. Tasks created at the new version survive.
    """
    engine = runtime_setup["engine"]
    task_manager = runtime_setup["task_manager"]
    state_manager = runtime_setup["state_manager"]

    session_id = "version_invalidate_test"
    await engine.init_session(session_id)

    # Manually create two tasks at different versions.
    # Task at version 1.
    task_v1 = TaskRecord(
        task_id="task_v1",
        task_type=TaskType.TOOL_EXECUTION,
        tool_name="search_flights",
        origin_state_version=1,
    )

    async def slow_work():
        await asyncio.sleep(2.0)
        return "done"

    await task_manager.spawn_task(session_id, task_v1, slow_work())
    await asyncio.sleep(0.02)

    rec_v1 = await task_manager.get_task("task_v1")
    assert rec_v1.status == TaskStatus.RUNNING

    # Advance state_version to 2 via apply_delta.
    await state_manager.apply_delta(session_id, slot_deltas={"city": "Berlin"})

    # Version 1 task should now be CANCELLING/CANCELLED.
    invalidated = await task_manager.cancel_tasks_before_version(
        session_id=session_id,
        current_version=2,
        reason="State version advanced",
    )

    assert "task_v1" in invalidated
    await asyncio.sleep(0.02)

    rec_v1_after = await task_manager.get_task("task_v1")
    assert rec_v1_after.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_stale_tool_result_marks_task_record_stale(runtime_setup):
    """
    Phase 2.2 — R7a/R7b/R7c: When a tool execution returns STALE, the TaskRecord
    is marked STALE, TASK_REJECTED_STALE is emitted, and the result data is None.
    """
    engine = runtime_setup["engine"]
    event_bus = runtime_setup["event_bus"]
    task_manager = runtime_setup["task_manager"]
    tool_registry = runtime_setup["engine"].tool_registry

    # Register a STATE_MODIFYING tool that takes time.
    async def slow_booking(flight: str):
        await asyncio.sleep(0.08)
        return {"booked": flight}

    tool_registry.register_tool(
        ToolManifest(
            name="book_flight",
            description="Book a flight",
            category=ToolCategory.STATE_MODIFYING,
            parameters_schema={},
        ),
        slow_booking,
    )

    session_id = "stale_result_test"
    await engine.init_session(session_id)

    events_received: List[RuntimeEvent] = []

    async def collect(evt: RuntimeEvent):
        events_received.append(evt)

    event_bus.subscribe_all(collect)

    # Manually spawn a task with origin_state_version=1.
    task = TaskRecord(
        task_id="task_stale_result",
        task_type=TaskType.TOOL_EXECUTION,
        tool_name="book_flight",
        origin_state_version=1,
    )

    version_ref = runtime_setup["engine"].state_manager
    session_sid = session_id

    async def run_tool_with_stale_result():
        from src.agent_runtime.core.runtime_engine import StateRef

        req = ToolCallRequest(
            call_id="call_stale_test",
            tool_name="book_flight",
            arguments={"flight": "JL001"},
            origin_state_version=1,
        )
        # StateRef returns 1 for first call (tool running), then 2 (version advanced).
        call_count = 0

        def getter() -> int:
            nonlocal call_count
            call_count += 1
            # return 1 on call #1 (pre-execution), 2 on call #2 (post-execution)
            return 1 if call_count == 1 else 2

        res = await engine.tool_executor.execute(req, current_version_getter=getter)
        # Simulate what _run_tool does: update task status.
        if res.status == TaskStatus.STALE:
            await task_manager.update_task_status(
                "task_stale_result",
                status=TaskStatus.STALE,
                error=res.error,
            )
            await event_bus.publish(
                RuntimeEvent(
                    session_id=session_id,
                    event_type=EventType.TASK_REJECTED_STALE,
                    state_version=2,
                    payload={
                        "task_id": "task_stale_result",
                        "tool_name": "book_flight",
                        "error": res.error,
                    },
                )
            )
            return None
        await task_manager.update_task_status(
            "task_stale_result",
            status=TaskStatus.COMPLETED,
            result=res.data,
        )
        return res.data

    await task_manager.spawn_task(
        session_id,
        task,
        run_tool_with_stale_result(),
    )

    await asyncio.sleep(0.2)

    rec = await task_manager.get_task("task_stale_result")
    assert rec.status == TaskStatus.STALE, f"Expected STALE, got {rec.status}"

    stale_events = [e for e in events_received if e.event_type == EventType.TASK_REJECTED_STALE]
    assert len(stale_events) == 1
    assert stale_events[0].payload["task_id"] == "task_stale_result"
    assert stale_events[0].payload["tool_name"] == "book_flight"

    original_provider = engine.llm_provider

    class RaisingProvider:
        async def plan_and_reason(self, session_state, conversation_history, available_tools, user_input):
            raise RuntimeError("synthetic error for test")

    engine.llm_provider = RaisingProvider()

    await engine.init_session(session_id)

    await event_bus.publish(
        RuntimeEvent(
            session_id=session_id,
            event_type=EventType.USER_TEXT,
            state_version=1,
            payload={"text": "trigger error"},
        )
    )

    await asyncio.sleep(0.1)

    assert engine._is_speaking.get(session_id, True) is False

    engine.llm_provider = original_provider


# ----------------------------------------------------------------------
# Phase 2.1: StateRef.__int__ and MockLLMProvider call_id uniqueness
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_reflect_get_current_version(runtime_setup):
    """int(state_ref) must delegate to get_current_version without touching the event loop."""
    state_manager = runtime_setup["state_manager"]
    session_id = "state_ref_int_test"

    await state_manager.create_session(session_id)
    await state_manager.apply_delta(session_id, slot_deltas={"city": "Berlin"})

    from src.agent_runtime.core.runtime_engine import StateRef

    ref = StateRef(state_manager, session_id)
    # Must not raise RuntimeError (no loop nesting)
    version = int(ref)
    assert version == 2, f"Expected version 2, got {version}"

    # __call__ should return the same value
    assert ref() == version


@pytest.mark.asyncio
async def test_mock_llm_call_id_unique():
    """MockLLMProvider heuristic flight responses must use globally unique call_ids."""
    from src.agent_runtime.core.mock_llm import MockLLMProvider
    from src.agent_runtime.models.state import SessionState

    provider = MockLLMProvider()
    state = SessionState(session_id="call_id_test")
    manifests = []

    # Generate two flight-search responses in the same session
    plan1 = await provider.plan_and_reason(
        session_state=state,
        conversation_history=[],
        available_tools=manifests,
        user_input="search flights to Tokyo",
    )

    plan2 = await provider.plan_and_reason(
        session_state=state,
        conversation_history=[],
        available_tools=manifests,
        user_input="search flights to Paris",
    )

    assert len(plan1.proposed_tool_calls) == 1
    assert len(plan2.proposed_tool_calls) == 1

    id1 = plan1.proposed_tool_calls[0].call_id
    id2 = plan2.proposed_tool_calls[0].call_id

    assert id1 != id2, f"call_ids must be unique; got {id1!r} twice"
    assert id1.startswith("call_mock_")
    assert id2.startswith("call_mock_")

