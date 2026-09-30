# Agent Runtime Specification: Interruptible Real-Time Agents

## 1. System Overview & Core Philosophy

The **Interruptible Real-Time Agents Runtime** is an event-driven, version-aware asynchronous agent runtime designed for low-latency voice/text/multimodal interactions where user interruptions, corrections, and mid-stream goal shifts are first-class primitives.

Unlike naive `listen -> think -> act -> respond` agent loops, this architecture continuously runs concurrent loops across a dual-path pipeline:
- **Fast Path:** Handles immediate event ingestion, interruption acknowledgement, cancellation propagation, state delta staging, and fast feedback without waiting for slow reasoning.
- **Slow Path (Async/Concurrent):** Handles LLM intent extraction, reasoning/planning, tool selection, dynamic tool execution, and response synthesis.

The runtime owns all session state, task lifecycles, and event ordering. The LLM is an unprivileged reasoning component producing structured proposals that are validated by the runtime before mutating state.

---

## 2. Component Topology & Data Flow

```
                      +-----------------------------------+
                      |         EXTERNAL CLIENT           |
                      |  (WebSocket / WebRTC / Audio-In)  |
                      +-----------------+-----------------+
                                        | (Validated Inbound Events)
                                        v
                      +-----------------------------------+
                      |      PROTOCOL & INGESTION         |
                      |     (ProtocolValidator)           |
                      +-----------------+-----------------+
                                        |
                                        v
                             +--------------------+
                             |      EVENT BUS     |
                             |  (asyncio.Queue)   |
                             +----+----------+----+
                                  |          |
               +------------------+          +------------------+
               | (Fast Path Priority)                           | (Asynchronous Background)
               v                                                v
    +-----------------------+                        +-----------------------+
    |       FAST PATH       |                        |       SLOW PATH       |
    | - Interruption Classif|                        | - LLM Reasoning & Plan|
    | - Fast-Ack Dispatch   |                        | - Tool Selection      |
    | - Cancel Affected Task|                        | - Dynamic Tool Exec   |
    | - State Delta Staging |                        | - Response Synthesis  |
    +-----------+-----------+                        +-----------+-----------+
                |                                                |
                \                       +------------------------/
                 \                      |
                  v                     v
               +-----------------------------------+
               |        CONTINUITY ENGINE          |
               |       (Orchestrator Core)         |
               +--------+--------+--------+--------+
                        |        |        |
        +---------------+        |        +---------------+
        v                        v                        v
+---------------+        +---------------+        +---------------+
| STATE MANAGER |        | TASK MANAGER  |        | TOOL REGISTRY |
| - State Version        | - Task Status |        | & EXECUTOR    |
| - Slots & Intent       | - Cancellation|        | - Idempotency |
| - Affected Task Eval   | - Async Tasks |        | - Dynamic Reg |
+---------------+        +---------------+        +---------------+
        |                        |                        |
        +----------------+-------+------------------------+
                         |
                         v
               +-------------------+
               |   TRACE LOGGER    |
               | (Replay / Audit)  |
---

## 3. Directory Structure

```
interruptible-realtime-agent/
├── AGENTS.md                    # Runtime specification and developer guidelines
├── ARCHITECTURE.md              # Complete architecture specification
├── pyproject.toml               # Python dependencies and build config
├── requirements.txt             # Locked requirements
├── README.md                    # Project overview & running instructions
├── src/
│   └── agent_runtime/
│       ├── __init__.py
│       ├── config.py            # Global runtime configuration
│       ├── models/              # Pydantic v2 schemas
│       │   ├── __init__.py
│       │   ├── events.py        # Inbound and Outbound event models
│       │   ├── state.py         # Session state, slots, version models
│       │   ├── tasks.py         # Task status, lifecycle, execution metadata
│       │   ├── tools.py         # Tool manifests, inputs, outputs, schemas
│       │   ├── classifier.py    # Interruption classification models
│       │   └── trace.py         # Structured trace log events
│       ├── interfaces/          # Abstract Base Classes (Protocols)
│       │   ├── __init__.py
│       │   ├── event_bus.py     # EventBus interface
│       │   ├── state_manager.py # StateManager interface
│       │   ├── task_manager.py  # TaskManager interface
│       │   ├── tool_registry.py # ToolRegistry interface
│       │   ├── tool_executor.py # ToolExecutor interface
│       │   ├── llm_provider.py  # LLMProvider interface
│       │   ├── classifier.py    # InterruptionClassifier interface
│       │   └── trace_logger.py  # TraceLogger interface
│       ├── core/                # Core implementation
│       │   ├── __init__.py
│       │   ├── event_bus.py     # High-performance in-memory async event bus
│       │   ├── state_manager.py # Thread-safe, versioned state store
│       │   ├── task_manager.py  # Task lifecycle supervisor & cancellation engine
│       │   ├── tool_registry.py # Dynamic tool registry with validation
│       │   ├── tool_executor.py # Idempotent, cancellable tool executor
│       │   ├── trace_logger.py  # In-memory & streaming trace logger
│       │   └── orchestrator.py  # Dual-path Orchestrator & Continuity Engine
│       ├── providers/           # LLM and classifier integrations
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── mock_llm.py      # Deterministic Mock LLM for scenarios & tests
│       │   ├── openai_llm.py    # OpenAI-compatible / external LLM adapter
│       │   └── fast_classifier.py# Deterministic/simple rule-based classifier
│       ├── tools/               # Standard & Mock Tools
│       │   ├── __init__.py
│       │   ├── base_tool.py     # BaseTool abstract class
│       │   ├── flight_booking.py# Flight search (Read) & Booking (State-Modifying)
│       │   ├── weather.py       # Read-only external API tool
│       │   └── calendar_tools.py# State-modifying calendar tool
│       └── server/              # FastAPI & WebSocket server
│           ├── __init__.py
│           ├── app.py           # FastAPI application
│           ├── routes.py        # REST endpoints (health, debug, scenarios)
│           └── ws_handler.py    # Real-time WebSocket connection handler
├── frontend/                    # Modern Developer/Ops Observability Console
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx
│       ├── components/
│       │   ├── SessionHeader.tsx
│       │   ├── ConversationStream.tsx
│       │   ├── StateVersionViewer.tsx
│       │   ├── TaskLifecycleMatrix.tsx
│       │   └── TraceTimeline.tsx
│       └── hooks/
├── tests/                       # Deterministic Unit & Integration Test Suite
│   ├── conftest.py
│   ├── test_state_manager.py    # Versioning & mutation tests
│   ├── test_task_cancellation.py# Task cancellation & stale result rejection
│   ├── test_fast_path.py        # Interruption latency & fast-ack
│   ├── test_classifier.py       # Interruption classification tests
---

