import { create } from "zustand";
import type { Candlesticks } from "../api/domain-types";

export type Period = "today" | "5" | "7" | "15" | "30" | "60" | "90";

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
    return `${symbol}::today::${granularity ?? "5min"}::${sessions ?? "regular"}`;
  }
  return `${symbol}::${period}`;
}

interface CandlesticksState {
  byKey: Record<string, Candlesticks>;
  setBars(key: string, bars: Candlesticks): void;
  reset(): void;
}

export const useCandlesticksStore = create<CandlesticksState>((set) => ({
  byKey: {},
  setBars: (key, bars) =>
    set((state) => ({ byKey: { ...state.byKey, [key]: bars } })),
  reset: () => set({ byKey: {} }),
}));
