/**
 * Resolves the bar index a single trade should anchor to for marker
 * rendering and hover aggregation. Shared between DetailChart (builds
 * B/S/T bubbles) and DetailPane (builds the hover-row agg display) so
 * both views agree on the same mapping.
 *
 *   Line views (intraday/minute/multiday): try strict floor-to-bucket
 *     first — a trade at 23:16 with 5-min bars lands on the bar
 *     timestamped 23:15. If no bar covers the trade's bucket (multiday
 *     only returns regular-session bars, so pre-/post-/overnight fills
 *     fall through here), snap to the SAME ET calendar day's regular
 *     open (pre-market or overnight 00:00-09:30) or regular close
 *     (post-market or overnight ≥16:00). Trades whose ET calendar day
 *     isn't in the loaded window are dropped.
 *
 *   Candlestick views (day/week/month/year): single nearest-bar match
 *     within ±12h so weekend / after-hours fills still anchor on the
 *     right daily candle.
 *
 * Returns -1 when no acceptable bar exists.
 */
const REGULAR_OPEN_MIN = 9 * 60 + 30;
const REGULAR_CLOSE_MIN = 16 * 60;
const CANDLE_TOL_MS = 12 * 3600 * 1000;

const _ET_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const _ET_HM = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function etDateAndMinutes(ms: number): { date: string; minutes: number } {
  const d = new Date(ms);
  const date = _ET_DATE.format(d);
  const parts = _ET_HM.formatToParts(d);
  const hr = parseInt(parts.find((p) => p.type === "hour")?.value ?? "0", 10);
  const mn = parseInt(parts.find((p) => p.type === "minute")?.value ?? "0", 10);
  // Some engines emit "24" for midnight under hour12=false — fold to 0.
  const minutes = ((hr === 24 ? 0 : hr) * 60) + mn;
  return { date, minutes };
}

export type DayBoundaries = Map<string, { firstIdx: number; lastIdx: number }>;

/** {ET-calendar-date -> first/last bar index} from a sorted bar-timestamp
 *  list. Drives the off-hours snap so a pre-market fill on 05/13 lands
 *  on 05/13's 09:30 open bar, not on the nearest bar of a different day. */
export function buildDayBoundaries(barTs: number[]): DayBoundaries {
  const m: DayBoundaries = new Map();
  for (let i = 0; i < barTs.length; i++) {
    if (barTs[i] === 0) continue;
    const { date } = etDateAndMinutes(barTs[i]!);
    const existing = m.get(date);
    if (!existing) m.set(date, { firstIdx: i, lastIdx: i });
    else existing.lastIdx = i;
  }
  return m;
}

export function findBarForTrade(
  barTs: number[],
  tradeTs: number,
  periodMs: number,
  isLineView: boolean,
  dayBoundaries?: DayBoundaries,
): number {
  if (isLineView && periodMs > 0) {
    let bucket = -1;
    for (let i = 0; i < barTs.length; i++) {
      if (barTs[i] === 0) continue;
      if (barTs[i]! > tradeTs) break;
      bucket = i;
    }
    if (bucket >= 0 && tradeTs - barTs[bucket]! < periodMs) {
      return bucket;
    }
    if (dayBoundaries) {
      const { date, minutes } = etDateAndMinutes(tradeTs);
      const day = dayBoundaries.get(date);
      if (!day) return -1;
      if (minutes < REGULAR_OPEN_MIN) return day.firstIdx;
      if (minutes >= REGULAR_CLOSE_MIN) return day.lastIdx;
      // Inside regular hours but no exact bucket — rare intraday data gap;
      // drop rather than guess a neighbor.
      return -1;
    }
    return -1;
  }
  let bestD = Infinity;
  let best = -1;
  for (let i = 0; i < barTs.length; i++) {
    if (barTs[i] === 0) continue;
    const d = Math.abs(barTs[i]! - tradeTs);
    if (d < bestD) { bestD = d; best = i; }
  }
  if (best < 0 || bestD > CANDLE_TOL_MS) return -1;
  return best;
}
