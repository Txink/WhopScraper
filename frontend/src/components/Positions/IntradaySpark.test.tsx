import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render } from "@testing-library/react";
import { IntradaySpark } from "./IntradaySpark";
import type { Candlestick } from "../../api/domain-types";

// All tests pin Date.now() to a known instant inside US regular session
// (BJ 22:30 = ET 10:30 on 2026-05-14, ~1h into the 6.5h session).
const NOW = Date.parse("2026-05-14T14:30:00Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

const bar = (iso: string, c: number): Candlestick => ({
  timestamp: iso, open: c, high: c, low: c, close: c, volume: 0, turnover: 0,
});

// US regular bars (BJ ISO; parseAsBJ in IntradaySpark assumes naive timestamps
// land in BJ wall clock). 09:30 ET = 21:30 BJ. Use 2026-05-14 21:30+ in BJ.
const baseBars: Candlestick[] = [
  bar("2026-05-14T21:30:00", 100),
  bar("2026-05-14T21:31:00", 101),
  bar("2026-05-14T21:32:00", 102),
];

function regionTexts(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll(".ispark-region-label"))
    .map((el) => el.textContent ?? "");
}

describe("IntradaySpark", () => {
  it("renders SVG with line + area + four US region labels (夜盘 first)", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark-svg")).not.toBeNull();
    expect(regionTexts(container)).toEqual(["夜盘", "盘前", "盘中", "盘后"]);
    expect(container.querySelector(".ispark-line")).not.toBeNull();
    expect(container.querySelector(".ispark-area")).not.toBeNull();
  });

  it("marks the currently-active US region label with .active", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    const active = container.querySelector(".ispark-region-label.active");
    expect(active?.textContent).toBe("盘中");
  });

  it("renders three dividers between four US regions", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    expect(container.querySelectorAll(".ispark-divider")).toHaveLength(3);
  });

  it("applies .pos when lastDone >= openPrice", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark.pos")).not.toBeNull();
    expect(container.querySelector(".ispark.neg")).toBeNull();
  });

  it("applies .neg when lastDone < openPrice", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={98} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark.neg")).not.toBeNull();
  });

  it("renders pulse dot in active session", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark-pulse")).not.toBeNull();
  });

  it("omits pulse dot when session === closed; no region marked active", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="closed"
        bars={baseBars} lastDone={null} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark-pulse")).toBeNull();
    expect(container.querySelector(".ispark.is-closed")).not.toBeNull();
    // All four region labels still render — they describe the day shape;
    // none gets the .active highlight because the market is closed.
    expect(regionTexts(container)).toEqual(["夜盘", "盘前", "盘中", "盘后"]);
    expect(container.querySelector(".ispark-region-label.active")).toBeNull();
  });

  it("renders skeleton when bars undefined", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={undefined} lastDone={null} openPrice={null}
      />,
    );
    expect(container.querySelector(".ispark-skeleton")).not.toBeNull();
    expect(container.querySelector(".ispark-line")).toBeNull();
  });

  it("renders region labels even when bars present but empty", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={[]} lastDone={null} openPrice={null}
      />,
    );
    expect(container.querySelector(".ispark-line")).toBeNull();
    expect(regionTexts(container)).toEqual(["夜盘", "盘前", "盘中", "盘后"]);
  });

  it("line path is non-empty when bars have data", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    const d = container.querySelector(".ispark-line")?.getAttribute("d") ?? "";
    expect(d.length).toBeGreaterThan(0);
    expect(d.startsWith("M")).toBe(true);
  });

  it("HK regular renders a single 盘中 region + no dividers", () => {
    vi.setSystemTime(Date.parse("2026-05-14T02:00:00Z")); // 10:00 HKT
    // 12:30 HKT bar should be dropped from the path (lunch slot returns -1)
    const lunchBar = bar("2026-05-14T12:30:00", 50);
    const { container } = render(
      <IntradaySpark
        symbol="0700.HK" market="HK" session="regular"
        bars={[bar("2026-05-14T09:30:00", 48), lunchBar, bar("2026-05-14T13:00:00", 52)]}
        lastDone={52} openPrice={48}
      />,
    );
    expect(regionTexts(container)).toEqual(["盘中"]);
    expect(container.querySelectorAll(".ispark-divider")).toHaveLength(0);
    expect(container.querySelector(".ispark-line")).not.toBeNull();
  });
});
