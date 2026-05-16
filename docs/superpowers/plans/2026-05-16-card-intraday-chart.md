# Card Intraday Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `MiniLine` (Chart.js) inside the positions stock card with a session-aware SVG sparkline that auto-switches across pre / regular / post / overnight / closed, reserves fixed x-axis width per session, shows a session-name watermark, and unifies the Day P/L baseline rule with the backend's ET-based session split.

**Architecture:** New `IntradaySpark` component renders a single SVG (watermark + area + line) with a sibling DOM pulse dot. A pure `sessionWindow` resolver projects bar timestamps onto session slots (HK lunch compressed, closed falls back to prior trading day). `PositionsPanel` fetches `granularity=分时, sessions=<current>` 1m bars per symbol, then refetches only when `quote.trade_session` actually transitions (≤4×/day via a `useRef`-diffed effect, not per push). `PositionCard.dayPl` switches its baseline to `today_close` in post / overnight to match the backend's `change_pct` rule.

**Tech Stack:** React 18, TypeScript, SVG (no chart lib), Zustand, vitest + @testing-library/react (jsdom).

**Spec reference:** `docs/superpowers/specs/2026-05-16-card-intraday-chart-design.md`

---

## File Structure

**Create:**
| File | Responsibility |
|---|---|
| `frontend/src/components/Positions/sessionWindow.ts` | Pure resolver `(market, session, now) → SessionWindow { startMs, endMs, slotCount, slotToMs, msToSlot, progress, label }`; HK regular folds lunch; closed falls back to last trading weekday in market tz. |
| `frontend/src/components/Positions/sessionWindow.test.ts` | Tests for window math, lunch reversal, closed fallback, DST. |
| `frontend/src/components/Positions/resolveSessionParam.ts` | Pure mapping `(market, trade_session) → backend sessions param`. |
| `frontend/src/components/Positions/resolveSessionParam.test.ts` | Tests for the mapping table. |
| `frontend/src/components/Positions/IntradaySpark.tsx` | Main SVG component; live-tip merge via `useMemo`. |
| `frontend/src/components/Positions/IntradaySpark.test.tsx` | Render tests for SVG shape, watermark, pos/neg, closed-no-pulse, gap handling. |
| `frontend/src/components/Positions/SparkDefs.tsx` | Hidden SVG holding two `<linearGradient>` defs; mounted once by `PositionsPanel`. |

**Modify:**
| File | Change |
|---|---|
| `frontend/src/styles/tokens.css` | Add `--brand-rgb: 63, 181, 197;` for rgba helpers. |
| `frontend/src/components/Card/cardHelpers.ts` | Add `marketOf(symbol): "US" \| "HK" \| "CN"` helper. |
| `frontend/src/components/Positions/PositionCard.tsx` | Replace `<MiniLine>` with `<IntradaySpark>`; use `today_close` as `dayBaseline` in post/overnight. |
| `frontend/src/components/Positions/PositionCard.test.tsx` | Add post-session baseline test; swap MiniLine assertion → IntradaySpark. |
| `frontend/src/components/Positions/PositionsPanel.tsx` | Switch initial fetch to `granularity=分时, sessions=<resolved>`; add session-transition effect; mount `<SparkDefs />`. |
| `frontend/src/components/Positions/PositionsPanel.test.tsx` | Test session-aware fetch + transition refetch. |
| `frontend/src/components/Positions/Positions.css` | Add `.ispark*` selectors + neutralize `.pcard-session.sess-regular`. |

**Unchanged (regression-protected):**
- `frontend/src/components/Positions/MiniLine.tsx` (option card still uses it)
- `frontend/src/components/Positions/DetailChart.tsx` (detail pane out of scope)
- `frontend/src/components/Positions/OptionCard.tsx`
- `frontend/src/stores/candlesticks.ts` (`candleCacheKey` already supports the granularity/sessions shape)

---

## Task 1: Add `--brand-rgb` token

**Files:**
- Modify: `frontend/src/styles/tokens.css:19`

`--brand: #3fb5c5;` already exists. We need the RGB triplet form so CSS can build `rgba(var(--brand-rgb), 0.4)` etc. for the neutral session pill in §7.

- [ ] **Step 1: Add the token**

Edit `frontend/src/styles/tokens.css`, locate line 19:
```css
  --brand: #3fb5c5;
```
Add the next line:
```css
  --brand: #3fb5c5;
  --brand-rgb: 63, 181, 197;
```

- [ ] **Step 2: Verify the existing tokens test still passes**

Run: `cd frontend && npm test -- tokens.test.ts --run`
Expected: PASS (tokens file syntax is still valid CSS).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles/tokens.css
git commit -m "$(cat <<'EOF'
feat(frontend/tokens): add --brand-rgb companion to --brand

Lets components build rgba() values from --brand without re-encoding the
hex. Used by the upcoming neutral session-pill restyle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `marketOf` helper to `cardHelpers.ts`

**Files:**
- Modify: `frontend/src/components/Card/cardHelpers.ts`
- Modify: `frontend/src/components/Card/cardHelpers.test.ts`

`PositionCard` currently re-parses the symbol suffix inline (`marketBadge`). The new fetch logic in `PositionsPanel` needs the same routing, so we extract.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/Card/cardHelpers.test.ts`:
```ts
import { marketOf } from "./cardHelpers";

