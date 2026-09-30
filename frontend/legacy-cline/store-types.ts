// Store types
import type { RuntimeEvent, SessionStateResponse, TaskRecord } from "./types";

export interface PlaygroundState {
  sessionId: string | null;
  connectionStatus: "connecting" | "connected" | "disconnected" | "error";
  events: RuntimeEvent[];
  currentState: SessionStateResponse | null;
  tasks: TaskRecord[];
  correctionDelta: { from: string; to: string } | null;
  versions: VersionSnapshot[];
  isProcessing: boolean;
  lastAgentResponse: string | null;
}

export interface VersionSnapshot {
  version: number;
  userText: string | null;
  slots: Record<string, unknown>;
  eventCount: number;
  tasks: TaskRecord[];
  cancelled: boolean;
  isCurrent: boolean;
}

export const initialState: PlaygroundState = {
  sessionId: null,
  connectionStatus: "disconnected",
  events: [],
  currentState: null,
  tasks: [],
  correctionDelta: null,
  versions: [],
  isProcessing: false,
  lastAgentResponse: null,
};

export type Action =
  | { type: "SET_SESSION"; sessionId: string }
  | { type: "SET_CONNECTION"; status: PlaygroundState["connectionStatus"] }
  | { type: "ADD_EVENT"; event: RuntimeEvent }
  | { type: "SET_STATE"; state: SessionStateResponse }
  | { type: "SET_TASKS"; tasks: TaskRecord[] }
  | { type: "SET_PROCESSING"; isProcessing: boolean }
  | { type: "SET_CORRECTION"; delta: { from: string; to: string } | null }
  | { type: "SET_LAST_RESPONSE"; text: string | null }
  | { type: "SNAPSHOT_VERSION"; snapshot: VersionSnapshot }
  | { type: "RESET" };

export function reducer(s: PlaygroundState, a: Action): PlaygroundState {
  switch (a.type) {
    case "SET_SESSION": return { ...s, sessionId: a.sessionId };
    case "SET_CONNECTION": return { ...s, connectionStatus: a.status };
    case "ADD_EVENT": return { ...s, events: [...s.events, a.event] };
    case "SET_STATE": return { ...s, currentState: a.state };
    case "SET_TASKS": return { ...s, tasks: a.tasks };
    case "SET_PROCESSING": return { ...s, isProcessing: a.isProcessing };
    case "SET_CORRECTION": return { ...s, correctionDelta: a.delta };
    case "SET_LAST_RESPONSE": return { ...s, lastAgentResponse: a.text };
    case "SNAPSHOT_VERSION": {
      const versions = s.versions.map((v) => ({ ...v, isCurrent: false }));
      const existing = versions.findIndex((v) => v.version === a.snapshot.version);
      if (existing >= 0) versions[existing] = a.snapshot;
      else versions.push(a.snapshot);
      return { ...s, versions };
    }
    case "RESET": return initialState;
    default: return s;
  }
}