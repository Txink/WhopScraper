import { create } from "zustand";
import type { components } from "../api/types";

export type AlertOut = components["schemas"]["AlertOut"];

interface AlertsState {
  /** Alerts indexed by ticker — each ticker holds its own list. */
  byTicker: Record<string, AlertOut[]>;

  /** Replace the full list for a ticker (e.g. on initial load). */
  setAlerts(ticker: string, alerts: AlertOut[]): void;

  /** Upsert a single alert by id. The ticker is read from the alert itself. */
  upsertAlert(alert: AlertOut): void;

  /** Remove an alert by id — searches all tickers. */
  removeAlert(alertId: number): void;
}

export const useAlertsStore = create<AlertsState>((set) => ({
  byTicker: {},

  setAlerts: (ticker, alerts) =>
    set((state) => ({
      byTicker: { ...state.byTicker, [ticker]: alerts },
    })),

  upsertAlert: (alert) =>
    set((state) => {
      const ticker = alert.ticker;
      const existing = state.byTicker[ticker] ?? [];
      const idx = existing.findIndex((a) => a.id === alert.id);
      let next: AlertOut[];
      if (idx >= 0) {
        next = existing.map((a) => (a.id === alert.id ? alert : a));
      } else {
        // Prepend new alert
        next = [alert, ...existing];
      }
      return { byTicker: { ...state.byTicker, [ticker]: next } };
    }),

  removeAlert: (alertId) =>
    set((state) => {
      const next: Record<string, AlertOut[]> = {};
      for (const [ticker, list] of Object.entries(state.byTicker)) {
        next[ticker] = list.filter((a) => a.id !== alertId);
      }
      return { byTicker: next };
    }),
}));
