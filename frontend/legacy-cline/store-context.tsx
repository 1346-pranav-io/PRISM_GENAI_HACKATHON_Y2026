"use client";
import React, { createContext, useContext, useReducer, useCallback, useRef } from "react";
import { reducer, initialState, type PlaygroundState, type Action } from "./store-types";
import { processEvent } from "./store-logic";

interface PlaygroundContextValue {
  state: PlaygroundState;
  dispatch: React.Dispatch<Action>;
  handleEvent: (event: import("./types").RuntimeEvent) => void;
}

const PlaygroundContext = createContext<PlaygroundContextValue | null>(null);

export function PlaygroundProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const eventsRef = useRef(state.events);
  eventsRef.current = state.events;

  const handleEvent = useCallback((event: import("./types").RuntimeEvent) => {
    eventsRef.current = [...eventsRef.current, event];
    const { allEvents, tasks, versions, delta } = processEvent(eventsRef.current, event);
    dispatch({ type: "ADD_EVENT", event });
    dispatch({ type: "SET_TASKS", tasks });
    for (const v of versions) dispatch({ type: "SNAPSHOT_VERSION", snapshot: v });
    dispatch({ type: "SET_CORRECTION", delta });
    if (event.event_type === "FAST_ACK") dispatch({ type: "SET_PROCESSING", isProcessing: true });
    if (event.event_type === "AGENT_FINAL_RESPONSE") {
      dispatch({ type: "SET_PROCESSING", isProcessing: false });
      dispatch({ type: "SET_LAST_RESPONSE", text: (event.payload?.text as string) ?? event.text ?? null });
    }
  }, []);

  return (
    <PlaygroundContext.Provider value={{ state, dispatch, handleEvent }}>
      {children}
    </PlaygroundContext.Provider>
  );
}

export function usePlayground() {
  const ctx = useContext(PlaygroundContext);
  if (!ctx) throw new Error("usePlayground must be used within PlaygroundProvider");
  return ctx;
}