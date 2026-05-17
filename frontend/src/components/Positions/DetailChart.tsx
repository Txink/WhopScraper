import { useEffect, useRef, useMemo, useState } from "react";
import {
  Chart,
  type ChartConfiguration,
  type ScriptableContext,
  LineController,
  ScatterController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
} from "chart.js";
import type { Plugin } from "chart.js";
import { drawBubble } from "./bubble";
import {
  CandlestickController,
  CandlestickElement,
  OhlcController,
  OhlcElement,
} from "chartjs-chart-financial";

// Custom tooltip positioner: anchor the popup at the cursor instead of
// the nearest data point. Registered once at module load (Chart.js stores
// positioners on the Tooltip class globally).
//
// `eventPosition` is the {x, y} of the most recent pointer event on the
// canvas; we offset slightly so the popup doesn't cover the crosshair.
(Tooltip.positioners as unknown as Record<string, (
  elements: unknown[], eventPosition: { x: number; y: number }
) => { x: number; y: number }>).cursor = (_elements, eventPosition) => ({
  x: eventPosition.x,
  y: eventPosition.y,
});
import zoomPlugin from "chartjs-plugin-zoom";
import type { Candlestick, Trade } from "../../api/domain-types";
import { sessionBgPlugin } from "./sessionBgPlugin";
import { crosshairPlugin } from "./crosshairPlugin";
import { minMaxLabelsPlugin } from "./minMaxLabelsPlugin";
import { buildSessionSlots } from "./sessionSlots";
import type { ViewType, ViewConfig } from "./viewConfig";
import { fmtBjHM, fmtBjDate, fmtBjRel, fmtBjWeekISO, fmtBjMonth, fmtBjYear, classifyETSession, tradingDayOfET, currentTradingDay } from "./timeFmt";
import { usePrefsStore } from "../../stores/prefs";
import { useQuotesStore } from "../../stores/quotes";
import { applyLiveTick, bucketKey } from "./liveTick";

Chart.register(
  LineController, ScatterController,
  LineElement, PointElement,
  LinearScale, CategoryScale,
  Filler, Tooltip,
  zoomPlugin,
  CandlestickController, CandlestickElement,
  OhlcController, OhlcElement,
);

/** Resolve a CSS custom-property to its current hex string. Used so the
 *  chart picks up live changes from the prefs store (red-up vs green-up)
 *  without each callsite needing to know the convention. */
function cssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

const C = {
  info: "#5aa0ff",
  // K-line uses brand blue regardless of direction — the up/down read is
  // carried by the change pill in DetailSummary, not by the curve color.
  price: "#5aa0ff",
  priceFill: "rgba(90, 160, 255, 0.16)",
  line: "rgba(255,255,255,0.06)",
  fg3: "#566071",
  bg0: "#0b0f14",
};

// Default 3 — all default-precision callsites in this file (y-axis
// tick, tooltip price, scatter trade price) are price reads. Volume /
// quantity / change% pass d=0 or d=2 explicitly.
function fmtN(n: number, d = 3): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** Draws B/S/T speech-bubble badges at aggregated trade scatter positions.
 *  Reads the three scatter datasets by label so it's order-independent.
 *  Tail tip lands exactly at the data point (candle top-center in candle
 *  views; VWAP pixel in line views). Body sits up and slightly right. */
const tradeMarkersPlugin: Plugin = {
  id: "tradeMarkers",
  afterDatasetsDraw(chart) {
    const ctx = chart.ctx;
    const B_COLOR = "#f59e0b";
    const S_COLOR = "#3b82f6";
    const T_COLOR = "#a855f7";

    chart.data.datasets.forEach((ds, dsIdx) => {
      const label = (ds as { label?: string }).label;
      let letter: "B" | "S" | "T" | null = null;
      let color = "";
      if (label === "买入") { letter = "B"; color = B_COLOR; }
      else if (label === "卖出") { letter = "S"; color = S_COLOR; }
      else if (label === "做T") { letter = "T"; color = T_COLOR; }
      if (!letter) return;
      const meta = chart.getDatasetMeta(dsIdx);
      meta.data.forEach((el) => {
        const x = (el as { x?: number }).x;
        const y = (el as { y?: number }).y;
        if (x == null || y == null) return;
        // Tail tip lands exactly at the data point. Body sits up + slightly right.
        drawBubble(ctx, x, y, letter!, color);
      });
    });
  },
};

