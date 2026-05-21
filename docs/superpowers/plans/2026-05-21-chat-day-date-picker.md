# Chat Day Date Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a floating bottom-right date picker to `ChatBoardPanel` so users can browse discussion messages one day at a time, with prev/next arrows and a month-grid calendar popup.

**Architecture:** The panel keeps fetching by ISO-week (server unchanged). New local state `selectedDate` controls a client-side day filter on the cached week. The ISO-week passed to `useChatStore.fetch` is *derived* from `selectedDate`, so crossing weeks via the arrows auto-triggers the existing week fetch. When the calendar pops open, the visible month's covering weeks are prefetched so each day's "has messages" dot can be reliably rendered. No third-party date library — `weekUtils.ts` gains 7 pure helpers (already Asia/Shanghai-aware in style).

**Tech Stack:** React + TypeScript, Zustand (`useChatStore`), Vitest, plain CSS. Date math via `Intl.DateTimeFormat` + UTC-anchored arithmetic (matches existing `weekUtils.ts` style).

**Spec:** `docs/superpowers/specs/2026-05-21-chat-day-date-picker-design.md`

---

## File Structure

**Create:**
- `frontend/src/components/Chat/DayPicker.tsx` — Floating control (arrows + center button), owns calendar-open state, glue to filter
- `frontend/src/components/Chat/CalendarPopover.tsx` — Month-grid calendar popup (purely presentational)
- `frontend/src/components/Chat/DayPicker.css` — Styles for both the floating control and popover

**Modify:**
- `frontend/src/components/Dashboard/weekUtils.ts` — Add `dayKeyOf`, `todayInShanghai`, `addDays`, `monthOf`, `daysInMonth`, `isoWeekOfDay`, `weeksCoveringMonth`, `formatDayLabel`
- `frontend/src/components/Dashboard/weekUtils.test.ts` — Tests for the 7 new helpers
- `frontend/src/components/Chat/ChatBoardPanel.tsx` — Drop `week` prop, own `selectedDate`, day-filter messages + tasks, mount `<DayPicker />`, prefetch effect
- `frontend/src/components/Chat/ChatBoardPanel.css` — Ensure `.chat-panel` is `position: relative` and add space-for-overlay rules
- `frontend/src/App.tsx` — Remove `currentIsoWeek()` import (if unused after), drop `week` prop on `<ChatBoardPanel>`, remove the TODO comment

**Don't touch:**
- Backend (no schema/endpoint changes)
- `chatStore.ts`, `chat.ts` (cache and API stay as-is)
- `chatCards.ts`, `chatTimeline.ts` (logic gets a smaller input set, code unchanged)
- `ChatSenderBar.tsx`

---

## Task 1: Add `dayKeyOf`, `todayInShanghai`, `addDays`, `monthOf` to weekUtils

**Files:**
- Modify: `frontend/src/components/Dashboard/weekUtils.ts`
- Test: `frontend/src/components/Dashboard/weekUtils.test.ts`

- [ ] **Step 1.1: Write failing tests for `dayKeyOf`**

Append to `frontend/src/components/Dashboard/weekUtils.test.ts`:

```ts
describe("dayKeyOf", () => {
  it("returns the Beijing-calendar YYYY-MM-DD for an afternoon timestamp", () => {
    // 2026-05-21 14:00 Beijing = 2026-05-21T06:00:00Z UTC
    expect(dayKeyOf("2026-05-21T06:00:00Z")).toBe("2026-05-21");
  });

  it("returns Beijing's date for a midnight-edge UTC timestamp", () => {
    // 2026-05-20 16:30 UTC = 2026-05-21 00:30 Beijing → '2026-05-21'
    expect(dayKeyOf("2026-05-20T16:30:00Z")).toBe("2026-05-21");
  });

  it("returns the prior day for a late-night Beijing → UTC offset case", () => {
    // 2026-05-21 15:59 UTC = 2026-05-21 23:59 Beijing → '2026-05-21'
    expect(dayKeyOf("2026-05-21T15:59:00Z")).toBe("2026-05-21");
    // 2026-05-21 16:00 UTC = 2026-05-22 00:00 Beijing → '2026-05-22'
    expect(dayKeyOf("2026-05-21T16:00:00Z")).toBe("2026-05-22");
  });
});
```

Also update the import at the top of the test file:

```ts
import {
  weekKeyOf,
  formatWeekRange,
  computeWeeks,
  isoWeekBounds,
  dayKeyOf,
} from "./weekUtils";
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts
```

Expected: type-check or runtime errors mentioning `dayKeyOf is not exported` / `is not defined`.

- [ ] **Step 1.3: Implement `dayKeyOf`**

Append to `frontend/src/components/Dashboard/weekUtils.ts` (after the existing `_BJ_PARTS` and `weekKeyOf`):

```ts
/**
 * Beijing-calendar YYYY-MM-DD for any ISO timestamp. Same projection as
 * weekKeyOf — go through Intl to extract the Beijing date parts.
 */
export function dayKeyOf(isoTs: string): string {
  const parts = _BJ_PARTS.formatToParts(new Date(isoTs));
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "";
  const y = get("year");
  const mo = get("month");
  const dd = get("day");
  if (!y || !mo || !dd) {
    throw new Error(`dayKeyOf: bad parts for "${isoTs}"`);
  }
  return `${y}-${mo}-${dd}`;
}
```

