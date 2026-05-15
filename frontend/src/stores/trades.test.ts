import { describe, it, expect, beforeEach } from "vitest";
import { useTradesStore } from "./trades";
import type { Trade } from "../api/domain-types";

const _trade = (id: string, overrides: Partial<Trade> = {}): Trade => ({
  id,
  ticker: "TSLA",
  symbol: "TSLA.US",
  side: "BUY",
  qty: 100,
  price: 200,
  ts: "2026-05-14T10:00:00Z",
  source: null,
  tag: null,
  ...overrides,
});

describe("trades store", () => {
  beforeEach(() => {
    useTradesStore.getState().reset();
  });

  it("setTrades replaces the list for that ticker", () => {
    useTradesStore.getState().setTrades("TSLA", [_trade("t1"), _trade("t2")]);
    expect(useTradesStore.getState().byTicker["TSLA"]).toHaveLength(2);
    useTradesStore.getState().setTrades("TSLA", [_trade("t3")]);
    expect(useTradesStore.getState().byTicker["TSLA"]?.map((t) => t.id)).toEqual(["t3"]);
  });

  it("appendTrades merges across pages: prior-page ids stay, duplicates upsert, new ids append", () => {
    // page 1 — newest two
    useTradesStore.getState().setTrades("TSLA", [_trade("t1"), _trade("t2")]);
    // page 2 — overlap on t2 with updated qty, plus a new t3
    useTradesStore.getState().appendTrades("TSLA", [
      _trade("t2", { qty: 300 }),
      _trade("t3"),
    ]);
    const list = useTradesStore.getState().byTicker["TSLA"]!;
    expect(new Set(list.map((t) => t.id))).toEqual(new Set(["t1", "t2", "t3"]));
    expect(list.find((t) => t.id === "t2")?.qty).toBe(300);
  });

  it("appendTrades into an empty ticker initializes the list", () => {
    useTradesStore.getState().appendTrades("AAPL", [_trade("t1", { ticker: "AAPL" })]);
    expect(useTradesStore.getState().byTicker["AAPL"]?.map((t) => t.id)).toEqual(["t1"]);
  });
});