describe("marketOf", () => {
  it("returns 'US' for .US suffix", () => {
    expect(marketOf("TSLA.US")).toBe("US");
  });
  it("returns 'HK' for .HK suffix", () => {
    expect(marketOf("0700.HK")).toBe("HK");
  });
  it("returns 'CN' for .SH and .SZ suffixes", () => {
    expect(marketOf("600519.SH")).toBe("CN");
    expect(marketOf("000001.SZ")).toBe("CN");
  });
  it("returns 'US' as default for unknown / missing suffix", () => {
    expect(marketOf("NOSUFFIX")).toBe("US");
    expect(marketOf("FOO.XX")).toBe("US");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- cardHelpers.test.ts --run`
Expected: FAIL with "marketOf is not a function" or "marketOf is undefined".

- [ ] **Step 3: Add the helper**

Append to `frontend/src/components/Card/cardHelpers.ts`:
```ts
/**
 * Resolve a broker-canonical symbol's market segment.
 *   "TSLA.US"   → "US"
 *   "0700.HK"   → "HK"
 *   "600519.SH" → "CN"
 *   "000001.SZ" → "CN"
 *   unknown     → "US" (default — US is the most common; misroute is
 *                 harmless for the session-window resolver since HK/CN
 *                 share a window shape distinct from US's).
 */
export function marketOf(symbol: string): "US" | "HK" | "CN" {
  const m = symbol.match(/\.([A-Z]+)$/);
  if (!m) return "US";
  const code = m[1];
  if (code === "HK") return "HK";
  if (code === "SH" || code === "SZ") return "CN";
  return "US";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- cardHelpers.test.ts --run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Card/cardHelpers.ts frontend/src/components/Card/cardHelpers.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend/cards): marketOf helper

Shared symbol-to-market resolver used by upcoming session-aware
positions card fetch. Centralizes the suffix parsing previously inlined
in marketBadge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `resolveSessionParam.ts`

**Files:**
- Create: `frontend/src/components/Positions/resolveSessionParam.ts`
- Create: `frontend/src/components/Positions/resolveSessionParam.test.ts`

Pure mapping from `(market, trade_session) → backend candlestick sessions param`. Drives §5 of the spec.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Positions/resolveSessionParam.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { resolveSessionParam } from "./resolveSessionParam";

describe("resolveSessionParam", () => {
  it("passes US active sessions through unchanged", () => {
    expect(resolveSessionParam("US", "pre")).toBe("pre");
    expect(resolveSessionParam("US", "regular")).toBe("regular");
    expect(resolveSessionParam("US", "post")).toBe("post");
    expect(resolveSessionParam("US", "overnight")).toBe("overnight");
  });

  it("US closed → falls back to post", () => {
    expect(resolveSessionParam("US", "closed")).toBe("post");
  });

  it("HK regular → regular", () => {
    expect(resolveSessionParam("HK", "regular")).toBe("regular");
  });

  it("HK closed → regular", () => {
    expect(resolveSessionParam("HK", "closed")).toBe("regular");
  });

  it("CN closed → regular", () => {
    expect(resolveSessionParam("CN", "closed")).toBe("regular");
  });

  it("HK with unreachable session → regular fallback", () => {
    expect(resolveSessionParam("HK", "pre")).toBe("regular");
    expect(resolveSessionParam("HK", "post")).toBe("regular");
    expect(resolveSessionParam("HK", "overnight")).toBe("regular");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- resolveSessionParam.test.ts --run`
Expected: FAIL (file does not exist).

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/Positions/resolveSessionParam.ts`:
```ts
/** Broker-side session label as carried on Quote.trade_session. */
export type TradeSession = "pre" | "regular" | "post" | "overnight" | "closed";

/** Value accepted by ``/api/candlesticks?sessions=...``. */
export type SessionsParam = "regular" | "pre" | "post" | "overnight";

/**
 * Decide which candlestick window to fetch for a card given its market
 * + live ``trade_session`` field.
 *
 * - US active sessions pass through identically — backend serves
 *   ``sessions=all`` SDK data and lets us ET-filter, so passing the
 *   specific session is honored.
 * - US closed → fetch the prior trading day's post window so the card
 *   still shows the freshest tape (matches 富途 weekend behavior).
 * - HK / CN have only regular; anything else maps to regular as a safe
 *   fallback (HK never legitimately emits pre / post / overnight, but
 *   the type system can't prove that).
 */
export function resolveSessionParam(
  market: "US" | "HK" | "CN",
  session: TradeSession,
): SessionsParam {
  if (market === "US") {
    if (session === "closed") return "post";
    return session;
  }
  // HK / CN
  return "regular";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- resolveSessionParam.test.ts --run`
Expected: PASS, all 6 cases.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/resolveSessionParam.ts frontend/src/components/Positions/resolveSessionParam.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend/positions): resolveSessionParam pure helper

Maps live trade_session → /api/candlesticks sessions arg. Closed states
fall back to the prior trading day's most-recent session (post for US,
regular for HK/CN) so cards show fresh tape on weekends/holidays.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `sessionWindow.ts` — window resolver

**Files:**
- Create: `frontend/src/components/Positions/sessionWindow.ts`
- Create: `frontend/src/components/Positions/sessionWindow.test.ts`

The pure resolver: given `(market, session, now)`, returns the visible window's start/end and slot math. This is the heart of the chart's x-axis logic.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Positions/sessionWindow.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { resolveSessionWindow } from "./sessionWindow";

// All test dates are concrete UTC instants. ET = UTC-4 (May → DST).
// HKT = UTC+8 year-round.

function ts(iso: string): number { return Date.parse(iso); }

describe("resolveSessionWindow — US", () => {
  it("regular: 09:30→16:00 ET = 13:30→20:00 UTC, 390 slots", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z")); // 13:00 ET
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(390);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T13:30:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T20:00:00.000Z");
  });

  it("pre: 04:00→09:30 ET, 330 slots", () => {
    const win = resolveSessionWindow("US", "pre", ts("2026-05-14T10:00:00Z")); // 06:00 ET
    expect(win.label).toBe("盘前");
    expect(win.slotCount).toBe(330);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T13:30:00.000Z");
  });

  it("post: 16:00→20:00 ET, 240 slots", () => {
    const win = resolveSessionWindow("US", "post", ts("2026-05-14T22:00:00Z")); // 18:00 ET
    expect(win.label).toBe("盘后");
    expect(win.slotCount).toBe(240);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T20:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");
  });

  it("overnight: 20:00→04:00 ET (+1d), 480 slots", () => {
    const win = resolveSessionWindow("US", "overnight", ts("2026-05-15T03:00:00Z")); // 23:00 ET 5/14
    expect(win.label).toBe("夜盘");
    expect(win.slotCount).toBe(480);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T00:00:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-15T08:00:00.000Z");
  });

  it("closed on weekend → falls back to last weekday's post", () => {
    // Sat 2026-05-16 10:00 UTC → last weekday = Fri 2026-05-15
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.label).toBe("休市");
    expect(win.slotCount).toBe(240);
    // post starts at Fri 16:00 ET = Fri 20:00 UTC
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T20:00:00.000Z");
  });

  it("closed on Monday morning BJ → falls back to Friday post", () => {
    // Mon 2026-05-18 02:00 UTC (= Mon 10:00 BJ; Sun 22:00 ET — still tail
    // of the weekend in market terms). last weekday = Fri 2026-05-15.
    const win = resolveSessionWindow("US", "closed", ts("2026-05-18T02:00:00Z"));
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T20:00:00.000Z");
  });
});

describe("resolveSessionWindow — HK", () => {
  it("regular: 09:30→16:00 HKT with lunch compressed, 300 slots", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z")); // 10:00 HKT
    expect(win.label).toBe("盘中");
    expect(win.slotCount).toBe(300);
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-14T01:30:00.000Z");
    expect(new Date(win.endMs).toISOString()).toBe("2026-05-14T08:00:00.000Z");
  });

  it("HK slot 0 → 09:30 HKT, slot 149 → 11:59 HKT", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(new Date(win.slotToMs(0)).toISOString()).toBe("2026-05-14T01:30:00.000Z");
    expect(new Date(win.slotToMs(149)).toISOString()).toBe("2026-05-14T03:59:00.000Z");
  });

  it("HK slot 150 → 13:00 HKT (lunch skipped)", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(new Date(win.slotToMs(150)).toISOString()).toBe("2026-05-14T05:00:00.000Z");
  });

  it("HK msToSlot rejects bars inside the lunch gap", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T04:30:00Z"))).toBe(-1); // 12:30 HKT
  });

  it("HK msToSlot bridges morning ↔ afternoon correctly", () => {
    const win = resolveSessionWindow("HK", "regular", ts("2026-05-14T02:00:00Z"));
    expect(win.msToSlot(ts("2026-05-14T01:30:00Z"))).toBe(0);   // 09:30 HKT
    expect(win.msToSlot(ts("2026-05-14T03:59:00Z"))).toBe(149); // 11:59 HKT
    expect(win.msToSlot(ts("2026-05-14T05:00:00Z"))).toBe(150); // 13:00 HKT
    expect(win.msToSlot(ts("2026-05-14T07:59:00Z"))).toBe(299); // 15:59 HKT
  });

  it("HK closed on Saturday → falls back to Friday regular", () => {
    const win = resolveSessionWindow("HK", "closed", ts("2026-05-16T02:00:00Z"));
    expect(win.label).toBe("休市");
    expect(new Date(win.startMs).toISOString()).toBe("2026-05-15T01:30:00.000Z");
  });
});

describe("resolveSessionWindow — progress", () => {
  it("US regular: ET 13:00 (3.5h in) → 3.5/6.5 ≈ 0.538", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T17:00:00Z"))).toBeCloseTo(3.5 / 6.5, 3);
  });

  it("clamps to 0 before start", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T12:00:00Z"))).toBe(0);
  });

  it("clamps to 1 after end", () => {
    const win = resolveSessionWindow("US", "regular", ts("2026-05-14T17:00:00Z"));
    expect(win.progress(ts("2026-05-14T22:00:00Z"))).toBe(1);
  });

  it("closed always returns 1", () => {
    const win = resolveSessionWindow("US", "closed", ts("2026-05-16T10:00:00Z"));
    expect(win.progress(ts("2026-05-16T10:00:00Z"))).toBe(1);
  });
});

