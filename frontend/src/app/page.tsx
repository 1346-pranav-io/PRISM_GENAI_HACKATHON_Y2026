"use client";
import { useMemo, useState } from "react";
import { ArrowDown, Ban, Check, CircleDot, RotateCcw, Send, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useSession } from "@/lib/use-session";
import { deriveTurns, parseToolOutput, type Turn } from "@/lib/turns";
import { BASE_URL } from "@/lib/api";
import { cn, formatTimestamp } from "@/lib/utils";

const EVENT_STYLE: Record<string, string> = {
  USER_TEXT: "text-sky-300 border-sky-500/30 bg-sky-500/10",
  FAST_ACK: "text-amber-300 border-amber-500/30 bg-amber-500/10",
  TASK_SCHEDULED: "text-violet-300 border-violet-500/30 bg-violet-500/10",
  TASK_CANCELLED: "text-red-300 border-red-500/30 bg-red-500/10",
  TASK_REJECTED_STALE: "text-red-300 border-red-500/30 bg-red-500/10",
  AGENT_FINAL_RESPONSE: "text-emerald-300 border-emerald-500/30 bg-emerald-500/10",
};

function Dot({ status }: { status: string }) {
  const c = status === "connected" ? "bg-emerald-400" : status === "connecting" ? "bg-amber-400 animate-pulse" : "bg-red-500";
  return <span className={cn("inline-block h-2 w-2 rounded-full", c)} />;
}

