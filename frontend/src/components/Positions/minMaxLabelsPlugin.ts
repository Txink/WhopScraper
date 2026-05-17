import type { Chart, Plugin } from "chart.js";

/**
 * Min/Max labels plugin: marks the highest and lowest price points in
 * the current x-axis window with a small white dot and an adjacent
 * price tag. Updates automatically when the user pans or zooms
 * (`afterDatasetsDraw` fires on every chart update).
 *
 * The dot uses solid white — it's a single attention-getter across
 * both extremes, matching LongBridge's mobile chart pattern.
 */

const DOT_COLOR = "#ffffff"; // solid white
const TEXT_COLOR = "#e4e8ef"; // --fg-1
const STROKE_COLOR = "rgba(0, 0, 0, 0.55)";

export const minMaxLabelsPlugin: Plugin = {
  id: "minMaxLabels",
  afterDatasetsDraw(chart: Chart) {
    const dsIdx = chart.data.datasets.findIndex(
      (d) => (d as { label?: string }).label === "成交价",
    );
    if (dsIdx < 0) return;

    const meta = chart.getDatasetMeta(dsIdx);
    const data = chart.data.datasets[dsIdx]?.data as Array<number | null>;
    if (!data || data.length === 0) return;
    const xScale = chart.scales.x;
    const area = chart.chartArea;
    if (!xScale || !area) return;

    const xMin = Math.max(0, Math.floor((xScale.min as number) ?? 0));
    const xMax = Math.min(
      data.length - 1,
      Math.ceil((xScale.max as number) ?? data.length - 1),
    );

    let maxV = -Infinity;
    let maxIdx = -1;
    let minV = Infinity;
    let minIdx = -1;
    for (let i = xMin; i <= xMax; i++) {
      const v = data[i];
      if (v == null || Number.isNaN(v)) continue;
      if (v > maxV) { maxV = v; maxIdx = i; }
      if (v < minV) { minV = v; minIdx = i; }
    }
    // Need at least two distinct values to bother labeling both — for a
    // flat-ish slice the "min" and "max" would overlap visually.
    if (maxIdx < 0 || minIdx < 0) return;

    const ctx = chart.ctx;
    ctx.save();
    ctx.font = "500 11px 'IBM Plex Mono', ui-monospace, monospace";
    ctx.lineWidth = 3;
    ctx.lineJoin = "round";

    const drawMarker = (
      idx: number, value: number,
      position: "above" | "below",
    ) => {
      const el = meta.data[idx] as { x?: number; y?: number } | undefined;
      if (!el || el.x == null || el.y == null) return;

      // White dot at the exact point. Drawn first so the label sits
      // over it visually.
      ctx.fillStyle = DOT_COLOR;
      ctx.beginPath();
      ctx.arc(el.x, el.y, 2, 0, Math.PI * 2);
      ctx.fill();

      // Price text adjacent. Anchor inside the chart area — flip side
      // when too close to the right edge so the label doesn't clip.
      const text = value.toFixed(3);
      const midX = (area.left + area.right) / 2;
      const goLeft = el.x > midX;
      ctx.textAlign = goLeft ? "right" : "left";
      ctx.textBaseline = position === "above" ? "bottom" : "top";
      const xOff = goLeft ? -8 : 8;
      const yOff = position === "above" ? -6 : 6;
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.strokeStyle = STROKE_COLOR;
      ctx.strokeText(text, el.x + xOff, el.y + yOff);
      ctx.fillStyle = TEXT_COLOR;
      ctx.fillText(text, el.x + xOff, el.y + yOff);
    };

    drawMarker(maxIdx, maxV, "above");
    if (minIdx !== maxIdx) drawMarker(minIdx, minV, "below");

    ctx.restore();
  },
};
