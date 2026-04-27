import { describe, it, expect } from "vitest";
import { weekKeyOf, formatWeekRange } from "./weekUtils";

describe("weekKeyOf", () => {
  it("returns the local-calendar Sunday's YYYY-MM-DD for a Wednesday", () => {
    // 2026-04-22 is a Wednesday in local time. The Sunday of its week
    // is 2026-04-19.
    const ts = new Date(2026, 3, 22, 14, 0, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });

  it("returns the same day's date when the timestamp is itself a Sunday", () => {
    const ts = new Date(2026, 3, 19, 9, 0, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });

  it("returns the previous Sunday for a Saturday late-night", () => {
    // 2026-04-25 (Saturday) 23:55 local → Sunday 2026-04-19.
    const ts = new Date(2026, 3, 25, 23, 55, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });

  it("does not get tricked by UTC-offset timezones", () => {
    // A timestamp at local Sunday 00:30 must still yield that Sunday's
    // local date even when the UTC date has rolled back to Saturday.
    const ts = new Date(2026, 3, 19, 0, 30, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });
});

describe("formatWeekRange", () => {
  it("returns MM/DD ~ MM/DD for the week starting on the given Sunday", () => {
    expect(formatWeekRange("2026-04-19")).toEqual({
      startLabel: "04/19",
      endLabel: "04/25",
    });
  });

  it("handles month rollover", () => {
    // 2026-04-26 (Sunday) → ends 2026-05-02 (Saturday).
    expect(formatWeekRange("2026-04-26")).toEqual({
      startLabel: "04/26",
      endLabel: "05/02",
    });
  });

  it("handles year rollover", () => {
    // 2025-12-28 (Sunday) → ends 2026-01-03 (Saturday).
    expect(formatWeekRange("2025-12-28")).toEqual({
      startLabel: "12/28",
      endLabel: "01/03",
    });
  });
});
