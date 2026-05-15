import { create } from "zustand";
import type { Quote } from "../api/domain-types";

/** Per-symbol latest quote snapshot. Keyed by broker-canonical symbol
 * (e.g. "TSLA.US"), refreshed periodically by the dashboard polling loop. */
interface QuotesState {
  quotesBySymbol: Record<string, Quote>;
  lastUpdatedAt: number | null;
  setQuotes(quotes: Quote[]): void;
  /** Apply a single quote-push update. The streaming payload carries
   *  a subset of fields (no change / change_pct — those are derived);
   *  we merge into any prior entry so derived fields aren't lost. */
  upsertQuote(symbol: string, patch: Partial<Quote>): void;
  reset(): void;
}

export const useQuotesStore = create<QuotesState>((set) => ({
  quotesBySymbol: {},
  lastUpdatedAt: null,
  setQuotes: (quotes) =>
    set((state) => {
      const next = { ...state.quotesBySymbol };
      for (const q of quotes) next[q.symbol] = q;
      return { quotesBySymbol: next, lastUpdatedAt: Date.now() };
    }),
  upsertQuote: (symbol, patch) =>
    set((state) => {
      const prev = state.quotesBySymbol[symbol];
      // Merge patch onto prev. ``change`` / ``change_pct`` are computed
      // by the backend per session (盘前/盘中 vs yesterday's close,
      // 盘后/夜盘 vs today's close) — the patch carries them directly
      // so the frontend just stores what arrived. If the backend
      // didn't send change in this patch (legacy paths / tests),
      // fall back to deriving from last_done vs prev_close.
      const merged: Quote = {
        ...(prev ?? {
          symbol,
          last_done: 0,
          prev_close: 0,
          today_close: null,
          open: 0,
          high: 0,
          low: 0,
          volume: 0,
          turnover: 0,
          change: 0,
          change_pct: 0,
          trade_session: "regular",
        }),
        ...patch,
        symbol,
      } as Quote;
      const hasChangeFields =
        "change" in (patch ?? {}) || "change_pct" in (patch ?? {});
      if (!hasChangeFields && merged.prev_close > 0) {
        merged.change = merged.last_done - merged.prev_close;
        merged.change_pct = (merged.change / merged.prev_close) * 100;
      }
      return {
        quotesBySymbol: { ...state.quotesBySymbol, [symbol]: merged },
        lastUpdatedAt: Date.now(),
      };
    }),
  reset: () => set({ quotesBySymbol: {}, lastUpdatedAt: null }),
}));
