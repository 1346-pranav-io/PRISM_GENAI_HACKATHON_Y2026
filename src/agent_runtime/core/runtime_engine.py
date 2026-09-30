"""Agent Runtime Orchestration Engine implementing Dual-Path event processing."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import uuid

from ..interfaces.classifier import IInterruptionClassifier
from ..interfaces.event_bus import IEventBus
from ..interfaces.llm_provider import ILLMProvider, compose_tool_response
from ..models.llm_plan import LLMPlan
from ..interfaces.state_manager import IStateManager
from ..interfaces.task_manager import ITaskManager
from ..interfaces.tool_executor import IToolExecutor
from ..interfaces.tool_registry import IToolRegistry
from ..interfaces.trace_logger import ITraceLogger
from ..models.classifier import InterruptionCategory
from ..models.events import EventType, RuntimeEvent
from ..models.state import SessionState
from ..models.tasks import TaskRecord, TaskStatus, TaskType
from ..models.tools import ToolCallRequest

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20


class StateRef:
    """
    Dynamic state-version reference resolved at access time.

    Satisfies the Callable[[], int] protocol expected by IToolExecutor.execute
    while ensuring every invocation reads the current (live) state version,
    not a stale snapshot captured at scheduling time.  Achieved via __int__
    delegation: int(state_ref) -> state_manager.get_state(session_id).state_version.

    This is the "dynamically evaluated getter" mandated by ARCHITECTURE.md:
    the version must be evaluated at tool-execution time, not at
    tool-scheduling time.
    """

    __slots__ = ("_state_manager", "_session_id")

    def __init__(self, state_manager: IStateManager, session_id: str) -> None:
        self._state_manager = state_manager
        self._session_id = session_id

    def __int__(self) -> int:
        # Supports int(state_ref) — used when the caller wraps the getter with int().
        # Delegates to the synchronous, lock-free get_current_version() so it is
        # safe to call from any async or sync context without touching the event loop.
        return self._state_manager.get_current_version(self._session_id)

    def __call__(self) -> int:
        """
        Satisfies Callable[[], int] for ToolExecutor.execute signature.

        Reads the live state_version directly via get_current_version — a
        synchronous, lock-free call.  Because apply_delta always writes the
        state_version from the asyncio event loop (single-writer guarantee),
        this always returns the current (not stale) version regardless of
        when the getter was captured or passed.
        """
        return self._state_manager.get_current_version(self._session_id)

    def __await__(self):
        return self._state_manager.get_state(self._session_id).__await__()


class AgentRuntimeEngine:
    """Core runtime coordinator integrating reflex path, deliberate path, and lifecycle."""

    def __init__(
        self,
        event_bus: IEventBus,
        state_manager: IStateManager,
        task_manager: ITaskManager,
        classifier: IInterruptionClassifier,
        tool_registry: IToolRegistry,
        tool_executor: IToolExecutor,
        llm_provider: ILLMProvider,
        trace_logger: ITraceLogger,
    ) -> None:
        self.event_bus = event_bus
        self.state_manager = state_manager
        self.task_manager = task_manager
        self.classifier = classifier
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.llm_provider = llm_provider
        self.trace_logger = trace_logger

        self._history: Dict[str, List[Dict[str, str]]] = {}
        self._is_speaking: Dict[str, bool] = {}

        self.event_bus.subscribe(EventType.USER_TEXT, self.handle_user_input)
        self.event_bus.subscribe(EventType.USER_INTERRUPTION, self.handle_user_interruption)
        self.event_bus.subscribe_all(self._log_and_trace)

    async def _log_and_trace(self, event: RuntimeEvent) -> None:
        await self.trace_logger.log_event(event)

    async def init_session(self, session_id: str) -> SessionState:
        state = await self.state_manager.get_state(session_id)
        # Re-initializing (e.g. a WebSocket reconnect) must not erase the conversation.
        self._history.setdefault(session_id, [])
        self._is_speaking[session_id] = False
        return state

    async def handle_user_interruption(self, event: RuntimeEvent) -> None:
        session_id = event.session_id
        self._is_speaking[session_id] = False
        await self.event_bus.publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.FAST_ACK,
                state_version=event.state_version,
                payload={"text": "Listening..."},
            )
        )

    async def handle_user_input(self, event: RuntimeEvent) -> None:
        session_id = event.session_id
        text = str(event.payload.get("text", ""))

        if session_id not in self._history:
            await self.init_session(session_id)
        # The single place a user turn enters history; the deliberate path reads it.
        history = self._history[session_id]
        history.append({"role": "user", "content": text})
        if len(history) > MAX_HISTORY_TURNS:
            history[:] = history[-MAX_HISTORY_TURNS:]

        current_state = await self.state_manager.get_state(session_id)
        classification = await self.classifier.classify(text, current_state)

        if classification.category == InterruptionCategory.BACKCHANNEL:
            await self.event_bus.publish(
                RuntimeEvent(
                    session_id=session_id,
                    event_type=EventType.FAST_ACK,
                    state_version=current_state.state_version,
                    payload={"text": "Listening...", "category": classification.category.value},
                )
            )
            return

        if classification.category == InterruptionCategory.CANCEL:
            self._is_speaking[session_id] = False
            cancelled_ids = await self.task_manager.cancel_all_active(
                session_id=session_id,
                reason=f"User cancelled: {text}",
            )
            new_state = await self.state_manager.apply_delta(
                session_id=session_id,
                last_user_utterance=text,
            )
            await self.event_bus.publish(
                RuntimeEvent(
                    session_id=session_id,
                    event_type=EventType.TASK_CANCELLED,
                    state_version=new_state.state_version,
                    payload={"cancelled_task_ids": cancelled_ids},
                )
            )
            await self.event_bus.publish(
                RuntimeEvent(
                    session_id=session_id,
                    event_type=EventType.FAST_ACK,
                    state_version=new_state.state_version,
                    payload={"text": "Cancelled.", "category": classification.category.value},
                )
            )
            return

        if self._is_speaking.get(session_id, False):
            self._is_speaking[session_id] = False

        ack_text = "Understood, updating..." if classification.category == InterruptionCategory.CORRECTION else "Checking that now..."
        await self.event_bus.publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.FAST_ACK,
                state_version=current_state.state_version,
                payload={"text": ack_text, "category": classification.category.value},
            )
        )

        # A correction supersedes in-flight work even when no slot delta could be
        # extracted (e.g. it arrives before the slow path has populated any slot):
        # bump the version and cancel, so the outdated plan can never commit.
        if classification.extracted_deltas or classification.category == InterruptionCategory.CORRECTION:
            new_state = await self.state_manager.apply_delta(
                session_id=session_id,
                slot_deltas=classification.extracted_deltas,
                last_user_utterance=text,
            )
            cancelled = await self.task_manager.cancel_affected_tasks(
                session_id=session_id,
                state_delta=classification.extracted_deltas,
                reason="State updated via user correction",
            )
            if cancelled:
                await self.event_bus.publish(
                    RuntimeEvent(
                        session_id=session_id,
                        event_type=EventType.TASK_CANCELLED,
                        state_version=new_state.state_version,
                        payload={"cancelled_task_ids": cancelled},
                    )
                )
            current_state = new_state

        elif classification.category == InterruptionCategory.NEW_QUERY:
            # A new, independent request is authoritative: cancel prior work and
            # drop prior slots/intent so they cannot leak into the new plan. The
            # version bump also makes any uncancellable prior result stale.
            active_ids = await self.task_manager.get_active_task_ids(session_id)
            if active_ids or current_state.slots or current_state.current_intent is not None:
                new_state = await self.state_manager.apply_delta(
                    session_id=session_id,
                    last_user_utterance=text,
                    reset_context=True,
                )
                cancelled = await self.task_manager.cancel_all_active(
                    session_id=session_id,
                    reason=f"Superseded by new query: {text}",
                )
                if cancelled:
                    await self.event_bus.publish(
                        RuntimeEvent(
                            session_id=session_id,
                            event_type=EventType.TASK_CANCELLED,
                            state_version=new_state.state_version,
                            payload={"cancelled_task_ids": cancelled},
                        )
                    )
                current_state = new_state

        reasoning_task_id = f"reason_{uuid.uuid4().hex[:8]}"
        await self.task_manager.spawn_task(
            session_id,
            TaskRecord(
                task_id=reasoning_task_id,
                task_type=TaskType.REASONING,
                origin_state_version=current_state.state_version,
                input_params={"text": text},
            ),
            self._execute_deliberate_path(
                session_id=session_id,
                user_text=text,
                origin_version=current_state.state_version,
                reasoning_task_id=reasoning_task_id,
            ),
        )

    async def _reject_stale_reasoning(
        self,
        session_id: str,
        expected_version: int,
        reasoning_task_id: Optional[str],
    ) -> bool:
        """Return True (and emit TASK_REJECTED_STALE) if the state advanced past expected_version."""
        current_version = self.state_manager.get_current_version(session_id)
        if current_version == expected_version:
            return False
        logger.info(
            "Discarding stale reasoning for session %s (origin v%d, current v%d)",
            session_id, expected_version, current_version,
        )
        if reasoning_task_id:
            await self.task_manager.update_task_status(
                reasoning_task_id,
                status=TaskStatus.STALE,
                error=f"State version advanced from {expected_version} to {current_version}",
            )
        await self.event_bus.publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.TASK_REJECTED_STALE,
                state_version=current_version,
                payload={
                    "task_id": reasoning_task_id,
                    "task_type": TaskType.REASONING.value,
                    "origin_state_version": expected_version,
                    "error": "Reasoning result discarded: state version advanced",
                },
            )
        )
        return True

    async def _synthesize_and_respond(
        self,
        session_id: str,
        user_text: str,
        plan: LLMPlan,
        expected_version: int,
        tool_task_ids: List[str],
        reasoning_task_id: Optional[str],
        history: List[Dict[str, str]],
    ) -> None:
        """Wait for the plan's tools, then publish a reply synthesized from current-version results."""
        records = await self.task_manager.wait_for_tasks(tool_task_ids)

        # A CORRECTION / NEW_QUERY / CANCEL while tools ran makes the whole turn stale.
        if await self._reject_stale_reasoning(session_id, expected_version, reasoning_task_id):
            return

        tool_results = [
            {
                "task_id": r.task_id,
                "tool_name": r.tool_name,
                "status": r.status.value,
                "data": r.result if r.status == TaskStatus.COMPLETED else None,
                "error": r.error,
            }
            for r in records
            if r.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
            and r.origin_state_version == expected_version
        ]

        state = await self.state_manager.get_state(session_id)
        synthesize = getattr(self.llm_provider, "synthesize_response", None)
        if synthesize is not None:
            text = await synthesize(
                session_state=state,
                conversation_history=history,
                user_input=user_text,
                plan=plan,
                tool_results=tool_results,
            )
        else:
            text = compose_tool_response(plan.assistant_response, tool_results)

        # Synthesis may itself await (e.g. a model call): re-check before speaking.
        if await self._reject_stale_reasoning(session_id, expected_version, reasoning_task_id):
            return

        self._is_speaking[session_id] = True
        history.append({"role": "assistant", "content": text})
        await self.event_bus.publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.AGENT_FINAL_RESPONSE,
                state_version=expected_version,
                payload={"text": text, "tool_results": tool_results},
            )
        )

    async def _execute_deliberate_path(
        self,
        session_id: str,
        user_text: str,
        origin_version: int,
        reasoning_task_id: Optional[str] = None,
    ) -> None:
        try:
            state = await self.state_manager.get_state(session_id)
            manifests = self.tool_registry.get_manifests()

            # The user turn was already recorded by handle_user_input.
            history = self._history.setdefault(session_id, [])

            plan = await self.llm_provider.plan_and_reason(
                session_state=state,
                conversation_history=history,
                available_tools=manifests,
                user_input=user_text,
            )

            # The plan was reasoned against origin_version; if the state moved on
            # while the LLM was thinking (CANCEL / CORRECTION), the plan is stale.
            if await self._reject_stale_reasoning(session_id, origin_version, reasoning_task_id):
                return

            if plan.extracted_slots:
                state = await self.state_manager.apply_delta(
                    session_id=session_id,
                    slot_deltas=plan.extracted_slots,
                )

                # Phase 2.2 — Version-aware invalidation:
                # After a state-version advance, cancel only tasks that were created
                # against an older version (origin_state_version < current_version).
                # This is the correctness boundary: cancellation may not prevent a task
                # from completing, but stale-result validation below will reject the result.
                pre_active_ids = await self.task_manager.get_active_task_ids(session_id)
                if pre_active_ids:
                    # Only pass current_version; cancel_tasks_before_version filters
                    # on origin_state_version < current_version internally.
                    invalidated = await self.task_manager.cancel_tasks_before_version(
                        session_id=session_id,
                        current_version=state.state_version,
                        reason="State version advanced",
                        exclude_task_ids=[reasoning_task_id] if reasoning_task_id else None,
                    )
                    if invalidated:
                        logger.debug(
                            "Invalidated %d tasks (version %d) after state delta",
                            len(invalidated),
                            state.state_version,
                        )

            tool_task_ids: List[str] = []
            for proposed in plan.proposed_tool_calls:
                # The runtime, not the LLM, owns origin_state_version: stamp the version
                # the tool is actually scheduled against (after this plan's own delta).
                tool_call = proposed.model_copy(update={"origin_state_version": state.state_version})
                task_id = f"task_{uuid.uuid4().hex[:8]}"
                task_record = TaskRecord(
                    task_id=task_id,
                    task_type=TaskType.TOOL_EXECUTION,
                    tool_name=tool_call.tool_name,
                    origin_state_version=state.state_version,
                )

                await self.event_bus.publish(
                    RuntimeEvent(
                        session_id=session_id,
                        event_type=EventType.TASK_SCHEDULED,
                        state_version=state.state_version,
                        payload={"task_id": task_id, "tool_name": tool_call.tool_name},
                    )
                )

                async def _run_tool(tc: ToolCallRequest = tool_call, tid: str = task_id) -> Any:
                    version_ref = StateRef(self.state_manager, session_id)
                    res = await self.tool_executor.execute(
                        request=tc,
                        current_version_getter=version_ref,
                    )
                    # The executor only version-checks STATE_MODIFYING tools. A READ_ONLY
                    # result is harmless to execute but equally outdated if the state
                    # moved on while it ran, so it must never reach synthesis either.
                    if res.status == TaskStatus.COMPLETED and version_ref() != tc.origin_state_version:
                        res = res.model_copy(update={
                            "status": TaskStatus.STALE,
                            "data": None,
                            "error": (
                                f"Post-execution rejection: state version advanced from "
                                f"{tc.origin_state_version} to {version_ref()}"
                            ),
                        })
                    if res.status == TaskStatus.STALE:
                        # R7a: mark TaskRecord STALE, not just the ToolExecutionResult.
                        # Even if the underlying operation could not be cancelled, the
                        # result is invalid and must not be used downstream.
                        await self.task_manager.update_task_status(
                            tid,
                            status=TaskStatus.STALE,
                            error=res.error,
                        )
                        latest = await self.state_manager.get_state(session_id)
                        await self.event_bus.publish(
                            RuntimeEvent(
                                session_id=session_id,
                                event_type=EventType.TASK_REJECTED_STALE,
                                state_version=latest.state_version,
                                payload={"task_id": tid, "tool_name": tc.tool_name, "error": res.error},
                            )
                        )
                        # R7c: result is discarded; do not return data for downstream processing.
                        return None
                    if res.status == TaskStatus.CANCELLED:
                        await self.task_manager.update_task_status(
                            tid,
                            status=TaskStatus.CANCELLED,
                            error=res.error,
                        )
                        # The executor swallows CancelledError; re-raise if this task
                        # was actually cancelled so the cancellation is not lost.
                        current = asyncio.current_task()
                        if current is not None and current.cancelling():
                            raise asyncio.CancelledError()
                        return None
                    if res.status != TaskStatus.COMPLETED:
                        await self.task_manager.update_task_status(
                            tid,
                            status=TaskStatus.FAILED,
                            error=res.error,
                        )
                        return None
                    # R8: Valid successful result — mark COMPLETED and return data.
                    await self.task_manager.update_task_status(
                        tid,
                        status=TaskStatus.COMPLETED,
                        result=res.data,
                    )
                    return res.data

                await self.task_manager.spawn_task(session_id, task_record, _run_tool())
                tool_task_ids.append(task_id)

            if tool_task_ids:
                await self._synthesize_and_respond(
                    session_id, user_text, plan, state.state_version, tool_task_ids, reasoning_task_id, history,
                )
            elif plan.assistant_response:
                # state.state_version already includes this plan's own slot delta.
                if await self._reject_stale_reasoning(session_id, state.state_version, reasoning_task_id):
                    return
                self._is_speaking[session_id] = True
                history.append({"role": "assistant", "content": plan.assistant_response})
                await self.event_bus.publish(
                    RuntimeEvent(
                        session_id=session_id,
                        event_type=EventType.AGENT_FINAL_RESPONSE,
                        state_version=state.state_version,
                        payload={"text": plan.assistant_response},
                    )
                )
        except asyncio.CancelledError:
            logger.info("Deliberate path cancelled for session %s", session_id)
            raise
        except Exception as e:
            logger.error("Error in deliberate path: %s", e, exc_info=True)
            await self.event_bus.publish(
                RuntimeEvent(
                    session_id=session_id,
                    event_type=EventType.SYSTEM_ERROR,
                    state_version=origin_version,
                    payload={"error": str(e)},
                )
            )
        finally:
            # Always reset the speaking flag so the next user turn is processed
            # by the reflex path, not silently deferred.
            self._is_speaking[session_id] = False

