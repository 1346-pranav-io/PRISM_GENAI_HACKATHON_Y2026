"""Unit tests for TaskManager lifecycle and cancellation."""

import asyncio
import pytest
from src.agent_runtime.core.task_manager import TaskManager
from src.agent_runtime.models.tasks import TaskRecord, TaskStatus, TaskType


@pytest.mark.asyncio
async def test_task_normal_completion():
    tm = TaskManager()

    async def sample_work():
        await asyncio.sleep(0.01)
        return {"flights": ["AI101", "AI102"]}

    task = TaskRecord(
        task_id="t1",
        task_type=TaskType.TOOL_EXECUTION,
        tool_name="search_flights",
        origin_state_version=1,
    )

    await tm.spawn_task("session_1", task, sample_work())
    await asyncio.sleep(0.05)

    rec = await tm.get_task("t1")
    assert rec is not None
    assert rec.status == TaskStatus.COMPLETED
    assert rec.result == {"flights": ["AI101", "AI102"]}
    assert rec.started_at is not None
    assert rec.completed_at is not None


@pytest.mark.asyncio
async def test_task_cancellation_mid_flight():
    tm = TaskManager()

    async def long_work():
        try:
            await asyncio.sleep(1.0)
            return "never reached"
        except asyncio.CancelledError:
            raise

    task = TaskRecord(
        task_id="t2",
        task_type=TaskType.REASONING,
        origin_state_version=1,
    )

    await tm.spawn_task("session_1", task, long_work())
    await asyncio.sleep(0.01)

    rec = await tm.get_task("t2")
    assert rec.status == TaskStatus.RUNNING

    cancelled = await tm.cancel_all_active("session_1", reason="User interrupted")
    assert "t2" in cancelled

    await asyncio.sleep(0.02)
    rec_after = await tm.get_task("t2")
    assert rec_after.status == TaskStatus.CANCELLED
    assert rec_after.cancellation_reason == "User interrupted"


@pytest.mark.asyncio
async def test_stale_result_rejection():
    tm = TaskManager()

    task = TaskRecord(
        task_id="t3",
        task_type=TaskType.TOOL_EXECUTION,
        tool_name="search_flights",
        origin_state_version=1,
    )

    await tm.spawn_task("session_1", task, asyncio.sleep(0.01))
    await asyncio.sleep(0.03)

    # Simulate stale detection at state reconciliation
    updated = await tm.update_task_status(
        "t3",
        status=TaskStatus.STALE,
        error="Discarded: superseded by version 2",
    )
    assert updated.status == TaskStatus.STALE
    assert updated.error == "Discarded: superseded by version 2"


# ---------------------------------------------------------------------------
# Phase 2.2: Version-aware invalidation and stale-result protection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_tasks_before_version_only_invalidates_old_tasks():
    """
    Phase 2.2 - Version-filtered cancellation.

    Task A: origin_state_version=1
    Task B: origin_state_version=2
    current_version=2

    Only Task A (origin < current) is cancelled.
    Task B (origin == current) remains active.
    """
    tm = TaskManager()

    task_a = TaskRecord(
        task_id="task_a",
        task_type=TaskType.TOOL_EXECUTION,
        tool_name="search",
        origin_state_version=1,
    )
    task_b = TaskRecord(
        task_id="task_b",
        task_type=TaskType.TOOL_EXECUTION,
        tool_name="search",
        origin_state_version=2,
    )

    async def slow_work():
        await asyncio.sleep(5.0)

    await tm.spawn_task("session_1", task_a, slow_work())
    await tm.spawn_task("session_1", task_b, slow_work())
    await asyncio.sleep(0.02)

    rec_a = await tm.get_task("task_a")
    rec_b = await tm.get_task("task_b")
    assert rec_a.status == TaskStatus.RUNNING
    assert rec_b.status == TaskStatus.RUNNING

    # Version 2 advance: only task A (origin=1) is invalid; task B (origin=2) survives.
    cancelled = await tm.cancel_tasks_before_version(
        session_id="session_1",
        current_version=2,
        reason="State version advanced",
    )

    assert "task_a" in cancelled
    assert "task_b" not in cancelled

    await asyncio.sleep(0.02)

    rec_a_after = await tm.get_task("task_a")
    rec_b_after = await tm.get_task("task_b")

    assert rec_a_after.status == TaskStatus.CANCELLED
    assert rec_b_after.status == TaskStatus.RUNNING, (
        "Task B at current_version should not be cancelled"
    )