/** Vertical guide lines at every trading-day boundary in `bars[]`. Only
 *  drawn when `viewCfg.dayMarkersEnabled` is true (multiday view). */
const dayMarkersPlugin: Plugin<"line" | "candlestick"> = {
  id: "dayMarkers",
  afterDraw(chart, _args, opts) {
    const { enabled, bars: pluginBars } = opts as { enabled: boolean; bars: Candlestick[] };
    if (!enabled || !pluginBars || pluginBars.length === 0) return;
    const ctx = chart.ctx;
    const xs = chart.scales.x;
    const ys = chart.scales.y;
    if (!xs || !ys) return;
    let prevDay: string | null = null;
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    for (let i = 0; i < pluginBars.length; i++) {
      const b = pluginBars[i]!;
      if (!b.timestamp) continue;
      const day = tradingDayOfET(b.timestamp);
      if (prevDay !== null && day !== prevDay) {
        const x = xs.getPixelForValue(i);
        if (Number.isFinite(x)) {
          ctx.beginPath();
          ctx.moveTo(x, ys.top);
          ctx.lineTo(x, ys.bottom);
          ctx.stroke();
        }
      }
      prevDay = day;
    }
    ctx.restore();
  },
};

type AggMarker = {
  x: number;
  y: number;
  type: "B" | "S" | "T";
  qty: number;
  price: number;
  trades: Trade[];
};

interface Props {
  symbol: string;
  bars: Candlestick[];
  view: ViewType;
  viewCfg: ViewConfig;
  trades: Trade[];
}

/**
 * Detail chart: price line + BUY/SELL scatter markers. Markers are snapped
 * to the nearest bar in time so they always land on the x-axis grid.
 */