- [ ] **Step 1.4: Verify `dayKeyOf` tests pass**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t dayKeyOf
```

Expected: 3 tests pass.

- [ ] **Step 1.5: Write failing tests for `todayInShanghai` + `addDays` + `monthOf`**

Append:

```ts
describe("todayInShanghai", () => {
  it("returns a string in YYYY-MM-DD shape", () => {
    const v = todayInShanghai();
    expect(v).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("matches dayKeyOf(new Date().toISOString())", () => {
    expect(todayInShanghai()).toBe(dayKeyOf(new Date().toISOString()));
  });
});

describe("addDays", () => {
  it("adds and subtracts days within a month", () => {
    expect(addDays("2026-05-21", 1)).toBe("2026-05-22");
    expect(addDays("2026-05-21", -1)).toBe("2026-05-20");
    expect(addDays("2026-05-21", 0)).toBe("2026-05-21");
  });

  it("rolls over month boundaries", () => {
    expect(addDays("2026-05-31", 1)).toBe("2026-06-01");
    expect(addDays("2026-06-01", -1)).toBe("2026-05-31");
  });

  it("rolls over year boundaries", () => {
    expect(addDays("2025-12-31", 1)).toBe("2026-01-01");
    expect(addDays("2026-01-01", -1)).toBe("2025-12-31");
  });

  it("handles Feb 29 in a leap year", () => {
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
    expect(addDays("2028-02-29", 1)).toBe("2028-03-01");
  });
});

describe("monthOf", () => {
  it("returns YYYY-MM", () => {
    expect(monthOf("2026-05-21")).toBe("2026-05");
    expect(monthOf("2026-01-01")).toBe("2026-01");
    expect(monthOf("2025-12-31")).toBe("2025-12");
  });
});
```

Update the import line:

```ts
import {
  weekKeyOf,
  formatWeekRange,
  computeWeeks,
  isoWeekBounds,
  dayKeyOf,
  todayInShanghai,
  addDays,
  monthOf,
} from "./weekUtils";
```

- [ ] **Step 1.6: Run tests to verify they fail**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts
```

Expected: errors about missing exports.

- [ ] **Step 1.7: Implement `todayInShanghai`, `addDays`, `monthOf`**

Append to `weekUtils.ts`:

```ts
export function todayInShanghai(): string {
  return dayKeyOf(new Date().toISOString());
}

/** Parse "YYYY-MM-DD" via UTC anchor → add `n` days → reformat. Pure
 *  date arithmetic, immune to host-tz drift. */
export function addDays(dayKey: string, n: number): string {
  const m = dayKey.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) throw new Error(`addDays: invalid dayKey "${dayKey}"`);
  const anchor = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  anchor.setUTCDate(anchor.getUTCDate() + n);
  const y = anchor.getUTCFullYear();
  const mo = String(anchor.getUTCMonth() + 1).padStart(2, "0");
  const d = String(anchor.getUTCDate()).padStart(2, "0");
  return `${y}-${mo}-${d}`;
}

export function monthOf(dayKey: string): string {
  const m = dayKey.match(/^(\d{4})-(\d{2})-\d{2}$/);
  if (!m) throw new Error(`monthOf: invalid dayKey "${dayKey}"`);
  return `${m[1]}-${m[2]}`;
}
```

- [ ] **Step 1.8: Verify all Task 1 tests pass**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts
```

Expected: all `dayKeyOf` / `todayInShanghai` / `addDays` / `monthOf` tests pass; no other failures.

- [ ] **Step 1.9: Commit**

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/components/Dashboard/weekUtils.ts frontend/src/components/Dashboard/weekUtils.test.ts
git commit -m "feat(weekUtils): add dayKeyOf, todayInShanghai, addDays, monthOf helpers"
```

---

## Task 2: Add `daysInMonth`, `isoWeekOfDay`, `weeksCoveringMonth`, `formatDayLabel`

**Files:**
- Modify: `frontend/src/components/Dashboard/weekUtils.ts`
- Test: `frontend/src/components/Dashboard/weekUtils.test.ts`

- [ ] **Step 2.1: Write failing tests for `daysInMonth`**

Append:

```ts
describe("daysInMonth", () => {
  it("returns 31 day-keys for May 2026", () => {
    const days = daysInMonth("2026-05");
    expect(days).toHaveLength(31);
    expect(days[0]).toBe("2026-05-01");
    expect(days[30]).toBe("2026-05-31");
  });

  it("returns 30 day-keys for June 2026", () => {
    expect(daysInMonth("2026-06")).toHaveLength(30);
  });

  it("returns 28 day-keys for February 2026 (non-leap)", () => {
    const days = daysInMonth("2026-02");
    expect(days).toHaveLength(28);
    expect(days[27]).toBe("2026-02-28");
  });

  it("returns 29 day-keys for February 2028 (leap)", () => {
    const days = daysInMonth("2028-02");
    expect(days).toHaveLength(29);
    expect(days[28]).toBe("2028-02-29");
  });
});
```

- [ ] **Step 2.2: Verify failure**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t daysInMonth
```

Expected: fail (undefined).

- [ ] **Step 2.3: Implement `daysInMonth`**

```ts
export function daysInMonth(monthKey: string): string[] {
  const m = monthKey.match(/^(\d{4})-(\d{2})$/);
  if (!m) throw new Error(`daysInMonth: invalid monthKey "${monthKey}"`);
  const year = Number(m[1]);
  const month = Number(m[2]);
  // Day 0 of next month = last day of this month (UTC date math).
  const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const out: string[] = [];
  for (let d = 1; d <= lastDay; d++) {
    out.push(`${m[1]}-${m[2]}-${String(d).padStart(2, "0")}`);
  }
  return out;
}
```

Update imports in test file:

```ts
import {
  weekKeyOf,
  formatWeekRange,
  computeWeeks,
  isoWeekBounds,
  dayKeyOf,
  todayInShanghai,
  addDays,
  monthOf,
  daysInMonth,
} from "./weekUtils";
```

- [ ] **Step 2.4: Verify `daysInMonth` passes**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t daysInMonth
```

Expected: 4 tests pass.

- [ ] **Step 2.5: Write failing tests for `isoWeekOfDay`**

Append:

```ts
describe("isoWeekOfDay", () => {
  it("returns 'YYYY-Www' for a mid-week date", () => {
    // 2026-05-21 is a Thursday in week 21 of 2026.
    expect(isoWeekOfDay("2026-05-21")).toBe("2026-W21");
  });

  it("matches currentIsoWeek() for today", () => {
    // Sanity: a same-day comparison should agree.
    const today = todayInShanghai();
    expect(isoWeekOfDay(today)).toBe(currentIsoWeek());
  });

  it("handles year-boundary ISO weeks (early January assigned to prior year)", () => {
    // 2027-01-01 is a Friday; ISO week 53 of 2026 (or W01 of 2027 depending on year).
    // Sanity-check the shape only.
    expect(isoWeekOfDay("2027-01-01")).toMatch(/^\d{4}-W\d{2}$/);
  });
});
```

Update imports in test file:

```ts
import {
  weekKeyOf,
  formatWeekRange,
  computeWeeks,
  isoWeekBounds,
  currentIsoWeek,
  dayKeyOf,
  todayInShanghai,
  addDays,
  monthOf,
  daysInMonth,
  isoWeekOfDay,
} from "./weekUtils";
```

- [ ] **Step 2.6: Verify failure**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t isoWeekOfDay
```

Expected: fail.

- [ ] **Step 2.7: Implement `isoWeekOfDay`**

```ts
/** ISO-8601 week label "YYYY-Www" for a Beijing-calendar dayKey. The
 *  ISO year and week number can differ from the input year around
 *  Jan/Dec boundaries (e.g. 2027-01-01 may fall in 2026-W53). */
export function isoWeekOfDay(dayKey: string): string {
  const m = dayKey.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) throw new Error(`isoWeekOfDay: invalid dayKey "${dayKey}"`);
  const y = Number(m[1]);
  const mo = Number(m[2]);
  const d = Number(m[3]);
  const anchor = new Date(Date.UTC(y, mo - 1, d));
  const dayNum = anchor.getUTCDay() || 7;            // Sun=0 → 7
  anchor.setUTCDate(anchor.getUTCDate() + 4 - dayNum); // Thursday of this ISO week
  const yearStart = new Date(Date.UTC(anchor.getUTCFullYear(), 0, 1));
  const weekNum = Math.ceil(
    ((anchor.getTime() - yearStart.getTime()) / 86_400_000 + 1) / 7,
  );
  return `${anchor.getUTCFullYear()}-W${String(weekNum).padStart(2, "0")}`;
}
```

- [ ] **Step 2.8: Verify `isoWeekOfDay` passes**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t isoWeekOfDay
```

Expected: 3 tests pass.

- [ ] **Step 2.9: Write failing tests for `weeksCoveringMonth`**

Append:

```ts
describe("weeksCoveringMonth", () => {
  it("returns the distinct ISO weeks touched by every day of the month, in order", () => {
    // May 2026 — Fri May 1 → Sun May 31. Weeks: W18..W22 (5 weeks).
    const weeks = weeksCoveringMonth("2026-05");
    expect(weeks.length).toBeGreaterThanOrEqual(4);
    expect(weeks.length).toBeLessThanOrEqual(6);
    // All should match "YYYY-Www" shape.
    weeks.forEach((w) => expect(w).toMatch(/^\d{4}-W\d{2}$/));
    // No duplicates.
    expect(new Set(weeks).size).toBe(weeks.length);
    // First week is the one containing May 1.
    expect(weeks[0]).toBe(isoWeekOfDay("2026-05-01"));
    // Last week contains May 31.
    expect(weeks[weeks.length - 1]).toBe(isoWeekOfDay("2026-05-31"));
  });
});
```

Update imports:

```ts
import {
  // ...prior imports...
  weeksCoveringMonth,
} from "./weekUtils";
```

- [ ] **Step 2.10: Verify failure**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t weeksCoveringMonth
```

- [ ] **Step 2.11: Implement `weeksCoveringMonth`**

```ts
export function weeksCoveringMonth(monthKey: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const day of daysInMonth(monthKey)) {
    const w = isoWeekOfDay(day);
    if (!seen.has(w)) {
      seen.add(w);
      out.push(w);
    }
  }
  return out;
}
```

- [ ] **Step 2.12: Verify `weeksCoveringMonth` passes**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t weeksCoveringMonth
```

