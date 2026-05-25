# Quote `trading_day` for Holiday-Correct Day P/L — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Day P/L on stock + option cards stays correct when the most recent trading day is more than 2 calendar days behind "now" (US holiday weekends, half-day holidays, etc).

**Architecture:** Broker reports a new `trading_day` field on each `QuoteOut` — the ET (or HKT / CST) calendar date that the quote actually belongs to, resolved via the broker's `trading_days` calendar so holidays are handled. Frontend's `dayPl` reducer in `PositionCard` / `OptionCard` filters today's executions against `quote.trading_day` instead of the wall-clock-derived `currentOrLastTradingDay()`. Backend `/api/broker/today_executions` widens its DB read window from `now − 2 days` to `now − 7 days` so the fills from the most recent trading day are always present for the frontend to filter precisely.

**Tech Stack:** FastAPI + Pydantic (backend), SQLite via SQLAlchemy (DB), React + Vitest + Zustand (frontend), `openapi-typescript` for type sync.

**Out of scope:** the `effectiveSession` pill still says `盘中` on holidays — separate bug, file as a follow-up. The `_market_state_for` holiday handling is already correct via `MarketSchedule`; this plan trusts it.

---

## File Structure

**Backend (modify):**
- `backend/app/broker/market_schedule.py` — add `current_or_last_trading_day()` method
- `backend/app/broker/longport_client.py` — `_quote_to_dict()` gains `trading_day` param; HTTP path (`get_quote`) and push path (`_on_quote`) populate it via the schedule
- `backend/app/api/schemas.py` — `QuoteOut` gains `trading_day: str | None = None`
- `backend/app/api/http.py:1145-1151` — widen `since = now - 2 days` to `now - 7 days`

**Backend (test):**
- `backend/tests/broker/test_market_schedule.py` — new tests for `current_or_last_trading_day`
- `backend/tests/broker/test_quote_to_dict.py` — new test that `trading_day` is plumbed through

**Frontend (modify):**
- `frontend/src/api/types.ts` — regenerated via `npm run gen:types` (will add `trading_day?: string | null`)
- `frontend/src/components/Positions/PositionCard.tsx:111-140` — `dayPl` uses `quote.trading_day ?? currentOrLastTradingDay()`
- `frontend/src/components/Positions/OptionCard.tsx:102-130` — same change

**Frontend (test):**
- `frontend/src/components/Positions/PositionCard.test.tsx` — new "uses quote.trading_day on a holiday Monday" test
- `frontend/src/components/Positions/OptionCard.test.tsx` — same

---

## Task 1: `MarketSchedule.current_or_last_trading_day()`

**Files:**
- Modify: `backend/app/broker/market_schedule.py` (add method to `MarketSchedule` class, near `last_trading_day` at line 251)
- Test: `backend/tests/broker/test_market_schedule.py` (append new test block)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/broker/test_market_schedule.py`:

```python
# --- current_or_last_trading_day -----------------------------------------