describe("resolveSessionWindow — DST", () => {
  it("US regular spans DST start (2026-03-08) correctly", () => {
    // 2026-03-09 (Mon after DST start) → ET = UTC-4
    const win = resolveSessionWindow("US", "regular", ts("2026-03-09T15:00:00Z")); // 11:00 ET
    expect(new Date(win.startMs).toISOString()).toBe("2026-03-09T13:30:00.000Z");
  });
  it("US regular spans DST end (2026-11-01) correctly", () => {
    // 2026-11-02 (Mon after DST end) → ET = UTC-5
    const win = resolveSessionWindow("US", "regular", ts("2026-11-02T16:00:00Z")); // 11:00 ET
    expect(new Date(win.startMs).toISOString()).toBe("2026-11-02T14:30:00.000Z");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- sessionWindow.test.ts --run`
Expected: FAIL (file does not exist).

- [ ] **Step 3: Create the implementation**

Create `frontend/src/components/Positions/sessionWindow.ts`:
```ts
/** Pure resolver for the card's intraday-spark x-axis window. */

export type Market = "US" | "HK" | "CN";
export type SessionLabel = "pre" | "regular" | "post" | "overnight" | "closed";

export interface SessionWindow {
  label: "盘前" | "盘中" | "盘后" | "夜盘" | "休市";
  /** UTC ms of the session's first minute boundary. */
  startMs: number;
  /** UTC ms of the session's last minute boundary (exclusive). */
  endMs: number;
  /** Number of 1-minute slots reserved on the x-axis. */
  slotCount: number;
  /** Slot idx → UTC ms (slot's minute start). */
  slotToMs(slotIdx: number): number;
  /** UTC ms → slot idx, or -1 if outside the window (incl. HK lunch). */
  msToSlot(ms: number): number;
  /** [0..1] progress of nowMs through the window. Clamped at the ends.
   *  Always 1 for closed-state windows. */
  progress(nowMs: number): number;
}

const LABEL_MAP: Record<SessionLabel, SessionWindow["label"]> = {
  pre: "盘前",
  regular: "盘中",
  post: "盘后",
  overnight: "夜盘",
  closed: "休市",
};

// ---------- date helpers (Intl, tz-correct, DST-safe) ---------- //

const _US_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric", month: "2-digit", day: "2-digit",
});
const _HK_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Hong_Kong",
  year: "numeric", month: "2-digit", day: "2-digit",
});
const _US_WEEKDAY = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
});
const _HK_WEEKDAY = new Intl.DateTimeFormat("en-US", {
  timeZone: "Asia/Hong_Kong",
  weekday: "short",
});
const _WEEKDAY_IDX: Record<string, number> = {
  Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
};

function dateKeyInTz(ms: number, market: Market): string {
  return market === "US" ? _US_DATE.format(new Date(ms)) : _HK_DATE.format(new Date(ms));
}

function weekdayInTz(ms: number, market: Market): number {
  const fmt = market === "US" ? _US_WEEKDAY : _HK_WEEKDAY;
  return _WEEKDAY_IDX[fmt.format(new Date(ms))] ?? 0;
}

/**
 * Resolve a local-tz wall-clock {YYYY-MM-DD, HH:MM} to UTC ms using an
 * iterative correction: Date.UTC gives us a starting point, then we
 * compute the tz offset at that instant via Intl and adjust. Two passes
 * suffice for all DST cases.
 */
function localToUtcMs(
  dateKey: string,
  hour: number,
  minute: number,
  market: Market,
): number {
  const [y, m, d] = dateKey.split("-").map(Number);
  let guess = Date.UTC(y, m - 1, d, hour, minute);
  for (let i = 0; i < 2; i++) {
    const offset = tzOffsetMinutes(guess, market);
    guess = Date.UTC(y, m - 1, d, hour, minute) - offset * 60_000;
  }
  return guess;
}

function tzOffsetMinutes(ms: number, market: Market): number {
  const tz = market === "US" ? "America/New_York" : "Asia/Hong_Kong";
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const parts = fmt.formatToParts(new Date(ms));
  const get = (t: string) => parseInt(parts.find((p) => p.type === t)?.value ?? "0", 10);
  const local = Date.UTC(
    get("year"), get("month") - 1, get("day"),
    get("hour") === 24 ? 0 : get("hour"), get("minute"),
  );
  return Math.round((local - ms) / 60_000);
}

/** Step back day-by-day in market tz until a weekday (Mon-Fri) is found. */
function lastTradingDateKey(now: number, market: Market): string {
  let ms = now;
  for (let i = 0; i < 7; i++) {
    ms -= 24 * 60 * 60 * 1000;
    const wd = weekdayInTz(ms, market);
    if (wd >= 1 && wd <= 5) return dateKeyInTz(ms, market);
  }
  // Should never happen — a week always contains a weekday.
  return dateKeyInTz(ms, market);
}

// ---------- main resolver ---------- //

export function resolveSessionWindow(
  market: Market,
  session: SessionLabel,
  now: number,
): SessionWindow {
  if (market === "US") return resolveUS(session, now);
  return resolveHK(session, now);
}

function resolveUS(session: SessionLabel, now: number): SessionWindow {
  if (session === "closed") {
    const dk = lastTradingDateKey(now, "US");
    return buildLinear({
      label: LABEL_MAP.closed,
      market: "US",
      dateKey: dk,
      startH: 16, startM: 0,
      lenMin: 240,
      closed: true,
    });
  }
  const todayKey = dateKeyInTz(now, "US");
  // overnight straddles midnight: starts ET 20:00 on the trading day's date
  // and runs 480 minutes into the next calendar date.
  if (session === "overnight") {
    return buildLinear({
      label: LABEL_MAP.overnight,
      market: "US",
      dateKey: todayKey,
      startH: 20, startM: 0,
      lenMin: 480,
    });
  }
  const spec = {
    pre:     { startH: 4,  startM: 0,  lenMin: 330 },
    regular: { startH: 9,  startM: 30, lenMin: 390 },
    post:    { startH: 16, startM: 0,  lenMin: 240 },
  }[session as "pre" | "regular" | "post"];
  return buildLinear({
    label: LABEL_MAP[session as "pre" | "regular" | "post"],
    market: "US",
    dateKey: todayKey,
    startH: spec.startH, startM: spec.startM,
    lenMin: spec.lenMin,
  });
}

function resolveHK(session: SessionLabel, now: number): SessionWindow {
  const closed = session === "closed";
  const dk = closed ? lastTradingDateKey(now, "HK") : dateKeyInTz(now, "HK");

  const morningStartMs = localToUtcMs(dk, 9, 30, "HK");
  const afternoonStartMs = localToUtcMs(dk, 13, 0, "HK");
  const morningSlots = 150; // 09:30 → 11:59 (inclusive of 12:00 boundary)
  const totalSlots = 300;   // 5h

  const startMs = morningStartMs;
  const endMs = afternoonStartMs + 150 * 60_000; // 16:00 HKT

  return {
    label: closed ? LABEL_MAP.closed : LABEL_MAP.regular,
    startMs,
    endMs,
    slotCount: totalSlots,
    slotToMs: (idx) => {
      if (idx < morningSlots) return morningStartMs + idx * 60_000;
      return afternoonStartMs + (idx - morningSlots) * 60_000;
    },
    msToSlot: (ms) => {
      const morningOffset = Math.floor((ms - morningStartMs) / 60_000);
      if (morningOffset >= 0 && morningOffset < morningSlots) return morningOffset;
      const afternoonOffset = Math.floor((ms - afternoonStartMs) / 60_000);
      if (afternoonOffset >= 0 && afternoonOffset < totalSlots - morningSlots) {
        return morningSlots + afternoonOffset;
      }
      return -1;
    },
    progress: (nowMs) => {
      if (closed) return 1;
      // Map nowMs through the slot grid so the lunch hour doesn't show as
      // "stalled" progress — use slot occupancy when possible.
      if (nowMs <= morningStartMs) return 0;
      if (nowMs >= endMs) return 1;
      // In morning window:
      if (nowMs < afternoonStartMs - 60_000) {
        const off = Math.min(morningSlots, Math.floor((nowMs - morningStartMs) / 60_000));
        return off / totalSlots;
      }
      // In afternoon window or lunch gap (clamp lunch to afternoon start):
      if (nowMs < afternoonStartMs) return morningSlots / totalSlots;
      const off = Math.min(
        totalSlots - morningSlots,
        Math.floor((nowMs - afternoonStartMs) / 60_000),
      );
      return (morningSlots + off) / totalSlots;
    },
  };
}

interface LinearWin {
  label: SessionWindow["label"];
  market: Market;
  dateKey: string;
  startH: number;
  startM: number;
  lenMin: number;
  closed?: boolean;
}

