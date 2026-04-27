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
| Real-time arrivals on past weeks | **Don't disrupt** the user's view; surface the indicator on the existing `PageInfoBar` "已发消息 N" element by replacing it with a red, slow-blinking, clickable label "新消息 +K". K = number of tasks in the real current week. Clicking jumps back to the real current week. **No separate badge in the sticky week bar.** |
| Selector layout | **Sticky horizontal selector** at the top: collapsed = single chip showing the selected week's date range + ▸; expanded = a horizontally scrollable strip of week chips, container width capped at 3 chips. |
| Selector ordering | **Time decreases left → right** (newest week leftmost). Expanding rightward = paging into history. |
| Default visible chips when expanded | **Centered on current selection**: 1 newer + current + 1 older. **Edge case**: if current = newest week, show current + 2 older (left-aligned). If current = oldest week, show 2 newer + current (right-aligned). |
| Chip label | Date range only, e.g., `04/22 ~ 04/28`. (No relative labels, no count.) |
| Encapsulation | `WeekPaginator` is a **standalone, controlled component**. |
| State location | Pagination state (`weeks`, `groups`, `currentWeekKey`) is **lifted to `App.tsx`'s `Dashboard`** so `PageInfoBar` and `TaskStream` can both read it. `TaskStream` becomes a controlled renderer; the indicator on `PageInfoBar` reuses the same `currentWeekKey` and the same "jump to current week" callback. |
| Orphan tab | Pagination still works (TaskStream paginates whatever it's handed). The new-messages indicator is **not shown** on the orphan tab — `PageInfoBar` in `mode="orphan"` shows a different layout ("已停用 · X 条历史") and doesn't have the "已发消息 N" anchor. YAGNI; can add later. |

## 3. User-Visible Change

### Added

- A sticky bar above the task stream containing the `WeekPaginator` chip selector on the left. (No badge or other element on the right.)
- The body of the stream renders **only the selected week's tasks**, still grouped by day with the existing `stream-divider`.
- `PageInfoBar` (page mode only): when the user is on a past week *and* the real current week has ≥1 task, the "已发消息 N" element is replaced with a red, slow-blinking, clickable label "新消息 +K". Clicking it jumps the stream back to the real current week, after which the label reverts to "已发消息 N" with the existing lifetime count.

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

**Become a controlled component.** Pagination state moves up to
`App.tsx` (see §4.4) so `PageInfoBar` can read it. `TaskStream` no
longer holds `currentWeekKey` state; instead it receives the selection
+ callback as props.

```ts
interface Props {
  // existing:
  tasks: TaskSummary[];
  pushEventsByTask: Record<string, PushEvent[]>;
  expandMode: ExpandMode;
  autoTrade: boolean;
  // new:
  weeks: WeekInfo[];
  groups: Map<string, TaskSummary[]>;
  currentWeekKey: string | null;
  onSelectWeek: (key: string) => void;
}
```

The `tasks` prop is still threaded through (back-compat for any test
or future caller that wants a "show everything, no pagination"
shortcut), but `TaskStream` itself now reads from `groups` for
rendering. The compute happens once in `App.tsx`, both for cheaper
recomputation and so PageInfoBar gets the same source of truth.

**Render**:

```tsx
if (weeks.length === 0 || currentWeekKey == null) return null;

const weekTasks = groups.get(currentWeekKey) ?? [];
// existing per-day grouping, scoped to weekTasks

return (
  <>
    <div className="week-bar">
      <WeekPaginator
        weeks={weeks}
        currentWeekKey={currentWeekKey}
        onSelect={onSelectWeek}
      />
    </div>
    {/* existing dateKey loop, scoped to weekTasks */}
  </>
);
```

The empty-state branch (`filteredTasks.length === 0`) stays in
`App.tsx`, which already gates `<TaskStream>` mounting — no change
needed there.

**`week-bar` styling** (in `Dashboard.css`):

- `position: sticky; top: <existing sticky offset>`.
- Background + bottom border so content doesn't bleed through on
  scroll.
- Flex row, vertical centering. (No `space-between` since the badge
  is gone — single child on the left.)

### 4.3 `PageInfoBar` changes

**Path**: `frontend/src/components/Dashboard/PageInfoBar.tsx`

Add two optional props:

```ts
interface Props {
  page: WhopPage | null;
  mode: "page" | "orphan";
  orphanCount?: number;
  // new:
  newMessageCount?: number;       // null/undefined/0 → no indicator
  onJumpToCurrent?: () => void;
}
```

Behavior:

- `mode="page"`, `newMessageCount` is a positive number, and
  `onJumpToCurrent` is provided → the `<span>已发消息 {n}</span>`
  element is replaced with:

  ```tsx
  <button
    type="button"
    className="page-info-new-msg"
    onClick={onJumpToCurrent}
  >
    新消息 +{newMessageCount}
  </button>
  ```

  All other elements in the row stay identical.
- `mode="page"` with no/zero `newMessageCount` → unchanged: shows
  "已发消息 N" exactly as today.
- `mode="orphan"` → `newMessageCount` is ignored; orphan layout is
  unchanged. (Consciously out of scope; see Decisions table.)

CSS in `Dashboard.css`:

```css
.page-info-new-msg {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid #cf6f6f;
  border-radius: 4px;
  background: rgba(207, 111, 111, 0.14);
  color: #cf6f6f;
  font: inherit;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  animation: page-info-new-msg-blink 1.6s ease-in-out infinite;
}
.page-info-new-msg:hover { background: rgba(207, 111, 111, 0.22); }
@keyframes page-info-new-msg-blink {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.45; }
}
@media (prefers-reduced-motion: reduce) {
  .page-info-new-msg { animation: none; }
}
```

The red hue (`#cf6f6f`) matches the existing `.db-status.rejected`
treatment in the same stylesheet — reusing the established palette
instead of inventing a new one.

### 4.4 `App.tsx` changes (state lift)

`Dashboard` already has `filteredTasks` and `activePage` in scope.
Add:

```ts
import { computeWeeks, weekKeyOf } from "./components/Dashboard/weekUtils";

const { groups, weeks } = useMemo(() => computeWeeks(filteredTasks), [filteredTasks]);
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

const realCurrentWeekKey = useMemo(() => weekKeyOf(new Date().toISOString()), []);
const onPastWeek = currentWeekKey !== null && currentWeekKey !== realCurrentWeekKey;
const newMessageCount =
  onPastWeek ? (groups.get(realCurrentWeekKey)?.length ?? 0) : 0;
```

Then pass through:

```tsx
<PageInfoBar
  page={activePage}
  orphanCount={orphanCount}
  mode={isOrphanTab ? "orphan" : "page"}
  newMessageCount={isOrphanTab ? 0 : newMessageCount}
  onJumpToCurrent={() => setCurrentWeekKey(realCurrentWeekKey)}
/>

<TaskStream
  tasks={filteredTasks}
  pushEventsByTask={pushEventsByTask}
  expandMode={expandMode}
  autoTrade={autoTrade}
  weeks={weeks}
  groups={groups}
  currentWeekKey={currentWeekKey}
  onSelectWeek={setCurrentWeekKey}
/>
```

The orphan-tab guard (`isOrphanTab ? 0 : newMessageCount`) keeps the
indicator off the orphan view per the Decisions table.

### 4.5 Tests for `TaskStream`

Augment existing tests (or add new ones):

- Given controlled `currentWeekKey` of the newest week, the
  newest-week tasks are rendered and other weeks' tasks are not in
  the DOM.
- Changing the controlling `currentWeekKey` prop swaps the rendered
  set on the next render.
- Selecting a non-current chip in `WeekPaginator` invokes
  `onSelectWeek` with that key.

Tests covering the new-messages indicator live in `PageInfoBar.test.tsx`
because the indicator is rendered there:

- `newMessageCount > 0` (and `mode="page"`) → "已发消息 N" replaced
  with `<button>新消息 +K</button>` carrying class
  `page-info-new-msg`.
- Clicking that button calls `onJumpToCurrent`.
- `newMessageCount` 0/undefined → original "已发消息 N" stays.
- `mode="orphan"` → indicator never shown even if `newMessageCount > 0`.

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

1. `weekUtils.ts` helpers (`weekKeyOf`, `formatWeekRange`, `computeWeeks`) + tests.
2. `WeekPaginator` component + tests (collapsed / expanded / scroll-position / outside-click / single-week guard).
3. Make `TaskStream` controlled — accepts `weeks`, `groups`,
   `currentWeekKey`, `onSelectWeek` as props; renders sticky bar with
   `WeekPaginator` + the selected week's tasks (no badge here).
4. Extend `PageInfoBar` with `newMessageCount` + `onJumpToCurrent`
   props and the red blinking label; tests for the swap.
5. Lift state into `Dashboard` in `App.tsx`: compute weeks/groups,
   hold `currentWeekKey`, derive `newMessageCount`/`onPastWeek`, wire
   props down to `PageInfoBar` and `TaskStream`.
6. CSS: `.week-bar`, `.week-paginator-*`, `.page-info-new-msg` +
   blink keyframe (with `prefers-reduced-motion` fallback).
7. Manual smoke in the dev server.
