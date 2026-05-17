import { create } from "zustand";
import type {
  ViewType,
  IntradaySession,
  MinuteGranularity,
  MultidayWindow,
} from "../components/Positions/viewConfig";

/** Re-export for callers that previously imported from this module. */
export type { ViewType, IntradaySession as SessionMode, MinuteGranularity, MultidayWindow };

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

  selectedBuys: Set<string>;
  selectedSells: Set<string>;

  selectSymbol(symbol: string | null): void;
  setActivePair(id: number | null): void;
  setShowAllPairs(v: boolean): void;
  setView(v: ViewType): void;
  setIntradaySessions(s: IntradaySession): void;
  setMinuteGranularity(g: MinuteGranularity): void;
  setMultidayWindow(w: MultidayWindow): void;
  toggleTrade(tradeId: string, side: "BUY" | "SELL"): void;
  clearSelection(): void;
}

export const useDetailViewStore = create<DetailViewState>((set) => ({
  selectedSymbol: null,
  activePairId: null,
  showAllPairs: false,
  view: "intraday",
  intradaySessions: "regular",
  minuteGranularity: "5min",
  multidayWindow: 5,
  selectedBuys: new Set(),
  selectedSells: new Set(),

  selectSymbol: (symbol) =>
    set({
      selectedSymbol: symbol,
      activePairId: null,
      selectedBuys: new Set(),
      selectedSells: new Set(),
    }),
  setActivePair: (id) => set({ activePairId: id }),
  setShowAllPairs: (v) => set({ showAllPairs: v }),
  setView: (v) => set({ view: v }),
  setIntradaySessions: (s) => set({ intradaySessions: s }),
  setMinuteGranularity: (g) => set({ minuteGranularity: g }),
  setMultidayWindow: (w) => set({ multidayWindow: w }),
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
