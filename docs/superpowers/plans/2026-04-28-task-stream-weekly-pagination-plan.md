# TaskStream Weekly Pagination — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add weekly pagination (Sun→Sat, local time) to the dashboard's `TaskStream` via a new standalone `WeekPaginator` chip-strip selector pinned in a sticky row, with a "本周新消息 N 条 →" badge for arrivals while viewing past weeks.

**Architecture:** Pure render-side change. A new `WeekPaginator` component (controlled, knows nothing about tasks) handles week selection. `TaskStream` computes a `{ groups, weeks }` structure from the existing in-memory task list, holds the selected `currentWeekKey`, and renders only that week's tasks (still grouped per-day inside the week). Empty weeks are skipped from the page list. New-messages badge is a sibling of `WeekPaginator` in a sticky `.week-bar` row.

**Tech Stack:** TypeScript + React 18, Vitest + @testing-library/react, plain CSS with existing design tokens.

**Spec:** `docs/superpowers/specs/2026-04-28-task-stream-weekly-pagination-design.md`

---

## File Structure

| File | Responsibility | Change kind |
|------|----------------|-------------|
| `frontend/src/components/Dashboard/weekUtils.ts` | Pure helpers: `weekKeyOf`, `formatWeekRange`, `computeWeeks` | **Create** |
| `frontend/src/components/Dashboard/weekUtils.test.ts` | Unit tests for the helpers | **Create** |
| `frontend/src/components/Dashboard/WeekPaginator.tsx` | Controlled chip-strip selector for picking a week | **Create** |
| `frontend/src/components/Dashboard/WeekPaginator.test.tsx` | Component tests | **Create** |
| `frontend/src/components/Dashboard/TaskStream.tsx` | Compute weeks, hold `currentWeekKey`, render sticky bar + selected week | Modify |
| `frontend/src/components/Dashboard/TaskStream.test.tsx` | New tests for week pagination behavior | **Create** |
| `frontend/src/components/Dashboard/Dashboard.css` | `.week-bar` + `.week-paginator-*` + `.week-bar-new-badge` styles | Modify |

`weekUtils.ts` is split out of the component so the timezone-sensitive
date math can be tested with the system clock mocked, without standing
up a React renderer.

---

## Conventions Used Throughout

- Run a single test file: `cd frontend && npx vitest run <path>`
- Run all frontend tests: `cd frontend && npm test`
- Run typecheck: `cd frontend && npm run typecheck`
- All commits include the trailing line:
  `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

Each task ends with a commit. Use the `git add` lines as written so
the `frontend/` working tree changes (`Card.css`, `OrderSubmit.tsx`)
already in flight don't leak in.

---

## Task 1: `weekKeyOf` helper

**Files:**
- Create: `frontend/src/components/Dashboard/weekUtils.ts`
- Create: `frontend/src/components/Dashboard/weekUtils.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Dashboard/weekUtils.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { weekKeyOf } from "./weekUtils";

