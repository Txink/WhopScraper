import { describe, it, expect, beforeEach } from "vitest";
import { useDetailViewStore } from "./detailView";

describe("detailView store", () => {
  beforeEach(() => {
    useDetailViewStore.setState({
      selectedSymbol: null,
      activePairId: null,
      showAllPairs: false,
      view: "intraday",
      intradaySessions: "regular",
      minuteGranularity: "5min",
      multidayWindow: 5,
      selectedBuys: new Set(),
      selectedSells: new Set(),
    });
  });

  it("selectSymbol stores the value", () => {
    useDetailViewStore.getState().selectSymbol("TSLA.US");
    expect(useDetailViewStore.getState().selectedSymbol).toBe("TSLA.US");
  });

  it("selectSymbol resets transient state (active pair + selection)", () => {
    useDetailViewStore.setState({
      activePairId: 1,
      selectedBuys: new Set(["b1", "b2"]),
      selectedSells: new Set(["s1"]),
    });
    useDetailViewStore.getState().selectSymbol("NVDA.US");
    const s = useDetailViewStore.getState();
    expect(s.activePairId).toBeNull();
    expect(s.selectedBuys.size).toBe(0);
    expect(s.selectedSells.size).toBe(0);
  });

  it("setView switches the discriminator", () => {
    useDetailViewStore.getState().setView("day");
    expect(useDetailViewStore.getState().view).toBe("day");
  });

  it("per-view sub-state persists across view switches", () => {
    const s = useDetailViewStore.getState();
    s.setIntradaySessions("post");
    s.setMinuteGranularity("2min");
    s.setMultidayWindow(7);
    s.setView("week");
    s.setView("intraday");
    expect(useDetailViewStore.getState().intradaySessions).toBe("post");
    expect(useDetailViewStore.getState().minuteGranularity).toBe("2min");
    expect(useDetailViewStore.getState().multidayWindow).toBe(7);
  });

  it("toggleTrade adds and removes from the correct side", () => {
    const { toggleTrade } = useDetailViewStore.getState();
    toggleTrade("t1", "BUY");
    expect(useDetailViewStore.getState().selectedBuys.has("t1")).toBe(true);
    toggleTrade("t1", "BUY");
    expect(useDetailViewStore.getState().selectedBuys.has("t1")).toBe(false);

    toggleTrade("t2", "SELL");
    expect(useDetailViewStore.getState().selectedSells.has("t2")).toBe(true);
  });

  it("clearSelection empties both buy/sell sets", () => {
    useDetailViewStore.setState({
      selectedBuys: new Set(["b1"]),
      selectedSells: new Set(["s1"]),
    });
    useDetailViewStore.getState().clearSelection();
    expect(useDetailViewStore.getState().selectedBuys.size).toBe(0);
    expect(useDetailViewStore.getState().selectedSells.size).toBe(0);
  });
});
