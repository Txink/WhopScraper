import { create } from "zustand";

export type ConnStatus = "connecting" | "open" | "closed" | "error";

interface ConnState {
  ws: ConnStatus;
  whop: "up" | "down" | "unknown";
  longport: "up" | "down" | "unknown";
  mode: "paper" | "real";
  dryRun: boolean;
  autoTrade: boolean;
  /** True iff broker is a live LongPortClient. False = NoopBrokerClient
   *  fallback (init failed). Null = haven't fetched broker status yet. */
  brokerIsReal: boolean | null;
  brokerInitError: string | null;
  lastEventId: number | null;    // server-issued cursor for WS replay
  setWs(status: ConnStatus): void;
  setHealth(health: { whop: string; longport: string; mode: string; dry_run: boolean }): void;
  setRuntimeSettings(runtime: { mode: "paper" | "real"; dry_run: boolean; auto_trade: boolean }): void;
  setBrokerStatus(status: { is_real: boolean; last_init_error: string | null }): void;
  setLastEventId(id: number): void;
}

export const useConnStore = create<ConnState>((set) => ({
  ws: "closed",
  whop: "unknown",
  longport: "unknown",
  mode: "paper",
  dryRun: true,
  autoTrade: true,
  brokerIsReal: null,
  brokerInitError: null,
  lastEventId: null,
  setWs: (status) => set({ ws: status }),
  setHealth: (h) =>
    set({
      whop: h.whop === "up" ? "up" : "down",
      longport: h.longport === "up" ? "up" : "down",
      mode: h.mode === "real" ? "real" : "paper",
      dryRun: Boolean(h.dry_run),
    }),
  setRuntimeSettings: (runtime) =>
    set({
      mode: runtime.mode,
      dryRun: runtime.dry_run,
      autoTrade: runtime.auto_trade,
    }),
  setBrokerStatus: (status) =>
    set({
      brokerIsReal: status.is_real,
      brokerInitError: status.last_init_error,
    }),
  setLastEventId: (id) => set({ lastEventId: id }),
}));
