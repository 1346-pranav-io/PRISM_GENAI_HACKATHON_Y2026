"""Unit tests for ToolRegistry and ToolExecutor."""

import asyncio
import pytest
from src.agent_runtime.core.tool_executor import ToolExecutor
from src.agent_runtime.core.tool_registry import ToolRegistry
from src.agent_runtime.models.tasks import TaskStatus
from src.agent_runtime.models.tools import ToolCallRequest, ToolCategory, ToolManifest


@pytest.mark.asyncio
async def test_tool_registration_and_execution():
    registry = ToolRegistry()

    async def add_nums(a: int, b: int):
        return a + b

    manifest = ToolManifest(
        name="add",
        description="Adds two numbers",
        category=ToolCategory.READ_ONLY,
        parameters_schema={"type": "object"},
    )
    registry.register_tool(manifest, add_nums)

    executor = ToolExecutor(registry)
    req = ToolCallRequest(
        call_id="call_1",
        tool_name="add",
        arguments={"a": 5, "b": 7},
        origin_state_version=1,
    )

    res = await executor.execute(req, current_version_getter=lambda: 1)
    assert res.status == TaskStatus.COMPLETED
    assert res.data == 12
    assert res.error is None


@pytest.mark.asyncio
async def test_tool_pre_execution_stale_rejection():
    registry = ToolRegistry()

    async def book_ticket(flight_id: str):
        return {"booked": flight_id}

    manifest = ToolManifest(
        name="book_ticket",
        description="Book a flight ticket",
        category=ToolCategory.STATE_MODIFYING,
        parameters_schema={"type": "object"},
    )
    registry.register_tool(manifest, book_ticket)

    executor = ToolExecutor(registry)
    req = ToolCallRequest(
        call_id="call_2",
        tool_name="book_ticket",
        arguments={"flight_id": "AI202"},
        origin_state_version=1,
    )

    # Current version has advanced to 2
    res = await executor.execute(req, current_version_getter=lambda: 2)
    assert res.status == TaskStatus.STALE
    assert "advanced" in (res.error or "")


@pytest.mark.asyncio
async def test_tool_timeout_handling():
    registry = ToolRegistry()

    async def slow_fn():
        await asyncio.sleep(0.5)
        return "done"

    manifest = ToolManifest(
        name="slow",
        description="Slow function",
        category=ToolCategory.READ_ONLY,
        parameters_schema={},
        timeout_seconds=0.05,
    )
    registry.register_tool(manifest, slow_fn)

    executor = ToolExecutor(registry)
    req = ToolCallRequest(
        call_id="call_3",
        tool_name="slow",
        arguments={},
        origin_state_version=1,
    )

    res = await executor.execute(req, current_version_getter=lambda: 1)
    assert res.status == TaskStatus.FAILED
    assert "timed out" in (res.error or "")


# ---------------------------------------------------------------------------
# Phase 2.2: Post-execution stale-result validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_post_execution_stale_rejection():
    """
    Phase 2.2 - R4/R5/R7: A STATE_MODIFYING tool that executes but whose
    version advances during execution must return ToolExecutionResult with
    status=STALE, even if the operation itself succeeded.

    This is the "cancellation is not sufficient" correctness guarantee:
    even if asyncio.TimeoutError was avoided and the tool completed, the
    result must be rejected because the state it was based on is no longer valid.
    """
    registry = ToolRegistry()

    async def book_seat(seat_id: str):
        # Simulate a slow, non-cancellable operation that actually succeeds.
        # Even though it "completes" normally, its result must be rejected
        # because the state version advanced during execution.
        await asyncio.sleep(0.05)
        return {"booked": seat_id}

    manifest = ToolManifest(
        name="book_seat",
        description="Book a seat",
        category=ToolCategory.STATE_MODIFYING,
        parameters_schema={"type": "object"},
        timeout_seconds=1.0,
    )
    registry.register_tool(manifest, book_seat)

    executor = ToolExecutor(registry)
    req = ToolCallRequest(
        call_id="call_post_stale",
        tool_name="book_seat",
        arguments={"seat_id": "42A"},
        origin_state_version=1,
    )

    # Simulate state_advance to version 2 AFTER execution starts but BEFORE it resolves.
    # The getter starts at 1 (matching origin), then changes to 2 during execution.
    call_count = 0

    def version_getter_that_advances() -> int:
        nonlocal call_count
        call_count += 1
        # return 1 on call #1 (pre-execution, passes pre-check),
        # return 2 on call #2 (post-execution, triggers stale check)
        return 1 if call_count == 1 else 2

    res = await executor.execute(req, current_version_getter=version_getter_that_advances)

    assert res.status == TaskStatus.STALE, (
        f"Expected STALE, got {res.status}"
    )
    assert res.origin_state_version == 1
    # The result data is None for stale results (R7c: discarded)
    assert res.data is None