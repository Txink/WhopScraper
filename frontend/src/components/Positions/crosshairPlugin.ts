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
const LABEL_BG = "rgba(20, 22, 28, 0.92)";
const LABEL_FG = "#e7e9ee";
const LABEL_BORDER = "rgba(255, 255, 255, 0.14)";

export const crosshairPlugin: Plugin = {
  id: "crosshair",
  afterDraw(chart: Chart) {
    const stash = chart as unknown as {
      $hoverBarIndex?: number | null;
    };
    const idx = stash.$hoverBarIndex;
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

    // Small time chip at the top of the crosshair. Label text comes
    // from `chart.data.labels[idx]` — each chart that uses this plugin
    // pre-builds labels as human-readable strings (intraday/minute →
    // "HH:MM", multiday → "date HH:MM", day/week/month → date).
    const labels = chart.data.labels as unknown[] | undefined;
    const label = labels?.[idx];
    if (typeof label !== "string" || label.length === 0) return;

    ctx.save();
    ctx.font = "10px 'IBM Plex Mono', monospace";
    ctx.textBaseline = "middle";
    const padX = 6;
    const textW = ctx.measureText(label).width;
    const boxW = textW + padX * 2;
    const boxH = 16;
    // Center the chip on the crosshair, clamping to the plot area so it
    // never bleeds past the canvas edges at the chart boundaries. The
    // chip sits just inside the plot area at the top of the crosshair
    // so the chart's outer padding never clips it.
    let boxX = x - boxW / 2;
    boxX = Math.max(area.left, Math.min(area.right - boxW, boxX));
    const boxY = area.top + 2;

    ctx.fillStyle = LABEL_BG;
    ctx.strokeStyle = LABEL_BORDER;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    const r = 3;
    ctx.beginPath();
    ctx.moveTo(boxX + r, boxY);
    ctx.lineTo(boxX + boxW - r, boxY);
    ctx.quadraticCurveTo(boxX + boxW, boxY, boxX + boxW, boxY + r);
    ctx.lineTo(boxX + boxW, boxY + boxH - r);
    ctx.quadraticCurveTo(boxX + boxW, boxY + boxH, boxX + boxW - r, boxY + boxH);
    ctx.lineTo(boxX + r, boxY + boxH);
    ctx.quadraticCurveTo(boxX, boxY + boxH, boxX, boxY + boxH - r);
    ctx.lineTo(boxX, boxY + r);
    ctx.quadraticCurveTo(boxX, boxY, boxX + r, boxY);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = LABEL_FG;
    ctx.textAlign = "center";
    ctx.fillText(label, boxX + boxW / 2, boxY + boxH / 2);
    ctx.restore();
  },
};
