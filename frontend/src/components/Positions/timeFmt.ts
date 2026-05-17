/**
 * Beijing-time formatters for chart axes, trade rows, and pair list.
 *
 * Backend stores timestamps as real UTC; we render everything in
 * Asia/Shanghai because the project is operated from Beijing and broker
 * fill timestamps map to Whop signal times that traders read in BJ time.
 *
 * The `Intl.DateTimeFormat` instances are module-scoped to avoid
 * per-render allocation.
 */

const _BJ_HM = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Shanghai",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const _BJ_DATE = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai",
  month: "2-digit",
  day: "2-digit",
});

const _BJ_YMD = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** "10:30" — used on intraday chart x-axis ticks. */
export function fmtBjHM(iso: string): string {
  const d = new Date(iso);
  return _BJ_HM.format(d).replace(/^24:/, "00:");
}

/** "05/14" — used on daily-K chart x-axis ticks. */
export function fmtBjDate(iso: string): string {
  const d = new Date(iso);
  return _BJ_DATE.format(d);
}

/** Yields "YYYY-MM-DD" in Beijing — used as a stable day key for the
 *  today/yesterday relative-date check. */
function _bjDayKey(iso: string): string {
  const d = new Date(iso);
  return _BJ_YMD.format(d);
}

/**
 * Classify a bar timestamp into a US trading session based on its
 * ET (America/New_York) wall-clock hour. Returns one of:
 *   "pre"        — 04:00 ≤ ET < 09:30
 *   "regular"    — 09:30 ≤ ET < 16:00
 *   "post"       — 16:00 ≤ ET < 20:00
 *   "overnight"  — 20:00 ≤ ET < 04:00 next day
 *
 * Using Intl with explicit timeZone makes this DST-safe and independent
 * of the browser's local zone.
 */
const _ET_HM = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export type ETSession = "pre" | "regular" | "post" | "overnight";

/**
 * Return the US trading day a given instant belongs to, as an ET
 * calendar date (YYYY-MM-DD). A trading day spans ET 4:00 → 4:00 next
 * day (= BJ 16:00 → 16:00 next day):
 *   pre + regular + post + overnight all roll up to the trading day
 *   whose name = the ET date of the pre-market open.
 *
 * Edge: bars at ET 00:00-04:00 belong to the PREVIOUS trading day
 * (still in its overnight tail).
 */
const _ET_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function _etDateAndHour(d: Date): { date: string; hour: number } {
  const dateStr = _ET_DATE.format(d); // "YYYY-MM-DD"
  const hmParts = _ET_HM.formatToParts(d);
  const hr = parseInt(hmParts.find((p) => p.type === "hour")?.value ?? "0", 10);
  return { date: dateStr, hour: hr };
}

/** Parse a possibly-naive ISO timestamp as UTC.
 *
 * Backend pydantic + SQLAlchemy DateTime(timezone=True) usually emits an
 * offset, but some serialization paths drop it. Without a tz marker the
 * native ``new Date(iso)`` interprets the string as LOCAL time — which
 * shifts the trade by the user's tz offset and misclassifies its
 * trading day (a 5/14 21:30 BJ trade would land at 5/14 09:30 of whatever
 * the local tz is, not 5/14 09:30 ET).  Adding a trailing "Z" forces
 * UTC parsing, after which the Intl ET formatter does the right thing.
 */
export function parseUtc(iso: string | Date): Date {
  if (iso instanceof Date) return iso;
  const hasTz = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return new Date(hasTz ? iso : iso + "Z");
}

export function tradingDayOfET(iso: string | Date): string {
  const d = parseUtc(iso);
  const { date, hour } = _etDateAndHour(d);
  if (hour < 4) {
    // 00:00-04:00 ET is still the tail of yesterday's trading day.
    const prev = new Date(d.getTime() - 24 * 60 * 60 * 1000);
    return _ET_DATE.format(prev);
  }
  return date;
}

/** The trading day the wall clock is currently inside. */
export function currentTradingDay(): string {
  return tradingDayOfET(new Date(Date.now()));
}

/** Like ``currentTradingDay`` but on weekends/holidays walks back to the
 *  most recent weekday. Use this for filters that match "today's trades"
 *  in contexts where Saturday should treat Friday's session as today —
 *  Day P/L on a closed weekend, for instance, where Friday's executions
 *  are the most recent activity to attribute. (Holidays aren't checked
 *  against a calendar; we step over Sat/Sun only.) */
