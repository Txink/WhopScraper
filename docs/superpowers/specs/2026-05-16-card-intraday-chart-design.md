# Card Intraday Chart Design

> **Status:** Brainstorming complete · 2026-05-16
> **Scope:** Positions panel **stock cards** (`PositionCard`) intraday spark only. Option cards (`OptionCard` — 30-day daily K) untouched. Detail pane chart (`DetailChart`) untouched.

## Goal

Replace `MiniLine` (Chart.js) inside the stock card with a session-aware SVG spark that:

1. Renders only the **currently-active trading session** (auto-switches across pre / regular / post / overnight / closed; HK has only regular / closed).
2. Reserves **fixed x-axis width** for that session's full duration — empty future minutes stay blank.
3. Shows the session label as a **centered low-opacity watermark** in the SVG background ("盘中" / "盘后" / etc.).
4. Updates the last data point in **real-time** via the existing `useQuotesStore` push pipeline; appends a new local bar when crossing a 1m boundary.
5. Refreshes 1m bars **only when `quote.trade_session` actually changes** (≤4 broker calls per symbol per day, not per push).
6. Uses the **same ET-based baseline rule** as the backend for Day P/L: pre/regular → `prev_close`; post/overnight → `today_close`; closed → `prev_close`.
7. Drops Chart.js for cards — pure SVG, themable via CSS vars.

The session pill at the top of the card stays, but is restyled to be **neutral** (not tied to up/down color tokens).

## Architecture

**New files:**

| File | Responsibility |
|---|---|
| `frontend/src/components/Positions/IntradaySpark.tsx` | Main SVG component. Stateless beyond a `useMemo` for the live-tip merge. |
| `frontend/src/components/Positions/sessionWindow.ts` | Pure resolver: `(market, session, now) → SessionWindow { startMs, endMs, slotCount, slotToMs, msToSlot, progress, label }`. HK regular folds out the lunch gap (12:00-13:00 HKT). Closed falls back to last trading day's post (US) / regular (HK). |
| `frontend/src/components/Positions/resolveSessionParam.ts` | Pure mapping: `(market, trade_session) → backend sessions param`. Closed → "post" for US, "regular" for HK. |
| `frontend/src/components/Positions/SparkDefs.tsx` | Hidden `<svg>` holding the two `<linearGradient>` defs (up / down). Mounted once by `PositionsPanel` so every `IntradaySpark` instance references them by id. |
| `frontend/src/components/Positions/sessionWindow.test.ts` | Pure-function tests. |
| `frontend/src/components/Positions/resolveSessionParam.test.ts` | Pure-function tests. |
| `frontend/src/components/Positions/IntradaySpark.test.tsx` | Component render tests. |

**Modified files:**

| File | Change |
|---|---|
| `frontend/src/components/Positions/PositionCard.tsx` | Replace `<MiniLine>` with `<IntradaySpark>`; switch Day P/L baseline to `today_close` in post / overnight. |
| `frontend/src/components/Positions/PositionsPanel.tsx` | Switch initial candle fetch to `granularity=分时, sessions=<resolved>`; add `useRef`-diffed effect that re-fetches on `trade_session` transition. Mount `<SparkDefs />` once. |
| `frontend/src/components/Positions/Positions.css` | Add `.ispark*` selectors; restyle `.pcard-session.sess-regular` to use brand color instead of `--up-color`. |

**Unchanged (regression-protected):**

- `frontend/src/components/Positions/MiniLine.tsx` — kept for option card.
- `frontend/src/components/Positions/DetailChart.tsx` — detail pane out of scope.
- `frontend/src/components/Positions/OptionCard.tsx` — uses `MiniLine`; behavior unchanged.
- `frontend/src/stores/candlesticks.ts` — `candleCacheKey` already supports `granularity=分时, sessions=<any>` shape; no schema change.

## Data Flow