function TurnCard({ t, isLast }: { t: Turn; isLast: boolean }) {
  const dead = t.supersededBy !== undefined;
  const { summary, flights } = parseToolOutput(t.response);
  return (
    <Card className={cn("p-4 transition-all", dead ? "border-red-500/40 bg-red-500/5" : isLast ? "border-emerald-500/40" : "")}>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">v{t.version}</Badge>
        {t.category && <Badge variant="secondary">{t.category}</Badge>}
        {dead && (
          <Badge className="border border-red-500/40 bg-red-500/20 text-red-300">
            <Ban className="mr-1 h-3 w-3" />
            SUPERSEDED, work cancelled
          </Badge>
        )}
        {!dead && t.response && (
          <Badge className="border border-emerald-500/40 bg-emerald-500/20 text-emerald-300">
            <Check className="mr-1 h-3 w-3" />
            FINAL @ v{t.responseVersion}
          </Badge>
        )}
      </div>
      <p className={cn("mt-2 text-base", dead && "line-through decoration-red-400/60 opacity-70")}>“{t.text}”</p>
      {t.ack && <p className="mt-1 text-xs text-amber-300/80">⚡ {t.ack}</p>}

      {t.cancelledIds.length > 0 && (
        <div className="mt-3 rounded-md border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-300">
          TASK_CANCELLED → {t.cancelledIds.join(", ")}
        </div>
      )}
      {t.tasks.map((k) => (
        <div key={k.id} className="mt-3 flex items-center gap-2 rounded-md border border-violet-500/30 bg-violet-500/10 p-2 text-xs text-violet-200">
          <CircleDot className="h-3 w-3" /> TASK_SCHEDULED {k.id} · {k.tool} · v{k.version}
        </div>
      ))}
      {t.response && (
        <div className="mt-3 rounded-md border border-border bg-background/60 p-3 text-xs">
          <div className="mb-2 text-muted-foreground">AGENT_FINAL_RESPONSE</div>
          <div className="mb-2">{summary}</div>
          {flights.length > 0 ? (
            <div className="space-y-1">
              {flights.map((f, i) => (
                <div key={i} className="flex justify-between rounded bg-secondary/60 px-2 py-1">
                  <span>
                    {String(f.id)} · {String(f.airline)}
                  </span>
                  <span>
                    {String(f.from)} → <b>{String(f.to)}</b> · ${String(f.price)}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <pre className="whitespace-pre-wrap">{t.response}</pre>
          )}
        </div>
      )}
    </Card>
  );
}

export default function Page() {
  const { sessionId, status, events, send, reset } = useSession();
  const [text, setText] = useState("");
  const turns = useMemo(() => deriveTurns(events), [events]);
  const version = events.length ? events[events.length - 1].state_version : 1;
  const lastDone = [...turns].reverse().find((t) => t.response);
  const destination = lastDone ? (parseToolOutput(lastDone.response).flights[0]?.to as string | undefined) : undefined;
  const ready = status === "connected";

  return (
    <div className="flex h-screen flex-col bg-[radial-gradient(ellipse_at_top,hsl(258_60%_12%),transparent_60%)]">
      <header className="flex items-center justify-between border-b border-border px-6 py-3">
        <div className="flex items-center gap-3">
          <Zap className="h-5 w-5 text-primary" />
          <div>
            <h1 className="text-sm font-semibold tracking-wide">Interruptible Agent Runtime · Live Console</h1>
            <p className="text-[11px] text-muted-foreground">
              {BASE_URL.replace("https://", "")} · session {sessionId}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs">
          <span className="flex items-center gap-2">
            <Dot status={status} />
            {status}
          </span>
          <Badge variant="outline">state v{version}</Badge>
          <Badge variant="secondary">result destination: {destination ?? "none"}</Badge>
          <Button size="sm" variant="ghost" onClick={reset}>
            <RotateCcw className="mr-1 h-3 w-3" />
            New session
          </Button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 p-4 lg:grid-cols-[1.2fr_1fr]">
        <section className="flex min-h-0 flex-col gap-3">
          <div className="flex flex-wrap gap-2">
            <Button disabled={!ready} onClick={() => send("Book a flight to Mumbai", "Actually make it New York")}>
              <Zap className="mr-1 h-4 w-4" />
              Run demo: Mumbai → “Actually New York”
            </Button>
            <Button disabled={!ready} variant="secondary" onClick={() => send("Book a flight to Mumbai")}>
              Book a flight to Mumbai
            </Button>
            <Button disabled={!ready} variant="secondary" onClick={() => send("Actually make it New York")}>
              Actually make it New York
            </Button>
          </div>
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            <b className="text-foreground">Run demo</b> triggers a real interruption sequence against the live runtime: it sends
            “Book a flight to Mumbai” and, immediately after on the same WebSocket, “Actually make it New York”. The backend&apos;s
            processing window is only ~50 ms, so the two are sent back-to-back to land the correction while Mumbai work is in flight.
            No delays or events are simulated; everything below is what the server emitted.
          </p>

          <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
            {turns.length === 0 && (
              <Card className="p-6 text-sm text-muted-foreground">
                {ready ? "Connected to the live backend. Send a message or run the demo." : "Connecting to backend (Render free tier can take ~30s to wake)…"}
              </Card>
            )}
            {turns.map((t, i) => (
              <div key={t.index}>
                {i > 0 && (
                  <div className="flex flex-col items-center py-1 text-[11px] text-amber-300">
                    <ArrowDown className="h-4 w-4" />
                    {t.category === "CORRECTION" ? "INTERRUPTION · CORRECTION" : t.category ?? "NEXT TURN"}
                    <ArrowDown className="h-4 w-4" />
                  </div>
                )}
                <TurnCard t={t} isLast={i === turns.length - 1} />
              </div>
            ))}
          </div>

          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (text.trim() && ready) {
                send(text.trim());
                setText("");
              }
            }}
          >
            <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message…" disabled={!ready} />
            <Button type="submit" disabled={!ready}>
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </section>

        <section className="flex min-h-0 flex-col gap-2">
          <div className="text-xs uppercase tracking-widest text-muted-foreground">Raw WebSocket events ({events.length})</div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto rounded-lg border border-border bg-card/60 p-2 text-xs">
            {events.map((e, i) => (
              <div key={i} className={cn("rounded border px-2 py-1", EVENT_STYLE[e.event_type] ?? "border-border")}>
                <div className="flex justify-between">
                  <b>{e.event_type}</b>
                  <span className="opacity-70">
                    v{e.state_version} · {formatTimestamp(e.timestamp)}
                  </span>
                </div>
                <div className="truncate opacity-80">
                  {e.text ?? e.task_id ?? (e.cancelled_task_ids ?? []).join(", ")}
                  {e.tool_name ? ` · ${e.tool_name}` : ""}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
