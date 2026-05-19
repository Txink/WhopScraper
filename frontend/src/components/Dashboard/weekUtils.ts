import type { TaskSummary } from "../../api/domain-types";

const _BJ_PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  weekday: "short",
});

/**
 * Sunday-of-week key (YYYY-MM-DD) computed in Asia/Shanghai.
 *
 * Backend timestamps are real UTC; the user thinks in Beijing. We project
 * the moment into Beijing, find that day's calendar date, then walk back
 * to the most recent Sunday — purely as date arithmetic, never as
 * tz-sensitive Date math.
 */
export function weekKeyOf(ts: string): string {
  const d = new Date(ts);
  const parts = _BJ_PARTS.formatToParts(d);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const y = Number(get("year"));
  const mo = Number(get("month"));
  const dd = Number(get("day"));
  const weekdayShort = get("weekday"); // "Sun" | "Mon" | ...
  const wdMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const wd = wdMap[weekdayShort] ?? 0;

  if (!y || !mo || !dd || !(weekdayShort in wdMap)) {
    throw new Error(`weekKeyOf: bad parts for "${ts}"`);
  }

  // Walk back `wd` days using a date-only UTC anchor (avoids host-tz drift).
  const anchor = new Date(Date.UTC(y, mo - 1, dd));
  anchor.setUTCDate(anchor.getUTCDate() - wd);
  const yyyy = anchor.getUTCFullYear();
  const mm = String(anchor.getUTCMonth() + 1).padStart(2, "0");
  const day = String(anchor.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${day}`;
}

/**
 * Today's ISO week label (``YYYY-Www``) anchored to Asia/Shanghai.
 *
 * Used as the ``week`` query param for the chat-messages endpoint, which
 * parses the value with ``_iso_week_bounds`` (backend/app/api/http.py).
 *
 * Pure: derives the Beijing calendar date via Intl, then computes ISO
 * week number with standard date arithmetic on a UTC anchor (no host-tz
 * drift). Returns e.g. ``"2026-W21"``.
 *
 * TODO(future): week navigation for chat pages — currently App.tsx always
 * passes the current ISO week to ``<ChatBoardPanel>``.
 */
export function currentIsoWeek(): string {
  const parts = _BJ_PARTS.formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const y = Number(get("year"));
  const mo = Number(get("month"));
  const dd = Number(get("day"));
  if (!y || !mo || !dd) {
    throw new Error("currentIsoWeek: bad Beijing date parts");
  }

  // ISO 8601 week-number algorithm (Mon=1..Sun=7). Operate on a date-only
  // UTC anchor so day arithmetic is tz-independent.
  const anchor = new Date(Date.UTC(y, mo - 1, dd));
  const dayNum = anchor.getUTCDay() || 7;            // Sun=0 → 7
  anchor.setUTCDate(anchor.getUTCDate() + 4 - dayNum); // shift to Thursday of this ISO week
  const yearStart = new Date(Date.UTC(anchor.getUTCFullYear(), 0, 1));
  const weekNum = Math.ceil(
    ((anchor.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7,
  );
  return `${anchor.getUTCFullYear()}-W${String(weekNum).padStart(2, "0")}`;
}

export interface WeekRange {
  startLabel: string;
  endLabel: string;
}

export function formatWeekRange(weekKey: string): WeekRange {
  const [y, m, d] = weekKey.split("-").map(Number);
  const start = new Date(y, m - 1, d);
  const end = new Date(y, m - 1, d + 6);
  const fmt = (date: Date) =>
    `${String(date.getMonth() + 1).padStart(2, "0")}/${String(
      date.getDate(),
    ).padStart(2, "0")}`;
  return { startLabel: fmt(start), endLabel: fmt(end) };
}

export interface WeekInfo {
  key: string;
  startLabel: string;
  endLabel: string;
}

export interface ComputedWeeks {
  groups: Map<string, TaskSummary[]>;
  weeks: WeekInfo[];
}

function taskTime(t: TaskSummary): string {
  return t.message?.posted_at ?? t.created_at;
}

/** Compute the start (Mon 00:00) and end (next Mon 00:00) of an ISO week
 *  given its key like "2026-W21". Returns ISO datetime strings without
 *  timezone, suitable as backend query params. */
export function isoWeekBounds(weekKey: string): { start: string; end: string } {
  const m = weekKey.match(/^(\d{4})-W(\d{2})$/);
  if (!m) throw new Error(`isoWeekBounds: invalid weekKey "${weekKey}"`);
  const year = Number(m[1]);
  const week = Number(m[2]);
  // ISO 8601: week 1 is the week containing Jan 4. Find that week's Monday.
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Day = jan4.getUTCDay() || 7;                  // Sun=0 → 7
  const week1Mon = new Date(jan4);
  week1Mon.setUTCDate(jan4.getUTCDate() - jan4Day + 1);   // backtrack to Mon
  const start = new Date(week1Mon);
  start.setUTCDate(week1Mon.getUTCDate() + (week - 1) * 7);
  const end = new Date(start);
  end.setUTCDate(start.getUTCDate() + 7);
  // Strip seconds + Z so backend's naive datetime accepts.
  const fmt = (d: Date) =>
    `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}T00:00:00`;
  return { start: fmt(start), end: fmt(end) };
}

export function computeWeeks(tasks: TaskSummary[]): ComputedWeeks {
  const sorted = [...tasks].sort((a, b) => taskTime(b).localeCompare(taskTime(a)));
  const groups = new Map<string, TaskSummary[]>();
  for (const t of sorted) {
    const key = weekKeyOf(taskTime(t));
    let bucket = groups.get(key);
    if (!bucket) {
      bucket = [];
      groups.set(key, bucket);
    }
    bucket.push(t);
  }
  const weeks: WeekInfo[] = Array.from(groups.keys()).map((key) => ({
    key,
    ...formatWeekRange(key),
  }));
  return { groups, weeks };
}
