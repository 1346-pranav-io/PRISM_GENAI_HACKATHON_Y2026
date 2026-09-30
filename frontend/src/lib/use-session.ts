"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { WebSocketClient } from "./websocket";
import { getWebSocketUrl } from "./api";
import type { RuntimeEvent } from "./types";

export type ConnStatus = "connecting" | "connected" | "disconnected" | "error";

export function newSessionId() {
  return `demo_${Math.random().toString(36).slice(2, 10)}`;
}

/** Live session against the real backend. Every event comes off the WebSocket. */
export function useSession() {
  const [sessionId, setSessionId] = useState<string>("");
  const [status, setStatus] = useState<ConnStatus>("disconnected");
  const [events, setEvents] = useState<RuntimeEvent[]>([]);
  const clientRef = useRef<WebSocketClient | null>(null);

  const connect = useCallback(
    (sid: string) => {
      clientRef.current?.disconnect();
      setEvents([]);
      setSessionId(sid);
      const c = new WebSocketClient(getWebSocketUrl(sid), (s) => setStatus(s as ConnStatus));
      c.subscribe((e) => {
        setEvents((prev) => [...prev, e]);
      });
      clientRef.current = c;
      c.connect();
    },
    [],
  );

  useEffect(() => {
    connect(newSessionId());
    return () => clientRef.current?.disconnect();
  }, [connect]);

  const send = useCallback((...texts: string[]) => {
    // Back-to-back sends on the same socket; no artificial delay.
    texts.forEach((t) => clientRef.current?.send({ type: "user_text", text: t }));
  }, []);

  const reset = useCallback(() => connect(newSessionId()), [connect]);

  return { sessionId, status, events, send, reset };
}