- [ ] **Step 2.13: Write failing tests for `formatDayLabel`**

Append (note: tests use a fake-timer / dependency trick — we just compare relative to `todayInShanghai()`):

```ts
describe("formatDayLabel", () => {
  it("returns '今天' for today's dayKey", () => {
    expect(formatDayLabel(todayInShanghai())).toBe("今天");
  });

  it("returns '昨天' for yesterday's dayKey", () => {
    expect(formatDayLabel(addDays(todayInShanghai(), -1))).toBe("昨天");
  });

  it("returns 'M月D日 周X' for a same-year non-recent date", () => {
    // Pick an arbitrary same-year date that is definitely not today/yesterday.
    // Use the first of January in the current year as a safe choice (unless today is Jan 1/2).
    const today = todayInShanghai();
    const year = today.slice(0, 4);
    const candidate = `${year}-07-15`; // mid-July; safe regardless of when test runs
    if (candidate === today || candidate === addDays(today, -1)) {
      // skip in the extremely unlikely case
      return;
    }
    const label = formatDayLabel(candidate);
    // Expect a Chinese-month-day prefix and a 周X suffix.
    expect(label).toMatch(/^\d{1,2}月\d{1,2}日 周[一二三四五六日]$/);
    expect(label).toContain("7月15日");
  });

  it("returns 'YYYY年M月D日 周X' for a cross-year date", () => {
    const today = todayInShanghai();
    const year = Number(today.slice(0, 4));
    const otherYear = year - 1;
    const label = formatDayLabel(`${otherYear}-01-15`);
    expect(label).toMatch(/^\d{4}年\d{1,2}月\d{1,2}日 周[一二三四五六日]$/);
    expect(label).toContain(`${otherYear}年`);
  });
});
```

Update imports:

```ts
import {
  // ...prior imports...
  formatDayLabel,
} from "./weekUtils";
```

- [ ] **Step 2.14: Verify failure**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts -t formatDayLabel
```

- [ ] **Step 2.15: Implement `formatDayLabel`**

```ts
const _BJ_WEEKDAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Shanghai",
  weekday: "short",
});

const _WEEKDAY_ZH: Record<string, string> = {
  Sun: "周日",
  Mon: "周一",
  Tue: "周二",
  Wed: "周三",
  Thu: "周四",
  Fri: "周五",
  Sat: "周六",
};