## 4. Core Domain Models (Pydantic v2)

### 4.1 Session & State Models (`models/state.py`)
- `SessionStatus`: `ACTIVE`, `PAUSED`, `TERMINATED`
- `SlotValue`: `key: str`, `value: Any`, `confidence: float = 1.0`, `source_state_version: int`, `updated_at: datetime`
- `SessionState`:
  - `session_id: str`
  - `state_version: int = 1`
  - `status: SessionStatus = SessionStatus.ACTIVE`
  - `current_intent: Optional[str] = None`
  - `slots: Dict[str, SlotValue] = Field(default_factory=dict)`
  - `active_task_ids: List[str] = Field(default_factory=list)`
  - `completed_task_ids: List[str] = Field(default_factory=list)`
  - `cancelled_task_ids: List[str] = Field(default_factory=list)`
  - `stale_task_ids: List[str] = Field(default_factory=list)`
  - `last_user_utterance: Optional[str] = None`
  - `last_assistant_utterance: Optional[str] = None`
  - `created_at: datetime`, `updated_at: datetime`

### 4.2 Task Lifecycle Models (`models/tasks.py`)
- `TaskStatus`: `PENDING`, `RUNNING`, `CANCELLING`, `CANCELLED`, `COMPLETED`, `FAILED`, `STALE`
- `TaskType`: `REASONING`, `TOOL_EXECUTION`, `MULTIMODAL_PROCESSING`, `SPEECH_SYNTHESIS`
- `TaskRecord`:
  - `task_id: str`, `call_id: Optional[str] = None`
  - `task_type: TaskType`, `tool_name: Optional[str] = None`
  - `input_params: Dict[str, Any] = Field(default_factory=dict)`
  - `origin_state_version: int`
  - `status: TaskStatus = TaskStatus.PENDING`
  - `idempotency_key: Optional[str] = None`
  - `is_state_modifying: bool = False`
  - `result: Optional[Any] = None`, `error: Optional[str] = None`
  - `cancellation_reason: Optional[str] = None`
  - `created_at: datetime`, `started_at: Optional[datetime] = None`, `completed_at: Optional[datetime] = None`

