# Live Intraday Chart Tick Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the detail-pane price chart's last bar move with `quote.snapshot` pushes across all minute-level views (today 分时 / 1-5min, 5D, 7D, 15D). On `today` views, also append a new bar on each period boundary. Daily-K periods (30D / 60D / 90D) stay static. A pulsing DOM dot marks the live point.

| Period | Granularity | periodMinutes | live update? | append on boundary? |
|---|---|---|---|---|
| today | 分时 | 1 | yes | yes |
| today | 1/2/3/5min | 1/2/3/5 | yes | yes |
| 5 / 7 | 5min (backend) | 5 | yes (in-place only) | no |
| 15 | 15min (backend) | 15 | yes (in-place only) | no |
| 30 / 60 / 90 | day | — | no | no |

For non-today views the "in-place" update is further gated by a freshness check: if `now - lastBarStart > 2 × periodMinutes`, the chart is staler than the live tick can honestly extend, so we leave it alone (don't paint 10:00 prices on a 09:30 bar).

**Architecture:** Refactor `DetailChart.tsx`'s single 280-line `useEffect` into three: (A) chart create/destroy on structural deps only, (B) data mutation via `chart.update("none")` on bar/marker/avg-cost changes, (C) live-tick subscription gated by a `liveConfig(period, todayGranularity)` resolver, driven by `useQuotesStore`, RAF-throttled, with a sibling DOM pulse element positioned via `chart.scales.{x,y}.getPixelForValue`. Live state stays local to the component — we never write back into the bars store, so `DetailPane`'s existing `barsInitialized` gate semantics are untouched.

**Tech Stack:** React 18, TypeScript, Chart.js 4, Zustand, vitest + @testing-library/react (jsdom).

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `frontend/src/components/Positions/DetailChart.tsx` | Modify | Split big useEffect into A/B/C; add `symbol` prop; render `<div className="live-pulse">`. |
| `frontend/src/components/Positions/DetailPane.tsx` | Modify | Pass `symbol` to `<DetailChart>` (one prop added). |
| `frontend/src/components/Positions/liveTick.ts` | Create | Pure helpers: `liveConfig` resolver + `bucketKey` + `applyLiveTick`. Testable without Chart.js. |
| `frontend/src/components/Positions/liveTick.test.ts` | Create | Unit tests for the pure helpers. |
| `frontend/src/components/Positions/Detail.css` | Modify | Add `.live-pulse` + `@keyframes live-pulse-anim`. |

Three buckets of state inside `DetailChart`:
- `chartRef` — Chart.js instance.
- `liveStateRef` — `{ lastMinuteKey: number; rafId: number | null }` (mutable, scoped to live-tick effect).
- `pulseRef` — `HTMLDivElement` for the DOM dot.

---

## Task 1: Pure live-tick helper (period-parameterized)

**Files:**
- Create: `frontend/src/components/Positions/liveTick.ts`
- Test: `frontend/src/components/Positions/liveTick.test.ts`

Three pure pieces the React effect composes with `chart.data` mutation:

1. `liveConfig(period, todayGranularity)` → resolves the view's `{ periodMinutes, allowAppend }` or `null` if the view is non-live (30D/60D/90D). Truth table:
   - `today` + `分时` → `{ 1, allowAppend: true }`
   - `today` + `1min/2min/3min/5min` → `{ N, allowAppend: true }`
   - `"5" | "7"` → `{ 5, allowAppend: false }` (backend serves 5-min K)
   - `"15"` → `{ 15, allowAppend: false }`
   - `"30" | "60" | "90"` → `null` (daily K, no live)
2. `bucketKey(ms, periodMinutes)` → `Math.floor(ms / (periodMinutes * 60_000))`. 5-min and 15-min bucket boundaries align with both UTC and BJ wall clock (whole-hour offset).
3. `applyLiveTick({ bars, labels, lastDone, nowMs, periodMinutes, allowAppend })` — returns next bars + labels and whether a boundary was crossed. Rules:
   - **Empty bars** → unchanged.
   - **Stale bar** (now is more than 2 buckets past lastBar's bucket AND `allowAppend=false`) → unchanged (chart is too old to honestly extend; e.g. 5D view opened in pre-market with last bar at yesterday's 16:00 ET).
   - **Same bucket** (`nowKey == lastKey`) OR (`nowKey > lastKey` AND `allowAppend=false`) → in-place update: `close = lastDone`, `high = max(high, lastDone)`, `low = min(low, lastDone)`. `crossedBoundary=false`.
   - **Crossed bucket AND `allowAppend=true`** → close out last bar as-is, append a new bar `{ timestamp: bucketStartIso, open=high=low=close=lastDone, volume: 0, turnover: 0 }`. Label uses `fmtBjHM(bucketStartIso)`. `crossedBoundary=true`.

The "stale" check is what protects 5D/7D/15D views opened outside RTH: backend gave us a bar series that ends at, say, yesterday 16:00 ET, and a quote.snapshot arriving from pre-market today shouldn't redraw that closed bar.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Positions/liveTick.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { applyLiveTick, bucketKey, liveConfig } from "./liveTick";
import type { Candlestick } from "../../api/domain-types";

const baseBar = (ts: string, c: number): Candlestick => ({
  timestamp: ts,
  open: c, high: c, low: c, close: c, volume: 0, turnover: 0,
});

describe("liveConfig", () => {
  it("today + 分时 → 1min, append allowed", () => {
    expect(liveConfig("today", "分时")).toEqual({ periodMinutes: 1, allowAppend: true });
  });
  it("today + Nmin → N, append allowed", () => {
    expect(liveConfig("today", "1min")).toEqual({ periodMinutes: 1, allowAppend: true });
    expect(liveConfig("today", "2min")).toEqual({ periodMinutes: 2, allowAppend: true });
    expect(liveConfig("today", "3min")).toEqual({ periodMinutes: 3, allowAppend: true });
    expect(liveConfig("today", "5min")).toEqual({ periodMinutes: 5, allowAppend: true });
  });
  it("5D/7D → 5min, no append", () => {
    expect(liveConfig("5", "分时")).toEqual({ periodMinutes: 5, allowAppend: false });
    expect(liveConfig("7", "分时")).toEqual({ periodMinutes: 5, allowAppend: false });
  });
  it("15D → 15min, no append", () => {
    expect(liveConfig("15", "分时")).toEqual({ periodMinutes: 15, allowAppend: false });
  });
  it("30D/60D/90D → null (no live)", () => {
    expect(liveConfig("30", "分时")).toBeNull();
    expect(liveConfig("60", "分时")).toBeNull();
    expect(liveConfig("90", "分时")).toBeNull();
  });
});

describe("bucketKey", () => {
  it("1-minute buckets snap on the minute", () => {
    const a = Date.parse("2026-05-15T13:30:15Z");
    const b = Date.parse("2026-05-15T13:30:59Z");
    const c = Date.parse("2026-05-15T13:31:00Z");
    expect(bucketKey(a, 1)).toBe(bucketKey(b, 1));
    expect(bucketKey(c, 1)).toBe(bucketKey(a, 1) + 1);
  });
  it("5-minute buckets snap on :00, :05, :10, …", () => {
    const a = Date.parse("2026-05-15T13:30:00Z");
    const b = Date.parse("2026-05-15T13:34:59Z");
    const c = Date.parse("2026-05-15T13:35:00Z");
    expect(bucketKey(a, 5)).toBe(bucketKey(b, 5));
    expect(bucketKey(c, 5)).toBe(bucketKey(a, 5) + 1);
  });
  it("15-minute buckets snap on :00, :15, :30, :45", () => {
    const a = Date.parse("2026-05-15T13:15:00Z");
    const b = Date.parse("2026-05-15T13:29:59Z");
    const c = Date.parse("2026-05-15T13:30:00Z");
    expect(bucketKey(a, 15)).toBe(bucketKey(b, 15));
    expect(bucketKey(c, 15)).toBe(bucketKey(a, 15) + 1);
  });
});

describe("applyLiveTick — same-bucket in-place updates", () => {
  it("updates close + accumulates high/low within the same 1-min bucket", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const minuteMs = Date.parse("2026-05-15T13:30:00Z");

    let out = applyLiveTick({
      bars, labels, lastDone: 102,
      nowMs: minuteMs + 15_000,
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(false);
    expect(out.bars).toHaveLength(1);
    expect(out.bars[0].close).toBe(102);
    expect(out.bars[0].high).toBe(102);
    expect(out.bars[0].low).toBe(100);

    out = applyLiveTick({
      bars: out.bars, labels: out.labels, lastDone: 98,
      nowMs: minuteMs + 45_000,
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.bars[0].high).toBe(102);
    expect(out.bars[0].low).toBe(98);
    expect(out.bars[0].close).toBe(98);
  });

  it("same logic at 5-min granularity (in-place within the same 5-min bucket)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const out = applyLiveTick({
      bars, labels, lastDone: 105,
      nowMs: Date.parse("2026-05-15T13:34:30Z"),
      periodMinutes: 5, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(false);
    expect(out.bars[0].close).toBe(105);
    expect(out.bars[0].high).toBe(105);
  });
});

describe("applyLiveTick — boundary crossing with allowAppend=true", () => {
  it("appends a new 1-min bar when now is in the next minute", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const out = applyLiveTick({
      bars, labels, lastDone: 103,
      nowMs: Date.parse("2026-05-15T13:31:05Z"),
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(true);
    expect(out.bars).toHaveLength(2);
    expect(out.bars[0]).toEqual(baseBar("2026-05-15T13:30:00Z", 100));
    expect(out.bars[1].timestamp).toBe("2026-05-15T13:31:00.000Z");
    expect(out.bars[1].open).toBe(103);
    expect(out.bars[1].close).toBe(103);
    expect(out.labels).toEqual(["21:30", "21:31"]);
  });

  it("anchors new-bar timestamp to the bucket start (not to nowMs)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    // Now is 13:38:15, periodMinutes=5 → new bucket starts at 13:35.
    const out = applyLiveTick({
      bars, labels, lastDone: 110,
      nowMs: Date.parse("2026-05-15T13:38:15Z"),
      periodMinutes: 5, allowAppend: true,
    });
    expect(out.crossedBoundary).toBe(true);
    expect(out.bars[1].timestamp).toBe("2026-05-15T13:35:00.000Z");
  });
});

describe("applyLiveTick — allowAppend=false (5D/7D/15D)", () => {
  it("updates last bar in place when within freshness window (≤ 2 buckets)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    // Last bar is at 13:30, now is 13:34 (same 5-min bucket).
    const sameBucket = applyLiveTick({
      bars, labels, lastDone: 102,
      nowMs: Date.parse("2026-05-15T13:34:00Z"),
      periodMinutes: 5, allowAppend: false,
    });
    expect(sameBucket.crossedBoundary).toBe(false);
    expect(sameBucket.bars[0].close).toBe(102);
    expect(sameBucket.bars).toHaveLength(1);

    // Now is 13:38 → next 5-min bucket. Still within 2-bucket window;
    // update in place (no append) — last bar's close tracks last_done.
    const nextBucket = applyLiveTick({
      bars, labels, lastDone: 104,
      nowMs: Date.parse("2026-05-15T13:38:00Z"),
      periodMinutes: 5, allowAppend: false,
    });
    expect(nextBucket.crossedBoundary).toBe(false);
    expect(nextBucket.bars).toHaveLength(1);
    expect(nextBucket.bars[0].close).toBe(104);
  });

  it("leaves bars unchanged when stale (>2 buckets old)", () => {
    const bars = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    // Now is 13:55 — 5 buckets past the last bar's 5-min bucket. 5D view
    // opened in stale state (e.g. session boundary skipped); chart
    // shouldn't paint 13:55 prices on the 13:30 bar.
    const out = applyLiveTick({
      bars, labels, lastDone: 999,
      nowMs: Date.parse("2026-05-15T13:55:00Z"),
      periodMinutes: 5, allowAppend: false,
    });
    expect(out.crossedBoundary).toBe(false);
    expect(out.bars[0].close).toBe(100);   // unchanged
    expect(out.bars).toHaveLength(1);
  });
});

describe("applyLiveTick — guards", () => {
  it("returns input unchanged when bars are empty", () => {
    const out = applyLiveTick({
      bars: [], labels: [],
      lastDone: 50, nowMs: Date.parse("2026-05-15T13:31:05Z"),
      periodMinutes: 1, allowAppend: true,
    });
    expect(out.bars).toEqual([]);
    expect(out.labels).toEqual([]);
    expect(out.crossedBoundary).toBe(false);
  });

  it("does not mutate the input bars/labels arrays", () => {
    const bars: Candlestick[] = [baseBar("2026-05-15T13:30:00Z", 100)];
    const labels = ["21:30"];
    const snapshot = JSON.stringify(bars);
    applyLiveTick({
      bars, labels, lastDone: 105,
      nowMs: Date.parse("2026-05-15T13:30:42Z"),
      periodMinutes: 1, allowAppend: true,
    });
    expect(JSON.stringify(bars)).toBe(snapshot);
    expect(labels).toEqual(["21:30"]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/Positions/liveTick.test.ts`
Expected: FAIL — `Cannot find module './liveTick'`.

- [ ] **Step 3: Write the helper**

Create `frontend/src/components/Positions/liveTick.ts`:

```ts
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Positions/liveTick.test.ts`
Expected: PASS — all cases green (3 `liveConfig` + 3 `bucketKey` + 2 same-bucket + 2 cross-boundary + 2 allowAppend=false + 2 guards = 14).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/liveTick.ts frontend/src/components/Positions/liveTick.test.ts
git commit -m "feat(chart): pure live-tick helper, parameterized by periodMinutes

Resolves view → (periodMinutes, allowAppend). today views append on
boundaries; 5D/7D/15D in-place only with a 2-bucket staleness guard;
30D/60D/90D non-live.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add `symbol` prop to `DetailChart` (no behavior change yet)

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx:73-95` (Props + signature)
- Modify: `frontend/src/components/Positions/DetailPane.tsx:341-350` (pass `symbol`)

The live-tick effect needs to read `useQuotesStore.quotesBySymbol[symbol]`. Symbol is currently not a prop on `DetailChart`. Add it first as a no-op so the refactor in Task 3 already has it on hand.

- [ ] **Step 1: Add `symbol` to `Props` and destructure it**

Edit `frontend/src/components/Positions/DetailChart.tsx`:

Replace the `Props` interface (~line 73) with:

```tsx
interface Props {
  symbol: string;
  bars: Candlestick[];
  period: Period;
  trades: Trade[];
  avgCost: number | null;
  /** When false (default), the avg-cost reference line is omitted from the
   *  chart. The legend toggle in DetailPane controls this. */
  showAvgCost: boolean;
  /** Today-only sub-options that drive the session-background overlay
   *  and the client-side session filtering for 分时 mode. */
  todayGranularity: "分时" | "1min" | "2min" | "3min" | "5min";
  todaySessions: "regular" | "pre" | "post" | "overnight" | "all";
}
```

Replace the destructuring in the function signature (~line 92-95) with:

```tsx
export function DetailChart({
  symbol, bars, period, trades, avgCost, showAvgCost,
  todayGranularity, todaySessions,
}: Props) {
```

- [ ] **Step 2: Pass `symbol` from `DetailPane`**

Edit `frontend/src/components/Positions/DetailPane.tsx` — find the `<DetailChart ...>` JSX (~line 342) and add `symbol={symbol}` as the first prop:

```tsx
<DetailChart
  symbol={symbol}
  bars={bars.bars}
  period={period}
  trades={trades}
  avgCost={position.avg_cost}
  showAvgCost={showAvgCost}
  todayGranularity={todayGranularity}
  todaySessions={todaySessions}
/>
```

- [ ] **Step 3: Type-check + run existing tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/components/Positions/`
Expected: PASS — all 35 existing Positions tests still pass (or whatever the current count is). New prop is unused inside `DetailChart` but compiles.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/DetailChart.tsx frontend/src/components/Positions/DetailPane.tsx
git commit -m "refactor(chart): thread symbol prop into DetailChart for upcoming live-tick

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Split DetailChart's big useEffect into create + data-update

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx:164-446` (the big effect)

This is the structural refactor the user signed off on. We split the existing effect into two:

- **Effect A — Mount / structural rebuild.** Creates the chart with an empty-but-correctly-shaped `data`. Deps: `[period, todayGranularity, todaySessions, colorMode]`. Reads latest `visibleBars / markers / avgCost / showAvgCost` via a `useRef` (we need them at create-time, but we don't want them in the deps array since changes to them go through Effect B).
- **Effect B — Data mutation.** On `[visibleBars, markers, avgCost, showAvgCost]` change, mutate `chart.data.labels`, `chart.data.datasets[i].data`, and the relevant scale/plugin options, then call `chart.update("none")`. No-op if chart not yet created (Effect A is still in mount phase).

Why a ref for Effect A's initial data: React's useEffect cleanup → next-effect ordering would otherwise force us to re-derive everything in Effect A's body anyway. Using `dataRef.current` keeps Effect A small (config only) and gives Effect B a single source of truth for the mutation path.

The chart's existing in-effect helpers — labels, closes, the gradient/zoom config, the `afterDataLimits` y-fitter — all stay; what changes is *when* they run.

- [ ] **Step 1: Add `dataRef` to hold latest derived chart data**

Inside `DetailChart`, just below `colorMode = usePrefsStore(...)` (~line 101), add:

```tsx
// Derived chart data — kept in a ref so Effect A (chart create) reads the
// latest closes/labels/markers at mount time without listing them in deps,
// while Effect B mutates them on subsequent changes.
const dataRef = useRef<{
  labels: string[];
  closes: number[];
  buys: { x: number; y: number; raw: Trade }[];
  sells: { x: number; y: number; raw: Trade }[];
} | null>(null);
```

- [ ] **Step 2: Build the labels/closes/buys/sells with a useMemo and keep dataRef in sync**

Replace the in-effect derivation (currently lines ~192-203) by hoisting it into a `useMemo` ABOVE the effects. After the existing `markers` `useMemo` (~line 162), add:

```tsx
const chartData = useMemo(() => {
  const SHOW_DATE_IN_LABEL = new Set<Period>(["5", "7", "15"]);
  const labels = visibleBars.map((b) => {
    if (!b.timestamp) return "";
    if (period === "today") return fmtBjHM(b.timestamp);
    if (SHOW_DATE_IN_LABEL.has(period)) {
      return `${fmtBjDate(b.timestamp)} ${fmtBjHM(b.timestamp)}`;
    }
    return fmtBjDate(b.timestamp);
  });
  const closes = visibleBars.map((b) => b.close);
  const buys = markers.filter((m) => m.raw.side === "BUY");
  const sells = markers.filter((m) => m.raw.side === "SELL");
  return { labels, closes, buys, sells };
}, [visibleBars, period, markers]);

// Mirror into a ref so Effect A (mount-once) can read latest at create-time
// without taking a deps subscription.
useEffect(() => { dataRef.current = chartData; }, [chartData]);
```

- [ ] **Step 3: Replace the big useEffect with Effect A (create chart)**

Delete the existing `useEffect(() => { const canvas = ... }, [visibleBars, period, ...])` block at lines 164-446 (everything from `useEffect(() => {` through the matching `}, [...]);`).

In its place, write Effect A:

```tsx
// Effect A — create the Chart instance once per structural-deps combo
// (period/granularity/session/color-mode). visibleBars / markers / avgCost
// flow through Effect B as in-place mutations so quote ticks don't tear
// the chart down. Symbol switch is structural too (chart cleanly resets).
useEffect(() => {
  const canvas = canvasRef.current;
  const data = dataRef.current;
  if (!canvas || !data || data.closes.length === 0) return;

  // Initial visible window per period — sized so the default view shows
  // ~1 reading-unit of data and the rest is reachable by dragging.
  const INITIAL_VISIBLE_COUNT: Record<Period, number> = {
    today: data.closes.length,
    "5": 78, "7": 78, "15": 52, "30": 20, "60": 25, "90": 30,
  };
  const initialCount = Math.min(
    INITIAL_VISIBLE_COUNT[period] ?? data.closes.length,
    data.closes.length,
  );
  const xMax = data.closes.length - 1;
  const xMin = Math.max(0, xMax - initialCount + 1);

  // Snapshot avgCost / showAvgCost at mount time. Subsequent changes
  // flow through Effect B (it adds/removes the dataset entry as needed).
  const initialAvgCost = avgCost;
  const initialShowAvgCost = showAvgCost;

  const cfg: ChartConfiguration = {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [
        {
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
        },
        ...(initialAvgCost != null && initialShowAvgCost ? [{
          label: "成本均价",
          data: data.closes.map(() => initialAvgCost),
          borderColor: C.info,
          borderWidth: 1.2,
          borderDash: [4, 4],
          fill: false, pointRadius: 0, tension: 0,
          order: 3,
        }] : []),
        {
          label: "买入",
          type: "scatter" as const,
          data: data.buys,
          backgroundColor: cssVar("--up-color", "#3dd68c"),
          borderColor: C.bg0,
          borderWidth: 2.5,
          pointRadius: 8, pointHoverRadius: 10,
          pointStyle: "triangle" as const,
          rotation: 0,
          order: 1,
          parsing: false as const,
        } as ChartConfiguration["data"]["datasets"][number],
        {
          label: "卖出",
          type: "scatter" as const,
          data: data.sells,
          backgroundColor: cssVar("--down-color", "#ef5b5b"),
          borderColor: C.bg0,
          borderWidth: 2.5,
          pointRadius: 8, pointHoverRadius: 10,
          pointStyle: "triangle" as const,
          rotation: 180,
          order: 1,
          parsing: false as const,
        } as ChartConfiguration["data"]["datasets"][number],
      ],
    },
    plugins: [sessionBgPlugin, crosshairPlugin, minMaxLabelsPlugin],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 240 },
      interaction: { mode: "nearest", intersect: false, axis: "x" },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0b0f14",
          borderColor: C.line,
          borderWidth: 1,
          padding: 10,
          position: "cursor" as unknown as undefined,
          caretSize: 0,
          caretPadding: 8,
          filter: (item) => {
            const ds = item.dataset as { type?: string; label?: string };
            return ds.label === "成交价" || ds.type === "scatter";
          },
          callbacks: {
            title: (items) => {
              const item = items[0];
              if (!item) return "";
              const ds = item.dataset as { type?: string };
              if (ds.type === "scatter") {
                const raw = (item.raw as { raw?: Trade }).raw;
                if (!raw) return "";
                return `${raw.side === "BUY" ? "买入" : "卖出"} · ${fmtBjRel(raw.ts)}`;
              }
              // Read live visibleBars via ref so tooltip stays accurate
              // after Effect B mutates / live-tick appends bars.
              const bar = visibleBarsRef.current[item.dataIndex];
              if (bar?.timestamp) return fmtBjRel(bar.timestamp);
              return item.label;
            },
            label: (item) => {
              const ds = item.dataset as { type?: string; label?: string };
              if (ds.type === "scatter") {
                const raw = (item.raw as { raw?: Trade }).raw;
                if (!raw) return "";
                return ` ${fmtN(raw.qty, 0)} 股 @ $${fmtN(raw.price)}${raw.tag ? "  · " + raw.tag : ""}`;
              }
              return ` 价格 $${fmtN(item.parsed.y as number)}`;
            },
          },
        },
        sessionBg: {
          enabled: period === "today"
            && (todayGranularity === "分时" || todaySessions === "all"),
          granularity: todayGranularity,
          barCount: data.closes.length,
          session: todaySessions,
        },
        zoom: {
          pan: {
            enabled: true, mode: "x", threshold: 4,
            onPanComplete: ({ chart }) => { setIsZoomed(true); chart.update("none"); },
          },
          zoom: {
            wheel: { enabled: true, modifierKey: "shift" },
            pinch: { enabled: true },
            mode: "x",
            onZoomComplete: ({ chart }) => { setIsZoomed(true); chart.update("none"); },
          },
          limits: { x: { min: 0, max: xMax, minRange: 5 } },
        },
      },
      scales: {
        x: {
          min: xMin, max: xMax,
          grid: { color: C.line, drawTicks: false },
          ticks: {
            color: C.fg3,
            font: { family: "IBM Plex Mono", size: 10 },
            maxRotation: 0, autoSkip: true, maxTicksLimit: 8,
          },
          border: { color: C.line },
        },
        y: {
          position: "right",
          afterDataLimits: (scale) => {
            const xScale = scale.chart.scales.x;
            if (!xScale || xScale.min == null || xScale.max == null) return;
            // Read live closes/markers/avg-cost via refs so the y-fit
            // reflects whatever Effect B / live-tick most recently wrote.
            const closes = dataRef.current?.closes ?? [];
            const xLo = Math.max(0, Math.floor(xScale.min as number));
            const xHi = Math.min(closes.length - 1, Math.ceil(xScale.max as number));
            let vMin = Infinity, vMax = -Infinity;
            for (let i = xLo; i <= xHi; i++) {
              const v = closes[i];
              if (v == null) continue;
              if (v < vMin) vMin = v;
              if (v > vMax) vMax = v;
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
          grid: { color: C.line, drawTicks: false },
          ticks: {
            color: C.fg3,
            font: { family: "IBM Plex Mono", size: 10 },
            callback: (v) => fmtN(v as number, 3),
          },
          border: { color: C.line },
        },
      },
    },
  };

  try {
    chartRef.current = new Chart(canvas, cfg);
  } catch (err) {
    if (import.meta.env.DEV) console.warn("DetailChart: Chart init skipped", err);
  }
  return () => {
    chartRef.current?.destroy();
    chartRef.current = null;
  };
  // Structural deps only — non-listed values are read via refs in callbacks.
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [symbol, period, todayGranularity, todaySessions, colorMode]);
```

- [ ] **Step 4: Add the refs that Effect A's callbacks read**

Add these refs just below the existing `chartRef` declaration (around line 97):

```tsx
const visibleBarsRef = useRef<Candlestick[]>([]);
const markersRef = useRef<{ x: number; y: number; raw: Trade }[]>([]);
const avgCostRef = useRef<number | null>(null);
const showAvgCostRef = useRef<boolean>(false);

// Keep refs in sync each render so chart callbacks read the latest values
// without forcing the chart to rebuild.
visibleBarsRef.current = visibleBars;
markersRef.current = markers;
avgCostRef.current = avgCost;
showAvgCostRef.current = showAvgCost;
```

- [ ] **Step 5: Add Effect B — mutate chart on data changes**

Below Effect A, add:

```tsx
// Effect B — mutate chart data in place on data/marker/avg-cost change.
// Skips when the chart hasn't been created yet (Effect A will pick up
// the latest snapshot via dataRef on mount).
useEffect(() => {
  const chart = chartRef.current;
  if (!chart) return;
  const data = dataRef.current;
  if (!data) return;

  chart.data.labels = data.labels;
  // dataset 0 is the price line — replace its data with the latest closes.
  (chart.data.datasets[0]!.data as unknown as number[]) = data.closes;

  // Find / sync the avg-cost dataset. It's optional — present when
  // (avgCost != null && showAvgCost). We never reorder the underlying
  // dataset positions; remove vs insert in-place.
  const datasets = chart.data.datasets as Array<{ label?: string; data: unknown }>;
  const avgIdx = datasets.findIndex((d) => d.label === "成本均价");
  if (avgCost != null && showAvgCost) {
    const avgData = data.closes.map(() => avgCost);
    if (avgIdx === -1) {
      datasets.splice(1, 0, {
        label: "成本均价",
        data: avgData,
        borderColor: C.info,
        borderWidth: 1.2,
        borderDash: [4, 4],
        fill: false, pointRadius: 0, tension: 0,
        order: 3,
      } as unknown as typeof datasets[number]);
    } else {
      (datasets[avgIdx]!.data as unknown as number[]) = avgData;
    }
  } else if (avgIdx !== -1) {
    datasets.splice(avgIdx, 1);
  }

  // Scatter datasets — find by label so order-independent.
  const buyDs = datasets.find((d) => d.label === "买入");
  const sellDs = datasets.find((d) => d.label === "卖出");
  if (buyDs) (buyDs.data as unknown) = data.buys;
  if (sellDs) (sellDs.data as unknown) = data.sells;

  // Keep scales / sessionBg in sync with the new bar count.
  const xMax = data.closes.length - 1;
  const opts = chart.options as unknown as {
    scales: { x: { max: number; min: number } };
    plugins: { sessionBg: { barCount: number }; zoom: { limits: { x: { max: number } } } };
  };
  // Only stretch x-max to the new last bar if the user hasn't panned away
  // from the tail — keeps manual pan/zoom from being yanked on every update.
  const prevMax = chart.scales.x.max as number;
  if (prevMax >= xMax - 1) {
    opts.scales.x.max = xMax;
  }
  opts.plugins.sessionBg.barCount = data.closes.length;
  opts.plugins.zoom.limits.x.max = xMax;

  chart.update("none");
}, [visibleBars, markers, avgCost, showAvgCost]);
```

- [ ] **Step 6: Type-check + run all Positions tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/components/Positions/`
Expected: PASS — existing 35 tests stay green. (The chart's hidden behavior is unchanged: period switch destroys+rebuilds; bar/marker changes mutate without rebuild — a strict improvement.)

- [ ] **Step 7: Manual smoke check**

Run: `cd frontend && npm run dev`
In browser:
1. Open any stock detail pane → chart appears.
2. Switch period today → 5D → today → chart rebuilds cleanly each time, single entry animation per switch.
3. Toggle "成本均价" — line appears/disappears without chart rebuild (no 240ms fade-in).
4. Pan / zoom — `↺ 重置` button shows, click resets.
5. Hover — tooltip shows time + price.

Report: "Smoke check passed: rebuild on period switch only, in-place updates on legend toggle, tooltip/zoom OK." If anything misbehaves, halt and report — don't proceed to Task 4.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Positions/DetailChart.tsx
git commit -m "refactor(chart): split DetailChart effect into create + data-update

Structural changes (period/granularity/session/color-mode) destroy + recreate;
bar/marker/avg-cost changes mutate via chart.update(\"none\"). Prep for the
live-tick effect that follows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Live-tick effect + DOM pulse element

**Files:**
- Modify: `frontend/src/components/Positions/DetailChart.tsx` (add Effect C + pulseRef + JSX dot)
- Modify: `frontend/src/components/Positions/Detail.css` (add `.live-pulse` + keyframes)

Wires the pure helpers from Task 1 to the chart instance and DOM. The `liveConfig` resolver gates the entire effect: if it returns `null` (30D/60D/90D), Effect C is a no-op and no pulse element is rendered.

- [ ] **Step 1: Import the helpers and the store**

Add to the import block at top of `DetailChart.tsx`:

```tsx
import { useQuotesStore } from "../../stores/quotes";
import { applyLiveTick, bucketKey, liveConfig } from "./liveTick";
```

- [ ] **Step 2: Add `pulseRef` and the live state**

Just below the other refs added in Task 3:

```tsx
const pulseRef = useRef<HTMLDivElement | null>(null);
// Local mutable state for live mode. We keep extended bars HERE (not in
// the bars store) so DetailPane's barsInitialized gate and other
// downstream consumers aren't churned by quote-push frequency.
const liveStateRef = useRef<{
  bars: Candlestick[];
  labels: string[];
  rafId: number | null;
  lastApplied: number;
} | null>(null);
```

- [ ] **Step 3: Resolve `liveCfg` and add Effect C**

Below Effect B, add:

```tsx
// liveCfg is null for 30D/60D/90D (daily K) and the today/分时, today/Nmin,
// 5D, 7D, 15D views all get a (periodMinutes, allowAppend) pair.
const liveCfg = liveConfig(period, todayGranularity);
const isLiveMode = liveCfg != null;

// Effect C — live tick. Drives all minute-level views (1/5/15-min).
// RAF-throttled so a tight quote burst doesn't trigger N chart updates
// per frame. Mutates Chart data in place (never the bars store) and
// repositions a DOM pulse dot at the last bar.
useEffect(() => {
  if (!liveCfg) return;
  const chart = chartRef.current;
  if (!chart) return;
  const seedData = dataRef.current;
  if (!seedData) return;

  liveStateRef.current = {
    bars: visibleBarsRef.current.slice(),
    labels: seedData.labels.slice(),
    rafId: null,
    lastApplied: 0,
  };

  const { periodMinutes, allowAppend } = liveCfg;

  const tick = () => {
    const state = liveStateRef.current;
    if (!state) return;
    state.rafId = null;
    const q = useQuotesStore.getState().quotesBySymbol[symbol];
    const lastDone = q?.last_done;
    if (lastDone == null || lastDone === 0) return;
    const nowMs = Date.now();

    // RAF can fire faster than the quote stream — skip if neither price
    // nor bucket changed since last apply.
    const lastTs = state.bars[state.bars.length - 1]?.timestamp;
    const lastBucket = lastTs
      ? bucketKey(Date.parse(lastTs), periodMinutes)
      : -1;
    if (lastDone === state.lastApplied && bucketKey(nowMs, periodMinutes) === lastBucket) {
      return;
    }

    const out = applyLiveTick({
      bars: state.bars,
      labels: state.labels,
      lastDone,
      nowMs,
      periodMinutes,
      allowAppend,
    });
    // If the helper bailed (stale guard, empty bars, etc.) we still want
    // to position the pulse dot — but no chart mutation is needed.
    const dataChanged = out.bars !== state.bars;
    state.bars = out.bars;
    state.labels = out.labels;
    state.lastApplied = lastDone;

    const ch = chartRef.current;
    if (!ch) return;

    if (dataChanged) {
      ch.data.labels = out.labels;
      const priceData = ch.data.datasets[0]!.data as unknown as number[];
      if (out.crossedBoundary) {
        priceData.push(lastDone);
      } else {
        priceData[priceData.length - 1] = lastDone;
      }
      const xMax = priceData.length - 1;
      const opts = ch.options as unknown as {
        scales: { x: { max: number; min: number } };
        plugins: { zoom: { limits: { x: { max: number } } } };
      };
      // Stretch right edge only if user hasn't manually panned away.
      if ((ch.scales.x.max as number) >= xMax - 1) {
        opts.scales.x.max = xMax;
      }
      opts.plugins.zoom.limits.x.max = xMax;
      ch.update("none");
    }

    // Position the pulse dot at the last (x, y) data point.
    const pulse = pulseRef.current;
    if (pulse) {
      const lastIdx = (ch.data.datasets[0]!.data as unknown as number[]).length - 1;
      const px = ch.scales.x.getPixelForValue(lastIdx);
      const py = ch.scales.y.getPixelForValue(lastDone);
      if (Number.isFinite(px) && Number.isFinite(py)) {
        pulse.style.left = `${px}px`;
        pulse.style.top = `${py}px`;
        pulse.classList.add("visible");
        const isDown = (q?.change ?? 0) < 0;
        pulse.classList.toggle("down", isDown);
      }
    }
  };

  // Each store push schedules a single RAF.
  const unsub = useQuotesStore.subscribe((s, prev) => {
    const next = s.quotesBySymbol[symbol]?.last_done;
    const old = prev.quotesBySymbol[symbol]?.last_done;
    if (next === old) return;
    const state = liveStateRef.current;
    if (!state || state.rafId != null) return;
    state.rafId = requestAnimationFrame(tick);
  });

  // Kick once at mount so the dot is positioned on the most-recent
  // already-pushed quote without waiting for the next push.
  liveStateRef.current.rafId = requestAnimationFrame(tick);

  return () => {
    unsub();
    const state = liveStateRef.current;
    if (state?.rafId != null) cancelAnimationFrame(state.rafId);
    liveStateRef.current = null;
    pulseRef.current?.classList.remove("visible", "down");
  };
  // Re-seeds on view changes (period/granularity/symbol). The other deps
  // are read via refs at tick-time, not at effect-mount time.
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [period, todayGranularity, symbol]);
```

- [ ] **Step 4: Render the pulse dot in the JSX**

Replace the existing return JSX (~line 457) with:

```tsx
return (
  <div className="chart-canvas-wrap">
    <canvas ref={canvasRef} />
    {isLiveMode && <div ref={pulseRef} className="live-pulse" aria-hidden />}
    {isZoomed && (
      <button
        className="chart-reset-btn"
        onClick={handleResetZoom}
        title="重置缩放"
      >
        ↺ 重置
      </button>
    )}
  </div>
);
```

- [ ] **Step 5: Add the pulse CSS**

Edit `frontend/src/components/Positions/Detail.css` — append after the `.chart-reset-btn:hover` block (~line 296):

```css
/* Live-mode "now" indicator overlaid on the last bar's data point. Mounted
 * in all minute-level views (today/分时, today/Nmin, 5D/7D/15D) — see
 * DetailChart.tsx's liveCfg gate. Positioned by JS via
 * chart.scales.{x,y}.getPixelForValue; the pulse is purely cosmetic. */
.live-pulse {
  position: absolute;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--up-color);
  transform: translate(-50%, -50%);
  pointer-events: none;
  z-index: 2;
  opacity: 0;
  transition: opacity 200ms ease;
}
.live-pulse.visible {
  opacity: 1;
  animation: live-pulse-anim 1.2s ease-out infinite;
}
.live-pulse.down { background: var(--down-color); }

@keyframes live-pulse-anim {
  0%   { transform: translate(-50%, -50%) scale(1);   opacity: 1;   }
  60%  { transform: translate(-50%, -50%) scale(2.2); opacity: 0;   }
  100% { transform: translate(-50%, -50%) scale(2.2); opacity: 0;   }
}
```

- [ ] **Step 6: Type-check + run existing tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/components/Positions/`
Expected: PASS — pre-existing Positions tests + 14 new `liveTick` tests all green.

- [ ] **Step 7: Manual verification against the acceptance criteria**

Run: `cd frontend && npm run dev`. Open the dashboard during a US session (or with a backend that's streaming quote.snapshot).

**today / 分时:**
1. Open a stock detail (e.g. TSLL), keep period=今日 · 分时 · 盘中.
2. Last bar's close should track DetailSummary's `$xxx.xxx` reading within ~250ms.
3. Cross a BJ minute boundary — x-axis grows a new HH:MM label, line extends one bar.
4. Pulse dot is visible on the last bar; color = `var(--up-color)` when `quote.change >= 0`, `var(--down-color)` otherwise.

**today / 1min ~ 5min K:**
5. Switch to 今日 · 5min — line is still live (last bar's close tracks last_done), but new bars only appear every 5 minutes. Pulse dot visible.

**5D / 7D / 15D:**
6. Switch to 5D — line is still live: last bar's close tracks last_done. Pulse dot visible. No new bars get appended even if 5 minutes pass.
7. Switch to 15D — same: last bar updates, no append.

**30D / 60D / 90D:**
8. Switch to 30D / 60D / 90D — pulse dot is gone, line is fully static, no quote-driven updates.

**Cleanup:**
9. Switch between any of the above — chart cleanly rebuilds (single 240ms entry animation per switch), pulse dot follows the new chart.
10. Close the detail pane — no console errors, no RAF leak.

Report: "Acceptance check ✓: today live, 5D/7D/15D in-place, 30/60/90D static, switches clean." If any step fails, halt and report.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Positions/DetailChart.tsx frontend/src/components/Positions/Detail.css
git commit -m "feat(chart): live last-bar updates across all minute-level views

today views (分时, 1/2/3/5min) drive the trailing bar's close/high/low
and append new bars on period boundaries. 5D/7D/15D views update the
trailing bar in place (with a 2-bucket staleness guard) but never
append. 30D/60D/90D stay fully static.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Integration test for `DetailChart` live wiring (no Chart.js mock)

**Files:**
- Create: `frontend/src/components/Positions/DetailChart.test.tsx`

We don't try to mount Chart.js under jsdom (it would need `HTMLCanvasElement.getContext("2d")` polyfill — fragile). Instead, this test verifies the *React wiring*: the pulse dot is rendered for every live-mode view (today/分时, today/Nmin, 5D/7D/15D), absent for non-live views (30D/60D/90D), and store updates don't crash the component.

- [ ] **Step 1: Write the test**

Create `frontend/src/components/Positions/DetailChart.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, act } from "@testing-library/react";
import { DetailChart } from "./DetailChart";
import { useQuotesStore } from "../../stores/quotes";
import type { Candlestick } from "../../api/domain-types";

// Chart.js needs a 2d context that jsdom doesn't provide. Stub the getter
// so `new Chart(canvas, ...)` swallows the failure quietly (the component
// wraps the constructor in a try/catch and warns in DEV).
beforeEach(() => {
  // @ts-expect-error — jsdom canvas getter is patchable.
  HTMLCanvasElement.prototype.getContext = () => null;
  useQuotesStore.getState().reset();
});

const bars: Candlestick[] = [
  { timestamp: "2026-05-15T13:30:00Z", open: 100, high: 100, low: 100, close: 100, volume: 0, turnover: 0 },
  { timestamp: "2026-05-15T13:31:00Z", open: 100, high: 101, low: 99, close: 101, volume: 0, turnover: 0 },
];

function renderAt(period: Parameters<typeof DetailChart>[0]["period"], todayGranularity: Parameters<typeof DetailChart>[0]["todayGranularity"]) {
  return render(
    <DetailChart
      symbol="TSLA.US"
      bars={bars}
      period={period}
      trades={[]}
      avgCost={null}
      showAvgCost={false}
      todayGranularity={todayGranularity}
      todaySessions="regular"
    />,
  );
}

describe("DetailChart live-mode wiring", () => {
  it.each([
    ["today", "分时"],
    ["today", "1min"],
    ["today", "2min"],
    ["today", "3min"],
    ["today", "5min"],
    ["5", "分时"],
    ["7", "分时"],
    ["15", "分时"],
  ] as const)("renders .live-pulse for live view (period=%s, granularity=%s)", (period, gran) => {
    const { container } = renderAt(period, gran);
    expect(container.querySelector(".live-pulse")).not.toBeNull();
  });

  it.each([
    ["30", "分时"],
    ["60", "分时"],
    ["90", "分时"],
  ] as const)("omits .live-pulse for non-live view (period=%s, granularity=%s)", (period, gran) => {
    const { container } = renderAt(period, gran);
    expect(container.querySelector(".live-pulse")).toBeNull();
  });

  it("survives a quote upsert in live mode without throwing", () => {
    renderAt("today", "分时");
    // The store push path is what App.tsx calls in production. Under jsdom
    // chartRef will be null (Chart construction failed), and the live-tick
    // effect's `if (!chart) return;` guard is what we're verifying here.
    expect(() => {
      act(() => {
        useQuotesStore.getState().upsertQuote("TSLA.US", {
          last_done: 102,
          prev_close: 100,
          today_close: null,
          open: 100, high: 102, low: 99,
          volume: 0, turnover: 0,
          change: 2, change_pct: 2,
          trade_session: "regular",
        });
      });
    }).not.toThrow();
  });

  it("survives quote upserts across all non-live views too", () => {
    for (const [period, gran] of [["30", "分时"], ["60", "分时"], ["90", "分时"]] as const) {
      const { unmount } = renderAt(period, gran);
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

- [ ] **Step 2: Run the test**

Run: `cd frontend && npx vitest run src/components/Positions/DetailChart.test.tsx`
Expected: PASS — both cases green.

- [ ] **Step 3: Run the full Positions suite to verify no regressions**

Run: `cd frontend && npx vitest run src/components/Positions/`
Expected: PASS — pre-existing tests + Task 1's 14 helper tests + Task 5's 8+3+1+1 = 13 cases (live, non-live, jsdom guard live, jsdom guard non-live) all green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/DetailChart.test.tsx
git commit -m "test(chart): DetailChart live-mode wiring (pulse element + store push)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ today/分时, today/Nmin: last bar's close/high/low track `last_done` — Task 1 same-bucket branch + Task 4 Effect C.
- ✅ today: cross-period boundary appends a new bar at the bucket's :00 anchor — Task 1 allowAppend branch + Task 4 priceData.push.
- ✅ 5D / 7D / 15D: last bar updates in place; no append; stale guard (>2 buckets) — Task 1 allowAppend=false branch.
- ✅ 30D / 60D / 90D: fully static — `liveConfig` returns null, Effect C early-returns, pulse element not rendered.
- ✅ DOM pulse dot positioned via `chart.scales.{x,y}.getPixelForValue` — Task 4 Step 3.
- ✅ Pulse color follows `quote.change` direction — Task 4 Step 3 (`isDown` toggle).
- ✅ Don't write back into bars store — extended bars live in `liveStateRef`, not `useCandlesticksStore`.
- ✅ Don't break `DetailPane` gates (`tradesInitialized` / `pairsInitialized` / `barsInitialized`) — none touched.
- ✅ Chart created once per structural-deps combo — Task 3 Effect A deps `[symbol, period, todayGranularity, todaySessions, colorMode]`.
- ✅ Data updates via `chart.update("none")` — Task 3 Effect B + Task 4 Effect C.
- ✅ Cleanup on unmount / period switch — Task 4 Effect C return cancels RAF + unsubscribes; pulse classes cleared.
- ✅ Existing tests stay green — Task 3 Step 6 + Task 5 Step 3.

**Placeholders:** None — all code blocks are complete with imports, types, and concrete logic.

**Type consistency:** `applyLiveTick` / `bucketKey` / `liveConfig` signatures match across Task 1's test and Task 4's caller. The `Granularity` type from `liveTick.ts` overlaps with `Props["todayGranularity"]` in `DetailChart.tsx` — explicitly re-typed there to avoid an extra cross-file import (the union is small and locally inlined).

**Risks:**
- `parseUtc` import in `liveTick.ts` must be exported from `timeFmt.ts` — verified at `timeFmt.ts:105`.
- `useQuotesStore.subscribe((s, prev) => …)` is the basic Zustand v4 two-arg overload — works without `subscribeWithSelector` middleware (confirmed by reading the store at `stores/quotes.ts:17`).
- The "2-bucket staleness" threshold for `allowAppend=false` is heuristic — set conservatively to permit the common "5D opened mid-RTH" scenario but reject "5D opened pre-market with yesterday's tail" scenarios. If users observe ghost updates on stale bars during overnight gaps, narrow this to `> 1`. Document in code.