function _weekdayZh(dayKey: string): string {
  // Use noon UTC to avoid any tz ambiguity — we already know the
  // calendar date; we just need its weekday name.
  const m = dayKey.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) throw new Error(`_weekdayZh: invalid dayKey "${dayKey}"`);
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12));
  const wd = _BJ_WEEKDAY.formatToParts(d).find((p) => p.type === "weekday")?.value ?? "";
  return _WEEKDAY_ZH[wd] ?? wd;
}

/** Chinese-friendly day label. Rules:
 *   - today        → "今天"
 *   - yesterday    → "昨天"
 *   - same year    → "5月18日 周日"
 *   - cross year   → "2025年12月31日 周三"
 */
export function formatDayLabel(dayKey: string): string {
  const today = todayInShanghai();
  if (dayKey === today) return "今天";
  if (dayKey === addDays(today, -1)) return "昨天";
  const [y, mo, d] = dayKey.split("-").map(Number);
  const wd = _weekdayZh(dayKey);
  const sameYear = String(y) === today.slice(0, 4);
  return sameYear
    ? `${mo}月${d}日 ${wd}`
    : `${y}年${mo}月${d}日 ${wd}`;
}
```

- [ ] **Step 2.16: Verify all weekUtils tests pass**

```bash
cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts
```

Expected: every test green.

- [ ] **Step 2.17: Commit**

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/components/Dashboard/weekUtils.ts frontend/src/components/Dashboard/weekUtils.test.ts
git commit -m "feat(weekUtils): add daysInMonth, isoWeekOfDay, weeksCoveringMonth, formatDayLabel"
```

---

## Task 3: Build `CalendarPopover` component

**Files:**
- Create: `frontend/src/components/Chat/CalendarPopover.tsx`
- Create: `frontend/src/components/Chat/DayPicker.css` (shared with Task 4)

- [ ] **Step 3.1: Create `DayPicker.css` with the popover styles**

Create `frontend/src/components/Chat/DayPicker.css`:

```css
/* Floating bottom-right control */
.day-picker {
  position: absolute;
  right: 12px;
  bottom: 12px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  background: rgba(20, 22, 28, 0.82);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.32);
  color: #e7e9ee;
  font-size: 13px;
  user-select: none;
}

.day-picker-arrow {
  background: transparent;
  border: none;
  color: inherit;
  font-size: 16px;
  line-height: 1;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.day-picker-arrow:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
}
.day-picker-arrow:disabled {
  opacity: 0.32;
  cursor: not-allowed;
}

.day-picker-center {
  background: transparent;
  border: none;
  color: inherit;
  padding: 4px 10px;
  border-radius: 12px;
  cursor: pointer;
  font: inherit;
  min-width: 96px;
  text-align: center;
}
.day-picker-center:hover { background: rgba(255, 255, 255, 0.08); }

/* Calendar popover anchored above the center button */
.calendar-popover {
  position: absolute;
  bottom: calc(100% + 8px);
  right: 0;
  background: #1c1f26;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
  width: 280px;
  color: #e7e9ee;
  font-size: 13px;
}
.calendar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.calendar-head button {
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
  width: 24px;
  height: 24px;
  border-radius: 50%;
}
.calendar-head button:hover { background: rgba(255, 255, 255, 0.08); }
.calendar-head .calendar-title { font-weight: 600; }

.calendar-week-names {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
  text-align: center;
  color: rgba(231, 233, 238, 0.5);
  font-size: 11px;
  margin-bottom: 4px;
}

.calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 2px;
}
.calendar-cell {
  position: relative;
  aspect-ratio: 1;
  border: none;
  background: transparent;
  color: inherit;
  border-radius: 8px;
  cursor: pointer;
  font: inherit;
  padding: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.calendar-cell:hover:not(:disabled) { background: rgba(255, 255, 255, 0.08); }
.calendar-cell:disabled { opacity: 0.28; cursor: not-allowed; }
.calendar-cell.is-other-month { color: rgba(231, 233, 238, 0.32); }
.calendar-cell.is-today { box-shadow: inset 0 0 0 1px #4f9cf9; }
.calendar-cell.is-selected { background: #2f6ed1; color: #fff; }
.calendar-cell.is-selected:hover { background: #3c79d8; }

.calendar-dot {
  position: absolute;
  bottom: 4px;
  left: 50%;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #4f9cf9;
  transform: translateX(-50%);
}
.calendar-cell.is-selected .calendar-dot { background: #fff; }

.calendar-loading {
  margin-top: 8px;
  font-size: 11px;
  color: rgba(231, 233, 238, 0.5);
  text-align: center;
}
```

- [ ] **Step 3.2: Create `CalendarPopover.tsx`**

