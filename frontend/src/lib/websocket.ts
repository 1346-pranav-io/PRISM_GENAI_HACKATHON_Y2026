import type { RuntimeEvent, EventType } from "./types";

type EventHandler = (event: RuntimeEvent) => void;

const CLIENT_EVENT_TYPES: EventType[] = [
  "USER_TEXT",
  "USER_INTERRUPTION",
  "SESSION_START",
  "SESSION_END",
  "FAST_ACK",
  "STATE_MUTATED",
  "TASK_SCHEDULED",
  "TASK_STARTED",
  "TASK_CANCELLING",
  "TASK_CANCELLED",
  "TASK_COMPLETED",
  "TASK_REJECTED_STALE",
  "AGENT_SPEAKING",
  "AGENT_FINAL_RESPONSE",
  "SYSTEM_ERROR",
];

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private handlers: Set<EventHandler> = new Set();
  private _sessionId: string | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private _status: "connecting" | "connected" | "disconnected" | "error" = "disconnected";
  private url: string;
  private onStatusChange: (status: string) => void;

  constructor(url: string, onStatusChange: (status: string) => void) {
    this.url = url;
    this.onStatusChange = onStatusChange;
  }

  get status() {
    return this._status;
  }

  get sessionId() {
    return this._sessionId;
  }

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this._setStatus("connecting");
    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this._setStatus("error");
      return;
    }

    this.ws.onopen = () => {
      this._setStatus("connected");
    };

    this.ws.onmessage = (evt) => {
      try {
        const raw = JSON.parse(evt.data as string);
        const event = this._parseEvent(raw);
        this.handlers.forEach((h) => h(event));
      } catch (err) {
        console.error("[WS] Failed to parse message:", err);
      }
    };

    this.ws.onerror = () => {
      this._setStatus("error");
    };

    this.ws.onclose = () => {
      this._setStatus("disconnected");
      // Clear stale reconnect attempts
      if (this.reconnectTimer) {
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = null;
      }
    };
  }

  private _setStatus(s: "connecting" | "connected" | "disconnected" | "error") {
    this._status = s;
    this.onStatusChange(s);
  }

  private _parseEvent(raw: Record<string, unknown>): RuntimeEvent {
    // Backend flattens the event payload into the top-level JSON object.
    const payload = { ...((raw.payload as Record<string, unknown>) ?? {}), ...raw } as Record<string, unknown>;
    const event_type = (raw.event_type as string) as EventType;
    return {
      event_id: (raw.event_id as string) ?? crypto.randomUUID(),
      session_id: (raw.session_id as string) ?? "",
      event_type,
      timestamp: (raw.timestamp as string) ?? new Date().toISOString(),
      state_version: (raw.state_version as number) ?? 0,
      payload,
      // Convenience: pre-extract known fields
      text: (payload.text as string) ?? (raw.text as string),
      task_id: (payload.task_id as string) ?? (raw.task_id as string),
      tool_name: (payload.tool_name as string) ?? (raw.tool_name as string),
      error: (payload.error as string) ?? (raw.error as string),
      cancelled_task_ids: (payload.cancelled_task_ids as string[]) ?? (raw.cancelled_task_ids as string[]),
      tool_results: (payload.tool_results as RuntimeEvent["tool_results"]) ?? (raw.tool_results as RuntimeEvent["tool_results"]),
    };
  }

  send(data: { text?: string; type?: string; content?: string }): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn("[WS] Not connected, cannot send:", data);
      return;
    }
    this.ws.send(JSON.stringify(data));
  }

  sendInterrupt(text?: string): void {
    this.send({ type: "interrupt", text: text ?? "" });
  }

  subscribe(handler: EventHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    if (this.ws) {
      this.ws.onclose = null; // prevent status bounce
      this.ws.close();
      this.ws = null;
    }
    this._setStatus("disconnected");
    this.handlers.clear();
  }
}

// Singleton export for the playground session
let clientInstance: WebSocketClient | null = null;

export function getPlaygroundClient(
  sessionId: string,
  onStatusChange: (status: string) => void,
): WebSocketClient {
  if (clientInstance) {
    clientInstance.disconnect();
  }
  // Dynamically import BASE_URL to avoid circular
  const base =
    typeof window !== "undefined"
      ? window.location.protocol === "https:"
        ? `wss://${window.location.host}`
        : `ws://${window.location.host}`
      : "";
  const apiBase =
    process.env.NEXT_PUBLIC_API_URL ??
    "https://interruptible-realtime-agent.onrender.com";
  const wsUrl = apiBase
    .replace("https://", "wss://")
    .replace("http://", "ws://")
    .replace(/\/api\/v1$/, "")
    + `/ws/${encodeURIComponent(sessionId)}`;

  clientInstance = new WebSocketClient(wsUrl, onStatusChange);
  return clientInstance;
}

export function disconnectPlayground(): void {
  if (clientInstance) {
    clientInstance.disconnect();
    clientInstance = null;
  }
}