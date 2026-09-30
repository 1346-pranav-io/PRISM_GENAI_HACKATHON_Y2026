"""Run the JSON scenario fixtures: ``python -m evaluation.runner [scenario ...]``.

Delegates to the canonical runner in ``agent_runtime.eval.runner``.
"""
import asyncio
import sys

from . import list_scenarios, run_all_scenarios, run_scenario

__all__ = ["list_scenarios", "run_all_scenarios", "run_scenario", "main"]


async def _run(names):
    if not names:
        return await run_all_scenarios()
    return [await run_scenario(name) for name in names]


def main(argv=None) -> int:
    results = asyncio.run(_run(list(sys.argv[1:] if argv is None else argv)))
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['scenario']}")
        for c in r.get("checks", []):
            mark = "ok " if c["passed"] else "BAD"
            print(f"    {mark} {c['check']}: expected={c['expected']} actual={c['actual']}")
        if "error" in r:
            print(f"    error: {r['error']}")
    return 0 if results and all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