```tsx
import React, { useEffect, useMemo, useRef } from "react";
import {
  addDays,
  daysInMonth,
  monthOf,
  todayInShanghai,
} from "../Dashboard/weekUtils";
import "./DayPicker.css";

interface Props {
  /** "YYYY-MM" — controls which month grid is shown. */
  visibleMonth: string;
  /** "YYYY-MM-DD" — currently selected day (may be outside visibleMonth). */
  selectedDate: string;
  /** Latest selectable date; days after this are disabled. */
  maxDate: string;
  /** Whether to show a dot under a given day (caller's data source). */
  hasMessagesOnDay: (dayKey: string) => boolean;
  /** Optional "loading" indicator at the bottom while prefetch is in flight. */
  loading?: boolean;
  onMonthChange: (nextMonthKey: string) => void;
  onPickDay: (dayKey: string) => void;
  onClose: () => void;
}

/** 6-row × 7-col fixed grid starting on Monday. Cells before the 1st and
 *  after the last belong to neighboring months (rendered dim, still
 *  clickable so the user can jump into them). */
function buildGrid(monthKey: string): { dayKey: string; inMonth: boolean }[] {
  const days = daysInMonth(monthKey);
  const first = days[0];
  const last = days[days.length - 1];
  // Beijing-calendar weekday of the 1st (we don't need a tz here — we're
  // computing the grid layout, not labels). Use the same UTC trick.
  const m = first.match(/^(\d{4})-(\d{2})-(\d{2})$/)!;
  const firstAnchor = new Date(
    Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])),
  );
  const firstWdSun0 = firstAnchor.getUTCDay(); // Sun=0..Sat=6
  // Convert to Monday-first index (Mon=0..Sun=6).
  const firstWdMon0 = (firstWdSun0 + 6) % 7;

  const cells: { dayKey: string; inMonth: boolean }[] = [];
  // Leading days from previous month.
  for (let i = firstWdMon0; i > 0; i--) {
    cells.push({ dayKey: addDays(first, -i), inMonth: false });
  }
  // Days in this month.
  for (const d of days) {
    cells.push({ dayKey: d, inMonth: true });
  }
  // Trailing days to fill 6 rows (42 cells) for a stable height.
  while (cells.length < 42) {
    cells.push({
      dayKey: addDays(last, cells.length - (firstWdMon0 + days.length) + 1),
      inMonth: false,
    });
  }
  return cells;
}

export function CalendarPopover({
  visibleMonth,
  selectedDate,
  maxDate,
  hasMessagesOnDay,
  loading,
  onMonthChange,
  onPickDay,
  onClose,
}: Props) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  // Click-outside-to-close.
  useEffect(() => {
    function onDocMouseDown(e: MouseEvent) {
      if (!rootRef.current) return;
      if (!rootRef.current.contains(e.target as Node)) onClose();
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [onClose]);

  const cells = useMemo(() => buildGrid(visibleMonth), [visibleMonth]);
  const today = todayInShanghai();

  const [year, monthNum] = visibleMonth.split("-").map(Number);
  const titleZh = `${year} 年 ${monthNum} 月`;

  const prevMonthKey = (mk: string): string => {
    const [y, m] = mk.split("-").map(Number);
    const ny = m === 1 ? y - 1 : y;
    const nm = m === 1 ? 12 : m - 1;
    return `${ny}-${String(nm).padStart(2, "0")}`;
  };
  const nextMonthKey = (mk: string): string => {
    const [y, m] = mk.split("-").map(Number);
    const ny = m === 12 ? y + 1 : y;
    const nm = m === 12 ? 1 : m + 1;
    return `${ny}-${String(nm).padStart(2, "0")}`;
  };

  return (
    <div className="calendar-popover" ref={rootRef} role="dialog" aria-label="选择日期">
      <div className="calendar-head">
        <button
          type="button"
          aria-label="上个月"
          onClick={() => onMonthChange(prevMonthKey(visibleMonth))}
        >
          ‹
        </button>
        <div className="calendar-title">{titleZh}</div>
        <button
          type="button"
          aria-label="下个月"
          onClick={() => onMonthChange(nextMonthKey(visibleMonth))}
        >
          ›
        </button>
      </div>
      <div className="calendar-week-names">
        <span>一</span><span>二</span><span>三</span><span>四</span>
        <span>五</span><span>六</span><span>日</span>
      </div>
      <div className="calendar-grid">
        {cells.map(({ dayKey, inMonth }) => {
          const disabled = dayKey > maxDate;
          const isToday = dayKey === today;
          const isSelected = dayKey === selectedDate;
          const showDot = hasMessagesOnDay(dayKey);
          const classes = [
            "calendar-cell",
            !inMonth && "is-other-month",
            isToday && "is-today",
            isSelected && "is-selected",
          ]
            .filter(Boolean)
            .join(" ");
          // Display the bare day number (1..31).
          const dayNum = Number(dayKey.slice(-2));
          return (
            <button
              key={dayKey}
              type="button"
              className={classes}
              disabled={disabled}
              onClick={() => {
                if (!inMonth) onMonthChange(monthOf(dayKey));
                onPickDay(dayKey);
              }}
            >
              {dayNum}
              {showDot && <span className="calendar-dot" />}
            </button>
          );
        })}
      </div>
      {loading && <div className="calendar-loading">加载中…</div>}
    </div>
  );
}
```

- [ ] **Step 3.3: Type-check the project**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no new TypeScript errors. If errors appear that reference these new files, fix them inline before moving on.

- [ ] **Step 3.4: Commit**

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/components/Chat/CalendarPopover.tsx frontend/src/components/Chat/DayPicker.css
git commit -m "feat(chat): add CalendarPopover (month grid with has-messages markers)"
```

---

## Task 4: Build `DayPicker` component

**Files:**
- Create: `frontend/src/components/Chat/DayPicker.tsx`

- [ ] **Step 4.1: Create `DayPicker.tsx`**

```tsx
import React, { useState } from "react";
import {
  addDays,
  formatDayLabel,
  monthOf,
} from "../Dashboard/weekUtils";
import { CalendarPopover } from "./CalendarPopover";
import "./DayPicker.css";

interface Props {
  selectedDate: string;
  maxDate: string;
  hasMessagesOnDay: (dayKey: string) => boolean;
  /** True while month-week prefetch is in flight; passed to the popover. */
  prefetching?: boolean;
  onChange: (dayKey: string) => void;
  /** Fires whenever the popover opens or closes (with the visible-month
   *  it is opening on), so the parent can drive prefetch. */
  onCalendarOpenChange: (open: boolean, visibleMonth: string) => void;
  /** Fires when the user pages the popover to a new month — parent uses
   *  this to prefetch that month. */
  onVisibleMonthChange: (monthKey: string) => void;
}

