"""Task lifecycle and execution models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
import uuid
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    STALE = "STALE"


class TaskType(str, Enum):
    REASONING = "REASONING"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    MULTIMODAL_PROCESSING = "MULTIMODAL_PROCESSING"
    SPEECH_SYNTHESIS = "SPEECH_SYNTHESIS"


class TaskRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    call_id: Optional[str] = None
    task_type: TaskType
    tool_name: Optional[str] = None
    input_params: Dict[str, Any] = Field(default_factory=dict)
    origin_state_version: int
    status: TaskStatus = TaskStatus.PENDING
    idempotency_key: Optional[str] = None
    is_state_modifying: bool = False
    result: Optional[Any] = None
    error: Optional[str] = None
    cancellation_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
