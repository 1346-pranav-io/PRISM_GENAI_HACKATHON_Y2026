"use client";
import { usePlayground } from "@/lib/store-context";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Database, Cpu, GitBranch, Activity } from "lucide-react";
import { TaskList } from "./task-list";
import { VersionTimeline } from "./version-timeline";
import { EventStream } from "./event-stream";

export function RuntimePanel() {
  const { state } = usePlayground();
  const { currentState, tasks } = state;
  const tabs = [
    { value: "state", label: "State", icon: Database },
    { value: "tasks", label: "Tasks", icon: Cpu },
    { value: "versions", label: "Versions", icon: GitBranch },
    { value: "events", label: "Events", icon: Activity },
  ] as const;

  return (
    <div className="w-80 flex-shrink-0 border-l border-border flex flex-col bg-card/20 overflow-hidden">
      <Tabs defaultValue="state" className="flex flex-col h-full">
        <TabsList className="w-full justify-start rounded-none border-b border-border bg-transparent p-0 h-auto">
          {tabs.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}
              className="flex items-center gap-1.5 px-3 py-2.5 text-xs font-mono text-muted-foreground border-b-2 border-transparent data-[state=active]:text-foreground data-[state=active]:border-primary rounded-none -mb-px transition-all">
              <tab.icon className="w-3 h-3" />
              {tab.label}
              {tab.value === "tasks" && tasks.length > 0 && <span className="ml-1 text-[10px] bg-primary/20 text-primary rounded-full px-1">{tasks.length}</span>}
              {tab.value === "events" && state.events.length > 0 && <span className="ml-1 text-[10px] bg-muted rounded-full px-1">{state.events.length}</span>}
            </TabsTrigger>
          ))}
        </TabsList>

        <ScrollArea className="flex-1">
          <TabsContent value="state" className="mt-0 p-4 animate-fade-in space-y-4">
            <div>
              <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest mb-1.5">State Version</p>
              <code className="text-2xl font-mono font-bold text-cyan-400">v{currentState?.state_version ?? "–"}</code>
            </div>
            <div>
              <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest mb-1.5">Intent</p>
              <code className="text-xs font-mono text-foreground bg-muted px-2 py-1 rounded block">
                {currentState?.current_intent ?? <span className="text-muted-foreground italic">None</span>}
              </code>
            </div>
            <div>
              <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest mb-1.5">Slots</p>
              {currentState?.slots && Object.keys(currentState.slots).length > 0 ? (
                <div className="space-y-1">{Object.entries(currentState.slots).map(([k, slot]) => (
                  <div key={k} className="flex justify-between bg-muted/50 rounded px-2 py-1 text-xs">
                    <span className="text-muted-foreground font-mono">{k}</span>
                    <span className="font-mono">{String(slot && typeof slot === "object" && "value" in slot ? slot.value : slot)}</span>
                  </div>
                ))}</div>
              ) : <p className="text-xs text-muted-foreground italic font-mono">No slots populated</p>}
            </div>
            {state.isProcessing && (
              <div className="flex items-center gap-2 text-xs text-yellow-400 font-mono">
                <div className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />Processing...
              </div>
            )}
            {state.sessionId && (
              <div className="pt-3 border-t border-border">
                <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest mb-1">Session</p>
                <code className="text-[10px] font-mono text-muted-foreground break-all">{state.sessionId}</code>
              </div>
            )}
          </TabsContent>

          <TabsContent value="tasks" className="mt-0 p-4 animate-fade-in">
            <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest mb-3">Active Execution ({tasks.length})</p>
            {tasks.length === 0 ? (
              <p className="text-xs text-muted-foreground font-mono text-center py-8">No tasks yet. Start a conversation.</p>
            ) : <TaskList />}
          </TabsContent>

          <TabsContent value="versions" className="mt-0 p-4 animate-fade-in">
            <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest mb-3">Version Timeline</p>
            <VersionTimeline />
          </TabsContent>

          <TabsContent value="events" className="mt-0 p-0 animate-fade-in">
            <p className="text-[10px] font-mono text-muted-foreground uppercase tracking-widest px-4 pt-3 mb-1">Event Stream ({state.events.length})</p>
            <EventStream />
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  );
}