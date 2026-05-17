import type { Chart, Plugin } from "chart.js";

/**
 * Crosshair plugin: when the user hovers the chart, draw a vertical
 * dashed line at the bar-snapped cursor x. The hovered bar index is
 * stashed by DetailChart's onHover handler at `chart.$hoverBarIndex`,
 * which we re-project to a pixel via the x-scale. This avoids the
 * sparse-scatter "active-element" pitfall where the crosshair would
 * otherwise jump to whichever dataset's element index happened to win.
 */
const LINE_COLOR = "rgba(255, 255, 255, 0.28)";

export const crosshairPlugin: Plugin = {
  id: "crosshair",
  afterDraw(chart: Chart) {
    const idx = (chart as unknown as { $hoverBarIndex?: number | null }).$hoverBarIndex;
    if (idx == null) return;
    const xScale = chart.scales.x;
    const area = chart.chartArea;
    if (!xScale || !area) return;
    const x = xScale.getPixelForValue(idx);
    if (!Number.isFinite(x)) return;
    if (x < area.left || x > area.right) return;

    const ctx = chart.ctx;
    ctx.save();
    ctx.strokeStyle = LINE_COLOR;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(x, area.top);
    ctx.lineTo(x, area.bottom);
    ctx.stroke();
    ctx.restore();
  },
};
