"use client";
import { useCorrection, useVersions } from "@/lib/store-context";
import { cn } from "@/lib/utils";
import { ArrowRight, RotateCcw, AlertTriangle } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

export function InterruptionBanner() {
  const delta = useCorrection();
  const versions = useVersions();
  const hasCancellation = versions.some((v) => v.cancelled);

  if (!delta && !hasCancellation) return null;

  return (
    <AnimatePresence>
      {delta && (
        <motion.div
          initial={{ opacity: 0, y: -8, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -8, scale: 0.98 }}
          className="mx-4 mb-3 rounded-xl border border-amber-500/30 bg-amber-500/8 p-3"
        >
          <div className="flex items-start gap-2.5">
            <div className="mt-0.5 flex-shrink-0"> <AlertTriangle className="w-4 h-4 text-amber-400" /> </div>
            <div className="flex-1 min-w-0"> <div className="text-xs font-600 text-amber-300 font-mono uppercase tracking-wider mb-1">
                Interruption Detected
              </div>
              <div className="flex items-center gap-2 text-sm">
                <span className="text-foreground/60 line-through">{delta.from}</span> <ArrowRight className="w-4 h-4 text-amber-400 flex-shrink-0" /> <span className="font-semibold text-foreground">{delta.to}</span>
              </div>
              <div className="mt-1.5 flex items-center gap-1 text-[10px] text-amber-400/60 font-mono"> <RotateCcw className="w-3 h-3" /> Prior work invalidated, state version bumped, replanning...
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}