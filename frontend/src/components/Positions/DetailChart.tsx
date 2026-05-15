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
import type { Period } from "../../stores/candlesticks";
import { fmtBjHM, fmtBjDate, fmtBjRel, classifyETSession, tradingDayOfET, currentTradingDay } from "./timeFmt";
import { usePrefsStore } from "../../stores/prefs";

Chart.register(
  LineController, ScatterController,
  LineElement, PointElement,
  LinearScale, CategoryScale,
  Filler, Tooltip,
  zoomPlugin,
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

interface Props {
  symbol: string;
  bars: Candlestick[];
  period: Period;
  trades: Trade[];
  avgCost: number | null;
  /** When false (default), the avg-cost reference line is omitted from the
   *  chart. The legend toggle in DetailPane controls this. */
  showAvgCost: boolean;
  /** Today-only sub-options that drive the session-background overlay
   *  and the client-side session filtering for 分时 mode. */
  todayGranularity: "分时" | "1min" | "2min" | "3min" | "5min";
  todaySessions: "regular" | "pre" | "post" | "overnight" | "all";
}

/**
 * Detail chart: price line + BUY/SELL scatter markers + avg-cost reference
 * line. Markers are snapped to the nearest bar in time so they always land
 * on the x-axis grid.
 */
export function DetailChart({
  symbol, bars, period, trades, avgCost, showAvgCost,
  todayGranularity, todaySessions,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);
  const [isZoomed, setIsZoomed] = useState(false);
  // Subscribe to prefs so the chart rebuilds (with new BUY/SELL marker
  // colors etc.) when the user toggles US/CN color convention.
  const colorMode = usePrefsStore((s) => s.colorMode);

  // Snap each trade to the index of its nearest bar in time. Skip trades
  // outside the chart window so they don't anchor to (0, 0) of the axis.
  // Today's intraday flow:
  //   1. Trim raw bars to TODAY's trading day (ET 4:00 rollover semantics)
  //   2. Further trim by selected session for 分时 mode
  //   3. Only 分时 pads to a full slot array (so未到的 sessions占住 x 轴);
  //      K-line granularities (2/3/5min) skip padding and render real bars
  //      only — those views don't fixed-window the same way LongBridge does.
  //
  // Non-today periods skip all of this and use bars verbatim.
  const visibleBars: Candlestick[] = useMemo(() => {
    if (period !== "today") return bars;
    const today = currentTradingDay();
    const trimmed = bars.filter((b) => {
      if (!b.timestamp) return false;
      if (tradingDayOfET(b.timestamp) !== today) return false;
      if (todayGranularity !== "分时") return true; // K-line shows all of today
      if (todaySessions === "all") return true;
      if (todaySessions === "regular") {
        return classifyETSession(b.timestamp) === "regular";
      }
      return classifyETSession(b.timestamp) === todaySessions;
    });
    // Padding is 分时-only — K-line views render whatever bars exist.
    if (todayGranularity !== "分时") return trimmed;
    return buildSessionSlots(trimmed, todayGranularity, todaySessions);
  }, [bars, period, todayGranularity, todaySessions]);

  const visibleTrades: Trade[] = useMemo(() => {
    if (period !== "today") return trades;
    const today = currentTradingDay();
    return trades.filter((t) => {
      if (tradingDayOfET(t.ts) !== today) return false;
      if (todayGranularity !== "分时" || todaySessions === "all") return true;
      return classifyETSession(t.ts) === todaySessions;
    });
  }, [trades, period, todayGranularity, todaySessions]);

  const markers = useMemo(() => {
    if (visibleBars.length === 0) return [];
    const barTs = visibleBars.map((b) => b.timestamp ? Date.parse(b.timestamp) : 0);
    // Snap tolerance reflects bar granularity: intraday bars (5/15-min) tolerate
    // up to 1h; daily bars tolerate up to 12h so weekend/after-hours fills still
    // anchor to the right calendar day.
    const isIntradayPeriod = period === "today" || period === "5" || period === "7" || period === "15";
    const tolerance = isIntradayPeriod ? 60 * 60 * 1000 : 12 * 3600 * 1000;
    return visibleTrades
      .map((t) => {
        const tts = Date.parse(t.ts);
        let best = -1;
        let bestD = Infinity;
        for (let i = 0; i < barTs.length; i++) {
          const d = Math.abs(barTs[i]! - tts);
          if (d < bestD) { bestD = d; best = i; }
        }
        if (bestD > tolerance) return null;
        return { x: best, y: t.price, raw: t };
      })
      .filter((m): m is { x: number; y: number; raw: Trade } => m != null);
  }, [visibleBars, visibleTrades, period]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || visibleBars.length === 0) return;

    // Initial visible window per period — sized so the default view shows
    // ~1 reading-unit of data and the rest is reachable by dragging.
    // Today (any granularity / session) fits everything in axis; longer
    // periods narrow so the user can pan to see history.
    const INITIAL_VISIBLE_COUNT: Record<Period, number> = {
      today: visibleBars.length,
      "5": 78,
      "7": 78,
      "15": 52,
      "30": 20,
      "60": 25,
      "90": 30,
    };
    const initialCount = Math.min(
      INITIAL_VISIBLE_COUNT[period] ?? visibleBars.length,
      visibleBars.length,
    );
    const xMax = visibleBars.length - 1;
    const xMin = Math.max(0, xMax - initialCount + 1);

    // Label format depends on bar granularity:
    //   today: HH:MM (intraday bars within one day)
    //   5/7/15D: MM/DD HH:MM (intraday bars stitched across days)
    //   30/60/90D: MM/DD (one bar per trading day)
    const SHOW_DATE_IN_LABEL = new Set<Period>(["5", "7", "15"]);
    const labels = visibleBars.map((b) => {
      if (!b.timestamp) return "";
      if (period === "today") return fmtBjHM(b.timestamp);
      if (SHOW_DATE_IN_LABEL.has(period)) {
        return `${fmtBjDate(b.timestamp)} ${fmtBjHM(b.timestamp)}`;
      }
      return fmtBjDate(b.timestamp);
    });
    const closes = visibleBars.map((b) => b.close);
    const buys = markers.filter((m) => m.raw.side === "BUY");
    const sells = markers.filter((m) => m.raw.side === "SELL");

    const cfg: ChartConfiguration = {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "成交价",
            data: closes,
            borderColor: C.price,
            backgroundColor: (ctx: ScriptableContext<"line">) => {
              const area = ctx.chart.chartArea;
              if (!area) return "transparent";
              const grad = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
              grad.addColorStop(0, C.priceFill);
              grad.addColorStop(1, "rgba(0,0,0,0)");
              return grad;
            },
            borderWidth: 1.6, fill: true, tension: 0.26,
            pointRadius: 0, pointHoverRadius: 0,
            order: 4,
          },
          // Avg-cost reference line is opt-in (legend toggle). Hidden by
          // default so the price line isn't visually anchored to a dashed
          // horizontal that often sits well above/below the visible window.
          ...(avgCost != null && showAvgCost ? [{
            label: "成本均价",
            data: closes.map(() => avgCost),
            borderColor: C.info,
            borderWidth: 1.2,
            borderDash: [4, 4],
            fill: false, pointRadius: 0, tension: 0,
            order: 3,
          }] : []),
          {
            label: "买入",
            type: "scatter" as const,
            data: buys,
            // Up/down colors come from --up-color / --down-color so the
            // user's prefs (US vs CN convention) flow into the chart.
            backgroundColor: cssVar("--up-color", "#3dd68c"),
            borderColor: C.bg0,
            borderWidth: 2.5,
            pointRadius: 8, pointHoverRadius: 10,
            pointStyle: "triangle" as const,
            rotation: 0,
            order: 1,
            parsing: false as const,
          } as ChartConfiguration["data"]["datasets"][number],
          {
            label: "卖出",
            type: "scatter" as const,
            data: sells,
            backgroundColor: cssVar("--down-color", "#ef5b5b"),
            borderColor: C.bg0,
            borderWidth: 2.5,
            pointRadius: 8, pointHoverRadius: 10,
            pointStyle: "triangle" as const,
            rotation: 180,
            order: 1,
            parsing: false as const,
          } as ChartConfiguration["data"]["datasets"][number],
        ],
      },
      plugins: [
        sessionBgPlugin,
        crosshairPlugin,
        minMaxLabelsPlugin,
      ],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 240 },
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: "#0b0f14",
            borderColor: C.line,
            borderWidth: 1,
            padding: 10,
            // Anchor at the cursor, not at the nearest data point.
            // Combined with the crosshair plugin, the popup tracks the
            // mouse so reading "time + price at this x" is one glance.
            position: "cursor" as unknown as undefined,
            caretSize: 0,
            caretPadding: 8,
            // Single-point tooltip — Chart.js otherwise emits one entry per
            // dataset (line + avg-cost + scatter), which crowds the popup.
            // We only need the price reading at the hovered x.
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
                  const raw = (item.raw as { raw?: Trade }).raw;
                  if (!raw) return "";
                  return `${raw.side === "BUY" ? "买入" : "卖出"} · ${fmtBjRel(raw.ts)}`;
                }
                // Line tooltip — show full BJ wall-clock for the bar so
                // intraday vs daily reads identically (the x-axis label
                // is intentionally short to keep ticks legible).
                const bar = visibleBars[item.dataIndex];
                if (bar?.timestamp) return fmtBjRel(bar.timestamp);
                return item.label;
              },
              label: (item) => {
                const ds = item.dataset as { type?: string; label?: string };
                if (ds.type === "scatter") {
                  const raw = (item.raw as { raw?: Trade }).raw;
                  if (!raw) return "";
                  return ` ${fmtN(raw.qty, 0)} 股 @ $${fmtN(raw.price)}${raw.tag ? "  · " + raw.tag : ""}`;
                }
                return ` 价格 $${fmtN(item.parsed.y as number)}`;
              },
            },
          },
          // Pre/regular/post session background — only when on today's
          // intraday view with "含盘前/盘后" selected.
          sessionBg: {
            // Show the session watermark for every today/分时 selection so
            // 盘前/盘中/盘后/夜盘/全部 are each clearly labeled (matches
            // LongBridge App's mobile chart). For K-line granularities
            // (2/3/5min) we still only label when "all" is selected since
            // there's just one section otherwise.
            enabled: period === "today"
              && (todayGranularity === "分时" || todaySessions === "all"),
            granularity: todayGranularity,
            barCount: visibleBars.length,
            session: todaySessions,
          },
          // Drag along the x-axis to scrub through time; shift+wheel or pinch
          // to zoom in on a slice. The y-axis stays auto-fit so prices keep
          // their scale as you pan. limits.x.minRange clamps how tight you
          // can zoom so individual bars stay readable.
          zoom: {
            pan: {
              enabled: true,
              mode: "x",
              threshold: 4,
              onPanComplete: ({ chart }) => {
                setIsZoomed(true);
                // Trigger a non-animated update so `afterDataLimits` on y
                // recomputes against the new x range.
                chart.update("none");
              },
            },
            zoom: {
              wheel: { enabled: true, modifierKey: "shift" },
              pinch: { enabled: true },
              mode: "x",
              onZoomComplete: ({ chart }) => {
                setIsZoomed(true);
                chart.update("none");
              },
            },
            limits: {
              // Clamp pan/zoom to the actual data range so users can't drag
              // into empty whitespace beyond the first/last bar.
              x: { min: 0, max: xMax, minRange: 5 },
            },
          },
        },
        scales: {
          x: {
            // Category axis indexed by bar position; setting min/max trims
            // the visible window so pan can scroll horizontally into the
            // off-screen bars.
            min: xMin,
            max: xMax,
            grid: { color: C.line, drawTicks: false },
            ticks: {
              color: C.fg3,
              font: { family: "IBM Plex Mono", size: 10 },
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 8,
            },
            border: { color: C.line },
          },
          y: {
            position: "right",
            // Y range auto-fits the currently-visible x window so prices
            // stay readable as the user pans/zooms. `afterDataLimits`
            // fires on every chart update (including pan/zoom) and
            // overrides Chart.js's full-data-derived bounds.
            afterDataLimits: (scale) => {
              const xScale = scale.chart.scales.x;
              if (!xScale || xScale.min == null || xScale.max == null) return;
              const xLo = Math.max(0, Math.floor(xScale.min as number));
              const xHi = Math.min(closes.length - 1, Math.ceil(xScale.max as number));
              let vMin = Infinity;
              let vMax = -Infinity;
              for (let i = xLo; i <= xHi; i++) {
                const v = closes[i];
                if (v == null) continue;
                if (v < vMin) vMin = v;
                if (v > vMax) vMax = v;
              }
              // Include visible markers and avg-cost so they don't get
              // clipped on the edge.
              for (const m of markers) {
                if (m.x >= xLo && m.x <= xHi) {
                  if (m.y < vMin) vMin = m.y;
                  if (m.y > vMax) vMax = m.y;
                }
              }
              if (showAvgCost && avgCost != null) {
                if (avgCost < vMin) vMin = avgCost;
                if (avgCost > vMax) vMax = avgCost;
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
  }, [visibleBars, period, visibleTrades, markers, avgCost, showAvgCost, todayGranularity, todaySessions, colorMode]);

  // Period switch destroys + recreates the chart, so reset the zoomed
  // indicator independently.
  useEffect(() => { setIsZoomed(false); }, [period]);

  const handleResetZoom = () => {
    chartRef.current?.resetZoom();
    setIsZoomed(false);
  };

  return (
    <div className="chart-canvas-wrap">
      <canvas ref={canvasRef} />
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
