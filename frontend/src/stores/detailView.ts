import { create } from "zustand";
import type { Period } from "./candlesticks";

/** 分时 = 1-min line with session-padded x-axis (LongBridge "分时" UX).
 *  1min = same SDK data but rendered as a regular K-line slice (no padding). */
export type TodayGranularity = "分时" | "1min" | "2min" | "3min" | "5min";

/** Session filter:
 *  - regular: 9:30-16:00 ET
 *  - pre:     4:00-9:30 ET
 *  - post:    16:00-20:00 ET
 *  - overnight: 20:00-04:00 ET (typically empty for US equities)
 *  - all:     pre + regular + post stitched
 *
 *  Sub-session filters (pre/post/overnight) only apply when granularity = 分时
 *  — for K-line granularities (2/3/5min) the UI restricts choices to
 *  regular | all.
 */
export type SessionMode = "regular" | "pre" | "post" | "overnight" | "all";

/** Ephemeral UI state for the position detail pane:
 *  - which symbol (if any) is open. Symbol — not ticker — because the
 *    same underlying ticker can have many distinct option contracts
 *    (e.g. HOOD stock + HOOD260618C100000 option). Symbol uniquely
 *    identifies the card the user clicked.
 *  - which做T pair is highlighted on the chart (stocks only)
 *  - which trades are currently selected for the bind builder
 *  - chart period switch + today's intraday sub-options */
interface DetailViewState {
  selectedSymbol: string | null;
  activePairId: number | null;
  showAllPairs: boolean;
  period: Period;
  /** Today-only: bar granularity. Persisted across period switches so it
   *  sticks when the user toggles away and back. */
  todayGranularity: TodayGranularity;
  /** Today-only: regular session vs include pre-market & post-market. */
  todaySessions: SessionMode;
  selectedBuys: Set<string>;
  selectedSells: Set<string>;

  selectSymbol(symbol: string | null): void;
  setActivePair(id: number | null): void;
  setShowAllPairs(v: boolean): void;
  setPeriod(p: Period): void;
  setTodayGranularity(g: TodayGranularity): void;
  setTodaySessions(s: SessionMode): void;
  toggleTrade(tradeId: string, side: "BUY" | "SELL"): void;
  clearSelection(): void;
}

export const useDetailViewStore = create<DetailViewState>((set) => ({
  selectedSymbol: null,
  activePairId: null,
  showAllPairs: false,
  period: "today",
  todayGranularity: "5min",
  todaySessions: "regular",
  selectedBuys: new Set(),
  selectedSells: new Set(),

  selectSymbol: (symbol) =>
    set({
      selectedSymbol: symbol,
      // Reset transient view state when switching positions.
      activePairId: null,
      selectedBuys: new Set(),
      selectedSells: new Set(),
    }),
  setActivePair: (id) => set({ activePairId: id }),
  setShowAllPairs: (v) => set({ showAllPairs: v }),
  setPeriod: (p) => set({ period: p }),
  setTodayGranularity: (g) =>
    set((state) => {
      // K-line granularities (2/3/5min) only support 盘中. Switching from
      // 分时 → K-line therefore always snaps the session back to "regular".
      if (g !== "分时" && state.todaySessions !== "regular") {
        return { todayGranularity: g, todaySessions: "regular" };
      }
      return { todayGranularity: g };
    }),
  setTodaySessions: (s) => set({ todaySessions: s }),
  toggleTrade: (tradeId, side) =>
    set((state) => {
      if (side === "BUY") {
        const next = new Set(state.selectedBuys);
        if (next.has(tradeId)) next.delete(tradeId);
        else next.add(tradeId);
        return { selectedBuys: next };
      } else {
        const next = new Set(state.selectedSells);
        if (next.has(tradeId)) next.delete(tradeId);
        else next.add(tradeId);
        return { selectedSells: next };
      }
    }),
  clearSelection: () =>
    set({ selectedBuys: new Set(), selectedSells: new Set() }),
}));
