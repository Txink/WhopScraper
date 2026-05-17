# Detail Pane Chart Tabs Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 7-period tab row + inline "today" sub-options panel in `DetailPane` with a 7-tab bar (3 with anchored popovers, 4 direct), and add candlestick rendering for day/week/month/year K views with continuous pinch-zoom + pan.

**Architecture:** Single `ViewType` discriminator replaces `(period, todayGranularity, todaySessions)` triplet. A `viewConfig.ts` pure mapping resolves each view to its fetch params + render shape. A new `TabPopover` component handles anchored-dropdown UX. `DetailChart` dispatches between line and candlestick datasets inside the same Chart instance using `chartjs-chart-financial`.

**Tech Stack:** React 18 + Zustand + Chart.js 4.x + new dep `chartjs-chart-financial` (frontend); FastAPI + LongPort SDK `Period.Week/Month/Year` enums (backend).

**Spec:** `docs/superpowers/specs/2026-05-17-chart-tabs-redesign-design.md`

---

## File Map

**New:**

| File | Responsibility |
|---|---|
| `frontend/src/components/Positions/TabPopover.tsx` | Reusable anchored dropdown |
| `frontend/src/components/Positions/TabPopover.test.tsx` | Render + dismiss-on-outside-click + Esc |
| `frontend/src/components/Positions/viewConfig.ts` | `ViewType → fetch + render config` mapping |
| `frontend/src/components/Positions/viewConfig.test.ts` | Pure-function test of `resolveViewConfig` |
| `frontend/src/components/Positions/timeFmt.test.ts` | Tests for new week/month/year formatters (new file alongside existing) |

**Modified:**

| File | Change |
|---|---|
| `backend/app/broker/longport_client.py` | Add `week/month/year` to `_SDK_PERIODS` |
| `backend/app/api/http.py` | Rewrite `_PERIOD_GRANULARITY_NON_TODAY`; update endpoint docstring |
| `backend/tests/api/test_quote_candles_http.py` | Drop 15/30/60/90 cases; add day/week/month/year |
| `frontend/package.json` + `package-lock.json` | Add `chartjs-chart-financial` |
| `frontend/src/stores/candlesticks.ts` | `Period` type reshape; `candleCacheKey` keys |
| `frontend/src/stores/detailView.ts` | `view` discriminator + per-view sub fields |
| `frontend/src/stores/detailView.test.ts` | New shape |
| `frontend/src/api/http.ts` | `candlesticks()` signature: new `period` enum |
| `frontend/src/components/Positions/DetailPane.tsx` | Tab-bar rewrite; fetch effect keys on `viewConfig` |
| `frontend/src/components/Positions/DetailChart.tsx` | Dataset dispatch (line vs candle); Effect A/B deps; tooltip branch; marker x reshape; day-separator inline plugin; sessionBg gating |
| `frontend/src/components/Positions/DetailChart.test.tsx` | Props re-shape; new candlestick case |
| `frontend/src/components/Positions/liveTick.ts` | Delete `liveConfig`; keep `applyLiveTick + bucketKey` |
| `frontend/src/components/Positions/timeFmt.ts` | Add `fmtBjWeekISO / fmtBjMonth / fmtBjYear` |
| `frontend/src/components/Positions/Positions.css` | `.tab-popover`, `.popover-pill`, tab sub-label styles |

---

## Phase A — Backend

### Task A1: Probe LongPort SDK Period enum

**Files:**
- Scratch only (no commit yet)

- [ ] **Step 1: Probe in the backend venv**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend
uv run python -c "from longport.openapi import Period; print([a for a in dir(Period) if not a.startswith('_')])"
```

Expected: a list containing at least `Min_1, Min_5, ..., Day`. Verify it also includes `Week`, `Month`, `Year` (or equivalent — could be `Week`, `Weekly`, `WK` depending on SDK version).

- [ ] **Step 2: Record exact spelling**

If the names are `Week / Month / Year`, proceed as planned.
If the names differ (e.g. `Weekly / Monthly / Yearly`), substitute those spellings wherever `Period.Week / Period.Month / Period.Year` appears in subsequent tasks.
If any of the three is **missing** from the SDK, stop and revise the plan: hide that tab in the UI and skip its backend mapping. Add a note to the spec.

---

### Task A2: Add week/month/year to `_SDK_PERIODS`

**Files:**
- Modify: `backend/app/broker/longport_client.py:708-720`

- [ ] **Step 1: Add the new SDK enum mappings**

In `backend/app/broker/longport_client.py`, replace the `_SDK_PERIODS` dict:

```python
_SDK_PERIODS = {
    "min_1": Period.Min_1,
    "min_2": Period.Min_2,
    "min_3": Period.Min_3,
    "min_5": Period.Min_5,
    "min_15": Period.Min_15,
    "min_30": Period.Min_30,
    "min_60": Period.Min_60,
    "day": Period.Day,
    "week": Period.Week,    # NEW
    "month": Period.Month,  # NEW
    "year": Period.Year,    # NEW
    # Legacy alias retained so older callers that pass "intraday" keep
    # working without a code change.
    "intraday": Period.Min_5,
}
```

- [ ] **Step 2: Run existing broker tests to confirm nothing breaks**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend
uv run pytest tests/broker/ -v
```

Expected: PASS, no regressions.

- [ ] **Step 3: Commit**

```bash
git add backend/app/broker/longport_client.py
git commit -m "feat(broker): expose Period.Week/Month/Year in _SDK_PERIODS"
```

---

### Task A3: Rewrite `_PERIOD_GRANULARITY_NON_TODAY` + update tests

**Files:**
- Modify: `backend/app/api/http.py:713-721`
- Modify: `backend/tests/api/test_quote_candles_http.py:227-256`

- [ ] **Step 1: Write the failing test first**

In `backend/tests/api/test_quote_candles_http.py`, replace the existing `test_candlesticks_periods_bar_counts` parametrize block:

```python
@pytest.mark.parametrize(
    "period,expected_bars",
    [
        # 5/7-day views remain: multi-day intraday stitched at 5-min granularity.
        ("5", 5 * 78),
        ("7", 7 * 78),
        # New K-line periods replace 15/30/60/90 with fixed batches.
        ("day", 250),
        ("week", 200),
        ("month", 120),
        ("year", 30),
    ],
)
def test_candlesticks_periods_bar_counts(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    period: str,
    expected_bars: int,
) -> None:
    """5/7 stitch 5-min intraday across days; day/week/month/year are
    candlestick batches the chart pans/zooms within."""
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": period},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == period
    assert len(data["bars"]) == expected_bars
```

Also delete the old `15/30/60/90` rows from the param list (replaced by `day/week/month/year` above).

- [ ] **Step 2: Add a test that removed periods now return 400**

Append to the same file:

```python
@pytest.mark.parametrize("period", ["15", "30", "60", "90"])
def test_candlesticks_removed_periods_return_400(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    period: str,
) -> None:
    """The old day-count periods are no longer accepted — UI uses
    day/week/month/year instead."""
    client, _ = client_and_broker
    resp = client.get(
        "/api/candlesticks",
        params={"token": _TOKEN, "symbol": "TSLA.US", "period": period},
    )
    assert resp.status_code == 400
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend
uv run pytest tests/api/test_quote_candles_http.py -v
```

Expected: the new parametrize rows for `day/week/month/year` FAIL with 400 (period not in map); the removed-periods test FAILS because they still PASS (period IS in map).

- [ ] **Step 4: Update `_PERIOD_GRANULARITY_NON_TODAY`**

In `backend/app/api/http.py`, replace the dict:

```python
    # Longer-horizon (non-today) periods use a fixed granularity; granularity/
    # sessions query params are ignored for these.
    #
    #   5/7  → multi-day intraday line (5-min bars stitched across days).
    #          Used by the "多日" view; the chart renders a folded line.
    #   day  → 1-year batch of daily candles. The "日K" candlestick view
    #          loads this once and lets the user pinch/pan within it.
    #   week → 4-year batch of weekly candles.
    #   month → 10-year batch of monthly candles.
    #   year  → 30-year batch of yearly candles.
    _PERIOD_GRANULARITY_NON_TODAY: dict[str, tuple[str, int]] = {
        "5":     ("min_5", 5 * 78),
        "7":     ("min_5", 7 * 78),
        "day":   ("day", 250),
        "week":  ("week", 200),
        "month": ("month", 120),
        "year":  ("year", 30),
    }
```

- [ ] **Step 5: Update the endpoint `period` query-param docstring**

In the same file, find the `candlesticks_endpoint` function and update the `period` `Query(description=...)` to:

```python
        period: Annotated[
            str,
            Query(description="today | 5 | 7 | day | week | month | year"),
        ] = "today",
```

Also update the function's docstring "For `today`..." paragraph — the trailing sentence currently reads `5/7 → 5-min, 15 → 15-min, 30/60/90 → daily.` Replace with:

```python
        """Return candlestick bars for a single symbol.

        For `today`, granularity (2/3/5 min) and sessions (regular vs
        pre+post) are user-selectable so the user can choose between a
        clean regular-hours curve and a wider view that includes pre-market
        and after-hours. For other periods these query params are ignored
        (fixed mapping):
          5/7 → 5-min stitched across days (多日 line view);
          day/week/month/year → 1/4/10/30-year batch of candles for the
                                日K/周K/月K/年K candlestick views.
        """
```

- [ ] **Step 6: Run tests to verify pass**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend
uv run pytest tests/api/test_quote_candles_http.py -v
```

Expected: PASS — including the 4 new `day/week/month/year` rows and the 4 removed-periods 400 rows.

- [ ] **Step 7: Run the full backend test suite for regressions**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend
uv run pytest -x
```

Expected: PASS — `_PERIOD_GRANULARITY_NON_TODAY` is used only by this one endpoint, so no other tests should break.

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_quote_candles_http.py
git commit -m "feat(api): replace 15/30/60/90 with day/week/month/year periods"
```

---

## Phase B — Frontend Foundation

### Task B1: Install `chartjs-chart-financial` + register controllers

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json` (auto)
- Modify: `frontend/src/components/Positions/DetailChart.tsx:40-46`

