"""Tool executor abstract interface."""

from abc import ABC, abstractmethod
from typing import Callable
from ..models.tools import ToolCallRequest, ToolExecutionResult


class IToolExecutor(ABC):
    @abstractmethod
    async def execute(
        self,
        request: ToolCallRequest,
        current_version_getter: Callable[[], int],
    ) -> ToolExecutionResult:
        """Execute a tool call with idempotency check, cancellation monitoring, and stale verification."""
        pass
