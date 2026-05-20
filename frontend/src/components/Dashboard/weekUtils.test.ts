import { describe, it, expect } from "vitest";
import { weekKeyOf, formatWeekRange, computeWeeks, isoWeekBounds } from "./weekUtils";
import type { TaskSummary } from "../../api/domain-types";

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

const mkTask = (id: string, postedAt: string): TaskSummary =>
  ({
    id,
    status: "FILLED",
    created_at: postedAt,
    updated_at: postedAt,
    message: { url: "https://w/x", author: "a", content: "c", posted_at: postedAt, received_at: postedAt },
  } as unknown as TaskSummary);

describe("computeWeeks", () => {
  it("returns empty groups and weeks for an empty input", () => {
    const r = computeWeeks([]);
    expect(r.weeks).toEqual([]);
    expect(r.groups.size).toBe(0);
  });

  it("groups tasks by their local-week Sunday key", () => {
    const t1 = mkTask("t1", new Date(2026, 3, 22, 10).toISOString()); // wk 04-19
    const t2 = mkTask("t2", new Date(2026, 3, 25, 10).toISOString()); // wk 04-19
    const t3 = mkTask("t3", new Date(2026, 3, 27, 10).toISOString()); // wk 04-26
    const r = computeWeeks([t3, t1, t2]); // arbitrary input order
    expect(r.weeks.map((w) => w.key)).toEqual(["2026-04-26", "2026-04-19"]);
    expect(r.groups.get("2026-04-26")?.map((t) => t.id)).toEqual(["t3"]);
    expect(r.groups.get("2026-04-19")?.map((t) => t.id).sort()).toEqual(["t1", "t2"]);
  });

  it("returns weeks descending and sorts each group's tasks descending by time", () => {
    const a = mkTask("a", new Date(2026, 3, 19, 9).toISOString());
    const b = mkTask("b", new Date(2026, 3, 19, 18).toISOString());
    const r = computeWeeks([a, b]);
    expect(r.groups.get("2026-04-19")?.map((t) => t.id)).toEqual(["b", "a"]);
  });

  it("populates startLabel/endLabel from the week key", () => {
    const t = mkTask("t", new Date(2026, 3, 22, 10).toISOString());
    const r = computeWeeks([t]);
    expect(r.weeks[0]).toMatchObject({
      key: "2026-04-19",
      startLabel: "04/19",
      endLabel: "04/25",
    });
  });

  it("falls back to created_at when message.posted_at is null", () => {
    const t = {
      id: "t",
      status: "FILLED",
      created_at: new Date(2026, 3, 22, 10).toISOString(),
      updated_at: new Date(2026, 3, 22, 10).toISOString(),
      message: { url: null, author: null, content: "", posted_at: null, received_at: null },
    } as unknown as TaskSummary;
    const r = computeWeeks([t]);
    expect(r.weeks[0]?.key).toBe("2026-04-19");
  });
});

describe("isoWeekBounds", () => {
  it("2026-W21 → start 2026-05-18T00:00:00, end 2026-05-25T00:00:00", () => {
    const r = isoWeekBounds("2026-W21");
    expect(r.start).toBe("2026-05-18T00:00:00");
    expect(r.end).toBe("2026-05-25T00:00:00");
  });

  it("rejects malformed keys", () => {
    expect(() => isoWeekBounds("2026/W21")).toThrow();
    expect(() => isoWeekBounds("2026-W2")).toThrow();
  });
});

describe("weekKeyOf — Beijing-pinned", () => {
  it("places a UTC-Saturday late-night moment in the correct Beijing week", () => {
    // Real UTC 2026-04-25T20:00:00Z = Beijing 2026-04-26T04:00 (Sunday).
    // In Beijing, Sunday Apr 26 is the start of the week containing Apr 26.
    expect(weekKeyOf("2026-04-25T20:00:00Z")).toBe("2026-04-26");
  });

  it("rolls a UTC-late-Saturday into the Beijing-Sunday week", () => {
    // Real UTC 2026-04-25T16:00:00Z = Beijing 2026-04-26T00:00 exactly.
    expect(weekKeyOf("2026-04-25T16:00:00Z")).toBe("2026-04-26");
  });

  it("treats early Beijing Saturday as still the previous Sunday's week", () => {
    // Real UTC 2026-04-25T01:00:00Z = Beijing 2026-04-25T09:00 (Saturday).
    // Beijing-Saturday belongs to the week starting on the prior Sunday Apr 19.
    expect(weekKeyOf("2026-04-25T01:00:00Z")).toBe("2026-04-19");
  });

  it("handles year-boundary cross (UTC Dec 31 → Beijing Jan 1)", () => {
    // Real UTC 2025-12-31T20:00:00Z = Beijing 2026-01-01T04:00 (Thursday).
    // Beijing-Thursday Jan 1 → walk back 4 days → Sunday Dec 28 2025.
    expect(weekKeyOf("2025-12-31T20:00:00Z")).toBe("2025-12-28");
  });
});
