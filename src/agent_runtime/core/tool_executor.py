"""Tool Executor with idempotency gating, timeout supervision, and stale detection."""

import asyncio
import time
from typing import Any, Callable
from ..interfaces.tool_executor import IToolExecutor
from ..interfaces.tool_registry import IToolRegistry
from ..models.tasks import TaskStatus
from ..models.tools import ToolCallRequest, ToolCategory, ToolExecutionResult


class ToolExecutor(IToolExecutor):
    """Executes registered tools with safety checks and stale detection."""

    def __init__(self, registry: IToolRegistry) -> None:
        self._registry = registry

    async def _resolve_version(self, getter: Any) -> int:
        """
        Resolve current state version from a Callable[[], int].

        The getter always returns int synchronously (StateRef.__call__ now uses
        the lock-free StateManager.get_current_version).  inspect.isawaitable
        guard is kept for robustness so legacy sync lambdas still work too.
        """
        import inspect

        result = getter()

        if inspect.isawaitable(result):
            # Defensive: handle awaitable getters (e.g. if StateRef ever
            # returns a Future again).  In normal operation this branch is
            # never hit.
            return await result

        return result

    async def execute(
        self,
        request: ToolCallRequest,
        current_version_getter: Callable[[], int],
    ) -> ToolExecutionResult:
        """Execute a tool call with idempotency check, cancellation monitoring, and stale verification."""
        manifest = self._registry.get_manifest(request.tool_name)
        executor_fn = self._registry.get_executor(request.tool_name)

        if not manifest or not executor_fn:
            return ToolExecutionResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status=TaskStatus.FAILED,
                error=f"Tool '{request.tool_name}' not registered.",
                origin_state_version=request.origin_state_version,
            )

        start_time = time.perf_counter()

        # Pre-execution stale check
        current_ver = await self._resolve_version(current_version_getter)
        if current_ver != request.origin_state_version and manifest.category == ToolCategory.STATE_MODIFYING:
            return ToolExecutionResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status=TaskStatus.STALE,
                error=f"Pre-execution rejection: state version advanced from {request.origin_state_version} to {current_ver}",
                origin_state_version=request.origin_state_version,
            )

        try:
            coro = executor_fn(**request.arguments)
            result_data = await asyncio.wait_for(coro, timeout=manifest.timeout_seconds)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Post-execution stale check
            latest_ver = await self._resolve_version(current_version_getter)
            is_stale = (latest_ver != request.origin_state_version) and (manifest.category == ToolCategory.STATE_MODIFYING)
            status = TaskStatus.STALE if is_stale else TaskStatus.COMPLETED
            # R7c: stale results must not carry data to prevent accidental use
            result_data_to_return = None if is_stale else result_data

            return ToolExecutionResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status=status,
                data=result_data_to_return,
                execution_duration_ms=duration_ms,
                origin_state_version=request.origin_state_version,
            )

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolExecutionResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status=TaskStatus.FAILED,
                execution_duration_ms=duration_ms,
                error=f"Tool '{request.tool_name}' timed out after {manifest.timeout_seconds}s.",
                origin_state_version=request.origin_state_version,
            )
        except asyncio.CancelledError:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolExecutionResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status=TaskStatus.CANCELLED,
                execution_duration_ms=duration_ms,
                error="Tool execution cancelled.",
                origin_state_version=request.origin_state_version,
            )
        except Exception as ex:
            duration_ms = (time.perf_counter() - start_time) * 1000
            return ToolExecutionResult(
                call_id=request.call_id,
                tool_name=request.tool_name,
                status=TaskStatus.FAILED,
                execution_duration_ms=duration_ms,
                error=str(ex),
                origin_state_version=request.origin_state_version,
            )

