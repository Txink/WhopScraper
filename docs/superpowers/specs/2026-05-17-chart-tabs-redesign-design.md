# Detail Pane Chart — Tabs + Popup + Candlestick Redesign

> **Status:** Brainstorming complete · 2026-05-17
> **Scope:** Position detail pane (`DetailPane` → `DetailChart`) top-of-chart period selector and chart rendering. Card-level `IntradaySpark` untouched. 做T pair / trade list / detail summary untouched.

## Goal

Replace the current 7-period tab row + inline-expanded "today" sub-options panel with a **7-tab top bar** where 3 tabs open **anchored popovers** for sub-config and 4 tabs are direct view switches. Switch the 4 multi-day K-line views from line/area to **candlestick** rendering with **continuous pinch-zoom + pan** within a pre-loaded batch — the broker-app convention.

Current pain points being addressed:

- "日内" double-click toggles an **inline panel** that pushes the chart down → layout shift, visual jank.
- Period buttons `5/7/15/30/60/90` mix data granularities (5min K vs 15min K vs daily K) under one "day count" abstraction — semantics blurry.
- No candlestick rendering anywhere, even where it's the right tool (multi-month price history is hard to read as a line).
- No weekly/monthly/yearly K views — the underlying SDK supports them; the backend doesn't expose them.

## View Type Taxonomy

The redesign introduces a single `ViewType` discriminator that replaces the current `(period, todayGranularity, todaySessions)` triplet. Each view has a fixed chart-rendering shape, fixed data-request signature, and (optionally) a popover with sub-config.

| View | Tab label | Renderer | Backend `period` | Sub-config | Live-tick |
|---|---|---|---|---|---|
| `intraday` | 日内 | line + session padding | `today` | sessions: 夜盘/盘前/盘中/盘后/全部 | ✅ (1-min) |
| `minute` | 分钟 | line (raw bars) | `today` | granularity: 1/2/3/5 min | ✅ (N-min) |
| `multiday` | 多日 | line + day-separator | `5` or `7` | window: 5日 / 7日 | ✅ (5-min) |
| `day` | 日K | **candlestick** + zoom/pan | `day` | — | ❌ |
| `week` | 周K | **candlestick** + zoom/pan | `week` | — | ❌ |
| `month` | 月K | **candlestick** + zoom/pan | `month` | — | ❌ |
| `year` | 年K | **candlestick** + zoom/pan | `year` | — | ❌ |

**Tab-bar layout:** flat 7-tab row in the chart card header, no overflow. Sub-config is shown on the tab as a "·sub" suffix:

```
[日内·盘中]  [分钟·5min]  [多日·5日]  [日K]  [周K]  [月K]  [年K]
```

The 3 popup-tabs (`intraday/minute/multiday`) carry sub-state independently in the `detailView` store — switching away and back restores the user's last sub-choice.

## Tab + Popup Interaction

`TabPopover` is a new reusable component (anchored dropdown). One instance per popup-tab.

| User action | Effect |
|---|---|
| Click an **inactive** popup-tab | Activate the view using the stored sub-state (or default if never set). **Do not** open the popover. |
| Click an **already-active** popup-tab | Toggle the popover. |
| Click a **K-line** tab | Switch directly to that view, no popover. |
| Click a pill inside the popover | Apply the sub-config and close the popover. |
| Click outside the popover / press Esc / switch to any other tab | Close the popover. |

**Popover placement:**

- Absolute-positioned **inside** the chart card.
- Top edge pinned to the bottom of the trigger tab (gap ≈ 6px).
- Left edge aligned with the tab's left edge, with **boundary detection**: if the popover's right edge would exit the card, shift left to stay inside.
- A small ▲ caret on the top edge points at the trigger tab.

**Defaults** (first time the user opens the detail pane):

| View | Default sub-config |
|---|---|
| `intraday` | sessions = `regular` |
| `minute` | granularity = `5min` |
| `multiday` | window = `5` |

Default initial view = `intraday` (unchanged from today).

## Store: `useDetailViewStore` Refactor

The current 3-field period model collapses to a single `view` discriminator + per-view sub-state.

**Before:**

```ts
period: Period;                    // "today" | "5" | "7" | "15" | "30" | "60" | "90"
todayGranularity: TodayGranularity; // "分时" | "1min" | "2min" | "3min" | "5min"
todaySessions: SessionMode;         // "regular" | "pre" | "post" | "overnight" | "all"
```

**After:**