@pytest.mark.asyncio
async def test_current_or_last_trading_day_during_regular_session() -> None:
    """US 10:30 ET on a trading day → returns that date."""
    sch = MarketSchedule(_seed_sessions_via_fake())
    await sch.force_refresh()
    # 2030-01-02 14:30 UTC = 09:30 ET, Wed, in cached trading days.
    now = datetime(2030, 1, 2, 14, 30, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2030, 1, 2)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_us_holiday_returns_prior_trading_day() -> None:
    """US Memorial Day Monday (gap in cached calendar) → returns the
    prior Friday from the cached trading days."""
    broker = FakeBrokerClient()
    broker.trading_sessions_map = {  # type: ignore[attr-defined]
        "US": [
            (time(4, 0), time(9, 30), "pre"),
            (time(9, 30), time(16, 0), "regular"),
            (time(16, 0), time(20, 0), "post"),
        ],
    }
    # Cached: Fri 5/22, (skip Mon 5/25 holiday), Tue 5/26 - newest first.
    broker.trading_days_map = {  # type: ignore[attr-defined]
        "US": [date(2026, 5, 26), date(2026, 5, 22), date(2026, 5, 21)],
    }
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # 2026-05-25 14:30 UTC = 10:30 EDT, Memorial Day Monday.
    now = datetime(2026, 5, 25, 14, 30, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 22)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_us_saturday_returns_friday() -> None:
    """US Saturday morning → returns the prior Friday."""
    broker = FakeBrokerClient()
    broker.trading_sessions_map = {  # type: ignore[attr-defined]
        "US": [(time(9, 30), time(16, 0), "regular")],
    }
    broker.trading_days_map = {  # type: ignore[attr-defined]
        "US": [date(2026, 5, 22), date(2026, 5, 21)],
    }
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # 2026-05-23 14:30 UTC = 10:30 EDT, Saturday.
    now = datetime(2026, 5, 23, 14, 30, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 22)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_overnight_tail_rolls_back() -> None:
    """US 02:00 ET = tail of yesterday's overnight session → yesterday's
    date (the trading day that started at yesterday's pre-market)."""
    broker = FakeBrokerClient()
    broker.trading_sessions_map = {  # type: ignore[attr-defined]
        "US": [
            (time(4, 0), time(9, 30), "pre"),
            (time(9, 30), time(16, 0), "regular"),
            (time(16, 0), time(20, 0), "post"),
            (time(20, 0), time(23, 59, 59), "overnight"),
            (time(0, 0), time(4, 0), "overnight"),
        ],
    }
    broker.trading_days_map = {  # type: ignore[attr-defined]
        "US": [date(2026, 5, 22), date(2026, 5, 21), date(2026, 5, 20)],
    }
    sch = MarketSchedule(broker)
    await sch.force_refresh()
    # Fri 2026-05-22 06:00 UTC = Fri 02:00 EDT — tail of Thursday's overnight.
    now = datetime(2026, 5, 22, 6, 0, tzinfo=timezone.utc)
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 21)


@pytest.mark.asyncio
async def test_current_or_last_trading_day_cold_cache_returns_local_date() -> None:
    """Before the first refresh (no sessions cached), fall back to the
    local market date so callers get a sane non-None value."""
    sch = MarketSchedule(FakeBrokerClient())  # no refresh
    now = datetime(2026, 5, 25, 14, 30, tzinfo=timezone.utc)
    # 10:30 EDT → 2026-05-25
    assert sch.current_or_last_trading_day("US", now) == date(2026, 5, 25)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest tests/broker/test_market_schedule.py::test_current_or_last_trading_day_during_regular_session -v
