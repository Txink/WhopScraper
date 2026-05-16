import { describe, it, expect } from "vitest";
import { resolveSessionWindow, effectiveSession } from "./sessionWindow";

// All test dates are concrete UTC instants. ET = UTC-4 (May → DST).
// HKT = UTC+8 year-round.

function ts(iso: string): number { return Date.parse(iso); }

describe("resolveSessionWindow — US 16h day window (no overnight)", () => {
  // The US window spans ET 04:00 (pre open) → ET 20:00 (post close).
  // 夜盘 is excluded by product decision — overnight quote pushes will
  // arrive but neither move the chart nor trigger a live-tip merge.
  it("regular session → ET 04:00 → 20:00, 960 slots", () => {
    // NOW = 2026-05-14T17:00:00Z = 13:00 ET (Thursday). chart day = Thu.
    // Window starts at Thu 04:00 ET = Thu 08:00 UTC.
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(960);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");
  });

  it("pre session → same window shape, label changes to 盘前", () => {
    const win = resolveSessionWindow("US", "pre", ts("2026-05-14T10:00:00Z"));
    expect(win.label).toBe("盘前");
    expect(win.slotCount).toBe(960);
  });

  it("post session label = 盘后, slotCount = 960", () => {
    const win = resolveSessionWindow("US", "post", ts("2026-05-14T22:00:00Z"));
    expect(win.label).toBe("盘后");
    expect(win.slotCount).toBe(960);
  });

  it("overnight at ET 23:00 (Thu) → chart day is still today (Thu)", () => {
    // 03:00 UTC on 5/15 = 23:00 ET on 5/14 (Thu). hour >= 4 → chart
    // day = today (Thu). Window starts at Thu 04:00 ET.
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T03:00:00Z"));
    expect(win.label).toBe("夜盘");
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
  });

  it("overnight at ET 02:00 (Fri morning) → chart day = yesterday (Thu)", () => {
    // 06:00 UTC on 5/15 = 02:00 ET on 5/15 (Fri). hour < 4 → chart day
    // = yesterday (Thu). Window starts at Thu 04:00 ET.
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T06:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
  });

  it("closed on weekend → falls back to last weekday's window", () => {
    // Sat 10:00 UTC. lastTradingDateKey = Friday 2026-05-15.
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.label).toBe("休市");
    expect(win.slotCount).toBe(960);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });

  it("closed on Monday morning BJ → falls back to Friday's window", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-18T02:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });
});

describe("resolveSessionWindow — US regions (3, no 夜盘)", () => {
  it("regions order: 盘前 → 盘中 → 盘后", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.regions).toEqual([
      { label: "盘前", startSlot: 0,   endSlot: 330 },
      { label: "盘中", startSlot: 330, endSlot: 720 },
      { label: "盘后", startSlot: 720, endSlot: 960 },
    ]);
  });

  it("slot 0 → ET 04:00 (pre open), slot 330 → ET 09:30 (regular open)", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(new Date(win.slotToMs(0)).toISOString()).toBe("2026-05-14T08:00:00.000Z");   // 04:00 ET
    expect(new Date(win.slotToMs(330)).toISOString()).toBe("2026-05-14T13:30:00.000Z"); // 09:30 ET
    expect(new Date(win.slotToMs(720)).toISOString()).toBe("2026-05-14T20:00:00.000Z"); // 16:00 ET
    expect(new Date(win.slotToMs(959)).toISOString()).toBe("2026-05-14T23:59:00.000Z"); // 19:59 ET
  });
});

describe("resolveSessionWindow — HK", () => {
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
    expect(win.msToSlot(ts("2026-05-14T04:30:00Z"))).toBe(-1);
  });

  it("HK msToSlot bridges morning ↔ afternoon correctly", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T01:30:00Z"))).toBe(0);
    expect(win.msToSlot(ts("2026-05-14T03:59:00Z"))).toBe(149);
    expect(win.msToSlot(ts("2026-05-14T05:00:00Z"))).toBe(150);
    expect(win.msToSlot(ts("2026-05-14T07:59:00Z"))).toBe(329);
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
  it("regular: 09:30→15:00 CST, 240 slots", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(240);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T01:30:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T07:00:00.000Z");
  });

  it("CN msToSlot rejects bars inside the lunch gap", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T04:00:00Z"))).toBe(-1);
  });

  it("CN msToSlot bridges morning ↔ afternoon correctly", () => {
    const win = resolveSessionWindow("CN", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T01:30:00Z"))).toBe(0);
    expect(win.msToSlot(ts("2026-05-14T03:29:00Z"))).toBe(119);
    expect(win.msToSlot(ts("2026-05-14T05:00:00Z"))).toBe(120);
    expect(win.msToSlot(ts("2026-05-14T06:59:00Z"))).toBe(239);
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
  it("US: ET 13:00 = 9h after 04:00 anchor → 9/16 = 0.5625", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T17:00:00Z"))).toBeCloseTo(9 / 16, 3);
  });

  it("clamps to 0 before start", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T05:00:00Z"))).toBe(0);
  });

  it("clamps to 1 after end", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-15T08:00:00Z"))).toBe(1);
  });

  it("closed always returns 1", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.progress(ts("2026-05-16T10:00:00Z"))).toBe(1);
  });
});

describe("resolveSessionWindow — DST", () => {
  it("US window spans DST start (2026-03-08) correctly", () => {
    // 2026-03-09 (Mon after DST start) → ET = UTC-4
    // Window starts at Mon 04:00 ET = Mon 08:00 UTC
    const win = resolveSessionWindow("US", "regular", ts("2026-03-09T15:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-03-09T08:00:00.000Z");
  });
  it("US window spans DST end (2026-11-01) correctly", () => {
    // 2026-11-02 (Mon after DST end) → ET = UTC-5
    // Window starts at Mon 04:00 ET = Mon 09:00 UTC
    const win = resolveSessionWindow("US", "regular", ts("2026-11-02T16:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-11-02T09:00:00.000Z");
  });
});

describe("effectiveSession — weekend guard", () => {
  it("US Saturday → closed regardless of broker state", () => {
    const sat = ts("2026-05-16T08:00:00Z");
    expect(effectiveSession("US", "pre", sat)).toBe("closed");
    expect(effectiveSession("US", "regular", sat)).toBe("closed");
    expect(effectiveSession("US", "overnight", sat)).toBe("closed");
  });

  it("US Sunday before ET 20:00 → closed", () => {
    expect(effectiveSession("US", "pre", ts("2026-05-17T18:00:00Z"))).toBe("closed");
  });

  it("US Sunday after ET 20:00 → broker state passes through", () => {
    expect(effectiveSession("US", "overnight", ts("2026-05-18T01:00:00Z"))).toBe("overnight");
  });

  it("US weekday → broker state passes through", () => {
    expect(effectiveSession("US", "regular", ts("2026-05-14T17:00:00Z"))).toBe("regular");
    expect(effectiveSession("US", "pre", ts("2026-05-14T10:00:00Z"))).toBe("pre");
  });

  it("HK Saturday → closed", () => {
    expect(effectiveSession("HK", "regular", ts("2026-05-16T04:00:00Z"))).toBe("closed");
  });

  it("HK weekday → broker state passes through", () => {
    expect(effectiveSession("HK", "regular", ts("2026-05-14T02:00:00Z"))).toBe("regular");
  });

  it("brokerSession=closed always returns closed", () => {
    expect(effectiveSession("US", "closed", ts("2026-05-14T17:00:00Z"))).toBe("closed");
  });
});
