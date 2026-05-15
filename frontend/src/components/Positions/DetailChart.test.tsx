import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, act } from "@testing-library/react";

// Mock chartjs-plugin-zoom to avoid HammerJS initialization errors in jsdom.
// HammerJS tries to attach to document during plugin registration, which fails.
vi.mock("chartjs-plugin-zoom");

// Mock Chart.js to avoid 2d context issues in jsdom. We return stubs that
// prevent the component from crashing while still allowing DOM rendering.
// In a real test, Chart would be initialized, but here we just verify React wiring.
vi.mock("chart.js", () => {
  type ChartStub = {
    destroy: () => void;
    update: () => void;
    data: { labels: unknown[]; datasets: Array<{ label: string; data: unknown[] }> };
    options: {
      scales: { x: { max: number; min: number } };
      plugins: {
        sessionBg: { barCount: number };
        zoom: { limits: { x: { max: number } } };
      };
    };
    scales: { x: { max: number; min: number } };
  };
  function ChartCtor(this: ChartStub) {
    this.destroy = vi.fn();
    this.update = vi.fn();
    // Pre-populate a minimal dataset structure so Effect B doesn't crash
    // trying to mutate chart.data.datasets[0].data
    this.data = {
      labels: [],
      datasets: [
        { label: "price", data: [] },
      ],
    };
    this.options = {
      scales: { x: { max: 0, min: 0 } },
      plugins: { sessionBg: { barCount: 0 }, zoom: { limits: { x: { max: 0 } } } },
    };
    this.scales = { x: { max: 0, min: 0 } };
  }
  const Chart = ChartCtor as unknown as {
    new (): ChartStub;
    register: (...args: unknown[]) => void;
  };
  Chart.register = vi.fn();
  return {
    Chart,
    LineController: {},
    ScatterController: {},
    LineElement: {},
    PointElement: {},
    LinearScale: {},
    CategoryScale: {},
    Filler: {},
    Tooltip: {
      positioners: {},
    },
  };
});

import { DetailChart } from "./DetailChart";
import { useQuotesStore } from "../../stores/quotes";
import type { Candlestick } from "../../api/domain-types";

// Chart.js needs a 2d context that jsdom doesn't provide. Stub the getter
// so `new Chart(canvas, ...)` swallows the failure quietly (the component
// wraps the constructor in a try/catch and warns in DEV).
beforeEach(() => {
  // Stub the canvas getter (jsdom defaults to null; we make it explicit
  // so Chart.js's internal context check doesn't throw before our mock
  // takes effect).
  (HTMLCanvasElement.prototype as unknown as { getContext: () => null }).getContext = () => null;
  useQuotesStore.getState().reset();
});

const bars: Candlestick[] = [
  { timestamp: "2026-05-15T13:30:00Z", open: 100, high: 100, low: 100, close: 100, volume: 0, turnover: 0 },
  { timestamp: "2026-05-15T13:31:00Z", open: 100, high: 101, low: 99, close: 101, volume: 0, turnover: 0 },
];

function renderAt(period: Parameters<typeof DetailChart>[0]["period"], todayGranularity: Parameters<typeof DetailChart>[0]["todayGranularity"]) {
  return render(
    <DetailChart
      symbol="TSLA.US"
      bars={bars}
      period={period}
      trades={[]}
      avgCost={null}
      showAvgCost={false}
      todayGranularity={todayGranularity}
      todaySessions="regular"
    />,
  );
}

describe("DetailChart live-mode wiring", () => {
  it.each([
    ["today", "分时"],
    ["today", "1min"],
    ["today", "2min"],
    ["today", "3min"],
    ["today", "5min"],
    ["5", "分时"],
    ["7", "分时"],
    ["15", "分时"],
  ] as const)("renders .live-pulse for live view (period=%s, granularity=%s)", (period, gran) => {
    const { container } = renderAt(period, gran);
    expect(container.querySelector(".live-pulse")).not.toBeNull();
  });

  it.each([
    ["30", "分时"],
    ["60", "分时"],
    ["90", "分时"],
  ] as const)("omits .live-pulse for non-live view (period=%s, granularity=%s)", (period, gran) => {
    const { container } = renderAt(period, gran);
    expect(container.querySelector(".live-pulse")).toBeNull();
  });

  it("survives a quote upsert in live mode without throwing", () => {
    renderAt("today", "分时");
    // The store push path is what App.tsx calls in production. Under jsdom
    // chartRef will be null (Chart construction failed), and the live-tick
    // effect's `if (!chart) return;` guard is what we're verifying here.
    expect(() => {
      act(() => {
        useQuotesStore.getState().upsertQuote("TSLA.US", {
          last_done: 102,
          prev_close: 100,
          today_close: null,
          open: 100, high: 102, low: 99,
          volume: 0, turnover: 0,
          change: 2, change_pct: 2,
          trade_session: "regular",
        });
      });
    }).not.toThrow();
  });

  it("survives quote upserts across all non-live views too", () => {
    for (const [period, gran] of [["30", "分时"], ["60", "分时"], ["90", "分时"]] as const) {
      const { unmount } = renderAt(period, gran);
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
