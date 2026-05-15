import { describe, it, expect } from "vitest";
import {
  fmtBjHM,
  fmtBjDate,
  fmtBjRel,
  classifyETSession,
  tradingDayOfET,
} from "./timeFmt";

describe("timeFmt — Beijing-time projection", () => {
  it("fmtBjHM converts UTC ISO to BJ wall-clock HH:MM", () => {
    // 2026-05-14T01:30:00Z = 2026-05-14 09:30 BJ
    expect(fmtBjHM("2026-05-14T01:30:00Z")).toBe("09:30");
    // 2026-05-13T15:55:00Z = 2026-05-13 23:55 BJ
    expect(fmtBjHM("2026-05-13T15:55:00Z")).toBe("23:55");
  });

  it("fmtBjDate uses BJ calendar date (handles UTC-day rollover)", () => {
    // 2026-05-13T20:00:00Z = 2026-05-14 04:00 BJ → month/day must show 05/14
    expect(fmtBjDate("2026-05-13T20:00:00Z")).toBe("05/14");
  });

  it("fmtBjRel labels 'today' relative to BJ midnight, not UTC", () => {
    // Stub clock to a known BJ "today"
    const now = new Date("2026-05-14T08:00:00Z"); // = 16:00 BJ on 5/14
    const realNow = Date.now;
    Date.now = () => now.getTime();
    try {
      // Same BJ day but at 02:00 BJ (= 2026-05-13T18:00Z)
      expect(fmtBjRel("2026-05-13T18:00:00Z")).toBe("今天 02:00");
      // Yesterday in BJ
      expect(fmtBjRel("2026-05-13T01:30:00Z")).toBe("昨天 09:30");
    } finally {
      Date.now = realNow;
    }
  });

  it("falls back to MM/DD HH:MM for older timestamps", () => {
    const now = new Date("2026-05-14T08:00:00Z");
    const realNow = Date.now;
    Date.now = () => now.getTime();
    try {
      // 5 days ago
      expect(fmtBjRel("2026-05-09T02:00:00Z")).toBe("05/09 10:00");
    } finally {
      Date.now = realNow;
    }
  });
});

describe("classifyETSession", () => {
  // May = DST, ET = UTC-4
  it("classifies regular session (9:30-16:00 ET)", () => {
    // 14:00 ET = 18:00 UTC
    expect(classifyETSession("2026-05-14T18:00:00Z")).toBe("regular");
    // 9:35 ET = 13:35 UTC (just into session)
    expect(classifyETSession("2026-05-14T13:35:00Z")).toBe("regular");
  });

  it("classifies pre-market (4:00-9:30 ET)", () => {
    // 5:00 ET = 9:00 UTC
    expect(classifyETSession("2026-05-14T09:00:00Z")).toBe("pre");
    // 9:29 ET = 13:29 UTC (last pre minute)
    expect(classifyETSession("2026-05-14T13:29:00Z")).toBe("pre");
  });

  it("classifies after-hours (16:00-20:00 ET)", () => {
    // 18:00 ET = 22:00 UTC
    expect(classifyETSession("2026-05-14T22:00:00Z")).toBe("post");
  });

  it("classifies overnight (20:00 ET — 04:00 ET next day)", () => {
    // 22:00 ET = 02:00 UTC next day
    expect(classifyETSession("2026-05-15T02:00:00Z")).toBe("overnight");
    // 03:00 ET = 07:00 UTC
    expect(classifyETSession("2026-05-14T07:00:00Z")).toBe("overnight");
  });
});

describe("tradingDayOfET — trades within one US session", () => {
  // Scenario from the user: a fill at 5/14 21:30 BJ and another at 5/15
  // 00:30 BJ are BOTH within the 5/14 ET regular session and must roll
  // up to the same trading day.
  it("attributes 5/14 21:30 BJ to the 2026-05-14 trading day", () => {
    // BJ 21:30 5/14 = UTC 13:30 5/14 = ET 09:30 5/14 (EDT, regular open).
    expect(tradingDayOfET("2026-05-14T13:30:00Z")).toBe("2026-05-14");
  });

  it("attributes 5/15 00:30 BJ to the same 2026-05-14 trading day", () => {
    // BJ 00:30 5/15 = UTC 16:30 5/14 = ET 12:30 5/14 (regular mid-day).
    expect(tradingDayOfET("2026-05-14T16:30:00Z")).toBe("2026-05-14");
  });

  it("attributes 5/15 04:00 BJ (= 5/14 16:00 ET after-hours start) to 5/14", () => {
    expect(tradingDayOfET("2026-05-14T20:00:00Z")).toBe("2026-05-14");
  });

  it("rolls ET 00:00-04:00 back to the previous trading day", () => {
    // ET 02:00 5/15 = UTC 06:00 5/15 — still tail of 5/14.
    expect(tradingDayOfET("2026-05-15T06:00:00Z")).toBe("2026-05-14");
  });

  it("starts a new trading day at ET 04:00 pre-market open", () => {
    // ET 04:30 5/15 = UTC 08:30 5/15 — first minute of 5/15 trading day.
    expect(tradingDayOfET("2026-05-15T08:30:00Z")).toBe("2026-05-15");
  });

  it("treats a naive ISO string (no tz marker) as UTC, not local time", () => {
    // Same instant as the 5/14 21:30 BJ test above, but without a tz
    // marker. Native ``new Date`` would parse as LOCAL time and shift by
    // the browser's offset — parseUtc forces UTC interpretation.
    expect(tradingDayOfET("2026-05-14T13:30:00")).toBe("2026-05-14");
  });
});