function buildLinear(w: LinearWin): SessionWindow {
  const startMs = localToUtcMs(w.dateKey, w.startH, w.startM, w.market);
  const endMs = startMs + w.lenMin * 60_000;
  return {
    label: w.label,
    startMs,
    endMs,
    slotCount: w.lenMin,
    slotToMs: (idx) => startMs + idx * 60_000,
    msToSlot: (ms) => {
      const off = Math.floor((ms - startMs) / 60_000);
      return off >= 0 && off < w.lenMin ? off : -1;
    },
    progress: (nowMs) => {
      if (w.closed) return 1;
      if (nowMs <= startMs) return 0;
      if (nowMs >= endMs) return 1;
      return (nowMs - startMs) / (endMs - startMs);
    },
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- sessionWindow.test.ts --run`
Expected: PASS, all cases.

If any case fails on DST: the iterative `localToUtcMs` should converge in 2 passes for all real-world DST transitions; verify the failing instant is within market hours and not literally inside the 1-hour DST jump (spring-forward 02:00→03:00 ET is outside trading hours, so this never breaks regular).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/sessionWindow.ts frontend/src/components/Positions/sessionWindow.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend/positions): sessionWindow resolver

Pure (market, session, now) → window resolver with slot math. HK regular
folds lunch (09:30-12:00 + 13:00-16:00 → 300 slots, no gap on x-axis).
Closed states fall back to the last weekday in market tz. Uses Intl
zone-aware date math so DST transitions are correct without manual
offset arithmetic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `SparkDefs.tsx`

**Files:**
- Create: `frontend/src/components/Positions/SparkDefs.tsx`

Static hidden SVG that owns the two `<linearGradient>` defs used by every `IntradaySpark` instance.

- [ ] **Step 1: Create the file**

Create `frontend/src/components/Positions/SparkDefs.tsx`:
```tsx
/**
 * Global SVG <defs> for IntradaySpark gradients. Mounted once by
 * PositionsPanel so every spark instance references the same gradient
 * ids — avoids id collisions + DOM bloat that per-instance defs would
 * cause.
 *
 * Colors track ``--up-color`` / ``--down-color`` CSS vars, so the color
 * mode preference (US green-up vs CN red-up) flows through without JS.
 */
export function SparkDefs() {
  return (
    <svg
      width="0"
      height="0"
      style={{ position: "absolute", pointerEvents: "none" }}
      aria-hidden
    >
      <defs>
        <linearGradient id="ispark-fill-up" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--up-color)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--up-color)" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="ispark-fill-down" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--down-color)" stopOpacity="0.22" />
          <stop offset="100%" stopColor="var(--down-color)" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Positions/SparkDefs.tsx
git commit -m "$(cat <<'EOF'
feat(frontend/positions): SparkDefs — shared gradient defs

One hidden SVG hosting the up/down gradients used by IntradaySpark.
PositionsPanel mounts it once so card instances reference shared ids.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `IntradaySpark.tsx` + component test

**Files:**
- Create: `frontend/src/components/Positions/IntradaySpark.tsx`
- Create: `frontend/src/components/Positions/IntradaySpark.test.tsx`

The main SVG component. Pulls together sessionWindow + bars + lastDone into a rendered spark.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Positions/IntradaySpark.test.tsx`:
```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render } from "@testing-library/react";
import { IntradaySpark } from "./IntradaySpark";
import type { Candlestick } from "../../api/domain-types";

// All tests pin Date.now() to a known instant inside US regular session
// (BJ 22:30 = ET 10:30 on 2026-05-14, ~1h into the 6.5h session).
const NOW = Date.parse("2026-05-14T14:30:00Z");

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

const bar = (iso: string, c: number): Candlestick => ({
  timestamp: iso, open: c, high: c, low: c, close: c, volume: 0, turnover: 0,
});

const baseBars: Candlestick[] = [
  bar("2026-05-14T13:30:00", 100),
  bar("2026-05-14T13:31:00", 101),
  bar("2026-05-14T13:32:00", 102),
];

describe("IntradaySpark", () => {
  it("renders SVG with watermark, line, area", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark-svg")).not.toBeNull();
    expect(container.querySelector(".ispark-watermark")?.textContent).toBe("盘中");
    expect(container.querySelector(".ispark-line")).not.toBeNull();
    expect(container.querySelector(".ispark-area")).not.toBeNull();
  });

  it("applies .pos when lastDone >= openPrice", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark.pos")).not.toBeNull();
    expect(container.querySelector(".ispark.neg")).toBeNull();
  });

  it("applies .neg when lastDone < openPrice", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={98} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark.neg")).not.toBeNull();
  });

  it("renders pulse dot in active session", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark-pulse")).not.toBeNull();
  });

  it("omits pulse dot when session === closed", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="closed"
        bars={baseBars} lastDone={null} openPrice={100}
      />,
    );
    expect(container.querySelector(".ispark-pulse")).toBeNull();
    expect(container.querySelector(".ispark-watermark")?.textContent).toBe("休市");
    expect(container.querySelector(".ispark.is-closed")).not.toBeNull();
  });

  it("renders skeleton when bars undefined", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={undefined} lastDone={null} openPrice={null}
      />,
    );
    expect(container.querySelector(".ispark-skeleton")).not.toBeNull();
    expect(container.querySelector(".ispark-line")).toBeNull();
  });

  it("renders empty state when bars present but empty", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={[]} lastDone={null} openPrice={null}
      />,
    );
    expect(container.querySelector(".ispark-line")).toBeNull();
    // Watermark still shows so user sees "盘中" label even before first bar
    expect(container.querySelector(".ispark-watermark")?.textContent).toBe("盘中");
  });

  it("line path is non-empty when bars have data", () => {
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={103} openPrice={100}
      />,
    );
    const d = container.querySelector(".ispark-line")?.getAttribute("d") ?? "";
    expect(d.length).toBeGreaterThan(0);
    expect(d.startsWith("M")).toBe(true);
  });

  it("merges lastDone into last bar (no append if same minute)", () => {
    // Last bar timestamp = 10:32 ET, NOW = 10:30 ET → same minute bucket
    // as the 10:30 bar? No, 10:32 != 10:30. Let's set NOW to match the
    // last bar's minute instead.
    vi.setSystemTime(Date.parse("2026-05-14T13:32:30Z")); // 10:32:30 ET
    const { container } = render(
      <IntradaySpark
        symbol="TSLA.US" market="US" session="regular"
        bars={baseBars} lastDone={102.7} openPrice={100}
      />,
    );
    // We can't easily assert the merged value visually, but path should
    // still render (sanity check that the merge didn't blow up).
    expect(container.querySelector(".ispark-line")).not.toBeNull();
  });

  it("HK regular renders 盘中 watermark + skips lunch slot", () => {
    vi.setSystemTime(Date.parse("2026-05-14T02:00:00Z")); // 10:00 HKT
    const lunchBar = bar("2026-05-14T04:30:00", 50); // 12:30 HKT — should be dropped
    const { container } = render(
      <IntradaySpark
        symbol="0700.HK" market="HK" session="regular"
        bars={[bar("2026-05-14T01:30:00", 48), lunchBar, bar("2026-05-14T05:00:00", 52)]}
        lastDone={52} openPrice={48}
      />,
    );
    expect(container.querySelector(".ispark-watermark")?.textContent).toBe("盘中");
    // Path should still render; the lunch bar is silently dropped.
    expect(container.querySelector(".ispark-line")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test -- IntradaySpark.test.tsx --run`
Expected: FAIL (file does not exist).

- [ ] **Step 3: Create the component**

Create `frontend/src/components/Positions/IntradaySpark.tsx`:
```tsx
import { useMemo, useLayoutEffect, useRef, useState } from "react";
import type { Candlestick } from "../../api/domain-types";
import {
  resolveSessionWindow,
  type Market,
  type SessionLabel,
} from "./sessionWindow";

interface Props {
  symbol: string;
  market: Market;
  bars: Candlestick[] | undefined;
  session: SessionLabel;
  lastDone: number | null;
  openPrice: number | null;
}

// ViewBox is stretched via preserveAspectRatio="none" to fit the
// container; non-scaling-stroke keeps the line at 1.4 logical px.
const VB_W = 100;
const VB_H = 100;

/** Parse a naive LongPort timestamp ("YYYY-MM-DDTHH:mm:ss") as BJ
 *  wall-clock → UTC ms. Matches the convention in sessionSlots.ts. */
function parseAsBJ(iso: string): number {
  if (!iso) return Number.NaN;
  if (iso.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(iso)) return Date.parse(iso);
  return Date.parse(iso + "+08:00");
}

/** Format a UTC ms as a naive BJ ISO string ("YYYY-MM-DDTHH:mm:ss"). */
const _BJ_ISO_FMT = new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Shanghai",
  year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
  hour12: false,
});
function bjIsoFromMs(ms: number): string {
  return _BJ_ISO_FMT.format(new Date(ms)).replace(" ", "T");
}

export function IntradaySpark({
  symbol: _symbol, market, bars, session, lastDone, openPrice,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerSize, setContainerSize] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  // Track container pixel size for pulse-dot positioning. ResizeObserver
  // keeps it accurate across grid relayout (option tab → stocks tab).
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      setContainerSize({ w: rect.width, h: rect.height });
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const win = useMemo(
    () => resolveSessionWindow(market, session, Date.now()),
    // session string OR market change → re-resolve. We deliberately
    // capture Date.now() once per (market, session) tuple — the window
    // start/end is fixed for the session; only nowMs (used by progress)
    // varies, and that's read fresh in the pulse-dot effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [market, session],
  );

  /** Bars enriched with the live tip (last close overwritten by
   *  lastDone, or a new bar appended at the current minute). */
  const renderedBars = useMemo(() => {
    if (!bars || bars.length === 0) return bars ?? [];
    if (lastDone == null) return bars;
    const nowMs = Date.now();
    const lastBar = bars[bars.length - 1];
    const lastBarMs = parseAsBJ(lastBar.timestamp);
    const lastBarSlot = win.msToSlot(lastBarMs);
    const nowSlot = win.msToSlot(nowMs);

    if (nowSlot < 0 || nowSlot < lastBarSlot) {
      return [...bars.slice(0, -1), { ...lastBar, close: lastDone }];
    }
    if (nowSlot === lastBarSlot) {
      return [...bars.slice(0, -1), {
        ...lastBar,
        close: lastDone,
        high: Math.max(lastBar.high ?? lastDone, lastDone),
        low: Math.min(lastBar.low ?? lastDone, lastDone),
      }];
    }
    return [...bars, {
      timestamp: bjIsoFromMs(win.slotToMs(nowSlot)),
      open: lastDone, high: lastDone, low: lastDone, close: lastDone,
      volume: 0, turnover: 0,
    }];
  }, [bars, lastDone, win]);

  const isClosed = session === "closed";

  // Project bars → (slot idx, close) pairs, dropping bars that fall
  // outside the window (HK lunch, stale data leaking from sessions=all).
  const points = useMemo(() => {
    if (!renderedBars || renderedBars.length === 0) return [];
    const out: { x: number; close: number | null }[] = [];
    for (const b of renderedBars) {
      const slot = win.msToSlot(parseAsBJ(b.timestamp));
      if (slot < 0) continue;
      out.push({ x: (slot / win.slotCount) * VB_W, close: b.close ?? null });
    }
    return out;
  }, [renderedBars, win]);

  // Y-axis bounds (pad ±20% so the line never touches the top/bottom edge).
  const { yLo, yHi } = useMemo(() => {
    const closes = points.map((p) => p.close).filter((c): c is number => c != null);
    if (closes.length === 0) return { yLo: 0, yHi: 1 };
    const lo = Math.min(...closes);
    const hi = Math.max(...closes);
    const pad = (hi - lo) * 0.2 || Math.abs(lo) * 0.005 || 0.5;
    return { yLo: lo - pad, yHi: hi + pad };
  }, [points]);

  const yFor = (close: number): number =>
    yHi === yLo ? VB_H / 2 : ((yHi - close) / (yHi - yLo)) * VB_H;

  // Build line + area path strings. Null close → gap (next segment
  // starts with M not L).
  const { linePath, areaPath } = useMemo(() => {
    if (points.length === 0) return { linePath: "", areaPath: "" };
    let line = "";
    let area = "";
    let segmentStart = true;
    let firstX = points[0].x;
    let lastX = points[0].x;
    for (const p of points) {
      if (p.close == null) {
        segmentStart = true;
        continue;
      }
      const cmd = segmentStart ? "M" : "L";
      line += `${cmd}${p.x.toFixed(2)},${yFor(p.close).toFixed(2)} `;
      if (segmentStart) {
        // Start the area at the baseline (bottom) so the fill closes neatly.
        area += `M${p.x.toFixed(2)},${VB_H} L${p.x.toFixed(2)},${yFor(p.close).toFixed(2)} `;
      } else {
        area += `L${p.x.toFixed(2)},${yFor(p.close).toFixed(2)} `;
      }
      lastX = p.x;
      segmentStart = false;
    }
    if (area) area += `L${lastX.toFixed(2)},${VB_H} L${firstX.toFixed(2)},${VB_H} Z`;
    return { linePath: line.trim(), areaPath: area.trim() };
  }, [points, yFor, yLo, yHi]); // eslint-disable-line react-hooks/exhaustive-deps

  // Color decision: pos when last >= open, else neg.
  const lastClose = points.length > 0 ? points[points.length - 1].close : null;
  const refOpen = openPrice ?? (points.length > 0 ? points[0].close : null);
  const isPos = lastClose != null && refOpen != null
    ? lastClose >= refOpen
    : true;

  // Pulse dot pixel coords. Read each render (re-renders happen on
  // every quote push → fresh nowMs).
  const pulse = useMemo(() => {
    if (isClosed || lastDone == null || containerSize.w === 0) return null;
    const x = win.progress(Date.now()) * containerSize.w;
    const yVb = yFor(lastDone);
    const y = (yVb / VB_H) * containerSize.h;
    return { x, y };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isClosed, lastDone, containerSize.w, containerSize.h, win, yLo, yHi]);

  if (!bars) {
    return (
      <div ref={containerRef} className="ispark">
        <div className="ispark-skeleton" aria-label="加载分时线…" />
      </div>
    );
  }

  const rootClass = [
    "ispark",
    isPos ? "pos" : "neg",
    isClosed ? "is-closed" : "",
  ].filter(Boolean).join(" ");

  const fillId = isPos ? "ispark-fill-up" : "ispark-fill-down";

  return (
    <div ref={containerRef} className={rootClass}>
      <svg className="ispark-svg" viewBox={`0 0 ${VB_W} ${VB_H}`} preserveAspectRatio="none">
        <text className="ispark-watermark" x="50%" y="58%">{win.label}</text>
        {areaPath && <path className="ispark-area" d={areaPath} fill={`url(#${fillId})`} />}
        {linePath && <path className="ispark-line" d={linePath} />}
      </svg>
      {pulse && (
        <span
          className="ispark-pulse"
          style={{ left: `${pulse.x}px`, top: `${pulse.y}px` }}
          aria-hidden
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test -- IntradaySpark.test.tsx --run`
Expected: PASS.

Note: jsdom's `ResizeObserver` is missing by default. If a test fails with `ReferenceError: ResizeObserver is not defined`, add this polyfill to `frontend/src/test-setup.ts` (check first; might already be there):

```ts
// Polyfill for jsdom — IntradaySpark uses ResizeObserver to measure
// its container for pulse-dot positioning.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as any;
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/IntradaySpark.tsx frontend/src/components/Positions/IntradaySpark.test.tsx frontend/src/test-setup.ts
git commit -m "$(cat <<'EOF'
feat(frontend/positions): IntradaySpark SVG component

Session-aware spark sized to its container via stretched viewBox.
Watermark, area fill, and line all rendered as SVG; pulse dot is a
sibling DOM element so its halo can animate independently of chart
redraw. Live tip merge: last close overwritten in-place inside the
current minute bucket, new bar appended on bucket cross. Closed state
omits pulse and dims the line.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Update `PositionCard.tsx` — swap chart + fix baseline

**Files:**
- Modify: `frontend/src/components/Positions/PositionCard.tsx`
- Modify: `frontend/src/components/Positions/PositionCard.test.tsx`

Two coordinated changes: replace `<MiniLine>` with `<IntradaySpark>`, and switch Day P/L baseline to `today_close` in post / overnight to mirror the backend's session-aware `change_pct`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/Positions/PositionCard.test.tsx`:
```tsx
import { vi } from "vitest";

describe("PositionCard — session-aware Day P/L baseline", () => {
  it("uses today_close as baseline in post session", () => {
    const postQuote: Quote = {
      ...quote,
      trade_session: "post",
      prev_close: 240,   // yesterday's close — should NOT be used
      today_close: 245,  // today's RTH close — should be used
      last_done: 246,    // up $1 vs today_close (post-market rise)
      change: 1,
      change_pct: 0.41,
    };
    // No today trades — qty_start == qty_now == 240
    // Day P/L = 246 × 240 + 0 - 0 - 245 × 240 = 240
    render(
      <PositionCard
        position={position}
        quote={postQuote}
        intraday={intraday}
        executions={[]}
        onClick={vi.fn()}
      />,
    );
    expect(screen.getByText(/\+\$240/)).toBeInTheDocument();
  });

  it("falls back to prev_close in regular session", () => {
    // Same setup as the existing dayPl test — verifies baseline is
    // prev_close (240) when session is regular.
    render(
      <PositionCard
        position={position}
        quote={quote}  // trade_session: "regular"
        intraday={intraday}
        executions={[]}
        onClick={vi.fn()}
      />,
    );
    // Day P/L = (245.50 - 240) × 240 = 1320
    expect(screen.getByText(/\+\$1,320/)).toBeInTheDocument();
  });
});

describe("PositionCard — IntradaySpark wiring", () => {
  it("mounts IntradaySpark when intraday bars are present", () => {
    const { container } = render(
      <PositionCard
        position={position}
        quote={quote}
        intraday={intraday}
        onClick={vi.fn()}
      />,
    );
    expect(container.querySelector(".ispark")).not.toBeNull();
    expect(container.querySelector(".minline")).toBeNull();
  });

  it("passes session=closed when quote.trade_session is closed", () => {
    const closedQuote: Quote = { ...quote, trade_session: "closed" };
    const { container } = render(
      <PositionCard
        position={position}
        quote={closedQuote}
        intraday={intraday}
        onClick={vi.fn()}
      />,
    );
    expect(container.querySelector(".ispark.is-closed")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- PositionCard.test.tsx --run`
Expected: FAIL — the new tests can't find `.ispark` (still rendering `.minline`) or use wrong baseline.

- [ ] **Step 3: Apply the swap + baseline fix**

Edit `frontend/src/components/Positions/PositionCard.tsx`:

a) Replace the `MiniLine` import (line 3) with the new pair plus helper:
```ts
import { IntradaySpark } from "./IntradaySpark";
import { marketOf } from "../Card/cardHelpers";
```
(Delete the `import { MiniLine } from "./MiniLine";` line.)

b) Inside the component, locate the `rawValues` / `values` `useMemo` block (lines 75-85). Delete the entire block — `IntradaySpark` handles the live-tip merge internally.

c) Locate the Day P/L `useMemo` (lines 103-128). Replace its dependency on `prevClose` with a session-aware `dayBaseline`. Insert above the `useMemo`:
```ts
// Day P/L baseline matches the backend's session-aware change_pct rule:
//   pre / regular / closed → yesterday's RTH close (prev_close)
//   post / overnight       → today's RTH close (today_close, frozen at
//                            16:00 ET when post starts)
// today_close is null in non-post/overnight sessions; we fall back to
// prev_close to keep the dayPl formula well-defined even on transient
// data gaps.
const tradeSession = quote?.trade_session ?? "regular";
const todayClose = toUsd(sym, quote?.today_close);
const dayBaseline =
  (tradeSession === "post" || tradeSession === "overnight") && todayClose != null
    ? todayClose
    : prevClose;
```

Then inside the `useMemo`, replace every `prevClose` reference with `dayBaseline`:
- Replace `if (last == null || prevClose == null) {` with `if (last == null || dayBaseline == null) {`
- Replace `return last * qty + sellsProceeds - buysCost - prevClose * qtyStart;` with `return last * qty + sellsProceeds - buysCost - dayBaseline * qtyStart;`
- Update the dependency array: change `[last, prevClose, change, qty, executions, sym]` to `[last, dayBaseline, change, qty, executions, sym]`.

d) Locate the `<MiniLine ... />` JSX (around line 184-188). Replace the whole `.pcard-chart` block:

Before:
```tsx
<div className="pcard-chart">
  {values.length > 0 ? (
    <MiniLine values={values} openPrice={quote?.open ?? null} />
  ) : (
    <div className="pcard-chart-skeleton" aria-label="加载分时线..." />
  )}
</div>
```

After:
```tsx
<div className="pcard-chart">
  <IntradaySpark
    symbol={position.symbol}
    market={marketOf(position.symbol)}
    bars={intraday?.bars}
    session={tradeSession}
    lastDone={last}
    openPrice={quote?.open ?? null}
  />
</div>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- PositionCard.test.tsx --run`
Expected: PASS — all existing tests + the 3 new ones.

Existing test "computes intraday-aware Day P/L from today's trades" uses regular session, so it still passes (baseline = prev_close).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/PositionCard.tsx frontend/src/components/Positions/PositionCard.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend/positions): PositionCard → IntradaySpark + session-aware Day P/L