export function DayPicker({
  selectedDate,
  maxDate,
  hasMessagesOnDay,
  prefetching,
  onChange,
  onCalendarOpenChange,
  onVisibleMonthChange,
}: Props) {
  const [open, setOpen] = useState(false);
  const [visibleMonth, setVisibleMonth] = useState<string>(monthOf(selectedDate));

  const isAtMax = selectedDate >= maxDate;

  function toggleOpen(next?: boolean) {
    const willOpen = next ?? !open;
    if (willOpen) {
      // Re-anchor the calendar to the currently selected day's month each
      // time we re-open — feels more natural than keeping last-seen month.
      const month = monthOf(selectedDate);
      setVisibleMonth(month);
      onCalendarOpenChange(true, month);
    } else {
      onCalendarOpenChange(false, visibleMonth);
    }
    setOpen(willOpen);
  }

  function handleMonthChange(next: string) {
    setVisibleMonth(next);
    onVisibleMonthChange(next);
  }

  function handlePickDay(dayKey: string) {
    onChange(dayKey);
    toggleOpen(false);
  }

  return (
    <div className="day-picker">
      <button
        type="button"
        className="day-picker-arrow"
        aria-label="上一天"
        onClick={() => onChange(addDays(selectedDate, -1))}
      >
        ‹
      </button>
      <button
        type="button"
        className="day-picker-center"
        onClick={() => toggleOpen()}
      >
        {formatDayLabel(selectedDate)}
      </button>
      <button
        type="button"
        className="day-picker-arrow"
        aria-label="下一天"
        disabled={isAtMax}
        onClick={() => onChange(addDays(selectedDate, 1))}
      >
        ›
      </button>
      {open && (
        <CalendarPopover
          visibleMonth={visibleMonth}
          selectedDate={selectedDate}
          maxDate={maxDate}
          hasMessagesOnDay={hasMessagesOnDay}
          loading={prefetching}
          onMonthChange={handleMonthChange}
          onPickDay={handlePickDay}
          onClose={() => toggleOpen(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4.2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 4.3: Commit**

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/components/Chat/DayPicker.tsx
git commit -m "feat(chat): add DayPicker (arrows + calendar trigger)"
```

---

## Task 5: Wire `DayPicker` into `ChatBoardPanel` with day filtering and prefetch

**Files:**
- Modify: `frontend/src/components/Chat/ChatBoardPanel.tsx`
- Modify: `frontend/src/components/Chat/ChatBoardPanel.css`

- [ ] **Step 5.1: Ensure `.chat-panel` is `position: relative`**

Open `frontend/src/components/Chat/ChatBoardPanel.css` and find the `.chat-panel` rule (around line 330). Edit it to ensure `position: relative` is set so the absolute-positioned `.day-picker` anchors to the panel:

Locate:

```css
.chat-panel { display: flex; flex-direction: column; flex: 1; min-height: 0; }
```

Replace with:

```css
.chat-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}
```

(If `position` is already declared on `.chat-panel`, just confirm it's `relative` and skip the edit.)

- [ ] **Step 5.2: Refactor `ChatBoardPanel.tsx`**

Open `frontend/src/components/Chat/ChatBoardPanel.tsx` and apply the following edits.

**Edit A — update imports** (replace the top import block with this set, adding `useChatStore` shape unchanged):

```tsx
import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { WhopPage } from "../../api/domain-types";
import { api } from "../../api/http";
import { useChatStore } from "../../stores/chatStore";
import { useChildPagesStore } from "../../stores/childPages";
import { useTasksStore } from "../../stores/tasks";
import { useConnStore } from "../../stores/conn";
import {
  dayKeyOf,
  isoWeekBounds,
  isoWeekOfDay,
  monthOf,
  todayInShanghai,
  weeksCoveringMonth,
} from "../Dashboard/weekUtils";
import { groupIntoCards } from "./chatCards";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { buildTimeline, buildFilterBlocks, buildStreamGroups } from "./chatTimeline";
import { StockCard } from "./StockCard";
import { OptionCard } from "./OptionCard";
import { StreamView } from "./StreamView";
import { DayPicker } from "./DayPicker";
import "./ChatBoardPanel.css";
```

**Edit B — drop `week` from `Props`** (lines around 25–28):

Locate:

```tsx
interface Props {
  page: WhopPage;
  week: string;                  // e.g., "2026-W21"
}
```

Replace with:

```tsx
interface Props {
  page: WhopPage;
}
```

**Edit C — change signature and add `selectedDate` state**:

Locate:

```tsx
export function ChatBoardPanel({ page, week }: Props) {
  const cache = useChatStore((s) => s.caches[`${page.id}|${week}`]);
  const fetch = useChatStore((s) => s.fetch);
```

Replace with:

```tsx
export function ChatBoardPanel({ page }: Props) {
  // Currently-selected calendar day, drives both the visible-message
  // filter and the ISO-week that gets fetched into chatStore.
  const [selectedDate, setSelectedDate] = useState<string>(todayInShanghai());
  // Reset to today whenever the active page changes.
  useEffect(() => { setSelectedDate(todayInShanghai()); }, [page.id]);

  const selectedWeek = isoWeekOfDay(selectedDate);
  const today = todayInShanghai();

  const cache = useChatStore((s) => s.caches[`${page.id}|${selectedWeek}`]);
  const fetch = useChatStore((s) => s.fetch);
  const allCaches = useChatStore((s) => s.caches);
```

**Edit D — change the week-fetch effect**:

Locate:

```tsx
  useEffect(() => {
    // Fetch full week's messages once per (page, week). Senders filter is
    // applied client-side via groupIntoCards — no need to re-fetch on toggle.
    fetch(page.id, week, []);
  }, [page.id, week, fetch]);
```

Replace with:

```tsx
  useEffect(() => {
    // Fetch full week's messages once per (page, selectedWeek). Senders
    // and day filters are applied client-side — no need to re-fetch on
    // toggles within the same week.
    fetch(page.id, selectedWeek, []);
  }, [page.id, selectedWeek, fetch]);
```

**Edit E — change the children-tasks fetch effect to use `selectedWeek`**:

Locate:

```tsx
  // Fetch children + their tasks on mount / page / week change.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await api.listWhopPages({ parentChatId: page.id });
        if (!alive) return;
        useChildPagesStore.getState().setByParent(page.id, r.pages);

        const urls = r.pages.map((p) => p.url);
        if (urls.length === 0) return;
        const { start, end } = isoWeekBounds(week);
        const tr = await api.listTasks({
          urls,
          week_start: start,
          week_end: end,
          limit: 500,
        });
        if (!alive) return;
        for (const t of tr.tasks) useTasksStore.getState().upsertTask(t);
      } catch (e) {
        console.warn("chat children fetch failed:", e);
      }
    })();
    return () => { alive = false; };
  }, [page.id, week]);
```

Replace with:

```tsx
  // Fetch children + their tasks on mount / page / selectedWeek change.
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const r = await api.listWhopPages({ parentChatId: page.id });
        if (!alive) return;
        useChildPagesStore.getState().setByParent(page.id, r.pages);

        const urls = r.pages.map((p) => p.url);
        if (urls.length === 0) return;
        const { start, end } = isoWeekBounds(selectedWeek);
        const tr = await api.listTasks({
          urls,
          week_start: start,
          week_end: end,
          limit: 500,
        });
        if (!alive) return;
        for (const t of tr.tasks) useTasksStore.getState().upsertTask(t);
      } catch (e) {
        console.warn("chat children fetch failed:", e);
      }
    })();
    return () => { alive = false; };
  }, [page.id, selectedWeek]);
