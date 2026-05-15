import type { Chart, Plugin, ActiveElement } from "chart.js";

/**
 * Crosshair plugin: when the user hovers the chart, draw a vertical
 * dashed line at the active x position so the tooltip's "time + price"
 * read is unambiguous against the rest of the curve.
 *
 * The plugin piggybacks on Chart.js's built-in tooltip activation —
 * whatever bar/point Chart.js considers "active" (governed by the
 * `interaction.mode` we set to "nearest" axis "x") gets the crosshair.
 * If nothing is active (mouse outside chart), no line is drawn.
 */
const LINE_COLOR = "rgba(255, 255, 255, 0.28)";

export const crosshairPlugin: Plugin = {
  id: "crosshair",
  afterDraw(chart: Chart) {
    // Chart.js's Tooltip exposes the active elements via getActiveElements()
    // (v4). Fallback to the internal _active array on older versions.
    const tooltip = chart.tooltip as unknown as {
      getActiveElements?: () => ActiveElement[];
      _active?: ActiveElement[];
    } | undefined;
    const active: ActiveElement[] =
      tooltip?.getActiveElements?.() ?? tooltip?._active ?? [];
    if (active.length === 0) return;

    const elem = active[0]?.element as { x?: number } | undefined;
    if (!elem || elem.x == null) return;
    const area = chart.chartArea;
    if (!area) return;
    const x = elem.x;
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