Swap the chart.js MiniLine for the new SVG IntradaySpark, and switch the
Day P/L baseline from prev_close to today_close in post / overnight to
match the backend's session-aware change_pct convention. Regular and
pre sessions keep prev_close (the user-facing chip already matched —
this just aligns the dollar figure).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Update `PositionsPanel.tsx` — session-aware fetch + transition refetch

**Files:**
- Modify: `frontend/src/components/Positions/PositionsPanel.tsx`
- Modify: `frontend/src/components/Positions/PositionsPanel.test.tsx`

Two changes: initial candle fetch uses `granularity=分时, sessions=<resolved>`; a second effect diffs `quote.trade_session` per symbol via `useRef` so a session transition triggers exactly one refetch. Plus mount `<SparkDefs />`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/Positions/PositionsPanel.test.tsx` (adjust mocks to match existing test style):
```tsx
describe("PositionsPanel — session-aware candle fetch", () => {
  it("fetches granularity=分时 with the current session on mount", async () => {
    // Mock api.candlesticks. Verify it's called with
    // { granularity: "分时", sessions: <resolved> } for each stock.
    const candleSpy = vi.spyOn(api, "candlesticks").mockResolvedValue({
      symbol: "TSLA.US", period: "today", bars: [],
    });
    // Seed positions store with a stock + quotes store with a regular-session quote
    usePositionsStore.setState({
      stocks: [{ symbol: "TSLA.US", ticker: "TSLA", quantity: 100, avg_cost: 100, type: "stock", option_strike: null, option_expiry: null, option_type: null }],
      options: [],
    });
    useQuotesStore.setState({
      quotesBySymbol: {
        "TSLA.US": { ...quoteFixture, symbol: "TSLA.US", trade_session: "regular" },
      },
      lastUpdatedAt: Date.now(),
    });

    render(<PositionsPanel />);
    await waitFor(() => {
      expect(candleSpy).toHaveBeenCalledWith(
        "TSLA.US", "today",
        expect.objectContaining({ granularity: "分时", sessions: "regular" }),
      );
    });
  });

  it("refetches when trade_session transitions regular → post", async () => {
    const candleSpy = vi.spyOn(api, "candlesticks").mockResolvedValue({
      symbol: "TSLA.US", period: "today", bars: [],
    });
    usePositionsStore.setState({
      stocks: [{ symbol: "TSLA.US", ticker: "TSLA", quantity: 100, avg_cost: 100, type: "stock", option_strike: null, option_expiry: null, option_type: null }],
      options: [],
    });
    useQuotesStore.setState({
      quotesBySymbol: {
        "TSLA.US": { ...quoteFixture, symbol: "TSLA.US", trade_session: "regular" },
      },
      lastUpdatedAt: Date.now(),
    });

    render(<PositionsPanel />);
    await waitFor(() => expect(candleSpy).toHaveBeenCalledTimes(1));

    // Simulate session transition: regular → post. quotesBySymbol is a
    // new object reference; the panel's effect should detect the per-
    // symbol change and refetch with sessions=post.
    useQuotesStore.setState({
      quotesBySymbol: {
        "TSLA.US": { ...quoteFixture, symbol: "TSLA.US", trade_session: "post" },
      },
      lastUpdatedAt: Date.now(),
    });

    await waitFor(() => {
      expect(candleSpy).toHaveBeenCalledTimes(2);
      expect(candleSpy).toHaveBeenLastCalledWith(
        "TSLA.US", "today",
        expect.objectContaining({ granularity: "分时", sessions: "post" }),
      );
    });
  });

  it("does NOT refetch on quote-push within the same session", async () => {
    const candleSpy = vi.spyOn(api, "candlesticks").mockResolvedValue({
      symbol: "TSLA.US", period: "today", bars: [],
    });
    usePositionsStore.setState({
      stocks: [{ symbol: "TSLA.US", ticker: "TSLA", quantity: 100, avg_cost: 100, type: "stock", option_strike: null, option_expiry: null, option_type: null }],
      options: [],
    });
    useQuotesStore.setState({
      quotesBySymbol: {
        "TSLA.US": { ...quoteFixture, symbol: "TSLA.US", trade_session: "regular" },
      },
      lastUpdatedAt: Date.now(),
    });

    render(<PositionsPanel />);
    await waitFor(() => expect(candleSpy).toHaveBeenCalledTimes(1));

    // 5 same-session pushes — should NOT refetch.
    for (let i = 0; i < 5; i++) {
      useQuotesStore.setState({
        quotesBySymbol: {
          "TSLA.US": {
            ...quoteFixture,
            symbol: "TSLA.US",
            trade_session: "regular",
            last_done: 100 + i,
          },
        },
        lastUpdatedAt: Date.now(),
      });
    }
    await new Promise((r) => setTimeout(r, 50));
    expect(candleSpy).toHaveBeenCalledTimes(1);
  });
});
```

You will need to import `api`, `waitFor`, `useQuotesStore`, `usePositionsStore`, and a `quoteFixture` const at the top of the file. Look at the existing test file's imports — if a quote fixture isn't defined, define one inline:
```ts
const quoteFixture: Quote = {
  symbol: "TSLA.US", last_done: 100, prev_close: 100, today_close: null,
  open: 100, high: 100, low: 100, volume: 0, turnover: 0,
  change: 0, change_pct: 0, trade_session: "regular",
};
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- PositionsPanel.test.tsx --run`
Expected: FAIL — current fetch uses default `granularity=5min, sessions=regular`, not `granularity=分时`.

- [ ] **Step 3: Rewrite the fetch logic**

Edit `frontend/src/components/Positions/PositionsPanel.tsx`:

a) Add imports near the top:
```ts
import { marketOf } from "../Card/cardHelpers";
import { resolveSessionParam } from "./resolveSessionParam";
import { SparkDefs } from "./SparkDefs";
```

b) Replace the `fetchCandles` function body inside `usePositionsData`. Locate the `const fetchCandles = async () => { ... }` block (lines 55-74) and replace with:

```ts
const fetchCandles = async () => {
  for (const p of stocks) {
    if (cancelled) return;
    const sess = useQuotesStore.getState().quotesBySymbol[p.symbol]?.trade_session ?? "regular";
    const sessionParam = resolveSessionParam(marketOf(p.symbol), sess);
    try {
      const c = await api.candlesticks(p.symbol, "today", {
        granularity: "分时",
        sessions: sessionParam,
      });
      if (!cancelled) {
        setBars(candleCacheKey(p.symbol, "today", "分时", sessionParam), c);
      }
    } catch (e) {
      console.warn("candlesticks fetch failed", p.symbol, e);
    }
  }
  // Options keep their existing 30-day daily-K fetch — unchanged.
  for (const p of options) {
    if (cancelled) return;
    try {
      const c = await api.candlesticks(p.symbol, "30");
      if (!cancelled) setBars(candleCacheKey(p.symbol, "30"), c);
    } catch (e) {
      console.warn("option candlesticks fetch failed", p.symbol, e);
    }
  }
};
```

c) Below `usePositionsData`, add a second hook for session-transition refetch:
```ts
/** Refetch a single stock's intraday bars when its trade_session changes.
 *  We diff per-symbol via useRef so the effect doesn't fire on every push
 *  (quotesBySymbol reference identity changes on every WS update). */
