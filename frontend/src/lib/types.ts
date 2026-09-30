// Backend event types matching the runtime schema
export type EventType =
  // Inbound
  | "USER_TEXT"
  | "USER_INTERRUPTION"
  | "AUDIO_CHUNK"
  | "VIDEO_FRAME"
  | "SESSION_START"
  | "SESSION_END"
  // Outbound / Internal
  | "FAST_ACK"
  | "STATE_MUTATED"
  | "TASK_SCHEDULED"
  | "TASK_STARTED"
  | "TASK_CANCELLING"
  | "TASK_CANCELLED"
  | "TASK_COMPLETED"
  | "TASK_REJECTED_STALE"
  | "AGENT_SPEAKING"
  | "AGENT_FINAL_RESPONSE"
  | "SYSTEM_ERROR";

export interface RuntimeEvent {
  event_id: string;
  session_id: string;
  event_type: EventType;
  timestamp: string;
  state_version: number;
  payload: Record<string, unknown>;
  // Convenience: pre-extracted fields from payload
  text?: string;
  task_id?: string;
  tool_name?: string;
  error?: string;
  cancelled_task_ids?: string[];
  tool_results?: ToolResult[];
}

export interface ToolResult {
  task_id: string;
  tool_name: string;
  status: TaskStatus;
  data: unknown;
  error: string | null;
}

// Session state from REST /sessions/{id}/state
export interface SessionStateResponse {
  session_id: string;
  state_version: number;
  status: "ACTIVE" | "PAUSED" | "TERMINATED";
  current_intent: string | null;
  slots: Record<string, SlotValue>;
}

export interface SlotValue {
  key: string;
  value: unknown;
  confidence: number;
  source_state_version: number;
  updated_at: string;
}

// Task types
export type TaskStatus =
  | "PENDING"
  | "RUNNING"
  | "CANCELLING"
  | "CANCELLED"
  | "COMPLETED"
  | "FAILED"
  | "STALE";

export type TaskType =
  | "REASONING"
  | "TOOL_EXECUTION"
  | "MULTIMODAL_PROCESSING"
  | "SPEECH_SYNTHESIS";

export interface TaskRecord {
  task_id: string;
  call_id?: string;
  task_type: TaskType;
  tool_name?: string;
  input_params: Record<string, unknown>;
  origin_state_version: number;
  status: TaskStatus;
  result?: unknown;
  error?: string;
  cancellation_reason?: string;
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

// Interruption categories
export type InterruptionCategory =
  | "CORRECTION"
  | "INTERRUPTION"
  | "BACKCHANNEL"
  | "NEW_QUERY"
  | "CANCEL"
  | "UNKNOWN";

// App state types
export interface AppState {
  sessionId: string | null;
  stateVersion: number;
  connectionStatus: "connecting" | "connected" | "disconnected" | "error";
  events: RuntimeEvent[];
  currentState: SessionStateResponse | null;
  tasks: TaskRecord[];
  pendingMessages: string[];
  correctionDelta: { from: string; to: string } | null;
  versions: VersionSnapshot[];
}

export interface VersionSnapshot {
  version: number;
  intent: string | null;
  slots: Record<string, unknown>;
  eventCount: number;
  tasks: TaskRecord[];
  cancelled: boolean;
  isCurrent: boolean;
}

// Health check
export interface HealthStatus {
  status: string;
  service: string;
}

export interface ReadinessStatus {
  ready: boolean;
  engine_initialized: boolean;
}

// API response types
export interface InitSessionResponse {
  session_id: string;
  status: string;
}

export interface SendMessageResponse {
  session_id: string;
  state_version: number;
  status: string;
}

export interface SessionTrace {
  session_id: string;
  events: RuntimeEvent[];
}

export interface DebugSessions {
  active_sessions: string[];
}

export interface DebugTasks {
  tasks: TaskRecord[];
}