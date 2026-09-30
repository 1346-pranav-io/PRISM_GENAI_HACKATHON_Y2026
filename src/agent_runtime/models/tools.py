"""Dynamic tool manifest and execution schema models."""

from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from .tasks import TaskStatus


class ToolCategory(str, Enum):
    READ_ONLY = "READ_ONLY"
    STATE_MODIFYING = "STATE_MODIFYING"


class ToolManifest(BaseModel):
    name: str
    description: str
    category: ToolCategory
    parameters_schema: Dict[str, Any]
    supports_cancellation: bool = True
    timeout_seconds: float = 30.0
    idempotency_required: bool = False


class ToolCallRequest(BaseModel):
    call_id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = None
    origin_state_version: int


class ToolExecutionResult(BaseModel):
    call_id: str
    tool_name: str
    status: TaskStatus
    data: Optional[Any] = None
    error: Optional[str] = None
    execution_duration_ms: float = 0.0
    origin_state_version: int