```
backend (per-quote-push)
  └─ MarketSchedule.state_for(market, now_utc_now)
     → trade_session field on every WS quote.snapshot
        ↓
useQuotesStore.upsertQuote(symbol, patch)
        ↓
PositionsPanel
  ├─ effect A: stocks list change → fetch granularity=分时, sessions=<current>
  └─ effect B: quotesBySymbol change → diff trade_session per symbol via useRef;
       on transition (≤4×/day) refetch granularity=分时, sessions=<new>
        ↓
useCandlesticksStore.byKey[`${sym}::today::分时::${session}`] = Candlesticks
        ↓
PositionCard
  ├─ pick bars: candleByKey[candleCacheKey(sym, "today", "分时", resolveSessionParam(market, trade_session))]
  ├─ session prop: quote.trade_session ?? "closed"
  ├─ lastDone prop: toUsd(sym, quote.last_done)
  └─ openPrice prop: quote.open
        ↓
IntradaySpark
  ├─ sessionWindow.resolve(market, session, Date.now())
  ├─ useMemo merge: bars + lastDone → renderedBars (live tip + bucket append)
  ├─ project (slot, close) → (x, y) via sessionWindow + min/max pad
  ├─ render <svg>: watermark + area path + line path
  └─ render <span.ispark-pulse> at (W·progress(now), yFor(lastDone))
       — closed state: pulse omitted
```

## §1 Component Contract

```ts
interface IntradaySparkProps {
  symbol: string;                  // "TSLA.US"
  market: "US" | "HK" | "CN";      // resolved by parent via cardHelpers.marketOf
  bars: Candlestick[] | undefined; // 1m bars; oldest first; undefined → skeleton
  session: "pre" | "regular" | "post" | "overnight" | "closed";
  lastDone: number | null;
  openPrice: number | null;
}
```

`market` is derived by the parent from `symbol` to avoid duplicating the suffix parsing logic. We extract a shared `marketOf(symbol): "US" | "HK" | "CN"` helper into `cardHelpers.ts` (currently parses inline inside `marketBadge`).

## §2 sessionWindow.ts

Pure function. Output:

```ts
export interface SessionWindow {
  label: "盘前" | "盘中" | "盘后" | "夜盘" | "休市";
  startMs: number;
  endMs: number;
  slotCount: number;
  slotToMs(slot: number): number;
  msToSlot(ms: number): number;     // -1 if outside window (e.g. HK lunch)
  progress(nowMs: number): number;  // [0..1]; 1.0 if closed
}
```

**Window table (local time in market tz; widths cite slot counts at 1m granularity):**

| Market | Session | Local window | Width | Slots |
|---|---|---|---|---|
| US | pre | ET 04:00 → 09:30 | 5.5h | 330 |
| US | regular | ET 09:30 → 16:00 | 6.5h | 390 |
| US | post | ET 16:00 → 20:00 | 4h | 240 |
| US | overnight | ET 20:00 → +1d 04:00 | 8h | 480 |
| US | closed | prior trading day's post (ET 16:00 → 20:00) | 4h | 240 |
| HK | regular | HKT 09:30→12:00 + 13:00→16:00 (lunch compressed) | 5.5h | 330 (150 + 180) |
| HK | closed | prior trading day's regular | 5.5h | 330 |
| CN | regular | CST 09:30→11:30 + 13:00→15:00 (lunch compressed) | 4h | 240 (120 + 120) |
| CN | closed | prior trading day's regular | 4h | 240 |

**HK lunch compression:**
- `slotToMs(idx)`: `idx < 150 ? 09:30 + idx min : 13:00 + (idx-150) min`. Afternoon spans 180 minutes (13:00→16:00 HKT), so total = 330 slots.
- `msToSlot(ms)`: inverse; ms inside `[12:00, 13:00)` returns `-1`.

**CN lunch compression:** same structure as HK but shorter:
- Morning 09:30→11:30 CST = 120 slots; afternoon 13:00→15:00 CST = 120 slots; total 240.
- `msToSlot(ms)` inside `[11:30, 13:00)` returns `-1`.

**Closed fallback:** market-tz-aware. `currentTradingDay()` in `timeFmt.ts` is ET-pinned (works for US only); for HK we need an HKT-pinned equivalent. Add `lastTradingDayInMarket(market, now)` to `sessionWindow.ts`:

- US: step back from current ET date until weekday found; anchor session at ET 16:00 (post start) → ET 20:00.
- HK / CN: step back from current HKT date until weekday found; anchor at HKT 09:30 (regular start) → HKT 16:00 (with lunch compression in `slotToMs`).

