# Architecture

## Overview

The Interruptible Realtime Agent Runtime is a versioned, event-driven async agent runtime. It processes user input (text, interruptions) in real-time through a dual-path pipeline: a fast path for low-latency acknowledgement and interruption handling, and a slow path for full LLM reasoning and tool execution.

The runtime is the central owner of all session state. The LLM is an unprivileged reasoning component that produces structured proposals; every proposal is validated by the runtime before mutating state.

---

## System Topology




External Client
     |
     v
FastAPI / WebSocket
  app.py + ws_handler.py
     |
     v
  Event Bus (asyncio.Queue)
     |
  +---+---+--------
  |               |
  v               v
Fast Path       Slow Path
(sync/await)    (asyncio tasks)
- FastAck       - LLM reasoning
- Interruption   - Tool execution
  Classification - Response
- Task cancel       synthesis
     |               |
     +-------+-------+
             |
             v
    RuntimeEngine (Orchestrator)
             |
  +---------+---------+--------+
  |         |         |        |
  v         v         v        v
State     Task     Tool      Trace
Manager   Manager  Registry  Logger

---

## Components

### Event Bus (core/event_bus.py)

Central pub/sub hub backed by asyncio.Queue. All runtime components publish and subscribe through it:
- publish(event) - enqueue one RuntimeEvent
- subscribe(event_type, subscriber_id, handler) - register a handler for one type
- subscribe_all(subscriber_id, handler) - register a handler for ALL event types
- unsubscribe_all(subscriber_id) - remove all subscriptions for an ID

The bus is shared by the fast path, slow path, and WebSocket handler.

### RuntimeEngine (core/runtime_engine.py)

The continuity orchestrator. Responsible for:

1. **Session initialization** - creates SessionState in StateManager
2. **Fast path** - runs synchronously from the event loop:
   - USER_TEXT / USER_INTERRUPTION received from bus
   - FastInterruptionClassifier.classify() -> ClassificationResult
   - FAST_ACK published immediately (sub-100ms goal)
   - State delta staged in StateManager
   - Affected tasks cancelled via TaskManager
3. **Slow path** - launched as a background asyncio.Task:
   - ILLMProvider.plan_and_reason() -> LLMPlan
   - ToolExecutor.execute() for each proposed tool call
   - Stale-result validation via TaskManager.reject_if_stale()
   - AGENT_FINAL_RESPONSE published to bus

### StateManager (core/state_manager.py)

Thread-safe, versioned session state store. Key operations:
- init_session(session_id) - create new SessionState
- get_state(session_id) - return current state snapshot
- apply_delta(session_id, slot_deltas, intent) - stage and commit state change, increment version
- get_current_version(session_id) - return version without snapshot
- is_valid_version(session_id, version) - check if version is still current

Concurrency: asyncio.Lock per session.

### TaskManager (core/task_manager.py)

Supervises lifecycle of all background tasks. Key operations:
- spawn_task(session_id, task_id, coro) - register a new task
- cancel_task(task_id, reason) - send CancelledError to a task
- cancel_affected_tasks(session_id, reason) - cancel all active tasks for a session
- reject_if_stale(task_record) - validate task result against current state version
- get_task(task_id) / get_session_tasks(session_id) - inspection

The origin_issue field on every task is used for stale-result validation.

### ToolRegistry (core/tool_registry.py)

Dynamic registry mapping tool_name -> (ToolManifest, executor_fn).
- register_tool(manifest, executor_fn)
- get_manifest(name) / get_manifests() / list_tool_names()

### ToolExecutor (core/tool_executor.py)

Executes tool calls, wraps results in ToolExecutionResult, handles cancellation.
- execute(request: ToolCallRequest)
- execute_many(requests) - run multiple tools concurrently

### Classifier (core/classifier.py)

Deterministic interruption classifier for the fast path.
- classify(utterance, session_state) -> ClassificationResult
- InterruptionCategory: CORRECTION, INTERRUPTION, BACKCHANNEL, NEW_QUERY, CANCEL, UNKNOWN

Invariant: BACKCHANNEL never triggers task cancellation or state mutation.

### TraceLogger (core/trace_logger.py)

In-memory immutable event log per session. Used for debugging, audit, and evaluation.
- log(event)
- get_session_trace(session_id) -> Trace
- Trace.issue exposes final_issue for evaluation assertions

## Interruption Handling Flow

1. User sends interruption text
2. Fast path (event loop):
   - FastInterruptionClassifier.classify()
   - BACKCHANNEL: ignore
   - CANCEL: cancel all active tasks
   - CORRECTION: stage delta, increment version, cancel affected tasks
   - FAST_ACK published immediately
3. Slow path (background):
   - LLM plan in progress...
   - Task completes
   - Check origin_state_issue vs current version
   - If stale: discard result
   - Else: apply result and publish AGENT_FINAL_RESPONSE

## Evaluation (evaluation/)

- runner.py - loads scenarios/*.json, drives events against fresh runtime, returns pass/fail
- metrics.py - computes TraceEvaluationMetrics from a Trace
- replayer.py - TraceReplayer for step-by-step trace reconstruction
- benchmark.py - BenchmarkSuite for performance benchmarks

## Server Transport (server/)

FastAPI app.py exposes:
- GET /api/v1/health - basic health check
- GET /api/v1/health/ready - readiness probe
- POST /api/v1/sessions/{id}/init - initialize a session
- POST /api/v1/sessions/{id}/message - send a user message
- GET /api/v1/sessions/{id}/state - get current session state
- GET /api/v1/sessions/{id}/trace - get session trace events
- GET /api/v1/debug/sessions - list active sessions
- GET /api/v1/debug/tasks/{id} - list session tasks
- POST /api/v1/scenarios/{name}/run - run a named scenario
- WS /ws/{session_id} - bidirectional WebSocket transport

The WebSocket handler bridges each WebSocket connection to a runtime session, publishing inbound messages to the event bus and forwarding runtime events back to the client.

## State Versioning Rules

1. state_version is strictly monotonic; v_next = v_current + 1
2. Every async task records its origin_state_version at creation
3. When a task completes, reject_if_stale() checks:
   IF task.origin_state_version < current_state_version:
       task.status = STALE; result is DISCARDED
4. A state-version change triggers cancel_affected_issues for tasks whose inputs were invalidated.

## Extension Points

| Interface | Location | Purpose | Swap With |
|-----------|----------|---------|-----------|
| ILLMProvider | interfaces/llm_provider.py | LLM reasoning | OpenAI, Gemini, Claude |
| IInterruptionClassifier | interfaces/classifier.py | Utterance classification | Small LM, rule engine |
| IEventBus | interfaces/event_bus.py | Pub/sub | Redis, Kafka |
| ITraceLogger | interfaces/trace_logger.py | Audit log | Database, cloud log |

