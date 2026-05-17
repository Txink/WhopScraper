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

import zoomPlugin from "chartjs-plugin-zoom";
import type { Candlestick, Trade } from "../../api/domain-types";
import { sessionBgPlugin } from "./sessionBgPlugin";
import { crosshairPlugin } from "./crosshairPlugin";
import { minMaxLabelsPlugin } from "./minMaxLabelsPlugin";
import { buildSessionSlots } from "./sessionSlots";
import type { ViewType, ViewConfig } from "./viewConfig";
import { fmtBjHM, fmtBjDate, fmtBjWeekISO, fmtBjMonth, fmtBjYear, classifyETSession, tradingDayOfET, currentTradingDay } from "./timeFmt";
import { usePrefsStore } from "../../stores/prefs";
import { useQuotesStore } from "../../stores/quotes";
import { applyLiveTick, bucketKey } from "./liveTick";
import { findBarForTrade, buildDayBoundaries } from "./tradeToBar";

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
    const B_COLOR = "#f43f5e";
    const S_COLOR = "#14b8a6";
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
    const { enabled, bars: pluginBars, showLabels } = opts as {
      enabled: boolean;
      bars: Candlestick[];
      showLabels?: boolean;
    };
    if (!enabled || !pluginBars || pluginBars.length === 0) return;
    const ctx = chart.ctx;
    const xs = chart.scales.x;
    const ys = chart.scales.y;
    const area = chart.chartArea;
    if (!xs || !ys || !area) return;
    let prevDay: string | null = null;
    ctx.save();
    // Brighter line for multiday since these ARE the primary ticks.
    // Match the horizontal grid color so vertical day-boundary ticks and
    // the left border read as part of the same chart frame.
    ctx.strokeStyle = C.line;
    ctx.lineWidth = 1;
    // Multiday uses solid day-boundary ticks + left border; the dashed
    // variant is reserved for the non-label fallback path.
    if (!showLabels) ctx.setLineDash([3, 3]);
    ctx.font = "500 9px 'IBM Plex Mono', ui-monospace, monospace";
    ctx.fillStyle = "#566071";  // C.fg3
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let i = 0; i < pluginBars.length; i++) {
      const b = pluginBars[i]!;
      if (!b.timestamp) continue;
      const day = tradingDayOfET(b.timestamp);
      // First-day: draw a vertical line at the chart's left edge (serves as
      // the multiday view's left border, since the x-grid is disabled here),
      // and left-align the label so it renders fully without clipping.
      if (prevDay === null && showLabels && i === 0) {
        const x = xs.getPixelForValue(i);
        if (Number.isFinite(x)) {
          ctx.beginPath();
          ctx.moveTo(x, ys.top);
          ctx.lineTo(x, ys.bottom);
          ctx.stroke();
          const label = fmtBjDate(b.timestamp);
          ctx.textAlign = "left";
          ctx.fillText(label, x + 2, area.bottom + 4);
          ctx.textAlign = "center";
        }
      }
      if (prevDay !== null && day !== prevDay) {
        const x = xs.getPixelForValue(i);
        if (Number.isFinite(x)) {
          ctx.beginPath();
          ctx.moveTo(x, ys.top);
          ctx.lineTo(x, ys.bottom);
          ctx.stroke();
          if (showLabels) {
            // Label below the chart area showing this day's date.
            const label = fmtBjDate(b.timestamp);
            ctx.fillText(label, x, area.bottom + 4);
          }
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
  onHoverBar?: (barIndex: number | null) => void;
  /** Fires when the user's pan brings the visible window within
   *  ~PAN_BACK_THRESHOLD bars of the loaded-data front. The parent
   *  is expected to fetch older bars and prepend them via the
   *  candlesticks store (dedupes in-flight requests itself). */
  onNeedOlder?: () => void;
}

/** How close to index 0 (in bars) before we ask the parent to extend
 *  the loaded history. Generous so the fetch starts before the user
 *  hits the actual edge and sees a "stuck" feeling. */
const PAN_BACK_THRESHOLD = 20;

/**
 * Detail chart: price line + BUY/SELL scatter markers. Markers are snapped
 * to the nearest bar in time so they always land on the x-axis grid.
 */
export function DetailChart({
  symbol, bars, view, viewCfg, trades, onHoverBar, onNeedOlder,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);
  const [isZoomed, setIsZoomed] = useState(false);
  const onHoverBarRef = useRef<((idx: number | null) => void) | undefined>(onHoverBar);
  useEffect(() => { onHoverBarRef.current = onHoverBar; }, [onHoverBar]);
  const onNeedOlderRef = useRef<(() => void) | undefined>(onNeedOlder);
  useEffect(() => { onNeedOlderRef.current = onNeedOlder; }, [onNeedOlder]);
  /** Timestamp of the leftmost bar at the previous render — used by
   *  Effect B to detect "older bars were prepended" and shift the
   *  visible x range by the prepend count so the user keeps looking
   *  at the same bars after the data extends. */
  const prevFirstTsRef = useRef<string | undefined>(undefined);
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
    const isLineView =
      view === "intraday" || view === "minute" || view === "multiday";
    const periodMs = (viewCfg.liveCfg?.periodMinutes ?? 0) * 60 * 1000;
    const dayBoundaries = isLineView ? buildDayBoundaries(barTs) : undefined;
    const grouped = new Map<number, Trade[]>();
    for (const t of visibleTrades) {
      const tts = Date.parse(t.ts);
      const best = findBarForTrade(barTs, tts, periodMs, isLineView, dayBoundaries);
      if (best < 0) continue;
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
            up: cssVar("--candle-up-color", "#147a48"),
            down: cssVar("--candle-down-color", "#952a2a"),
            unchanged: C.fg3,
          },
          backgroundColors: {
            up: cssVar("--candle-up-color", "#147a48"),
            down: cssVar("--candle-down-color", "#952a2a"),
            unchanged: C.fg3,
          },
          borderColor: cssVar("--candle-up-color", "#147a48"),
          backgroundColor: cssVar("--candle-up-color", "#147a48"),
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
            backgroundColor: "#f43f5e",
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
            backgroundColor: "#14b8a6",
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
        interaction: { mode: "index", intersect: false, axis: "x" },
        onHover: (event, _elements, chart) => {
          const e = event as { x?: number | null };
          const px = e?.x;
          if (px == null) {
            onHoverBarRef.current?.(null);
            return;
          }
          const xScale = chart.scales.x;
          if (!xScale) {
            onHoverBarRef.current?.(null);
            return;
          }
          const v = xScale.getValueForPixel?.(px);
          if (v == null || !Number.isFinite(v)) {
            onHoverBarRef.current?.(null);
            return;
          }
          const n = visibleBarsRef.current.length;
          if (n === 0) {
            onHoverBarRef.current?.(null);
            return;
          }
          const idx = Math.max(0, Math.min(n - 1, Math.round(v)));
          onHoverBarRef.current?.(idx);
          // Stash for crosshair to read.
          (chart as unknown as { $hoverBarIndex?: number | null }).$hoverBarIndex = idx;
          chart.draw();
        },
        // Y-axis labels live on the right; left side has nothing to
        // anchor, so flatten the left/right chartArea inset and let the
        // canvas hug the card padding. Top/bottom default to 0 too.
        // Multiday view reserves bottom space for the dayMarkersPlugin
        // day labels (x-axis ticks are disabled, so Chart.js doesn't
        // auto-reserve space below the chart area).
        layout: {
          padding: {
            left: 0,
            right: 0,
            top: 0,
            bottom: view === "multiday" ? 4 : 0,
          },
        },
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
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
            showLabels: view === "multiday",
          },
          zoom: {
            pan: {
              enabled: view !== "multiday", mode: "x", threshold: 4,
              onPanComplete: ({ chart }) => {
                setIsZoomed(true);
                chart.update("none");
                // If the user has panned close to the left edge of the
                // loaded data, ask the parent for older bars. Parent
                // dedupes in-flight fetches.
                const xMin = chart.scales.x.min as number;
                if (Number.isFinite(xMin) && xMin <= PAN_BACK_THRESHOLD) {
                  onNeedOlderRef.current?.();
                }
              },
            },
            zoom: {
              wheel: { enabled: view !== "multiday", speed: 0.05 },
              pinch: { enabled: view !== "multiday" },
              mode: "x",
              onZoomComplete: ({ chart }) => { setIsZoomed(true); chart.update("none"); },
            },
            // Candle views cap the visible window at 250 bars so the user
            // can't zoom out into an unreadable thumbnail. minRange = 5
            // applies to every view. Line views (intraday/multiday) skip
            // the upper cap — they show all loaded bars by design.
            limits: {
              x: {
                min: 0,
                max: xMax,
                minRange: 5,
                ...(viewCfg.datasetType === "candlestick" ? { maxRange: 250 } : {}),
              },
            },
          },
        },
        scales: {
          x: {
            min: xMin, max: xMax,
            grid: view === "multiday"
              ? { display: false }
              : { color: C.line, drawTicks: false },
            ticks: view === "multiday"
              ? { display: false }
              : {
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

    const onLeave = () => {
      onHoverBarRef.current?.(null);
      const ch = chartRef.current;
      if (ch) {
        (ch as unknown as { $hoverBarIndex?: number | null }).$hoverBarIndex = null;
        ch.draw();
      }
    };
    canvas.addEventListener("mouseleave", onLeave);
    try {
      chartRef.current = new Chart(canvas, cfg);
    } catch (err) {
      if (import.meta.env.DEV) console.warn("DetailChart: Chart init skipped", err);
    }
    return () => {
      canvas.removeEventListener("mouseleave", onLeave);
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
    // Detect a prepend (older bars added at the front by pan-back) by
    // finding the previous first-bar timestamp in the new array. If it
    // moved to index N, shift the visible range by N so the user keeps
    // looking at the same bars they were on before the fetch.
    const prevFirstTs = prevFirstTsRef.current;
    const newFirstTs = visibleBars[0]?.timestamp;
    if (prevFirstTs && newFirstTs && prevFirstTs !== newFirstTs) {
      const shift = visibleBars.findIndex((b) => b.timestamp === prevFirstTs);
      if (shift > 0) {
        const curMin = chart.scales.x.min as number;
        const curMax = chart.scales.x.max as number;
        opts.scales.x.min = curMin + shift;
        opts.scales.x.max = curMax + shift;
      }
    }
    prevFirstTsRef.current = newFirstTs ?? undefined;
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
        // Candle datasets carry {x,o,h,l,c} objects; line datasets carry
        // plain close numbers. Mirror whichever shape the dataset uses so
        // the live tick works for both intraday/multiday (line) and
        // minute (candlestick).
        let dataLen: number;
        if (viewCfg.datasetType === "candlestick") {
          const candleData = priceDataset.data as Array<{
            x: number; o: number; h: number; l: number; c: number;
          }>;
          const lastBarIdx = out.bars.length - 1;
          const lastBar = out.bars[lastBarIdx]!;
          if (out.crossedBoundary) {
            candleData.push({
              x: lastBarIdx,
              o: lastBar.open, h: lastBar.high, l: lastBar.low, c: lastBar.close,
            });
          } else if (candleData.length > 0) {
            const last = candleData[candleData.length - 1]!;
            last.o = lastBar.open;
            last.h = lastBar.high;
            last.l = lastBar.low;
            last.c = lastBar.close;
          }
          dataLen = candleData.length;
        } else {
          const priceData = priceDataset.data as unknown as number[];
          if (out.crossedBoundary) {
            priceData.push(lastDone);
          } else {
            priceData[priceData.length - 1] = lastDone;
          }
          dataLen = priceData.length;
        }
        const xMax = dataLen - 1;
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
      {isLiveMode && viewCfg.livePulseEnabled && <div ref={pulseRef} className="live-pulse" aria-hidden />}
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