function useSessionTransitionRefetch(stocks: Position[]): void {
  const setBars = useCandlesticksStore((s) => s.setBars);
  const quotesBySymbol = useQuotesStore((s) => s.quotesBySymbol);
  const lastSessionRef = useRef<Record<string, string>>({});

  useEffect(() => {
    for (const p of stocks) {
      const cur = quotesBySymbol[p.symbol]?.trade_session;
      if (!cur) continue;
      const prev = lastSessionRef.current[p.symbol];
      if (prev !== cur) {
        lastSessionRef.current[p.symbol] = cur;
        if (prev !== undefined) {
          // True transition — refetch.
          const sessionParam = resolveSessionParam(marketOf(p.symbol), cur);
          void api.candlesticks(p.symbol, "today", {
            granularity: "分时",
            sessions: sessionParam,
          }).then((c) => {
            setBars(candleCacheKey(p.symbol, "today", "分时", sessionParam), c);
          }).catch((e) => {
            console.warn("session-transition refetch failed", p.symbol, e);
          });
        }
      }
    }
  }, [quotesBySymbol, stocks, setBars]);
}
```

You'll need to import `useEffect, useRef` from `react`, `Position` from domain-types, and the helpers as already imported above.

d) In `PositionsPanel`, call the new hook and update the stock card cache lookup:
```ts
export function PositionsPanel() {
  const stocks = usePositionsStore((s) => s.stocks);
  const options = usePositionsStore((s) => s.options);
  usePositionsData(stocks, options);
  useSessionTransitionRefetch(stocks);   // ← new line
  // ... existing code ...
```

e) Update the `<PositionCard>` render — replace the `intraday={candleByKey[candleCacheKey(p.symbol, "today")]}` prop with:
```tsx
intraday={(() => {
  const sess = quotesBySymbol[p.symbol]?.trade_session ?? "regular";
  const sessionParam = resolveSessionParam(marketOf(p.symbol), sess);
  return candleByKey[candleCacheKey(p.symbol, "today", "分时", sessionParam)];
})()}
```

f) Mount `<SparkDefs />` once at the top of the rendered JSX (inside `<aside className="positions-panel">`):
```tsx
return (
  <aside className="positions-panel">
    <SparkDefs />
    <div className="positions-panel-top">
      ...
```
Also add it to the drill-down detail branch (line 170-176) so a card → detail → back round-trip doesn't tear down the defs:
```tsx
if (pos) {
  return (
    <aside className="positions-panel">
      <SparkDefs />
      <DetailPane position={pos} onBack={() => selectSymbol(null)} />
    </aside>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npm test -- PositionsPanel.test.tsx --run`
Expected: PASS — all existing tests + the 3 new ones.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/PositionsPanel.tsx frontend/src/components/Positions/PositionsPanel.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend/positions): session-aware candle fetch + transition refetch

Initial card fetch now uses granularity=分时, sessions=<resolved current
trade_session>. A second effect diffs quote.trade_session per symbol
via useRef so cross-session transitions (e.g. 盘中→盘后 at 04:00 BJ)
trigger exactly one refetch rather than one per push. SparkDefs mounted
once at the panel root so all cards share gradient ids.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: CSS — `.ispark*` selectors + neutral session pill

**Files:**
- Modify: `frontend/src/components/Positions/Positions.css`

- [ ] **Step 1: Apply the CSS**

Append to `frontend/src/components/Positions/Positions.css`:
```css
/* ─── Intraday spark (股票卡片专用 SVG sparkline) ─── */
.ispark {
  position: relative;
  width: 100%;
  height: 100%;
}
.ispark-svg {
  display: block;
  width: 100%;
  height: 100%;
  overflow: visible;
}

/* 背景水印 — 大字号低透明度居中。SVG <text>。 */
.ispark-watermark {
  font-family: var(--font-sans);
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-anchor: middle;
  dominant-baseline: central;
  fill: var(--fg-3);
  opacity: 0.10;
  pointer-events: none;
  user-select: none;
}
.ispark.is-closed .ispark-watermark {
  opacity: 0.08;
  letter-spacing: 0.22em;
}

/* 曲线 — 颜色跟 .ispark.pos / .ispark.neg 切换 */
.ispark-line {
  fill: none;
  stroke-width: 1.4;
  stroke-linejoin: round;
  stroke-linecap: round;
  vector-effect: non-scaling-stroke;
}
.ispark.pos .ispark-line { stroke: var(--up-color); }
.ispark.neg .ispark-line { stroke: var(--down-color); }
.ispark.is-closed .ispark-line {
  stroke: var(--fg-3);
  opacity: 0.7;
}

/* 渐变填充 — 引用 SparkDefs 的全局 <defs> id */
.ispark-area { stroke: none; }
.ispark.is-closed .ispark-area { opacity: 0.3; }

/* Pulse dot — DOM 节点，复用 minline-pulse keyframes */
.ispark-pulse {
  position: absolute;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--pulse-color);
  transform: translate(-50%, -50%);
  pointer-events: none;
  box-shadow: 0 0 0 1.5px rgba(0, 0, 0, 0.4);
}
.ispark.pos .ispark-pulse { --pulse-color: var(--up-color); }
.ispark.neg .ispark-pulse { --pulse-color: var(--down-color); }
.ispark-pulse::before {
  content: "";
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  background: var(--pulse-color);
  opacity: 0.5;
  animation: minline-pulse 1.8s ease-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .ispark-pulse::before { animation: none; }
}

/* Skeleton — 与 .pcard-chart-skeleton 视觉一致 */
.ispark-skeleton {
  height: 100%;
  background: linear-gradient(
    90deg, transparent, rgba(255, 255, 255, 0.03), transparent
  );
  border-radius: 3px;
  animation: pcard-shimmer 1.4s linear infinite;
}
```

Then replace the existing `.pcard-session.sess-regular` selector. Find this rule (around line 236):
```css
.pcard-session.sess-regular  { color: var(--up-color); border-color: rgba(61, 214, 140, 0.4); background: rgba(61, 214, 140, 0.08); }
```
Replace with:
```css
.pcard-session.sess-regular {
  color: var(--brand);
  border-color: rgba(var(--brand-rgb), 0.4);
  background: rgba(var(--brand-rgb), 0.08);
}
```

- [ ] **Step 2: Visually verify in dev server**

Start the dev server: `cd frontend && npm run dev`. Open the dashboard. Confirm:

1. Stock cards show the new SVG spark with watermark text (盘中 / 盘前 / 盘后 / 夜盘 / 休市 per current state)
2. The top session pill on each card uses brand teal color, not up/down green/red
3. Pulse dot pulses near the right edge (or wherever the session-progress ratio puts it)
4. Color-mode toggle in LongPort settings → line / fill / pulse swap; watermark stays gray; session pill stays teal
5. Option cards still render their old MiniLine (verify the 30-day daily K hasn't changed)

If the watermark looks too prominent at small card sizes, drop `font-size` to 18px and re-check. The opacity 0.10 baseline should make it readable but unobtrusive.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Positions/Positions.css
git commit -m "$(cat <<'EOF'
feat(frontend/positions): IntradaySpark CSS + neutral session pill

Watermark, line, area, pulse, and skeleton selectors for the new SVG
spark. Pulse halo reuses minline-pulse keyframes (same visual,
reduced-motion-safe). Session-pill 盘中 state moves off --up-color
(which flips under CN color mode) onto --brand for color-mode-agnostic
neutrality — fixes the user-reported "盘中 红色" issue.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Full test suite + manual dev-server walkthrough

**Files:** none modified — verification only.

- [ ] **Step 1: Run the entire frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: PASS (or only pre-existing failures unrelated to this work).

If the test runner reports `Cannot find module './MiniLine'` from any non-option-card test, the MiniLine import wasn't actually removed where expected. Re-check `PositionCard.tsx`.

- [ ] **Step 2: Manual walkthrough on dev server**

Start: `cd frontend && npm run dev`. With the dashboard open, exercise the matrix from §8 of the spec:

| Scenario | Verify |
|---|---|
| US regular session (BJ 21:30-04:00) | 盘中 watermark; pulse at progress ratio; line + fill in up/down color |
| US post session (BJ 04:00-08:00) | 盘后 watermark; new pulse position; verify Day P/L matches today_close baseline |
| US overnight (BJ 08:00-16:00) | 夜盘 watermark; sparse bars (typical for overnight); pulse on the right |
| US closed (weekends, holidays) | 休市 watermark; previous Friday's post snapshot; **no pulse** |
| HK regular (BJ 09:30-16:00) | 盘中 watermark; lunch (BJ 12:00-13:00) compressed away; pulse advances smoothly through the morning→afternoon transition |
| Color flip (LongPort settings → US ↔ CN) | Line + fill + pulse all swap colors; watermark stays gray; session pill stays brand teal |
| Live tick at minute boundary | Watch a single bar for 60+ seconds: close should update in-place; at the minute roll, a new bar appears at the right edge |

- [ ] **Step 3: Tag the commit history**

No commit needed for this task — but verify `git log --oneline -15` shows clean, single-purpose commits and no rogue formatting changes.

```bash
git log --oneline -15
```
Expected output (in order, most recent first):
```
<hash> feat(frontend/positions): IntradaySpark CSS + neutral session pill
<hash> feat(frontend/positions): session-aware candle fetch + transition refetch
<hash> feat(frontend/positions): PositionCard → IntradaySpark + session-aware Day P/L
<hash> feat(frontend/positions): IntradaySpark SVG component
<hash> feat(frontend/positions): SparkDefs — shared gradient defs
<hash> feat(frontend/positions): sessionWindow resolver
<hash> feat(frontend/positions): resolveSessionParam pure helper
<hash> feat(frontend/cards): marketOf helper
<hash> feat(frontend/tokens): add --brand-rgb companion to --brand
<hash> docs(specs): card intraday chart design
... (prior history)
```

If anything is missing or out of order, you can `git rebase -i` to clean up — but only if commits haven't been pushed.

---

## Self-Review

**Spec coverage:**

| Spec section | Plan task | Status |
|---|---|---|
| §1 Component contract | Task 6 + 7 | ✓ (props match) |
| §2 sessionWindow resolver | Task 4 | ✓ (windows, slot math, closed fallback, DST) |
| §3 SVG render structure | Task 6 + 9 | ✓ (DOM + CSS) |
| §4 Live tick integration | Task 6 (renderedBars useMemo) | ✓ |
| §5 Refetch on session change | Task 8 | ✓ (useSessionTransitionRefetch + useRef diff) |
| §6 Day P/L baseline unification | Task 7 | ✓ (dayBaseline derived from trade_session) |
| §7 Styling | Task 1 + 9 | ✓ (brand-rgb + .ispark*) |
| §8 Test plan | Tasks 3-8 (TDD throughout) | ✓ |

**Placeholder scan:** none — every code block contains the literal code to write.

**Type consistency:** `Market` and `SessionLabel` defined in `sessionWindow.ts`, exported; consumed by `IntradaySpark.tsx` and `resolveSessionParam.ts`. `TradeSession` (in `resolveSessionParam.ts`) is structurally identical to `SessionLabel` but kept distinct so the two helpers can evolve independently — both tasks list the exact union members.

**Known follow-ups (out of scope for this plan, noted in spec §"Non-Goals"):**
- Crosshair / hover tooltips on cards
- Public holiday awareness in `lastTradingDateKey` (currently weekday-only)
- Option card intraday support
- Detail pane chart unification with the new SVG approach