Weekend Monday in BJ → US closed correctly walks back to Friday ET; HK closed walks back to Friday HKT. Public holidays are not enumerated in v1 — the broker's candle fetch will return empty or stale data for holidays, which the card renders as a flat snapshot (acceptable). The static-clock heuristic accepts this drift because `quote.trade_session = closed` is driven by `MarketSchedule.state_for` server-side, which DOES know holidays; only the **fallback window boundary** drifts, and it's a watermark-level concern, not a data-correctness concern.

**DST:** all time math uses `Intl.DateTimeFormat` with `timeZone: 'America/New_York' | 'Asia/Hong_Kong'`. No `+12h` arithmetic; ET ↔ BJ offset is not constant.

## §3 SVG Render Structure

```jsx
<div className={`ispark ${posClass} ${closedClass}`} ref={containerRef}>
  <svg className="ispark-svg" viewBox="0 0 100 100" preserveAspectRatio="none">
    <text className="ispark-watermark" x="50%" y="58%">{win.label}</text>
    <path className="ispark-area" d={areaPath} fill="url(#ispark-fill-up)" />
    <path className="ispark-line" d={linePath} />
  </svg>
  {!isClosed && (
    <span className="ispark-pulse" style={{ left: `${dotX}px`, top: `${dotY}px` }} />
  )}
</div>
```

**Coord math:**

- `viewBox = "0 0 100 100"` with `preserveAspectRatio="none"` — SVG stretches to fit `.pcard-chart` (height 60px). `vector-effect: non-scaling-stroke` on `.ispark-line` keeps the line 1.4px regardless of stretch.
- X per bar: `(msToSlot(bar.timestamp) / slotCount) * 100`. Bars whose `msToSlot` returns `-1` are dropped from the projection.
- Y per close: linear projection over `[yMin - pad, yMax + pad]` where `pad = (yMax - yMin) * 0.2 || |yMin| * 0.005 || 0.5`. SVG y is top-down so `y = ((yHi - close) / (yHi - yLo)) * 100`.
- Line path: `M x0,y0 L x1,y1 ...`; null close → switch to `M` (gap).
- Area path: line path + `L W,H L 0,H Z`.
- Pulse dot px coords: `dotX = (containerWidth) * win.progress(Date.now())`, `dotY = (containerHeight) * (yFor(lastDone) / 100)`. Read `containerRef.current.getBoundingClientRect()` via a `useLayoutEffect` so the dot is positioned in pixels (not viewBox units) — same model as current MiniLine.

**Color rule:** `isPos = (lastDone ?? lastClose) >= (openPrice ?? firstClose)`. Toggles `.pos` / `.neg` class on the root; CSS selectors swap stroke + fill + pulse.

**Gradient ids:** both `ispark-fill-up` and `ispark-fill-down` defined once globally by `<SparkDefs />`. Per-instance `<defs>` would inflate DOM and risk id collisions.

## §4 Live Tick Integration

No store subscription inside `IntradaySpark`. Props change → React re-renders the SVG.

```ts
const renderedBars = useMemo(() => {
  if (!bars || bars.length === 0 || lastDone == null) return bars;
  const nowMs = Date.now();
  const lastBar = bars[bars.length - 1];
  const lastBarSlot = win.msToSlot(parseAsBJ(lastBar.timestamp));
  const nowSlot = win.msToSlot(nowMs);

  // Outside session window (gap or clock skew) — overwrite last close only.
  if (nowSlot < 0 || nowSlot < lastBarSlot) {
    return [...bars.slice(0, -1), { ...lastBar, close: lastDone }];
  }
  // Same bucket — in-place close/high/low merge.
  if (nowSlot === lastBarSlot) {
    return [...bars.slice(0, -1), {
      ...lastBar,
      close: lastDone,
      high: Math.max(lastBar.high ?? lastDone, lastDone),
      low: Math.min(lastBar.low ?? lastDone, lastDone),
    }];
  }
  // Crossed bucket — append a local bar; never written back to store.
  return [...bars, {
    timestamp: bjIsoFromMs(win.slotToMs(nowSlot)),
    open: lastDone, high: lastDone, low: lastDone, close: lastDone,
    volume: 0, turnover: 0,
  }];
}, [bars, lastDone, win]);
```

