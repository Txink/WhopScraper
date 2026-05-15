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
import { useQuotesStore } from "../../stores/quotes";
import { applyLiveTick, bucketKey, liveConfig } from "./liveTick";

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

  // Derived chart data — kept in a ref so Effect A (chart create) reads the
  // latest closes/labels/markers at mount time without listing them in deps,
  // while Effect B mutates them on subsequent changes.
  const dataRef = useRef<{
    labels: string[];
    closes: number[];
    buys: { x: number; y: number; raw: Trade }[];
    sells: { x: number; y: number; raw: Trade }[];
  } | null>(null);

  const visibleBarsRef = useRef<Candlestick[]>([]);
  const markersRef = useRef<{ x: number; y: number; raw: Trade }[]>([]);
  const avgCostRef = useRef<number | null>(null);
  const showAvgCostRef = useRef<boolean>(false);

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

  const chartData = useMemo(() => {
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
    return { labels, closes, buys, sells };
  }, [visibleBars, period, markers]);

  // Mirror into a ref so Effect A (mount-once) can read latest at create-time
  // without taking a deps subscription.
  useEffect(() => { dataRef.current = chartData; }, [chartData]);

  // Keep refs in sync each render so chart callbacks read the latest values
  // without forcing the chart to rebuild.
  visibleBarsRef.current = visibleBars;
  markersRef.current = markers;
  avgCostRef.current = avgCost;
  showAvgCostRef.current = showAvgCost;

  // Effect A — create the Chart instance once per structural-deps combo
  // (period/granularity/session/color-mode). visibleBars / markers / avgCost
  // flow through Effect B as in-place mutations so quote ticks don't tear
  // the chart down. Symbol switch is structural too (chart cleanly resets).
  useEffect(() => {
    const canvas = canvasRef.current;
    const data = dataRef.current;
    if (!canvas || !data || data.closes.length === 0) return;

    // Initial visible window per period — sized so the default view shows
    // ~1 reading-unit of data and the rest is reachable by dragging.
    const INITIAL_VISIBLE_COUNT: Record<Period, number> = {
      today: data.closes.length,
      "5": 78, "7": 78, "15": 52, "30": 20, "60": 25, "90": 30,
    };
    const initialCount = Math.min(
      INITIAL_VISIBLE_COUNT[period] ?? data.closes.length,
      data.closes.length,
    );
    const xMax = data.closes.length - 1;
    const xMin = Math.max(0, xMax - initialCount + 1);

    // Snapshot avgCost / showAvgCost at mount time. Subsequent changes
    // flow through Effect B (it adds/removes the dataset entry as needed).
    const initialAvgCost = avgCost;
    const initialShowAvgCost = showAvgCost;

    const cfg: ChartConfiguration = {
      type: "line",
      data: {
        labels: data.labels,
        datasets: [
          {
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
            borderWidth: 1.6, fill: true, tension: 0.26,
            pointRadius: 0, pointHoverRadius: 0,
            order: 4,
          },
          ...(initialAvgCost != null && initialShowAvgCost ? [{
            label: "成本均价",
            data: data.closes.map(() => initialAvgCost),
            borderColor: C.info,
            borderWidth: 1.2,
            borderDash: [4, 4],
            fill: false, pointRadius: 0, tension: 0,
            order: 3,
          }] : []),
          {
            label: "买入",
            type: "scatter" as const,
            data: data.buys,
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
            data: data.sells,
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
      plugins: [sessionBgPlugin, crosshairPlugin, minMaxLabelsPlugin],
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
                  const raw = (item.raw as { raw?: Trade }).raw;
                  if (!raw) return "";
                  return `${raw.side === "BUY" ? "买入" : "卖出"} · ${fmtBjRel(raw.ts)}`;
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
                  const raw = (item.raw as { raw?: Trade }).raw;
                  if (!raw) return "";
                  return ` ${fmtN(raw.qty, 0)} 股 @ $${fmtN(raw.price)}${raw.tag ? "  · " + raw.tag : ""}`;
                }
                return ` 价格 $${fmtN(item.parsed.y as number)}`;
              },
            },
          },
          sessionBg: {
            enabled: period === "today"
              && (todayGranularity === "分时" || todaySessions === "all"),
            granularity: todayGranularity,
            barCount: data.closes.length,
            session: todaySessions,
          },
          zoom: {
            pan: {
              enabled: true, mode: "x", threshold: 4,
              onPanComplete: ({ chart }) => { setIsZoomed(true); chart.update("none"); },
            },
            zoom: {
              wheel: { enabled: true, modifierKey: "shift" },
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
            },
            border: { color: C.line },
          },
          y: {
            position: "right",
            afterDataLimits: (scale) => {
              const xScale = scale.chart.scales.x;
              if (!xScale || xScale.min == null || xScale.max == null) return;
              // Read live closes/markers/avg-cost via refs so the y-fit
              // reflects whatever Effect B / live-tick most recently wrote.
              const closes = dataRef.current?.closes ?? [];
              const xLo = Math.max(0, Math.floor(xScale.min as number));
              const xHi = Math.min(closes.length - 1, Math.ceil(xScale.max as number));
              let vMin = Infinity, vMax = -Infinity;
              for (let i = xLo; i <= xHi; i++) {
                const v = closes[i];
                if (v == null) continue;
                if (v < vMin) vMin = v;
                if (v > vMax) vMax = v;
              }
              for (const m of markersRef.current) {
                if (m.x >= xLo && m.x <= xHi) {
                  if (m.y < vMin) vMin = m.y;
                  if (m.y > vMax) vMax = m.y;
                }
              }
              const avgRef = avgCostRef.current;
              if (showAvgCostRef.current && avgRef != null) {
                if (avgRef < vMin) vMin = avgRef;
                if (avgRef > vMax) vMax = avgRef;
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
    // Structural deps only — non-listed values are read via refs in callbacks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, period, todayGranularity, todaySessions, colorMode]);

  // Effect B — mutate chart data in place on data/marker/avg-cost change.
  // Skips when the chart hasn't been created yet (Effect A will pick up
  // the latest snapshot via dataRef on mount).
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const data = dataRef.current;
    if (!data) return;

    chart.data.labels = data.labels;
    // dataset 0 is the price line — replace its data with the latest closes.
    (chart.data.datasets[0]!.data as unknown as number[]) = data.closes;

    // Find / sync the avg-cost dataset. It's optional — present when
    // (avgCost != null && showAvgCost). We never reorder the underlying
    // dataset positions; remove vs insert in-place.
    const datasets = chart.data.datasets as Array<{ label?: string; data: unknown }>;
    const avgIdx = datasets.findIndex((d) => d.label === "成本均价");
    if (avgCost != null && showAvgCost) {
      const avgData = data.closes.map(() => avgCost);
      if (avgIdx === -1) {
        datasets.splice(1, 0, {
          label: "成本均价",
          data: avgData,
          borderColor: C.info,
          borderWidth: 1.2,
          borderDash: [4, 4],
          fill: false, pointRadius: 0, tension: 0,
          order: 3,
        } as unknown as typeof datasets[number]);
      } else {
        (datasets[avgIdx]!.data as unknown as number[]) = avgData;
      }
    } else if (avgIdx !== -1) {
      datasets.splice(avgIdx, 1);
    }

    // Scatter datasets — find by label so order-independent.
    const buyDs = datasets.find((d) => d.label === "买入");
    const sellDs = datasets.find((d) => d.label === "卖出");
    if (buyDs) (buyDs.data as unknown) = data.buys;
    if (sellDs) (sellDs.data as unknown) = data.sells;

    // Keep scales / sessionBg in sync with the new bar count.
    const xMax = data.closes.length - 1;
    const opts = chart.options as unknown as {
      scales: { x: { max: number; min: number } };
      plugins: { sessionBg: { barCount: number }; zoom: { limits: { x: { max: number } } } };
    };
    // Only stretch x-max to the new last bar if the user hasn't panned away
    // from the tail — keeps manual pan/zoom from being yanked on every update.
    const prevMax = chart.scales.x.max as number;
    if (prevMax >= xMax - 1) {
      opts.scales.x.max = xMax;
    }
    opts.plugins.sessionBg.barCount = data.closes.length;
    opts.plugins.zoom.limits.x.max = xMax;

    chart.update("none");
  }, [visibleBars, markers, avgCost, showAvgCost]);

  // liveCfg is null for 30D/60D/90D (daily K) and the today/分时, today/Nmin,
  // 5D, 7D, 15D views all get a (periodMinutes, allowAppend) pair.
  const liveCfg = liveConfig(period, todayGranularity);
  const isLiveMode = liveCfg != null;

  // Effect C — live tick. Drives all minute-level views (1/5/15-min).
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
    // the live path robust against future dataset reorderings (avg-cost
    // is inserted/removed dynamically by Effect B).
    const priceDataset = chart.data.datasets.find(
      (d) => (d as { label?: string }).label === "成交价",
    ) as { data: unknown } | undefined;

    const tick = () => {
      const state = liveStateRef.current;
      if (!state) return;
      state.rafId = null;
      const q = useQuotesStore.getState().quotesBySymbol[symbol];
      const lastDone = q?.last_done;
      if (lastDone == null || lastDone === 0) return;
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
    // Re-seeds on view changes (period/granularity/symbol). The other deps
    // are read via refs at tick-time, not at effect-mount time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [period, todayGranularity, symbol]);

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