export function DetailChart({
  symbol, bars, view, viewCfg, trades,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);
  const [isZoomed, setIsZoomed] = useState(false);
  // Subscribe to prefs so the chart rebuilds (with new BUY/SELL marker
  // colors etc.) when the user toggles US/CN color convention.
  const colorMode = usePrefsStore((s) => s.colorMode);

  // Derived chart data — kept in a ref so Effect A (chart create) reads the
  // latest closes/labels/markers at mount time without listing them in deps,
  // while Effect B mutates them on subsequent changes.
  const dataRef = useRef<{
    labels: string[];
    closes: number[];
    buys: AggMarker[];
    sells: AggMarker[];
    ts: AggMarker[];
  } | null>(null);

  const visibleBarsRef = useRef<Candlestick[]>([]);
  const markersRef = useRef<AggMarker[]>([]);

  const pulseRef = useRef<HTMLDivElement | null>(null);
  // Local mutable state for live mode. We keep extended bars HERE (not in
  // the bars store) so DetailPane's barsInitialized gate and other
  // downstream consumers aren't churned by quote-push frequency.
  const liveStateRef = useRef<{
    bars: Candlestick[];
    labels: string[];
    rafId: number | null;
    lastApplied: number;
  } | null>(null);

  // Snap each trade to the index of its nearest bar in time. Skip trades
  // outside the chart window so they don't anchor to (0, 0) of the axis.
  // Intraday flow:
  //   1. Trim raw bars to TODAY's trading day (ET 4:00 rollover semantics)
  //   2. Further trim by selected session for 分时 mode
  //   3. Only 分时 pads to a full slot array (so未到的 sessions占住 x 轴);
  //      minute granularities skip padding and render real bars only.
  //
  // Non-intraday views skip all of this and use bars verbatim.
  const visibleBars: Candlestick[] = useMemo(() => {
    // 分时 (intraday view) is the only mode that needs session padding/trim.
    if (view !== "intraday") return bars;
    const today = currentTradingDay();
    const trimmed = bars.filter((b) => {
      if (!b.timestamp) return false;
      if (tradingDayOfET(b.timestamp) !== today) return false;
      if (viewCfg.sessions === "all") return true;
      if (viewCfg.sessions === "regular") return classifyETSession(b.timestamp) === "regular";
      return classifyETSession(b.timestamp) === viewCfg.sessions;
    });
    return buildSessionSlots(trimmed, "分时", viewCfg.sessions ?? "regular");
  }, [bars, view, viewCfg.sessions]);

  const visibleTrades: Trade[] = useMemo(() => {
    if (view !== "intraday") return trades;
    const today = currentTradingDay();
    return trades.filter((t) => {
      if (tradingDayOfET(t.ts) !== today) return false;
      if (viewCfg.sessions === "all") return true;
      if (viewCfg.sessions === "regular") return classifyETSession(t.ts) === "regular";
      return classifyETSession(t.ts) === viewCfg.sessions;
    });
  }, [trades, view, viewCfg.sessions]);

  const markers: AggMarker[] = useMemo(() => {
    if (visibleBars.length === 0) return [];
    const barTs = visibleBars.map((b) => b.timestamp ? Date.parse(b.timestamp) : 0);
    // Snap tolerance reflects bar granularity: intraday/minute/multiday bars
    // tolerate up to 1h; daily bars tolerate up to 12h so weekend/after-hours
    // fills still anchor to the right calendar day.
    const isIntradayPeriod =
      view === "intraday" || view === "minute" || view === "multiday";
    const tolerance = isIntradayPeriod ? 60 * 60 * 1000 : 12 * 3600 * 1000;
    // Group trades by their nearest-bar index.
    const grouped = new Map<number, Trade[]>();
    for (const t of visibleTrades) {
      const tts = Date.parse(t.ts);
      let best = -1; let bestD = Infinity;
      for (let i = 0; i < barTs.length; i++) {
        const d = Math.abs(barTs[i]! - tts);
        if (d < bestD) { bestD = d; best = i; }
      }
      if (bestD > tolerance || best < 0) continue;
      if (!grouped.has(best)) grouped.set(best, []);
      grouped.get(best)!.push(t);
    }
    // Reduce each bar's trades into a single aggregate marker.
    const out: AggMarker[] = [];
    grouped.forEach((trades, x) => {
      const buys = trades.filter((t) => t.side === "BUY");
      const sells = trades.filter((t) => t.side === "SELL");
      const totalQty = trades.reduce((s, t) => s + t.qty, 0);
      const totalValue = trades.reduce((s, t) => s + t.qty * t.price, 0);
      const vwap = totalQty > 0 ? totalValue / totalQty : 0;
      const type: AggMarker["type"] =
        buys.length > 0 && sells.length > 0 ? "T"
        : buys.length > 0 ? "B"
        : "S";
      // In candle views, anchor the badge at the candle's top so badges form
      // a clean above-bar row regardless of where trades happened within the bar.
      // In line views, keep VWAP so the badge sits next to the actual price.
      const bar = visibleBars[x];
      const isCandleView = viewCfg.datasetType === "candlestick";
      const y = isCandleView && bar ? bar.high : vwap;
      out.push({ x, y, type, qty: totalQty, price: vwap, trades });
    });
    return out;
  }, [visibleBars, visibleTrades, view, viewCfg.datasetType]);

  const chartData = useMemo(() => {
    const labels = visibleBars.map((b) => {
      if (!b.timestamp) return "";
      if (view === "intraday" || view === "minute") return fmtBjHM(b.timestamp);
      if (view === "multiday") return `${fmtBjDate(b.timestamp)} ${fmtBjHM(b.timestamp)}`;
      if (view === "day") return fmtBjDate(b.timestamp);
      if (view === "week") return fmtBjWeekISO(b.timestamp);
      if (view === "month") return fmtBjMonth(b.timestamp);
      if (view === "year") return fmtBjYear(b.timestamp);
      return fmtBjDate(b.timestamp);
    });
    const closes = visibleBars.map((b) => b.close);
    const buys = markers.filter((m) => m.type === "B");
    const sells = markers.filter((m) => m.type === "S");
    const ts = markers.filter((m) => m.type === "T");
    return { labels, closes, buys, sells, ts };
  }, [visibleBars, view, markers]);

  // Mirror into a ref so Effect A (mount-once) can read latest at create-time
  // without taking a deps subscription.
  useEffect(() => { dataRef.current = chartData; }, [chartData]);

  // Keep refs in sync each render so chart callbacks read the latest values
  // without forcing the chart to rebuild.
  visibleBarsRef.current = visibleBars;
  markersRef.current = markers;

  // Effect A — create the Chart instance once per structural-deps combo
  // (view/granularity/session/datasetType/color-mode). visibleBars / markers
  // flow through Effect B as in-place mutations so quote ticks don't tear
  // the chart down. Symbol switch is structural too (chart cleanly resets).
  useEffect(() => {
    const canvas = canvasRef.current;
    const data = dataRef.current;
    if (!canvas || !data || data.closes.length === 0) return;

    const initialCount = Number.isFinite(viewCfg.initialVisibleCount)
      ? Math.min(viewCfg.initialVisibleCount, data.closes.length)
      : data.closes.length;
    const xMax = data.closes.length - 1;
    const xMin = Math.max(0, xMax - initialCount + 1);

    const priceDataset = viewCfg.datasetType === "candlestick"
      ? ({
          label: "成交价",
          type: "candlestick" as const,
          data: visibleBars.map((b, i) => ({
            x: i,
            o: b.open, h: b.high, l: b.low, c: b.close,
          })),
          // chartjs-chart-financial reads `borderColors` / `backgroundColors`
          // (plural) for per-direction coloring. The singular `borderColor` /
          // `backgroundColor` must be scalar strings for Chart.js's own hover
          // resolver; passing an object literal there causes a runtime crash
          // ("value.toString is not a function").
          borderColors: {
            up: cssVar("--up-color", "#3dd68c"),
            down: cssVar("--down-color", "#ef5b5b"),
            unchanged: C.fg3,
          },
          backgroundColors: {
            up: cssVar("--up-color", "#3dd68c"),
            down: cssVar("--down-color", "#ef5b5b"),
            unchanged: C.fg3,
          },
          borderColor: cssVar("--up-color", "#3dd68c"),
          backgroundColor: cssVar("--up-color", "#3dd68c"),
          borderWidth: 1,
          barPercentage: 0.9,
          categoryPercentage: 0.95,
          order: 4,
          parsing: false as const,
        } as ChartConfiguration["data"]["datasets"][number])
      : ({
          label: "成交价",
          data: data.closes,
          borderColor: C.price,
          backgroundColor: (ctx: ScriptableContext<"line">) => {
            const area = ctx.chart.chartArea;
            if (!area) return "transparent";
            const grad = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
            grad.addColorStop(0, C.priceFill);
            grad.addColorStop(1, "rgba(0,0,0,0)");
            return grad;
          },
          borderWidth: 1.1, fill: true, tension: 0.26,
          pointRadius: 0, pointHoverRadius: 0,
          order: 4,
        } as ChartConfiguration["data"]["datasets"][number]);

    const cfg: ChartConfiguration = {
      type: "line",
      data: {
        labels: data.labels,
        datasets: [
          priceDataset,
          {
            label: "买入",
            type: "scatter" as const,
            data: data.buys,
            backgroundColor: "#f59e0b",
            borderColor: C.bg0,
            borderWidth: 0,
            pointRadius: 0,
            pointHoverRadius: 0,
            pointHitRadius: 14,
            pointStyle: "circle" as const,
            order: 1,
            parsing: false as const,
          } as ChartConfiguration["data"]["datasets"][number],
          {
            label: "卖出",
            type: "scatter" as const,
            data: data.sells,
            backgroundColor: "#3b82f6",
            borderColor: C.bg0,
            borderWidth: 0,
            pointRadius: 0,
            pointHoverRadius: 0,
            pointHitRadius: 14,
            pointStyle: "circle" as const,
            order: 1,
            parsing: false as const,
          } as ChartConfiguration["data"]["datasets"][number],
          {
            label: "做T",
            type: "scatter" as const,
            data: data.ts,
            backgroundColor: "#a855f7",
            borderColor: C.bg0,
            borderWidth: 0,
            pointRadius: 0,
            pointHoverRadius: 0,
            pointHitRadius: 14,
            pointStyle: "circle" as const,
            order: 1,
            parsing: false as const,
          } as ChartConfiguration["data"]["datasets"][number],
        ],
      },
      plugins: [sessionBgPlugin, crosshairPlugin, minMaxLabelsPlugin, dayMarkersPlugin, tradeMarkersPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 240 },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        // Y-axis labels live on the right; left side has nothing to
        // anchor, so flatten the left/right chartArea inset and let the
        // canvas hug the card padding. Top/bottom default to 0 too.
        layout: { padding: { left: 0, right: 0, top: 0, bottom: 0 } },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#0b0f14",
            borderColor: C.line,
            borderWidth: 1,
            padding: 10,
            position: "cursor" as unknown as undefined,
            caretSize: 0,
            caretPadding: 8,
            filter: (item) => {
              const ds = item.dataset as { type?: string; label?: string };
              return ds.label === "成交价" || ds.type === "scatter";
            },
            callbacks: {
              title: (items) => {
                const item = items[0];
                if (!item) return "";
                const ds = item.dataset as { type?: string };
                if (ds.type === "scatter") {
                  const agg = item.raw as { trades?: Trade[] };
                  const first = agg.trades?.[0];
                  if (!first) return "";
                  const extra = (agg.trades?.length ?? 1) > 1 ? ` · 共 ${agg.trades!.length} 笔` : "";
                  return `${fmtBjRel(first.ts)}${extra}`;
                }
                // Read live visibleBars via ref so tooltip stays accurate
                // after Effect B mutates / live-tick appends bars.
                const bar = visibleBarsRef.current[item.dataIndex];
                if (bar?.timestamp) return fmtBjRel(bar.timestamp);
                return item.label;
              },
              label: (item) => {
                const ds = item.dataset as { type?: string; label?: string };
                if (ds.type === "scatter") {
                  const agg = (item.raw as { type?: string; qty?: number; price?: number; trades?: Trade[] });
                  if (!agg || agg.qty == null) return "";
                  const action = agg.type === "B" ? "买入" : agg.type === "S" ? "卖出" : "做T";
                  return ` ${action} ${fmtN(agg.qty, 0)} 股 @ $${fmtN(agg.price ?? 0)}`;
                }
                if (ds.type === "candlestick") {
                  const ohlc = item.raw as { o: number; h: number; l: number; c: number };
                  return [
                    ` 开 $${fmtN(ohlc.o)}`,
                    ` 高 $${fmtN(ohlc.h)}`,
                    ` 低 $${fmtN(ohlc.l)}`,
                    ` 收 $${fmtN(ohlc.c)}`,
                  ];
                }
                return ` 价格 $${fmtN(item.parsed.y as number)}`;
              },
            },
          },
          sessionBg: {
            enabled: viewCfg.sessionBgEnabled,
            granularity: "分时" as const,
            barCount: data.closes.length,
            session: viewCfg.sessions ?? "regular",
          },
          // @ts-expect-error — dayMarkers is a custom plugin not in Chart.js types
          dayMarkers: {
            enabled: viewCfg.dayMarkersEnabled,
            bars: visibleBars,
          },
          zoom: {
            pan: {
              enabled: true, mode: "x", threshold: 4,
              onPanComplete: ({ chart }) => { setIsZoomed(true); chart.update("none"); },
            },
            zoom: {
              wheel: { enabled: true, speed: 0.05 },
              pinch: { enabled: true },
              mode: "x",
              onZoomComplete: ({ chart }) => { setIsZoomed(true); chart.update("none"); },
            },
            limits: { x: { min: 0, max: xMax, minRange: 5 } },
          },
        },
        scales: {
          x: {
            min: xMin, max: xMax,
            grid: { color: C.line, drawTicks: false },
            ticks: {
              color: C.fg3,
              font: { family: "IBM Plex Mono", size: 10 },
              maxRotation: 0, autoSkip: true, maxTicksLimit: 8,
              // For views that carry both date + time in the label
              // (multiday window — "MM/DD HH:MM"), split into two lines:
              // time on top, date below. Other views pass through.
              // Chart.js renders array tick values as multi-line.
              callback: function (this: { getLabelForValue: (v: number) => string }, value) {
                const lbl = this.getLabelForValue(value as number);
                const parts = lbl.split(/\s+/);
                return parts.length === 2 ? [parts[1], parts[0]] : lbl;
              },
            },
            border: { color: C.line },
          },
          y: {
            position: "right",
            afterDataLimits: (scale) => {
              const xScale = scale.chart.scales.x;
              if (!xScale || xScale.min == null || xScale.max == null) return;
              const xLo = Math.max(0, Math.floor(xScale.min as number));
              const xHi = Math.min(visibleBarsRef.current.length - 1, Math.ceil(xScale.max as number));
              let vMin = Infinity, vMax = -Infinity;
              for (let i = xLo; i <= xHi; i++) {
                const b = visibleBarsRef.current[i];
                if (!b) continue;
                if (viewCfg.datasetType === "candlestick") {
                  if (b.low < vMin) vMin = b.low;
                  if (b.high > vMax) vMax = b.high;
                } else {
                  if (b.close < vMin) vMin = b.close;
                  if (b.close > vMax) vMax = b.close;
                }
              }
              for (const m of markersRef.current) {
                if (m.x >= xLo && m.x <= xHi) {
                  if (m.y < vMin) vMin = m.y;
                  if (m.y > vMax) vMax = m.y;
                }
              }
              if (vMin === Infinity) return;
              const pad = (vMax - vMin) * 0.06 || Math.abs(vMax) * 0.005 || 0.5;
              scale.min = vMin - pad;
              scale.max = vMax + pad;
            },
            grid: { color: C.line, drawTicks: false },
            ticks: {
              color: C.fg3,
              font: { family: "IBM Plex Mono", size: 10 },
              callback: (v) => fmtN(v as number, 3),
            },
            border: { color: C.line },
          },
        },
      },
    };

    try {
      chartRef.current = new Chart(canvas, cfg);
    } catch (err) {
      if (import.meta.env.DEV) console.warn("DetailChart: Chart init skipped", err);
    }
    return () => {
      chartRef.current?.destroy();
      chartRef.current = null;
    };
    // Structural deps only — Chart instance rebuilds when these change.
    // Per-render values (visibleBars, markers) flow through Effect B's
    // in-place mutations and are NOT listed here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, view, viewCfg.granularity, viewCfg.sessions, viewCfg.datasetType, colorMode]);

  // Effect B — mutate chart data in place on data/marker change.
  // Skips when the chart hasn't been created yet (Effect A will pick up
  // the latest snapshot via dataRef on mount).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const data = dataRef.current;
    if (!data) return;

    chart.data.labels = data.labels;
    // Find the price dataset by label so the branch is robust against future
    // dataset insertions / reorderings.
    const priceDs = chart.data.datasets.find(
      (d) => (d as { label?: string }).label === "成交价",
    ) as { data: unknown } | undefined;
    if (priceDs) {
      if (viewCfg.datasetType === "candlestick") {
        priceDs.data = visibleBars.map((b, i) => ({
          x: i,
          o: b.open,
          h: b.high,
          l: b.low,
          c: b.close,
        }));
      } else {
        priceDs.data = data.closes;
      }
    }

    // Scatter datasets — find by label so order-independent.
    const datasets = chart.data.datasets as Array<{ label?: string; data: unknown }>;
    const buyDs = datasets.find((d) => d.label === "买入");
    const sellDs = datasets.find((d) => d.label === "卖出");
    const tDs = datasets.find((d) => d.label === "做T");
    if (buyDs) (buyDs.data as unknown) = data.buys;
    if (sellDs) (sellDs.data as unknown) = data.sells;
    if (tDs) (tDs.data as unknown) = data.ts;

    // Keep scales / sessionBg / dayMarkers in sync with the new bar count.
    const xMax = data.closes.length - 1;
    const opts = chart.options as unknown as {
      scales: { x: { max: number; min: number } };
      plugins: {
        sessionBg: { barCount: number };
        dayMarkers: { bars: Candlestick[] };
        zoom: { limits: { x: { max: number } } };
      };
    };
    // Only stretch x-max to the new last bar if the user hasn't panned away
    // from the tail — keeps manual pan/zoom from being yanked on every update.
    const prevMax = chart.scales.x.max as number;
    if (prevMax >= xMax - 1) {
      opts.scales.x.max = xMax;
    }
    opts.plugins.sessionBg.barCount = data.closes.length;
    // Update the dayMarkers plugin's bars reference too.
    const opts2 = chart.options as unknown as {
      plugins: { dayMarkers: { bars: Candlestick[] } };
    };
    opts2.plugins.dayMarkers.bars = visibleBars;
    opts.plugins.zoom.limits.x.max = xMax;

    chart.update("none");

    // Re-seed Effect C's local snapshot so the next live-tick reads the
    // fresh bars/labels Effect B just installed (otherwise live-tick would
    // overwrite this mutation with its stale snapshot). lastApplied is
    // reset so the de-dup guard in tick() doesn't suppress the next push.
    if (liveStateRef.current) {
      liveStateRef.current.bars = visibleBarsRef.current.slice();
      liveStateRef.current.labels = data.labels.slice();
      liveStateRef.current.lastApplied = 0;
    }
  }, [visibleBars, markers]);

  // liveCfg is null for day/week/month/year (K-line) views; live updates
  // are active for intraday, minute, and multiday views.
  const liveCfg = viewCfg.liveCfg;
  const isLiveMode = liveCfg != null;

  // Effect C — live tick. Drives all minute-level views (intraday/minute/multiday).
  // RAF-throttled so a tight quote burst doesn't trigger N chart updates
  // per frame. Mutates Chart data in place (never the bars store) and
  // repositions a DOM pulse dot at the last bar.
  useEffect(() => {
    if (!liveCfg) return;
    const chart = chartRef.current;
    if (!chart) return;
    const seedData = dataRef.current;
    if (!seedData) return;

    liveStateRef.current = {
      bars: visibleBarsRef.current.slice(),
      labels: seedData.labels.slice(),
      rafId: null,
      lastApplied: 0,
    };

    const { periodMinutes, allowAppend } = liveCfg;

    // Find the price-line dataset by label rather than by index 0 — keeps
    // the live path robust against future dataset reorderings.
    const priceDataset = chart.data.datasets.find(
      (d) => (d as { label?: string }).label === "成交价",
    ) as { data: unknown } | undefined;

    const tick = () => {
      const state = liveStateRef.current;
      if (!state) return;
      state.rafId = null;
      const q = useQuotesStore.getState().quotesBySymbol[symbol];
      const lastDone = q?.last_done;
      if (lastDone == null || lastDone === 0) {
        // Degraded quote (e.g. halted symbol) — hide the pulse so it doesn't
        // animate against a stale position. The next valid push re-shows it.
        pulseRef.current?.classList.remove("visible", "down");
        return;
      }
      const nowMs = Date.now();

      // RAF can fire faster than the quote stream — skip if neither price
      // nor bucket changed since last apply.
      const lastTs = state.bars[state.bars.length - 1]?.timestamp;
      const lastBucket = lastTs
        ? bucketKey(Date.parse(lastTs), periodMinutes)
        : -1;
      if (lastDone === state.lastApplied && bucketKey(nowMs, periodMinutes) === lastBucket) {
        return;
      }

      const out = applyLiveTick({
        bars: state.bars,
        labels: state.labels,
        lastDone,
        nowMs,
        periodMinutes,
        allowAppend,
      });
      // If the helper bailed (stale guard, empty bars, etc.) we still want
      // to position the pulse dot — but no chart mutation is needed.
      const dataChanged = out.bars !== state.bars;
      state.bars = out.bars;
      state.labels = out.labels;
      state.lastApplied = lastDone;

      const ch = chartRef.current;
      if (!ch || !priceDataset) return;

      if (dataChanged) {
        ch.data.labels = out.labels;
        const priceData = priceDataset.data as unknown as number[];
        if (out.crossedBoundary) {
          priceData.push(lastDone);
        } else {
          priceData[priceData.length - 1] = lastDone;
        }
        const xMax = priceData.length - 1;
        const opts = ch.options as unknown as {
          scales: { x: { max: number; min: number } };
          plugins: { zoom: { limits: { x: { max: number } } } };
        };
        // Stretch right edge only if user hasn't manually panned away.
        if ((ch.scales.x.max as number) >= xMax - 1) {
          opts.scales.x.max = xMax;
        }
        opts.plugins.zoom.limits.x.max = xMax;
        ch.update("none");
      }

      // Position the pulse dot at the last (x, y) data point.
      const pulse = pulseRef.current;
      if (pulse) {
        const priceArr = priceDataset.data as unknown as number[];
        const lastIdx = priceArr.length - 1;
        const px = ch.scales.x.getPixelForValue(lastIdx);
        const py = ch.scales.y.getPixelForValue(lastDone);
        if (Number.isFinite(px) && Number.isFinite(py)) {
          pulse.style.left = `${px}px`;
          pulse.style.top = `${py}px`;
          pulse.classList.add("visible");
          const isDown = (q?.change ?? 0) < 0;
          pulse.classList.toggle("down", isDown);
        }
      }
    };

    // Each store push schedules a single RAF.
    const unsub = useQuotesStore.subscribe((s, prev) => {
      const next = s.quotesBySymbol[symbol]?.last_done;
      const old = prev.quotesBySymbol[symbol]?.last_done;
      if (next === old) return;
      const state = liveStateRef.current;
      if (!state || state.rafId != null) return;
      state.rafId = requestAnimationFrame(tick);
    });

    // Kick once at mount so the dot is positioned on the most-recent
    // already-pushed quote without waiting for the next push.
    liveStateRef.current.rafId = requestAnimationFrame(tick);

    return () => {
      unsub();
      const state = liveStateRef.current;
      if (state?.rafId != null) cancelAnimationFrame(state.rafId);
      liveStateRef.current = null;
      pulseRef.current?.classList.remove("visible", "down");
    };
    // Re-seeds on view changes (view/granularity/symbol). The other deps
    // are read via refs at tick-time, not at effect-mount time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, viewCfg.granularity, symbol]);

  // View switch destroys + recreates the chart, so reset the zoomed
  // indicator independently.
  useEffect(() => { setIsZoomed(false); }, [view]);

  const handleResetZoom = () => {
    chartRef.current?.resetZoom();
    setIsZoomed(false);
  };

  return (
    <div className="chart-canvas-wrap">
      <canvas ref={canvasRef} />
      {isLiveMode && <div ref={pulseRef} className="live-pulse" aria-hidden />}
      {isZoomed && (
        <button
          className="chart-reset-btn"
          onClick={handleResetZoom}
          title="重置缩放"
        >
          ↺ 重置
        </button>
      )}
    </div>
  );
}
