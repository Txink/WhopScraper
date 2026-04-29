import { describe, expect, it } from "vitest";
import { fmtTime, elapsedMs, fmtBeijingFull } from "./cardHelpers";

describe("fmtTime", () => {
  it("renders a real-UTC timestamp as Beijing HH:MM:SS", () => {
    // Real UTC 06:30:00 → Beijing 14:30:00
    expect(fmtTime("2026-04-25T06:30:00Z")).toBe("14:30:00");
  });

  it("crosses the date boundary correctly", () => {
    // Real UTC 16:00:00 Apr 24 → Beijing 00:00:00 Apr 25
    expect(fmtTime("2026-04-24T16:00:00Z")).toBe("00:00:00");
  });

  it("handles seconds precision", () => {
    expect(fmtTime("2026-04-25T06:30:42.000Z")).toBe("14:30:42");
  });

  it("renders independent of the host browser timezone", () => {
    // The Intl path uses an explicit timeZone option, so this assertion
    // documents intent: identical input → identical output regardless
    // of where the test runs.
    const a = fmtTime("2026-04-25T06:30:00Z");
    expect(a).toBe("14:30:00");
  });
});

describe("elapsedMs", () => {
  it("computes positive elapsed milliseconds for forward intervals", () => {
    expect(elapsedMs("2026-04-25T06:30:00Z", "2026-04-25T06:30:01Z")).toBe(1000);
  });
});

describe("fmtBeijingFull", () => {
  it("renders a real-UTC ISO as Beijing YYYY-MM-DD HH:MM:SS", () => {
    expect(fmtBeijingFull("2026-04-25T06:30:00Z")).toBe("2026-04-25 14:30:00");
  });

  it("crosses the date boundary forwards", () => {
    expect(fmtBeijingFull("2026-04-24T16:30:00Z")).toBe("2026-04-25 00:30:00");
  });
});
