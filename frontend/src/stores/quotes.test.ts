import { describe, it, expect, beforeEach } from "vitest";
import { useQuotesStore } from "./quotes";
import type { Quote } from "../api/domain-types";

const _quote = (overrides: Partial<Quote> = {}): Quote => ({
  symbol: "TSLA.US",
  last_done: 250,
  prev_close: 240,
  open: 245,
  high: 252,
  low: 244,
  volume: 100,
  turnover: 25000,
  change: 10,
  change_pct: 4.17,
  trade_session: "regular",
  ...overrides,
});

describe("quotes store", () => {
  beforeEach(() => {
    useQuotesStore.getState().reset();
  });

  it("setQuotes replaces full quote rows", () => {
    useQuotesStore.getState().setQuotes([_quote()]);
    expect(useQuotesStore.getState().quotesBySymbol["TSLA.US"]?.last_done).toBe(250);
  });

  it("upsertQuote merges patch into prior quote and recomputes change", () => {
    // Bootstrap with an HTTP-pulled quote.
    useQuotesStore.getState().setQuotes([_quote()]);
    // Push-style patch: only last_done + session.
    useQuotesStore.getState().upsertQuote("TSLA.US", {
      last_done: 255,
      trade_session: "post",
    });
    const q = useQuotesStore.getState().quotesBySymbol["TSLA.US"]!;
    expect(q.last_done).toBe(255);
    expect(q.trade_session).toBe("post");
    // prev fields preserved.
    expect(q.prev_close).toBe(240);
    expect(q.open).toBe(245);
    // change derived from new last_done.
    expect(q.change).toBeCloseTo(15);
    expect(q.change_pct).toBeCloseTo(6.25, 2);
  });

  it("upsertQuote without a prior entry initializes with the patch", () => {
    useQuotesStore.getState().upsertQuote("NVDA.US", {
      last_done: 100,
      trade_session: "pre",
    });
    const q = useQuotesStore.getState().quotesBySymbol["NVDA.US"]!;
    expect(q.symbol).toBe("NVDA.US");
    expect(q.last_done).toBe(100);
    // prev_close=0 → change stays 0 (no divide-by-zero, no fake percent).
    expect(q.change).toBe(0);
    expect(q.change_pct).toBe(0);
  });
});
