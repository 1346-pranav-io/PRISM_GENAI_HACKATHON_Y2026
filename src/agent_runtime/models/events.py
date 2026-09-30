"""Event protocol models for runtime communication."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, Field


class EventType(str, Enum):
    # Inbound
    USER_TEXT = "USER_TEXT"
    USER_INTERRUPTION = "USER_INTERRUPTION"
    AUDIO_CHUNK = "AUDIO_CHUNK"
    VIDEO_FRAME = "VIDEO_FRAME"
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"

    # Outbound / Internal
    FAST_ACK = "FAST_ACK"
    STATE_MUTATED = "STATE_MUTATED"
    TASK_SCHEDULED = "TASK_SCHEDULED"
    TASK_STARTED = "TASK_STARTED"
    TASK_CANCELLING = "TASK_CANCELLING"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_REJECTED_STALE = "TASK_REJECTED_STALE"
    AGENT_SPEAKING = "AGENT_SPEAKING"
    AGENT_FINAL_RESPONSE = "AGENT_FINAL_RESPONSE"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class RuntimeEvent(BaseModel):
    """Represents a validated event within the runtime."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    event_type: EventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    state_version: int
    payload: Dict[str, Any] = Field(default_factory=dict)
