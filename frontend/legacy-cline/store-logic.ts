// Event processing helpers
import type { RuntimeEvent, TaskRecord, TaskStatus } from "./types";
import type { VersionSnapshot } from "./store-types";

export function deriveTasks(events: RuntimeEvent[]): TaskRecord[] {
  const seen = new Map<string, TaskRecord>();
  for (const e of events) {
    if (e.event_type === "TASK_SCHEDULED" || e.event_type === "TASK_STARTED") {
      seen.set(e.task_id ?? "", {
        task_id: e.task_id ?? "", task_type: "TOOL_EXECUTION",
        tool_name: e.tool_name, origin_state_version: e.state_version,
        status: e.event_type === "TASK_STARTED" ? "RUNNING" : "PENDING",
        input_params: {},
      });
    } else if (e.event_type === "TASK_CANCELLED") {
      seen.get(e.task_id ?? "") && (seen.get(e.task_id ?? "")!.status = "CANCELLED");
    } else if (e.event_type === "TASK_COMPLETED") {
      seen.get(e.task_id ?? "") && (seen.get(e.task_id ?? "")!.status = "COMPLETED");
    } else if (e.event_type === "TASK_REJECTED_STALE") {
      seen.get(e.task_id ?? "") && (seen.get(e.task_id ?? "")!.status = "STALE");
    }
  }
  return Array.from(seen.values());
}

export function computeVersions(events: RuntimeEvent[]): VersionSnapshot[] {
  const byVer = new Map<number, RuntimeEvent[]>();
  for (const e of events) {
    if (!byVer.has(e.state_version)) byVer.set(e.state_version, []);
    byVer.get(e.state_version)!.push(e);
  }
  return Array.from(byVer.entries()).sort(([a], [b]) => a - b).map(([version, evts]) => {
    const userEvts = evts.filter((e) => e.event_type === "USER_TEXT");
    const taskEvts = evts.filter((e) => e.event_type.startsWith("TASK_"));
    return {
      version, userText: userEvts[userEvts.length - 1]?.text ?? null,
      slots: {}, eventCount: evts.length,
      tasks: taskEvts.map((te) => ({
        task_id: te.task_id ?? "", task_type: "TOOL_EXECUTION" as const,
        tool_name: te.tool_name, origin_state_version: te.state_version,
        status: (te.event_type === "TASK_CANCELLED" ? "CANCELLED"
          : te.event_type === "TASK_REJECTED_STALE" ? "STALE"
          : te.event_type === "TASK_COMPLETED" ? "COMPLETED" : "RUNNING") as TaskStatus,
        input_params: {},
      })),
      cancelled: evts.some((e) => e.event_type === "TASK_CANCELLED" || e.event_type === "TASK_REJECTED_STALE"),
      isCurrent: evts.some((e) => e.event_type === "AGENT_FINAL_RESPONSE"),
    } satisfies VersionSnapshot;
  });
}

export function detectCorrection(events: RuntimeEvent[]): { from: string; to: string } | null {
  const texts = events.filter((e) => e.event_type === "USER_TEXT" && !!e.text);
  if (texts.length < 2) return null;
  const last = texts[texts.length - 1];
  const prev = texts[texts.length - 2];
  if (!prev.text || !last.text || last.text === prev.text) return null;
  if (last.state_version <= prev.state_version) return null;
  const extractCity = (t: string) => {
    const m = t.match(/\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b/);
    return m ? m[1] : null;
  };
  const cOld = extractCity(prev.text);
  const cNew = extractCity(last.text);
  if (cOld && cNew && cOld !== cNew) return { from: cOld, to: cNew };
  const mOld = prev.text.match(/(?:to|for|make it|change to)\s+(.+?)(?:\s*$|\.|\!)/i);
  const mNew = last.text.match(/(?:to|for|make it|change to)\s+(.+?)(?:\s*$|\.|\!)/i);
  if (mOld && mNew && mOld[1].trim() !== mNew[1].trim()) return { from: mOld[1].trim(), to: mNew[1].trim() };
  return null;
}

export function processEvent(stateEvents: RuntimeEvent[], event: RuntimeEvent) {
  const allEvents = [...stateEvents, event];
  return { allEvents, tasks: deriveTasks(allEvents), versions: computeVersions(allEvents), delta: detectCorrection(allEvents) };
}