export function currentOrLastTradingDay(): string {
  const today = currentTradingDay();
  const [y, m, d] = today.split("-").map(Number);
  // Reference noon UTC of the candidate date so DST / midnight edge
  // cases don't flip which day we land on.
  let ms = Date.UTC(y, m - 1, d, 12);
  for (let i = 0; i < 7; i++) {
    const wd = new Date(ms).getUTCDay(); // 0 = Sun, 6 = Sat
    if (wd >= 1 && wd <= 5) {
      return _ET_DATE.format(new Date(ms));
    }
    ms -= 24 * 60 * 60 * 1000;
  }
  return today;
}

export function classifyETSession(iso: string): ETSession {
  const d = new Date(iso);
  const parts = _ET_HM.formatToParts(d);
  const hr = parseInt(parts.find((p) => p.type === "hour")?.value ?? "0", 10);
  const mn = parseInt(parts.find((p) => p.type === "minute")?.value ?? "0", 10);
  const mins = hr * 60 + mn;
  // en-US with hour12=false on Intl emits "24" for midnight on some
  // engines — fold to 0 so the range checks below work.
  const norm = mins >= 24 * 60 ? mins - 24 * 60 : mins;
  if (norm >= 4 * 60 && norm < 9 * 60 + 30) return "pre";
  if (norm >= 9 * 60 + 30 && norm < 16 * 60) return "regular";
  if (norm >= 16 * 60 && norm < 20 * 60) return "post";
  return "overnight";
}

const _BJ_MONTH = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
});

const _BJ_YEAR = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
});

/** "2026-03" — used on month-K x-axis ticks. */
export function fmtBjMonth(iso: string): string {
  const d = parseUtc(iso);
  // en-CA → "YYYY-MM" (no day field) — strip any trailing day if present.
  return _BJ_MONTH.format(d).slice(0, 7);
}

/** "2026" — used on year-K x-axis ticks. */
export function fmtBjYear(iso: string): string {
  return _BJ_YEAR.format(parseUtc(iso));
}

/** "2026-W19" — ISO-8601 week date in BJ tz. Used on week-K x-axis ticks.
 *  ISO weeks start on Monday and week 1 is the week containing the first
 *  Thursday of the calendar year. */
export function fmtBjWeekISO(iso: string): string {
  // Project the BJ-tz date by adding 8h then reading the UTC components.
  const d = parseUtc(iso);
  const bjMs = d.getTime() + 8 * 60 * 60 * 1000;
  const bj = new Date(bjMs);
  // Move to the Thursday in this week (Mon=1, Sun=7 — ISO).
  const dayNum = bj.getUTCDay() || 7; // Sun(0) → 7
  // Use UTC midnight for Thursday so time-of-day doesn't skew the week math.
  const thursdayMs = Date.UTC(
    bj.getUTCFullYear(),
    bj.getUTCMonth(),
    bj.getUTCDate() + (4 - dayNum),
  );
  const thursday = new Date(thursdayMs);
  const year = thursday.getUTCFullYear();
  // Week 1 = the week with Jan 4 (which is always in week 1 by ISO def).
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Day = jan4.getUTCDay() || 7;
  const week1Mon = new Date(jan4.getTime() - (jan4Day - 1) * 24 * 60 * 60 * 1000);
  const weekNum = Math.round(
    (thursdayMs - week1Mon.getTime()) / (7 * 24 * 60 * 60 * 1000),
  ) + 1;
  return `${year}-W${String(weekNum).padStart(2, "0")}`;
}

/** "今天 10:30" / "昨天 10:30" / "05/14 10:30" — used in TradeList and
 *  PairList rows so they read in BJ time regardless of browser locale. */
export function fmtBjRel(iso: string): string {
  if (!iso) return "—";
  // Use Date.now() (rather than `new Date()`) so test stubs of the clock
  // work — `new Date()` reads system time directly and bypasses
  // `Date.now` overrides.
  const nowMs = Date.now();
  const todayKey = _bjDayKey(new Date(nowMs).toISOString());
  const targetKey = _bjDayKey(iso);
  const time = fmtBjHM(iso);
  if (targetKey === todayKey) return `今天 ${time}`;
  // Compute yesterday key by subtracting one day in UTC then re-projecting.
  const yest = new Date(nowMs - 24 * 60 * 60 * 1000);
  if (_bjDayKey(yest.toISOString()) === targetKey) return `昨天 ${time}`;
  return `${fmtBjDate(iso)} ${time}`;
}