describe("weekKeyOf", () => {
  it("returns the local-calendar Sunday's YYYY-MM-DD for a Wednesday", () => {
    // 2026-04-22 is a Wednesday in local time. The Sunday of its week
    // is 2026-04-19.
    const ts = new Date(2026, 3, 22, 14, 0, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });

  it("returns the same day's date when the timestamp is itself a Sunday", () => {
    const ts = new Date(2026, 3, 19, 9, 0, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });

  it("returns the previous Sunday for a Saturday late-night", () => {
    // 2026-04-25 (Saturday) 23:55 local → Sunday 2026-04-19.
    const ts = new Date(2026, 3, 25, 23, 55, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });

  it("does not get tricked by UTC-offset timezones", () => {
    // A timestamp at local Sunday 00:30 must still yield that Sunday's
    // local date even when the UTC date has rolled back to Saturday.
    const ts = new Date(2026, 3, 19, 0, 30, 0).toISOString();
    expect(weekKeyOf(ts)).toBe("2026-04-19");
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: FAIL — module `./weekUtils` not found.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/components/Dashboard/weekUtils.ts`:

```ts
export function weekKeyOf(ts: string): string {
  const d = new Date(ts);
  const sunday = new Date(d);
  sunday.setHours(0, 0, 0, 0);
  sunday.setDate(d.getDate() - d.getDay());
  const yyyy = sunday.getFullYear();
  const mm = String(sunday.getMonth() + 1).padStart(2, "0");
  const dd = String(sunday.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/weekUtils.ts frontend/src/components/Dashboard/weekUtils.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend): weekKeyOf — local-time Sunday key for a timestamp

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `formatWeekRange` helper

**Files:**
- Modify: `frontend/src/components/Dashboard/weekUtils.ts`
- Modify: `frontend/src/components/Dashboard/weekUtils.test.ts`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/Dashboard/weekUtils.test.ts`:

```ts
import { formatWeekRange } from "./weekUtils";

describe("formatWeekRange", () => {
  it("returns MM/DD ~ MM/DD for the week starting on the given Sunday", () => {
    expect(formatWeekRange("2026-04-19")).toEqual({
      startLabel: "04/19",
      endLabel: "04/25",
    });
  });

  it("handles month rollover", () => {
    // 2026-04-26 (Sunday) → ends 2026-05-02 (Saturday).
    expect(formatWeekRange("2026-04-26")).toEqual({
      startLabel: "04/26",
      endLabel: "05/02",
    });
  });

  it("handles year rollover", () => {
    // 2025-12-28 (Sunday) → ends 2026-01-03 (Saturday).
    expect(formatWeekRange("2025-12-28")).toEqual({
      startLabel: "12/28",
      endLabel: "01/03",
    });
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: FAIL — `formatWeekRange` not exported.

- [ ] **Step 3: Implement the helper**

Append to `frontend/src/components/Dashboard/weekUtils.ts`:

```ts
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: PASS, 7 tests total.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/weekUtils.ts frontend/src/components/Dashboard/weekUtils.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend): formatWeekRange — MM/DD labels for a week key

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `computeWeeks` helper

**Files:**
- Modify: `frontend/src/components/Dashboard/weekUtils.ts`
- Modify: `frontend/src/components/Dashboard/weekUtils.test.ts`

- [ ] **Step 1: Add the failing tests**

Append to `frontend/src/components/Dashboard/weekUtils.test.ts`:

```ts
import { computeWeeks } from "./weekUtils";
import type { TaskSummary } from "../../api/domain-types";

const mkTask = (id: string, postedAt: string): TaskSummary =>
  ({
    id,
    status: "FILLED",
    created_at: postedAt,
    updated_at: postedAt,
    message: { url: "https://w/x", author: "a", content: "c", posted_at: postedAt, received_at: postedAt },
  } as unknown as TaskSummary);

describe("computeWeeks", () => {
  it("returns empty groups and weeks for an empty input", () => {
    const r = computeWeeks([]);
    expect(r.weeks).toEqual([]);
    expect(r.groups.size).toBe(0);
  });

  it("groups tasks by their local-week Sunday key", () => {
    const t1 = mkTask("t1", new Date(2026, 3, 22, 10).toISOString()); // wk 04-19
    const t2 = mkTask("t2", new Date(2026, 3, 25, 10).toISOString()); // wk 04-19
    const t3 = mkTask("t3", new Date(2026, 3, 27, 10).toISOString()); // wk 04-26
    const r = computeWeeks([t3, t1, t2]); // arbitrary input order
    expect(r.weeks.map((w) => w.key)).toEqual(["2026-04-26", "2026-04-19"]);
    expect(r.groups.get("2026-04-26")?.map((t) => t.id)).toEqual(["t3"]);
    expect(r.groups.get("2026-04-19")?.map((t) => t.id).sort()).toEqual(["t1", "t2"]);
  });

  it("returns weeks descending and sorts each group's tasks descending by time", () => {
    const a = mkTask("a", new Date(2026, 3, 19, 9).toISOString());
    const b = mkTask("b", new Date(2026, 3, 19, 18).toISOString());
    const r = computeWeeks([a, b]);
    expect(r.groups.get("2026-04-19")?.map((t) => t.id)).toEqual(["b", "a"]);
  });

  it("populates startLabel/endLabel from the week key", () => {
    const t = mkTask("t", new Date(2026, 3, 22, 10).toISOString());
    const r = computeWeeks([t]);
    expect(r.weeks[0]).toMatchObject({
      key: "2026-04-19",
      startLabel: "04/19",
      endLabel: "04/25",
    });
  });

  it("falls back to created_at when message.posted_at is null", () => {
    const t = {
      id: "t",
      status: "FILLED",
      created_at: new Date(2026, 3, 22, 10).toISOString(),
      updated_at: new Date(2026, 3, 22, 10).toISOString(),
      message: { url: null, author: null, content: "", posted_at: null, received_at: null },
    } as unknown as TaskSummary;
    const r = computeWeeks([t]);
    expect(r.weeks[0]?.key).toBe("2026-04-19");
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: FAIL — `computeWeeks` not exported.

- [ ] **Step 3: Implement the helper**

Append to `frontend/src/components/Dashboard/weekUtils.ts`:

```ts
import type { TaskSummary } from "../../api/domain-types";

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/Dashboard/weekUtils.test.ts`
Expected: PASS, 12 tests total.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/weekUtils.ts frontend/src/components/Dashboard/weekUtils.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend): computeWeeks — group tasks by Sunday week, descending

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `WeekPaginator` collapsed-state rendering

**Files:**
- Create: `frontend/src/components/Dashboard/WeekPaginator.tsx`
- Create: `frontend/src/components/Dashboard/WeekPaginator.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Dashboard/WeekPaginator.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WeekPaginator } from "./WeekPaginator";
import type { WeekInfo } from "./weekUtils";

const W = (key: string, startLabel: string, endLabel: string): WeekInfo => ({ key, startLabel, endLabel });

describe("<WeekPaginator>", () => {
  it("renders a single chip showing the current week's range when collapsed", () => {
    const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
    render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ })).toBeInTheDocument();
    // The other week should not be visible while collapsed.
    expect(screen.queryByText("04/12 ~ 04/18")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: FAIL — module `./WeekPaginator` not found.

- [ ] **Step 3: Create the minimal component**

Create `frontend/src/components/Dashboard/WeekPaginator.tsx`:

```tsx
import { useState } from "react";
import type { WeekInfo } from "./weekUtils";

export interface WeekPaginatorProps {
  weeks: WeekInfo[];
  currentWeekKey: string;
  onSelect: (key: string) => void;
}

export function WeekPaginator({ weeks, currentWeekKey, onSelect }: WeekPaginatorProps) {
  const [expanded, setExpanded] = useState(false);
  const current = weeks.find((w) => w.key === currentWeekKey);
  if (!current) return null;
  const canExpand = weeks.length > 1;

  if (!expanded) {
    return (
      <button
        type="button"
        className="week-paginator-chip current collapsed"
        onClick={() => canExpand && setExpanded(true)}
        disabled={!canExpand}
      >
        {current.startLabel} ~ {current.endLabel}
        {canExpand && <span className="week-paginator-caret">▸</span>}
      </button>
    );
  }

  return (
    <div className="week-paginator-strip" role="listbox">
      {weeks.map((w) => {
        const isCurrent = w.key === currentWeekKey;
        return (
          <button
            type="button"
            key={w.key}
            role="option"
            aria-selected={isCurrent}
            className={`week-paginator-chip${isCurrent ? " current" : ""}`}
            onClick={() => {
              onSelect(w.key);
              setExpanded(false);
            }}
          >
            {w.startLabel} ~ {w.endLabel}
            {isCurrent && <span className="week-paginator-caret">▾</span>}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: PASS, 1 test.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/WeekPaginator.tsx frontend/src/components/Dashboard/WeekPaginator.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): WeekPaginator — collapsed chip rendering

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `WeekPaginator` expand on click

**Files:**
- Modify: `frontend/src/components/Dashboard/WeekPaginator.test.tsx`

- [ ] **Step 1: Add the failing test**

Append to `frontend/src/components/Dashboard/WeekPaginator.test.tsx`:

```tsx
it("expands on click to reveal all weeks, with the current one selected", () => {
  const weeks = [
    W("2026-04-19", "04/19", "04/25"),
    W("2026-04-12", "04/12", "04/18"),
    W("2026-04-05", "04/05", "04/11"),
  ];
  render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-12" onSelect={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
  const options = screen.getAllByRole("option");
  expect(options.map((o) => o.textContent)).toEqual([
    expect.stringContaining("04/19 ~ 04/25"),
    expect.stringContaining("04/12 ~ 04/18"),
    expect.stringContaining("04/05 ~ 04/11"),
  ]);
  expect(screen.getByRole("option", { selected: true }).textContent).toContain("04/12 ~ 04/18");
});
```

- [ ] **Step 2: Run test to verify it passes (already implemented in Task 4)**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: PASS, 2 tests.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dashboard/WeekPaginator.test.tsx
git commit -m "$(cat <<'EOF'
test(frontend): WeekPaginator expansion behavior

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `WeekPaginator` selecting a chip fires `onSelect` and collapses

**Files:**
- Modify: `frontend/src/components/Dashboard/WeekPaginator.test.tsx`

- [ ] **Step 1: Add the failing test**

Append to the test file:

```tsx
it("calls onSelect with the clicked week's key and collapses", () => {
  const onSelect = vi.fn();
  const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
  render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={onSelect} />);
  fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
  fireEvent.click(screen.getByRole("option", { name: /04\/12 ~ 04\/18/ }));
  expect(onSelect).toHaveBeenCalledWith("2026-04-12");
  // Strip should be gone (collapsed back to a single chip).
  expect(screen.queryByRole("listbox")).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: PASS, 3 tests. (Behavior was already implemented in Task 4; this just locks it in.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dashboard/WeekPaginator.test.tsx
git commit -m "$(cat <<'EOF'
test(frontend): WeekPaginator click-to-select + collapse

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `WeekPaginator` single-week guard

**Files:**
- Modify: `frontend/src/components/Dashboard/WeekPaginator.test.tsx`

- [ ] **Step 1: Add the failing test**

Append:

```tsx
it("renders a non-interactive single chip with no caret when only one week is available", () => {
  const weeks = [W("2026-04-19", "04/19", "04/25")];
  render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />);
  const chip = screen.getByRole("button", { name: /04\/19 ~ 04\/25/ });
  expect(chip).toBeDisabled();
  expect(chip.querySelector(".week-paginator-caret")).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: PASS, 4 tests. (Already implemented via the `canExpand` check.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dashboard/WeekPaginator.test.tsx
git commit -m "$(cat <<'EOF'
test(frontend): WeekPaginator single-week is non-interactive

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `WeekPaginator` outside-click collapses

**Files:**
- Modify: `frontend/src/components/Dashboard/WeekPaginator.tsx`
- Modify: `frontend/src/components/Dashboard/WeekPaginator.test.tsx`

- [ ] **Step 1: Add the failing test**

Append:

```tsx
it("collapses when the user clicks outside the strip", () => {
  const weeks = [W("2026-04-19", "04/19", "04/25"), W("2026-04-12", "04/12", "04/18")];
  render(
    <div>
      <WeekPaginator weeks={weeks} currentWeekKey="2026-04-19" onSelect={vi.fn()} />
      <div data-testid="outside">elsewhere</div>
    </div>,
  );
  fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
  expect(screen.getByRole("listbox")).toBeInTheDocument();
  fireEvent.mouseDown(screen.getByTestId("outside"));
  expect(screen.queryByRole("listbox")).toBeNull();
});
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: FAIL — strip remains visible after outside `mouseDown`.

- [ ] **Step 3: Implement outside-click**

Replace the contents of `WeekPaginator.tsx` with:

```tsx
import { useEffect, useRef, useState } from "react";
import type { WeekInfo } from "./weekUtils";

export interface WeekPaginatorProps {
  weeks: WeekInfo[];
  currentWeekKey: string;
  onSelect: (key: string) => void;
}

export function WeekPaginator({ weeks, currentWeekKey, onSelect }: WeekPaginatorProps) {
  const [expanded, setExpanded] = useState(false);
  const stripRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!expanded) return;
    function onDocMouseDown(e: MouseEvent) {
      if (stripRef.current && !stripRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [expanded]);

  const current = weeks.find((w) => w.key === currentWeekKey);
  if (!current) return null;
  const canExpand = weeks.length > 1;

  if (!expanded) {
    return (
      <button
        type="button"
        className="week-paginator-chip current collapsed"
        onClick={() => canExpand && setExpanded(true)}
        disabled={!canExpand}
      >
        {current.startLabel} ~ {current.endLabel}
        {canExpand && <span className="week-paginator-caret">▸</span>}
      </button>
    );
  }

  return (
    <div className="week-paginator-strip" role="listbox" ref={stripRef}>
      {weeks.map((w) => {
        const isCurrent = w.key === currentWeekKey;
        return (
          <button
            type="button"
            key={w.key}
            role="option"
            aria-selected={isCurrent}
            className={`week-paginator-chip${isCurrent ? " current" : ""}`}
            onClick={() => {
              onSelect(w.key);
              setExpanded(false);
            }}
          >
            {w.startLabel} ~ {w.endLabel}
            {isCurrent && <span className="week-paginator-caret">▾</span>}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/WeekPaginator.tsx frontend/src/components/Dashboard/WeekPaginator.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): WeekPaginator collapses on outside click

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `WeekPaginator` scroll-positioning on expand

**Files:**
- Modify: `frontend/src/components/Dashboard/WeekPaginator.tsx`
- Modify: `frontend/src/components/Dashboard/WeekPaginator.test.tsx`

- [ ] **Step 1: Add the failing tests**

Append:

```tsx
it("scrolls the strip so the current chip is centered when current is mid-list", () => {
  const weeks = [
    W("2026-04-26", "04/26", "05/02"),
    W("2026-04-19", "04/19", "04/25"),
    W("2026-04-12", "04/12", "04/18"),
    W("2026-04-05", "04/05", "04/11"),
    W("2026-03-29", "03/29", "04/04"),
  ];
  render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-12" onSelect={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
  const strip = screen.getByRole("listbox") as HTMLElement;
  // Current is index 2 of 5. The component should set scrollLeft so that
  // index 2 is in the middle of the visible 3-chip viewport — i.e., the
  // strip's data-scroll-mode attribute should be "center".
  expect(strip.dataset.scrollMode).toBe("center");
});

it("left-aligns when current is the newest week (index 0)", () => {
  const weeks = [
    W("2026-04-26", "04/26", "05/02"),
    W("2026-04-19", "04/19", "04/25"),
    W("2026-04-12", "04/12", "04/18"),
  ];
  render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-26" onSelect={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /04\/26 ~ 05\/02/ }));
  expect((screen.getByRole("listbox") as HTMLElement).dataset.scrollMode).toBe("start");
});

it("right-aligns when current is the oldest week (last index)", () => {
  const weeks = [
    W("2026-04-26", "04/26", "05/02"),
    W("2026-04-19", "04/19", "04/25"),
    W("2026-04-12", "04/12", "04/18"),
  ];
  render(<WeekPaginator weeks={weeks} currentWeekKey="2026-04-12" onSelect={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /04\/12 ~ 04\/18/ }));
  expect((screen.getByRole("listbox") as HTMLElement).dataset.scrollMode).toBe("end");
});
```

These tests verify the *intent* (which alignment mode was chosen)
without depending on jsdom layout, which doesn't compute `scrollLeft`
from CSS. The actual `scrollLeft` write is exercised manually in the
final smoke task.

- [ ] **Step 2: Run tests to verify failure**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: FAIL — `data-scroll-mode` not present.

- [ ] **Step 3: Implement scroll-mode selection + scrollLeft write**

Replace the entire contents of `frontend/src/components/Dashboard/WeekPaginator.tsx` with:

```tsx
import { useEffect, useRef, useState } from "react";
import type { WeekInfo } from "./weekUtils";

export interface WeekPaginatorProps {
  weeks: WeekInfo[];
  currentWeekKey: string;
  onSelect: (key: string) => void;
}

export function WeekPaginator({ weeks, currentWeekKey, onSelect }: WeekPaginatorProps) {
  const [expanded, setExpanded] = useState(false);
  const stripRef = useRef<HTMLDivElement | null>(null);

  const current = weeks.find((w) => w.key === currentWeekKey);
  const currentIndex = weeks.findIndex((w) => w.key === currentWeekKey);
  const canExpand = weeks.length > 1;
  const scrollMode: "start" | "center" | "end" =
    currentIndex <= 0
      ? "start"
      : currentIndex >= weeks.length - 1
        ? "end"
        : "center";

  useEffect(() => {
    if (!expanded) return;
    function onDocMouseDown(e: MouseEvent) {
      if (stripRef.current && !stripRef.current.contains(e.target as Node)) {
        setExpanded(false);
      }
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [expanded]);

  useEffect(() => {
    if (!expanded) return;
    const el = stripRef.current;
    if (!el) return;
    const chip = el.children[currentIndex] as HTMLElement | undefined;
    if (!chip) return;
    if (scrollMode === "start") {
      el.scrollLeft = 0;
    } else if (scrollMode === "end") {
      el.scrollLeft = el.scrollWidth - el.clientWidth;
    } else {
      el.scrollLeft = chip.offsetLeft - (el.clientWidth - chip.clientWidth) / 2;
    }
  }, [expanded, currentIndex, scrollMode]);

  if (!current) return null;

  if (!expanded) {
    return (
      <button
        type="button"
        className="week-paginator-chip current collapsed"
        onClick={() => canExpand && setExpanded(true)}
        disabled={!canExpand}
      >
        {current.startLabel} ~ {current.endLabel}
        {canExpand && <span className="week-paginator-caret">▸</span>}
      </button>
    );
  }

  return (
    <div
      className="week-paginator-strip"
      role="listbox"
      ref={stripRef}
      data-scroll-mode={scrollMode}
    >
      {weeks.map((w) => {
        const isCurrent = w.key === currentWeekKey;
        return (
          <button
            type="button"
            key={w.key}
            role="option"
            aria-selected={isCurrent}
            className={`week-paginator-chip${isCurrent ? " current" : ""}`}
            onClick={() => {
              onSelect(w.key);
              setExpanded(false);
            }}
          >
            {w.startLabel} ~ {w.endLabel}
            {isCurrent && <span className="week-paginator-caret">▾</span>}
          </button>
        );
      })}
    </div>
  );
}
```

This is a full-file replacement. All hooks are declared at the top in
a stable order before any conditional returns; computed values
(`current`, `currentIndex`, `scrollMode`) sit between the hook
declarations and the early-return guard so both effects can reference
them safely.

- [ ] **Step 4: Run all WeekPaginator tests**

Run: `cd frontend && npx vitest run src/components/Dashboard/WeekPaginator.test.tsx`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/WeekPaginator.tsx frontend/src/components/Dashboard/WeekPaginator.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): WeekPaginator scroll-position rule on expand

Centers current chip; left-aligns at newest edge, right-aligns at oldest.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Refactor `TaskStream` to render only the selected week

**Files:**
- Modify: `frontend/src/components/Dashboard/TaskStream.tsx`

- [ ] **Step 1: Read the current file**

Read `frontend/src/components/Dashboard/TaskStream.tsx` end-to-end to
confirm the current shape before editing.

- [ ] **Step 2: Replace the file with the new implementation**

Overwrite `frontend/src/components/Dashboard/TaskStream.tsx` with:

```tsx
import { useEffect, useMemo, useState } from "react";
import { Card } from "../Card/Card";
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import type { ExpandMode } from "../../stores/pageTabs";
import { WeekPaginator } from "./WeekPaginator";
import { computeWeeks, weekKeyOf } from "./weekUtils";

const ACTIVE_STATUSES = new Set([
  "RECEIVED", "PARSING", "INSTRUCTION_READY",
  "SUBMITTING", "PENDING", "PARTIAL",
]);

function isActiveExpanded(task: TaskSummary): boolean {
  if (ACTIVE_STATUSES.has(task.status)) return true;
  if (task.status === "FILLED") {
    const updatedAt = new Date(task.updated_at).getTime();
    return Date.now() - updatedAt < 30_000;
  }
  return false;
}

function formatDateLabel(dateKey: string): string {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (dateKey === today) return `今天 ${dateKey}`;
  if (dateKey === yesterday) return `昨天 ${dateKey}`;
  return dateKey;
}

interface Props {
  tasks: TaskSummary[];
  pushEventsByTask: Record<string, PushEvent[]>;
  expandMode: ExpandMode;
  autoTrade: boolean;
}

export function TaskStream({ tasks, pushEventsByTask, expandMode, autoTrade }: Props) {
  const { groups, weeks } = useMemo(() => computeWeeks(tasks), [tasks]);

  const [currentWeekKey, setCurrentWeekKey] = useState<string | null>(null);
  useEffect(() => {
    if (weeks.length === 0) {
      if (currentWeekKey !== null) setCurrentWeekKey(null);
      return;
    }
    if (currentWeekKey == null || !groups.has(currentWeekKey)) {
      setCurrentWeekKey(weeks[0].key);
    }
  }, [weeks, groups, currentWeekKey]);

  const realCurrentWeekKey = useMemo(
    () => weekKeyOf(new Date().toISOString()),
    [],
  );
  const onPastWeek = currentWeekKey !== null && currentWeekKey !== realCurrentWeekKey;
  const newCount = onPastWeek ? (groups.get(realCurrentWeekKey)?.length ?? 0) : 0;

  if (weeks.length === 0 || currentWeekKey == null) {
    return null;
  }

  const weekTasks = groups.get(currentWeekKey) ?? [];

  // Within-week per-day grouping (preserves descending order set by computeWeeks).
  const dayGroups = new Map<string, TaskSummary[]>();
  for (const t of weekTasks) {
    const ts = t.message?.posted_at ?? t.created_at;
    const dateKey = ts.slice(0, 10);
    if (!dayGroups.has(dateKey)) dayGroups.set(dateKey, []);
    dayGroups.get(dateKey)!.push(t);
  }
  const dateKeys = Array.from(dayGroups.keys());

  return (
    <>
      <div className="week-bar">
        <WeekPaginator
          weeks={weeks}
          currentWeekKey={currentWeekKey}
          onSelect={setCurrentWeekKey}
        />
        {newCount > 0 && (
          <button
            type="button"
            className="week-bar-new-badge"
            onClick={() => setCurrentWeekKey(realCurrentWeekKey)}
          >
            本周新消息 {newCount} 条 →
          </button>
        )}
      </div>

      {dateKeys.map((dateKey) => {
        const dayTasks = dayGroups.get(dateKey)!;
        return (
          <div key={dateKey}>
            <div className="stream-divider">{formatDateLabel(dateKey)} · {dayTasks.length}</div>
            {dayTasks.map((t) => {
              const expanded =
                expandMode === "all-open" ? true :
                expandMode === "all-closed" ? false :
                isActiveExpanded(t);
              return (
                <Card
                  key={t.id}
                  task={t}
                  pushEvents={pushEventsByTask[t.id] ?? []}
                  expanded={expanded}
                  autoTrade={autoTrade}
                />
              );
            })}
          </div>
        );
      })}
    </>
  );
}
```

Note: this preserves the existing `Card` props and `formatDateLabel`
behavior verbatim. The only render-time change is wrapping the
date-keyed loop with the sticky bar and scoping `dayGroups` to one
week.

- [ ] **Step 3: Run typecheck**

Run: `cd frontend && npm run typecheck`
Expected: zero errors. (If a `Card` prop has changed since this plan
was written, surface the mismatch and fix before continuing.)

- [ ] **Step 4: Run all existing frontend tests**

Run: `cd frontend && npm test`
Expected: all green. Existing TaskStream consumers should still work
because `Props` is unchanged.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Dashboard/TaskStream.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): TaskStream — weekly pagination via WeekPaginator

Renders one week's tasks at a time, defaulting to the newest week.
Past-week views show a "本周新消息 N 条 →" badge that jumps back to
the real current week.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `TaskStream` integration tests

**Files:**
- Create: `frontend/src/components/Dashboard/TaskStream.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Dashboard/TaskStream.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { TaskStream } from "./TaskStream";
import type { TaskSummary } from "../../api/domain-types";

// Freeze "now" so the "real current week" is deterministic.
const NOW = new Date(2026, 3, 22, 12, 0, 0); // 2026-04-22 (Wednesday) → wk 04-19

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
});

const mkTask = (id: string, postedAt: Date, content = "msg"): TaskSummary =>
  ({
    id,
    status: "FILLED",
    created_at: postedAt.toISOString(),
    updated_at: postedAt.toISOString(),
    message: {
      url: "https://w/x",
      author: "a",
      content,
      posted_at: postedAt.toISOString(),
      received_at: postedAt.toISOString(),
    },
  }) as unknown as TaskSummary;

describe("<TaskStream> weekly pagination", () => {
  it("renders only the current week's tasks by default", () => {
    const tasks = [
      mkTask("this-1", new Date(2026, 3, 22, 10), "this week 1"),
      mkTask("last-1", new Date(2026, 3, 15, 10), "last week 1"),
    ];
    render(
      <TaskStream tasks={tasks} pushEventsByTask={{}} expandMode="smart" autoTrade={false} />,
    );
    expect(screen.getByText("this week 1")).toBeInTheDocument();
    expect(screen.queryByText("last week 1")).toBeNull();
  });

  it("shows the WeekPaginator chip with the current week's range", () => {
    const tasks = [mkTask("a", new Date(2026, 3, 22, 10))];
    render(
      <TaskStream tasks={tasks} pushEventsByTask={{}} expandMode="smart" autoTrade={false} />,
    );
    expect(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ })).toBeInTheDocument();
  });

  it("switches to a past week when its chip is selected", () => {
    const tasks = [
      mkTask("this-1", new Date(2026, 3, 22, 10), "this week"),
      mkTask("last-1", new Date(2026, 3, 15, 10), "last week"),
    ];
    render(
      <TaskStream tasks={tasks} pushEventsByTask={{}} expandMode="smart" autoTrade={false} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    fireEvent.click(screen.getByRole("option", { name: /04\/12 ~ 04\/18/ }));
    expect(screen.queryByText("this week")).toBeNull();
    expect(screen.getByText("last week")).toBeInTheDocument();
  });

  it("shows the new-messages badge with the current-week count when viewing a past week", () => {
    const tasks = [
      mkTask("this-1", new Date(2026, 3, 22, 10), "this week 1"),
      mkTask("this-2", new Date(2026, 3, 21, 10), "this week 2"),
      mkTask("last-1", new Date(2026, 3, 15, 10), "last week"),
    ];
    render(
      <TaskStream tasks={tasks} pushEventsByTask={{}} expandMode="smart" autoTrade={false} />,
    );
    // Switch to last week.
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    fireEvent.click(screen.getByRole("option", { name: /04\/12 ~ 04\/18/ }));
    const badge = screen.getByRole("button", { name: /本周新消息 2 条/ });
    expect(badge).toBeInTheDocument();
    // Click jumps back.
    fireEvent.click(badge);
    expect(screen.getByText("this week 1")).toBeInTheDocument();
    expect(screen.queryByText("last week")).toBeNull();
    // Badge no longer shown.
    expect(screen.queryByRole("button", { name: /本周新消息/ })).toBeNull();
  });

  it("does not show the new-messages badge when the current real week has no data", () => {
    const tasks = [mkTask("last-1", new Date(2026, 3, 15, 10), "last week only")];
    render(
      <TaskStream tasks={tasks} pushEventsByTask={{}} expandMode="smart" autoTrade={false} />,
    );
    expect(screen.queryByRole("button", { name: /本周新消息/ })).toBeNull();
  });

  it("snaps back to the newest week when the previously selected week disappears", () => {
    const initial = [
      mkTask("this-1", new Date(2026, 3, 22, 10), "this week"),
      mkTask("last-1", new Date(2026, 3, 15, 10), "last week"),
    ];
    const { rerender } = render(
      <TaskStream tasks={initial} pushEventsByTask={{}} expandMode="smart" autoTrade={false} />,
    );
    // Navigate to last week.
    fireEvent.click(screen.getByRole("button", { name: /04\/19 ~ 04\/25/ }));
    fireEvent.click(screen.getByRole("option", { name: /04\/12 ~ 04\/18/ }));
    expect(screen.getByText("last week")).toBeInTheDocument();
    // Simulate page-tab swap → new tasks list with no last-week data.
    rerender(
      <TaskStream
        tasks={[mkTask("other-this-1", new Date(2026, 3, 22, 11), "other this week")]}
        pushEventsByTask={{}}
        expandMode="smart"
        autoTrade={false}
      />,
    );
    expect(screen.getByText("other this week")).toBeInTheDocument();
    expect(screen.queryByText("last week")).toBeNull();
  });

  it("preserves the existing per-day stream-divider inside a week", () => {
    const tasks = [
      mkTask("today", new Date(2026, 3, 22, 10), "today msg"),
      mkTask("yesterday", new Date(2026, 3, 21, 10), "yesterday msg"),
    ];
    render(
      <TaskStream tasks={tasks} pushEventsByTask={{}} expandMode="smart" autoTrade={false} />,
    );
    const dividers = screen.getAllByText(/2026-04-2[12]/);
    expect(dividers.length).toBeGreaterThanOrEqual(2);
    // "Today" label format is `今天 YYYY-MM-DD`.
    expect(within(document.body).getByText(/今天 2026-04-22/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests**

Run: `cd frontend && npx vitest run src/components/Dashboard/TaskStream.test.tsx`
Expected: PASS, 7 tests.

If the "snaps back" test fails because the rerender's effect hasn't
flushed, wrap the `rerender` call in `act(() => { ... })` from
`@testing-library/react`. Confirm before adjusting.

- [ ] **Step 3: Run the full frontend suite**

Run: `cd frontend && npm test`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Dashboard/TaskStream.test.tsx
git commit -m "$(cat <<'EOF'
test(frontend): TaskStream weekly pagination behavior

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `.week-bar` and `.week-paginator-*` styles

**Files:**
- Modify: `frontend/src/components/Dashboard/Dashboard.css`

- [ ] **Step 1: Append the new styles**

Append to the end of `frontend/src/components/Dashboard/Dashboard.css`:

```css
/* ──────────────────────────────────────────────────────────────────────
 * Week bar — sticky row above the task stream.
 * Holds the WeekPaginator chip-strip on the left and a "new messages"
 * badge on the right when the user is viewing a past week.
 * ────────────────────────────────────────────────────────────────────── */
.week-bar {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-3);
  background: var(--bg-1);
  border-bottom: 1px solid var(--line);
}

.week-paginator-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 28px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: var(--bg-2);
  color: var(--fg-2);
  font: inherit;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  white-space: nowrap;
  scroll-snap-align: start;
}
.week-paginator-chip:hover:not(:disabled) {
  border-color: var(--brand);
  color: var(--fg-1);
}
.week-paginator-chip.current {
  background: var(--bg-3);
  color: var(--fg-1);
  border-color: var(--line-strong);
}
.week-paginator-chip:disabled {
  cursor: default;
  opacity: 0.85;
}
.week-paginator-caret {
  font-size: 10px;
  opacity: 0.7;
}

.week-paginator-strip {
  display: flex;
  gap: var(--space-2);
  /* Width = 3 chips (~110px each) + 2 gaps. */
  max-width: calc(110px * 3 + var(--space-2) * 2);
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scrollbar-width: none;
}
.week-paginator-strip::-webkit-scrollbar {
  display: none;
}

.week-bar-new-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--brand);
  border-radius: 13px;
  background: rgba(63, 181, 197, 0.12);
  color: var(--brand);
  font: inherit;
  font-size: 11.5px;
  cursor: pointer;
}
.week-bar-new-badge:hover {
  background: rgba(63, 181, 197, 0.20);
}
```

- [ ] **Step 2: Verify nothing else broke**

Run: `cd frontend && npm test`
Expected: all green. (CSS changes don't affect test outcomes, but a
typo in a selector that JSX reads via `className` could.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dashboard/Dashboard.css
git commit -m "$(cat <<'EOF'
style(frontend): week-bar + WeekPaginator chip styles

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Manual smoke test in the dev server

**Files:** none modified — verification only.

- [ ] **Step 1: Start the dev server**

In one terminal:

```bash
cd frontend && npm run dev
```

In another, ensure the backend is up (existing project workflow —
`make dev` or your usual command).

- [ ] **Step 2: Walk through the checklist with at least 2 weeks of data**

If the dev DB doesn't have multi-week tasks, create some by either:
- inserting tasks via a backend script with `posted_at` spanning two
  Sundays apart, or
- temporarily editing `weekKeyOf` to bucket per-day instead of
  per-week (then revert before committing) — only if no easy data
  path exists.

Verify each:
- Sticky bar shows current week's `MM/DD ~ MM/DD ▸` chip.
- Clicking the chip expands a horizontal strip; max 3 chips visible
  side-by-side; older weeks are reachable by horizontal scroll/swipe.
- Selecting a past-week chip swaps the rendered tasks.
- While on a past week, the "本周新消息 N 条 →" badge appears at the
  right of the bar; clicking it returns to the newest week and
  removes the badge.
- Switching the active page tab (PageTabs) resets selection to the
  newest week of the new tab.
- Single-week page: chip is a non-interactive plain pill (no caret).

- [ ] **Step 3: Open browser devtools**

Confirm the console has no errors or warnings introduced by the new
component.

- [ ] **Step 4: Run the full frontend test suite one final time**

Run: `cd frontend && npm test && npm run typecheck`
Expected: all green, zero type errors.

- [ ] **Step 5: No code changes — nothing to commit**

If smoke uncovered a defect, fix it in a follow-up task (write the
test first, then the fix), do not amend earlier commits.

---

## Self-Review Notes

- Spec coverage:
  - Sun→Sat boundary → Tasks 1, 11.
  - Empty weeks skipped → Task 3 (computeWeeks only emits keys with non-empty buckets), Task 11 (test covers).
  - Don't disrupt past-week view; show jump-back badge → Tasks 10, 11.
  - WeekPaginator standalone, controlled, ≤3 visible chips, scrollable, time decreases L→R, edge alignment rules, single-week guard, outside-click collapse → Tasks 4–9.
  - New-messages badge sibling of paginator → Task 10.
  - Per-day grouping inside week preserved → Task 10 (kept `formatDateLabel`), Task 11 (test).
  - Snap-back-to-newest on tab swap → Task 10 (sync effect), Task 11 (test).
  - Standalone CSS `.week-bar` + chip styles → Task 12.
- Placeholder scan: no TODOs, no "similar to", every code step has full code.
- Type/name consistency: `WeekInfo` defined once in `weekUtils.ts`, re-exported via component import; `WeekPaginatorProps` props match `TaskStream` call site exactly; `currentWeekKey: string | null` used consistently in `TaskStream`, narrowed to `string` before passing into `WeekPaginator`.
