import { describe, it, expect } from "vitest";
import { resolveViewConfig } from "./viewConfig";

describe("resolveViewConfig", () => {
  const defaults = {
    intradaySessions: "regular" as const,
    minuteGranularity: "5min" as const,
    multidayWindow: 5 as const,
    dayKGranularity: "day" as const,
  };

  it("intraday → period=today, granularity=分时, line, sessionBg enabled, live", () => {
    const c = resolveViewConfig("intraday", { ...defaults, intradaySessions: "pre" });
    expect(c.period).toBe("today");
    expect(c.granularity).toBe("分时");
    expect(c.sessions).toBe("pre");
    expect(c.datasetType).toBe("line");
    expect(c.sessionBgEnabled).toBe(true);
    expect(c.liveCfg).toEqual({ periodMinutes: 1, allowAppend: true });
  });

  it("minute → period=today, candlestick, no sessionBg, live at chosen minutes", () => {
    const c = resolveViewConfig("minute", { ...defaults, minuteGranularity: "3min" });
    expect(c.period).toBe("today");
    expect(c.granularity).toBe("3min");
    expect(c.sessions).toBe("all");
    expect(c.datasetType).toBe("candlestick");
    expect(c.sessionBgEnabled).toBe(false);
    expect(c.liveCfg).toEqual({ periodMinutes: 3, allowAppend: true });
  });

  it("multiday → period=5 or 7, line + day separators, live at 5min no-append", () => {
    const c = resolveViewConfig("multiday", { ...defaults, multidayWindow: 7 });
    expect(c.period).toBe("7");
    expect(c.datasetType).toBe("line");
    expect(c.dayMarkersEnabled).toBe(true);
    expect(c.liveCfg).toEqual({ periodMinutes: 5, allowAppend: false });
  });

  it.each([
    ["day",   "day",   80],
    ["week",  "week",  52],
    ["month", "month", 36],
    ["year",  "year",  20],
  ] as const)("%s → period=%s, candlestick, no live, initial visible %d", (view, period, visible) => {
    const c = resolveViewConfig(view, defaults);
    expect(c.period).toBe(period);
    expect(c.datasetType).toBe("candlestick");
    expect(c.liveCfg).toBeNull();
    expect(c.initialVisibleCount).toBe(visible);
    expect(c.sessionBgEnabled).toBe(false);
    expect(c.dayMarkersEnabled).toBe(false);
  });
});
