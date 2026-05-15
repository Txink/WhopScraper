import { create } from "zustand";
import type { LongportSettings } from "../api/domain-types";

export type ConnStatus = "connecting" | "open" | "closed" | "error";

interface ConnState {
  ws: ConnStatus;
  whop: "up" | "down" | "unknown";
  longport: "up" | "down" | "unknown";
  /** Label of the currently active LongBridge account (e.g. "paper" /
   *  "real" / "副账户"). Empty string when no account is active yet. */
  mode: string;
  dryRun: boolean;
  autoTrade: boolean;
  /** True iff broker is a live LongPortClient. False = NoopBrokerClient
   *  fallback (init failed). Null = haven't fetched broker status yet. */
  brokerIsReal: boolean | null;
  brokerInitError: string | null;
  lastEventId: number | null;
  setWs(status: ConnStatus): void;
  setHealth(health: { whop: string; longport: string; account_label?: string; dry_run: boolean }): void;
  setRuntimeSettings(settings: LongportSettings): void;
  setBrokerStatus(status: { is_real: boolean; last_init_error: string | null }): void;
  setLastEventId(id: number): void;
}

export const useConnStore = create<ConnState>((set) => ({
  ws: "closed",
  whop: "unknown",
  longport: "unknown",
  mode: "",
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
      mode: h.account_label ?? "",
      dryRun: Boolean(h.dry_run),
    }),
  setRuntimeSettings: (settings) => {
    const active = settings.accounts.find(
      (a) => a.account_id === settings.active_account_id,
    );
    set({
      mode: active?.label ?? "",
      dryRun: settings.dry_run,
      autoTrade: settings.auto_trade,
    });
  },
  setBrokerStatus: (status) =>
    set({
      brokerIsReal: status.is_real,
      brokerInitError: status.last_init_error,
    }),
  setLastEventId: (id) => set({ lastEventId: id }),
}));
