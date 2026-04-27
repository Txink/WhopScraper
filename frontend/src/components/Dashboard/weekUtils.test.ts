import { describe, it, expect } from "vitest";
import { weekKeyOf } from "./weekUtils";

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
