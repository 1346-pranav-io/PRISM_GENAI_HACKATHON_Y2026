"""Trace logger abstract interface."""

from abc import ABC, abstractmethod
from typing import List, Optional
from ..models.events import RuntimeEvent
from ..models.trace import SessionTrace


class ITraceLogger(ABC):
    @abstractmethod
    async def log_event(self, event: RuntimeEvent) -> None:
        """Append an event to the immutable session trace."""
        pass

    @abstractmethod
    async def get_session_trace(self, session_id: str) -> Optional[SessionTrace]:
        """Retrieve full chronological trace for session."""
        pass

    @abstractmethod
    async def get_all_events(self, session_id: str) -> List[RuntimeEvent]:
        """Retrieve all raw events for session in order."""
        pass