```

**Edit F — day-filter the messages and childTasks before building the timeline**:

Locate:

```tsx
  const childTasks = useMemo(
    () =>
      allTasks.filter(
        (t) => t.message.url != null && childUrls.includes(t.message.url),
      ),
    [allTasks, childUrls],
  );
```

Leave that block as-is — it remains the full pool for the active week.

Locate (later in the file):

```tsx
  // ── Data ─────────────────────────────────────────────────────────────
  const messages = cache?.messages ?? [];
  const authors = cache?.authors ?? [];
```

Replace with:

```tsx
  // ── Data ─────────────────────────────────────────────────────────────
  const rawMessages = cache?.messages ?? [];
  const authors = cache?.authors ?? [];

  // Day-filter both messages and child-task signals to selectedDate so
  // every downstream consumer (groupIntoCards, buildTimeline, ...)
  // sees only that day's content.
  const messages = useMemo(
    () => rawMessages.filter((m) => dayKeyOf(m.posted_at) === selectedDate),
    [rawMessages, selectedDate],
  );
  const dayFilteredChildTasks = useMemo(
    () =>
      childTasks.filter(
        (t) => dayKeyOf(t.message.posted_at) === selectedDate,
      ),
    [childTasks, selectedDate],
  );
```

Then locate the timeline build:

```tsx
  // Merged chronological timeline of chat messages + child tasks.
  const timeline = useMemo(
    () => buildTimeline(messages, childTasks, urlToMonitorName),
    [messages, childTasks, urlToMonitorName],
  );
```

Replace with:

```tsx
  // Merged chronological timeline of chat messages + child tasks
  // (already filtered to selectedDate above).
  const timeline = useMemo(
    () => buildTimeline(messages, dayFilteredChildTasks, urlToMonitorName),
    [messages, dayFilteredChildTasks, urlToMonitorName],
  );
