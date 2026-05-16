import { describe, it, expect } from "vitest";
import { resolveSessionWindow } from "./sessionWindow";

// All test dates are concrete UTC instants. ET = UTC-4 (May → DST).
// HKT = UTC+8 year-round.

function ts(iso: string): number { return Date.parse(iso); }

describe("resolveSessionWindow — US unified day window", () => {
  // The US window is now a single 1440-slot x-axis covering all four
  // sessions (pre / regular / post / overnight) of the active trading
  // day. The `session` prop only affects the `label` field (used for
  // live-state styling); the window shape is identical across sessions.
  it("regular session → window spans ET 04:00 → +24h, 1440 slots", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z")); // 13:00 ET
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(1440);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z"); // 04:00 ET
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });

  it("pre session → same window shape, label changes to 盘前", () => {
    const win = resolveSessionWindow("US", "pre", ts("2026-05-14T10:00:00Z"));
    expect(win.label).toBe("盘前");
    expect(win.slotCount).toBe(1440);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
  });

  it("post session label = 盘后", () => {
    const win = resolveSessionWindow("US", "post", ts("2026-05-14T22:00:00Z"));
    expect(win.label).toBe("盘后");
    expect(win.slotCount).toBe(1440);
  });

  it("overnight at ET 23:00 → trading day = today; window starts today 04:00 ET", () => {
    // 03:00 UTC on 5/15 = 23:00 ET on 5/14 — overnight session.
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T03:00:00Z"));
    expect(win.label).toBe("夜盘");
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });

  it("overnight at ET 02:00 → trading day = YESTERDAY (still overnight tail)", () => {
    // 06:00 UTC on 5/15 = 02:00 ET on 5/15. ET hour < 4 → trading day = 5/14.
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T06:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
  });

  it("closed on weekend → falls back to last weekday's full window", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.label).toBe("休市");
    expect(win.slotCount).toBe(1440);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });

  it("closed on Monday morning BJ → falls back to Friday's window", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-18T02:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });
});

describe("resolveSessionWindow — US regions", () => {
  it("regions cover the four sessions in order", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.regions).toEqual([
      { label: "盘前", startSlot: 0,   endSlot: 330 },
      { label: "盘中", startSlot: 330, endSlot: 720 },
      { label: "盘后", startSlot: 720, endSlot: 960 },
      { label: "夜盘", startSlot: 960, endSlot: 1440 },
    ]);
  });

  it("closed-state US still has all four regions", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.regions).toHaveLength(4);
    expect(win.regions.map((r) => r.label)).toEqual(["盘前", "盘中", "盘后", "夜盘"]);
  });

  it("slot 329 maps to a pre bar (ET 09:29), slot 330 to regular open", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(new Date(win.slotToMs(0)).toISOString()).toBe("2026-05-14T08:00:00.000Z");   // ET 04:00
    expect(new Date(win.slotToMs(329)).toISOString()).toBe("2026-05-14T13:29:00.000Z"); // ET 09:29
    expect(new Date(win.slotToMs(330)).toISOString()).toBe("2026-05-14T13:30:00.000Z"); // ET 09:30
    expect(new Date(win.slotToMs(960)).toISOString()).toBe("2026-05-15T00:00:00.000Z"); // ET 20:00
    expect(new Date(win.slotToMs(1439)).toISOString()).toBe("2026-05-15T07:59:00.000Z"); // ET 03:59
  });
});

describe("resolveSessionWindow — HK", () => {
  // HK Main Board trades 09:30-12:00 + 13:00-16:00 HKT = 5.5h. Lunch
  // (12:00-13:00) is compressed off the x-axis. HKT = UTC+8 year-round.
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

  it("HK has one region (盘中)", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.regions).toEqual([{ label: "盘中", startSlot: 0, endSlot: 330 }]);
  });
});

describe("resolveSessionWindow — CN", () => {
  // CN A-shares trade 09:30-15:00 CST = 4h. Lunch (11:30-13:00, 90 min)
  // compressed off the x-axis. CST = UTC+8 year-round.
  it("regular: 09:30→15:00 CST, 240 slots", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(240);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T01:30:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T07:00:00.000Z");
  });

  it("CN msToSlot rejects bars inside the lunch gap", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T04:00:00Z"))).toBe(-1); // 12:00 CST
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

  it("CN has one region (盘中)", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.regions).toEqual([{ label: "盘中", startSlot: 0, endSlot: 240 }]);
  });
});

describe("resolveSessionWindow — progress", () => {
  it("US: ET 13:00 (= 9h after 04:00 start) → 9/24 = 0.375", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T17:00:00Z"))).toBeCloseTo(9 / 24, 3);
  });

  it("clamps to 0 before start", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T05:00:00Z"))).toBe(0);
  });

  it("clamps to 1 after end", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-16T00:00:00Z"))).toBe(1);
  });

  it("closed always returns 1", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.progress(ts("2026-05-16T10:00:00Z"))).toBe(1);
  });
});

describe("resolveSessionWindow — DST", () => {
  it("US window spans DST start (2026-03-08) correctly — startMs is ET 04:00 EDT", () => {
    // 2026-03-09 (Mon after DST start) → ET = UTC-4
    const win = resolveSessionWindow("US", "regular", ts("2026-03-09T15:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-03-09T08:00:00.000Z");
  });
  it("US window spans DST end (2026-11-01) correctly — startMs is ET 04:00 EST", () => {
    // 2026-11-02 (Mon after DST end) → ET = UTC-5
    const win = resolveSessionWindow("US", "regular", ts("2026-11-02T16:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-11-02T09:00:00.000Z");
  });
});
