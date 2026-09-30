"""Task manager abstract interface."""

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Dict, List, Optional
from ..models.tasks import TaskRecord, TaskStatus


class ITaskManager(ABC):
    @abstractmethod
    async def spawn_task(
        self,
        session_id: str,
        task: TaskRecord,
        coro: Awaitable[Any],
    ) -> str:
        """Spawn a tracked async task."""
        pass

    @abstractmethod
    async def cancel_affected_tasks(
        self,
        session_id: str,
        state_delta: Dict[str, Any],
        reason: str,
    ) -> List[str]:
        """Cancel tasks affected by state mutation."""
        pass

    @abstractmethod
    async def cancel_all_active(
        self,
        session_id: str,
        reason: str,
    ) -> List[str]:
        """Cancel all currently running tasks for session."""
        pass

    @abstractmethod
    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Retrieve task record by ID."""
        pass

    @abstractmethod
    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> TaskRecord:
        """Update task record lifecycle state."""
        pass
