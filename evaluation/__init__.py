"""Evaluation entry point: JSON scenario fixtures plus re-exports of the harness.

The implementation lives in ``agent_runtime.eval``; this package only owns the
fixtures in ``evaluation/scenarios/``. It uses the installed ``agent_runtime``
package when available, otherwise the in-repo ``src.agent_runtime`` layout.
"""
try:
    from agent_runtime import eval as _harness
except ModuleNotFoundError as exc:
    if exc.name != "agent_runtime":
        raise
    from src.agent_runtime import eval as _harness

BenchmarkSuite = _harness.BenchmarkSuite
BenchmarkResult = _harness.BenchmarkResult
MetricsCalculator = _harness.MetricsCalculator
TraceEvaluationMetrics = _harness.TraceEvaluationMetrics
TraceReplayer = _harness.TraceReplayer
TraceReplayResult = _harness.TraceReplayResult
run_scenario = _harness.run_scenario
run_all_scenarios = _harness.run_all_scenarios
list_scenarios = _harness.list_scenarios

__all__ = [
    "BenchmarkSuite", "BenchmarkResult",
    "MetricsCalculator", "TraceEvaluationMetrics",
    "TraceReplayer", "TraceReplayResult",
    "run_scenario", "run_all_scenarios", "list_scenarios",
]
