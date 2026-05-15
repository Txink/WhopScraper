import { describe, it, expect } from "vitest";
import type { TPair, Trade } from "../../api/domain-types";
import {
  pairTotalBuyQty, pairTotalSellQty,
  pairBuyCost, pairSellRevenue,
  pairAvgBuyPrice, pairAvgSellPrice,
  pairMatchedQty, pairIsPartial, pairRemainder,
  pairProfit, pairProfitPct,
  tradeAllocatedQty, tradeAvailableQty, tradePairsForTrade,
  pairColor,
} from "./pairMath";

const t = (id: string, side: "BUY" | "SELL", qty: number, price: number): Trade => ({
  id, ticker: "TSLA", side, qty, price,
  ts: "2026-05-14T10:00:00Z",
  source: null, tag: null,
});

const pair = (id: number, buys: [string, number][], sells: [string, number][]): TPair => ({
  id, ticker: "TSLA", symbol: "TSLA.US",
  buys: buys.map(([trade_id, qty]) => ({ trade_id, qty })),
  sells: sells.map(([trade_id, qty]) => ({ trade_id, qty })),
  profit: 0,
  created_at: "2026-05-14T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
});

describe("pairMath", () => {
  it("totals sum allocated qty per side", () => {
    const p = pair(1, [["b1", 60], ["b2", 40]], [["s1", 100]]);
    expect(pairTotalBuyQty(p)).toBe(100);
    expect(pairTotalSellQty(p)).toBe(100);
  });

  it("buy cost / sell revenue weight each leg by its trade price", () => {
    const p = pair(1, [["b1", 60], ["b2", 40]], [["s1", 100]]);
    const trades = [
      t("b1", "BUY",  60, 245.0),
      t("b2", "BUY",  40, 246.0),
      t("s1", "SELL", 100, 248.5),
    ];
    expect(pairBuyCost(p, trades)).toBeCloseTo(60 * 245.0 + 40 * 246.0);
    expect(pairSellRevenue(p, trades)).toBeCloseTo(100 * 248.5);
  });

  it("avg prices = cost / qty (and 0 when empty)", () => {
    const p = pair(1, [["b1", 100]], []);
    const trades = [t("b1", "BUY", 100, 200.0)];
    expect(pairAvgBuyPrice(p, trades)).toBeCloseTo(200.0);
    expect(pairAvgSellPrice(p, trades)).toBe(0);
  });

  it("matched qty = min(BUY total, SELL total)", () => {
    const p = pair(1, [["b1", 100]], [["s1", 150]]);
    expect(pairMatchedQty(p)).toBe(100);
  });

  it("partial flag detects qty mismatch", () => {
    expect(pairIsPartial(pair(1, [["b1", 100]], [["s1", 100]]))).toBe(false);
    expect(pairIsPartial(pair(2, [["b1", 100]], [["s1", 60]]))).toBe(true);
  });

  it("remainder identifies which side is over and what's needed", () => {
    expect(pairRemainder(pair(1, [["b1", 100]], [["s1", 60]]))).toEqual({
      side: "BUY", qty: 40, need: "SELL",
    });
    expect(pairRemainder(pair(2, [["b1", 60]], [["s1", 100]]))).toEqual({
      side: "SELL", qty: 40, need: "BUY",
    });
    expect(pairRemainder(pair(3, [["b1", 60]], [["s1", 60]]))).toBeNull();
  });

  it("realized profit uses matched qty × (avgSell - avgBuy)", () => {
    const p = pair(1, [["b1", 100]], [["s1", 100]]);
    const trades = [
      t("b1", "BUY",  100, 100.0),
      t("s1", "SELL", 100, 110.0),
    ];
    expect(pairProfit(p, trades)).toBeCloseTo(1000.0);
    expect(pairProfitPct(p, trades)).toBeCloseTo(10.0);
  });

  it("realized profit is 0 when one side is empty (one-sided pair)", () => {
    const p = pair(1, [["b1", 100]], []);
    const trades = [t("b1", "BUY", 100, 100.0)];
    expect(pairProfit(p, trades)).toBe(0);
    expect(pairProfitPct(p, trades)).toBe(0);
  });

  it("trade allocated qty sums across pairs", () => {
    const p1 = pair(1, [["b1", 40]], []);
    const p2 = pair(2, [["b1", 30]], []);
    expect(tradeAllocatedQty("b1", [p1, p2])).toBe(70);
  });

  it("trade available qty = trade.qty - allocated", () => {
    const p1 = pair(1, [["b1", 40]], []);
    expect(tradeAvailableQty(t("b1", "BUY", 100, 1.0), [p1])).toBe(60);
  });

  it("tradePairsForTrade returns each (pair, qty)", () => {
    const p1 = pair(1, [["b1", 40]], []);
    const p2 = pair(2, [], [["b1", 10]]); // unusual but valid (same trade as SELL)
    const result = tradePairsForTrade("b1", [p1, p2]);
    expect(result.map((r) => [r.pair.id, r.qty])).toEqual([[1, 40], [2, 10]]);
  });

  it("pairColor is stable by index (T-1 always same color)", () => {
    const pairs = [pair(10, [], []), pair(20, [], [])];
    expect(pairColor(10, pairs)).not.toBe(pairColor(20, pairs));
    expect(pairColor(10, pairs)).toBe(pairColor(10, pairs));
  });
});
