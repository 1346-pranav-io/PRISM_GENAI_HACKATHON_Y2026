import type { RuntimeEvent } from "./types";

export interface Turn {
  index: number;
  text: string;
  version: number; // version at which the utterance arrived
  category?: string;
  ack?: string;
  cancelledIds: string[]; // work cancelled by THIS turn (belongs to an earlier turn)
  supersededBy?: number; // set when a later turn cancelled this turn's work
  tasks: { id: string; tool?: string; version: number }[];
  response?: string;
  responseVersion?: number;
}

/** Group the raw event stream into user turns. Pure derivation, no invented data. */
export function deriveTurns(events: RuntimeEvent[]): Turn[] {
  const turns: Turn[] = [];
  for (const e of events) {
    const cur = turns[turns.length - 1];
    switch (e.event_type) {
      case "USER_TEXT":
        turns.push({ index: turns.length, text: e.text ?? "", version: e.state_version, cancelledIds: [], tasks: [] });
        break;
      case "FAST_ACK":
        if (cur) {
          cur.ack = e.text;
          cur.category = e.payload.category as string;
        }
        break;
      case "TASK_CANCELLED":
        if (cur) {
          cur.cancelledIds.push(...((e.cancelled_task_ids as string[]) ?? []));
          if (turns.length > 1) turns[turns.length - 2].supersededBy = cur.index;
        }
        break;
      case "TASK_SCHEDULED":
        cur?.tasks.push({ id: e.task_id ?? "", tool: e.tool_name, version: e.state_version });
        break;
      case "AGENT_FINAL_RESPONSE":
        if (cur) {
          cur.response = e.text;
          cur.responseVersion = e.state_version;
        }
        break;
    }
  }
  return turns;
}

export function parseToolOutput(text?: string): { summary: string; flights: Record<string, unknown>[] } {
  if (!text) return { summary: "", flights: [] };
  const [summary, ...rest] = text.split("\n");
  const flights: Record<string, unknown>[] = [];
  for (const line of rest) {
    const i = line.indexOf("[");
    if (i < 0) continue;
    try {
      flights.push(...JSON.parse(line.slice(i)));
    } catch {
      /* not json */
    }
  }
  return { summary, flights };
}
