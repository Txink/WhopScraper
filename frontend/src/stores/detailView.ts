import { create } from "zustand";
import type {
  ViewType,
  IntradaySession,
  MinuteGranularity,
  MultidayWindow,
  DayKGranularity,
} from "../components/Positions/viewConfig";

/** Re-export for callers that previously imported from this module. */
export type { ViewType, IntradaySession as SessionMode, MinuteGranularity, MultidayWindow, DayKGranularity };

/** Ephemeral UI state for the position detail pane:
 *  - which symbol (if any) is open. Symbol — not ticker — because the
 *    same underlying ticker can have many distinct option contracts.
 *  - which 做T pair is highlighted on the chart (stocks only)
 *  - which trades are currently selected for the bind builder
 *  - which chart `view` is showing + per-view sub-config persisted
 *    independently so switching away and back restores the user's choice */
interface DetailViewState {
  selectedSymbol: string | null;
  activePairId: number | null;
  showAllPairs: boolean;

  /** Current chart tab. Maps via viewConfig.ts to (period, granularity, sessions). */
  view: ViewType;
  /** Sub-config for the `intraday` tab — persisted independently. */
  intradaySessions: IntradaySession;
  /** Sub-config for the `minute` tab — persisted independently. */
  minuteGranularity: MinuteGranularity;
  /** Sub-config for the `multiday` tab — persisted independently. */
  multidayWindow: MultidayWindow;
  /** Sub-config for the `dayK` tab group — day/week/month/year share one
   *  visual tab; this is the granularity the popover is set to. */
  dayKGranularity: DayKGranularity;
  /** Sub-config for the `overlay` tab — ET trading-day strings (YYYY-MM-DD)
   *  to overlay on the comparison chart. Capped at 5 by the toggle
   *  helper; insertion order is preserved so each date keeps the same
   *  series color across re-renders. */
  overlayDates: string[];

  selectedBuys: Set<string>;
  selectedSells: Set<string>;

  selectSymbol(symbol: string | null): void;
  setActivePair(id: number | null): void;
  setShowAllPairs(v: boolean): void;
  setView(v: ViewType): void;
  setIntradaySessions(s: IntradaySession): void;
  setMinuteGranularity(g: MinuteGranularity): void;
  setMultidayWindow(w: MultidayWindow): void;
  setDayKGranularity(g: DayKGranularity): void;
  /** Toggle an ET trading-day in/out of overlayDates. No-op if the cap
   *  (5) would be exceeded — UI is expected to disable the affordance
   *  in that state. */
  toggleOverlayDate(date: string): void;
  clearOverlayDates(): void;
  toggleTrade(tradeId: string, side: "BUY" | "SELL"): void;
  clearSelection(): void;

  /** Active tab in the bottom detail-pane container:
   *  0 = trade records, 1 = trading panel, 2 = alerts.
   *  Persists across ticker switches; resets to 0 on selectSymbol(null). */
  tabIndex: 0 | 1 | 2;
  setTabIndex(idx: 0 | 1 | 2): void;
}

/** Max overlay slots — matches the user-visible "最多同时显示5个" cap. */
export const OVERLAY_MAX = 5;

export const useDetailViewStore = create<DetailViewState>((set) => ({
  selectedSymbol: null,
  activePairId: null,
  showAllPairs: false,
  view: "intraday",
  intradaySessions: "regular",
  minuteGranularity: "5min",
  multidayWindow: 5,
  dayKGranularity: "day",
  overlayDates: [],
  selectedBuys: new Set(),
  selectedSells: new Set(),
  tabIndex: 0,

  selectSymbol: (symbol) =>
    set({
      selectedSymbol: symbol,
      activePairId: null,
      selectedBuys: new Set(),
      selectedSells: new Set(),
      tabIndex: 0,
    }),
  setActivePair: (id) => set({ activePairId: id }),
  setShowAllPairs: (v) => set({ showAllPairs: v }),
  setView: (v) => set({ view: v }),
  setIntradaySessions: (s) => set({ intradaySessions: s }),
  setMinuteGranularity: (g) => set({ minuteGranularity: g }),
  setMultidayWindow: (w) => set({ multidayWindow: w }),
  setDayKGranularity: (g) => set({ dayKGranularity: g }),
  toggleOverlayDate: (date) =>
    set((state) => {
      if (state.overlayDates.includes(date)) {
        return { overlayDates: state.overlayDates.filter((d) => d !== date) };
      }
      if (state.overlayDates.length >= OVERLAY_MAX) return state;
      return { overlayDates: [...state.overlayDates, date] };
    }),
  clearOverlayDates: () => set({ overlayDates: [] }),
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
  setTabIndex: (idx) => set({ tabIndex: idx }),
}));