`parseAsBJ` and `bjIsoFromMs` already exist in `sessionSlots.ts` — extract to a shared `timeFmt.ts` helper (or import directly; both files coexist in `Positions/`).

**Closed state:** still merges (so users glancing at a closed-market card see "the snapshot at close") but skips the pulse render.

**Performance:** at ~390 slots, React DOM diff on `<path d=...>` is ~0.5ms. Quote pushes arrive at ≤10 Hz per symbol; aggregate frame cost on a 10-card grid ≈ 5ms — well under one frame.

## §5 Session-Aware Refetch

`PositionsPanel` owns the fetch logic. Two effects:

```ts
// Effect A: positions list change
useEffect(() => {
  for (const p of stocks) {
    const sess = quotesBySymbol[p.symbol]?.trade_session ?? "regular";
    void fetchIntradayForSession(p.symbol, sess);
  }
}, [stocks.map(p => p.symbol).join(",")]);

// Effect B: session transition diff
const lastSessionRef = useRef<Record<string, string>>({});
useEffect(() => {
  for (const p of stocks) {
    const cur = quotesBySymbol[p.symbol]?.trade_session;
    if (!cur) continue;
    const prev = lastSessionRef.current[p.symbol];
    if (prev !== cur) {
      lastSessionRef.current[p.symbol] = cur;
      if (prev !== undefined) {
        void fetchIntradayForSession(p.symbol, cur);
      }
    }
  }
}, [quotesBySymbol]);

async function fetchIntradayForSession(symbol, session) {
  const market = marketOf(symbol);
  const sessionParam = resolveSessionParam(market, session);
  const c = await api.candlesticks(symbol, "today", {
    granularity: "分时",
    sessions: sessionParam,
  });
  setBars(candleCacheKey(symbol, "today", "分时", sessionParam), c);
}
```

The `useRef` diff is critical: `quotesBySymbol` reference changes on every push, but only the session-string transition triggers a fetch. Without the diff, broker would be hammered.

**`resolveSessionParam`:**

| market | trade_session | sessions param |
|---|---|---|
| US | pre / regular / post / overnight | same |
| US | closed | "post" |
| HK | regular | "regular" |
| HK | closed | "regular" |
| HK | pre / post / overnight (unreachable) | fallback "regular" |
| CN | regular / closed / anything | "regular" (CN never reports pre / post / overnight) |

**Backend compatibility:** `/api/candlesticks` already accepts `sessions=pre|post|overnight` and folds them into SDK `All`-mode with frontend-side ET filtering (see `backend/app/api/http.py:732-734`). No backend change needed.

**Bar filtering:** when backend returns `sessions=all`-flavored data (post/overnight paths), `IntradaySpark`'s `xFor` drops bars whose `msToSlot` returns -1, so off-session bars never reach the rendered path.

## §6 Day P/L Baseline Unification

Backend already session-aware (see `_quote_to_dict` in `backend/app/broker/longport_client.py:64-136`): `change` / `change_pct` use `prev_close` in pre/regular and `today_close` in post/overnight.

Frontend `PositionCard.dayPl` currently always uses `prev_close` — wrong in post / overnight. Fix:

```ts
const session = quote?.trade_session ?? "regular";
const todayClose = toUsd(sym, quote?.today_close);
const dayBaseline =
  (session === "post" || session === "overnight") && todayClose != null
    ? todayClose
    : prevClose;

// Use dayBaseline in the Day P/L formula (replaces inline prevClose at line 127).
```

**Baseline table (single source of truth):**

| Session | Baseline | Source field |
|---|---|---|
| pre | yesterday's RTH close | `quote.prev_close` |
| regular | yesterday's RTH close | `quote.prev_close` |
| post | today's RTH close (16:00 ET) | `quote.today_close` |
| overnight | today's RTH close (16:00 ET) | `quote.today_close` |
| closed | prior trading day's RTH close | `quote.prev_close` (broker frozen) |

`tradingDayOfET` already rolls post + overnight into "today" (ET 04:00 → 04:00 boundary), so the trade-filter loop needs no change.

## §7 Styling Tokens

