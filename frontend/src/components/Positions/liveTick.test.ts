import { describe, it, expect } from "vitest";
import { applyLiveTick, bucketKey } from "./liveTick";
import type { Candlestick } from "../../api/domain-types";

const baseBar = (ts: string, c: number): Candlestick => ({
  timestamp: ts,
  open: c, high: c, low: c, close: c, volume: 0, turnover: 0,
});

describe("bucketKey", () => {
  it("1-minute buckets snap on the minute", () => {
    const a = Date.parse("2026-05-15T13:30:15Z");
    const b = Date.parse("2026-05-15T13:30:59Z");
    const c = Date.parse("2026-05-15T13:31:00Z");
    expect(bucketKey(a, 1)).toBe(bucketKey(b, 1));
    expect(bucketKey(c, 1)).toBe(bucketKey(a, 1) + 1);
  });
  it("5-minute buckets snap on :00, :05, :10, …", () => {
    const a = Date.parse("2026-05-15T13:30:00Z");
    const b = Date.parse("2026-05-15T13:34:59Z");
    const c = Date.parse("2026-05-15T13:35:00Z");
    expect(bucketKey(a, 5)).toBe(bucketKey(b, 5));
    expect(bucketKey(c, 5)).toBe(bucketKey(a, 5) + 1);
  });
  it("15-minute buckets snap on :00, :15, :30, :45", () => {
    const a = Date.parse("2026-05-15T13:15:00Z");
    const b = Date.parse("2026-05-15T13:29:59Z");
    const c = Date.parse("2026-05-15T13:30:00Z");
    expect(bucketKey(a, 15)).toBe(bucketKey(b, 15));
    expect(bucketKey(c, 15)).toBe(bucketKey(a, 15) + 1);
  });
});

describe("applyLiveTick — same-bucket in-place updates", () => {
  it("updates close + accumulates high/low within the same 1-min bucket", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const minuteMs = Date.parse("2026-05-15T13:30:00Z");

    let out = applyLiveTick({
      bars, labels, lastDone: 102,
      nowMs: minuteMs + 15_000,
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(false);
    expect(out.bars).toHaveLength(1);
    expect(out.bars[0].close).toBe(102);
    expect(out.bars[0].high).toBe(102);
    expect(out.bars[0].low).toBe(100);

    out = applyLiveTick({
      bars: out.bars, labels: out.labels, lastDone: 98,
      nowMs: minuteMs + 45_000,
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.bars[0].high).toBe(102);
    expect(out.bars[0].low).toBe(98);
    expect(out.bars[0].close).toBe(98);
  });

  it("same logic at 5-min granularity (in-place within the same 5-min bucket)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const out = applyLiveTick({
      bars, labels, lastDone: 105,
      nowMs: Date.parse("2026-05-15T13:34:30Z"),
      periodMinutes: 5, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(false);
    expect(out.bars[0].close).toBe(105);
    expect(out.bars[0].high).toBe(105);
  });
});

describe("applyLiveTick — boundary crossing with allowAppend=true", () => {
  it("appends a new 1-min bar when now is in the next minute", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const out = applyLiveTick({
      bars, labels, lastDone: 103,
      nowMs: Date.parse("2026-05-15T13:31:05Z"),
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(true);
    expect(out.bars).toHaveLength(2);
    expect(out.bars[0]).toEqual(baseBar("2026-05-15T13:30:00Z", 100));
    expect(out.bars[1].timestamp).toBe("2026-05-15T13:31:00.000Z");
    expect(out.bars[1].open).toBe(103);
    expect(out.bars[1].close).toBe(103);
    expect(out.labels).toEqual(["21:30", "21:31"]);
  });

  it("anchors new-bar timestamp to the bucket start (not to nowMs)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    // Now is 13:38:15, periodMinutes=5 → new bucket starts at 13:35.
    const out = applyLiveTick({
      bars, labels, lastDone: 110,
      nowMs: Date.parse("2026-05-15T13:38:15Z"),
      periodMinutes: 5, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(true);
    expect(out.bars[1].timestamp).toBe("2026-05-15T13:35:00.000Z");
  });
});

describe("applyLiveTick — allowAppend=false (5D/7D/15D)", () => {
  it("updates last bar in place when within freshness window (≤ 2 buckets)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    // Last bar is at 13:30, now is 13:34 (same 5-min bucket).
    const sameBucket = applyLiveTick({
      bars, labels, lastDone: 102,
      nowMs: Date.parse("2026-05-15T13:34:00Z"),
      periodMinutes: 5, allowAppend: false,
    });
    expect(sameBucket.crossedBoundary).toBe(false);
    expect(sameBucket.bars[0].close).toBe(102);
    expect(sameBucket.bars).toHaveLength(1);

    // Now is 13:38 → next 5-min bucket. Still within 2-bucket window;
    // update in place (no append) — last bar's close tracks last_done.
    const nextBucket = applyLiveTick({
      bars, labels, lastDone: 104,
      nowMs: Date.parse("2026-05-15T13:38:00Z"),
      periodMinutes: 5, allowAppend: false,
    });
    expect(nextBucket.crossedBoundary).toBe(false);
    expect(nextBucket.bars).toHaveLength(1);
    expect(nextBucket.bars[0].close).toBe(104);
  });

  it("leaves bars unchanged when stale (>2 buckets old)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    // Now is 13:55 — 5 buckets past the last bar's 5-min bucket. 5D view
    // opened in stale state (e.g. session boundary skipped); chart
    // shouldn't paint 13:55 prices on the 13:30 bar.
    const out = applyLiveTick({
      bars, labels, lastDone: 999,
      nowMs: Date.parse("2026-05-15T13:55:00Z"),
      periodMinutes: 5, allowAppend: false,
    });
    expect(out.crossedBoundary).toBe(false);
    expect(out.bars[0].close).toBe(100);   // unchanged
    expect(out.bars).toHaveLength(1);
  });
});

describe("applyLiveTick — guards", () => {
  it("returns input unchanged when bars are empty", () => {
    const out = applyLiveTick({
      bars: [], labels: [],
      lastDone: 50, nowMs: Date.parse("2026-05-15T13:31:05Z"),
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.bars).toEqual([]);
    expect(out.labels).toEqual([]);
    expect(out.crossedBoundary).toBe(false);
  });

  it("does not mutate the input bars/labels arrays", () => {
    const bars: Candlestick[] = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const snapshot = JSON.stringify(bars);
    applyLiveTick({
      bars, labels, lastDone: 105,
      nowMs: Date.parse("2026-05-15T13:30:42Z"),
      periodMinutes: 1, allowAppend: true,
    });
    expect(JSON.stringify(bars)).toBe(snapshot);
    expect(labels).toEqual(["21:30"]);
  });
});
