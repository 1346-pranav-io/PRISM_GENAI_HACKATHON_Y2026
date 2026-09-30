"""Benchmark runner executing standard evaluation scenarios."""

import asyncio
from typing import Any, Dict, List
from pydantic import BaseModel, Field
from .metrics import MetricsCalculator, TraceEvaluationMetrics
from ..core.classifier import FastInterruptionClassifier
from ..core.event_bus import EventBus
from ..core.mock_llm import MockLLMProvider
from ..core.runtime_engine import AgentRuntimeEngine
from ..core.state_manager import StateManager
from ..core.task_manager import TaskManager
from ..core.tool_executor import ToolExecutor
from ..core.tool_registry import ToolRegistry
from ..core.trace_logger import TraceLogger
from ..models.events import EventType, RuntimeEvent
from ..models.tools import ToolCategory, ToolManifest


class BenchmarkResult(BaseModel):
    scenario_name: str
    passed: bool
    metrics: TraceEvaluationMetrics
    details: Dict[str, Any] = Field(default_factory=dict)


class BenchmarkSuite:
    """Automated benchmark testbed for latency, cancellation, and state consistency."""

    def __init__(self) -> None:
        self.results: List[BenchmarkResult] = []

    async def run_all(self) -> List[BenchmarkResult]:
        self.results = []
        self.results.append(await self.run_rapid_barge_in())
        self.results.append(await self.run_backchannel_flood())
        self.results.append(await self.run_cancellation_cascade())
        return self.results

    async def _create_runtime(self) -> Dict[str, Any]:
        bus = EventBus()
        sm = StateManager()
        tm = TaskManager()
        clf = FastInterruptionClassifier()
        reg = ToolRegistry()
        tex = ToolExecutor(reg)
        llm = MockLLMProvider()
        trace = TraceLogger()

        async def mock_search(query: str):
            await asyncio.sleep(0.04)
            return [{"id": "flight1"}]

        reg.register_tool(
            ToolManifest(
                name="search_flights",
                description="Search flights",
                category=ToolCategory.READ_ONLY,
                parameters_schema={"type": "object"},
            ),
            mock_search,
        )

        engine = AgentRuntimeEngine(
            event_bus=bus,
            state_manager=sm,
            task_manager=tm,
            classifier=clf,
            tool_registry=reg,
            tool_executor=tex,
            llm_provider=llm,
            trace_logger=trace,
        )

        return {"engine": engine, "bus": bus, "sm": sm, "tm": tm, "trace": trace}

    async def run_rapid_barge_in(self) -> BenchmarkResult:
        ctx = await self._create_runtime()
        session_id = "bench_barge_in"
        await ctx["engine"].init_session(session_id)

        await ctx["bus"].publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.USER_TEXT,
                state_version=ctx["sm"].get_current_version(session_id),
                payload={"text": "search flights to London"},
            )
        )
        await asyncio.sleep(0.01)

        await ctx["bus"].publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.USER_TEXT,
                state_version=ctx["sm"].get_current_version(session_id),
                payload={"text": "No wait, change destination to Tokyo"},
            )
        )
        await asyncio.sleep(0.12)

        session_trace = await ctx["trace"].get_session_trace(session_id)
        metrics = MetricsCalculator.evaluate_trace(session_trace)

        passed = (
            metrics.version_strictly_monotonic
            and metrics.final_state_version >= 2
            and (metrics.avg_reflex_latency_ms < 50.0)
        )

        return BenchmarkResult(
            scenario_name="rapid_barge_in",
            passed=passed,
            metrics=metrics,
            details={"avg_reflex_latency_ms": metrics.avg_reflex_latency_ms},
        )

    async def run_backchannel_flood(self) -> BenchmarkResult:
        ctx = await self._create_runtime()
        session_id = "bench_backchannel"
        await ctx["engine"].init_session(session_id)

        await ctx["bus"].publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.USER_TEXT,
                state_version=ctx["sm"].get_current_version(session_id),
                payload={"text": "search flights to Paris"},
            )
        )

        for _ in range(3):
            await asyncio.sleep(0.01)
            await ctx["bus"].publish(
                RuntimeEvent(
                    session_id=session_id,
                    event_type=EventType.USER_TEXT,
                    state_version=ctx["sm"].get_current_version(session_id),
                    payload={"text": "uh-huh"},
                )
            )

        await asyncio.sleep(0.1)

        session_trace = await ctx["trace"].get_session_trace(session_id)
        metrics = MetricsCalculator.evaluate_trace(session_trace)

        passed = metrics.total_tasks_cancelled == 0

        return BenchmarkResult(
            scenario_name="backchannel_flood",
            passed=passed,
            metrics=metrics,
            details={"cancelled_tasks": metrics.total_tasks_cancelled},
        )

    async def run_cancellation_cascade(self) -> BenchmarkResult:
        ctx = await self._create_runtime()
        session_id = "bench_cancel_cascade"
        await ctx["engine"].init_session(session_id)

        await ctx["bus"].publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.USER_TEXT,
                state_version=ctx["sm"].get_current_version(session_id),
                payload={"text": "search flights to Rome"},
            )
        )
        await asyncio.sleep(0.005)

        await ctx["bus"].publish(
            RuntimeEvent(
                session_id=session_id,
                event_type=EventType.USER_TEXT,
                state_version=ctx["sm"].get_current_version(session_id),
                payload={"text": "stop!"},
            )
        )
        await asyncio.sleep(0.05)

        session_trace = await ctx["trace"].get_session_trace(session_id)
        metrics = MetricsCalculator.evaluate_trace(session_trace)

        passed = metrics.version_strictly_monotonic and metrics.final_state_version >= 2

        return BenchmarkResult(
            scenario_name="cancellation_cascade",
            passed=passed,
            metrics=metrics,
            details={"final_state_version": metrics.final_state_version},
        )