CSS additions live in `frontend/src/components/Positions/Positions.css`. Highlights:

- `.ispark-watermark` — `font-size: 22px; font-weight: 700; letter-spacing: 0.18em; opacity: 0.10; text-anchor: middle; dominant-baseline: central; fill: var(--fg-3)`. Closed state bumps letter-spacing to 0.22em for the more breathy "休市" feel.
- `.ispark-line` — `vector-effect: non-scaling-stroke` so the stretched viewBox doesn't thicken the line. Stroke color toggled via `.pos` / `.neg` / `.is-closed` ancestor classes.
- `.ispark-area` — fills via `url(#ispark-fill-up|down)`; closed state drops opacity to 0.3.
- `.ispark-pulse` — DOM element, reuses existing `@keyframes minline-pulse`. `prefers-reduced-motion: reduce` disables halo.

**Session pill neutralization:**

```css
- .pcard-session.sess-regular { color: var(--up-color); border-color: rgba(61,214,140,0.4); background: rgba(61,214,140,0.08); }
+ .pcard-session.sess-regular { color: var(--brand); border-color: rgba(var(--brand-rgb), 0.4); background: rgba(var(--brand-rgb), 0.08); }
```

If `--brand` / `--brand-rgb` tokens don't exist, fall back to a neutral pair such as `var(--fg-2)` + `rgba(255,255,255,0.06)`. Verify against `frontend/src/styles/tokens.css` at implementation time.

**Watermark text map:**

| `session` prop | watermark |
|---|---|
| `pre` | 盘前 |
| `regular` | 盘中 |
| `post` | 盘后 |
| `overnight` | 夜盘 |
| `closed` | 休市 |

## §8 Test Plan

| Layer | File | Coverage |
|---|---|---|
| Pure fn | `sessionWindow.test.ts` | All market × session windows; HK lunch slot reversal; closed fallback to prior trading day; DST boundary days; `progress()` edge cases. |
| Pure fn | `resolveSessionParam.test.ts` | Full mapping table. |
| Component | `IntradaySpark.test.tsx` | SVG shape + watermark text + line path + pos/neg class + closed-no-pulse + gap handling + skeleton path. |
| Card | `PositionCard.test.tsx` (extend) | Existing cases pass; new: post session uses `today_close` baseline; `<IntradaySpark>` mount assertion replaces `<MiniLine>`. |
| Panel | `PositionsPanel.test.tsx` (extend) | Mount fetches `granularity=分时, sessions=<current>`; first push doesn't trigger refetch; regular→post transition triggers exactly one refetch; 10 same-session pushes trigger zero refetches. |

**Regression-protected (no edits):**
- `MiniLine` tests
- `OptionCard.test.tsx`
- `DetailChart.test.tsx`

**Implementation order (TDD):**

1. `sessionWindow.ts` + tests
2. `resolveSessionParam.ts` + tests
3. `IntradaySpark.tsx` + tests
4. `PositionCard.tsx` swap + baseline fix + extended tests
5. `PositionsPanel.tsx` fetch rewrite + `<SparkDefs />` mount + extended tests
6. CSS + manual dev-server walkthrough

**Manual verification matrix (dev server):**

| Scenario | Expected |
|---|---|
| US regular, BJ 22:00 | "盘中" watermark, line in left ~1/13 of 6.5h slot, pulse at ~ET 10:00 progress |
| US post, BJ 05:00 | "盘后" watermark, 4h slot |
| HK regular, HKT 09:30 | "盘中" watermark, 5h slot (lunch compressed) |
| Weekend open | "休市" watermark, prior Friday's post (US) / regular (HK), no pulse |
| Color flip US ↔ CN | line + fill + pulse swap; watermark stays gray |
| Live transition 04:00 BJ (US regular → post) | Card auto-refetches and re-renders into post view within seconds |
| Quote push every ~1s | DOM idle stays under 16ms/frame on 10-card grid |

## Non-Goals

- Crosshair / tooltip on hover (detail pane already covers this)
- Hover-to-pause live tick
- Per-session color theming beyond the existing pre/post/overnight pill accents
- Option card chart rework
- Detail pane chart rework
- Backend changes (the existing `/api/candlesticks` + `MarketSchedule` + WS push already covers our needs)
