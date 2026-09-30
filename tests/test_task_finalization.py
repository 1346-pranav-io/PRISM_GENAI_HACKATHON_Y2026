"""Tasks cancelled before (or while) their runner starts must still be finalized cleanly."""

import asyncio
import gc
import warnings

import pytest

from src.agent_runtime.core.task_manager import TaskManager
from src.agent_runtime.models.tasks import TaskRecord, TaskStatus, TaskType


def _record(task_id, version=1):
    return TaskRecord(task_id=task_id, task_type=TaskType.TOOL_EXECUTION, origin_state_version=version)


async def _slow():
    await asyncio.sleep(5)
    return "done"


def _never_awaited(caught):
    return [w for w in caught if "was never awaited" in str(w.message)]


async def _assert_cancelled_cleanly(cancel):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tm = TaskManager()
        await tm.spawn_task("s", _record("t1"), _slow())
        cancelled = await cancel(tm)  # the runner has not been scheduled yet
        assert cancelled == ["t1"]
        await asyncio.sleep(0.01)

        rec = await tm.get_task("t1")
        assert rec.status == TaskStatus.CANCELLED
        assert rec.completed_at is not None
        assert await tm.get_active_task_ids("s") == []
        assert tm._asyncio_tasks["t1"].done()

        del tm, rec
        gc.collect()
    assert _never_awaited(caught) == []


@pytest.mark.asyncio
async def test_cancel_all_active_before_start_finalizes():
    await _assert_cancelled_cleanly(lambda tm: tm.cancel_all_active("s", reason="stop"))


@pytest.mark.asyncio
async def test_cancel_affected_before_start_finalizes():
    await _assert_cancelled_cleanly(lambda tm: tm.cancel_affected_tasks("s", {"x": 1}, reason="delta"))


@pytest.mark.asyncio
async def test_cancel_before_version_before_start_finalizes():
    await _assert_cancelled_cleanly(
        lambda tm: tm.cancel_tasks_before_version("s", current_version=2, reason="advanced")
    )


@pytest.mark.asyncio
async def test_cancel_while_runner_waits_for_lock_finalizes():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tm = TaskManager()
        await tm.spawn_task("s", _record("t1"), _slow())
        async with tm._lock:
            await asyncio.sleep(0)  # runner starts and blocks on the lock
            tm._asyncio_tasks["t1"].cancel()
        await asyncio.sleep(0.01)
        assert (await tm.get_task("t1")).status == TaskStatus.CANCELLED
        del tm
        gc.collect()
    assert _never_awaited(caught) == []


@pytest.mark.asyncio
async def test_cancel_after_start_still_runs_coroutine_cleanup():
    cleaned_up = asyncio.Event()

    async def with_cleanup():
        try:
            await asyncio.sleep(5)
        finally:
            cleaned_up.set()

    tm = TaskManager()
    await tm.spawn_task("s", _record("t1"), with_cleanup())
    await asyncio.sleep(0.01)
    assert (await tm.get_task("t1")).status == TaskStatus.RUNNING
    await tm.cancel_all_active("s", reason="stop")
    await asyncio.sleep(0.01)
    assert cleaned_up.is_set()
    assert (await tm.get_task("t1")).status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_uncancelled_tasks_are_unaffected_by_finalizer():
    async def boom():
        raise RuntimeError("x")

    tm = TaskManager()
    await tm.spawn_task("s", _record("ok"), asyncio.sleep(0, result="r"))
    await tm.spawn_task("s", _record("bad"), boom())
    await asyncio.sleep(0.01)
    assert (await tm.get_task("ok")).status == TaskStatus.COMPLETED
    assert (await tm.get_task("ok")).result == "r"
    assert (await tm.get_task("bad")).status == TaskStatus.FAILED
