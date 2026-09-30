"use client";
import { useState, useRef, useCallback, useEffect } from "react";
import { usePlayground } from "@/lib/store-context";
import { initSession, getSessionState } from "@/lib/api";
import { getPlaygroundClient } from "@/lib/websocket";
import { generateSessionId } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Send, Zap, Loader2 } from "lucide-react";

const SUGGESTIONS = [
  "Find me a flight to Mumbai tomorrow",
  "What's the weather in Paris?",
  "Plan a trip to Delhi",
  "Search for flights from London to Tokyo",
  "Book me a morning flight to Singapore",
];

export function ConversationPanel() {
  const { state, dispatch, handleEvent } = usePlayground();
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sessionStarted, setSessionStarted] = useState(false);
  const wsRef = useRef<ReturnType<typeof getPlaygroundClient> | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Start session on mount
  useEffect(() => {
    if (sessionStarted) return;
    startSession();
    return () => { wsRef.current?.disconnect(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startSession() {
    const sessionId = generateSessionId();
    try {
      await initSession(sessionId);
      dispatch({ type: "SET_SESSION", sessionId });
      dispatch({ type: "SET_CONNECTION", status: "connecting" });
      setSessionStarted(true);

      // Connect WebSocket
      const client = getPlaygroundClient(sessionId, (status) => {
        dispatch({ type: "SET_CONNECTION", status: status as typeof state.connectionStatus });
      });
      wsRef.current = client;

      client.subscribe((event) => {
        handleEvent(event);
        // Periodically refresh state from REST
        if (event.event_type === "AGENT_FINAL_RESPONSE" || event.event_type === "FAST_ACK") {
          getSessionState(sessionId).then((s) => dispatch({ type: "SET_STATE", state: s })).catch(() => {});
        }
      });
      client.connect();
    } catch (err) {
      console.error("Failed to start session:", err);
      dispatch({ type: "SET_CONNECTION", status: "error" });
    }
  }

  async function handleSend(text?: string) {
    const msg = text ?? input.trim();
    if (!msg || sending) return;
    setInput("");
    setSending(true);
    try {
      wsRef.current?.send({ text: msg });
    } catch (err) {
      console.error("Send failed:", err);
    } finally {
      setTimeout(() => setSending(false), 500);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Hero / Empty state */}
      {!sessionStarted && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="text-center max-w-sm">
            <div className="w-12 h-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center mx-auto mb-4">
              <Zap className="w-6 h-6 text-primary" />
            </div>
            <h2 className="text-lg font-display font-semibold mb-2">Ready to Interact</h2>
            <p className="text-sm text-muted-foreground">Start a session to begin.</p>
            <Button className="mt-4" onClick={startSession}>Start Session</Button>
          </div>
        </div>
      )}

      {/* Input area */}
      {sessionStarted && (
        <div className="flex-shrink-0 p-4 border-t border-border bg-card/60">
          {/* Suggestions */}
          {!state.events.length && (
            <div className="flex flex-wrap gap-2 mb-3">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSend(s)}
                  className="text-xs font-mono px-3 py-1.5 rounded-lg border border-dashed border-border text-muted-foreground hover:text-foreground hover:border-primary/40 hover:bg-primary/5 transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          )}
          {/* Input row */}
          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask the agent to do something..."
              rows={1}
              className="flex-1 resize-none bg-muted/50 border border-input rounded-lg px-3 py-2.5 text-sm font-mono placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary/50 transition-all"
              style={{ minHeight: "44px", maxHeight: "120px" }}
            />
            <Button
              size="icon"
              onClick={() => handleSend()}
              disabled={!input.trim() || sending}
              className="flex-shrink-0 h-11 w-11"
            >
              {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground font-mono mt-1.5">
            Press Enter to send · Try: &ldquo;Book a flight to Mumbai&rdquo; then interrupt with &ldquo;Actually New York&rdquo;
          </p>
        </div>
      )}
    </div>
  );
}