### 4.3 Tool Manifest & Execution Models (`models/tools.py`)
- `ToolCategory`: `READ_ONLY`, `STATE_MODIFYING`
- `ToolManifest`: `name: str`, `description: str`, `category: ToolCategory`, `parameters_schema: Dict[str, Any]`, `supports_cancellation: bool = True`, `timeout_seconds: float = 30.0`, `idempotency_required: bool = False`
- `ToolCallRequest`: `call_id: str`, `tool_name: str`, `arguments: Dict[str, Any]`, `idempotency_key: Optional[str] = None`, `origin_state_version: int`
- `ToolExecutionResult`: `call_id: str`, `tool_name: str`, `status: TaskStatus`, `data: Optional[Any] = None`, `error: Optional[str] = None`, `execution_duration_ms: float`, `origin_state_version: int`

### 4.4 Interruption Classification Models (`models/classifier.py`)
- `InterruptionCategory`:
  - `CORRECTION`: User explicitly rectifies a slot or state attribute (e.g., "Actually Mumbai").
  - `INTERRUPTION`: User abruptly stops or changes the conversation flow.
  - `BACKCHANNEL`: Non-interruptive feedback (e.g., "uh-huh", "okay", "go on").
  - `NEW_QUERY`: User abandons prior task to start a new independent query.
  - `CANCEL`: User explicitly halts the ongoing action.
  - `UNKNOWN`: Unclassified utterance falling back to full slow-path reasoning.
- `ClassificationResult`:
  - `category: InterruptionCategory`
  - `confidence: float = 1.0`
  - `extracted_deltas: Dict[str, Any] = Field(default_factory=dict)`
---

## 5. Core Interfaces (Protocols)

1. `IEventBus`:
   - `publish(event: RuntimeEvent) -> None`
   - `subscribe(event_type: EventType, handler: Callable[[RuntimeEvent], Awaitable[None]]) -> None`

2. `IStateManager`:
   - `get_state(session_id: str) -> SessionState`
   - `apply_delta(session_id: str, slot_deltas: Dict[str, Any], intent: Optional[str] = None) -> SessionState`
   - `is_valid_version(session_id: str, state_version: int) -> bool`

3. `ITaskManager`:
   - `spawn_task(session_id: str, task: TaskRecord, coro: Awaitable[Any]) -> str`
   - `cancel_affected_tasks(session_id: str, state_delta: Dict[str, Any], reason: str) -> List[str]`
   - `cancel_all_active(session_id: str, reason: str) -> List[str]`
   - `get_task(task_id: str) -> Optional[TaskRecord]`

4. `IInterruptionClassifier`:
   - `classify(utterance: str, current_state: SessionState) -> ClassificationResult`
   - *Design note:* Decoupled and replaceable abstraction. The system optimizes for low latency and measures actual latency through traces. Initially uses a deterministic/simple rule and pattern implementation. Kept replaceable so a small model or advanced classifier can be introduced only if benchmarking demonstrates a need.

5. `IToolRegistry` & `IToolExecutor`:
   - `register_tool(manifest: ToolManifest, executor_fn: Callable[..., Awaitable[Any]]) -> None`
   - `get_manifests() -> List[ToolManifest]`
   - `execute(request: ToolCallRequest, current_version_getter: Callable[[], int]) -> ToolExecutionResult`

6. `ILLMProvider`:
   - `plan_and_reason(session_state, conversation_history, available_tools, user_input) -> LLMPlan`

7. `ITraceLogger`:
   - `log_event(event: RuntimeEvent) -> None`
   - `get_session_trace(session_id: str) -> List[RuntimeEvent]`

  - `classification_duration_ms: float = 0.0`

### 4.5 Event Protocol Models (`models/events.py`)
- `EventType`: `USER_TEXT`, `USER_INTERRUPTION`, `AUDIO_CHUNK`, `VIDEO_FRAME`, `SESSION_START`, `SESSION_END`, `FAST_ACK`, `STATE_MUTATED`, `TASK_SCHEDULED`, `TASK_STARTED`, `TASK_CANCELLING`, `TASK_CANCELLED`, `TASK_COMPLETED`, `TASK_REJECTED_STALE`, `AGENT_SPEAKING`, `AGENT_FINAL_RESPONSE`, `SYSTEM_ERROR`
- `RuntimeEvent`: `event_id: str`, `session_id: str`, `event_type: EventType`, `timestamp: datetime`, `state_version: int`, `payload: Dict[str, Any]`

