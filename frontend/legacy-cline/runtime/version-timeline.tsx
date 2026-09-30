"use client";
import { useVersions } from "@/lib/store-context";
import { cn } from "@/lib/utils";
import { CheckCircle2, XCircle, Clock, RotateCcw } from "lucide-react";

export function VersionTimeline() {
  const versions = useVersions();
  if (versions.length === 0) return null;

  return (
    <div className="space-y-0">
      {versions.map((v, idx) => {
        const prev = versions[idx - 1];
        const hasJump = prev ? v.version > prev.version + 1 : false;

        return (
          <div key={v.version} className="relative">
            {/* Connector line */}
            {idx > 0 && (
              <div className={cn(
                "absolute left-4 top-0 w-px h-3 -translate-y-px",
                v.cancelled ? "bg-orange-500/50" : hasJump ? "bg-cyan-500/50" : "bg-muted",
              )} />
            )}

            <div className="flex items-start gap-3 py-2 animate-fade-in">
              {/* Version badge */}
              <div className={cn(
                "relative flex-shrink-0 w-8 h-8 rounded-ful rounded-full flex items-center justify-center text-xs font-mono font-bold border",
                v.isCurrent ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-400 shadow-0 shadow-cyan-400/20" : "bg-muted border-border text-foreground/50",
              )}>
                {v.isCurrent ? "✓" : `v${v.version}`}
              </div>

              {/* Content */}
              <div className={cn(
                "flex-1 min-w-0 p-2 rounded-lg border", v.isCurrent ? "bg-cyan-400/5 border-cyan-400/20" : "bg-card border-border",
              )}>
                {/* User text or label */}
                <p className="text-xs text-foreground/60 font-italic">
                  {v.userText ?? (v.cancelled ? "Cancelled work" : "No input")}
                </p>

                {/* Tasks summary */}
                {v.tasks.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1"> {v.tasks.map((task) => {
                    const statusIcon = task.status === "CANCELLED" || task.status === "STALE" ? <XCircle className="w-3 h-3 text-orange-400" />
                      : task.status === "COMPLETED" ? <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                      : <Clock className="w-3 h-3 text-yellow-400" />; return (
                      <div key={task.task_id} className="flex items-center gap-1 bg-muted/60 rounded px-1.5 py-0.5 text-[10px] font-mono">
                        {statusIcon} {task.tool_name ?? task.task_type.toLowerCase().replace(/_/g, " ")}
                      </div>
                    );
                  })}
                  </div>
                )}

                {v.cancelled && (
                  <div className="mt-1 flex items-center gap-1 text-[10px] text-orange-400 font-mono">
                    <RotateCcw className="w-3 h-3" /> invalidated & replanned
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}