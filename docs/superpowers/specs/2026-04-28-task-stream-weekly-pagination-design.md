# TaskStream Weekly Pagination — Design

**Date**: 2026-04-28
**Status**: Spec, awaiting user review.
**Branch**: refactor-v2

## 1. Background & Motivation

The main dashboard's `TaskStream` (`frontend/src/components/Dashboard/TaskStream.tsx`)
currently renders every task for the active page tab in one descending
scroll, grouped only by date (`stream-divider` chips like
"今天 2026-04-28 · 12"). As traders accumulate weeks of history, the
single scrolling list gets unwieldy: there is no way to jump to "two
weeks ago" without scrolling past the entire intervening run, and the
DOM keeps growing.

The user wants weekly pagination: each page = one week of messages,
with a compact week selector pinned at the top.

## 2. Decisions Made During Brainstorming

| Question | Decision |
|---|---|
| Week boundary | **Sunday 00:00 → Saturday 23:59:59 (local timezone)**. Week key = the Sunday's `YYYY-MM-DD`. |
| Empty weeks | **Skipped.** Only weeks with ≥1 task appear in the page list. |
| Real-time arrivals on past weeks | **Don't disrupt** the user's view; show a "本周新消息 N 条 →" badge that, when clicked, jumps back to the current real-world week. |
| Selector layout | **Sticky horizontal selector** at the top: collapsed = single chip showing the selected week's date range + ▸; expanded = a horizontally scrollable strip of week chips, container width capped at 3 chips. |
| Selector ordering | **Time decreases left → right** (newest week leftmost). Expanding rightward = paging into history. |
| Default visible chips when expanded | **Centered on current selection**: 1 newer + current + 1 older. **Edge case**: if current = newest week, show current + 2 older (left-aligned). If current = oldest week, show 2 newer + current (right-aligned). |
| Chip label | Date range only, e.g., `04/22 ~ 04/28`. (No relative labels, no count.) |
| New-messages badge placement | **Outside** the `WeekPaginator` component, as a sibling in the sticky bar. The component itself stays focused on "list of weeks + which is selected." |
| Encapsulation | `WeekPaginator` is a **standalone, controlled component**. |

## 3. User-Visible Change

### Added

- A sticky bar above the task stream containing:
  - The `WeekPaginator` chip selector on the left.
  - A "本周新消息 N 条 →" badge on the right, shown only when the user is viewing a past week and the current real-world week has data.
- The body of the stream renders **only the selected week's tasks**, still grouped by day with the existing `stream-divider`.

### Unchanged

- Card rendering, expansion behavior, `RightRail`, `PageTabs`, sort
  order within a week.
- Behavior when the active page tab has no tasks at all: the existing
  empty state ("该监听页暂无任务。") still renders.
- WebSocket / store layer: pagination is purely a render-side concern.
  No new API calls; pagination operates over the tasks already in the
  store.

## 4. Component Design

### 4.1 `WeekPaginator` (new)

**Path**: `frontend/src/components/Dashboard/WeekPaginator.tsx`

**Purpose**: A controlled chip-strip selector for picking one week
from a list of weeks. Knows nothing about tasks.

**Props**:

```ts
export interface WeekInfo {
  key: string;        // Sunday's YYYY-MM-DD, used as identity
  startLabel: string; // e.g., "04/22"
  endLabel: string;   // e.g., "04/28"
}

export interface WeekPaginatorProps {
  weeks: WeekInfo[];                 // Descending by date. May be empty.
  currentWeekKey: string;            // Must match a key in `weeks`.
  onSelect: (key: string) => void;
}
```

**Internal state**:

- `expanded: boolean` (default `false`)
- A `ref` on the strip element for scroll positioning.

**Render logic**:

- If `weeks.length <= 1`: render a single non-interactive chip with no
  expand button. Selecting is a no-op.
- Collapsed: a single chip showing `${start} ~ ${end} ▸` for
  `currentWeekKey`. Clicking it sets `expanded = true`.