│   └── test_orchestrator.py     # Full loop integration
└── evaluation/                  # Deterministic Replay & Scenario Benchmarks
    ├── runner.py                # Isolated scenario replay engine with virtual clock
    └── scenarios/
        ├── interruption_flight_correction.json
---

## 6. State Versioning, Invalidation & Stale Protection Rules

1. **State Version Recording**:
   - `state_version` is strictly monotonic (`v_next = v_current + 1`).
   - Every asynchronous task records its originating `origin_state_version` at creation time.

2. **Affected Task Evaluation & Invalidation**:
   - A state-version change triggers evaluation of active tasks.
   - A task may be cancelled or invalidated when the state change affects its inputs or objective.
   - Initial implementation may use conservative version invalidation (cancelling active tasks with `origin_state_version < current_state_version` whose inputs/intent were touched).
   - Future optimization may use explicit slot/task dependency tracking without altering the core interface contract.

3. **Mandatory Stale-Result Validation**:
   - Stale-result validation remains mandatory even when in-flight cancellation was not possible (e.g., non-cancellable third-party network I/O).
   ```text
   WHEN Task T completes with result R:
      IF state_change_invalidates(T, current_state):
          T.status = STALE
          trace_logger.log(TASK_REJECTED_STALE, task_id=T.id, origin=T.origin_state_version, current=current_v)
          DISCARD R
      ELSE:
          T.status = COMPLETED
          APPLY R to state / response pipeline
   ```

4. **Interruption Classification Invariants**:
   - `BACKCHANNEL` -> Do NOT cancel tasks; continue background execution; no state mutation.
   - `CORRECTION` -> Fast-Ack, stage state delta, increment version, cancel affected tasks, trigger replan.
   - `CANCEL` -> Immediately halt all active tasks; emit acknowledgement.
   - `NEW_QUERY` -> Cancel prior tasks, reset active intent, start new plan.
   - `UNKNOWN` -> Hand off to slow path reasoning without destructive pre-emptive cancellation.

---

## 7. Deterministic Replay & Evaluation Architecture

Deterministic replay and evaluation is a first-class architectural concern, isolated from production runtime logic:

```
+-------------------+      +-------------------------+      +-------------------+
|  Scenario Fixture | ---> | Virtual Clock / Replay  | ---> |   Agent Runtime   |
|     (JSON File)   |      |     Harness Engine      |      |   (Dual-Path)     |
+-------------------+      +-------------------------+      +---------+---------+
                                                                      |
                                                                      v
+-------------------+      +-------------------------+      +-------------------+
|   Deterministic   | <--- |   Reconstructed Trace   | <--- |   Trace Logger    |
|    Assertions     |      |       Chronology        |      | (Immutable JSONL) |
+-------------------+      +-------------------------+      +-------------------+
```

- **Scenario Fixtures (`evaluation/scenarios/*.json`)**: Define timed sequences of user events, simulated tool latencies/responses, and expected state milestones.
- **Virtual Clock / Replay Engine (`evaluation/runner.py`)**: Feeds events with deterministic timing intervals without relying on unpredictable wall-clock sleeping.
- **Trace Output**: Generates complete chronological traces of all internal and external events.
- **Deterministic Assertions**: Verifies final state versions, cancelled task IDs, stale result discards, and response outputs.

---

## 8. Anti-Overengineering Invariants

- **No Premature ML / Heavy Pipelines**: Do not introduce ML models, multimodal pipelines, dependency graphs, distributed infrastructure, or agent frameworks (e.g., LangGraph, CrewAI, AutoGen) until a measurable requirement and benchmark trace justifies them.
- **Runtime-Owned Concurrency**: Concurrency, state transitions, task lifecycles, and cancellation are directly controlled by standard Python `asyncio` primitives and Pydantic models.
- **LLM as Unprivileged Reasoner**: The LLM never writes directly to application state or task tables; it only proposes deltas and tool calls that are validated by the runtime.
- **Backend First as Product**: The backend runtime, state consistency, latency guarantees, and deterministic trace logs are the actual product. The frontend is strictly an observability and demonstration console.
