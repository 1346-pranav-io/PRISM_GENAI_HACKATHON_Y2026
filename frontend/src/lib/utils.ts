import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

export function taskStatusColor(status: string): string {
  switch (status) {
    case "RUNNING": return "text-blue-400";
    case "PENDING": return "text-yellow-400";
    case "CANCELLED": return "text-orange-400";
    case "STALE": return "text-red-400";
    case "COMPLETED": return "text-emerald-400";
    case "FAILED": return "text-red-500";
    default: return "text-muted-foreground";
  }
}

export function taskStatusBg(status: string): string {
  switch (status) {
    case "RUNNING": return "bg-blue-500/10 border-blue-500/30";
    case "PENDING": return "bg-yellow-500/10 border-yellow-500/30";
    case "CANCELLED": return "bg-orange-500/10 border-orange-500/30";
    case "STALE": return "bg-red-500/10 border-red-500/30";
    case "COMPLETED": return "bg-emerald-500/10 border-emerald-500/30";
    case "FAILED": return "bg-red-500/20 border-red-500/40";
    default: return "bg-muted border-border";
  }
}

export function eventTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    USER_TEXT: "User",
    USER_INTERRUPTION: "Interrupt",
    FAST_ACK: "Fast Ack",
    STATE_MUTATED: "State Updated",
    TASK_SCHEDULED: "Task Scheduled",
    TASK_STARTED: "Task Started",
    TASK_CANCELLING: "Cancelling",
    TASK_CANCELLED: "Cancelled",
    TASK_COMPLETED: "Completed",
    TASK_REJECTED_STALE: "Stale Rejected",
    AGENT_SPEAKING: "Speaking",
    AGENT_FINAL_RESPONSE: "Final Response",
    SYSTEM_ERROR: "System Error",
  };
  return labels[type] ?? type;
}

export function eventTypeColor(type: string): string {
  if (type.startsWith("TASK_CANCEL")) return "text-orange-400";
  if (type === "TASK_REJECTED_STALE") return "text-red-400";
  if (type === "AGENT_FINAL_RESPONSE") return "text-emerald-400";
  if (type === "FAST_ACK") return "text-cyan-400";
  if (type === "USER_TEXT") return "text-primary";
  if (type === "SYSTEM_ERROR") return "text-red-500";
  return "text-muted-foreground";
}

export function generateSessionId(): string {
  const adj = ["swift", "bright", "calm", "sharp", "steady", "warm"];
  const noun = ["agent", "stream", "pilot", "node", "core", "loop"];
  const a = adj[Math.floor(Math.random() * adj.length)];
  const n = noun[Math.floor(Math.random() * noun.length)];
  const id = Math.random().toString(36).slice(2, 7);
  return `${a}-${n}-${id}`;
}

export function truncate(s: string, max = 80): string {
  if (s.length <= max) return s;
  return s.slice(0, max - 1) + "…";
}

export function pluralize(n: number, word: string): string {
  return `${n} ${word}${n !== 1 ? "s" : ""}`;
}