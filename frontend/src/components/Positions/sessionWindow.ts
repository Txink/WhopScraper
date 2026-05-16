/** Pure resolver for the card's intraday-spark x-axis window. */

export type Market = "US" | "HK" | "CN";
export type SessionLabel = "pre" | "regular" | "post" | "overnight" | "closed";

/** One sub-region of the x-axis, e.g. for US the full day is split into
 *  四个区段 (盘前/盘中/盘后/夜盘). HK/CN windows return a single region. */
export interface SessionRegion {
  /** Watermark text — anchors which broker session this region covers. */
  label: "盘前" | "盘中" | "盘后" | "夜盘";
  /** First slot index this region claims (inclusive). */
  startSlot: number;
  /** Last slot index this region claims (exclusive). */
  endSlot: number;
}

export interface SessionWindow {
  /** Live indicator — matches the current trade_session prop. Used for
   *  closed-state styling decisions; the per-region labels are what's
   *  actually shown on the chart. */
  label: "盘前" | "盘中" | "盘后" | "夜盘" | "休市";
  /** UTC ms of the session's first minute boundary. */
  startMs: number;
  /** UTC ms of the session's last minute boundary (exclusive). */
  endMs: number;
  /** Number of 1-minute slots reserved on the x-axis. */
  slotCount: number;
  /** Slot idx → UTC ms (slot's minute start). */
  slotToMs(slotIdx: number): number;
  /** UTC ms → slot idx, or -1 if outside the window (incl. HK lunch). */
  msToSlot(ms: number): number;
  /** [0..1] progress of nowMs through the window. Clamped at the ends.
   *  Always 1 for closed-state windows. */
  progress(nowMs: number): number;
  /** Sub-regions across the x-axis. US has 4 (pre/regular/post/overnight);
   *  HK + CN have 1 (regular only). Vertical dividers are drawn between
   *  consecutive regions, region labels are watermarked at their midpoints. */
  regions: SessionRegion[];
}

const LABEL_MAP: Record<SessionLabel, SessionWindow["label"]> = {
  pre: "盘前",
  regular: "盘中",
  post: "盘后",
  overnight: "夜盘",
  closed: "休市",
};

// ---------- date helpers (Intl, tz-correct, DST-safe) ---------- //

const _US_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric", month: "2-digit", day: "2-digit",
});
const _HK_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Hong_Kong",
  year: "numeric", month: "2-digit", day: "2-digit",
});
const _US_WEEKDAY = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
});
const _HK_WEEKDAY = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Hong_Kong",
  weekday: "short",
});
const _WEEKDAY_IDX: Record<string, number> = {
  Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
};

function dateKeyInTz(ms: number, market: Market): string {
  return market === "US" ? _US_DATE.format(new Date(ms)) : _HK_DATE.format(new Date(ms));
}

function weekdayInTz(ms: number, market: Market): number {
  const fmt = market === "US" ? _US_WEEKDAY : _HK_WEEKDAY;
  return _WEEKDAY_IDX[fmt.format(new Date(ms))] ?? 0;
}

/**
 * Resolve a local-tz wall-clock {YYYY-MM-DD, HH:MM} to UTC ms using an
 * iterative correction: Date.UTC gives us a starting point, then we
 * compute the tz offset at that instant via Intl and adjust. Two passes
 * suffice for all DST cases.
 */
function localToUtcMs(
  dateKey: string,
  hour: number,
  minute: number,
  market: Market,
): number {
  const [y, m, d] = dateKey.split("-").map(Number);
  let guess = Date.UTC(y, m - 1, d, hour, minute);
  for (let i = 0; i < 2; i++) {
    const offset = tzOffsetMinutes(guess, market);
    guess = Date.UTC(y, m - 1, d, hour, minute) - offset * 60_000;
  }
  return guess;
}

function tzOffsetMinutes(ms: number, market: Market): number {
  const tz = market === "US" ? "America/New_York" : "Asia/Hong_Kong";
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const parts = fmt.formatToParts(new Date(ms));
  const get = (t: string) => parseInt(parts.find((p) => p.type === t)?.value ?? "0", 10);
  const local = Date.UTC(
    get("year"), get("month") - 1, get("day"),
    get("hour") === 24 ? 0 : get("hour"), get("minute"),
  );
  return Math.round((local - ms) / 60_000);
}

/** Step back day-by-day in market tz until a weekday (Mon-Fri) is found. */
function lastTradingDateKey(now: number, market: Market): string {
  let ms = now;
  for (let i = 0; i < 7; i++) {
    ms -= 24 * 60 * 60 * 1000;
    const wd = weekdayInTz(ms, market);
    if (wd >= 1 && wd <= 5) return dateKeyInTz(ms, market);
  }
  return dateKeyInTz(ms, market);
}

/** ET hour-of-day for a UTC instant. Handles DST via Intl. */
function getEtHour(ms: number): number {
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit", hour12: false,
  });
  const h = parseInt(fmt.format(new Date(ms)), 10);
  return h === 24 ? 0 : h;
}

