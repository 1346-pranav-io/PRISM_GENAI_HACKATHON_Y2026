"""Evaluation metrics engine for session traces."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from ..models.events import EventType, RuntimeEvent
from ..models.trace import SessionTrace


class TraceEvaluationMetrics(BaseModel):
    session_id: str
    total_events: int = 0
    final_state_version: int = 1
    version_strictly_monotonic: bool = True
    reflex_latencies_ms: List[float] = Field(default_factory=list)
    avg_reflex_latency_ms: float = 0.0
    max_reflex_latency_ms: float = 0.0
    total_tasks_scheduled: int = 0
    total_tasks_cancelled: int = 0
    total_tasks_rejected_stale: int = 0
    stale_execution_rate: float = 0.0
    cancellation_latency_ms: List[float] = Field(default_factory=list)


class MetricsCalculator:
    """Evaluates session traces for latency, stale rejections, and state consistency."""

    @staticmethod
    def evaluate_trace(trace: SessionTrace) -> TraceEvaluationMetrics:
        events = trace.events
        if not events:
            return TraceEvaluationMetrics(session_id=trace.session_id)

        reflex_latencies: List[float] = []
        cancellation_latencies: List[float] = []
        is_monotonic = True
        last_ver = 0

        tasks_scheduled = 0
        tasks_cancelled = 0
        tasks_stale = 0

        # Check version monotonicity
        for evt in events:
            if evt.state_version < last_ver:
                is_monotonic = False
            last_ver = max(last_ver, evt.state_version)

            if evt.event_type == EventType.TASK_SCHEDULED:
                tasks_scheduled += 1
            elif evt.event_type == EventType.TASK_CANCELLED:
                tasks_cancelled += 1
            elif evt.event_type == EventType.TASK_REJECTED_STALE:
                tasks_stale += 1

        # Calculate reflex latency (USER_TEXT / USER_INTERRUPTION -> FAST_ACK)
        for i, evt in enumerate(events):
            if evt.event_type in (EventType.USER_TEXT, EventType.USER_INTERRUPTION):
                # Look for subsequent FAST_ACK
                for j in range(i + 1, len(events)):
                    next_evt = events[j]
                    if next_evt.event_type == EventType.FAST_ACK:
                        diff_ms = (next_evt.timestamp - evt.timestamp).total_seconds() * 1000.0
                        if diff_ms >= 0:
                            reflex_latencies.append(diff_ms)
                        break
                    if next_evt.event_type in (EventType.USER_TEXT, EventType.USER_INTERRUPTION):
                        break

        # Calculate cancellation latency
        for i, evt in enumerate(events):
            if evt.event_type == EventType.USER_TEXT and ("cancel" in str(evt.payload.get("text", "")).lower() or "stop" in str(evt.payload.get("text", "")).lower()):
                for j in range(i + 1, len(events)):
                    next_evt = events[j]
                    if next_evt.event_type == EventType.TASK_CANCELLED:
                        diff_ms = (next_evt.timestamp - evt.timestamp).total_seconds() * 1000.0
                        if diff_ms >= 0:
                            cancellation_latencies.append(diff_ms)
                        break

        avg_lat = sum(reflex_latencies) / len(reflex_latencies) if reflex_latencies else 0.0
        max_lat = max(reflex_latencies) if reflex_latencies else 0.0
        stale_rate = (tasks_stale / tasks_scheduled) if tasks_scheduled > 0 else 0.0

        return TraceEvaluationMetrics(
            session_id=trace.session_id,
            total_events=len(events),
            final_state_version=trace.final_state_version,
            version_strictly_monotonic=is_monotonic,
            reflex_latencies_ms=reflex_latencies,
            avg_reflex_latency_ms=avg_lat,
            max_reflex_latency_ms=max_lat,
            total_tasks_scheduled=tasks_scheduled,
            total_tasks_cancelled=tasks_cancelled,
            total_tasks_rejected_stale=tasks_stale,
            stale_execution_rate=stale_rate,
            cancellation_latency_ms=cancellation_latencies,
        )
