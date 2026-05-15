import { describe, it, expect, beforeEach } from "vitest";
import { usePairsStore } from "./pairs";
import type { TPair } from "../api/domain-types";

const _pair = (id: number, overrides: Partial<TPair> = {}): TPair => ({
  id,
  ticker: "TSLA",
  symbol: "TSLA.US",
  buys: [{ trade_id: "b1", qty: 100 }],
  sells: [{ trade_id: "s1", qty: 100 }],
  profit: 0,
  created_at: "2026-05-14T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
  ...overrides,
});

describe("pairs store", () => {
  beforeEach(() => {
    usePairsStore.getState().reset();
  });

  it("setPairs replaces the list for that ticker", () => {
    usePairsStore.getState().setPairs("TSLA", [_pair(1), _pair(2)]);
    expect(usePairsStore.getState().byTicker["TSLA"]).toHaveLength(2);
    usePairsStore.getState().setPairs("TSLA", [_pair(3)]);
    expect(usePairsStore.getState().byTicker["TSLA"]?.map((p) => p.id)).toEqual([3]);
  });

  it("upsertPair adds a new pair when id is unseen", () => {
    usePairsStore.getState().setPairs("TSLA", [_pair(1)]);
    usePairsStore.getState().upsertPair("TSLA", _pair(2));
    expect(usePairsStore.getState().byTicker["TSLA"]?.map((p) => p.id)).toEqual([1, 2]);
  });

  it("upsertPair replaces by id when present (used after extend mutation)", () => {
    usePairsStore.getState().setPairs("TSLA", [_pair(1), _pair(2)]);
    const updated = _pair(1, {
      buys: [{ trade_id: "b1", qty: 200 }],
    });
    usePairsStore.getState().upsertPair("TSLA", updated);
    const list = usePairsStore.getState().byTicker["TSLA"]!;
    expect(list).toHaveLength(2);
    expect(list[0]?.buys[0]?.qty).toBe(200);
  });

  it("removePair filters out the given id", () => {
    usePairsStore.getState().setPairs("TSLA", [_pair(1), _pair(2)]);
    usePairsStore.getState().removePair("TSLA", 1);
    expect(usePairsStore.getState().byTicker["TSLA"]?.map((p) => p.id)).toEqual([2]);
  });

  it("removePair on unknown ticker is a no-op (no crash)", () => {
    usePairsStore.getState().removePair("UNKNOWN", 1);
    expect(usePairsStore.getState().byTicker["UNKNOWN"]).toEqual([]);
  });

  it("appendPairs merges by id across pages (no duplicates, page-1 ids preserved)", () => {
    // page 1
    usePairsStore.getState().setPairs("TSLA", [_pair(1), _pair(2)]);
    // page 2 — overlaps on 2, adds 3
    usePairsStore.getState().appendPairs("TSLA", [
      _pair(2, { buys: [{ trade_id: "b1", qty: 999 }] }),
      _pair(3),
    ]);
    const list = usePairsStore.getState().byTicker["TSLA"]!;
    const ids = list.map((p) => p.id);
    expect(new Set(ids)).toEqual(new Set([1, 2, 3]));
    // 2 overwritten by the appended page-2 row.
    expect(list.find((p) => p.id === 2)?.buys[0]?.qty).toBe(999);
  });
});
