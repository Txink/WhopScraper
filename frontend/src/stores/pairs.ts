import { create } from "zustand";
import type { TPair } from "../api/domain-types";

/** 做T pair allocations keyed by ticker. Mirrors the backend's t_pairs
 * table — every mutation (create/extend/delete) re-syncs from the server
 * to keep client state authoritative-by-server. */
interface PairsState {
  byTicker: Record<string, TPair[]>;
  /** Set the full list for a ticker (replaces any prior value). */
  setPairs(ticker: string, pairs: TPair[]): void;
  /** Append a page of pairs into the ticker's list, de-duped by id. Used
   *  by the detail pane's "加载更多" affordance — keeps prior pages so
   *  T-1, T-2, ... numbering is stable as the user scrolls. */
  appendPairs(ticker: string, pairs: TPair[]): void;
  /** Add or replace a single pair after a create/extend mutation. */
  upsertPair(ticker: string, pair: TPair): void;
  /** Remove a pair after a successful delete. */
  removePair(ticker: string, pairId: number): void;
  reset(): void;
}

export const usePairsStore = create<PairsState>((set) => ({
  byTicker: {},
  setPairs: (ticker, pairs) =>
    set((state) => ({ byTicker: { ...state.byTicker, [ticker]: pairs } })),
  appendPairs: (ticker, pairs) =>
    set((state) => {
      const prev = state.byTicker[ticker] ?? [];
      const byId = new Map(prev.map((p) => [p.id, p]));
      for (const p of pairs) byId.set(p.id, p);
      return { byTicker: { ...state.byTicker, [ticker]: [...byId.values()] } };
    }),
  upsertPair: (ticker, pair) =>
    set((state) => {
      const list = state.byTicker[ticker] ?? [];
      const idx = list.findIndex((p) => p.id === pair.id);
      const next = idx >= 0
        ? [...list.slice(0, idx), pair, ...list.slice(idx + 1)]
        : [...list, pair];
      return { byTicker: { ...state.byTicker, [ticker]: next } };
    }),
  removePair: (ticker, pairId) =>
    set((state) => {
      const list = state.byTicker[ticker] ?? [];
      return {
        byTicker: { ...state.byTicker, [ticker]: list.filter((p) => p.id !== pairId) },
      };
    }),
  reset: () => set({ byTicker: {} }),
}));