- [ ] **Step 1: Install the package**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm install chartjs-chart-financial
```

If npm reports a peer-dep mismatch with chart.js 4.x, pin a known-compatible version:

```bash
npm install chartjs-chart-financial@^0.2.1
```

(0.2.x is the chart.js 4-compatible line.)

- [ ] **Step 2: Register the candlestick controllers in DetailChart**

In `frontend/src/components/Positions/DetailChart.tsx`, find the import block at the top and the `Chart.register(...)` call at lines 40-46. Add these imports just below the existing chart.js imports:

```ts
import {
  CandlestickController,
  CandlestickElement,
  OhlcController,
  OhlcElement,
} from "chartjs-chart-financial";
```

Then extend `Chart.register(...)`:

```ts
Chart.register(
  LineController, ScatterController,
  LineElement, PointElement,
  LinearScale, CategoryScale,
  Filler, Tooltip,
  zoomPlugin,
  CandlestickController, CandlestickElement,
  OhlcController, OhlcElement,
);
```

- [ ] **Step 3: Run frontend tests to verify nothing regressed**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test
```

Expected: PASS — registering extra controllers should not affect existing line-chart behavior.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/Positions/DetailChart.tsx
git commit -m "feat(detail-chart): add chartjs-chart-financial + register K/OHLC controllers"
```

---

### Task B2: Add week/month/year time formatters

**Files:**
- Modify: `frontend/src/components/Positions/timeFmt.ts`
- Create: `frontend/src/components/Positions/timeFmt.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Positions/timeFmt.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { fmtBjWeekISO, fmtBjMonth, fmtBjYear } from "./timeFmt";

describe("week/month/year BJ formatters", () => {
  it("fmtBjMonth returns YYYY-MM in BJ tz", () => {
    // 2026-03-15T08:00:00Z → 2026-03-15 16:00 BJ
    expect(fmtBjMonth("2026-03-15T08:00:00Z")).toBe("2026-03");
  });

  it("fmtBjYear returns YYYY in BJ tz", () => {
    expect(fmtBjYear("2025-12-31T20:00:00Z")).toBe("2026");
    // 2025-12-31 20:00 UTC = 2026-01-01 04:00 BJ → year=2026
  });

  it("fmtBjWeekISO returns YYYY-Wnn ISO-week", () => {
    // 2026-05-04 (Mon BJ) is ISO week 19 of 2026
    expect(fmtBjWeekISO("2026-05-04T08:00:00Z")).toBe("2026-W19");
  });

  it("fmtBjWeekISO handles year boundary", () => {
    // 2025-12-29 (Mon BJ) is ISO week 1 of 2026 (rolls forward)
    expect(fmtBjWeekISO("2025-12-29T08:00:00Z")).toBe("2026-W01");
  });
});
```

- [ ] **Step 2: Run to verify the tests fail**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- timeFmt.test
```

Expected: FAIL — `fmtBjWeekISO / fmtBjMonth / fmtBjYear` not exported.

- [ ] **Step 3: Add the formatters**

Append to `frontend/src/components/Positions/timeFmt.ts`:

```ts
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
  const thursday = new Date(bjMs + (4 - dayNum) * 24 * 60 * 60 * 1000);
  const year = thursday.getUTCFullYear();
  // Week 1 = the week with Jan 4 (which is always in week 1 by ISO def).
  const jan4 = new Date(Date.UTC(year, 0, 4));
  const jan4Day = jan4.getUTCDay() || 7;
  const week1Mon = new Date(jan4.getTime() - (jan4Day - 1) * 24 * 60 * 60 * 1000);
  const weekNum = Math.round(
    (thursday.getTime() - week1Mon.getTime()) / (7 * 24 * 60 * 60 * 1000),
  ) + 1;
  return `${year}-W${String(weekNum).padStart(2, "0")}`;
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- timeFmt.test
```

Expected: PASS — all 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/timeFmt.ts frontend/src/components/Positions/timeFmt.test.ts
git commit -m "feat(timeFmt): add fmtBjWeekISO/fmtBjMonth/fmtBjYear for K-line axes"
```

---

### Task B3: Create `viewConfig.ts`

**Files:**
- Create: `frontend/src/components/Positions/viewConfig.ts`
- Create: `frontend/src/components/Positions/viewConfig.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Positions/viewConfig.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { resolveViewConfig } from "./viewConfig";

describe("resolveViewConfig", () => {
  const defaults = {
    intradaySessions: "regular" as const,
    minuteGranularity: "5min" as const,
    multidayWindow: 5 as const,
  };

  it("intraday → period=today, granularity=分时, line, sessionBg enabled, live", () => {
    const c = resolveViewConfig("intraday", { ...defaults, intradaySessions: "pre" });
    expect(c.period).toBe("today");
    expect(c.granularity).toBe("分时");
    expect(c.sessions).toBe("pre");
    expect(c.datasetType).toBe("line");
    expect(c.sessionBgEnabled).toBe(true);
    expect(c.liveCfg).toEqual({ periodMinutes: 1, allowAppend: true });
  });

  it("minute → period=today, line, no sessionBg, live at chosen minutes", () => {
    const c = resolveViewConfig("minute", { ...defaults, minuteGranularity: "3min" });
    expect(c.period).toBe("today");
    expect(c.granularity).toBe("3min");
    expect(c.sessions).toBe("regular");
    expect(c.datasetType).toBe("line");
    expect(c.sessionBgEnabled).toBe(false);
    expect(c.liveCfg).toEqual({ periodMinutes: 3, allowAppend: true });
  });

  it("multiday → period=5 or 7, line + day separators, live at 5min no-append", () => {
    const c = resolveViewConfig("multiday", { ...defaults, multidayWindow: 7 });
    expect(c.period).toBe("7");
    expect(c.datasetType).toBe("line");
    expect(c.dayMarkersEnabled).toBe(true);
    expect(c.liveCfg).toEqual({ periodMinutes: 5, allowAppend: false });
  });

  it.each([
    ["day",   "day",   60],
    ["week",  "week",  52],
    ["month", "month", 36],
    ["year",  "year",  20],
  ] as const)("%s → period=%s, candlestick, no live, initial visible %d", (view, period, visible) => {
    const c = resolveViewConfig(view, defaults);
    expect(c.period).toBe(period);
    expect(c.datasetType).toBe("candlestick");
    expect(c.liveCfg).toBeNull();
    expect(c.initialVisibleCount).toBe(visible);
    expect(c.sessionBgEnabled).toBe(false);
    expect(c.dayMarkersEnabled).toBe(false);
  });
});
```

- [ ] **Step 2: Run to verify the tests fail**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- viewConfig.test
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `viewConfig.ts`**

Create `frontend/src/components/Positions/viewConfig.ts`:

```ts
/**
 * Single source of truth mapping each chart `view` to its data-fetch
 * parameters and render shape. Consumed by:
 *   - DetailPane (fetch effect: derives api.candlesticks args)
 *   - DetailChart (dataset type, plugin gating, initial scale window, live tick)
 *
 * Adding a new view = adding a row here + a tab button + (maybe) a sub-config
 * field on the detailView store. The chart component does NOT branch on view
 * name directly; it reads off ViewConfig.
 */

import type { Period } from "../../stores/candlesticks";

export type ViewType =
  | "intraday" | "minute" | "multiday"
  | "day" | "week" | "month" | "year";

export type IntradaySession = "regular" | "pre" | "post" | "overnight" | "all";
export type MinuteGranularity = "1min" | "2min" | "3min" | "5min";
export type MultidayWindow = 5 | 7;

export interface ViewSubState {
  intradaySessions: IntradaySession;
  minuteGranularity: MinuteGranularity;
  multidayWindow: MultidayWindow;
}

export interface LiveCfg {
  periodMinutes: number;
  /** today/today-like views can grow new bars at boundaries; 5/7-day
   *  stitched line never does (the backend ships a fresh window when the
   *  user re-opens the view). */
  allowAppend: boolean;
}

export interface ViewConfig {
  /** Maps to the backend `period` query param. */
  period: Period;
  /** Only sent to the backend when `period === "today"`. */
  granularity?: "分时" | "1min" | "2min" | "3min" | "5min";
  /** Only sent to the backend when `period === "today"`. */
  sessions?: IntradaySession;
  /** Drives Chart.js dataset `type` and tooltip / scale shape. */
  datasetType: "line" | "candlestick";
  /** Default visible-x window when the chart first mounts. User can pinch/pan
   *  beyond this within the loaded `bars.length`. For line views = full data. */
  initialVisibleCount: number;
  /** `null` ⇒ no live updates (K-line views). */
  liveCfg: LiveCfg | null;
  /** Enable the dim "盘前/盘中/盘后" wash + dividers — intraday only. */
  sessionBgEnabled: boolean;
  /** Enable vertical day-separator guides — multiday line only. */
  dayMarkersEnabled: boolean;
}

const _MINUTE_LIVE: Record<MinuteGranularity, number> = {
  "1min": 1, "2min": 2, "3min": 3, "5min": 5,
};

export function resolveViewConfig(view: ViewType, sub: ViewSubState): ViewConfig {
  switch (view) {
    case "intraday":
      return {
        period: "today",
        granularity: "分时",
        sessions: sub.intradaySessions,
        datasetType: "line",
        initialVisibleCount: Number.POSITIVE_INFINITY, // chart owner clamps to bars.length
        liveCfg: { periodMinutes: 1, allowAppend: true },
        sessionBgEnabled: true,
        dayMarkersEnabled: false,
      };
    case "minute":
      return {
        period: "today",
        granularity: sub.minuteGranularity,
        sessions: "regular",
        datasetType: "line",
        initialVisibleCount: Number.POSITIVE_INFINITY,
        liveCfg: { periodMinutes: _MINUTE_LIVE[sub.minuteGranularity], allowAppend: true },
        sessionBgEnabled: false,
        dayMarkersEnabled: false,
      };
    case "multiday":
      return {
        period: sub.multidayWindow === 7 ? "7" : "5",
        datasetType: "line",
        initialVisibleCount: Number.POSITIVE_INFINITY,
        liveCfg: { periodMinutes: 5, allowAppend: false },
        sessionBgEnabled: false,
        dayMarkersEnabled: true,
      };
    case "day":
      return _candleConfig("day", 60);
    case "week":
      return _candleConfig("week", 52);
    case "month":
      return _candleConfig("month", 36);
    case "year":
      return _candleConfig("year", 20);
  }
}

