import { useEffect, useRef, useState } from "react";
import {
  Chart,
  type ChartConfiguration,
  type ScriptableContext,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
} from "chart.js";
import { usePrefsStore } from "../../stores/prefs";

Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
);

/** Resolve a CSS custom property to its computed hex/rgba value so the
 *  sparkline tracks the user's prefs (US green-up vs CN red-up) without
 *  re-registering at draw time. */
function cssVar(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

interface Props {
  /** Intraday closing prices, oldest first. */
  values: number[];
  /** open price for color decision; positive change = green, negative = red. */
  openPrice: number | null;
}

/**
 * Sparkline intraday chart for a position card. Keeps a single Chart.js
 * instance across the component's lifetime and applies *in-place* updates
 * when ``values`` changes — same length → mutate dataset.data + repaint
 * with no animation; length grew → push the new bar(s). This replaces the
 * prior destroy/recreate pattern, which flashed the whole canvas on each
 * 15s poll.
 *
 * A pulsing dot is overlaid at the last point's pixel position so the
 * user has a clear "live" cue even when the line itself is nearly flat.
 */
export function MiniLine({ values, openPrice }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const chartRef = useRef<Chart | null>(null);
  // Subscribe so the sparkline rebuilds when the user flips US ↔ CN
  // colors in LongPort settings.
  const colorMode = usePrefsStore((s) => s.colorMode);

  // Dot position is tracked in React state so it re-renders alongside the
  // chart update. Computed via ``chart.scales.*.getPixelForValue`` after
  // each update so the dot stays anchored to the last data point.
  const [dot, setDot] = useState<{ x: number; y: number; color: string } | null>(null);

  // Build (or rebuild) the chart from scratch. Only fires when the color
  // mode flips or when the canvas first mounts — value updates take the
  // in-place path below.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (values.length === 0) return;

    const last = values[values.length - 1] ?? 0;
    const open = openPrice ?? values[0] ?? 0;
    const isPos = last >= open;
    const color = isPos
      ? cssVar("--up-color", "#3dd68c")
      : cssVar("--down-color", "#ef5b5b");
    const fillColor = isPos
      ? cssVar("--up-soft", "rgba(61,214,140,0.20)")
      : cssVar("--down-soft", "rgba(239,91,91,0.20)");

    const min = Math.min(...values);
    const max = Math.max(...values);
    const pad = (max - min) * 0.2 || Math.abs(open) * 0.005 || 0.5;

    const cfg: ChartConfiguration = {
      type: "line",
      data: {
        labels: values.map((_, i) => i),
        datasets: [
          {
            data: [...values],
            borderColor: color,
            backgroundColor: (ctx: ScriptableContext<"line">) => {
              const area = ctx.chart.chartArea;
              if (!area) return "transparent";
              const grad = ctx.chart.ctx.createLinearGradient(
                0, area.top, 0, area.bottom,
              );
              grad.addColorStop(0, fillColor);
              grad.addColorStop(1, "rgba(0,0,0,0)");
              return grad;
            },
            borderWidth: 1.4,
            fill: true,
            tension: 0.28,
            pointRadius: 0,
            pointHoverRadius: 0,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        // animations are zeroed out so updates feel "live" (instant
        // pop-into-place) rather than a 220ms ease-in tween that
        // visually conflicts with the pulsing dot at the right edge.
        animation: false,
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: {
          x: { display: false },
          y: { display: false, min: min - pad, max: max + pad },
        },
      },
    };

    try {
      chartRef.current = new Chart(canvas, cfg);
      // Force scale computation before reading getPixelForValue — Chart.js
      // doesn't populate ``chart.scales.*`` until the first draw, which
      // happens on the next frame by default. The explicit update keeps
      // dot placement in lockstep with chart creation.
      chartRef.current.update("none");
      positionDot();
    } catch (err) {
      if (import.meta.env.DEV) console.warn("MiniLine: Chart.js init skipped", err);
      // ``new Chart()`` can half-construct in jsdom (canvas context APIs
      // missing) — the constructor still returns, but the follow-up
      // ``update("none")`` blows up reading null contexts. Null the ref
      // so the in-place values-effect doesn't poke a broken instance.
      try { chartRef.current?.destroy(); } catch { /* ignore */ }
      chartRef.current = null;
    }
    return () => {
      chartRef.current?.destroy();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colorMode]);

  // In-place update on every ``values`` (or openPrice) change.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || values.length === 0) return;

    const last = values[values.length - 1] ?? 0;
    const open = openPrice ?? values[0] ?? 0;
    const isPos = last >= open;
    const color = isPos
      ? cssVar("--up-color", "#3dd68c")
      : cssVar("--down-color", "#ef5b5b");
    const fillColor = isPos
      ? cssVar("--up-soft", "rgba(61,214,140,0.20)")
      : cssVar("--down-soft", "rgba(239,91,91,0.20)");

    // Same length → mutate the last value in place so Chart.js diffs
    // a single point. Length changed (new bar appeared, or stale series
    // got swapped out) → wholesale replace, but still no animation.
    const ds = chart.data.datasets[0];
    if (chart.data.labels && chart.data.labels.length === values.length) {
      (ds.data as number[]).splice(0, ds.data.length, ...values);
    } else {
      chart.data.labels = values.map((_, i) => i);
      ds.data = [...values];
    }

    // Direction may have flipped (price crossed open) — refresh colors
    // without recreating the chart. backgroundColor is a callable that
    // re-evaluates on draw so we only need to swap fillColor closure-side
    // via reassign.
    ds.borderColor = color;
    ds.backgroundColor = (ctx: ScriptableContext<"line">) => {
      const area = ctx.chart.chartArea;
      if (!area) return "transparent";
      const grad = ctx.chart.ctx.createLinearGradient(
        0, area.top, 0, area.bottom,
      );
      grad.addColorStop(0, fillColor);
      grad.addColorStop(1, "rgba(0,0,0,0)");
      return grad;
    };

    // Refit the y-axis if the new value escaped the prior pad band, else
    // leave it untouched so the line's slope stays comparable across ticks.
    const yScale = chart.options.scales?.y;
    if (yScale && typeof yScale === "object") {
      const min = Math.min(...values);
      const max = Math.max(...values);
      const pad = (max - min) * 0.2 || Math.abs(open) * 0.005 || 0.5;
      yScale.min = min - pad;
      yScale.max = max + pad;
    }

    try {
      chart.update("none");
      positionDot();
    } catch (err) {
      // Defensive — jsdom test env can still hit canvas-API gaps when
      // Chart.js redraws. Production browsers never reach this branch.
      if (import.meta.env.DEV) console.warn("MiniLine: update skipped", err);
    }
  }, [values, openPrice]);

  // Anchor the pulse dot to the last data point's pixel location. Called
  // after every chart update; reads scales lazily because they're only
  // populated after the first ``chart.update``.
  function positionDot(): void {
    const chart = chartRef.current;
    const container = containerRef.current;
    if (!chart || !container || values.length === 0) {
      setDot(null);
      return;
    }
    const lastIdx = values.length - 1;
    const lastVal = values[lastIdx] ?? 0;
    const xScale = chart.scales.x;
    const yScale = chart.scales.y;
    if (!xScale || !yScale) return;
    const x = xScale.getPixelForValue(lastIdx);
    const y = yScale.getPixelForValue(lastVal);
    const open = openPrice ?? values[0] ?? 0;
    const color = lastVal >= open
      ? cssVar("--up-color", "#3dd68c")
      : cssVar("--down-color", "#ef5b5b");
    setDot({ x, y, color });
  }

  return (
    <div ref={containerRef} className="minline">
      <canvas ref={canvasRef} />
      {dot && (
        <span
          className="minline-pulse"
          style={{
            left: `${dot.x}px`,
            top: `${dot.y}px`,
            ["--pulse-color" as never]: dot.color,
          }}
          aria-hidden
        />
      )}
    </div>
  );
}
