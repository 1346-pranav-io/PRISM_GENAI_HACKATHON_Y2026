"use client";
import { useTasks } from "@/lib/store-context";
import { cn, taskStatusBg, taskStatusColor } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ArrowRight } from "lucide-react";

export function TaskList() {
  const tasks = useTasks();
  if (tasks.length === 0) return null;

  return (
    <div className="space-y-1.5">
      {tasks.map((task, i) => {
        const displayName = task.tool_name
          ?? task.task_type.toLowerCase().replace(/_/g, " ");
        const colorClass = taskStatusColor(task.status);
        const bgClass = taskStatusBg(task.status);
        const isTerminal = ["CANCELLED", "STALE", "COMPLETED", "FAILED"].includes(task.status);

        return (
          <div key={task.task_id} className={cn("flex items-center gap-2 px-3 py-2 rounded-lg border text-xs animate-fade-in", bgClass)}>
            {i > 0 && !isTerminal && <ArrowRight className="w-3 h-3 text-foreground/20 flex-shrink-0" />}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className={cn("font-mono font-medium", colorClass)}>{displayName}</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5 flex-shrink-0">
              <code className="text-[10px] text-cyan-400/60 font-mono">v{task.origin_state_version}</code>
              <Badge variant="outline" className="text-[10px] h-4 px-1.5 font-mono border-current/20">
                <span className={cn("font-semibold", colorClass)}>{task.status}</span>
              </Badge>
            </div>
          </div>
        );
      })}
    </div>
  );
}