import type { Candlestick } from "../../api/domain-types";
import { currentTradingDay } from "./timeFmt";
import type { IntradaySession as SessionMode } from "./viewConfig";

/** Granularity used for intraday and minute-bar views. */
type TodayGranularity = "分时" | "1min" | "2min" | "3min" | "5min";

/**
 * Build a "slot" array that reserves space on the x-axis for the full
 * session window even when the corresponding bars haven't been printed
 * by the exchange yet (e.g. user is mid-regular and asks for "盘后" —
 * the chart should still show the 4-hour post-market window, just empty).
 *
 * Slot index 0 starts at the session's first minute (BJ wall clock).
 * Real bars get matched to their slot by minute-offset from session
 * start; remaining slots carry `close: null` so Chart.js draws a gap
 * (spanGaps default = false).
 *
 * Reference points (DST May; ET = BJ − 12h):
 *   pre       — BJ 16:00 today      → ET 04:00 (5.5h)
 *   regular   — BJ 21:30 today      → ET 09:30 (6.5h)
 *   post      — BJ 04:00 next day   → ET 16:00 (4h)
 *   overnight — BJ 08:00 next day   → ET 20:00 (8h, no US data)
 *   all       — BJ 16:00 today      → ET 04:00 (16h, pre+regular+post)
 */

const GRANULARITY_MIN: Record<TodayGranularity, number> = {
  "分时": 1,
  "1min": 1,
  "2min": 2,
  "3min": 3,
  "5min": 5,
};

const SESSION_WINDOW: Record<
  SessionMode,
  { offsetMin: number; lenMin: number }
> = {
  pre:       { offsetMin: 0,   lenMin: 330 },
  regular:   { offsetMin: 330, lenMin: 390 },
  post:      { offsetMin: 720, lenMin: 240 },
  overnight: { offsetMin: 960, lenMin: 480 },
  all:       { offsetMin: 0,   lenMin: 960 },
};

/** Parse a naive LongPort timestamp string as BJ wall-clock → UTC ms. */
function parseAsBJ(iso: string): number {
  if (!iso) return Number.NaN;
  if (iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso)) return Date.parse(iso);
  return Date.parse(iso + "+08:00");
}

/** Format a UTC ms timestamp as a naive BJ ISO string ("YYYY-MM-DDTHH:mm:ss"). */
function bjIsoFromMs(ms: number): string {
  const fmt = new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false,
  });
  // sv-SE outputs "YYYY-MM-DD HH:mm:ss" — promote the space to "T" so the
  // shape matches LongPort's naive ISO strings used everywhere else.
  return fmt.format(new Date(ms)).replace(" ", "T");
}

export function buildSessionSlots(
  realBars: Candlestick[],
  granularity: TodayGranularity,
  sessions: SessionMode,
): Candlestick[] {
  const intervalMin = GRANULARITY_MIN[granularity];
  const win = SESSION_WINDOW[sessions];
  if (!intervalMin || !win) return realBars;

  // Trading day's pre-market open in BJ (16:00 same date).
  const tradingDay = currentTradingDay(); // "YYYY-MM-DD" (ET calendar)
  const tradingDayBjStartMs = Date.parse(`${tradingDay}T16:00:00+08:00`);
  if (Number.isNaN(tradingDayBjStartMs)) return realBars;

  const sessionStartMs = tradingDayBjStartMs + win.offsetMin * 60_000;
  const intervalMs = intervalMin * 60_000;
  const slotCount = Math.floor(win.lenMin / intervalMin);
  if (slotCount <= 0) return realBars;

  // Map each real bar to its slot index by wall-clock offset.
  const realByIdx: Record<number, Candlestick> = {};
  for (const bar of realBars) {
    if (!bar.timestamp) continue;
    const ms = parseAsBJ(bar.timestamp);
    if (Number.isNaN(ms)) continue;
    const idx = Math.round((ms - sessionStartMs) / intervalMs);
    if (idx >= 0 && idx < slotCount) realByIdx[idx] = bar;
  }

  // Fill the slot array — real bar where matched, else placeholder with
  // `close: null` so Chart.js renders a gap.
  const slots: Candlestick[] = [];
  for (let i = 0; i < slotCount; i++) {
    const real = realByIdx[i];
    if (real) {
      slots.push(real);
    } else {
      const ts = sessionStartMs + i * intervalMs;
      slots.push({
        timestamp: bjIsoFromMs(ts),
        open: null as unknown as number,
        high: null as unknown as number,
        low: null as unknown as number,
        close: null as unknown as number,
        volume: 0,
        turnover: 0,
      });
    }
  }
  return slots;
}
