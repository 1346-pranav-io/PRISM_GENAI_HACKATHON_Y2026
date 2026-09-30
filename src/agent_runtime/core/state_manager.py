"""Thread-safe, versioned Session State Manager."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from ..interfaces.state_manager import IStateManager
from ..models.state import SessionState, SessionStatus, SlotValue


class StateManager(IStateManager):
    """Manages session states with strict version monotonicity and lock concurrency."""

    def __init__(self) -> None:
        self._states: Dict[str, SessionState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_lock(self, session_id: str) -> asyncio.Lock:
        async with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = asyncio.Lock()
            return self._locks[session_id]

    async def create_session(self, session_id: str) -> SessionState:
        """Initialize a new session with state_version = 1."""
        lock = await self._get_lock(session_id)
        async with lock:
            now = datetime.now(timezone.utc)
            state = SessionState(
                session_id=session_id,
                state_version=1,
                status=SessionStatus.ACTIVE,
                slots={},
                active_task_ids=[],
                completed_task_ids=[],
                cancelled_task_ids=[],
                stale_task_ids=[],
                created_at=now,
                updated_at=now,
            )
            self._states[session_id] = state
            return state.model_copy(deep=True)

    async def get_state(self, session_id: str) -> SessionState:
        """Retrieve current session state (or create default if not exists)."""
        lock = await self._get_lock(session_id)
        async with lock:
            if session_id not in self._states:
                now = datetime.now(timezone.utc)
                self._states[session_id] = SessionState(
                    session_id=session_id,
                    state_version=1,
                    status=SessionStatus.ACTIVE,
                    slots={},
                    created_at=now,
                    updated_at=now,
                )
            return self._states[session_id].model_copy(deep=True)

    async def apply_delta(
        self,
        session_id: str,
        slot_deltas: Optional[Dict[str, Any]] = None,
        intent: Optional[str] = None,
        last_user_utterance: Optional[str] = None,
        last_assistant_utterance: Optional[str] = None,
        reset_context: bool = False,
    ) -> SessionState:
        """Atomically mutate state, update slots with origin version, and increment state_version.

        reset_context=True clears existing slots and the current intent before the
        delta is applied (a new, independent request replaces the prior context).
        """
        lock = await self._get_lock(session_id)
        async with lock:
            if session_id not in self._states:
                now = datetime.now(timezone.utc)
                self._states[session_id] = SessionState(
                    session_id=session_id,
                    state_version=1,
                    status=SessionStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )

            current = self._states[session_id]
            has_changes = (
                bool(slot_deltas)
                or (reset_context and (bool(current.slots) or current.current_intent is not None))
                or (intent is not None and intent != current.current_intent)
                or (last_user_utterance is not None)
                or (last_assistant_utterance is not None)
            )

            if not has_changes:
                return current.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            new_version = current.state_version + 1

            new_slots = {} if reset_context else dict(current.slots)
            if slot_deltas:
                for k, v in slot_deltas.items():
                    new_slots[k] = SlotValue(
                        key=k,
                        value=v,
                        confidence=1.0,
                        source_state_version=new_version,
                        updated_at=now,
                    )

            updated_state = current.model_copy(
                update={
                    "state_version": new_version,
                    "slots": new_slots,
                    "current_intent": (
                        intent if intent is not None
                        else None if reset_context
                        else current.current_intent
                    ),
                    "last_user_utterance": (
                        last_user_utterance
                        if last_user_utterance is not None
                        else current.last_user_utterance
                    ),
                    "last_assistant_utterance": (
                        last_assistant_utterance
                        if last_assistant_utterance is not None
                        else current.last_assistant_utterance
                    ),
                    "updated_at": now,
                },
                deep=True,
            )

            self._states[session_id] = updated_state
            return updated_state.model_copy(deep=True)

    async def is_valid_version(self, session_id: str, state_version: int) -> bool:
        """Check if the given version matches current session version."""
        lock = await self._get_lock(session_id)
        async with lock:
            if session_id not in self._states:
                return False
            return self._states[session_id].state_version == state_version

    # ------------------------------------------------------------------
    # Synchronous single-writer / multiple-reader accessor.
    # Writes (apply_delta) only ever happen on the asyncio event loop.
    # Reading a plain Python int from a dict value is safe from threads.
    # ------------------------------------------------------------------
    def get_current_version(self, session_id: str) -> int:
        state = self._states.get(session_id)
        if state is None:
            return 0  # Session not yet created — caller must handle.
        return state.state_version
