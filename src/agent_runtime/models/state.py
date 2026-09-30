"""State and slot tracking models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


class SlotValue(BaseModel):
    key: str
    value: Any
    confidence: float = 1.0
    source_state_version: int
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionState(BaseModel):
    session_id: str
    state_version: int = 1
    status: SessionStatus = SessionStatus.ACTIVE
    current_intent: Optional[str] = None
    slots: Dict[str, SlotValue] = Field(default_factory=dict)
    active_task_ids: List[str] = Field(default_factory=list)
    completed_task_ids: List[str] = Field(default_factory=list)
    cancelled_task_ids: List[str] = Field(default_factory=list)
    stale_task_ids: List[str] = Field(default_factory=list)
    last_user_utterance: Optional[str] = None
    last_assistant_utterance: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
