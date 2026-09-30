"""In-memory and JSONL-persisted Trace Logger."""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
from ..interfaces.trace_logger import ITraceLogger
from ..models.events import RuntimeEvent
from ..models.trace import SessionTrace, TraceEntry


class TraceLogger(ITraceLogger):
    """Logs and indexes all runtime events per session for replay and evaluation."""

    def __init__(self, output_dir: Optional[str] = None) -> None:
        self._output_dir = output_dir
        self._traces: Dict[str, List[RuntimeEvent]] = {}
        self._session_start_times: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def log_event(self, event: RuntimeEvent) -> None:
        """Append an event to the session trace."""
        async with self._lock:
            if event.session_id not in self._traces:
                self._traces[event.session_id] = []
                self._session_start_times[event.session_id] = event.timestamp

            self._traces[event.session_id].append(event)

    async def get_session_trace(self, session_id: str) -> Optional[SessionTrace]:
        """Get the full chronological trace object for a session."""
        async with self._lock:
            if session_id not in self._traces:
                return None

            events = list(self._traces[session_id])
            start_time = self._session_start_times.get(
                session_id,
                events[0].timestamp if events else datetime.now(timezone.utc),
            )
            final_version = events[-1].state_version if events else 1

            return SessionTrace(
                session_id=session_id,
                events=events,
                start_time=start_time,
                end_time=events[-1].timestamp if events else None,
                final_state_version=final_version,
            )

    async def get_all_events(self, session_id: str) -> List[RuntimeEvent]:
        """Retrieve a copy of all raw events for a session."""
        async with self._lock:
            return list(self._traces.get(session_id, []))
