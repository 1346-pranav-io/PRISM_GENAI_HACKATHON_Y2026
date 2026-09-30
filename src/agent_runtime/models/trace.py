"""Trace logging and event replay models."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .events import EventType, RuntimeEvent


class TraceEntry(BaseModel):
    """An immutable recorded trace entry representing a point-in-time runtime event."""

    trace_id: str
    session_id: str
    event: RuntimeEvent
    persisted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionTrace(BaseModel):
    session_id: str
    events: List[RuntimeEvent] = Field(default_factory=list)
    start_time: datetime
    end_time: Optional[datetime] = None
    final_state_version: int = 1
