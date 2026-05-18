# Pull-recent-trades menu item

## Problem

The trade-list gear menu in `DetailPane` already has two heavy-handed actions:

- **重新拉取（近 2 年）** — deletes the local `broker_executions` slice for the
  current ticker, then triggers a full 2-year chunked backfill via the
  existing `/api/broker/executions` GET path (which runs the first-time
  fall-through inside `sync_broker_executions_incremental`).
- **清空交易记录** — pure local-DB wipe.

What's missing is a cheap, **non-destructive** "refresh from broker"
action for the common case: the user opened the detail pane minutes ago,
suspects a fill might have arrived (or might be missing) inside the last
week, and wants the local DB to reflect that *without* losing what's
already cached.

The existing GET `/api/broker/executions` path does run an incremental
sync on every call, but its anchor is `MAX(ts)` in the DB — so any gap
**older than** the latest local row (e.g., a mid-week fill that wasn't
captured because a prior sync hiccupped) is silently skipped. A
"last-7-days unconditional pull" is the correct primitive for that case.

## Solution

Add a menu item **"拉取最新（近 1 周）"** to the gear menu, above the
existing "重新拉取（近 2 年）". Clicking it pulls the last 7 days of
broker fills for the current ticker, upserts into `broker_executions`
keyed by `order_id` (no delete, duplicates skipped automatically), and
refreshes the visible trade list. No confirmation modal — the action is
non-destructive.

The backend primitive `sync_broker_executions(ticker, days)` already
exists (used by `/api/broker/today_executions` with `days=2`); it's
chunked at ≤ 90 days per LongBridge call and idempotent on `order_id`.
We only need to expose it via a new endpoint and wire a callback through.

## Backend changes

### New endpoint: `POST /api/broker/executions/sync`

In `backend/app/api/http.py`, alongside the existing executions endpoints:

```python
@router.post("/api/broker/executions/sync", response_model=ExecutionsSyncOut)
async def sync_executions_endpoint(
    ticker: Annotated[str, Query(min_length=1)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> ExecutionsSyncOut:
    """Force-pull the last ``days`` of broker fills for ``ticker`` and
    upsert into ``broker_executions``. Distinct from the GET path's
    incremental sync (which anchors on ``MAX(ts)``) — this unconditionally
    walks back ``days`` so mid-window gaps in the local cache are filled.

    Idempotent: PK is order_id; upsert keeps qty / price / ts current.
    Capped at 90 days because LongBridge's history_executions rejects
    wider single calls.
    """
    from app.broker.executions_sync import sync_broker_executions

    broker = _get_broker()
    if not getattr(broker, "account_id", ""):
        return ExecutionsSyncOut(persisted=0)
    async with session_scope(session_factory) as session:
        persisted = await sync_broker_executions(
            session, broker, ticker=ticker, days=days
        )
    return ExecutionsSyncOut(persisted=persisted)
```

### New schema: `ExecutionsSyncOut`

In `backend/app/api/schemas.py`:

```python
class ExecutionsSyncOut(BaseModel):
    persisted: int
```

`persisted` is the upsert count returned by `sync_broker_executions` (new
rows + updated rows). The frontend doesn't display it — the field exists
for logging / future test assertions, not UX.

### Why a new endpoint and not GET `?force_sync=true`

Two reasons. (1) The existing GET is shaped around incremental sync
semantics; a `force_sync` query param would branch the handler and blur
the read-vs-write distinction. (2) The new caller doesn't actually need
the trade list rows in the response — the frontend re-runs the existing
GET right after to refresh the list. A separate write-style POST keeps
both verbs clean.

## Frontend changes

### `frontend/src/api/http.ts`

Add an `api.syncExecutions(ticker, days)` method:

```ts
async syncExecutions(ticker: string, days = 7): Promise<{ persisted: number }> {
  const qs = new URLSearchParams({ ticker, days: String(days) });
  return request(`/api/broker/executions/sync?${qs.toString()}`, {
    method: "POST",
  });
}
```

### `frontend/src/components/Positions/DetailPane.tsx`

Add an `onSyncRecentTrades` callback, modeled on the existing
`onRefetchTrades` but **without** the ConfirmModal step and **without**
the `api.deleteBrokerExecutions` call:

```ts
const onSyncRecentTrades = useCallback(async () => {
  try {
    setTradesInitialized(false);
    await api.syncExecutions(ticker, 7);
    const r = await api.executions(ticker, { offset: 0, limit: TRADES_INITIAL_LIMIT });
    const trades = r.executions.map((e) => ({
      id: e.order_id,
      ticker: e.ticker,
      symbol: e.symbol,
      side: e.side,
      qty: e.qty,
      price: e.price,
      ts: e.ts,
      source: null,
      tag: null,
      t_pair_tags: (e as { t_pair_tags?: [number, number][] }).t_pair_tags ?? [],
    }));
    setTrades(ticker, trades);
    setTradesTotal(r.total_count);
    setLastSyncedAt(r.last_synced_at ?? null);
  } catch (e) {
    console.error("syncRecentTrades failed", e);
  } finally {
    setTradesInitialized(true);
  }
}, [ticker, setTrades]);
```

Pass it down: `<TradeList ... onSyncRecentTrades={onSyncRecentTrades} />`.

### `frontend/src/components/Positions/TradeList.tsx`

Add a new optional prop:

```ts
onSyncRecentTrades?(): Promise<void> | void;
```

Render a new menu item above the existing "重新拉取（近 2 年）" item:

```tsx
<button
  className="trade-menu-item"
  onClick={() => {
    setMenuOpen(false);
    void onSyncRecentTrades?.();
  }}
>
  拉取最新（近 1 周）
</button>
```

Placement rationale: the lighter, more frequently-used action goes
first; the destructive full-refetch sits below. No separator between
them — both are "sync from broker" verbs sharing visual grouping.

## UX feedback

- **During sync**: `setTradesInitialized(false)` triggers the existing
  "加载中…" state in TradeList. No new spinners or toasts.
- **After sync**: trade list refreshes in place; the footer's "上次更新
  xxx" caption updates automatically (driven by `lastSyncedAt`).
- **On error**: silent `console.error`. Same pattern as
  `onRefetchTrades` — we don't have a user-facing toast system in this
  codebase yet, and adding one is out of scope.

## Testing

**Backend** — add a unit test in `backend/tests/api/` (matching the
existing per-endpoint test file pattern) that:
- Hits `POST /api/broker/executions/sync?ticker=AAPL&days=7` with a fake
  broker, asserts `sync_broker_executions` was called with
  `ticker="AAPL"`, `days=7`, and the response payload matches the
  returned persisted count.
- Asserts `days` out of range (0, 91) → 422.
- Asserts missing `ticker` → 422.

**Frontend** — extend `TradeList.test.tsx`:
- Menu opens → "拉取最新（近 1 周）" item is rendered (above "重新拉取").
- Click → `onSyncRecentTrades` is invoked, menu closes.

A DetailPane integration test for the full callback chain
(`syncExecutions → executions → setTrades`) is **not** added — the
existing `onRefetchTrades` path has no equivalent integration test and
mirroring it for this lighter variant is low value vs. cost.

## Out of scope

- No global / all-account "pull recent" button (per-ticker scope only —
  matches the rest of the gear menu).
- No toast / persistent UI feedback beyond the existing loading state.
- No change to the incremental sync semantics of the GET path.
- No change to the 2-year refetch flow.
