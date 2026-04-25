import { create } from "zustand";

export type ConnStatus = "connecting" | "open" | "closed" | "error";

interface ConnState {
  ws: ConnStatus;
  whop: "up" | "down" | "unknown";
  longport: "up" | "down" | "unknown";
  mode: "paper" | "real";
  dryRun: boolean;
  lastEventId: number | null;    // server-issued cursor for WS replay
  setWs(status: ConnStatus): void;
  setHealth(health: { whop: string; longport: string; mode: string; dry_run: boolean }): void;
  setLastEventId(id: number): void;
}

export const useConnStore = create<ConnState>((set) => ({
  ws: "closed",
  whop: "unknown",
  longport: "unknown",
  mode: "paper",
  dryRun: true,
  lastEventId: null,
  setWs: (status) => set({ ws: status }),
  setHealth: (h) =>
    set({
      whop: h.whop === "up" ? "up" : "down",
      longport: h.longport === "up" ? "up" : "down",
      mode: h.mode === "real" ? "real" : "paper",
      dryRun: Boolean(h.dry_run),
    }),
  setLastEventId: (id) => set({ lastEventId: id }),
}));