/** Current US "chart day" — the ET calendar date whose regular session
 *  the chart is anchored around. The chart's 24h window spans ET 20:00
 *  of (chartDay - 1) through ET 20:00 of chartDay, so the four sessions
 *  read left-to-right as 夜盘 → 盘前 → 盘中 → 盘后.
 *
 *  - ET 20:00+: overnight leading into TOMORROW's regular → chartDay = tomorrow
 *  - else:      pre/regular/post or overnight tail of today → chartDay = today
 */
function currentUSChartDayKey(now: number): string {
  if (getEtHour(now) >= 20) {
    return dateKeyInTz(now + 24 * 60 * 60 * 1000, "US");
  }
  return dateKeyInTz(now, "US");
}

/** Anchor = ET 20:00 of the day BEFORE the chart day, so the overnight
 *  session (Thu 20:00 → Fri 04:00 for Friday's chart) sits at slot 0.
 *  We anchor date arithmetic at NOON UTC of the chartDayKey — that
 *  instant is unambiguously inside the chartDayKey ET calendar day for
 *  every tz we care about, so subtracting 24h lands cleanly on the
 *  previous ET date. (Using midnight UTC would put us at 20:00 ET of
 *  the previous day, breaking the rollback by one full day.) */
function chartAnchorMsUS(chartDayKey: string): number {
  const [y, m, d] = chartDayKey.split("-").map(Number);
  const noonUtc = Date.UTC(y, m - 1, d, 12);
  const prevDayKey = dateKeyInTz(noonUtc - 24 * 60 * 60 * 1000, "US");
  return localToUtcMs(prevDayKey, 20, 0, "US");
}

/** Fixed slot offsets for the four US sessions inside the unified
 *  1440-min day window. Order: 夜盘 → 盘前 → 盘中 → 盘后, so the chart
 *  reads chronologically left-to-right starting at the prior evening's
 *  overnight open. */
const US_REGIONS: SessionRegion[] = [
  { label: "夜盘", startSlot: 0,    endSlot: 480 },   // 20:00 → 04:00+1d
  { label: "盘前", startSlot: 480,  endSlot: 810 },   // 04:00 → 09:30
  { label: "盘中", startSlot: 810,  endSlot: 1200 },  // 09:30 → 16:00
  { label: "盘后", startSlot: 1200, endSlot: 1440 },  // 16:00 → 20:00
];

/** Defensive guard: the backend's MarketSchedule.state_for can be wrong
 *  on weekends/holidays if its trading-session cache is stale and
 *  matches a weekday's session window against today's wall-clock time
 *  (e.g. Saturday ET 04:00 matches the 04:00-09:30 pre window, so the
 *  pushed quote claims "pre" when in fact markets are closed).
 *
 *  This function downgrades the broker's session to "closed" when the
 *  date in market tz is not a known trading weekday. Holidays still
 *  slip through (we don't have a holiday calendar), but weekends are
 *  the common case and they're the one most visibly broken. */
export function effectiveSession(
  market: Market,
  brokerSession: SessionLabel,
  now: number,
): SessionLabel {
  if (brokerSession === "closed") return "closed";
  const wd = weekdayInTz(now, market);
  if (market === "US") {
    // US trades overnight Sun→Fri (Sunday 20:00 → Friday 20:00 ET).
    // Saturday: fully closed. Sunday: closed until 20:00 ET when
    // overnight session re-opens.
    if (wd === 6) return "closed";              // Saturday
    if (wd === 0 && getEtHour(now) < 20) return "closed"; // Sunday before evening
    return brokerSession;
  }
  // HK / CN never trade weekends.
  if (wd === 0 || wd === 6) return "closed";
  return brokerSession;
}

// ---------- main resolver ---------- //

export function resolveSessionWindow(
  market: Market,
  session: SessionLabel,
  now: number,
): SessionWindow {
  if (market === "US") return resolveUS(session, now);
  if (market === "CN") return resolveCN(session, now);
  return resolveHK(session, now);
}

function resolveUS(session: SessionLabel, now: number): SessionWindow {
  // Unified day window: 1440-minute x-axis anchored at ET 20:00 of the
  // day BEFORE the chart day, so 夜盘 → 盘前 → 盘中 → 盘后 read left-to-
  // right. On a non-trading day (weekend), session is already "closed"
  // (callers pre-filter via effectiveSession); we anchor the window on
  // the last trading day's chart (Thu 20:00 → Fri 20:00 for "Friday's
  // chart" shown over the weekend).
  const closed = session === "closed";
  const chartDayKey = closed
    ? lastTradingDateKey(now, "US")
    : currentUSChartDayKey(now);
  const startMs = chartAnchorMsUS(chartDayKey);
  const slotCount = 1440;
  const endMs = startMs + slotCount * 60_000;

  return {
    label: LABEL_MAP[session],
    startMs,
    endMs,
    slotCount,
    slotToMs: (idx) => startMs + idx * 60_000,
    msToSlot: (ms) => {
      const off = Math.floor((ms - startMs) / 60_000);
      return off >= 0 && off < slotCount ? off : -1;
    },
    progress: (nowMs) => {
      if (closed) return 1;
      if (nowMs <= startMs) return 0;
      if (nowMs >= endMs) return 1;
      return (nowMs - startMs) / (endMs - startMs);
    },
    regions: US_REGIONS,
  };
}

