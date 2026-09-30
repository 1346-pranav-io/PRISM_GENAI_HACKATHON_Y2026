# Interruptible Real-Time Agent Runtime

An event-driven, version-aware `asyncio` runtime for conversational agents where interruptions, corrections and cancellations come first. The runtime owns session state, task lifecycles and event ordering. The LLM is an unprivileged planner. It proposes plans and tool calls, and the runtime validates them before any state changes.

Production deployment is covered in [DEPLOY.md](DEPLOY.md).

## Architecture

```
client (REST / WebSocket)
        |
        v
    EVENT BUS ------------------------------------------------+
        |                                                      |
        v                                                      v
  FAST PATH                                         DELIBERATE PATH
  classify utterance                                REASONING task -> LLM plan
  -> FAST_ACK                                       -> tool tasks (concurrent)
  -> state delta (version++)                        -> wait for tool results
  -> cancel affected tasks                          -> staleness check
        |                                           -> response synthesis
        |                                           -> AGENT_FINAL_RESPONSE
        v                                                      |
  STATE MANAGER (monotonic state_version) <--------------------+
  TASK MANAGER  (origin_state_version, cancellation)
  TOOL EXECUTOR (registered tools)  ->  TRACE LOGGER (per-session trace)
```

Interruption categories used by the classifier:

| Category | Example | Effect |
|---|---|---|
| `BACKCHANNEL` | "uh-huh", "okay" | Acknowledged. No state change and no cancellation. |
| `CANCEL` | "stop" | All active tasks for the session are cancelled. |
| `CORRECTION` | "No wait, change destination to X", "Actually make it X", "No, X" | Slot updated, version bumped, in-flight work cancelled, replan. |
| `NEW_QUERY` | anything else (default) | If prior work or context exists, active tasks are cancelled, prior slots and intent are cleared, and the version is bumped. Then a new plan starts. |

Staleness rules:
- `state_version` only ever increases. Every task records its `origin_state_version`.
- When a result arrives from an older version, the runtime discards it and emits `TASK_REJECTED_STALE`. This covers tool results of any category and reasoning replies.
- Superseded turns never produce a final response.

## Installation

Requires Python 3.11+.

```bash
pip install -r requirements.txt
# for tests:
pip install -e ".[dev]"        # or: pip install pytest pytest-asyncio httpx
```

## Environment variables

| Variable | Purpose |
|---|---|
| `PORT` | Listen port for deployment start commands (see DEPLOY.md). The app does not read it; pass it to uvicorn with `--port`. |
| `AGENT_LLM_LATENCY_SECONDS` | Simulated reasoning latency of the default mock LLM (default `0.05`). Raise it (e.g. `2`) for hand-typed interruption demos. |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL` | Used by `OpenAILLMProvider`. **The default server does not use these.** |
| `GEMINI_API_KEY` | Used by `GeminiLiveProvider`. **The default server does not use this.** |

The server is wired to the deterministic `MockLLMProvider`, so it needs no API key. The OpenAI and Gemini providers exist in `src/agent_runtime/core/` and fall back to heuristics when a call fails. To use one, change the provider in `src/agent_runtime/server/app.py`.

## Running locally

From the repo root:

```bash
python -m uvicorn src.agent_runtime.server.app:app --host 127.0.0.1 --port 8000
```

The server registers two tools, `search_flights` and `get_weather`. `book_flight` and the calendar tools exist but are only registered in the scenario runner.

## REST API (`/api/v1`)

```bash
BASE=http://127.0.0.1:8000/api/v1
curl $BASE/health
curl $BASE/health/ready
curl -X POST $BASE/sessions/s1/init
curl -X POST $BASE/sessions/s1/message \
  -H "Content-Type: application/json" \
  -d '{"session_id": "s1", "text": "Book a flight to Mumbai"}'
curl $BASE/sessions/s1/state        # version, intent, slots
curl $BASE/sessions/s1/trace        # full event trace
curl $BASE/debug/sessions           # known session ids
curl $BASE/debug/tasks/s1           # task records for session s1
curl -X POST $BASE/scenarios/explicit_correction/run
```

`/message` does not wait for the final response. It returns `{"session_id", "state_version", "status": "queued"}`. Read the result from `/trace`, or subscribe over WebSocket.

## WebSocket (`/ws/{session_id}`)

The client sends `{"text": "..."}` or `{"type": "interrupt", "text": "..."}`. The server streams JSON events. Each event has `session_id`, `event_type`, `state_version` and `timestamp`, plus the fields from its payload.

```python
import asyncio, json, websockets

