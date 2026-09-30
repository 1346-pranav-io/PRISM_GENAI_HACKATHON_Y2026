"""State manager abstract interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from ..models.state import SessionState


class IStateManager(ABC):
    @abstractmethod
    async def get_state(self, session_id: str) -> SessionState:
        """Retrieve current session state."""
        pass

    @abstractmethod
    async def create_session(self, session_id: str) -> SessionState:
        """Initialize a new session with version 1."""
        pass

    @abstractmethod
    async def apply_delta(
        self,
        session_id: str,
        slot_deltas: Optional[Dict[str, Any]] = None,
        intent: Optional[str] = None,
        last_user_utterance: Optional[str] = None,
        last_assistant_utterance: Optional[str] = None,
        reset_context: bool = False,
    ) -> SessionState:
        """Atomically mutate state and increment state_version.

        reset_context=True clears prior slots and intent before applying the delta.
        """
        pass

    @abstractmethod
    async def is_valid_version(self, session_id: str, state_version: int) -> bool:
        """Check if a given version matches current session version."""
        pass

    def get_current_version(self, session_id: str) -> int:
        """
        Synchronous, lock-free read of the current state version.

        This is the single-writer / multiple-reader pattern: writes only happen
        inside apply_delta (always on the asyncio event loop), so reading the
        state_version int directly from self._states is safe from any thread.

        Used by StateRef to satisfy ToolExecutor's Callable[[], int] interface
        while guaranteeing the returned value is always the current (live) version,
        evaluated at the moment of the call — never a stale snapshot.
        """
        ...
