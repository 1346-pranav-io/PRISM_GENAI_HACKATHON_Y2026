"use client";
import { useEvents } from "@/lib/store-context";
import { cn, formatTimestamp, eventTypeLabel, eventTypeColor } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

export function EventStream() {
  const events = useEvents();

  if (events.length === 0) {
    return (
      <div className="h-full flex items-center justify-center"> <p className="text-foreground/30 text-xs font-mono">
          Waiting for events...
        </p>
      </div>
    );
  }

  return (
    <ScrollArea className="h-full" type="always"> <div className="space-y-0 p-2">
        {events.slice(-80).map((e, idx) => {
          const label = eventTypeLabel(e.event_type); const color = eventTypeColor(e.event_type); const isUser = e.event_type === "USER_TEXT";
          const isAgent = e.event_type === "AGENT_FINAL_RESPONSE";
          const isCancelled = e.event_type === "TASK_CANCELLED"; const isStale = e.event_type === "TASK_REJECTED_STALE";
          return (
            <div key={e.event_id} className={cn(
              "flex items-start gap-2 px-2 py-1.5 rounded-md text-xs animate-slide-in-right",
              isCancelled && "bg-orange-500/5",
              isStale && "bg-red-500/5",
            )}>
              <span className="text-[10px] text-cyan-400/60 font-mono mt-px w-12 flex- shrink-0">{formatTimestamp(e.timestamp).slice(0, 8)}</span>
              <code className={cn("text-[10px] font-mono px-1 py-0.5 rounded border flex-shrink-0", e.event_type === "USER_TEXT" ? "bg-blue-500/10 border-blue-500/20 text-blue-400" : "bg-muted border-border text-muted-foreground")}>
                v{e.state_version}
              </code>
              <span className={cn("text-xs font-mono font-medium flex-shrink-0", color)}>{label}</span>
              <span className="flex-1 text-muted-foreground font-mono truncate">
                {isUser && e.text && <span className="text-foreground/60 italic">"{e.text.slice(0, 40)}{e.text.length > 40 ? "…" : ""}"</span>}
                {e.tool_name && <span className="text-primary/80">{e.tool_name}</span>}
                {e.event_type === "FAST_ACK" && e.text && <span className="text-cyan-400/70 italic">"{e.text}"</span>}
                {e.error && <span className="text-red-400">{e.error}</span>}
                {isCancelled && e.task_id && <span className="text-orange-400">task={e.task_id.slice(0, 8)}…</span>}
                {isStale && <span className="text-red-400/80">stale result discarded</span>}
                {!isUser && !e.tool_name && !e.error && !isCancelled && !isStale && e.event_type !== "FAST_ACK" && e.text && <span className="text-muted-foreground italic truncate">"{truncate(e.text, 50)}"</span>}
              </span>
            </div>
          );
        })}
      </div>
    </ScrollArea>
  );
}

function truncate(s: string, n: number) { return s.length <= n ? s : s.slice(0, n) + "…"; }