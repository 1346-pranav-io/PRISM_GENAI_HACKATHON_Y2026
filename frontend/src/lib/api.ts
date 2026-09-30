import type {
  HealthStatus,
  ReadinessStatus,
  InitSessionResponse,
  SendMessageResponse,
  SessionStateResponse,
  SessionTrace,
  DebugSessions,
  DebugTasks,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "https://interruptible-realtime-agent.onrender.com";
const API = `${BASE_URL}/api/v1`;

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json() as Promise<T>;
}

// Health
export async function getHealth(): Promise<HealthStatus> {
  return get<HealthStatus>("/health");
}

export async function getReadiness(): Promise<ReadinessStatus> {
  return get<ReadinessStatus>("/health/ready");
}

// Sessions
export async function initSession(sessionId: string): Promise<InitSessionResponse> {
  return post<InitSessionResponse>(`/sessions/${encodeURIComponent(sessionId)}/init`);
}

export async function sendMessage(
  sessionId: string,
  text: string,
): Promise<SendMessageResponse> {
  return post<SendMessageResponse>(`/sessions/${encodeURIComponent(sessionId)}/message`, {
    session_id: sessionId,
    text,
  });
}

export async function getSessionState(sessionId: string): Promise<SessionStateResponse> {
  return get<SessionStateResponse>(
    `/sessions/${encodeURIComponent(sessionId)}/state`,
  );
}

export async function getSessionTrace(sessionId: string): Promise<SessionTrace> {
  return get<SessionTrace>(`/sessions/${encodeURIComponent(sessionId)}/trace`);
}

// Debug
export async function listActiveSessions(): Promise<DebugSessions> {
  return get<DebugSessions>("/debug/sessions");
}

export async function getSessionTasks(sessionId: string): Promise<DebugTasks> {
  return get<DebugTasks>(`/debug/tasks/${encodeURIComponent(sessionId)}`);
}

export function getWebSocketUrl(sessionId: string): string {
  const wsBase = BASE_URL.replace("https://", "wss://").replace("http://", "ws://");
  return `${wsBase}/ws/${encodeURIComponent(sessionId)}`;
}

export { BASE_URL };
export type { BASE_URL as ApiBaseUrl };