- Expanded:
  - Outer container: fixed width = `3 × chip-width + 2 × gap`,
    `overflow-x: auto`, scroll-snap on the x-axis.
  - Inner strip: every `WeekInfo` rendered as a chip, in array order
    (already descending = newest first / leftmost).
  - The current chip carries a "selected" style (deeper bg + ▾).
  - On open, the strip programmatically scrolls so the selection lands
    where requested by the edge rules:
    - `currentIndex === 0` → scroll to start (current at left, two
      older to its right).
    - `currentIndex === weeks.length - 1` → scroll to end (current at
      right, two newer to its left).
    - Otherwise → center current.
    Implementation uses `ref.current.scrollLeft = ...`. **Do not use
    `scrollIntoView`** — it disrupts iframe-embedded preview hosts and
    is forbidden by the project's design-engineering guardrails.
  - Clicking any chip:
    1. Calls `onSelect(key)`.
    2. Sets `expanded = false`.
- Outside-click: clicking outside the strip collapses it. (Use a
  `mousedown` listener on `document` while expanded.)

**Styling**:

- Hide scrollbar visually but keep functional scrolling:
  `scrollbar-width: none` and `&::-webkit-scrollbar { display: none }`.
- Chip: pill-shaped, monospace digits for date, ~110px wide so that
  three fit cleanly in the container.
- Use existing CSS variables from `Dashboard.css` (`--fg-*`, `--bg-*`,
  border tokens) — do not introduce new color values.

**Tests** (`WeekPaginator.test.tsx`):

- Renders the current chip in collapsed mode by default.
- Clicking the chip toggles expansion.
- Expanded mode renders all weeks, selected one highlighted.
- Clicking a non-selected chip fires `onSelect(key)` and collapses.
- When `weeks.length === 1`, no expand affordance is rendered.
- Outside-click collapses the expanded strip.

### 4.2 `TaskStream` changes

**Path**: `frontend/src/components/Dashboard/TaskStream.tsx`

**New computation** (memoized):

```ts
// Local-time Sunday key for any timestamp string.
// Returns the local-calendar YYYY-MM-DD of the Sunday that starts the week
// containing `ts`. We deliberately do NOT use toISOString() because in
// timezones with a non-zero UTC offset (e.g., Asia/Shanghai +08), the local
// Sunday midnight serializes to a different UTC date, which would mislabel
// the week.
function weekKeyOf(ts: string): string {
  const d = new Date(ts);
  const sunday = new Date(d);
  sunday.setHours(0, 0, 0, 0);
  sunday.setDate(d.getDate() - d.getDay()); // d.getDay() === 0 for Sunday
  const yyyy = sunday.getFullYear();
  const mm = String(sunday.getMonth() + 1).padStart(2, "0");
  const dd = String(sunday.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
```

From the descending-sorted `tasks`, build:

- `groups: Map<weekKey, TaskSummary[]>` — preserves descending order
  within each bucket because we iterate in sorted order.
- `weeks: WeekInfo[]` — derived from `groups.keys()`, preserving
  insertion order (which is descending because the first task of each
  newer week is encountered first). Each `WeekInfo`'s `startLabel` /
  `endLabel` are formatted from the Sunday key + 6 days.

**State**:

- `currentWeekKey: string | null` — `useState<string | null>(null)`.
- An effect synchronizes it with `weeks`:

  ```ts
  useEffect(() => {
    if (weeks.length === 0) {
      if (currentWeekKey !== null) setCurrentWeekKey(null);
      return;
    }
    if (currentWeekKey == null || !groups.has(currentWeekKey)) {
      setCurrentWeekKey(weeks[0].key);
    }
  }, [weeks, currentWeekKey, groups]);
  ```

  This handles three transitions cleanly:
  - First render with data → land on newest week.
  - User switched page tab → previous selection no longer in `groups`
    → snap back to newest.
  - Tasks for the selected week were filtered out → snap back to
    newest.

**New-messages prompt**:

```ts
const realCurrentWeekKey = useMemo(
  () => weekKeyOf(new Date().toISOString()),
  // recomputed only on mount; date rollover during a session is rare,
  // and the value gets refreshed any time TaskStream remounts.
  [],
);
const onPastWeek = currentWeekKey !== null && currentWeekKey !== realCurrentWeekKey;
const newCount = onPastWeek ? (groups.get(realCurrentWeekKey)?.length ?? 0) : 0;
```

**Render**:

```tsx
<>
  {weeks.length > 0 && currentWeekKey && (
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
  )}

  {/* Existing per-day grouping, but only for the selected week */}
  {currentWeekKey && (groups.get(currentWeekKey) ?? []).length > 0 ? (
    /* existing dateKey loop, scoped to groups.get(currentWeekKey)! */
  ) : null}
</>
```

The empty-state branch (`filteredTasks.length === 0`) stays in
`App.tsx`, which already handles "no tasks for active page" before
`TaskStream` is mounted — no change needed there.

**`week-bar` styling** (in `Dashboard.css`):

- `position: sticky; top: <existing sticky offset>` — match whatever
  offset `PageInfoBar` / `PageActionBar` already use.
- Background and shadow so content doesn't bleed through.
- Flex row, space-between, vertical centering.

### 4.3 Tests for `TaskStream`

Augment existing tests (or add new ones):

- Tasks spanning two weeks → renders only the newest-week tasks by
  default; the other week's tasks are not in the DOM.
- Switching `currentWeekKey` (via interacting with `WeekPaginator`)
  swaps the rendered set.
- New-message badge appears when the user navigates to a past week
  whose `realCurrentWeekKey` has data; clicking it jumps back.
- Empty `groups.get(realCurrentWeekKey)` (e.g., the only data is in
  past weeks) → no badge shown.
- After remount with a tasks list that omits the previously-selected
  week, the component snaps to the newest available week.

## 5. Edge Cases

- **Timezones**: `weekKeyOf` formats the local-calendar Sunday with
  `getFullYear/getMonth/getDate`. Two timestamps in the same local
  week always produce the same key regardless of UTC offset.
- **DST transitions**: For timestamps on a DST-jump Sunday, `setDate`
  + `setHours(0,0,0,0)` lands on local midnight of that Sunday; the
  formatted key is unaffected. Add a unit test for both edges.
- **Single-task page**: 1 task → 1 week → `WeekPaginator` shows a
  single chip with no expand button. Stream below renders that one
  task normally.
- **Active page tab swap mid-session**: covered by the sync effect;
  user always lands on the newest week of the new tab's data.
- **Real-world week with no data**: the `realCurrentWeekKey` lookup
  returns `undefined`, `newCount = 0`, badge not shown — nothing to
  jump to.
- **Many weeks (e.g., 30+)**: only `WeekPaginator` cares; horizontal
  scroll handles it. The stream below always renders one week, so
  TaskStream itself stays bounded.

## 6. Out of Scope (YAGNI)

- Fetching older tasks beyond the initial 100-task load. The store
  already accumulates whatever the WS pushes; pagination operates on
  what's there. Backfill of older history is a separate concern.
- Persisting `currentWeekKey` across reloads. Each session starts on
  the newest week.
- Calendar / date picker. The chip strip is sufficient for the
  expected number of weeks (a few dozen at most).
- "Mark as read" / unread state for the new-messages badge. The
  badge's count comes from "tasks in the real current week" and
  disappears the moment the user is back on that week.

## 7. Implementation Order (preview)

The detailed plan will be authored by the writing-plans skill, but
the rough sequence:

1. Add `WeekPaginator` component + tests.
2. Refactor `TaskStream` to compute weeks, hold `currentWeekKey`, and
   render only the selected week.
3. Add the sticky `week-bar` row with `WeekPaginator` + new-messages
   badge; CSS in `Dashboard.css`.
4. Update `TaskStream.test.tsx` for the new behavior.
5. Manual smoke in the dev server: switch page tabs, expand selector,
   click chips, verify badge appearance/disappearance.
