import type { Chart, Plugin } from "chart.js";

/**
 * Chart.js plugin that overlays trade-session boundaries on the intraday
 * chart when the user has toggled "含盘前/盘后". Draws:
 *   - vertical dashed lines at the pre→regular and regular→post boundaries
 *   - a faded background label centered in each section: 盘前 / 盘中 / 盘后
 *
 * Bar-count-based boundary detection avoids any timezone math
 * (LongPort.TradeSessions.All = pre + regular + post = 16h, no overnight):
 *   2-min  bars: pre=165, regular=195, post=120   (total 480)
 *   3-min  bars: pre=110, regular=130, post=80    (total 320)
 *   5-min  bars: pre=66,  regular=78,  post=48    (total 192)
 *
 * The actual bar list may be shorter when the user is mid-day (post-market
 * hasn't started yet) — the plugin handles truncated data gracefully and
 * just doesn't draw boundaries that are past `barCount - 1`.
 */
export interface SessionBgPluginOptions {
  enabled: boolean;
  /** Granularity name from DetailPane's pill row. */
  granularity: "分时" | "1min" | "2min" | "3min" | "5min";
  /** Total number of bars actually rendered (== closes.length). */
  barCount: number;
  /** Which session(s) are currently visible. "all" → 3 labeled segments
   *  with dashed dividers; single-session values → one centered label
   *  spanning the whole chart, no dividers. */
  session: "regular" | "pre" | "post" | "overnight" | "all";
}

const SESSION_LABEL: Record<
  Exclude<SessionBgPluginOptions["session"], "all">,
  string
> = {
  regular: "盘中",
  pre: "盘前",
  post: "盘后",
  overnight: "夜盘",
};

declare module "chart.js" {
  interface PluginOptionsByType<TType> { // eslint-disable-line @typescript-eslint/no-unused-vars
    sessionBg?: SessionBgPluginOptions;
  }
}

const SESSION_BARS: Record<
  SessionBgPluginOptions["granularity"],
  { pre: number; regular: number; post: number }
> = {
  "分时": { pre: 330, regular: 390, post: 240 },  // 1-min bars
  "1min": { pre: 330, regular: 390, post: 240 },  // same SDK data
  "2min": { pre: 165, regular: 195, post: 120 },
  "3min": { pre: 110, regular: 130, post: 80 },
  "5min": { pre: 66, regular: 78, post: 48 },
};

const LABEL_COLOR = "rgba(255, 255, 255, 0.045)";
const LINE_COLOR = "rgba(255, 255, 255, 0.10)";

export const sessionBgPlugin: Plugin = {
  id: "sessionBg",
  // beforeDatasetsDraw → labels and boundary lines sit BEHIND the price
  // line + markers, like a watermark.
  beforeDatasetsDraw(chart: Chart, _args, rawOpts) {
    const opts = rawOpts as SessionBgPluginOptions | undefined;
    if (!opts || !opts.enabled) return;
    const { barCount, session } = opts;
    if (barCount <= 0) return;

    const xScale = chart.scales.x;
    const area = chart.chartArea;
    if (!xScale || !area) return;

    const ctx = chart.ctx;
    ctx.save();

    const drawLabel = (text: string, x1: number, x2: number) => {
      const cx = (x1 + x2) / 2;
      const cy = (area.top + area.bottom) / 2;
      const width = x2 - x1;
      // Scale font with section width but cap so it doesn't dominate.
      const size = Math.max(20, Math.min(64, width * 0.16));
      ctx.fillStyle = LABEL_COLOR;
      ctx.font = `700 ${size}px "IBM Plex Sans", "PingFang SC", sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, cx, cy);
    };

    // Single-session view (盘中 / 盘前 / 盘后 / 夜盘) — one watermark spanning
    // the whole chart, no dividers needed.
    if (session !== "all") {
      drawLabel(SESSION_LABEL[session], area.left, area.right);
      ctx.restore();
      return;
    }

    // "全部" view — 3 segments (pre / regular / post) + dashed dividers.
    const cfg = SESSION_BARS[opts.granularity];
    if (!cfg) { ctx.restore(); return; }
    const preEnd = cfg.pre;
    const regularEnd = cfg.pre + cfg.regular;

    const sectionPx = (startIdx: number, endIdx: number) => {
      if (startIdx >= barCount) return null;
      const lo = Math.max(0, startIdx);
      const hi = Math.min(barCount - 1, endIdx - 1);
      if (hi < lo) return null;
      const xLo = xScale.getPixelForValue(lo);
      const xHi = xScale.getPixelForValue(hi);
      const clippedLo = Math.max(area.left, Math.min(xLo, xHi));
      const clippedHi = Math.min(area.right, Math.max(xLo, xHi));
      if (clippedHi <= clippedLo) return null;
      return { x1: clippedLo, x2: clippedHi };
    };

    const preSec = sectionPx(0, preEnd);
    if (preSec) drawLabel("盘前", preSec.x1, preSec.x2);
    const regSec = sectionPx(preEnd, regularEnd);
    if (regSec) drawLabel("盘中", regSec.x1, regSec.x2);
    const postSec = sectionPx(regularEnd, regularEnd + cfg.post);
    if (postSec) drawLabel("盘后", postSec.x1, postSec.x2);

    const drawDivider = (idx: number) => {
      if (idx <= 0 || idx >= barCount) return;
      const x = xScale.getPixelForValue(idx);
      if (x < area.left || x > area.right) return;
      ctx.strokeStyle = LINE_COLOR;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, area.top);
      ctx.lineTo(x, area.bottom);
      ctx.stroke();
    };
    drawDivider(preEnd);
    drawDivider(regularEnd);

    ctx.restore();
  },
};
