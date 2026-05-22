import { useEffect, useMemo, useRef, useState } from "react";
import {
  Chart,
  type ChartConfiguration,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
} from "chart.js";
import { api } from "../../api/http";
import type { Candlestick } from "../../api/domain-types";
import { tradingDayOfET } from "./timeFmt";
import { crosshairPlugin } from "./crosshairPlugin";

Chart.register(
  LineController, LineElement, PointElement,
  LinearScale, CategoryScale,
  Filler, Tooltip,
);

/** Static palette mapped 1:1 with overlay slot index. Picked so each
 *  pair is visually distinct on a dark background (matches the existing
 *  detail-pane color language). */
export const OVERLAY_COLORS = [
  "#5aa0ff", // brand-ish blue
  "#f59e0b", // amber
  "#10b981", // teal-green
  "#f472b6", // pink
  "#a78bfa", // violet
] as const;

/** Build the canonical x-axis of "minutes from 04:00 ET". Covers 04:00
 *  → 20:00 ET (the chart's pre-market open through after-hours close —
 *  the user-requested 盘前 → 盘后 range), one tick per minute = 960 slots.
 *
 *  Slots remain ET-anchored so bars from different dates align by US
 *  market wall-clock (open/close land on the same slot regardless of
 *  DST). Tick labels are rendered in BJT for readability, assuming EDT
 *  (+12h). During EST the displayed BJT label runs 1h earlier than the
 *  actual BJT at the time — slot alignment is still correct. */
const X_AXIS_START_MIN = 4 * 60;   // 04:00 ET
const X_AXIS_END_MIN = 20 * 60;    // 20:00 ET
const X_AXIS_SLOTS = X_AXIS_END_MIN - X_AXIS_START_MIN; // 960

const X_LABELS: string[] = (() => {
  const out: string[] = [];
  for (let i = 0; i < X_AXIS_SLOTS; i++) {
    const etM = X_AXIS_START_MIN + i;
    const bjtM = (etM + 12 * 60) % (24 * 60);
    const h = Math.floor(bjtM / 60);
    const mm = bjtM % 60;
    out.push(`${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}`);
  }
  return out;
})();

export const OVERLAY_X_AXIS_SLOTS = X_AXIS_SLOTS;

/** Convert a bar's ISO timestamp into its X slot index in 04:00→20:00 ET
 *  minute space. Returns -1 if outside the range (e.g. overnight bars).
 *  Exported so the legend in DetailPane can match the same x-axis
 *  semantics when looking up the hovered slot's close per date. */
const _ET_HM = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "2-digit", minute: "2-digit", hour12: false,
});
export function overlayBarSlot(iso: string): number {
  const parts = _ET_HM.formatToParts(new Date(iso));
  const hr = parseInt(parts.find((p) => p.type === "hour")?.value ?? "0", 10);
  const mn = parseInt(parts.find((p) => p.type === "minute")?.value ?? "0", 10);
  const norm = hr === 24 ? 0 : hr;
  const m = norm * 60 + mn;
  if (m < X_AXIS_START_MIN || m >= X_AXIS_END_MIN) return -1;
  return m - X_AXIS_START_MIN;
}

const C = {
  line: "rgba(255,255,255,0.06)",
  fg3: "#566071",
};

function fmtN(n: number, d = 3): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** UTC instant of "20:01 ET on ``ymdEt``" — the `before` cut we pass
 *  to the broker. The SDK's history_candlesticks_by_offset returns N
 *  bars chronologically before this cut; with N = 1000 (sessions=all)
 *  that comfortably covers the 960-minute pre→post window (04:00→20:00
 *  ET) of the target date, with ~40 bars of spillover into the
 *  previous day's overnight tail that the date-filter strips client-
 *  side. ET DST is resolved via Intl rather than hand-rolled offsets. */
function endOfTradingDayUtc(ymdEt: string): string {
  const [y, m, d] = ymdEt.split("-").map(Number);
  // Probe at 12:00 UTC of the target date so the DST lookup uses an
  // instant well inside the same ET calendar day regardless of zone shift.
  const probe = new Date(Date.UTC(y, m - 1, d, 12));
  const tzFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    timeZoneName: "shortOffset",
  });
  const offsetPart = tzFmt.formatToParts(probe)
    .find((p) => p.type === "timeZoneName")?.value ?? "GMT-5";
  // "GMT-5" (EST) / "GMT-4" (EDT)
  const sign = offsetPart.includes("-") ? -1 : 1;
  const hours = parseInt(offsetPart.replace(/[^\d]/g, ""), 10) || 5;
  // 20:01 ET = 20:01 - signedOffsetHours UTC. EST (sign=-1, hours=5) →
  // 20:01 + 5 = 01:01 UTC next day; EDT → 00:01 UTC next day.
  const utcMinutesFromEt = 20 * 60 + 1 - sign * hours * 60;
  const cut = new Date(Date.UTC(y, m - 1, d, 0, utcMinutesFromEt, 0));
  return cut.toISOString();
}