```ts
type ViewType = "intraday" | "minute" | "multiday" | "day" | "week" | "month" | "year";
type IntradaySession = "regular" | "pre" | "post" | "overnight" | "all";
type MinuteGranularity = "1min" | "2min" | "3min" | "5min";
type MultidayWindow = 5 | 7;

view: ViewType;                    // current tab
intradaySessions: IntradaySession; // 日内 sub (persisted independently)
minuteGranularity: MinuteGranularity;
multidayWindow: MultidayWindow;
```

The `setTodayGranularity` constraint that auto-snapped session → "regular" on K-line granularity switch goes away — it's no longer reachable, since K-line granularities are now in their own `minute` view (session is always `regular` there) and `intraday` view's granularity is fixed to `分时`.

`activePairId / selectedBuys / selectedSells / showAllPairs / selectedSymbol` all stay untouched.

## New File: `viewConfig.ts`

Single source of truth mapping `ViewType` → fetch params + render shape:

```ts
interface ViewConfig {
  period: "today" | "5" | "7" | "day" | "week" | "month" | "year";
  granularity?: "分时" | "1min" | "2min" | "3min" | "5min"; // only for period=today
  sessions?: "regular" | "pre" | "post" | "overnight" | "all"; // only for period=today
  datasetType: "line" | "candlestick";
  initialVisibleCount: number;
  liveCfg: { periodMinutes: number; allowAppend: boolean } | null;
  sessionBgEnabled: boolean;
  dayMarkersEnabled: boolean; // multi-day separator lines
}

function resolveViewConfig(
  view: ViewType,
  intradaySessions: IntradaySession,
  minuteGranularity: MinuteGranularity,
  multidayWindow: MultidayWindow,
): ViewConfig;
```

Initial visible counts (for K-line zoom defaults — user can pinch out to see all loaded bars):

| View | Loaded batch | Initial visible |
|---|---|---|
| `intraday` | full session | full session |
| `minute · 1min` | ~390 | ~390 |
| `minute · 5min` | ~78 | ~78 |
| `multiday · 5` | ~390 (5×78) | ~390 |
| `day` | 250 | 60 |
| `week` | 200 | 52 |
| `month` | 120 | 36 |
| `year` | 30 | 20 |

## Chart Rendering: `DetailChart` Rewrite

**New dependency:** `chartjs-chart-financial` — registers `CandlestickController + OhlcController + CandlestickElement` alongside existing `LineController + ScatterController`.

**Effect A (chart create) structural deps change:**

```ts
// before
[symbol, period, todayGranularity, todaySessions, colorMode]
// after
[symbol, view, intradaySessions, minuteGranularity, multidayWindow, colorMode]
```

Each view-change (or sub-change for popup views) destroys + recreates the chart instance — same one-rebuild-per-switch contract as today.

**Dataset shape dispatch:**

```ts
const priceDataset = viewConfig.datasetType === "candlestick"
  ? {
      type: "candlestick",
      data: bars.map(b => ({
        x: Date.parse(b.timestamp),
        o: b.open, h: b.high, l: b.low, c: b.close,
      })),
      borderColor: { up: cssVar("--up-color"), down: cssVar("--down-color"), unchanged: C.fg3 },
      backgroundColor: { up: cssVar("--up-color"), down: cssVar("--down-color"), unchanged: C.fg3 },
    }
  : {
      type: "line",
      data: bars.map(b => b.close),
      // (existing line config — borderColor, fill gradient, tension, etc.)
    };
```

**BUY/SELL scatter markers** + **avg-cost reference line** + **crosshair plugin** + **min/max labels plugin** all attach to the chart unchanged, so K-line views inherit all the trade-overlay infrastructure.

**`sessionBgPlugin`** only enables for `view === "intraday"` (the session-tint background only makes sense for the time-padded 分时 layout).

**Day-separator markers** (new): for `view === "multiday"` only, draw a vertical guide line at every trading-day boundary in `bars`. Implemented as a small inline plugin in `DetailChart`, not a new file.

**`chartjs-plugin-zoom`** stays globally registered. For `day/week/month/year` views: `limits.x = { min: 0, max: data.length-1, minRange: 5 }`, initial `scale.x.{min,max}` clamped to the right edge ± `initialVisibleCount`. For line views, zoom is left on but rarely used.

**Reset zoom button** (existing `↺ 重置`): visible whenever the user has panned/zoomed off the initial window — semantics unchanged, applies to all 7 views.

## Live Tick: `liveTick.ts` Remap

The standalone `liveConfig(period, todayGranularity)` function is **deleted** — its responsibility moves into `viewConfig.ts`'s `liveCfg` field (see "New File" section above). Effect C in `DetailChart` reads `viewConfig.liveCfg` directly; no separate resolver.

