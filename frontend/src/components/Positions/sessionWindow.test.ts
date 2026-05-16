import { describe, it, expect } from "vitest";
import { resolveSessionWindow } from "./sessionWindow";

// All test dates are concrete UTC instants. ET = UTC-4 (May → DST).
// HKT = UTC+8 year-round.

function ts(iso: string): number { return Date.parse(iso); }

describe("resolveSessionWindow — US", () => {
  it("regular: 09:30→16:00 ET = 13:30→20:00 UTC, 390 slots", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z")); // 13:00 ET
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(390);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T13:30:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T20:00:00.000Z");
  });

  it("pre: 04:00→09:30 ET, 330 slots", () => {
    const win = resolveSessionWindow("US", "pre", ts("2026-05-14T10:00:00Z"));
    expect(win.label).toBe("盘前");
    expect(win.slotCount).toBe(330);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T13:30:00.000Z");
  });

  it("post: 16:00→20:00 ET, 240 slots", () => {
    const win = resolveSessionWindow("US", "post", ts("2026-05-14T22:00:00Z"));
    expect(win.label).toBe("盘后");
    expect(win.slotCount).toBe(240);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T20:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");
  });

  it("overnight: 20:00→04:00 ET (+1d), 480 slots", () => {
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T03:00:00Z"));
    expect(win.label).toBe("夜盘");
    expect(win.slotCount).toBe(480);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });

  it("closed on weekend → falls back to last weekday's post", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.label).toBe("休市");
    expect(win.slotCount).toBe(240);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T20:00:00.000Z");
  });

  it("closed on Monday morning BJ → falls back to Friday post", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-18T02:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T20:00:00.000Z");
  });
});

describe("resolveSessionWindow — HK", () => {
  // HK Main Board trades 09:30-12:00 + 13:00-16:00 HKT = 5.5h.
  // Lunch is compressed off the x-axis: 150 morning slots + 180 afternoon
  // slots = 330 total.
  it("regular: 09:30→16:00 HKT with lunch compressed, 330 slots", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(330);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T01:30:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
  });

  it("HK slot 0 → 09:30 HKT, slot 149 → 11:59 HKT", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(new Date(win.slotToMs(0)).toISOString()).toBe("2026-05-14T01:30:00.000Z");
    expect(new Date(win.slotToMs(149)).toISOString()).toBe("2026-05-14T03:59:00.000Z");
  });

  it("HK slot 150 → 13:00 HKT (lunch skipped)", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(new Date(win.slotToMs(150)).toISOString()).toBe("2026-05-14T05:00:00.000Z");
  });

  it("HK msToSlot rejects bars inside the lunch gap", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T04:30:00Z"))).toBe(-1); // 12:30 HKT
  });

  it("HK msToSlot bridges morning ↔ afternoon correctly", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T01:30:00Z"))).toBe(0);   // 09:30 HKT
    expect(win.msToSlot(ts("2026-05-14T03:59:00Z"))).toBe(149); // 11:59 HKT
    expect(win.msToSlot(ts("2026-05-14T05:00:00Z"))).toBe(150); // 13:00 HKT
    expect(win.msToSlot(ts("2026-05-14T07:59:00Z"))).toBe(329); // 15:59 HKT
  });

  it("HK closed on Saturday → falls back to Friday regular", () => {
    const win = resolveSessionWindow("HK", "closed", ts("2026-05-16T02:00:00Z"));
    expect(win.label).toBe("休市");
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T01:30:00.000Z");
  });
});

describe("resolveSessionWindow — CN", () => {
  // CN A-shares trade 09:30-11:30 + 13:00-15:00 CST = 4h. Lunch
  // (11:30-13:00) is compressed off the x-axis. CST = UTC+8 year-round.
  it("regular: 09:30→15:00 CST, 240 slots", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z")); // 10:00 CST
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(240);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T01:30:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T07:00:00.000Z");
  });

  it("CN msToSlot rejects bars inside the lunch gap", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T04:00:00Z"))).toBe(-1); // 12:00 CST (lunch)
  });

  it("CN msToSlot bridges morning ↔ afternoon correctly", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T01:30:00Z"))).toBe(0);   // 09:30 CST
    expect(win.msToSlot(ts("2026-05-14T03:29:00Z"))).toBe(119); // 11:29 CST
    expect(win.msToSlot(ts("2026-05-14T05:00:00Z"))).toBe(120); // 13:00 CST
    expect(win.msToSlot(ts("2026-05-14T06:59:00Z"))).toBe(239); // 14:59 CST
  });

  it("CN closed on Saturday → falls back to Friday regular", () => {
    const win = resolveSessionWindow("CN", "closed", ts("2026-05-16T02:00:00Z"));
    expect(win.label).toBe("休市");
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T01:30:00.000Z");
  });
});

describe("resolveSessionWindow — progress", () => {
  it("US regular: ET 13:00 (3.5h in) → 3.5/6.5 ≈ 0.538", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T17:00:00Z"))).toBeCloseTo(3.5 / 6.5, 3);
  });

  it("clamps to 0 before start", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T12:00:00Z"))).toBe(0);
  });

  it("clamps to 1 after end", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T22:00:00Z"))).toBe(1);
  });

  it("closed always returns 1", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.progress(ts("2026-05-16T10:00:00Z"))).toBe(1);
  });
});

describe("resolveSessionWindow — DST", () => {
  it("US regular spans DST start (2026-03-08) correctly", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-03-09T15:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-03-09T13:30:00.000Z");
  });
  it("US regular spans DST end (2026-11-01) correctly", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-11-02T16:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-11-02T14:30:00.000Z");
  });
});