```

**Edit G — empty-state copy**:

Locate:

```tsx
  if (timeline.length === 0) {
    body = (
      <div className="chat-empty">本周无消息 · 切换周或调整发送者过滤</div>
    );
  } else if (mode === "filter" && watchedSenders.length > 0) {
```

Replace with:

```tsx
  if (timeline.length === 0) {
    body = (
      <div className="chat-empty">这一天还没有消息</div>
    );
  } else if (mode === "filter" && watchedSenders.length > 0) {
```

**Edit H — add prefetch state + handlers and mount `<DayPicker />`**:

Just before the `return (` block of the component, add:

```tsx
  // ── Calendar prefetch (covers the visible month so dots are reliable) ─
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [calendarMonth, setCalendarMonth] = useState<string>(monthOf(selectedDate));

  useEffect(() => {
    if (!calendarOpen) return;
    for (const w of weeksCoveringMonth(calendarMonth)) {
      const key = `${page.id}|${w}`;
      if (!allCaches[key]) fetch(page.id, w, []);
    }
  }, [calendarOpen, calendarMonth, page.id, fetch, allCaches]);

  // Whether any of the visible month's weeks is still missing from the cache.
  const prefetching = useMemo(() => {
    if (!calendarOpen) return false;
    return weeksCoveringMonth(calendarMonth).some(
      (w) => !allCaches[`${page.id}|${w}`],
    );
  }, [calendarOpen, calendarMonth, page.id, allCaches]);

  const hasMessagesOnDay = useCallback(
    (dayKey: string) => {
      const week = isoWeekOfDay(dayKey);
      const c = allCaches[`${page.id}|${week}`];
      if (!c) return false;
      return c.messages.some((m) => dayKeyOf(m.posted_at) === dayKey);
    },
    [allCaches, page.id],
  );
```

Then locate the existing return:

```tsx
  return (
    <div className="chat-panel">
      <ChatSenderBar
        pageId={page.id}
        authors={authorsWithMonitors}
        watchedSenders={watchedSenders}
        onChange={handleSenderChange}
        mode={mode}
        onModeChange={handleModeChange}
        monitorSources={monitorSources}
      />
      <div className="chat-board" ref={boardRef} onScroll={handleBoardScroll}>
        {body}
      </div>
    </div>
  );
}
```

Replace with:

```tsx
  return (
    <div className="chat-panel">
      <ChatSenderBar
        pageId={page.id}
        authors={authorsWithMonitors}
        watchedSenders={watchedSenders}
        onChange={handleSenderChange}
        mode={mode}
        onModeChange={handleModeChange}
        monitorSources={monitorSources}
      />
      <div className="chat-board" ref={boardRef} onScroll={handleBoardScroll}>
        {body}
      </div>
      <DayPicker
        selectedDate={selectedDate}
        maxDate={today}
        hasMessagesOnDay={hasMessagesOnDay}
        prefetching={prefetching}
        onChange={setSelectedDate}
        onCalendarOpenChange={(open, month) => {
          setCalendarOpen(open);
          if (open) setCalendarMonth(month);
        }}
        onVisibleMonthChange={setCalendarMonth}
      />
    </div>
  );
}
```

- [ ] **Step 5.3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 5.4: Run any existing chat-related tests**

```bash
cd frontend && npx vitest run src/components/Chat
```

Expected: no regressions (existing tests should still pass; we did not change chatCards / chatTimeline logic).

- [ ] **Step 5.5: Commit**

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/components/Chat/ChatBoardPanel.tsx frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "feat(chat): filter discussion by day, mount DayPicker, prefetch month"
```

---

## Task 6: Remove `week` prop from `App.tsx` call site

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 6.1: Remove `currentIsoWeek` usage at the ChatBoardPanel call site and drop the TODO**

Locate lines around 365–371:

```tsx
      {/* Chat-source pages render ChatBoardPanel (owns its own scroll
          container) instead of the TaskStream message list. Week-
          navigation for chat pages is not yet implemented — we always
          pass the current ISO week. TODO(future): wire WeekPaginator to
          ChatBoardPanel using the ISO-week format. */}
      {activePage && activePage.source === "chat" ? (
        <ChatBoardPanel page={activePage} week={currentIsoWeek()} />
      ) : (
```

Replace with:

```tsx
      {/* Chat-source pages render ChatBoardPanel (owns its own scroll
          container) instead of the TaskStream message list. The panel
          owns its own day-based date picker (see DayPicker.tsx); the
          parent doesn't need to pass a week. */}
      {activePage && activePage.source === "chat" ? (
        <ChatBoardPanel page={activePage} />
      ) : (
```

- [ ] **Step 6.2: Check if `currentIsoWeek` is still used elsewhere in `App.tsx`**

```bash
grep -n "currentIsoWeek" /Users/tianpengxuan/Documents/signal-station/frontend/src/App.tsx
```

If only line 25 (the import line) remains, remove it from the import.

Locate:

```tsx
import { computeWeeks, weekKeyOf, currentIsoWeek } from "./components/Dashboard/weekUtils";
```

If `currentIsoWeek` is unused elsewhere, change to:

```tsx
import { computeWeeks, weekKeyOf } from "./components/Dashboard/weekUtils";
```

(If it IS still used elsewhere — there's a `const week = currentIsoWeek();` around line 345 — leave the import.)

- [ ] **Step 6.3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: clean.

- [ ] **Step 6.4: Commit**

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/App.tsx
git commit -m "refactor(app): drop week prop on ChatBoardPanel (now self-owned)"
```

---

## Task 7: Manual verification

**No code changes — just exercise the feature in the running app.**

- [ ] **Step 7.1: Start the frontend dev server**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend && npm run dev
```

Open the URL printed by Vite. Sign in / select a chat page so `ChatBoardPanel` renders.

- [ ] **Step 7.2: Run the 12-step manual checklist from the spec**

For each: confirm visually, then check it off.

1. Open the discussion panel → DayPicker visible bottom-right; center button reads `今天`; right arrow disabled; today's messages (if any) shown.
2. Click `‹` once → button becomes `昨天`; messages switch to yesterday's; right arrow now enabled.
3. Click `‹` enough times to cross last Sunday → label flips to `M月D日 周X`; brief loading skeleton appears; previous-week messages render.
4. Click `›` enough times to return to today → label `今天`, right arrow disabled again.
5. Click center button → calendar pops up anchored above-left of the button; today has a 1px highlight border; the day(s) with messages in the currently-loaded week have small dots.
6. Wait ~1 second → dots appear on the rest of the month's days that have messages.
7. Click any day in the popover → popover closes; messages update.
8. Page the calendar to next month (`›` in the popover header) → future days are dimmed/disabled; past days remain clickable.
9. With a day selected, toggle a sender in the top `ChatSenderBar` → result is the AND of "that day" and "that sender". Verify with a sender you know posted only on a different day → empty state appears.
10. Click anywhere outside the popover → popover closes; selected date unchanged.
11. Resize the panel narrower → calendar still fits inside the panel, not clipped.
12. Switch to another page, then back to this chat page → `selectedDate` resets to today.

- [ ] **Step 7.3: Run the full test suite once to confirm no collateral damage**

```bash
cd frontend && npm test
```

Expected: every test passes.

- [ ] **Step 7.4: Stop the dev server and report success**

Mention any deviations from the manual checklist. If any item fails, file follow-up tasks rather than silently fixing — the implementer should surface the regression so the user can decide.

---

## Self-Review

**Spec coverage:**

- ✅ Floating bottom-right control with `‹ [日期] ›` (Task 4 + CSS in Task 3)
- ✅ Calendar popover with month grid, anchored above-left (Task 3)
- ✅ "Today" / "昨天" / "M月D日 周X" / cross-year labeling (Task 2 `formatDayLabel`)
- ✅ Future days disabled, right arrow disabled at today (Task 3 + Task 4)
- ✅ "Has messages" dot via prefetched month coverage (Task 5)
- ✅ Day-filter applied to both messages and child-task signals (Task 5)
- ✅ ISO week derived from selectedDate, drives existing fetch (Task 5)
- ✅ Empty state copy "这一天还没有消息" (Task 5)
- ✅ App.tsx call-site cleaned (Task 6)
- ✅ Manual test checklist (Task 7)
- ✅ Time zone: all helpers use Asia/Shanghai consistent with existing code (Tasks 1 + 2)

**Placeholder scan:** None — all steps contain executable code or commands.

**Type / name consistency:**

- `dayKeyOf`, `todayInShanghai`, `addDays`, `monthOf`, `daysInMonth`, `isoWeekOfDay`, `weeksCoveringMonth`, `formatDayLabel` — referenced consistently in Tasks 1–5.
- Cache key format `${pageId}|${week}` — matches `chatStore.cacheKey` (verified against `chatStore.ts`).
- `DayPicker` prop names (`selectedDate`, `maxDate`, `hasMessagesOnDay`, `prefetching`, `onChange`, `onCalendarOpenChange`, `onVisibleMonthChange`) — match between Task 4 (definition) and Task 5 (usage).
- `CalendarPopover` prop names — match between Task 3 (definition) and Task 4 (usage).
- ChatBoardPanel `Props` interface — `week` removed in Edit B; App.tsx no longer passes it (Task 6).
