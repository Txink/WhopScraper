import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, act } from "@testing-library/react";

vi.mock("chartjs-plugin-zoom");

let lastChartInstance: { data: { labels: unknown[]; datasets: Array<{ label: string; data: unknown[] }> } } | null = null;

vi.mock("chart.js", () => {
  type ChartStub = {
    destroy: () => void;
    update: () => void;
    data: { labels: unknown[]; datasets: Array<{ label: string; data: unknown[] }> };
    options: {
      scales: { x: { max: number; min: number } };
      plugins: {
        sessionBg: { barCount: number };
        dayMarkers: { bars: unknown[] };
        zoom: { limits: { x: { max: number } } };
      };
    };
    scales: { x: { max: number; min: number } };
  };
  function ChartCtor(this: ChartStub) {
    this.destroy = vi.fn();
    this.update = vi.fn();
    this.data = {
      labels: [],
      datasets: [{ label: "成交价", data: [] }],
    };
    this.options = {
      scales: { x: { max: 0, min: 0 } },
      plugins: {
        sessionBg: { barCount: 0 },
        dayMarkers: { bars: [] },
        zoom: { limits: { x: { max: 0 } } },
      },
    };
    this.scales = { x: { max: 0, min: 0 } };
    lastChartInstance = this;
  }
  const Chart = ChartCtor as unknown as { new (): ChartStub; register: (...args: unknown[]) => void };
  Chart.register = vi.fn();
  return {
    Chart,
    LineController: {}, ScatterController: {},
    LineElement: {}, PointElement: {},
    LinearScale: {}, CategoryScale: {},
    Filler: {}, Tooltip: { positioners: {} },
  };
});

vi.mock("chartjs-chart-financial", () => ({
  CandlestickController: {}, CandlestickElement: {},
  OhlcController: {}, OhlcElement: {},
}));

import { DetailChart } from "./DetailChart";
import { useQuotesStore } from "../../stores/quotes";
import { resolveViewConfig, type ViewType } from "./viewConfig";
import type { Candlestick } from "../../api/domain-types";

beforeEach(() => {
  (HTMLCanvasElement.prototype as unknown as { getContext: () => null }).getContext = () => null;
  useQuotesStore.getState().reset();
});

const bars: Candlestick[] = [
  { timestamp: "2026-05-15T13:30:00Z", open: 100, high: 100, low: 100, close: 100, volume: 0, turnover: 0 },
  { timestamp: "2026-05-15T13:31:00Z", open: 100, high: 101, low: 99, close: 101, volume: 0, turnover: 0 },
];

function renderView(view: ViewType, subOverrides: Partial<Parameters<typeof resolveViewConfig>[1]> = {}) {
  const sub = {
    intradaySessions: "regular" as const,
    minuteGranularity: "5min" as const,
    multidayWindow: 5 as const,
    ...subOverrides,
  };
  const cfg = resolveViewConfig(view, sub);
  return render(
    <DetailChart
      symbol="TSLA.US"
      bars={bars}
      view={view}
      viewCfg={cfg}
      trades={[]}
      avgCost={null}
      showAvgCost={false}
    />,
  );
}

describe("DetailChart candlestick dataset shape", () => {
  it("Effect B writes OHLC objects (not numbers) for view=day", () => {
    renderView("day");
    const ds = lastChartInstance?.data.datasets[0];
    expect(Array.isArray(ds?.data)).toBe(true);
    const first = (ds?.data as unknown[])[0];
    expect(first).toMatchObject({ x: expect.any(Number), o: expect.any(Number), h: expect.any(Number), l: expect.any(Number), c: expect.any(Number) });
  });
});

describe("DetailChart live-mode wiring", () => {
  it.each([
    ["intraday"],
    ["minute"],
    ["multiday"],
  ] as const)("renders .live-pulse for live view (%s)", (view) => {
    const { container } = renderView(view);
    expect(container.querySelector(".live-pulse")).not.toBeNull();
  });

  it.each([
    ["day"],
    ["week"],
    ["month"],
    ["year"],
  ] as const)("omits .live-pulse for non-live view (%s)", (view) => {
    const { container } = renderView(view);
    expect(container.querySelector(".live-pulse")).toBeNull();
  });

  it("survives a quote upsert in live mode without throwing", () => {
    renderView("intraday");
    expect(() => {
      act(() => {
        useQuotesStore.getState().upsertQuote("TSLA.US", {
          last_done: 102, prev_close: 100, today_close: null,
          open: 100, high: 102, low: 99,
          volume: 0, turnover: 0,
          change: 2, change_pct: 2,
          trade_session: "regular",
        });
      });
    }).not.toThrow();
  });

  it("survives quote upserts across all non-live views too", () => {
    for (const view of ["day", "week", "month", "year"] as const) {
      const { unmount } = renderView(view);
      expect(() => {
        act(() => {
          useQuotesStore.getState().upsertQuote("TSLA.US", {
            last_done: 105, prev_close: 100, today_close: null,
            open: 100, high: 105, low: 99,
            volume: 0, turnover: 0,
            change: 5, change_pct: 5,
            trade_session: "regular",
          });
        });
      }).not.toThrow();
      unmount();
    }
  });
});
