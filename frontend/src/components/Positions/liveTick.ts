import type { Candlestick } from "../../api/domain-types";
import type { Period } from "../../stores/candlesticks";
import { fmtBjHM, parseUtc } from "./timeFmt";

export type Granularity = "分时" | "1min" | "2min" | "3min" | "5min";

export interface LiveConfig {
  periodMinutes: number;
  /** today views can grow new bars at boundaries; 5D/7D/15D never do
   *  (backend ships a fresh window when the user re-opens the view). */
  allowAppend: boolean;
}

/** Resolve the (periodMinutes, allowAppend) for a chart view, or null
 *  when the view is non-live (daily K — 30D/60D/90D). */
export function liveConfig(period: Period, todayGranularity: Granularity): LiveConfig | null {
  if (period === "today") {
    const mins: Record<Granularity, number> = {
      "分时": 1, "1min": 1, "2min": 2, "3min": 3, "5min": 5,
    };
    return { periodMinutes: mins[todayGranularity], allowAppend: true };
  }
  if (period === "5" || period === "7") return { periodMinutes: 5, allowAppend: false };
  if (period === "15") return { periodMinutes: 15, allowAppend: false };
  return null;
}

/** Bucket a millisecond timestamp by periodMinutes. 1/2/3/5/15-minute
 *  bucket boundaries align with both UTC and BJ wall clock (BJ offset
 *  is whole hours), so this works without tz math. */
export function bucketKey(ms: number, periodMinutes: number): number {
  return Math.floor(ms / (periodMinutes * 60_000));
}

interface ApplyArgs {
  bars: Candlestick[];
  labels: string[];
  lastDone: number;
  nowMs: number;
  periodMinutes: number;
  allowAppend: boolean;
}

interface ApplyResult {
  bars: Candlestick[];
  labels: string[];
  crossedBoundary: boolean;
}

/** Compute the next (bars, labels) state given a streaming last_done tick.
 *
 *  - Same bucket → mutate last bar's close, accumulate high/low.
 *  - Crossed bucket + allowAppend → append a fresh bar at the new bucket's start.
 *  - Crossed bucket + !allowAppend → still update last bar in place,
 *    UNLESS we're more than 2 buckets past lastBar (then bail — too stale).
 *
 *  Pure: never mutates inputs.
 */
export function applyLiveTick({
  bars, labels, lastDone, nowMs, periodMinutes, allowAppend,
}: ApplyArgs): ApplyResult {
  if (bars.length === 0) {
    return { bars, labels, crossedBoundary: false };
  }
  const last = bars[bars.length - 1]!;
  const lastTsMs = last.timestamp ? parseUtc(last.timestamp).getTime() : 0;
  const lastKey = bucketKey(lastTsMs, periodMinutes);
  const nowKey = bucketKey(nowMs, periodMinutes);

  // Stale guard for non-append views: don't redraw bars that are >2 buckets old.
  if (!allowAppend && nowKey - lastKey > 2) {
    return { bars, labels, crossedBoundary: false };
  }

  const inPlaceUpdate = (): ApplyResult => {
    const updated: Candlestick = {
      ...last,
      close: lastDone,
      high: Math.max(last.high, lastDone),
      low: Math.min(last.low, lastDone),
    };
    return {
      bars: [...bars.slice(0, -1), updated],
      labels,
      crossedBoundary: false,
    };
  };

  if (nowKey <= lastKey) return inPlaceUpdate();
  if (!allowAppend) return inPlaceUpdate();

  // Append a new bar anchored at the new bucket's start.
  const bucketStartMs = nowKey * periodMinutes * 60_000;
  const newIso = new Date(bucketStartMs).toISOString();
  const newBar: Candlestick = {
    timestamp: newIso,
    open: lastDone,
    high: lastDone,
    low: lastDone,
    close: lastDone,
    volume: 0,
    turnover: 0,
  };
  return {
    bars: [...bars, newBar],
    labels: [...labels, fmtBjHM(newIso)],
    crossedBoundary: true,
  };
}