export interface OverlayBarsState {
  /** Cached intraday bars per ET trading-day; entries persist across
   *  rapid select/deselect so re-adding a recently-seen date is instant. */
  barsByDate: Record<string, Candlestick[]>;
  loadingDates: Set<string>;
  errorDates: Set<string>;
}

/** Per-(symbol, date) intraday bars for the 多日重叠 view. State lives
 *  here so the legend rendered upstream in DetailPane and the chart in
 *  DetailChartOverlay both read off the same fetched data — keeps the
 *  legend's "last close" column in lockstep with what the line shows. */
export function useOverlayBars(symbol: string, dates: string[]): OverlayBarsState {
  const [barsByDate, setBars] = useState<Record<string, Candlestick[]>>({});
  const [loadingDates, setLoadingDates] = useState<Set<string>>(new Set());
  const [errorDates, setErrorDates] = useState<Set<string>>(new Set());

  // Symbol switches drop all caches — a different stock's bars would
  // mislead the legend and the chart alike.
  useEffect(() => {
    setBars({});
    setLoadingDates(new Set());
    setErrorDates(new Set());
  }, [symbol]);

  useEffect(() => {
    let alive = true;
    const missing = dates.filter((d) => !barsByDate[d] && !loadingDates.has(d));
    if (missing.length === 0) return;
    setLoadingDates((cur) => {
      const n = new Set(cur);
      missing.forEach((d) => n.add(d));
      return n;
    });
    missing.forEach((date) => {
      api.candlesticks(symbol, "today", {
        granularity: "分时",
        sessions: "all",
        before: endOfTradingDayUtc(date),
      })
        .then((r) => {
          if (!alive) return;
          // Server returns up to 1000 most-recent bars before the cut —
          // filter down to the target ET trading day so the overlay
          // slot stays clean when the SDK overshoots into yesterday.
          const filtered = r.bars.filter(
            (b) => b.timestamp && tradingDayOfET(b.timestamp) === date,
          );
          setBars((cur) => ({ ...cur, [date]: filtered }));
          setErrorDates((cur) => {
            if (!cur.has(date)) return cur;
            const n = new Set(cur);
            n.delete(date);
            return n;
          });
        })
        .catch((e) => {
          console.warn("overlay fetch failed", date, e);
          if (!alive) return;
          setErrorDates((cur) => new Set(cur).add(date));
        })
        .finally(() => {
          if (!alive) return;
          setLoadingDates((cur) => {
            const n = new Set(cur);
            n.delete(date);
            return n;
          });
        });
    });
    return () => { alive = false; };
    // barsByDate / loadingDates intentionally NOT in deps — the effect
    // already reads them only as "have we cached this?" gates and any
    // mutation we trigger lands via setState callbacks rather than
    // re-running the effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dates, symbol]);

  return { barsByDate, loadingDates, errorDates };
}

interface Props {
  symbol: string;
  /** ET trading-day strings (YYYY-MM-DD), in selection order. */
  dates: string[];
  /** Bars + loading/error states from useOverlayBars — passed in so
   *  the upstream legend and this chart share one fetch. */
  barsByDate: Record<string, Candlestick[]>;
  loadingDates: Set<string>;
  errorDates: Set<string>;
  /** Fired on mouseover with the x-axis slot under the cursor (or
   *  null on mouse leave). DetailPane uses this to refresh the
   *  legend prices to the hovered minute's close per date. */
  onHoverSlot?: (slot: number | null) => void;
}

/** Multi-day overlay line chart. Pure presenter: receives bars from
 *  the parent's useOverlayBars hook, slots them onto a shared
 *  04:00→20:00 ET minute x-axis, renders one line per selected date
 *  with a distinct color. Rebuilt whenever the dataset shape changes —
 *  the overlay isn't a hot path. */
export function DetailChartOverlay({
  symbol: _symbol, dates, barsByDate, loadingDates, errorDates, onHoverSlot,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);
  // Ref-wrap onHoverSlot so the chart's onHover closure always picks
  // up the latest callback without forcing a chart rebuild on every
  // parent re-render.
  const onHoverSlotRef = useRef(onHoverSlot);
  useEffect(() => { onHoverSlotRef.current = onHoverSlot; }, [onHoverSlot]);

  // Build chart datasets: one line per selected date, slotted into the
  // shared 04:00→20:00 ET minute x-axis. Missing slots stay null so
  // Chart.js gaps the line rather than drawing a horizontal floor.
  const datasets = useMemo(() => {
    return dates.map((date, idx) => {
      const color = OVERLAY_COLORS[idx % OVERLAY_COLORS.length]!;
      const dayBars = barsByDate[date] ?? [];
      const data: (number | null)[] = Array(X_AXIS_SLOTS).fill(null);
      for (const b of dayBars) {
        if (!b.timestamp) continue;
        const slot = overlayBarSlot(b.timestamp);
        if (slot < 0) continue;
        data[slot] = b.close;
      }
      return {
        label: date,
        data,
        borderColor: color,
        backgroundColor: color,
        borderWidth: 1.2,
        pointRadius: 0,
        pointHoverRadius: 0,
        tension: 0.18,
        spanGaps: false,
      };
    });
  }, [dates, barsByDate]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (datasets.length === 0) {
      chartRef.current?.destroy();
      chartRef.current = null;
      return;
    }
    const cfg: ChartConfiguration = {
      type: "line",
      data: {
        labels: X_LABELS,
        datasets: datasets as ChartConfiguration["data"]["datasets"],
      },
      // crosshairPlugin reads chart.$hoverBarIndex (stashed by onHover
      // below) and draws the vertical dashed guide. Registered inline
      // rather than globally so it only attaches to overlay charts.
      plugins: [crosshairPlugin],
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        interaction: { mode: "index", intersect: false, axis: "x" },
        onHover: (event, _elements, chart) => {
          const e = event as { x?: number | null };
          const px = e?.x;
          const stash = chart as unknown as { $hoverBarIndex?: number | null };
          if (px == null) {
            stash.$hoverBarIndex = null;
            onHoverSlotRef.current?.(null);
            chart.draw();
            return;
          }
          const xScale = chart.scales.x;
          if (!xScale) return;
          const v = xScale.getValueForPixel?.(px);
          if (v == null || !Number.isFinite(v)) {
            stash.$hoverBarIndex = null;
            onHoverSlotRef.current?.(null);
            chart.draw();
            return;
          }
          const idx = Math.max(0, Math.min(X_AXIS_SLOTS - 1, Math.round(v)));
          stash.$hoverBarIndex = idx;
          onHoverSlotRef.current?.(idx);
          chart.draw();
        },
        plugins: {
          // Legend lives outside the canvas (in .detail-chart-head); the
          // pop-up tooltip was redundant against the head's hover-driven
          // readout pattern, so both are off here.
          legend: { display: false },
          tooltip: { enabled: false },
        },
        scales: {
          x: {
            grid: { color: C.line, drawTicks: false },
            ticks: {
              color: C.fg3,
              font: { family: "IBM Plex Mono", size: 10 },
              maxRotation: 0,
              autoSkip: true,
              maxTicksLimit: 9,
            },
            border: { color: C.line },
          },
          y: {
            position: "right",
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
      const ch = chartRef.current as unknown as
        { $hoverBarIndex?: number | null; draw: () => void } | null;
      if (!ch) return;
      ch.$hoverBarIndex = null;
      onHoverSlotRef.current?.(null);
      ch.draw();
    };
    canvas.addEventListener("mouseleave", onLeave);
    try {
      chartRef.current = new Chart(canvas, cfg);
    } catch (err) {
      if (import.meta.env.DEV) console.warn("DetailChartOverlay: Chart init skipped", err);
    }
    return () => {
      canvas.removeEventListener("mouseleave", onLeave);
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, [datasets]);

  const isLoadingAny = loadingDates.size > 0;
  const isEmpty = dates.length === 0;

  return (
    <div className="chart-canvas-wrap overlay-wrap">
      <canvas ref={canvasRef} />
      {isEmpty && (
        <div className="overlay-empty">
          点击上方 <b>多日重叠</b> 选择日期开始叠加
        </div>
      )}
      {!isEmpty && isLoadingAny && (
        <div className="overlay-loading">加载中…</div>
      )}
      {!isEmpty && errorDates.size > 0 && (
        <div className="overlay-error">
          {Array.from(errorDates).join(", ")} 加载失败
        </div>
      )}
    </div>
  );
}
