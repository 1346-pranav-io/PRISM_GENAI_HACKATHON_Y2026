"""Unit tests for TraceLogger."""

import pytest
from src.agent_runtime.core.trace_logger import TraceLogger
from src.agent_runtime.models.events import EventType, RuntimeEvent


@pytest.mark.asyncio
async def test_trace_logging_and_retrieval():
    logger = TraceLogger()

    evt1 = RuntimeEvent(
        event_type=EventType.USER_TEXT,
        session_id="session_test",
        state_version=1,
        payload={"query": "book flight"},
    )
    evt2 = RuntimeEvent(
        event_type=EventType.STATE_MUTATED,
        session_id="session_test",
        state_version=2,
        payload={"delta": {"destination": "NYC"}},
    )

    await logger.log_event(evt1)
    await logger.log_event(evt2)

    all_evts = await logger.get_all_events("session_test")
    assert len(all_evts) == 2
    assert all_evts[0].event_type == EventType.USER_TEXT
    assert all_evts[1].state_version == 2

    trace = await logger.get_session_trace("session_test")
    assert trace is not None
    assert trace.session_id == "session_test"
    assert trace.final_state_version == 2
    assert len(trace.events) == 2

