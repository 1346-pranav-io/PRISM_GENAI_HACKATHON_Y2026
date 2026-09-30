"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import {
  Zap, Activity, Cpu, BarChart3, Radio, ChevronRight,
} from "lucide-react";

const navItems = [
  { href: "/", label: "Playground", icon: Zap, desc: "Interact with the agent" },
  { href: "/runs", label: "Live Runs", icon: Activity, desc: "Active sessions" },
  { href: "/architecture", label: "Architecture", icon: Cpu, desc: "How it works" },
  { href: "/evaluation", label: "Evaluation", icon: BarChart3, desc: "Verification & metrics" },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="w-56 flex-shrink-0 border-r border-border bg-card/40 flex flex-col">
      {/* Logo */}
      <div className="px-4 py-5 border-b border-border">
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="relative">
            <div className="w-7 h-7 rounded-lg bg-primary/20 border border-primary/40 flex items-center justify-center">
              <Radio className="w-3.5 h-3.5 text-primary" />
            </div>
            <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-emerald-400 animate-pulse-dot" />
          </div>
          <div>
            <div className="text-sm font-semibold text-foreground tracking-tight group-hover:text-primary transition-colors">
              INTERRUPTIBLE
            </div>
            <div className="text-[10px] text-muted-foreground font-mono tracking-widest uppercase">
              AI Runtime
            </div>
          </div>
        </Link>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        <div className="px-2 mb-3">
          <p className="text-[10px] font-mono text-muted-foreground tracking-widest uppercase">
            Navigation
          </p>
        </div>
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-sm transition-all group",
                isActive
                  ? "bg-primary/10 text-primary border border-primary/20"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent",
              )}
            >
              <item.icon className={cn("w-4 h-4 flex-shrink-0", isActive ? "text-primary" : "text-muted-foreground group-hover:text-foreground")} />
              <span className={cn("flex-1", isActive ? "font-medium" : "")}>{item.label}</span>
              {isActive && <ChevronRight className="w-3 h-3 text-primary/60" />}
            </Link>
          );
        })}
      </nav>

      {/* Bottom: version badge */}
      <div className="px-4 py-3 border-t border-border">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-muted-foreground font-mono">v0.1.0</span>
          <div className="flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span className="text-[10px] text-muted-foreground font-mono">Render LIVE</span>
          </div>
        </div>
      </div>
    </aside>
  );
}