| View | `liveCfg` value in `viewConfig` |
|---|---|
| `intraday` | `{ periodMinutes: 1, allowAppend: true }` |
| `minute` | `{ periodMinutes: N, allowAppend: true }` (N from granularity) |
| `multiday` | `{ periodMinutes: 5, allowAppend: true }` |
| `day/week/month/year` | `null` (no live updates) |

What stays in `liveTick.ts`: `applyLiveTick(...)` and `bucketKey(...)` — the pure helpers that mutate a bars array / compute time-bucket keys. Only `liveConfig` is removed.

Effect C (live-tick RAF loop) re-keys on `[view, minuteGranularity, multidayWindow, symbol]`. The DOM pulse dot stays a `<div class="live-pulse">` overlay.

## Time Formatting: `timeFmt.ts` Additions

New formatters for K-line tick labels:

```ts
fmtBjWeekISO(iso): string;  // "2026-W19"
fmtBjMonth(iso): string;    // "2026-03"
fmtBjYear(iso): string;     // "2025"
```

Existing `fmtBjHM / fmtBjDate / fmtBjRel / classifyETSession / tradingDayOfET / currentTradingDay` untouched.

## Backend: Period Enum Expansion

`backend/app/broker/longport_client.py`:

```python
# _SDK_PERIODS additions
"week": Period.Week,
"month": Period.Month,
"year": Period.Year,
```

`backend/app/api/http.py`:

```python
# _PERIOD_GRANULARITY_NON_TODAY rewrite
_PERIOD_GRANULARITY_NON_TODAY = {
    "5":     ("min_5", 5 * 78),    # 多日·5日 (preserved)
    "7":     ("min_5", 7 * 78),    # 多日·7日 (preserved)
    "day":   ("day", 250),         # NEW: 日K, ~1 year
    "week":  ("week", 200),        # NEW: 周K, ~4 years
    "month": ("month", 120),       # NEW: 月K, ~10 years
    "year":  ("year", 30),         # NEW: 年K, ~30 years
}
# Removed: "15", "30", "60", "90"
```

Endpoint signature `GET /api/candlesticks?symbol=&period=&granularity=&sessions=` is unchanged — only the accepted enum values for `period` shift.

**Sanity check before any other work:** confirm `Period.Week / Period.Month / Period.Year` are real attributes of the installed `longport.openapi.Period`. A 4-line throwaway script at the start of implementation. If absent, the affected views must be hidden behind a `LONGPORT_HAS_PERIODS_EXTENDED` flag and tabs disabled.

**No `since/until` parameters and no infinite-scroll.** Per §1, every K-line view loads its fixed batch in one request — the user pinches/pans within that batch and can't pull older bars beyond it.

## New File: `TabPopover.tsx`

Reusable anchored dropdown:

```ts
interface TabPopoverProps {
  open: boolean;
  anchorRef: React.RefObject<HTMLElement>;
  containerRef: React.RefObject<HTMLElement>; // for boundary detection
  onClose(): void;
  children: React.ReactNode;
}
```

- Renders a `<div role="dialog">` absolute-positioned relative to `containerRef.current`.
- Computes `left/top` from `anchorRef.current.getBoundingClientRect()` minus `containerRef.current.getBoundingClientRect()`; reflows on window resize.
- Boundary detection: if `left + popoverWidth > containerWidth`, shift left so the right edge is at `containerWidth - 4px`.
- Listens for `keydown` (Esc) and click-outside to call `onClose`.
- Renders a `▲` caret at the top pointing at the trigger.

Used 3 times in `DetailPane`, one per popup-tab. K-line tabs don't use it.

## File Map

**New:**

| File | Responsibility |
|---|---|
| `frontend/src/components/Positions/TabPopover.tsx` | Anchored-dropdown reusable component |
| `frontend/src/components/Positions/viewConfig.ts` | `ViewType → fetch + render config` mapping |

**Modified:**

| File | Change |
|---|---|
| `frontend/src/stores/candlesticks.ts` | `Period` type reshape; `candleCacheKey` keys on `(symbol, view, sub)` |
| `frontend/src/stores/detailView.ts` | `view` discriminator + per-view sub fields; remove `setTodayGranularity` snap logic |
| `frontend/src/components/Positions/DetailPane.tsx` | Tab-bar rewrite (7 tabs, 3 with `TabPopover`); fetch effect keys on `viewConfig` not `(period, todayGranularity, todaySessions)` |
| `frontend/src/components/Positions/DetailChart.tsx` | Dataset dispatch (line vs candlestick); Effect A deps reshape; new day-separator inline plugin for `multiday`; `sessionBg` gating |
| `frontend/src/components/Positions/liveTick.ts` | `liveConfig(view, sub)` replaces `liveConfig(period, todayGranularity)` |
| `frontend/src/components/Positions/timeFmt.ts` | Add `fmtBjWeekISO / fmtBjMonth / fmtBjYear` |
| `frontend/src/components/Positions/Positions.css` | New `.tab-popover`, `.popover-caret`, `.popover-pill` selectors; tab `·sub` suffix style |
| `backend/app/api/http.py` | `_PERIOD_GRANULARITY_NON_TODAY` rewrite |
| `backend/app/broker/longport_client.py` | `_SDK_PERIODS` additions |
| `package.json` | Add `chartjs-chart-financial` |

