import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { socketURL, type Stack } from "./api";

type Logs = Record<string, Record<string, string[]>>;

type Panel = {
  logs: Logs;
  subscribe: (stack: string) => void;
  unsubscribe: (stack: string) => void;
};

const Ctx = createContext<Panel | null>(null);

export function PanelProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [logs, setLogs] = useState<Logs>({});
  const wsRef = useRef<WebSocket | null>(null);
  const subs = useRef(new Set<string>());

  useEffect(() => {
    let stopped = false;
    let socket: WebSocket | null = null;
    let timer = 0;
    const open = () => {
      if (stopped) return;
      socket = new WebSocket(socketURL("/api/ws"));
      wsRef.current = socket;
      socket.onmessage = (ev) => {
        const msg = JSON.parse(ev.data as string) as {
          type: string;
          stacks?: Stack[];
          stack?: string;
          service?: string;
          line?: string;
        };
        if (msg.type === "state" && msg.stacks) {
          qc.setQueryData(["stacks"], msg.stacks);
        }
        if (msg.type === "log" && msg.stack && msg.service && msg.line) {
          const stack = msg.stack;
          const service = msg.service;
          const line = msg.line;
          setLogs((prev) => {
            const bucket = { ...(prev[stack] ?? {}) };
            const lines = [...(bucket[service] ?? []), line].slice(-400);
            bucket[service] = lines;
            return { ...prev, [stack]: bucket };
          });
        }
      };
      socket.onopen = () => {
        for (const stack of subs.current) {
          socket?.send(JSON.stringify({ type: "subscribe", stack }));
        }
      };
      socket.onclose = () => {
        if (!stopped) timer = window.setTimeout(open, 1500);
      };
    };
    open();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      socket?.close();
    };
  }, [qc]);

  const subscribe = useCallback((stack: string) => {
    subs.current.add(stack);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "subscribe", stack }));
    }
  }, []);
  const unsubscribe = useCallback((stack: string) => {
    subs.current.delete(stack);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "unsubscribe", stack }));
    }
  }, []);
  const api = useMemo<Panel>(() => ({ logs, subscribe, unsubscribe }), [logs, subscribe, unsubscribe]);

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function usePanel() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("panel missing");
  return ctx;
}
