"""Scripted demo + verification client for a running server (local or hosted).

    python scripts/demo_client.py http://127.0.0.1:8000
    python scripts/demo_client.py https://<your-app>.onrender.com

Demo 1: one session sends "Book a flight to Mumbai" and, while it is still
processing, "Actually make it New York". Demo 2: runs that again alongside a
second session (Delhi, then Tokyo) at the same time. Every invariant is checked;
the exit code is non-zero if any check fails.
"""
import asyncio
import json
import sys
import time
import urllib.request
import uuid

import websockets

CORRECTION_DELAY_S = 0.03  # sent while the Mumbai turn is still reasoning / searching
SETTLE_S = 1.5


class Checks:
    def __init__(self):
        self.failures = []

    def expect(self, ok, label):
        print(f"    [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok:
            self.failures.append(label)


def _ws_url(base, session_id):
    scheme = "wss" if base.startswith("https") else "ws"
    return f"{scheme}://{base.split('://', 1)[1].rstrip('/')}/ws/{session_id}"


def _get(base, path):
    with urllib.request.urlopen(base.rstrip("/") + "/api/v1" + path, timeout=15) as r:
        return json.loads(r.read())


async def _collect(ws, seconds):
    events = []
    deadline = time.monotonic() + seconds
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            events.append(json.loads(await asyncio.wait_for(ws.recv(), remaining)))
        except asyncio.TimeoutError:
            break
    return events


def _flights_to(final):
    for r in final.get("tool_results", []):
        if r["tool_name"] == "search_flights" and r["status"] == "COMPLETED":
            return {f.get("to") for f in r["data"] or []}
    return set()


def _print_timeline(events):
    for e in events:
        extra = e.get("text", "") or e.get("cancelled_task_ids", "") or e.get("tool_name", "") or e.get("error", "")
        print(f"      v{e['state_version']:<2} {e['event_type']:<22} {str(extra)[:90]}")


async def correction_session(base, sid, checks):
    async with websockets.connect(_ws_url(base, sid), open_timeout=20) as ws:
        await ws.send(json.dumps({"text": "Book a flight to Mumbai"}))
        await asyncio.sleep(CORRECTION_DELAY_S)
        await ws.send(json.dumps({"text": "Actually make it New York"}))
        events = await _collect(ws, SETTLE_S)
    print(f"  session {sid}:")
    _print_timeline(events)

    corr = next((i for i, e in enumerate(events) if e["event_type"] == "USER_TEXT" and "New York" in e.get("text", "")), None)
    finals = [e for e in events if e["event_type"] == "AGENT_FINAL_RESPONSE"]
    finals_after = [e for e in events[corr:] if e["event_type"] == "AGENT_FINAL_RESPONSE"] if corr is not None else []
    state = _get(base, f"/sessions/{sid}/state")
    tasks = _get(base, f"/debug/tasks/{sid}")["tasks"]

    checks.expect(all(e["session_id"] == sid for e in events), f"{sid}: only its own events")
    checks.expect(len({json.dumps(e, sort_keys=True) for e in events}) == len(events), f"{sid}: no duplicate events")
    checks.expect(any(e["event_type"] == "TASK_CANCELLED" for e in events), f"{sid}: Mumbai work cancelled")
    checks.expect(any(t["status"] in ("CANCELLED", "STALE") and t["task_type"] == "REASONING" for t in tasks),
                  f"{sid}: old reasoning task CANCELLED/STALE")
    checks.expect(len(finals) == 1 and len(finals_after) == 1, f"{sid}: exactly one final response, after the correction")
    final = finals[-1] if finals else {}
    checks.expect(final.get("state_version") == state["state_version"], f"{sid}: final is at the current state version (v{state['state_version']})")
    checks.expect(state["slots"].get("destination", {}).get("value") == "New York", f"{sid}: destination slot is New York")
    destinations = _flights_to(final)
    checks.expect(destinations == {"New York"}, f"{sid}: synthesized from New York flights only (got {sorted(destinations)})")
    checks.expect("Mumbai" not in destinations, f"{sid}: no Mumbai-destination result in the final response")


async def second_session(base, sid, checks):
    async with websockets.connect(_ws_url(base, sid), open_timeout=20) as ws:
        await ws.send(json.dumps({"text": "Book a flight to Delhi"}))
        first = await _collect(ws, SETTLE_S)
        await ws.send(json.dumps({"text": "Search flights to Tokyo"}))
        second = await _collect(ws, SETTLE_S)
    print(f"  session {sid}:")
    _print_timeline(first + second)
    events = first + second
    f1 = [e for e in first if e["event_type"] == "AGENT_FINAL_RESPONSE"]
    f2 = [e for e in second if e["event_type"] == "AGENT_FINAL_RESPONSE"]
    checks.expect(all(e["session_id"] == sid for e in events), f"{sid}: only its own events")
    checks.expect(len({json.dumps(e, sort_keys=True) for e in events}) == len(events), f"{sid}: no duplicate events")
    checks.expect(len(f1) == 1 and _flights_to(f1[0]) == {"Delhi"}, f"{sid}: Delhi request answered with Delhi flights")
    checks.expect(len(f2) == 1 and _flights_to(f2[0]) == {"Tokyo"}, f"{sid}: Tokyo request answered with Tokyo flights")
    checks.expect("New York" not in json.dumps(events) and "Mumbai" not in json.dumps(f2), f"{sid}: no data from the other session")


async def main(base):
    checks = Checks()
    run = uuid.uuid4().hex[:6]
    print(f"Target: {base}")
    health, ready = _get(base, "/health"), _get(base, "/health/ready")
    print(f"  health={health} ready={ready}")
    checks.expect(health.get("status") == "ok" and ready.get("ready") is True, "REST health + readiness")

    print("\nDEMO 1 - correction while processing (Mumbai -> New York)")
    await correction_session(base, f"demo1_{run}", checks)

    print("\nDEMO 2 - two simultaneous sessions")
    await asyncio.gather(
        correction_session(base, f"demoA_{run}", checks),
        second_session(base, f"demoB_{run}", checks),
    )

    print(f"\nRESULT: {'ALL CHECKS PASSED' if not checks.failures else f'{len(checks.failures)} CHECK(S) FAILED'}")
    for f in checks.failures:
        print(f"  - {f}")
    return 0 if not checks.failures else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")))