@pytest.mark.asyncio
async def test_cancel_tasks_before_version_preserves_current_version_tasks():
    """
    Phase 2.2 - Tasks created at the new version survive version advance.

    A task with origin_state_version == current_version is NOT cancelled.
    """
    tm = TaskManager()

    async def slow_work():
        await asyncio.sleep(5.0)

    task = TaskRecord(
        task_id="task_current_ver",
        task_type=TaskType.TOOL_EXECUTION,
        origin_state_version=3,
    )
    await tm.spawn_task("session_1", task, slow_work())
    await asyncio.sleep(0.02)

    rec_before = await tm.get_task("task_current_ver")
    assert rec_before.status == TaskStatus.RUNNING

    # current_version == 3, task origin == 3 - not cancelled
    cancelled = await tm.cancel_tasks_before_version(
        session_id="session_1",
        current_version=3,
        reason="State version advanced",
    )

    assert cancelled == []
    await asyncio.sleep(0.02)

    rec_after = await tm.get_task("task_current_ver")
    assert rec_after.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_all_active_cancels_everything():
    """
    Phase 2.2 - Explicit CANCEL must still cancel ALL active tasks.

    Unlike version-aware invalidation, explicit cancel_all_active() does not
    filter by origin_state_version.  All PENDING/RUNNING tasks are cancelled.
    """
    tm = TaskManager()

    async def slow_work():
        await asyncio.sleep(5.0)

    task_a = TaskRecord(task_id="cancel_all_a", origin_state_version=1, task_type=TaskType.TOOL_EXECUTION)
    task_b = TaskRecord(task_id="cancel_all_b", origin_state_version=2, task_type=TaskType.TOOL_EXECUTION)
    task_c = TaskRecord(task_id="cancel_all_c", origin_state_version=3, task_type=TaskType.TOOL_EXECUTION)

    await tm.spawn_task("sess_cancel_all", task_a, slow_work())
    await tm.spawn_task("sess_cancel_all", task_b, slow_work())
    await tm.spawn_task("sess_cancel_all", task_c, slow_work())
    await asyncio.sleep(0.02)

    cancelled = await tm.cancel_all_active(
        session_id="sess_cancel_all",
        reason="User explicitly cancelled",
    )

    assert len(cancelled) == 3
    assert set(cancelled) == {"cancel_all_a", "cancel_all_b", "cancel_all_c"}

    await asyncio.sleep(0.02)
    for tid in ["cancel_all_a", "cancel_all_b", "cancel_all_c"]:
        rec = await tm.get_task(tid)
        assert rec.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_get_active_task_ids_excludes_terminal_tasks():
    """
    Phase 2.2 - get_active_task_ids returns only PENDING/RUNNING tasks.

    COMPLETED, FAILED, CANCELLED, and STALE tasks are excluded.
    """
    tm = TaskManager()

    async def fast_work():
        await asyncio.sleep(0.01)
        return "done"

    async def slow_work():
        await asyncio.sleep(5.0)

    fast_task = TaskRecord(task_id="fast_task", origin_state_version=1, task_type=TaskType.TOOL_EXECUTION)
    slow_task = TaskRecord(task_id="slow_task", origin_state_version=1, task_type=TaskType.TOOL_EXECUTION)
    cancelled_task = TaskRecord(task_id="cancelled_task", origin_state_version=1, task_type=TaskType.TOOL_EXECUTION)
    stale_task = TaskRecord(task_id="stale_task", origin_state_version=1, task_type=TaskType.TOOL_EXECUTION)

    await tm.spawn_task("sess_active", fast_task, fast_work())
    await tm.spawn_task("sess_active", slow_task, slow_work())
    await tm.spawn_task("sess_active", cancelled_task, slow_work())
    await tm.spawn_task("sess_active", stale_task, slow_work())

    await asyncio.sleep(0.05)  # fast_task completes

    await tm.cancel_all_active("sess_active", "test")
    await tm.update_task_status("stale_task", status=TaskStatus.STALE)

    active = await tm.get_active_task_ids("sess_active")

    # All tasks are now in terminal states; active should be empty.
    assert "fast_task" not in active
    assert "slow_task" not in active
    assert "cancelled_task" not in active
    assert "stale_task" not in active
    assert active == []