function _candleConfig(period: Period, initialVisibleCount: number): ViewConfig {
  return {
    period,
    datasetType: "candlestick",
    initialVisibleCount,
    liveCfg: null,
    sessionBgEnabled: false,
    dayMarkersEnabled: false,
  };
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- viewConfig.test
```

Expected: PASS — all 7 test cases green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/viewConfig.ts frontend/src/components/Positions/viewConfig.test.ts
git commit -m "feat(detail-chart): add viewConfig — single source for view→fetch+render"
```

---

### Task B4: Reshape `Period` type + `candleCacheKey`

**Files:**
- Modify: `frontend/src/stores/candlesticks.ts`
- Modify: `frontend/src/api/http.ts:300-313`

- [ ] **Step 1: Update `Period` type and `candleCacheKey`**

Replace `frontend/src/stores/candlesticks.ts` entirely:

```ts
import { create } from "zustand";
import type { Candlesticks } from "../api/domain-types";

/** Backend-facing period enum. See viewConfig.ts for the higher-level
 *  ViewType discriminator that maps onto this. */
export type Period = "today" | "5" | "7" | "day" | "week" | "month" | "year";

/** Cache key shape — for `today` it includes the granularity + sessions
 * sub-options so toggling those triggers a fresh fetch instead of reusing
 * stale bars. For other periods it's just symbol::period. */
export function candleCacheKey(
  symbol: string,
  period: Period,
  granularity?: string,
  sessions?: string,
): string {
  if (period === "today") {
    return `${symbol}::today::${granularity ?? "分时"}::${sessions ?? "regular"}`;
  }
  return `${symbol}::${period}`;
}

interface CandlesticksState {
  byKey: Record<string, Candlesticks>;
  setBars(key: string, bars: Candlesticks): void;
  reset(): void;
}

export const useCandlesticksStore = create<CandlesticksState>((set) => ({
  byKey: {},
  setBars: (key, bars) =>
    set((state) => ({ byKey: { ...state.byKey, [key]: bars } })),
  reset: () => set({ byKey: {} }),
}));
```

Note: the default granularity in the cache key changed from `5min` to `分时` because intraday view is now the default user lands on with `分时` granularity.

- [ ] **Step 2: Update `api.candlesticks` signature**

In `frontend/src/api/http.ts`, replace the `candlesticks` method (lines ~300-313):

```ts
  async candlesticks(
    symbol: string,
    period: "today" | "5" | "7" | "day" | "week" | "month" | "year" = "today",
    opts: {
      // Only used when period === "today"; ignored otherwise.
      granularity?: "分时" | "1min" | "2min" | "3min" | "5min";
      sessions?: "regular" | "pre" | "post" | "overnight" | "all";
    } = {},
  ): Promise<Candlesticks> {
    const qs = new URLSearchParams({ symbol, period });
    if (opts.granularity) qs.set("granularity", opts.granularity);
    if (opts.sessions) qs.set("sessions", opts.sessions);
    return request<Candlesticks>(`/api/candlesticks?${qs.toString()}`);
  },
```

- [ ] **Step 3: Type-check the frontend to surface all breakage**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run typecheck
```

Expected: FAIL. There will be type errors in:
- `stores/detailView.ts` (still has old `period` shape — fixed in Task B5)
- `components/Positions/DetailPane.tsx` (consumes the old shape — fixed in Task D1/D2)
- `components/Positions/DetailChart.tsx` (consumes old `Period` for `INITIAL_VISIBLE_COUNT` — fixed in Task E1)
- `components/Positions/liveTick.ts` (`Period` import — fixed in Task F1)
- Tests that reference the old period values.

This is expected — we'll fix them in subsequent tasks. **Do not commit yet** — typecheck must pass before commit. Move directly to Task B5.

---

### Task B5: Rewrite `detailView` store + update its test

**Files:**
- Modify: `frontend/src/stores/detailView.ts`
- Modify: `frontend/src/stores/detailView.test.ts`

- [ ] **Step 1: Update the test to reflect the new shape**

Replace `frontend/src/stores/detailView.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { useDetailViewStore } from "./detailView";

describe("detailView store", () => {
  beforeEach(() => {
    useDetailViewStore.setState({
      selectedSymbol: null,
      activePairId: null,
      showAllPairs: false,
      view: "intraday",
      intradaySessions: "regular",
      minuteGranularity: "5min",
      multidayWindow: 5,
      selectedBuys: new Set(),
      selectedSells: new Set(),
    });
  });

  it("selectSymbol stores the value", () => {
    useDetailViewStore.getState().selectSymbol("TSLA.US");
    expect(useDetailViewStore.getState().selectedSymbol).toBe("TSLA.US");
  });

  it("selectSymbol resets transient state (active pair + selection)", () => {
    useDetailViewStore.setState({
      activePairId: 1,
      selectedBuys: new Set(["b1", "b2"]),
      selectedSells: new Set(["s1"]),
    });
    useDetailViewStore.getState().selectSymbol("NVDA.US");
    const s = useDetailViewStore.getState();
    expect(s.activePairId).toBeNull();
    expect(s.selectedBuys.size).toBe(0);
    expect(s.selectedSells.size).toBe(0);
  });

  it("setView switches the discriminator", () => {
    useDetailViewStore.getState().setView("day");
    expect(useDetailViewStore.getState().view).toBe("day");
  });

  it("per-view sub-state persists across view switches", () => {
    const s = useDetailViewStore.getState();
    s.setIntradaySessions("post");
    s.setMinuteGranularity("2min");
    s.setMultidayWindow(7);
    s.setView("week");
    s.setView("intraday");
    expect(useDetailViewStore.getState().intradaySessions).toBe("post");
    expect(useDetailViewStore.getState().minuteGranularity).toBe("2min");
    expect(useDetailViewStore.getState().multidayWindow).toBe(7);
  });

  it("toggleTrade adds and removes from the correct side", () => {
    const { toggleTrade } = useDetailViewStore.getState();
    toggleTrade("t1", "BUY");
    expect(useDetailViewStore.getState().selectedBuys.has("t1")).toBe(true);
    toggleTrade("t1", "BUY");
    expect(useDetailViewStore.getState().selectedBuys.has("t1")).toBe(false);

    toggleTrade("t2", "SELL");
    expect(useDetailViewStore.getState().selectedSells.has("t2")).toBe(true);
  });

  it("clearSelection empties both buy/sell sets", () => {
    useDetailViewStore.setState({
      selectedBuys: new Set(["b1"]),
      selectedSells: new Set(["s1"]),
    });
    useDetailViewStore.getState().clearSelection();
    expect(useDetailViewStore.getState().selectedBuys.size).toBe(0);
    expect(useDetailViewStore.getState().selectedSells.size).toBe(0);
  });
});
```

- [ ] **Step 2: Run to verify the tests fail**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- detailView.test
```

Expected: FAIL — store still has old shape.

- [ ] **Step 3: Replace the store**

Replace `frontend/src/stores/detailView.ts`:

```ts
import { create } from "zustand";
import type {
  ViewType,
  IntradaySession,
  MinuteGranularity,
  MultidayWindow,
} from "../components/Positions/viewConfig";

/** Re-export for callers that previously imported from this module. */
export type { ViewType, IntradaySession as SessionMode, MinuteGranularity, MultidayWindow };

/** Ephemeral UI state for the position detail pane:
 *  - which symbol (if any) is open. Symbol — not ticker — because the
 *    same underlying ticker can have many distinct option contracts.
 *  - which 做T pair is highlighted on the chart (stocks only)
 *  - which trades are currently selected for the bind builder
 *  - which chart `view` is showing + per-view sub-config persisted
 *    independently so switching away and back restores the user's choice */
interface DetailViewState {
  selectedSymbol: string | null;
  activePairId: number | null;
  showAllPairs: boolean;

  /** Current chart tab. Maps via viewConfig.ts to (period, granularity, sessions). */
  view: ViewType;
  /** Sub-config for the `intraday` tab — persisted independently. */
  intradaySessions: IntradaySession;
  /** Sub-config for the `minute` tab — persisted independently. */
  minuteGranularity: MinuteGranularity;
  /** Sub-config for the `multiday` tab — persisted independently. */
  multidayWindow: MultidayWindow;

  selectedBuys: Set<string>;
  selectedSells: Set<string>;

  selectSymbol(symbol: string | null): void;
  setActivePair(id: number | null): void;
  setShowAllPairs(v: boolean): void;
  setView(v: ViewType): void;
  setIntradaySessions(s: IntradaySession): void;
  setMinuteGranularity(g: MinuteGranularity): void;
  setMultidayWindow(w: MultidayWindow): void;
  toggleTrade(tradeId: string, side: "BUY" | "SELL"): void;
  clearSelection(): void;
}

export const useDetailViewStore = create<DetailViewState>((set) => ({
  selectedSymbol: null,
  activePairId: null,
  showAllPairs: false,
  view: "intraday",
  intradaySessions: "regular",
  minuteGranularity: "5min",
  multidayWindow: 5,
  selectedBuys: new Set(),
  selectedSells: new Set(),

  selectSymbol: (symbol) =>
    set({
      selectedSymbol: symbol,
      activePairId: null,
      selectedBuys: new Set(),
      selectedSells: new Set(),
    }),
  setActivePair: (id) => set({ activePairId: id }),
  setShowAllPairs: (v) => set({ showAllPairs: v }),
  setView: (v) => set({ view: v }),
  setIntradaySessions: (s) => set({ intradaySessions: s }),
  setMinuteGranularity: (g) => set({ minuteGranularity: g }),
  setMultidayWindow: (w) => set({ multidayWindow: w }),
  toggleTrade: (tradeId, side) =>
    set((state) => {
      if (side === "BUY") {
        const next = new Set(state.selectedBuys);
        if (next.has(tradeId)) next.delete(tradeId);
        else next.add(tradeId);
        return { selectedBuys: next };
      } else {
        const next = new Set(state.selectedSells);
        if (next.has(tradeId)) next.delete(tradeId);
        else next.add(tradeId);
        return { selectedSells: next };
      }
    }),
  clearSelection: () =>
    set({ selectedBuys: new Set(), selectedSells: new Set() }),
}));
```

- [ ] **Step 4: Run the store test alone**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- detailView.test
```

Expected: PASS — all store tests green.

- [ ] **Step 5: Type-check (still expected to fail elsewhere — DetailPane / DetailChart pending)**

```bash
npm run typecheck
```

Expected: type errors only in `DetailPane.tsx / DetailChart.tsx / DetailChart.test.tsx / liveTick.ts`. **Do not commit yet** — wait until those are fixed too. Move to Task F1 next (liveTick is the smallest dependent and clears one block).

---

## Phase C — Live Tick Cleanup

### Task C1: Remove `liveConfig` from liveTick.ts (its job moved to viewConfig)

**Files:**
- Modify: `frontend/src/components/Positions/liveTick.ts`

- [ ] **Step 1: Delete the `liveConfig` function and `Period` import**

Replace `frontend/src/components/Positions/liveTick.ts`:

```ts
import type { Candlestick } from "../../api/domain-types";
import { fmtBjHM, parseUtc } from "./timeFmt";

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
```

(The change: removed the `import type { Period } from "../../stores/candlesticks"` line, the `Granularity` export, and the `liveConfig` function. Everything else is identical.)

- [ ] **Step 2: Verify the existing live-tick unit test still passes (if one exists)**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- liveTick
```

Expected: PASS — `applyLiveTick` and `bucketKey` signatures unchanged.

- [ ] **Step 3: Type-check — DetailChart still imports liveConfig, breaks here**

```bash
npm run typecheck
```

Expected: still failing in `DetailChart.tsx` (uses `liveConfig`). That's fixed in Task E5. Do not commit yet.

---

## Phase D — Tab Bar UI

### Task D1: Build the `TabPopover` component

**Files:**
- Create: `frontend/src/components/Positions/TabPopover.tsx`
- Create: `frontend/src/components/Positions/TabPopover.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Positions/TabPopover.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, act } from "@testing-library/react";
import { useRef } from "react";
import { TabPopover } from "./TabPopover";

function Host({ open, onClose }: { open: boolean; onClose: () => void }) {
  const anchorRef = useRef<HTMLButtonElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  return (
    <div ref={containerRef} style={{ position: "relative", width: 600, height: 300 }}>
      <button ref={anchorRef}>anchor</button>
      <TabPopover
        open={open}
        anchorRef={anchorRef}
        containerRef={containerRef}
        onClose={onClose}
      >
        <span data-testid="content">popover content</span>
      </TabPopover>
    </div>
  );
}

describe("TabPopover", () => {
  it("renders nothing when open=false", () => {
    const { queryByTestId } = render(<Host open={false} onClose={() => {}} />);
    expect(queryByTestId("content")).toBeNull();
  });

  it("renders children when open=true", () => {
    const { getByTestId } = render(<Host open={true} onClose={() => {}} />);
    expect(getByTestId("content")).toBeInTheDocument();
  });

  it("calls onClose when Escape is pressed", () => {
    const onClose = vi.fn();
    render(<Host open={true} onClose={onClose} />);
    act(() => {
      fireEvent.keyDown(document, { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when clicking outside the popover", () => {
    const onClose = vi.fn();
    const { container } = render(<Host open={true} onClose={onClose} />);
    // Click on a node that is neither the popover nor the anchor.
    const outside = container.firstChild as HTMLElement; // the container div itself
    act(() => {
      fireEvent.mouseDown(outside);
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onClose when clicking inside the popover", () => {
    const onClose = vi.fn();
    const { getByTestId } = render(<Host open={true} onClose={onClose} />);
    act(() => {
      fireEvent.mouseDown(getByTestId("content"));
    });
    expect(onClose).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify the tests fail**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- TabPopover.test
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `TabPopover`**

Create `frontend/src/components/Positions/TabPopover.tsx`:

```tsx
import { useEffect, useLayoutEffect, useRef, useState } from "react";

interface Props {
  open: boolean;
  /** The tab button (or any anchor element) the popover positions against. */
  anchorRef: React.RefObject<HTMLElement>;
  /** The chart-card element — popover stays inside its bounds. Provides the
   *  relative-positioning context as well, so this MUST be `position: relative`
   *  (or absolute) in CSS. */
  containerRef: React.RefObject<HTMLElement>;
  onClose(): void;
  children: React.ReactNode;
}

/**
 * Anchored dropdown used by DetailPane's popup-tabs (日内 / 分钟 / 多日).
 *
 * - Absolute-positioned inside `containerRef.current`.
 * - Top edge sits 6px below the anchor; left edge aligns to the anchor's left.
 * - If `left + popoverWidth > containerWidth - 4`, the popover shifts left so
 *   its right edge sticks at `containerWidth - 4`.
 * - Closes on Escape / click outside the popover (the anchor click is the
 *   parent's responsibility — clicking it again just toggles the parent's open
 *   state).
 *
 * The popover content is the caller's responsibility (typically a row of
 * `<button class="popover-pill">`).
 */
export function TabPopover({ open, anchorRef, containerRef, onClose, children }: Props) {
  const popRef = useRef<HTMLDivElement | null>(null);
  const [pos, setPos] = useState<{ left: number; top: number; caretLeft: number } | null>(null);

  // Position before paint so users never see the popover at (0,0) for a frame.
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const anchor = anchorRef.current;
    const container = containerRef.current;
    const pop = popRef.current;
    if (!anchor || !container || !pop) return;
    const a = anchor.getBoundingClientRect();
    const c = container.getBoundingClientRect();
    const popW = pop.offsetWidth || 160;
    const idealLeft = a.left - c.left;
    const maxLeft = c.width - popW - 4;
    const left = Math.min(Math.max(0, idealLeft), Math.max(0, maxLeft));
    const top = a.bottom - c.top + 6;
    // Caret stays anchored over the trigger even when popover shifts left.
    const caretLeft = a.left - c.left - left + a.width / 2 - 6;
    setPos({ left, top, caretLeft });
  }, [open, anchorRef, containerRef]);

  // Escape + click-outside dismissal.
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    function onDown(e: MouseEvent) {
      const pop = popRef.current;
      const anchor = anchorRef.current;
      const target = e.target as Node | null;
      if (!target) return;
      if (pop?.contains(target)) return;
      if (anchor?.contains(target)) return; // anchor toggles via its own onClick
      onClose();
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
    };
  }, [open, anchorRef, onClose]);

  if (!open) return null;

  return (
    <div
      ref={popRef}
      role="dialog"
      className="tab-popover"
      style={pos ? { left: pos.left, top: pos.top } : { visibility: "hidden" }}
    >
      {pos && (
        <span className="tab-popover-caret" style={{ left: pos.caretLeft }} aria-hidden />
      )}
      {children}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test -- TabPopover.test
```

Expected: PASS — all 5 tests green.

- [ ] **Step 5: Commit Phase B + C + D1 in one go**

(B4/B5/C1/D1 changes are all queued and depend on each other — we've been holding the commit until typecheck-clean. Skip if you committed earlier; otherwise:)

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/stores/candlesticks.ts \
        frontend/src/stores/detailView.ts \
        frontend/src/stores/detailView.test.ts \
        frontend/src/api/http.ts \
        frontend/src/components/Positions/liveTick.ts \
        frontend/src/components/Positions/TabPopover.tsx \
        frontend/src/components/Positions/TabPopover.test.tsx
# Note: do NOT commit yet — typecheck is still red (DetailPane / DetailChart).
# This commit happens at end of Phase E.
```

(Skip — this is just a checkpoint reminder. Real commit comes after Phase E1-E5.)

---

### Task D2: Add tab + popover CSS

**Files:**
- Modify: `frontend/src/components/Positions/Positions.css` (append)

- [ ] **Step 1: Locate the existing `.period-tabs` block**

```bash
grep -n "period-tabs\|today-dropdown\|subopt-group" /Users/tianpengxuan/Documents/signal-station/frontend/src/components/Positions/Positions.css | head -20
```

This finds the old tab styles. We'll add new ones; the old `.period-tabs / .today-dropdown / .subopt-group` block gets deleted in Task D3 (when `DetailPane.tsx` stops emitting them).

- [ ] **Step 2: Append new styles**

Append to `frontend/src/components/Positions/Positions.css`:

```css
/* Detail-chart tab bar — 7 flat tabs, 3 with anchored popovers. */
.chart-tabs {
  display: flex;
  gap: 2px;
  flex-wrap: nowrap;
}

.chart-tab {
  background: transparent;
  border: 1px solid transparent;
  color: var(--fg-2, #8a93a3);
  padding: 4px 9px;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: inherit;
  white-space: nowrap;
}
.chart-tab:hover { color: var(--fg-1, #d6dbe5); }
.chart-tab.active {
  color: var(--fg-1, #d6dbe5);
  background: rgba(90, 160, 255, 0.12);
  border-color: rgba(90, 160, 255, 0.32);
}
.chart-tab.popover-open {
  background: rgba(90, 160, 255, 0.22);
  border-color: rgba(90, 160, 255, 0.5);
  color: var(--fg-1, #d6dbe5);
}
.chart-tab .sub {
  color: #5aa0ff;
  font-size: 10px;
  opacity: 0.85;
}

/* Anchored popover used by 日内 / 分钟 / 多日 tabs. */
.tab-popover {
  position: absolute;
  z-index: 5;
  background: #0f1520;
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 6px;
  padding: 8px 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.tab-popover-caret {
  position: absolute;
  top: -6px;
  width: 0;
  height: 0;
  border-left: 6px solid transparent;
  border-right: 6px solid transparent;
  border-bottom: 6px solid rgba(255, 255, 255, 0.16);
}
.popover-pill {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--fg-2, #8a93a3);
  padding: 3px 9px;
  border-radius: 12px;
  font-size: 10px;
  white-space: nowrap;
  cursor: pointer;
  font-family: inherit;
}
.popover-pill:hover { color: var(--fg-1, #d6dbe5); }
.popover-pill.active {
  background: rgba(90, 160, 255, 0.16);
  border-color: rgba(90, 160, 255, 0.4);
  color: var(--fg-1, #d6dbe5);
}
```

(No test for CSS — visual verification in the dev-server smoke test at the end.)

- [ ] **Step 3: No commit yet**

CSS commit ships together with `DetailPane.tsx` in Task D3 since the old `.period-tabs / .today-dropdown / .subopt-group` block has to go in the same change.

---

### Task D3: Rewrite `DetailPane` tab bar + fetch effect

**Files:**
- Modify: `frontend/src/components/Positions/DetailPane.tsx`
- Modify: `frontend/src/components/Positions/Positions.css` (delete old `.period-tabs / .today-dropdown / .subopt-group` block)

This is the largest single edit. Read the existing `DetailPane.tsx` thoroughly first — most logic (trade fetching, pair fetching, confirm dialogs, etc.) is unchanged. Only the period tabs UI and the candlesticks fetch effect change.

- [ ] **Step 1: Replace imports + state hooks**

At the top of `frontend/src/components/Positions/DetailPane.tsx`, find:

```ts
import { useCandlesticksStore, candleCacheKey, type Period } from "../../stores/candlesticks";
```

Replace with:

```ts
import { useCandlesticksStore, candleCacheKey } from "../../stores/candlesticks";
import { resolveViewConfig, type ViewType } from "./viewConfig";
import { TabPopover } from "./TabPopover";
```

Then find the existing detail-view selectors (around lines 79-89). Replace:

```ts
const period = useDetailViewStore((s) => s.period);
const setPeriod = useDetailViewStore((s) => s.setPeriod);
const todayGranularity = useDetailViewStore((s) => s.todayGranularity);
const setTodayGranularity = useDetailViewStore((s) => s.setTodayGranularity);
const todaySessions = useDetailViewStore((s) => s.todaySessions);
const setTodaySessions = useDetailViewStore((s) => s.setTodaySessions);
```

with:

```ts
const view = useDetailViewStore((s) => s.view);
const setView = useDetailViewStore((s) => s.setView);
const intradaySessions = useDetailViewStore((s) => s.intradaySessions);
const setIntradaySessions = useDetailViewStore((s) => s.setIntradaySessions);
const minuteGranularity = useDetailViewStore((s) => s.minuteGranularity);
const setMinuteGranularity = useDetailViewStore((s) => s.setMinuteGranularity);
const multidayWindow = useDetailViewStore((s) => s.multidayWindow);
const setMultidayWindow = useDetailViewStore((s) => s.setMultidayWindow);

const viewCfg = resolveViewConfig(view, {
  intradaySessions, minuteGranularity, multidayWindow,
});
```

- [ ] **Step 2: Replace the `PERIODS` constant and the `barsKey` derivation**

Delete this block (around lines 48-56):

```ts
const PERIODS: { id: Period; label: string }[] = [
  { id: "today", label: "日内" },
  ...
];
```

Replace with:

```ts
const TABS: Array<{ view: ViewType; label: string; hasPopover: boolean }> = [
  { view: "intraday", label: "日内",  hasPopover: true },
  { view: "minute",   label: "分钟",  hasPopover: true },
  { view: "multiday", label: "多日",  hasPopover: true },
  { view: "day",      label: "日K",   hasPopover: false },
  { view: "week",     label: "周K",   hasPopover: false },
  { view: "month",    label: "月K",   hasPopover: false },
  { view: "year",     label: "年K",   hasPopover: false },
];

function subLabel(view: ViewType, sessions: string, granularity: string, window: number): string | null {
  if (view === "intraday") {
    return sessions === "regular" ? "盘中"
         : sessions === "pre" ? "盘前"
         : sessions === "post" ? "盘后"
         : sessions === "overnight" ? "夜盘"
         : "全部";
  }
  if (view === "minute") return granularity;
  if (view === "multiday") return `${window}日`;
  return null;
}
```

Find the existing `barsKey` line (~line 103):

```ts
const barsKey = candleCacheKey(symbol, period, todayGranularity, todaySessions);
```

Replace with:

```ts
const barsKey = candleCacheKey(symbol, viewCfg.period, viewCfg.granularity, viewCfg.sessions);
```

- [ ] **Step 3: Replace the candlesticks fetch effect**

Find the effect that starts `useEffect(() => { ... api.candlesticks(...` (around lines 240-261). Replace its body:

```ts
useEffect(() => {
  let alive = true;
  // For `today`, granularity + sessions are sent; for other periods they're ignored.
  const opts = viewCfg.period === "today"
    ? { granularity: viewCfg.granularity, sessions: viewCfg.sessions }
    : {};
  const key = candleCacheKey(symbol, viewCfg.period, viewCfg.granularity, viewCfg.sessions);
  api.candlesticks(symbol, viewCfg.period, opts)
    .then((r) => {
      if (!alive) return;
      setBars(key, r);
    })
    .catch((e) => console.warn("candlesticks fetch failed", e))
    .finally(() => {
      if (alive) setFetchedBarsKey(key);
    });
  return () => { alive = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [symbol, view, intradaySessions, minuteGranularity, multidayWindow, setBars]);
```

(The deps reshape is the important change — fetch refires on any of the 4 fields, just as the old code fired on `period/todayGranularity/todaySessions`.)

- [ ] **Step 4: Replace the chart-header tab/popover UI**

Find the `<div className="detail-chart-card">` block (~lines 443-563). Replace the `<div className="detail-chart-head">` section AND delete the entire `{period === "today" && todayDropdownOpen && ( ... )}` inline-dropdown block. Replace with:

```tsx
<div className="detail-chart-card">
  <DetailChartHead
    view={view}
    setView={setView}
    intradaySessions={intradaySessions}
    setIntradaySessions={setIntradaySessions}
    minuteGranularity={minuteGranularity}
    setMinuteGranularity={setMinuteGranularity}
    multidayWindow={multidayWindow}
    setMultidayWindow={setMultidayWindow}
    showAvgCost={showAvgCost}
    setShowAvgCost={setShowAvgCost}
  />
  <div className="detail-chart-wrap">
    {bars && bars.bars.length > 0 && tradesInitialized && pairsInitialized && barsInitialized ? (
      <DetailChart
        symbol={symbol}
        bars={bars.bars}
        view={view}
        viewCfg={viewCfg}
        trades={trades}
        avgCost={position.avg_cost}
        showAvgCost={showAvgCost}
      />
    ) : (
      <div className="empty-pat" style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
        {barsInitialized && bars && bars.bars.length === 0 ? "暂无 K 线数据" : "加载中..."}
      </div>
    )}
  </div>
</div>
```

Delete the now-unused `todayDropdownOpen` `useState` (`const [todayDropdownOpen, setTodayDropdownOpen] = useState(false);` and any references).

- [ ] **Step 5: Add the `DetailChartHead` inner component**

Just above the `export function DetailPane(...)` declaration, add a new component:

```tsx
interface HeadProps {
  view: ViewType;
  setView(v: ViewType): void;
  intradaySessions: import("./viewConfig").IntradaySession;
  setIntradaySessions(s: import("./viewConfig").IntradaySession): void;
  minuteGranularity: import("./viewConfig").MinuteGranularity;
  setMinuteGranularity(g: import("./viewConfig").MinuteGranularity): void;
  multidayWindow: import("./viewConfig").MultidayWindow;
  setMultidayWindow(w: import("./viewConfig").MultidayWindow): void;
  showAvgCost: boolean;
  setShowAvgCost(v: boolean): void;
}

function DetailChartHead(props: HeadProps) {
  const {
    view, setView,
    intradaySessions, setIntradaySessions,
    minuteGranularity, setMinuteGranularity,
    multidayWindow, setMultidayWindow,
    showAvgCost, setShowAvgCost,
  } = props;

  const containerRef = useRef<HTMLDivElement | null>(null);
  // Refs for the 3 popover-tab buttons (anchors).
  const intradayAnchor = useRef<HTMLButtonElement | null>(null);
  const minuteAnchor = useRef<HTMLButtonElement | null>(null);
  const multidayAnchor = useRef<HTMLButtonElement | null>(null);
  const [openPopover, setOpenPopover] = useState<null | "intraday" | "minute" | "multiday">(null);

  const anchorOf = (v: ViewType) =>
    v === "intraday" ? intradayAnchor
    : v === "minute" ? minuteAnchor
    : v === "multiday" ? multidayAnchor
    : intradayAnchor;

  return (
    <div className="detail-chart-head" ref={containerRef}>
      <div className="legend-row">
        <h4>价格</h4>
        <div className="legend">
          <span className="it"><span className="glyph buy">▲</span>买入</span>
          <span className="it"><span className="glyph sell">▼</span>卖出</span>
          <button
            className={`toggle-mini ${showAvgCost ? "on" : ""}`}
            onClick={() => setShowAvgCost(!showAvgCost)}
            title="显示/隐藏成本均价参考线"
          >
            <span className="glyph avg" />成本{showAvgCost ? "" : " · 隐藏"}
          </button>
        </div>
      </div>
      <div className="chart-tabs">
        {TABS.map((t) => {
          const isActive = view === t.view;
          // Every popover-tab carries its own sub-value as a quiet suffix
          // (regardless of which tab is active) so the user can see what
          // each popover-tab will switch to before clicking.
          const ownSub =
            t.view === "intraday" ? subLabel("intraday", intradaySessions, "", 0)
            : t.view === "minute" ? subLabel("minute", "", minuteGranularity, 0)
            : t.view === "multiday" ? subLabel("multiday", "", "", multidayWindow)
            : null;
          const popoverOpen = openPopover === t.view;
          return (
            <button
              key={t.view}
              ref={t.view === "intraday" ? intradayAnchor : t.view === "minute" ? minuteAnchor : t.view === "multiday" ? multidayAnchor : undefined}
              className={`chart-tab ${isActive ? "active" : ""} ${popoverOpen ? "popover-open" : ""}`}
              onClick={() => {
                if (!isActive) {
                  setView(t.view);
                  setOpenPopover(null);
                  return;
                }
                if (t.hasPopover) {
                  setOpenPopover((cur) => (cur === t.view ? null : (t.view as "intraday" | "minute" | "multiday")));
                } else {
                  setOpenPopover(null);
                }
              }}
            >
              <span>{t.label}</span>
              {ownSub && <span className="sub">{ownSub}</span>}
            </button>
          );
        })}
      </div>

      {/* 日内 popover — sessions */}
      <TabPopover
        open={openPopover === "intraday"}
        anchorRef={intradayAnchor}
        containerRef={containerRef}
        onClose={() => setOpenPopover(null)}
      >
        {(["regular", "pre", "post", "overnight", "all"] as const).map((s) => (
          <button
            key={s}
            className={`popover-pill ${intradaySessions === s ? "active" : ""}`}
            onClick={() => { setIntradaySessions(s); setOpenPopover(null); }}
          >
            {s === "regular" ? "盘中" : s === "pre" ? "盘前" : s === "post" ? "盘后" : s === "overnight" ? "夜盘" : "全部"}
          </button>
        ))}
      </TabPopover>

      {/* 分钟 popover — granularity */}
      <TabPopover
        open={openPopover === "minute"}
        anchorRef={minuteAnchor}
        containerRef={containerRef}
        onClose={() => setOpenPopover(null)}
      >
        {(["1min", "2min", "3min", "5min"] as const).map((g) => (
          <button
            key={g}
            className={`popover-pill ${minuteGranularity === g ? "active" : ""}`}
            onClick={() => { setMinuteGranularity(g); setOpenPopover(null); }}
          >{g}</button>
        ))}
      </TabPopover>

      {/* 多日 popover — window */}
      <TabPopover
        open={openPopover === "multiday"}
        anchorRef={multidayAnchor}
        containerRef={containerRef}
        onClose={() => setOpenPopover(null)}
      >
        {([5, 7] as const).map((w) => (
          <button
            key={w}
            className={`popover-pill ${multidayWindow === w ? "active" : ""}`}
            onClick={() => { setMultidayWindow(w); setOpenPopover(null); }}
          >{w}日</button>
        ))}
      </TabPopover>
    </div>
  );
}
```

Add the missing `useRef, useState` imports to the top of the file if they aren't already there (they are — `useState/useCallback/useEffect/useRef` were all imported originally; verify).

- [ ] **Step 6: Delete the obsolete CSS blocks**

In `frontend/src/components/Positions/Positions.css`, delete:
- The `.period-tabs` block (and any descendant selectors like `.period-tabs .p`, `.period-tabs .p.active`, `.period-tabs .caret`).
- The `.today-dropdown` block (and any descendant selectors).
- The `.subopt-group` block (and any descendant selectors like `.subopt-group .lbl`, `.subopt-group .pill`).

Use `grep -n` to find their bounds before deleting, e.g.:

```bash
grep -n "^.period-tabs\|^.today-dropdown\|^.subopt-group" frontend/src/components/Positions/Positions.css
```

- [ ] **Step 7: Type-check — should be clean now if DetailChart props alignment is done**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run typecheck
```

Expected: still FAILS — `DetailChart` is invoked with the new `view` / `viewCfg` props in DetailPane but its signature still takes the old `period / todayGranularity / todaySessions`. That gets fixed in Phase E. Do not commit yet.

---

## Phase E — DetailChart Renderer Rewrite

### Task E1: Update `DetailChart` props + structural Effect A deps

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx`

- [ ] **Step 1: Update the props interface**

In `frontend/src/components/Positions/DetailChart.tsx`, find the `interface Props { ... }` block (around lines 75-88). Replace:

```ts
interface Props {
  symbol: string;
  bars: Candlestick[];
  period: Period;
  trades: Trade[];
  avgCost: number | null;
  showAvgCost: boolean;
  todayGranularity: "分时" | "1min" | "2min" | "3min" | "5min";
  todaySessions: "regular" | "pre" | "post" | "overnight" | "all";
}
```

With:

```ts
import type { ViewType, ViewConfig } from "./viewConfig";

interface Props {
  symbol: string;
  bars: Candlestick[];
  view: ViewType;
  viewCfg: ViewConfig;
  trades: Trade[];
  avgCost: number | null;
  showAvgCost: boolean;
}
```

Update the `export function DetailChart({...})` destructure:

```tsx
export function DetailChart({
  symbol, bars, view, viewCfg, trades, avgCost, showAvgCost,
}: Props) {
```

Delete the `import type { Period } from "../../stores/candlesticks";` line at the top (no longer used directly).

Delete the `import { liveConfig } from "./liveTick";` and any other liveTick imports except `applyLiveTick, bucketKey`. Keep:

```ts
import { applyLiveTick, bucketKey } from "./liveTick";
```

- [ ] **Step 2: Replace `visibleBars` / `visibleTrades` computation to use `view`**

Find the `useMemo` block computing `visibleBars` (~lines 142-158). Replace `period !== "today"` with `view !== "intraday" && view !== "minute"`, and replace references to `todayGranularity / todaySessions`:

```ts
const visibleBars: Candlestick[] = useMemo(() => {
  // 分时 (intraday view) is the only mode that needs session padding/trim.
  if (view !== "intraday") return bars;
  const today = currentTradingDay();
  const trimmed = bars.filter((b) => {
    if (!b.timestamp) return false;
    if (tradingDayOfET(b.timestamp) !== today) return false;
    if (viewCfg.sessions === "all") return true;
    if (viewCfg.sessions === "regular") return classifyETSession(b.timestamp) === "regular";
    return classifyETSession(b.timestamp) === viewCfg.sessions;
  });
  return buildSessionSlots(trimmed, "分时", viewCfg.sessions ?? "regular");
}, [bars, view, viewCfg.sessions]);

const visibleTrades: Trade[] = useMemo(() => {
  if (view !== "intraday") return trades;
  const today = currentTradingDay();
  return trades.filter((t) => {
    if (tradingDayOfET(t.ts) !== today) return false;
    if (viewCfg.sessions === "all") return true;
    if (viewCfg.sessions === "regular") return classifyETSession(t.ts) === "regular";
    return classifyETSession(t.ts) === viewCfg.sessions;
  });
}, [trades, view, viewCfg.sessions]);
```

The 分钟 view doesn't filter — it renders today's bars verbatim (the backend returns regular-session minutes only because sessions="regular" is fixed for that view).

- [ ] **Step 3: Update `markers` snap-tolerance to use `view`**

Find the `markers` `useMemo` (~lines 170-191). Replace the `isIntradayPeriod` line:

```ts
const isIntradayPeriod =
  view === "intraday" || view === "minute" || view === "multiday";
const tolerance = isIntradayPeriod ? 60 * 60 * 1000 : 12 * 3600 * 1000;
```

For candlestick views (day/week/month/year), `m.x` will need to become a timestamp rather than a bar index. See Task E3 for the x-axis-type branch. For now the markers still snap by index — the index→timestamp transform happens at dataset-build time inside Task E3.

- [ ] **Step 4: Update `chartData.labels` for K-line views**

Find the `chartData` `useMemo` (~lines 193-207). Replace the labels build:

```ts
const chartData = useMemo(() => {
  const labels = visibleBars.map((b) => {
    if (!b.timestamp) return "";
    if (view === "intraday" || view === "minute") return fmtBjHM(b.timestamp);
    if (view === "multiday") return `${fmtBjDate(b.timestamp)} ${fmtBjHM(b.timestamp)}`;
    if (view === "day") return fmtBjDate(b.timestamp);
    if (view === "week") return fmtBjWeekISO(b.timestamp);
    if (view === "month") return fmtBjMonth(b.timestamp);
    if (view === "year") return fmtBjYear(b.timestamp);
    return fmtBjDate(b.timestamp);
  });
  const closes = visibleBars.map((b) => b.close);
  const buys = markers.filter((m) => m.raw.side === "BUY");
  const sells = markers.filter((m) => m.raw.side === "SELL");
  return { labels, closes, buys, sells };
}, [visibleBars, view, markers]);
```

Add to the imports at the top: `fmtBjWeekISO, fmtBjMonth, fmtBjYear`.

- [ ] **Step 5: Update Effect A deps**

Find the chart-create `useEffect(() => { ... return () => { chartRef.current?.destroy(); ... }; }, [symbol, period, todayGranularity, todaySessions, colorMode]);` block.

Replace the dep array:

```ts
}, [symbol, view, viewCfg.granularity, viewCfg.sessions, viewCfg.datasetType, colorMode]);
```

(Including `datasetType` ensures we rebuild on a view switch that changes line↔candlestick. Sub-state for 分钟/多日/intraday all participates through `granularity / sessions`; the `multiday` window swap shows up as a `period` change which triggers a fresh fetch and a fresh bars reference — so we don't need `multidayWindow` here.)

- [ ] **Step 6: Update `INITIAL_VISIBLE_COUNT`**

Find the `INITIAL_VISIBLE_COUNT` `Record<Period, number>` declaration in Effect A's body. Replace:

```ts
const initialCount = Number.isFinite(viewCfg.initialVisibleCount)
  ? Math.min(viewCfg.initialVisibleCount, data.closes.length)
  : data.closes.length;
```

(Delete the old `INITIAL_VISIBLE_COUNT: Record<Period, number> = {...}` literal entirely.)

- [ ] **Step 7: Update `sessionBg` plugin gating**

Find the `sessionBg: { enabled: ..., granularity: ..., barCount: ..., session: ... }` block in Effect A's `plugins` config. Replace:

```ts
sessionBg: {
  enabled: viewCfg.sessionBgEnabled
    && (viewCfg.sessions === "all" || viewCfg.sessions === "regular" /* same single-label behavior as before */),
  granularity: "分时" as const,
  barCount: data.closes.length,
  session: (viewCfg.sessions ?? "regular"),
},
```

Wait — the old code enabled sessionBg for ALL today views when `granularity==="分时"` OR `sessions==="all"`. The new spec says sessionBg is intraday-view only. So simplify:

```ts
sessionBg: {
  enabled: viewCfg.sessionBgEnabled,
  granularity: "分时" as const,
  barCount: data.closes.length,
  session: viewCfg.sessions ?? "regular",
},
```

`viewCfg.sessionBgEnabled` is true only for `view === "intraday"` per Task B3.

- [ ] **Step 8: Update Effect B's `sessionBg.barCount` write**

Find Effect B (mutate-in-place). The line `opts.plugins.sessionBg.barCount = data.closes.length;` stays as-is, but make sure the surrounding code still works after the dataset shape shift in E2/E3. (It does — Effect B writes the prim/scatter dataset data references by label, which is robust to candlestick mixed in.)

(No commit here yet — keep going through Phase E.)

---

### Task E2: Dataset dispatch — line vs candlestick

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx` (Effect A inner `cfg` build)

- [ ] **Step 1: Branch the price dataset on `viewCfg.datasetType`**

Inside Effect A, find the first dataset entry in `datasets: [...]` — the one labeled `"成交价"` with `type: "line"`. Replace it with a branched build:

```ts
const priceDataset = viewCfg.datasetType === "candlestick"
  ? ({
      label: "成交价",
      type: "candlestick" as const,
      data: visibleBars.map((b) => ({
        // x is the bar index in label-array order, like the line view; the
        // candlestick plugin reads (o, h, l, c) for the body shape.
        x: visibleBars.indexOf(b),
        o: b.open, h: b.high, l: b.low, c: b.close,
      })),
      borderColor: {
        up: cssVar("--up-color", "#3dd68c"),
        down: cssVar("--down-color", "#ef5b5b"),
        unchanged: C.fg3,
      } as unknown as string,
      backgroundColor: {
        up: cssVar("--up-color", "#3dd68c"),
        down: cssVar("--down-color", "#ef5b5b"),
        unchanged: C.fg3,
      } as unknown as string,
      borderWidth: 1,
      barPercentage: 0.9,
      categoryPercentage: 0.95,
      order: 4,
      parsing: false as const,
    } as ChartConfiguration["data"]["datasets"][number])
  : ({
      label: "成交价",
      data: data.closes,
      borderColor: C.price,
      backgroundColor: (ctx: ScriptableContext<"line">) => {
        const area = ctx.chart.chartArea;
        if (!area) return "transparent";
        const grad = ctx.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
        grad.addColorStop(0, C.priceFill);
        grad.addColorStop(1, "rgba(0,0,0,0)");
        return grad;
      },
      borderWidth: 1.6, fill: true, tension: 0.26,
      pointRadius: 0, pointHoverRadius: 0,
      order: 4,
    } as ChartConfiguration["data"]["datasets"][number]);
```

Replace the explicit `{ label: "成交价", data: data.closes, ... }` entry in `datasets:` with `priceDataset`:

```ts
datasets: [
  priceDataset,
  ...(initialAvgCost != null && initialShowAvgCost ? [{ ...avg cost dataset... }] : []),
  { label: "买入", ... },
  { label: "卖出", ... },
],
```

- [ ] **Step 2: Update tooltip callback to handle candlestick parsed shape**

Find the tooltip `callbacks.label` callback (~lines 345-353). Replace:

```ts
label: (item) => {
  const ds = item.dataset as { type?: string; label?: string };
  if (ds.type === "scatter") {
    const raw = (item.raw as { raw?: Trade }).raw;
    if (!raw) return "";
    return ` ${fmtN(raw.qty, 0)} 股 @ $${fmtN(raw.price)}${raw.tag ? "  · " + raw.tag : ""}`;
  }
  if (ds.type === "candlestick") {
    const ohlc = item.raw as { o: number; h: number; l: number; c: number };
    return [
      ` 开 $${fmtN(ohlc.o)}`,
      ` 高 $${fmtN(ohlc.h)}`,
      ` 低 $${fmtN(ohlc.l)}`,
      ` 收 $${fmtN(ohlc.c)}`,
    ];
  }
  return ` 价格 $${fmtN(item.parsed.y as number)}`;
},
```

- [ ] **Step 3: Verify tooltip `filter` still passes candlestick items**

Find the tooltip `filter:` line (~lines 325-328):

```ts
filter: (item) => {
  const ds = item.dataset as { type?: string; label?: string };
  return ds.label === "成交价" || ds.type === "scatter";
},
```

This already passes candlestick (because `label === "成交价"`). No change needed.

- [ ] **Step 4: No commit yet, continue to E3**

---

### Task E3: Update y-axis fit + scatter snap for candlestick range

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx`

- [ ] **Step 1: Update `afterDataLimits` to consider candle highs/lows**

Find `afterDataLimits: (scale) => { ... }` in the y-scale config (~lines 399-429). The current code reads from `closes[]` only. For candlestick views, the bar's range is `[low, high]`, not just `close`. Replace the inner loop:

```ts
afterDataLimits: (scale) => {
  const xScale = scale.chart.scales.x;
  if (!xScale || xScale.min == null || xScale.max == null) return;
  const xLo = Math.max(0, Math.floor(xScale.min as number));
  const xHi = Math.min(visibleBarsRef.current.length - 1, Math.ceil(xScale.max as number));
  let vMin = Infinity, vMax = -Infinity;
  for (let i = xLo; i <= xHi; i++) {
    const b = visibleBarsRef.current[i];
    if (!b) continue;
    if (viewCfg.datasetType === "candlestick") {
      if (b.low < vMin) vMin = b.low;
      if (b.high > vMax) vMax = b.high;
    } else {
      if (b.close < vMin) vMin = b.close;
      if (b.close > vMax) vMax = b.close;
    }
  }
  for (const m of markersRef.current) {
    if (m.x >= xLo && m.x <= xHi) {
      if (m.y < vMin) vMin = m.y;
      if (m.y > vMax) vMax = m.y;
    }
  }
  const avgRef = avgCostRef.current;
  if (showAvgCostRef.current && avgRef != null) {
    if (avgRef < vMin) vMin = avgRef;
    if (avgRef > vMax) vMax = avgRef;
  }
  if (vMin === Infinity) return;
  const pad = (vMax - vMin) * 0.06 || Math.abs(vMax) * 0.005 || 0.5;
  scale.min = vMin - pad;
  scale.max = vMax + pad;
},
```

(Closure capture of `viewCfg.datasetType` — since Effect A only re-runs on `datasetType` change, this stays correct between rebuilds.)

- [ ] **Step 2: Verify scatter `m.x` integer index still works on candle x-scale**

Candlestick controller still uses a `category` scale when bound to `labels:`, so `m.x = bar index` continues to work the same as on line view. No change needed.

(If you discover at smoke-test time that markers don't appear on candle views, swap `m.x` to `Date.parse(t.ts)` and set `scales.x.type = "time"` for candle views. Probably not needed.)

- [ ] **Step 3: No commit yet, continue to E4**

---

### Task E4: Add multiday day-separator inline plugin

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx` (small inline plugin)

- [ ] **Step 1: Add the plugin definition**

Near the top of `DetailChart.tsx` (after the existing `sessionBgPlugin / crosshairPlugin / minMaxLabelsPlugin` imports), add an inline plugin:

```ts
import type { Plugin } from "chart.js";

/** Vertical guide lines at every trading-day boundary in `bars[]`. Only
 *  drawn when `viewCfg.dayMarkersEnabled` is true (multiday view). */
const dayMarkersPlugin: Plugin<"line" | "candlestick"> = {
  id: "dayMarkers",
  afterDraw(chart, _args, opts) {
    const { enabled, bars } = opts as { enabled: boolean; bars: Candlestick[] };
    if (!enabled || !bars || bars.length === 0) return;
    const ctx = chart.ctx;
    const xs = chart.scales.x;
    const ys = chart.scales.y;
    if (!xs || !ys) return;
    let prevDay: string | null = null;
    ctx.save();
    ctx.strokeStyle = "rgba(255,255,255,0.08)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    for (let i = 0; i < bars.length; i++) {
      const b = bars[i]!;
      if (!b.timestamp) continue;
      const day = tradingDayOfET(b.timestamp);
      if (prevDay !== null && day !== prevDay) {
        const x = xs.getPixelForValue(i);
        if (Number.isFinite(x)) {
          ctx.beginPath();
          ctx.moveTo(x, ys.top);
          ctx.lineTo(x, ys.bottom);
          ctx.stroke();
        }
      }
      prevDay = day;
    }
    ctx.restore();
  },
};
```

(The plugin gets a `Candlestick[]` reference via options each render — Chart.js calls `afterDraw` with the latest options.)

- [ ] **Step 2: Register the plugin in the chart `plugins: [...]` array**

In Effect A's `cfg.plugins` array, add it:

```ts
plugins: [sessionBgPlugin, crosshairPlugin, minMaxLabelsPlugin, dayMarkersPlugin],
```

- [ ] **Step 3: Configure the plugin via `options.plugins.dayMarkers`**

Add to the `options.plugins` object (next to `sessionBg`):

```ts
dayMarkers: {
  enabled: viewCfg.dayMarkersEnabled,
  bars: visibleBars,
},
```

And in Effect B (mutate-in-place), update its `bars` reference when bars change:

```ts
const opts2 = chart.options as unknown as {
  plugins: { sessionBg: { barCount: number }; dayMarkers: { bars: Candlestick[] }; zoom: { limits: { x: { max: number } } } };
};
opts2.plugins.dayMarkers.bars = visibleBars;
```

(Append this near the existing Effect B end-of-block writes.)

---

### Task E5: Effect C live-tick remap

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx`

- [ ] **Step 1: Replace the `liveCfg / isLiveMode` derivation**

Find:

```ts
const liveCfg = liveConfig(period, todayGranularity);
const isLiveMode = liveCfg != null;
```

Replace with:

```ts
const liveCfg = viewCfg.liveCfg;
const isLiveMode = liveCfg != null;
```

- [ ] **Step 2: Update Effect C's dep array**

Find the live-tick effect's closing `}, [period, todayGranularity, symbol]);`. Replace with:

```ts
}, [view, viewCfg.granularity, symbol]);
```

(intraday/minute live both depend on granularity choices; multiday is fixed at 5min so it doesn't need its own dep — view change covers it.)

- [ ] **Step 3: Update the zoom-reset effect**

Find `useEffect(() => { setIsZoomed(false); }, [period]);`. Replace with `[view]`.

- [ ] **Step 4: Type-check — should be clean now**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run typecheck
```

Expected: PASS — all the period→view ripples are resolved.

- [ ] **Step 5: Update `DetailChart.test.tsx` for the new prop shape**

Replace `frontend/src/components/Positions/DetailChart.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, act } from "@testing-library/react";

vi.mock("chartjs-plugin-zoom");

vi.mock("chart.js", () => {
  type ChartStub = {
    destroy: () => void;
    update: () => void;
    data: { labels: unknown[]; datasets: Array<{ label: string; data: unknown[] }> };
    options: {
      scales: { x: { max: number; min: number } };
      plugins: {
        sessionBg: { barCount: number };
        dayMarkers: { bars: unknown[] };
        zoom: { limits: { x: { max: number } } };
      };
    };
    scales: { x: { max: number; min: number } };
  };
  function ChartCtor(this: ChartStub) {
    this.destroy = vi.fn();
    this.update = vi.fn();
    this.data = {
      labels: [],
      datasets: [{ label: "price", data: [] }],
    };
    this.options = {
      scales: { x: { max: 0, min: 0 } },
      plugins: {
        sessionBg: { barCount: 0 },
        dayMarkers: { bars: [] },
        zoom: { limits: { x: { max: 0 } } },
      },
    };
    this.scales = { x: { max: 0, min: 0 } };
  }
  const Chart = ChartCtor as unknown as { new (): ChartStub; register: (...args: unknown[]) => void };
  Chart.register = vi.fn();
  return {
    Chart,
    LineController: {}, ScatterController: {},
    LineElement: {}, PointElement: {},
    LinearScale: {}, CategoryScale: {},
    Filler: {}, Tooltip: { positioners: {} },
  };
});

// chartjs-chart-financial controllers also need stubbing for the import to resolve.
vi.mock("chartjs-chart-financial", () => ({
  CandlestickController: {}, CandlestickElement: {},
  OhlcController: {}, OhlcElement: {},
}));

import { DetailChart } from "./DetailChart";
import { useQuotesStore } from "../../stores/quotes";
import { resolveViewConfig, type ViewType } from "./viewConfig";
import type { Candlestick } from "../../api/domain-types";

beforeEach(() => {
  (HTMLCanvasElement.prototype as unknown as { getContext: () => null }).getContext = () => null;
  useQuotesStore.getState().reset();
});

const bars: Candlestick[] = [
  { timestamp: "2026-05-15T13:30:00Z", open: 100, high: 100, low: 100, close: 100, volume: 0, turnover: 0 },
  { timestamp: "2026-05-15T13:31:00Z", open: 100, high: 101, low: 99, close: 101, volume: 0, turnover: 0 },
];

function renderView(view: ViewType, subOverrides: Partial<Parameters<typeof resolveViewConfig>[1]> = {}) {
  const sub = {
    intradaySessions: "regular" as const,
    minuteGranularity: "5min" as const,
    multidayWindow: 5 as const,
    ...subOverrides,
  };
  const cfg = resolveViewConfig(view, sub);
  return render(
    <DetailChart
      symbol="TSLA.US"
      bars={bars}
      view={view}
      viewCfg={cfg}
      trades={[]}
      avgCost={null}
      showAvgCost={false}
    />,
  );
}

describe("DetailChart live-mode wiring", () => {
  it.each([
    ["intraday"],
    ["minute"],
    ["multiday"],
  ] as const)("renders .live-pulse for live view (%s)", (view) => {
    const { container } = renderView(view);
    expect(container.querySelector(".live-pulse")).not.toBeNull();
  });

  it.each([
    ["day"],
    ["week"],
    ["month"],
    ["year"],
  ] as const)("omits .live-pulse for non-live view (%s)", (view) => {
    const { container } = renderView(view);
    expect(container.querySelector(".live-pulse")).toBeNull();
  });

  it("survives a quote upsert in live mode without throwing", () => {
    renderView("intraday");
    expect(() => {
      act(() => {
        useQuotesStore.getState().upsertQuote("TSLA.US", {
          last_done: 102, prev_close: 100, today_close: null,
          open: 100, high: 102, low: 99,
          volume: 0, turnover: 0,
          change: 2, change_pct: 2,
          trade_session: "regular",
        });
      });
    }).not.toThrow();
  });

  it("survives quote upserts across all non-live views too", () => {
    for (const view of ["day", "week", "month", "year"] as const) {
      const { unmount } = renderView(view);
      expect(() => {
        act(() => {
          useQuotesStore.getState().upsertQuote("TSLA.US", {
            last_done: 105, prev_close: 100, today_close: null,
            open: 100, high: 105, low: 99,
            volume: 0, turnover: 0,
            change: 5, change_pct: 5,
            trade_session: "regular",
          });
        });
      }).not.toThrow();
      unmount();
    }
  });
});
```

- [ ] **Step 6: Run all frontend tests**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test
```

Expected: PASS — all 4 modified/new test files green; no regressions in the other Positions tests (`PositionsPanel.test.tsx`, `IntradaySpark.test.tsx`, `sessionWindow.test.ts`, `PositionCard.test.tsx`).

- [ ] **Step 7: Type-check one more time**

```bash
npm run typecheck
```

Expected: PASS.

- [ ] **Step 8: Commit the entire frontend rewrite as one atomic change**

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/
git commit -m "$(cat <<'EOF'
refactor(detail-chart): 7-tab + popover + candlestick K-line views

- 替换 period/todayGranularity/todaySessions 三元组为 ViewType discriminator
- 新增 viewConfig.ts 单一映射: view → 后端 period + 渲染配置 + live 配置
- 新增 TabPopover 可复用锚定下拉组件 (Esc / click-outside 关闭)
- DetailPane 顶部 tab 栏改为 7 平铺: [日内][分钟][多日][日K][周K][月K][年K]
  其中前 3 通过 popover 选子配置, 后 4 直接切换
- DetailChart 引入 chartjs-chart-financial, 按 viewCfg.datasetType 分发
  渲染 line vs candlestick
- 蜡烛图 y-axis 用 bar.high/low 计算合理范围, tooltip 显示 OHLC
- 多日 view 新增日分割线 dayMarkersPlugin
- sessionBg 仅 intraday view 启用
- 删除 liveTick.liveConfig (并入 viewConfig.liveCfg)
- 删除 .period-tabs/.today-dropdown/.subopt-group 旧样式

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase F — Smoke + Polish

### Task F1: Dev-server visual smoke test

**Files:** none

- [ ] **Step 1: Start the backend dev server**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend
uv run uvicorn app.api.main:app --reload --port 8000
```

- [ ] **Step 2: Start the frontend dev server**

In a separate terminal:

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run dev
```

- [ ] **Step 3: Walk through each tab in the browser**

Open the dev URL printed by Vite. Click a stock card to open the detail pane, then verify:

| Tab | Verification |
|---|---|
| 日内 | Default opens with `盘中` session. Click tab → no popover. Click again → popover shows 5 sessions. Switch to 盘前 → label updates, chart re-fetches with extended-hours data. |
| 分钟 | Click → switches to 5min K (the persisted default). Click again → popover shows 1/2/3/5min. Switch to 1min → ~390 bars. |
| 多日 | Click → 5日 (default). Popover shows 5日 / 7日. Switch to 7日 → ~546 bars. Day-separator vertical lines visible. |
| 日K | Click → candlestick chart, ~250 bars. Default visible window ≈ 60. **Pinch-zoom out** → see all 250. **Pinch in** → focus on 5-10. **Pan left** → scroll backward. |
| 周K | Click → candlestick, ~200 bars, x labels like `2026-W19`. |
| 月K | Click → candlestick, ~120 bars, x labels like `2026-03`. |
| 年K | Click → candlestick, ~30 bars, x labels like `2025`. |

Verify BUY/SELL markers still appear on candle views (over the bars at the trade timestamps).

Verify avg-cost toggle (top-right) shows/hides the reference line on every view.

- [ ] **Step 4: Verify popover edge behavior**

- Click `日内` tab — popover does not open.
- Click `日内` again (it's active now) — popover opens.
- Click outside the popover → it closes.
- Click `日内` again → popover opens.
- Press `Escape` → it closes.
- Click `分钟` while `日内`'s popover is open — `分钟` becomes active and old popover closes (no popover auto-opens since 分钟 wasn't active before).
- Click `分钟` again — its popover opens with `5min` highlighted.

- [ ] **Step 5: Stop dev servers**

Ctrl-C both. Note any visual glitches (popover offset wrong, marker not rendering on candle view, label collision). For each: open an issue/note rather than over-fixing here.

---

### Task F2: Final verification + open risks check

**Files:** none

- [ ] **Step 1: Run full backend tests**

```bash
cd /Users/tianpengxuan/Documents/signal-station/backend
uv run pytest
```

Expected: PASS.

- [ ] **Step 2: Run full frontend tests + type-check**

```bash
cd /Users/tianpengxuan/Documents/signal-station/frontend
npm run test && npm run typecheck && npm run build
```

Expected: PASS.

- [ ] **Step 3: Walk the spec's "Open Risks" section against actual behavior**

Open `docs/superpowers/specs/2026-05-17-chart-tabs-redesign-design.md` and confirm in code:

1. **`Period.Week/Month/Year` SDK availability** — confirmed in Task A1.
2. **`chartjs-chart-financial` vs chart.js 4.x compatibility** — `npm run build` passing confirms.
3. **Plugin coord assumption (crosshair / minMaxLabels on time-scale x)** — the dataset uses `category` scale (labels[]), not time-scale, so existing plugins work. Verified in smoke test step F1/3.
4. **Tooltip behavior on candlesticks** — covered by Task E2 step 2; smoke-test in F1/3.
5. **BUY/SELL marker snapping on candle views** — `m.x = bar index` works because candle dataset is also bound to `labels[]`. Verified in smoke test.
6. **Initial visible window vs loaded batch** — optional polish; defer unless smoke test surfaces user confusion.

If any of these surface real bugs in smoke, file as a follow-up task (do not block this PR). Document in the PR description.

- [ ] **Step 4: Final commit if any test/typecheck fixes were needed**

If steps 1-3 required changes, commit them:

```bash
git add ...
git commit -m "fix(detail-chart): <specific fix>"
```

Otherwise nothing to do — the implementation is complete.

---

## Out of Scope (Reminder)

The following are **deliberately not in this plan** — do not add them mid-task:

- Infinite-scroll historical loading for K-line views.
- Technical indicators (MA / MACD / RSI / Bollinger).
- Migration to `lightweight-charts`.
- Live-tick on weekly/monthly/yearly K.
- Changes to `IntradaySpark` (card-level mini chart).
- Changes to 做T pair / trade list / detail summary / pair detail modal.
- Mobile-responsive tab collapsing.

If smoke test reveals one of these is critical, raise it as a follow-up — not as scope creep here.