```

Expected: `AttributeError: 'MarketSchedule' object has no attribute 'current_or_last_trading_day'`.

- [ ] **Step 3: Implement the method**

Add to `backend/app/broker/market_schedule.py`, immediately after the `last_trading_day` method (around line 262):

```python
    def current_or_last_trading_day(
        self, market: str, now: datetime | None = None
    ) -> date:
        """Trading day this ``now`` belongs to, as a local-market date.

        - Live session (regular / pre / post): today's local date.
        - Overnight 00:00-04:00 tail: the prior local date (the trading
          day that opened with yesterday's pre-market — ``state_for``
          guarantees the prior date is a real trading day before
          returning "overnight" here).
        - Closed (weekend / holiday): the most recent past trading day
          from the broker's calendar.
        - Cold cache: today's local date (best effort).

        Used by ``_quote_to_dict`` to stamp each quote with the trading
        day it belongs to, so the frontend can filter today's executions
        without trying to recompute holiday-aware calendar math
        client-side.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        if market in ("SH", "SZ"):
            market_key = "CN"
        else:
            market_key = market
        local = now.astimezone(_market_tz(market_key))
        local_date = local.date()

        state = self.state_for(market, now)
        if state == "overnight" and local.time() < time(4, 0):
            return local_date - timedelta(days=1)
        if state in ("regular", "pre", "post", "overnight"):
            return local_date

        # state == "closed" — walk back through the calendar.
        prior = self.last_trading_day(market, before=local_date)
        return prior if prior is not None else local_date
```

Make sure `timedelta` is imported at the top of the file; if not, add it to the existing `from datetime import ...` line.

- [ ] **Step 4: Run all market_schedule tests**

```bash
cd backend && uv run pytest tests/broker/test_market_schedule.py -v
```

Expected: PASS (all existing + 5 new tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/broker/market_schedule.py backend/tests/broker/test_market_schedule.py
git commit -m "$(cat <<'EOF'
feat(market-schedule): current_or_last_trading_day(market, now)

Returns the trading day a given instant belongs to, walking back through
the broker's calendar on weekends / holidays. Used in the next commit to
stamp each Quote with the trading day so the frontend can filter
today's executions without doing client-side holiday math.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `QuoteOut.trading_day` schema field

**Files:**
- Modify: `backend/app/api/schemas.py:304-327`

- [ ] **Step 1: Add the field**

Edit `QuoteOut` in `backend/app/api/schemas.py` — append after the existing `trade_session` field (around line 327):

```python
    # ET (or HKT / CST) calendar date that ``last_done`` belongs to,
    # as ISO ``YYYY-MM-DD``. Resolved server-side from the broker's
    # trading-days calendar so weekends + holidays are handled. The
    # frontend uses this to filter "today's executions" for Day P/L
    # without needing its own holiday calendar. ``None`` when the
    # broker calendar cache is cold (frontend falls back to wall clock).
    trading_day: str | None = None
```

- [ ] **Step 2: Verify schema dump renders the new field**

```bash
cd backend && uv run python -c "from app.api.schemas import QuoteOut; print(QuoteOut.model_json_schema().get('properties', {}).get('trading_day'))"
```

Expected output (something like):
```
{'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None, 'title': 'Trading Day', ...}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/schemas.py
git commit -m "$(cat <<'EOF'
feat(api/schemas): add QuoteOut.trading_day (ISO date)

Stamps each quote with the ET / HKT / CST calendar date that
``last_done`` belongs to. Populated server-side in the next commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Plumb `trading_day` through `_quote_to_dict` + both quote paths

**Files:**
- Modify: `backend/app/broker/longport_client.py:64-150` (`_quote_to_dict`), `:446-476` (`get_quote`), `:995-1055` (`_on_quote`)
- Test: `backend/tests/broker/test_quote_to_dict.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/broker/test_quote_to_dict.py`:

```python
def test_trading_day_field_is_threaded_through() -> None:
    """`_quote_to_dict` accepts a `trading_day` kwarg and surfaces it
    verbatim in the output dict. Callers (HTTP + push handler) compute
    the value via `MarketSchedule.current_or_last_trading_day` and pass
    it in — the converter itself does not call the schedule."""
    q = _security_quote(symbol="TSLA.US", last_done=250.0, prev_close=240.0)
    row = _quote_to_dict(q, state="regular", trading_day="2026-05-22")
    assert row["trading_day"] == "2026-05-22"


def test_trading_day_defaults_to_none_when_not_provided() -> None:
    """Backwards-compat: callers that don't pass `trading_day` get
    `None` (the frontend falls back to wall-clock in that case)."""
    q = _security_quote(symbol="TSLA.US")
    row = _quote_to_dict(q, state="regular")
    assert row["trading_day"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/broker/test_quote_to_dict.py::test_trading_day_field_is_threaded_through -v
```

Expected: `TypeError: _quote_to_dict() got an unexpected keyword argument 'trading_day'` (or `KeyError` after that's fixed).

- [ ] **Step 3: Add the `trading_day` parameter and output key**

Edit `backend/app/broker/longport_client.py` at the `_quote_to_dict` signature (line 64) and its return dict (line 138-150):

```python
def _quote_to_dict(
    q: Any,
    state: str | None = None,
    trading_day: str | None = None,
) -> dict[str, Any]:
```

Add `"trading_day": trading_day,` as the last field in the returned dict (after `"trade_session": state,` at line 149):

```python
    return {
        "last_done": last_done,
        "prev_close": prev_close,
        "today_close": today_close,
        "open": float(getattr(q, "open", 0) or 0),
        "high": float(getattr(chosen, "high", 0) or 0),
        "low": float(getattr(chosen, "low", 0) or 0),
        "volume": int(getattr(chosen, "volume", 0) or 0),
        "turnover": float(getattr(chosen, "turnover", 0) or 0),
        "change": change,
        "change_pct": change_pct,
        "trade_session": state,
        "trading_day": trading_day,
    }
```

- [ ] **Step 4: Add a helper on LongPortClient for market-keyed lookups**

Add a private helper near `_market_state_for` (around line 380) so both `get_quote` and `_on_quote` can stamp quotes uniformly:

```python
    def _trading_day_iso_for(self, symbol: str) -> str | None:
        """ISO date string for the trading day this symbol's quote
        belongs to. ``None`` when the schedule isn't bound yet — the
        frontend falls back to its wall-clock heuristic in that case.

        Lookup goes through the bound :class:`MarketSchedule` so
        holidays are respected (the schedule consults the broker's
        trading-days calendar)."""
        if self._market_schedule is None:
            return None
        market = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
        if market not in {"US", "HK", "SH", "SZ"}:
            return None
        try:
            day = self._market_schedule.current_or_last_trading_day(market)
        except Exception:
            logger.exception(
                "LongPortClient: trading_day lookup failed for %s", symbol,
            )
            return None
        return day.isoformat()
```

- [ ] **Step 5: Populate `trading_day` in `get_quote`**

In `backend/app/broker/longport_client.py:463-476`, change both `_quote_to_dict` call sites to pass `trading_day`:

```python
        result: dict[str, dict[str, Any]] = {}
        if stock_syms:
            for q in self._quote_ctx.quote(stock_syms):
                state = self._market_state_for(q.symbol)
                td = self._trading_day_iso_for(q.symbol)
                row = _quote_to_dict(q, state, trading_day=td)
                self._apply_closed_state_baseline(q.symbol, state, row)
                result[q.symbol] = row
        if option_syms:
            for q in self._quote_ctx.option_quote(option_syms):
                state = self._market_state_for(q.symbol)
                td = self._trading_day_iso_for(q.symbol)
                result[q.symbol] = _quote_to_dict(q, state, trading_day=td)
        return result
```

- [ ] **Step 6: Populate `trading_day` in `_on_quote` push path**

In `backend/app/broker/longport_client.py:1040-1052`, add `"trading_day"` to the push dict:

```python
            quote_dict: dict[str, Any] = {
                "last_done": last_done,
                "prev_close": prev_close,
                "today_close": float(today_close) if today_close else None,
                "open": float(getattr(event, "open", 0) or 0),
                "high": float(getattr(event, "high", 0) or 0),
                "low": float(getattr(event, "low", 0) or 0),
                "volume": int(getattr(event, "volume", 0) or 0),
                "turnover": float(getattr(event, "turnover", 0) or 0),
                "change": change,
                "change_pct": change_pct,
                "trade_session": state,
                "trading_day": self._trading_day_iso_for(symbol),
            }
```

- [ ] **Step 7: Run all broker tests to make sure nothing else broke**

```bash
cd backend && uv run pytest tests/broker/test_quote_to_dict.py tests/broker/test_longport_client.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/broker/longport_client.py backend/tests/broker/test_quote_to_dict.py
git commit -m "$(cat <<'EOF'
feat(broker): stamp Quote with trading_day from broker calendar

Threads a `trading_day` kwarg through `_quote_to_dict`; both
`get_quote` (HTTP) and `_on_quote` (push) populate it via
`MarketSchedule.current_or_last_trading_day`, which knows about
holidays. The frontend will use this in the next commit to filter
today's executions for Day P/L without doing client-side calendar
math.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Widen `today_executions` DB window

**Files:**
- Modify: `backend/app/api/http.py:1142-1151`

- [ ] **Step 1: Read the existing endpoint**

Confirm the current code (no edit yet):

```python
                await sync_broker_executions(session, broker, days=2)
                since = datetime.now(_tz.utc) - timedelta(days=2)
                rows = await repo.list_broker_executions(
                    session,
                    account_id=account_id,
                    since=since,
                )
```

- [ ] **Step 2: Widen the window**

Edit `backend/app/api/http.py` around line 1142-1151:

```python
            if account_id:
                # 7-day window: comfortably spans the worst-case
                # Thanksgiving (Thu close + Fri half-day + Sat + Sun)
                # or Memorial Day (Fri + Sat + Sun + Mon holiday) so
                # the most recent trading day's fills are always in
                # the DB read. Frontend filters precisely by
                # ``quote.trading_day``; backend just needs to not
                # drop fills before they reach the client. DB upsert
                # in sync_broker_executions dedupes by order_id so
                # the widened sync is idempotent.
                await sync_broker_executions(session, broker, days=7)
                since = datetime.now(_tz.utc) - timedelta(days=7)
                rows = await repo.list_broker_executions(
                    session,
                    account_id=account_id,
                    since=since,
                )
```

- [ ] **Step 3: Verify the endpoint still returns coherent shape**

Run the backend's HTTP test suite to make sure nothing else cared about the 2-day window:

```bash
cd backend && uv run pytest tests/api -v -k "execution or today"
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/http.py
git commit -m "$(cat <<'EOF'
fix(api/executions): widen today_executions window from 2 → 7 days

The 2-day cutoff dropped fills from the most recent trading day on
4-day-weekend holidays (e.g. Memorial Day: Fri fills are 3 days
behind a Mon-evening BJ view, so since = now-2d excluded them).
Frontend filters precisely by `quote.trading_day` (added in the
prior commit); backend just needs to not drop fills before they
reach the client.

DB upsert in sync_broker_executions dedupes by order_id, so the
widened sync is idempotent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Regenerate frontend types

**Files:**
- Modify: `frontend/src/api/types.ts`

- [ ] **Step 1: Make sure backend imports cleanly**

```bash
cd backend && uv run python -c "from app.main import app; print(app.openapi()['components']['schemas']['QuoteOut']['properties']['trading_day'])"
```

Expected: a dict showing the new field. If this fails, fix the backend first.

- [ ] **Step 2: Regenerate**

```bash
cd frontend && npm run gen:types
```

- [ ] **Step 3: Verify the new field is in types.ts**

```bash
grep -A1 "Trading Day" frontend/src/api/types.ts | head -5
```

Expected output:
```
            /** Trading Day */
            trading_day?: string | null;
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/openapi.json
git commit -m "$(cat <<'EOF'
feat(frontend/api): regenerate OpenAPI types — adds QuoteOut.trading_day

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: PositionCard uses `quote.trading_day`

**Files:**
- Modify: `frontend/src/components/Positions/PositionCard.tsx:111-140`
- Test: `frontend/src/components/Positions/PositionCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/Positions/PositionCard.test.tsx` (after the existing `describe` blocks):

```typescript
describe("PositionCard — Day P/L uses quote.trading_day on holidays", () => {
  it("counts Friday fills as today's trades when quote.trading_day = Friday on a holiday Monday", () => {
    // 2026-05-25 = Memorial Day (US market closed). Broker reports
    // last_done = 7.240 (Friday's close), trade_session = "regular"
    // (state-machine bug, separate issue), trading_day = "2026-05-22"
    // (the actual session this quote belongs to). The dayPl reducer
    // must filter Friday's executions in, not skip them as "not today".
    vi.setSystemTime(Date.parse("2026-05-25T14:30:00Z")); // Mon 10:30 ET

    const conlPosition: Position = {
      symbol: "CONL.US",
      type: "stock",
      ticker: "CONL",
      quantity: 7002,
      avg_cost: 6.941,
      option_strike: null,
      option_expiry: null,
      option_type: null,
    };
    const conlQuote: Quote = {
      symbol: "CONL.US",
      last_done: 7.240,
      prev_close: 7.96,
      open: 7.80,
      high: 7.95,
      low: 7.20,
      volume: 0,
      turnover: 0,
      change: -0.72,
      change_pct: -9.05,
      trade_session: "regular",
      trading_day: "2026-05-22",
    } as Quote;
    // Friday fills: 6001 shares total, avg ~$7.50.
    // Pre-Friday position: 1001 shares (held overnight, baseline = $7.96).
    const executions = [
      { ts: "2026-05-22T11:01:05Z", symbol: "CONL.US", side: "BUY", qty: 1, price: 7.87 },
      { ts: "2026-05-22T14:20:41Z", symbol: "CONL.US", side: "BUY", qty: 2000, price: 7.60 },
      { ts: "2026-05-22T14:21:28Z", symbol: "CONL.US", side: "BUY", qty: 2000, price: 7.50 },
      { ts: "2026-05-22T18:45:30Z", symbol: "CONL.US", side: "BUY", qty: 2000, price: 7.38 },
    ];

    render(
      <PositionCard
        position={conlPosition}
        quote={conlQuote}
        intraday={undefined}
        executions={executions as never}
        onClick={() => {}}
      />,
    );

    // Expected: -2241 (1001×(7.24-7.96) + 2000×(7.24-7.60) + 2000×(7.24-7.50) + 2000×(7.24-7.38) + 1×(7.24-7.87))
    expect(screen.getByText(/-\$2,241/)).toBeInTheDocument();
  });

  it("falls back to wall-clock today when quote.trading_day is null", () => {
    // No trading_day on the quote → behaviour matches the pre-fix
    // path (currentOrLastTradingDay), so this is the regression guard.
    vi.setSystemTime(Date.parse("2026-05-14T14:30:00Z")); // Thu 10:30 ET

    const quoteNoTradingDay: Quote = { ...quote, trading_day: null } as Quote;
    const executions = [
      { ts: "2026-05-14T14:25:00Z", symbol: "TSLA.US", side: "BUY", qty: 40, price: 244 },
    ];
    const positionAfter = { ...position, quantity: 240 + 40 };

    render(
      <PositionCard
        position={positionAfter}
        quote={quoteNoTradingDay}
        intraday={undefined}
        executions={executions as never}
        onClick={() => {}}
      />,
    );
    // qtyStart = 240, last = 245.5, prev = 240, buys = 40 * 244 = 9760
    // Day P/L = 245.5 * 280 + 0 - 9760 - 240 * 240 = 68740 - 9760 - 57600 = 1380
    expect(screen.getByText(/\+\$1,380/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npx vitest run src/components/Positions/PositionCard.test.tsx -t "uses quote.trading_day"
```

Expected: FAIL — current code still ignores `quote.trading_day` and uses `currentOrLastTradingDay()` which returns "2026-05-25"; Friday fills are filtered out and Day P/L = `(7.24 - 7.96) × 7002 ≈ -5041`, not -2241.

- [ ] **Step 3: Update `PositionCard.dayPl`**

Edit `frontend/src/components/Positions/PositionCard.tsx` around lines 119-128:

```tsx
    // Trading-day key: prefer the server-stamped value on the quote
    // (broker calendar, holiday-aware). Fall back to the wall-clock
    // heuristic only when the field is missing (cold broker, very old
    // backend) — the heuristic mishandles holidays but is correct on
    // regular trading days.
    const todayKey = quote?.trading_day ?? currentOrLastTradingDay();
    let buysCost = 0;
    let sellsProceeds = 0;
    let buysQty = 0;
    let sellsQty = 0;
    for (const e of executions ?? []) {
      // Filter to THIS stock symbol AND today's trading day. Broker
      // returns the whole account's fills in a flat list.
      if (e.symbol !== sym) continue;
      if (tradingDayOfET(e.ts) !== todayKey) continue;
```

- [ ] **Step 4: Run the new tests + all PositionCard tests**

```bash
cd frontend && npx vitest run src/components/Positions/PositionCard.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/PositionCard.tsx frontend/src/components/Positions/PositionCard.test.tsx
git commit -m "$(cat <<'EOF'
fix(positions): PositionCard.dayPl uses quote.trading_day

Day P/L was wrong on US holidays whose last trading day was the prior
Friday (e.g. Memorial Day): the wall-clock-derived todayKey
("2026-05-25") didn't match Friday's fills ("2026-05-22"), so they
got filtered out and the formula degenerated to
``(last − prev_close) × qty``, double-counting Friday's drop on
shares that were actually bought during Friday's session.

Now uses ``quote.trading_day`` (server-stamped from the broker's
holiday-aware calendar) and only falls back to the wall-clock
heuristic when the field is missing. Same-pattern fix as 8db45b4
(weekend gap) but for weekday holidays.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: OptionCard uses `quote.trading_day`

**Files:**
- Modify: `frontend/src/components/Positions/OptionCard.tsx:102-130`
- Test: `frontend/src/components/Positions/OptionCard.test.tsx`

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/components/Positions/OptionCard.test.tsx`:

```typescript
describe("OptionCard — Day P/L uses quote.trading_day on holidays", () => {
  it("counts Friday fills as today's trades when quote.trading_day = Friday", () => {
    vi.setSystemTime(Date.parse("2026-05-25T14:30:00Z")); // Mon holiday

    const optPosition: Position = {
      symbol: "TSLA250620C300000.US",
      type: "option",
      ticker: "TSLA",
      quantity: 5,
      avg_cost: 4.20,
      option_strike: 300,
      option_expiry: "2025-06-20",
      option_type: "call",
    };
    const optQuote: Quote = {
      symbol: "TSLA250620C300000.US",
      last_done: 4.50,
      prev_close: 5.00,
      open: 4.80,
      high: 4.95,
      low: 4.30,
      volume: 0,
      turnover: 0,
      change: -0.50,
      change_pct: -10.0,
      trade_session: "regular",
      trading_day: "2026-05-22",
    } as Quote;
    // 3 contracts bought on Friday at $4.50, 2 held overnight from
    // prev_close $5.00.
    const executions = [
      { ts: "2026-05-22T14:30:00Z", symbol: "TSLA250620C300000.US", side: "BUY", qty: 3, price: 4.50 },
    ];

    render(
      <OptionCard
        position={optPosition}
        quote={optQuote}
        intraday={undefined}
        executions={executions as never}
        onClick={() => {}}
      />,
    );
    // qtyStart = 5 - 3 = 2. Day P/L (×100):
    //   (4.50 * 5 + 0 - 4.50 * 3 - 5.00 * 2) * 100
    //   = (22.5 - 13.5 - 10) * 100
    //   = -100
    expect(screen.getByText(/-\$100/)).toBeInTheDocument();
  });
});
```

If `OptionCard.test.tsx` doesn't already exist or doesn't import `OptionCard` + types, add the standard preamble matching `PositionCard.test.tsx` (vi.useFakeTimers / setSystemTime).

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npx vitest run src/components/Positions/OptionCard.test.tsx -t "uses quote.trading_day"
```

Expected: FAIL — Friday fills filtered out by wall-clock todayKey.

- [ ] **Step 3: Update `OptionCard.dayPl`**

Edit `frontend/src/components/Positions/OptionCard.tsx` around line 107:

```tsx
    // Trading-day key: prefer the server-stamped value on the quote
    // (broker calendar, holiday-aware). Wall-clock fallback for older
    // backends — see PositionCard.tsx for the same fix on stocks.
    const todayKey = quote?.trading_day ?? currentOrLastTradingDay();
```

- [ ] **Step 4: Run all OptionCard tests**

```bash
cd frontend && npx vitest run src/components/Positions/OptionCard.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Positions/OptionCard.tsx frontend/src/components/Positions/OptionCard.test.tsx
git commit -m "$(cat <<'EOF'
fix(positions): OptionCard.dayPl uses quote.trading_day

Same holiday-correctness fix as the PositionCard commit — options
contracts had the identical bug since they share the dayPl reducer
shape.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Manual verification

- [ ] **Step 1: Start dev**

```bash
make dev
```

- [ ] **Step 2: Check the CONL card**

In the browser dashboard, open the CONL position card. Verify:
- 当日盈亏 chip shows approximately **−$2,241** (Friday's real session loss, including new Friday fills at their actual buy prices), not −$5,041.
- 浮盈 still shows **+$2,094** (unchanged — depends only on avg_cost + last_done).
- Refresh once to confirm the value sticks after the WS push handler updates the quote (i.e. `trading_day` flows through pushes too).

- [ ] **Step 3: Check at least one non-holiday symbol**

Pick a symbol the user actively trades (TSLL etc) — confirm Day P/L hasn't regressed on a normal trading day. Floating P/L unchanged, day P/L matches `(last − prev_close) × qty` when no fills today.

- [ ] **Step 4: Sanity-check the executions endpoint**

```bash
curl -s -H "Authorization: Bearer change-me-to-a-random-32-char-string" \
  http://127.0.0.1:8000/api/broker/today_executions \
  | python3 -m json.tool | head -40
```

Expected: returns Friday's CONL fills (4 rows), with valid `ts` and `symbol` fields. (Empty response means Task 4 didn't take — check the file.)

- [ ] **Step 5: Run the full test suite once**

```bash
make test
```

Expected: PASS on backend + frontend.

---

## Self-Review

**Spec coverage:** ✅ all three layers of the original analysis are addressed —
- `MarketSchedule` gains `current_or_last_trading_day` so the broker calendar drives the trading-day answer (Task 1)
- `QuoteOut.trading_day` carries that answer to the client on both HTTP fetches and WS pushes (Tasks 2-3)
- The frontend's Day P/L reducer in both card types uses the field (Tasks 6-7)
- `today_executions` endpoint is widened so the precise filter has the data to work with (Task 4)
- Verification at the same CONL card the user reported (Task 8)

**Placeholders:** none — every code block is concrete; every test has actual assertions; every command has expected output.

**Type consistency:**
- `QuoteOut.trading_day: str | None = None` (backend Pydantic) ⇄ `trading_day?: string | null` (frontend types) ⇄ `quote?.trading_day` (consumer)
- `current_or_last_trading_day` returns `date` (not `date | None`) — Task 1 explicitly falls back to local date on cold cache so the caller never has to handle None. `_trading_day_iso_for` returns `str | None` only because it gates on `self._market_schedule is None`.

Out-of-scope follow-ups noted in the goal section: `effectiveSession` pill on holidays.
