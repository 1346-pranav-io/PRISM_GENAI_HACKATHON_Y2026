"use client";
import { usePlayground } from "@/lib/store-context";
import { cn } from "@/lib/utils";

export function Header() {
  const { state } = usePlayground();
  const statusColor = {
    connected: "text-emerald-400",
    connecting: "text-yellow-400",
    disconnected: "text-muted-foreground",
    error: "text-red-400",
  }[state.connectionStatus];

  const statusDot = {
    connected: "bg-emerald-400",
    connecting: "bg-yellow-400 animate-pulse",
    disconnected: "bg-muted-foreground",
    error: "bg-red-400",
  }[state.connectionStatus];

  return (
    <header className="h-12 flex-shrink-0 border-b border-border bg-card/60 flex items-center px-5 gap-4">
      {/* Status */}
      <div className="flex items-center gap-2 ml-auto">
        {state.sessionId && (
          <div className="flex items-center gap-3 mr-3">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground font-mono uppercase tracking-wider">
                Session
              </span>
              <code className="text-xs text-muted-foreground font-mono bg-muted px-1.5 py-0.5 rounded">
                {state.sessionId.slice(0, 16)}{state.sessionId.length > 16 ? "…" : ""}
              </code>
            </div>
            <div className="w-px h-3 bg-border" />
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-muted-foreground font-mono uppercase tracking-wider">
                Version
              </span>
              <code className="text-xs text-cyan-400 font-mono bg-cyan-400/10 px-1.5 py-0.5 rounded border border-cyan-400/20">
                v{state.currentState?.state_version ?? "–"}
              </code>
            </div>
          </div>
        )}
        <div className="flex items-center gap-1.5">
          <div className={cn("w-1.5 h-1.5 rounded-full", statusDot)} />
          <span className={cn("text-xs font-mono capitalize", statusColor)}>
            {state.connectionStatus}
          </span>
        </div>
      </div>
    </header>
  );
}