async def main():
    async with websockets.connect("ws://127.0.0.1:8000/ws/demo") as ws:
        await ws.send(json.dumps({"text": "Book a flight to Mumbai"}))
        await asyncio.sleep(0.02)
        await ws.send(json.dumps({"text": "Actually make it New York"}))
        while True:
            evt = json.loads(await ws.recv())
            print(evt["state_version"], evt["event_type"], evt.get("text", ""))
            if evt["event_type"] == "AGENT_FINAL_RESPONSE":
                break

asyncio.run(main())
```

## Interruption walkthrough

The user says "Book a flight to Mumbai", then "Actually make it New York" while the first turn is still running. Actual WebSocket events from a live run (`scripts/demo_client.py`):

```
v1  USER_TEXT             Book a flight to Mumbai
v1  FAST_ACK              Checking that now...
v1  USER_TEXT             Actually make it New York
v1  FAST_ACK              Understood, updating...
v2  TASK_CANCELLED        ['reason_...']          <- Mumbai reasoning cancelled; correction bumped v1 -> v2
v3  TASK_SCHEDULED        search_flights          <- New York replan set destination (v3) and scheduled the search
v3  AGENT_FINAL_RESPONSE  Searching for flights matching your request...
                          search_flights: [{"id": "UA830", "from": "London", "to": "New York", ...}, ...]
```

The final payload also carries structured `tool_results`. The Mumbai turn never emits `AGENT_FINAL_RESPONSE`. If the correction arrives after a Mumbai tool has already started, that tool is cancelled; if it cannot be cancelled and returns late, its result is discarded with `TASK_REJECTED_STALE`. If the Mumbai turn had already finished before the correction arrived, its reply was legitimately delivered and the correction produces a second, New York reply at the newer version.

### Scripted demo / verification

```bash
python scripts/demo_client.py http://127.0.0.1:8000          # or https://<your-host>
```

Runs the correction demo, then the correction demo alongside a second concurrent session (Delhi, then Tokyo), and checks: cancellation, one final response at the current version, New York-only results, no cross-session events or duplicates. Exit code 0 means every check passed.

For a hand-typed demo, start the server with `AGENT_LLM_LATENCY_SECONDS=2` so there is time to type the correction while the first request is still reasoning.

## Tool execution and response synthesis

The deliberate path runs the LLM plan's tool calls as tasks. Each task carries its origin version. The runtime waits for those tasks, then checks staleness. A turn that used tools returns this final payload:

```json
{"text": "...", "tool_results": [{"task_id": "...", "tool_name": "...", "status": "...", "data": {}, "error": null}]}
```

`text` comes from `ILLMProvider.synthesize_response`. It has a deterministic default implementation, and providers may override it. A turn without tools returns `{"text": "..."}`.

## Concurrency and session isolation

REST and WebSocket share one in-memory runtime: the event bus, state manager, task manager and trace logger. Each session has its own state, version counter, tasks and trace. A WebSocket connection only receives events for its own `session_id`. Many sessions can run concurrently in a single event loop.

## Tests

```bash
python -W error::RuntimeWarning -m pytest tests/ -q
```

## Evaluation scenarios

```bash
python -m evaluation.runner
```

This replays the JSON fixtures in `evaluation/scenarios/`: `backchannel_flood`, `cancellation_cascade`, `explicit_correction` and `rapid_barge_in`. It runs deterministic assertions on state versions, cancellations and stale discards.

## Benchmark and interactive CLI

Git Bash / Linux / macOS:

```bash
PYTHONPATH=src python -m agent_runtime.cli --benchmark
PYTHONPATH=src python -m agent_runtime.cli            # interactive
```

PowerShell:

```powershell
$env:PYTHONPATH="src"; python -m agent_runtime.cli --benchmark
```

## Known limitations

- **In-memory, single process.** No persistence. All state and traces are lost on restart. Run exactly one worker. See [DEPLOY.md](DEPLOY.md).
- **No authentication** on the REST or WebSocket endpoints.
- **Mock LLM by default.** Real providers exist but are not wired into the server.
- **Rule-based classifier.** Anything that is not a backchannel, cancel or correction pattern is treated as `NEW_QUERY`. Follow-up questions therefore reset prior slots and context.
- Only `search_flights` and `get_weather` are exposed by the server.

## Deployment

See [DEPLOY.md](DEPLOY.md).

## 🎥 Demo Video

Watch the LockedIn Demo:https://drive.google.com/file/d/1likWGe_a4Fw9qQJ4meAYZGQ_SS8k0ErZ/view?usp=drive_link

