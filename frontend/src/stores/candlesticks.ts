import { create } from "zustand";
import type { Candlesticks } from "../api/domain-types";

/** Backend-facing period enum. See viewConfig.ts for the higher-level
 *  ViewType discriminator that maps onto this. */
export type Period = "today" | "5" | "7" | "30" | "day" | "week" | "month" | "year";

/** Cache key shape — for `today` it includes the granularity + sessions
 * sub-options so toggling those triggers a fresh fetch instead of reusing
 * stale bars. For other periods it's just symbol::period. */
export function candleCacheKey(
  symbol: string,
  period: Period,
  granularity?: string,
  sessions?: string,
): string {
  if (period === "today") {
    return `${symbol}::today::${granularity ?? "分时"}::${sessions ?? "regular"}`;
  }
  return `${symbol}::${period}`;
}

interface CandlesticksState {
  byKey: Record<string, Candlesticks>;
  setBars(key: string, bars: Candlesticks): void;
  /** Prepend older bars to the front of a key's loaded array — used by
   *  the detail-pane pan-back flow when the user scrolls past the
   *  oldest loaded bar. Skips any incoming bar whose timestamp already
   *  exists locally so the prefix stays unique. */
  prependBars(key: string, older: Candlesticks): void;
  reset(): void;
}

export const useCandlesticksStore = create<CandlesticksState>((set) => ({
  byKey: {},
  setBars: (key, bars) =>
    set((state) => ({ byKey: { ...state.byKey, [key]: bars } })),
  prependBars: (key, older) =>
    set((state) => {
      const cur = state.byKey[key];
      if (!cur || older.bars.length === 0) return state;
      const knownTs = new Set(
        cur.bars.map((b) => b.timestamp).filter((t): t is string => !!t),
      );
      const dedup = older.bars.filter(
        (b) => !b.timestamp || !knownTs.has(b.timestamp),
      );
      if (dedup.length === 0) return state;
      return {
        byKey: {
          ...state.byKey,
          [key]: { ...cur, bars: [...dedup, ...cur.bars] },
        },
      };
    }),
  reset: () => set({ byKey: {} }),
}));
