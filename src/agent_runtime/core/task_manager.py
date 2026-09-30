"""Task Manager supervising task lifecycles, cancellations, and state-version alignment."""

import asyncio
import inspect
from datetime import datetime, timezone
import logging
from typing import Any, Awaitable, Dict, List, Optional
from ..interfaces.task_manager import ITaskManager
from ..models.tasks import TaskRecord, TaskStatus

logger = logging.getLogger(__name__)


class TaskManager(ITaskManager):
    """Supervises async agent tasks with lifecycle FSM and cancellation."""

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._session_tasks: Dict[str, List[str]] = {}
        self._asyncio_tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def spawn_task(
        self,
        session_id: str,
        task: TaskRecord,
        coro: Awaitable[Any],
    ) -> str:
        async with self._lock:
            self._tasks[task.task_id] = task
            if session_id not in self._session_tasks:
                self._session_tasks[session_id] = []
            self._session_tasks[session_id].append(task.task_id)

            async def _runner() -> None:
                try:
                    async with self._lock:
                        rec = self._tasks[task.task_id]
                        if rec.status == TaskStatus.PENDING:
                            rec.status = TaskStatus.RUNNING
                            rec.started_at = datetime.now(timezone.utc)
                    res = await coro
                    async with self._lock:
                        t = self._tasks[task.task_id]
                        if t.status in (TaskStatus.RUNNING, TaskStatus.PENDING):
                            t.status = TaskStatus.COMPLETED
                            t.result = res
                            t.completed_at = datetime.now(timezone.utc)
                except asyncio.CancelledError:
                    async with self._lock:
                        t = self._tasks[task.task_id]
                        t.status = TaskStatus.CANCELLED
                        t.completed_at = datetime.now(timezone.utc)
                    raise
                except Exception as ex:
                    async with self._lock:
                        t = self._tasks[task.task_id]
                        t.status = TaskStatus.FAILED
                        t.error = str(ex)
                        t.completed_at = datetime.now(timezone.utc)
                    logger.error(f"Task {task.task_id} failed: {ex}")

            atask = asyncio.create_task(_runner())
            atask.add_done_callback(lambda t: self._finalize_unstarted(task.task_id, coro, t))
            self._asyncio_tasks[task.task_id] = atask
            return task.task_id

    def _finalize_unstarted(self, task_id: str, coro: Awaitable[Any], atask: asyncio.Task) -> None:
        """
        Finalize a task that was cancelled before _runner reached its body.

        asyncio cancels a not-yet-started task by throwing into the unstarted
        _runner coroutine, so its except-handler never runs. Without this, the
        record would stay CANCELLING and the wrapped coroutine would never be
        awaited (RuntimeWarning). Runs synchronously on the event loop, so it
        needs no lock.
        """
        if inspect.iscoroutine(coro) and inspect.getcoroutinestate(coro) == inspect.CORO_CREATED:
            coro.close()
        if not atask.cancelled():
            return
        rec = self._tasks.get(task_id)
        if rec and rec.status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.CANCELLING):
            rec.status = TaskStatus.CANCELLED
            rec.completed_at = datetime.now(timezone.utc)

    async def cancel_affected_tasks(
        self,
        session_id: str,
        state_delta: Dict[str, Any],
        reason: str,
    ) -> List[str]:
        """Cancel active tasks affected by state changes."""
        cancelled_ids: List[str] = []
        async with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            for tid in task_ids:
                record = self._tasks.get(tid)
                if not record:
                    continue
                if record.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    record.status = TaskStatus.CANCELLING
                    record.cancellation_reason = reason
                    atask = self._asyncio_tasks.get(tid)
                    if atask and not atask.done():
                        atask.cancel()
                    cancelled_ids.append(tid)
        return cancelled_ids

    async def cancel_all_active(
        self,
        session_id: str,
        reason: str,
    ) -> List[str]:
        """Cancel all active tasks for session."""
        cancelled_ids: List[str] = []
        async with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            for tid in task_ids:
                record = self._tasks.get(tid)
                if not record:
                    continue
                if record.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    record.status = TaskStatus.CANCELLING
                    record.cancellation_reason = reason
                    atask = self._asyncio_tasks.get(tid)
                    if atask and not atask.done():
                        atask.cancel()
                    cancelled_ids.append(tid)
        return cancelled_ids

    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        async with self._lock:
            rec = self._tasks.get(task_id)
            return rec.model_copy(deep=True) if rec else None

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[Any] = None,
        error: Optional[str] = None,
    ) -> TaskRecord:
        async with self._lock:
            if task_id not in self._tasks:
                raise KeyError(f"Task {task_id} not found")
            t = self._tasks[task_id]
            t.status = status
            if result is not None:
                t.result = result
            if error is not None:
                t.error = error
            if status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.STALE):
                t.completed_at = datetime.now(timezone.utc)
            return t.model_copy(deep=True)

    async def get_session_tasks(self, session_id: str) -> List[TaskRecord]:
        async with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            return [self._tasks[tid].model_copy(deep=True) for tid in task_ids if tid in self._tasks]

    async def wait_for_tasks(self, task_ids: List[str]) -> List[TaskRecord]:
        """
        Wait until the given tasks reach a terminal state and return their records.

        Observes only: task failures/cancellations are reflected in the records,
        not raised. If the waiter itself is cancelled, CancelledError propagates
        to the waiter while the awaited tasks are left untouched (they are
        cancelled, if at all, through the normal cancel_* paths).
        """
        atasks = [self._asyncio_tasks[t] for t in task_ids if t in self._asyncio_tasks]
        if atasks:
            await asyncio.wait(atasks)
        records = [await self.get_task(t) for t in task_ids]
        return [r for r in records if r is not None]

    async def get_active_task_ids(self, session_id: str) -> List[str]:
        """
        Return IDs of all active (PENDING or RUNNING) tasks for the session.
        Used by the runtime engine to identify tasks that may need invalidation
        after a state-version advance.
        """
        async with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            return [
                tid
                for tid in task_ids
                if tid in self._tasks
                and self._tasks[tid].status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ]

    async def cancel_tasks_before_version(
        self,
        session_id: str,
        current_version: int,
        reason: str,
        exclude_task_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Version-aware task invalidation.

        Identifies active tasks whose origin_state_version is strictly less than
        current_version — meaning the state has advanced since those tasks were
        spawned — and cancels them through the standard cancellation mechanism.

        Does NOT cancel tasks created at the current version.

        This is the correctness boundary for requirement 7: a task that cannot
        be cancelled may still complete, but this method ensures that every task
        whose origin version is behind the current version transitions to
        CANCELLING (or CANCELLED if it finishes immediately).

        Explicit user-initiated "cancel everything" should still use
        cancel_all_active() to preserve the existing CANCEL semantics.
        """
        cancelled_ids: List[str] = []
        async with self._lock:
            task_ids = self._session_tasks.get(session_id, [])
            for tid in task_ids:
                record = self._tasks.get(tid)
                if not record or (exclude_task_ids and tid in exclude_task_ids):
                    continue
                # Only invalidate tasks that were created against an older state version.
                # Tasks created at the current (new) version are unaffected.
                if record.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                    if record.origin_state_version < current_version:
                        record.status = TaskStatus.CANCELLING
                        record.cancellation_reason = reason
                        atask = self._asyncio_tasks.get(tid)
                        if atask and not atask.done():
                            atask.cancel()
                        cancelled_ids.append(tid)
        return cancelled_ids

