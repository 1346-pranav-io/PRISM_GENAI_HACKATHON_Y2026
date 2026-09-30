"""Deterministic Trace Replayer for evaluation, regression testing, and verification."""

import asyncio
from typing import Any, Callable, Dict, List, Optional
from ..core.classifier import FastInterruptionClassifier
from ..core.event_bus import EventBus
from ..core.mock_llm import MockLLMProvider
from ..core.runtime_engine import AgentRuntimeEngine
from ..core.state_manager import StateManager
from ..core.task_manager import TaskManager
from ..core.tool_executor import ToolExecutor
from ..core.tool_registry import ToolRegistry
from ..core.trace_logger import TraceLogger
from ..models.events import EventType, RuntimeEvent
from ..models.trace import SessionTrace


class TraceReplayResult:
    """Outcome of replaying a recorded trace."""

    def __init__(
        self,
        original_trace: SessionTrace,
        replayed_trace: SessionTrace,
        is_state_equivalent: bool,
        divergence_details: Optional[str] = None,
    ) -> None:
        self.original_trace = original_trace
        self.replayed_trace = replayed_trace
        self.is_state_equivalent = is_state_equivalent
        self.divergence_details = divergence_details


class TraceReplayer:
    """Replays recorded session traces deterministically into a fresh runtime instance."""

    def __init__(
        self,
        tool_registry: Optional[ToolRegistry] = None,
        llm_provider: Optional[MockLLMProvider] = None,
    ) -> None:
        self.tool_registry = tool_registry or ToolRegistry()
        self.llm_provider = llm_provider or MockLLMProvider()

    async def replay(
        self,
        recorded_trace: SessionTrace,
        fast_forward: bool = True,
    ) -> TraceReplayResult:
        """Replay recorded inbound events into a newly instantiated runtime."""
        event_bus = EventBus()
        state_manager = StateManager()
        task_manager = TaskManager()
        classifier = FastInterruptionClassifier()
        tool_executor = ToolExecutor(self.tool_registry)
        trace_logger = TraceLogger()

        engine = AgentRuntimeEngine(
            event_bus=event_bus,
            state_manager=state_manager,
            task_manager=task_manager,
            classifier=classifier,
            tool_registry=self.tool_registry,
            tool_executor=tool_executor,
            llm_provider=self.llm_provider,
            trace_logger=trace_logger,
        )

        replay_session_id = f"replay_{recorded_trace.session_id}"
        await engine.init_session(replay_session_id)

        inbound_events = [
            e for e in recorded_trace.events
            if e.event_type in (EventType.USER_TEXT, EventType.USER_INTERRUPTION)
        ]

        last_time = None
        for evt in inbound_events:
            if not fast_forward and last_time is not None:
                delta = (evt.timestamp - last_time).total_seconds()
                if delta > 0:
                    await asyncio.sleep(min(delta, 1.0))
            last_time = evt.timestamp

            # Publish remapped event
            replayed_event = RuntimeEvent(
                session_id=replay_session_id,
                event_type=evt.event_type,
                state_version=evt.state_version,
                payload=dict(evt.payload),
            )
            await event_bus.publish(replayed_event)

        # Allow deliberation tasks to settle
        await asyncio.sleep(0.1)

        new_trace = await trace_logger.get_session_trace(replay_session_id)
        assert new_trace is not None

        # Compare version progression
        orig_final_ver = recorded_trace.final_state_version
        new_final_ver = new_trace.final_state_version

        is_equiv = (orig_final_ver == new_final_ver)
        divergence = None if is_equiv else f"Final version mismatch: orig={orig_final_ver}, replay={new_final_ver}"

        return TraceReplayResult(
            original_trace=recorded_trace,
            replayed_trace=new_trace,
            is_state_equivalent=is_equiv,
            divergence_details=divergence,
        )
