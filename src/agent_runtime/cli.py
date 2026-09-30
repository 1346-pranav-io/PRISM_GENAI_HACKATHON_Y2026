"""Command-line Interface for the Interruptible Realtime Agent Runtime."""

import argparse
import asyncio
from .core.classifier import FastInterruptionClassifier
from .core.event_bus import EventBus
from .core.mock_llm import MockLLMProvider
from .core.runtime_engine import AgentRuntimeEngine
from .core.state_manager import StateManager
from .core.task_manager import TaskManager
from .core.tool_executor import ToolExecutor
from .core.tool_registry import ToolRegistry
from .core.trace_logger import TraceLogger
from .eval.benchmark import BenchmarkSuite
from .models.events import EventType, RuntimeEvent
from .models.tools import ToolCategory, ToolManifest


async def run_benchmark_cli() -> None:
    print("=" * 60)
    print(" Running Interruptible Realtime Agent Benchmark Suite")
    print("=" * 60)

    suite = BenchmarkSuite()
    results = await suite.run_all()

    for r in results:
        status_icon = "PASS" if r.passed else "FAIL"
        print(f"[{status_icon}] Scenario: {r.scenario_name}")
        print(f"       - Total Events: {r.metrics.total_events}")
        print(f"       - Final State Version: {r.metrics.final_state_version}")
        print(f"       - Monotonic State Versioning: {r.metrics.version_strictly_monotonic}")
        print(f"       - Avg Reflex Latency: {r.metrics.avg_reflex_latency_ms:.2f} ms")
        print(f"       - Cancelled Tasks: {r.metrics.total_tasks_cancelled}")
        print(f"       - Stale Task Rejections: {r.metrics.total_tasks_rejected_stale}")
        print("-" * 60)

    all_passed = all(r.passed for r in results)
    print(f"\nFinal Result: {'ALL BENCHMARKS PASSED' if all_passed else 'SOME BENCHMARKS FAILED'}\n")


async def run_interactive_cli() -> None:
    print("=" * 60)
    print(" Interruptible Realtime Agent CLI")
    print(" Type your messages below. Try interrupting with 'stop' or 'No wait, change destination to X'.")
    print(" Type 'exit' or 'quit' to end the session.")
    print("=" * 60)

    event_bus = EventBus()
    state_manager = StateManager()
    task_manager = TaskManager()
    classifier = FastInterruptionClassifier()
    tool_registry = ToolRegistry()
    tool_executor = ToolExecutor(tool_registry)
    llm_provider = MockLLMProvider(latency_seconds=0.2)
    trace_logger = TraceLogger()

    async def mock_flight_search(query: str):
        await asyncio.sleep(0.5)
        return [{"flight": "AI101", "price": 450}]

    tool_registry.register_tool(
        ToolManifest(
            name="search_flights",
            description="Search flights",
            category=ToolCategory.READ_ONLY,
            parameters_schema={"type": "object"},
        ),
        mock_flight_search,
    )

    engine = AgentRuntimeEngine(
        event_bus=event_bus,
        state_manager=state_manager,
        task_manager=task_manager,
        classifier=classifier,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        llm_provider=llm_provider,
        trace_logger=trace_logger,
    )

    session_id = "cli_session"
    await engine.init_session(session_id)

    async def handle_outbound(evt: RuntimeEvent):
        if evt.event_type == EventType.FAST_ACK:
            print(f"\n⚡ [FAST ACK] {evt.payload.get('text')} (State v{evt.state_version})")
        elif evt.event_type == EventType.AGENT_FINAL_RESPONSE:
            print(f"\n🤖 [AGENT] {evt.payload.get('text')} (State v{evt.state_version})")
        elif evt.event_type == EventType.TASK_CANCELLED:
            print(f"\n🛑 [CANCEL] Task(s) cancelled: {evt.payload.get('cancelled_task_ids')} (State v{evt.state_version})")
        elif evt.event_type == EventType.TASK_REJECTED_STALE:
            print(f"\n⚠️  [STALE REJECT] {evt.payload.get('tool_name')} rejected: {evt.payload.get('error')}")

    event_bus.subscribe_all(handle_outbound)

    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, input, "\nYou > ")
            if not line:
                continue
            if line.strip().lower() in ("exit", "quit"):
                break

            state = await state_manager.get_state(session_id)
            await event_bus.publish(
                RuntimeEvent(
                    session_id=session_id,
                    event_type=EventType.USER_TEXT,
                    state_version=state.state_version,
                    payload={"text": line},
                )
            )
            # Short yield for reflex path
            await asyncio.sleep(0.05)
        except (KeyboardInterrupt, EOFError):
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Interruptible Realtime Agent Runtime CLI")
    parser.add_argument("--benchmark", action="store_true", help="Run benchmark suite")
    args = parser.parse_args()

    if args.benchmark:
        asyncio.run(run_benchmark_cli())
    else:
        asyncio.run(run_interactive_cli())


if __name__ == "__main__":
    main()