function resolveHK(session: SessionLabel, now: number): SessionWindow {
  // HK Main Board: 09:30-12:00 morning (150 min) + 13:00-16:00 afternoon (180 min).
  // Lunch (12:00-13:00 HKT) is compressed off the x-axis — slot 149 → 11:59,
  // slot 150 → 13:00.
  const closed = session === "closed";
  const dk = closed ? lastTradingDateKey(now, "HK") : dateKeyInTz(now, "HK");

  const morningStartMs = localToUtcMs(dk, 9, 30, "HK");
  const afternoonStartMs = localToUtcMs(dk, 13, 0, "HK");
  const morningSlots = 150;
  const afternoonSlots = 180;
  const totalSlots = morningSlots + afternoonSlots; // 330

  const startMs = morningStartMs;
  const endMs = afternoonStartMs + afternoonSlots * 60_000; // 16:00 HKT

  return {
    label: closed ? LABEL_MAP.closed : LABEL_MAP.regular,
    startMs,
    endMs,
    slotCount: totalSlots,
    slotToMs: (idx) => {
      if (idx < morningSlots) return morningStartMs + idx * 60_000;
      return afternoonStartMs + (idx - morningSlots) * 60_000;
    },
    msToSlot: (ms) => {
      const morningOffset = Math.floor((ms - morningStartMs) / 60_000);
      if (morningOffset >= 0 && morningOffset < morningSlots) return morningOffset;
      const afternoonOffset = Math.floor((ms - afternoonStartMs) / 60_000);
      if (afternoonOffset >= 0 && afternoonOffset < afternoonSlots) {
        return morningSlots + afternoonOffset;
      }
      return -1;
    },
    progress: (nowMs) => {
      if (closed) return 1;
      if (nowMs <= morningStartMs) return 0;
      if (nowMs >= endMs) return 1;
      if (nowMs < afternoonStartMs - 60_000) {
        const off = Math.min(morningSlots, Math.floor((nowMs - morningStartMs) / 60_000));
        return off / totalSlots;
      }
      if (nowMs < afternoonStartMs) return morningSlots / totalSlots;
      const off = Math.min(
        afternoonSlots,
        Math.floor((nowMs - afternoonStartMs) / 60_000),
      );
      return (morningSlots + off) / totalSlots;
    },
    regions: [{ label: "盘中", startSlot: 0, endSlot: totalSlots }],
  };
}

function resolveCN(session: SessionLabel, now: number): SessionWindow {
  // CN A-shares (Shanghai + Shenzhen): 09:30-11:30 morning (120 min)
  // + 13:00-15:00 afternoon (120 min). Total 4h = 240 slots. Lunch
  // (11:30-13:00 CST, 90 min) is compressed off the x-axis — slot 119
  // → 11:29, slot 120 → 13:00. CST = UTC+8 year-round (no DST), so
  // we reuse the HK Intl formatters in localToUtcMs.
  const closed = session === "closed";
  const dk = closed ? lastTradingDateKey(now, "HK") : dateKeyInTz(now, "HK");

  const morningStartMs = localToUtcMs(dk, 9, 30, "HK");
  const afternoonStartMs = localToUtcMs(dk, 13, 0, "HK");
  const morningSlots = 120;
  const afternoonSlots = 120;
  const totalSlots = morningSlots + afternoonSlots; // 240

  const startMs = morningStartMs;
  const endMs = afternoonStartMs + afternoonSlots * 60_000; // 15:00 CST

  return {
    label: closed ? LABEL_MAP.closed : LABEL_MAP.regular,
    startMs,
    endMs,
    slotCount: totalSlots,
    slotToMs: (idx) => {
      if (idx < morningSlots) return morningStartMs + idx * 60_000;
      return afternoonStartMs + (idx - morningSlots) * 60_000;
    },
    msToSlot: (ms) => {
      const morningOffset = Math.floor((ms - morningStartMs) / 60_000);
      if (morningOffset >= 0 && morningOffset < morningSlots) return morningOffset;
      const afternoonOffset = Math.floor((ms - afternoonStartMs) / 60_000);
      if (afternoonOffset >= 0 && afternoonOffset < afternoonSlots) {
        return morningSlots + afternoonOffset;
      }
      return -1;
    },
    progress: (nowMs) => {
      if (closed) return 1;
      if (nowMs <= morningStartMs) return 0;
      if (nowMs >= endMs) return 1;
      if (nowMs < afternoonStartMs - 60_000) {
        const off = Math.min(morningSlots, Math.floor((nowMs - morningStartMs) / 60_000));
        return off / totalSlots;
      }
      if (nowMs < afternoonStartMs) return morningSlots / totalSlots;
      const off = Math.min(
        afternoonSlots,
        Math.floor((nowMs - afternoonStartMs) / 60_000),
      );
      return (morningSlots + off) / totalSlots;
    },
    regions: [{ label: "盘中", startSlot: 0, endSlot: totalSlots }],
  };
}