**Tests modified:**

| File | Change |
|---|---|
| `frontend/src/components/Positions/DetailChart.test.tsx` | Props re-shape; new candlestick-mode render case |
| `backend/tests/api/test_quote_candles_http.py` | Drop `period=15/30/60/90` cases; add `period=day/week/month/year` cases |

**Untouched** (verified scope):

- `IntradaySpark.tsx` + `sessionWindow.ts` + `sessionSlots.ts` + `resolveSessionParam.ts` + `SparkDefs.tsx` — card-level mini chart, separate component
- `crosshairPlugin.ts` + `minMaxLabelsPlugin.ts` + `sessionBgPlugin.ts` — reused as-is, sessionBg only enabled for `intraday`
- `DetailSummary.tsx` / `TradeList.tsx` / `PairDetailModal.tsx` / `ConfirmModal.tsx` — orthogonal
- `PositionCard.tsx` / `OptionCard.tsx` / `PositionsPanel.tsx` — orthogonal
- 做T pair feature in its entirety

## Implementation Order

Inside one branch, with each step independently committable:

1. **Backend enum probe** — 1-line script: `from longport.openapi import Period; print(dir(Period))`. Confirm `Week / Month / Year` exist. If missing, branch the plan (hide those tabs).
2. **Backend changes** — `_SDK_PERIODS` + `_PERIOD_GRANULARITY_NON_TODAY` + test updates. Mergeable without frontend.
3. **Add `chartjs-chart-financial`** — install + register controllers in `DetailChart.tsx`.
4. **`viewConfig.ts`** — new file, pure mapping; add unit test if it grows logic.
5. **`detailView` store rewrite** — `view` discriminator + sub fields. Update consumers (one call site: `DetailPane`).
6. **`TabPopover.tsx`** — new reusable; small render test.
7. **`DetailPane` tab-bar rewrite** — wire `TabPopover` × 3 + 4 direct K tabs; fetch effect rekeys on `viewConfig`.
8. **`DetailChart` render dispatch** — line/candlestick branch; day-separator plugin for multiday.
9. **`liveTick` remap** — new signature; Effect C dep changes.
10. **Tests** — `DetailChart.test.tsx` update; manual smoke per view.

## Out of Scope

- No infinite-scroll historical backfill — fixed batch per K view (§1).
- No technical indicators (MA / MACD / RSI / Bollinger) — pure price-only chart.
- No `lightweight-charts` migration — staying in chart.js (§3).
- No live-tick on weekly/monthly/yearly K (no sane semantics).
- No `IntradaySpark` card-level changes.
- No 做T pair / trade list / detail summary changes.
- No mobile-specific responsive tab collapsing — desktop product, no need.

## Open Risks

1. **`Period.Week/Month/Year` SDK availability** — probe before commit (step 1).
2. **`chartjs-chart-financial` vs chart.js 4.x compatibility** — check `peerDependencies` on install; lock version if needed.
3. **Plugin coord assumption** — `crosshairPlugin / minMaxLabelsPlugin` were written against a `category`-scale line chart. The candlestick controller uses a `time`/`linear` scale for x — pixel-to-data conversions need re-verification on candle views.
4. **Tooltip behavior on candlesticks** — existing tooltip callbacks read `dataset.label === "成交价"`; the candlestick dataset has different parsed shape (`{o,h,l,c}` not a single `y`). Tooltip label callback needs a branch.
5. **BUY/SELL marker snapping on candle views** — current marker `x` is the bar index in `closes[]`. On candlestick chart with a time-scale x-axis, markers need `x = Date.parse(bar.timestamp)` instead. The marker-snap loop in `DetailChart` needs a view-aware branch.
6. **Initial visible window vs loaded batch** — for `day` view: loaded 250 / visible 60. The user might not realize they can pinch out to see all 250. Mitigation: when `view ∈ {day, week, month, year}`, render a subtle "↔ 滑动 / 缩放" hint in the chart corner for the first session after the feature ships. (Optional polish, not blocking.)
