import type { ConnStatus } from "../stores/conn";

export interface WsEvent {
  event_id: number;
  type: string;
  payload: Record<string, unknown>;
}

type StatusListener = (status: ConnStatus) => void;
type EventListener = (evt: WsEvent) => void;

export interface WsClient {
  connect(): void;
  disconnect(): void;
  // Current last-received event_id for replay on reconnect
  getLastEventId(): number | null;
}

export interface WsConfig {
  baseUrl: string;     // e.g. "http://localhost:8000" — translated to ws://
  token: string;
  onEvent: EventListener;
  onStatus?: StatusListener;
  initialSince?: number | null;
  pingIntervalMs?: number;
  maxBackoffMs?: number;
}

export function createWsClient(config: WsConfig): WsClient {
  const {
    baseUrl,
    token,
    onEvent,
    onStatus,
    initialSince = null,
    pingIntervalMs = 25_000,
    maxBackoffMs = 30_000,
  } = config;

  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let pingTimer: ReturnType<typeof setInterval> | null = null;
  let backoffMs = 1_000;
  let lastEventId: number | null = initialSince;
  let explicitlyClosed = false;

  function emitStatus(s: ConnStatus) {
    onStatus?.(s);
  }

  function buildUrl(): string {
    const u = new URL(baseUrl);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/ws";
    u.search = "";
    u.searchParams.set("token", token);
    if (lastEventId !== null) {
      u.searchParams.set("since", String(lastEventId));
    }
    return u.toString();
  }

  function clearTimers() {
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
  }

  function open() {
    emitStatus("connecting");
    const ws = new WebSocket(buildUrl());
    socket = ws;

    ws.onopen = () => {
      emitStatus("open");
      backoffMs = 1_000;   // reset on successful connect
      pingTimer = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, pingIntervalMs);
    };

    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "pong") return;
        if (typeof msg.event_id === "number") {
          lastEventId = msg.event_id;
        }
        onEvent(msg as WsEvent);
      } catch (e) {
        console.warn("ws parse error:", e);
      }
    };

    ws.onerror = () => {
      emitStatus("error");
    };

    ws.onclose = () => {
      clearTimers();
      socket = null;
      if (explicitlyClosed) {
        emitStatus("closed");
        return;
      }
      emitStatus("closed");
      reconnectTimer = setTimeout(() => {
        backoffMs = Math.min(backoffMs * 2, maxBackoffMs);
        open();
      }, backoffMs);
    };
  }

  return {
    connect() {
      explicitlyClosed = false;
      open();
    },
    disconnect() {
      explicitlyClosed = true;
      clearTimers();
      socket?.close();
      socket = null;
    },
    getLastEventId() { return lastEventId; },
  };
}
