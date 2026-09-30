"""Unit and integration tests for Evaluation Metrics, Replayer, and Benchmark Suite."""

import asyncio
import pytest
from src.agent_runtime.core.trace_logger import TraceLogger
from src.agent_runtime.eval.benchmark import BenchmarkSuite
from src.agent_runtime.eval.metrics import MetricsCalculator
from src.agent_runtime.eval.replayer import TraceReplayer
from src.agent_runtime.models.events import EventType, RuntimeEvent


@pytest.mark.asyncio
async def test_metrics_calculator():
    trace_logger = TraceLogger()
    session_id = "test_eval_1"

    # Log events: user query, fast ack, deliberate tool schedule, response
    evt1 = RuntimeEvent(
        session_id=session_id,
        event_type=EventType.USER_TEXT,
        state_version=1,
        payload={"text": "Book flight to NYC"},
    )
    await trace_logger.log_event(evt1)
    await asyncio.sleep(0.005)

    evt2 = RuntimeEvent(
        session_id=session_id,
        event_type=EventType.FAST_ACK,
        state_version=1,
        payload={"text": "Checking..."},
    )
    await trace_logger.log_event(evt2)

    evt3 = RuntimeEvent(
        session_id=session_id,
        event_type=EventType.TASK_SCHEDULED,
        state_version=1,
        payload={"task_id": "t1"},
    )
    await trace_logger.log_event(evt3)

    evt4 = RuntimeEvent(
        session_id=session_id,
        event_type=EventType.AGENT_FINAL_RESPONSE,
        state_version=1,
        payload={"text": "Flight found"},
    )
    await trace_logger.log_event(evt4)

    trace = await trace_logger.get_session_trace(session_id)
    assert trace is not None

    metrics = MetricsCalculator.evaluate_trace(trace)
    assert metrics.total_events == 4
    assert metrics.version_strictly_monotonic is True
    assert metrics.total_tasks_scheduled == 1
    assert len(metrics.reflex_latencies_ms) == 1
    assert metrics.reflex_latencies_ms[0] > 0.0


@pytest.mark.asyncio
async def test_trace_replayer():
    trace_logger = TraceLogger()
    session_id = "test_replay_origin"

    # Inbound events
    evt1 = RuntimeEvent(
        session_id=session_id,
        event_type=EventType.USER_TEXT,
        state_version=1,
        payload={"text": "stop!"},
    )
    await trace_logger.log_event(evt1)

    trace = await trace_logger.get_session_trace(session_id)
    assert trace is not None

    replayer = TraceReplayer()
    replay_result = await replayer.replay(trace, fast_forward=True)

    assert replay_result.replayed_trace is not None
    # Replay executed user cancellation and incremented state version
    assert replay_result.replayed_trace.final_state_version >= 1


@pytest.mark.asyncio
async def test_benchmark_suite_execution():
    suite = BenchmarkSuite()
    results = await suite.run_all()

    assert len(results) == 3
    for r in results:
        assert r.passed is True
        assert r.metrics.version_strictly_monotonic is True
