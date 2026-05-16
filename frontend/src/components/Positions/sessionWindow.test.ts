import { describe, it, expect } from "vitest";
import { resolveSessionWindow, effectiveSession } from "./sessionWindow";

// All test dates are concrete UTC instants. ET = UTC-4 (May → DST).
// HKT = UTC+8 year-round.

function ts(iso: string): number { return Date.parse(iso); }

describe("resolveSessionWindow — US unified day window", () => {
  // The US window is a 1440-slot x-axis spanning ET 20:00 (prev day) →
  // ET 20:00 (chart day), so sessions read 夜盘 → 盘前 → 盘中 → 盘后
  // left-to-right. The `session` prop only affects the `label` field
  // (used for live-state styling); the window shape is identical
  // across sessions.
  it("regular session → window spans Mon 20:00 ET → Tue 20:00 ET, 1440 slots", () => {
    // NOW = 2026-05-14T17:00:00Z = 13:00 ET (Thursday). chart day = Thu.
    // Window starts at Wed 20:00 ET = Thu 00:00 UTC.
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(1440);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T00:00:00.000Z"); // Wed 20:00 ET
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");   // Thu 20:00 ET
  });

  it("pre session → same window shape, label changes to 盘前", () => {
    const win = resolveSessionWindow("US", "pre", ts("2026-05-14T10:00:00Z")); // 06:00 ET
    expect(win.label).toBe("盘前");
    expect(win.slotCount).toBe(1440);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T00:00:00.000Z");
  });

  it("post session label = 盘后", () => {
    const win = resolveSessionWindow("US", "post", ts("2026-05-14T22:00:00Z")); // 18:00 ET
    expect(win.label).toBe("盘后");
    expect(win.slotCount).toBe(1440);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T00:00:00.000Z");
  });

  it("overnight at ET 23:00 (Thu) → chart day = Fri; window starts Thu 20:00 ET", () => {
    // 03:00 UTC on 5/15 = 23:00 ET on 5/14 (Thu). hour >= 20 → chart day
    // is tomorrow = Fri 2026-05-15. Window starts at Thu 20:00 ET.
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T03:00:00Z"));
    expect(win.label).toBe("夜盘");
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T00:00:00.000Z"); // Thu 20:00 ET
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-16T00:00:00.000Z");   // Fri 20:00 ET
  });

  it("overnight at ET 02:00 (Fri morning) → chart day = today (Fri)", () => {
    // 06:00 UTC on 5/15 = 02:00 ET on 5/15 (Fri). hour < 20 → chart day
    // = today (Fri). Window starts at Thu 20:00 ET.
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T06:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");
  });

  it("closed on weekend → falls back to last weekday's window", () => {
    // Sat 10:00 UTC = 06:00 ET. lastTradingDateKey = Friday 2026-05-15.
    // Window = Thu 20:00 ET → Fri 20:00 ET.
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.label).toBe("休市");
    expect(win.slotCount).toBe(1440);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");
  });
});

describe("resolveSessionWindow — US regions (夜盘 first)", () => {
  it("regions order: 夜盘 → 盘前 → 盘中 → 盘后", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.regions).toEqual([
      { label: "夜盘", startSlot: 0,    endSlot: 480 },
      { label: "盘前", startSlot: 480,  endSlot: 810 },
      { label: "盘中", startSlot: 810,  endSlot: 1200 },
      { label: "盘后", startSlot: 1200, endSlot: 1440 },
    ]);
  });

  it("slot 0 → ET 20:00 (start of overnight), slot 810 → ET 09:30 (regular open)", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(new Date(win.slotToMs(0)).toISOString()).toBe("2026-05-14T00:00:00.000Z");   // Wed 20:00 ET
    expect(new Date(win.slotToMs(480)).toISOString()).toBe("2026-05-14T08:00:00.000Z"); // Thu 04:00 ET
    expect(new Date(win.slotToMs(810)).toISOString()).toBe("2026-05-14T13:30:00.000Z"); // Thu 09:30 ET
    expect(new Date(win.slotToMs(1200)).toISOString()).toBe("2026-05-14T20:00:00.000Z"); // Thu 16:00 ET
    expect(new Date(win.slotToMs(1439)).toISOString()).toBe("2026-05-14T23:59:00.000Z");
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
  it("US: ET 13:00 = 17h after Wed 20:00 anchor → 17/24 ≈ 0.708", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T17:00:00Z"))).toBeCloseTo(17 / 24, 3);
  });

  it("clamps to 0 before start", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-13T22:00:00Z"))).toBe(0);
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
  it("US window spans DST start (2026-03-08) correctly", () => {
    // 2026-03-09 (Mon after DST start) → ET = UTC-4
    // Window starts at Sun 20:00 ET = Mon 00:00 UTC
    const win = resolveSessionWindow("US", "regular", ts("2026-03-09T15:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-03-09T00:00:00.000Z");
  });
  it("US window spans DST end (2026-11-01) correctly", () => {
    // 2026-11-02 (Mon after DST end) → ET = UTC-5
    // Window starts at Sun 20:00 ET = Mon 01:00 UTC
    const win = resolveSessionWindow("US", "regular", ts("2026-11-02T16:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-11-02T01:00:00.000Z");
  });
});

describe("effectiveSession — weekend guard", () => {
  // US Saturday 04:00 ET — backend may misreport as "pre" because its
  // cached weekday session windows match the time-of-day. Frontend
  // guard forces this to "closed".
  it("US Saturday → closed regardless of broker state", () => {
    // 2026-05-16T08:00:00Z = Sat 04:00 ET
    const sat = ts("2026-05-16T08:00:00Z");
    expect(effectiveSession("US", "pre", sat)).toBe("closed");
    expect(effectiveSession("US", "regular", sat)).toBe("closed");
    expect(effectiveSession("US", "overnight", sat)).toBe("closed");
  });

  it("US Sunday before ET 20:00 → closed", () => {
    // 2026-05-17T18:00:00Z = Sun 14:00 ET
    expect(effectiveSession("US", "pre", ts("2026-05-17T18:00:00Z"))).toBe("closed");
  });

  it("US Sunday after ET 20:00 → broker state passes through (overnight may be live)", () => {
    // 2026-05-18T01:00:00Z = Sun 21:00 ET
    expect(effectiveSession("US", "overnight", ts("2026-05-18T01:00:00Z"))).toBe("overnight");
  });

  it("US weekday → broker state passes through", () => {
    // 2026-05-14T17:00:00Z = Thu 13:00 ET
    expect(effectiveSession("US", "regular", ts("2026-05-14T17:00:00Z"))).toBe("regular");
    expect(effectiveSession("US", "pre", ts("2026-05-14T10:00:00Z"))).toBe("pre");
  });

  it("HK Saturday → closed", () => {
    // 2026-05-16T04:00:00Z = Sat 12:00 HKT
    expect(effectiveSession("HK", "regular", ts("2026-05-16T04:00:00Z"))).toBe("closed");
  });

  it("HK weekday → broker state passes through", () => {
    // 2026-05-14T02:00:00Z = Thu 10:00 HKT
    expect(effectiveSession("HK", "regular", ts("2026-05-14T02:00:00Z"))).toBe("regular");
  });

  it("brokerSession=closed always returns closed", () => {
    expect(effectiveSession("US", "closed", ts("2026-05-14T17:00:00Z"))).toBe("closed");
  });
});
