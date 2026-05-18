# Pull-recent-trades Menu Item — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-destructive **"拉取最新（近 1 周）"** menu item to the trade-list gear menu in `DetailPane`. It force-pulls the last 7 days of broker fills for the current ticker, upserts into `broker_executions` (idempotent on `order_id`), and refreshes the visible trade list — no DB delete, no confirmation modal.

**Architecture:** Expose the existing `sync_broker_executions(ticker, days)` primitive via a new `POST /api/broker/executions/sync` endpoint (distinct from the GET path's incremental-from-`MAX(ts)` semantics, which misses mid-window gaps). Frontend adds a thin `api.syncExecutions` wrapper, a new `onSyncRecentTrades` callback in `DetailPane.tsx`, and one menu item in `TradeList.tsx`.

**Tech Stack:** Python / FastAPI (backend), SQLAlchemy async session, Pydantic v2, pytest with TestClient + FakeBrokerClient. React 18 / TypeScript / Vitest + @testing-library/react (frontend).

**Spec:** `docs/superpowers/specs/2026-05-18-pull-recent-trades-design.md`

---

## File Structure

**Backend:**
- Modify: `backend/app/api/schemas.py` — add `ExecutionsSyncOut` Pydantic model.
- Modify: `backend/app/api/http.py` — add `POST /api/broker/executions/sync` endpoint (next to the existing `/api/broker/executions` GET / DELETE near line 896).
- Modify: `backend/tests/api/test_http.py` — add 3 endpoint tests next to the existing `test_history_executions_endpoint_*` cases.

**Frontend:**
- Modify: `frontend/src/api/http.ts` — add `api.syncExecutions(ticker, days)` next to `api.executions()` (~line 375).
- Modify: `frontend/src/components/Positions/TradeList.tsx` — add `onSyncRecentTrades` prop, render new menu item above "重新拉取（近 2 年）".
- Modify: `frontend/src/components/Positions/DetailPane.tsx` — add `onSyncRecentTrades` callback (~line 646, next to `onRefetchTrades`), pass to `<TradeList>`.
- Create: `frontend/src/components/Positions/TradeList.test.tsx` — first test file for this component, covering the new menu item click flow.

---

## Task 1: Backend — `ExecutionsSyncOut` schema

**Files:**
- Modify: `backend/app/api/schemas.py`

- [ ] **Step 1: Add the response schema**

Open `backend/app/api/schemas.py` and add (placement: after `PendingExecutionsOut` near line 252, alphabetical/proximity doesn't matter here — group it near the other executions-shaped models):

```python
class ExecutionsSyncOut(BaseModel):
    """Response payload for ``POST /api/broker/executions/sync``.

    ``persisted`` is the upsert count returned by
    ``sync_broker_executions`` (new rows + updated rows). The frontend
    doesn't display it; the field exists for logging and test assertions.
    """

    persisted: int
```

- [ ] **Step 2: No commit yet** — pair with Task 2's endpoint commit.

---

## Task 2: Backend — `POST /api/broker/executions/sync` endpoint

**Files:**
- Modify: `backend/app/api/http.py:988` (insert new endpoint between the DELETE at line 988 and the GET `/api/broker/today_executions` at line 1007)
- Modify: `backend/tests/api/test_http.py` (append after `test_history_executions_endpoint_*` cases)

- [ ] **Step 1: Write the failing happy-path test**

Append to `backend/tests/api/test_http.py` (after the existing `test_history_executions_endpoint_*` block, before the DELETE tests is fine — group with the executions tests):

```python
def test_sync_executions_endpoint_force_pulls_recent_window(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """``POST /api/broker/executions/sync?ticker=X&days=7`` calls
    ``sync_broker_executions`` (NOT the incremental variant), which
    walks back ``days`` unconditionally from now and upserts on
    ``order_id``. Re-issuing the same request is a no-op (idempotent)."""
    from datetime import datetime, timedelta, timezone

    client, broker = client_and_broker
    now = datetime.now(timezone.utc)
    broker.history_executions_list = [  # type: ignore[attr-defined]
        {
            "order_id": "fill-1",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "BUY",
            "qty": 10,
            "price": 200.0,
            "ts": now - timedelta(days=2),
        },
        # Older than the 7-day window — must NOT be persisted.
        {
            "order_id": "old",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "SELL",
            "qty": 5,
            "price": 220.0,
            "ts": now - timedelta(days=30),
        },
    ]

    r = client.post(
        "/api/broker/executions/sync",
        params={"token": _TOKEN, "ticker": "TSLA", "days": 7},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"persisted": 1}

    # Idempotency: re-posting upserts the same row → still counts it,
    # but a follow-up GET returns the same single row.
    r2 = client.post(
        "/api/broker/executions/sync",
        params={"token": _TOKEN, "ticker": "TSLA", "days": 7},
    )
    assert r2.status_code == 200, r2.text

    g = client.get(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA", "offset": 0, "limit": 50},
    )
    assert g.status_code == 200
    rows = g.json()["executions"]
    assert [e["order_id"] for e in rows] == ["fill-1"]
```

- [ ] **Step 2: Run the test, expect 404**

```bash
cd backend && uv run pytest tests/api/test_http.py::test_sync_executions_endpoint_force_pulls_recent_window -v
```

Expected: FAIL — endpoint doesn't exist yet (response will likely be 404 or 405).

- [ ] **Step 3: Implement the endpoint**

Open `backend/app/api/http.py`. Locate the DELETE handler ending around line 1006 (immediately before `@router.get("/api/broker/today_executions", ...)` at line 1007). Insert this new endpoint between them:

```python
    @router.post(
        "/api/broker/executions/sync", response_model=ExecutionsSyncOut
    )
    async def sync_executions_endpoint(
        ticker: Annotated[str, Query(min_length=1)],
        days: Annotated[int, Query(ge=1, le=90)] = 7,
    ) -> ExecutionsSyncOut:
        """Force-pull the last ``days`` of broker fills for ``ticker`` and
        upsert into ``broker_executions``. Distinct from the GET path's
        incremental sync (which anchors on ``MAX(ts)``) — this
        unconditionally walks back ``days`` so mid-window gaps in the
        local cache are filled. Idempotent: PK is order_id.

        ``days`` capped at 90 because LongBridge's history_executions
        rejects wider single calls (see knowledge/longbridge-api-limits.md).
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

Then add `ExecutionsSyncOut` to the imports near the top of `http.py`. Find the existing import line for `ExecutionsOut` (search the file for `ExecutionsOut`) and add the new symbol to that same import. Example pattern:

```python
# before
from app.api.schemas import (
    ...,
    ExecutionsOut,
    ...,
)

# after
from app.api.schemas import (
    ...,
    ExecutionsOut,
    ExecutionsSyncOut,
    ...,
)
```

- [ ] **Step 4: Run the test, expect PASS**

```bash
cd backend && uv run pytest tests/api/test_http.py::test_sync_executions_endpoint_force_pulls_recent_window -v
```

Expected: PASS.

- [ ] **Step 5: Add the validation tests**

Append two more tests:

```python
def test_sync_executions_endpoint_rejects_missing_ticker(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """``ticker`` is required — the endpoint is per-ticker by design."""
    client, _ = client_and_broker
    r = client.post(
        "/api/broker/executions/sync",
        params={"token": _TOKEN, "days": 7},
    )
    assert r.status_code == 422


def test_sync_executions_endpoint_rejects_out_of_range_days(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """``days`` is clamped to [1, 90]; LongBridge rejects wider single
    calls and the menu item only needs 7."""
    client, _ = client_and_broker
    r0 = client.post(
        "/api/broker/executions/sync",
        params={"token": _TOKEN, "ticker": "TSLA", "days": 0},
    )
    assert r0.status_code == 422
    r91 = client.post(
        "/api/broker/executions/sync",
        params={"token": _TOKEN, "ticker": "TSLA", "days": 91},
    )
    assert r91.status_code == 422
```

- [ ] **Step 6: Run all three new tests**

```bash
cd backend && uv run pytest tests/api/test_http.py -v -k "sync_executions_endpoint"
```

Expected: 3 passed.

- [ ] **Step 7: Run the existing executions tests to confirm no regression**

```bash
cd backend && uv run pytest tests/api/test_http.py -v -k "executions"
```

Expected: All pass (including the new 3 and the existing `test_history_executions_endpoint_*` / `test_delete_broker_executions_endpoint_*` / `test_today_executions_endpoint_*`).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/http.py backend/tests/api/test_http.py
git commit -m "$(cat <<'EOF'
feat(api): POST /api/broker/executions/sync for force-pull window

Exposes the existing sync_broker_executions primitive over HTTP, so a
forthcoming trade-list menu item can pull the last N days of broker
fills for one ticker without deleting local rows. Distinct from the
GET path's incremental sync (which anchors on MAX(ts) and misses
mid-window gaps).

Idempotent: order_id is PK, repeated calls upsert.
EOF
)"
```

---

## Task 3: Frontend — `api.syncExecutions` wrapper

**Files:**
- Modify: `frontend/src/api/http.ts:391` (insert after the existing `executions()` method, before the `// 做T pair CRUD` block at line 394)

- [ ] **Step 1: Add the method**

Open `frontend/src/api/http.ts`. Find the `async executions(...)` method (around line 375). Immediately after its closing brace and before the `// -------- 做T pair CRUD --------` divider (~line 393), add:

```ts
  /** Force-pull the last ``days`` of broker fills for ``ticker`` and
   *  upsert into ``broker_executions``. Distinct from a re-GET of
   *  ``executions()``, which uses incremental-from-MAX(ts) semantics
   *  and misses mid-window gaps in the local cache. */
  async syncExecutions(
    ticker: string,
    days = 7,
  ): Promise<{ persisted: number }> {
    const qs = new URLSearchParams({ ticker, days: String(days) });
    return request(`/api/broker/executions/sync?${qs.toString()}`, {
      method: "POST",
    });
  },
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: No commit yet** — pair with Task 4's UI commit so the wrapper lands with its first caller.

---

## Task 4: Frontend — TradeList menu item + DetailPane callback + test

**Files:**
- Create: `frontend/src/components/Positions/TradeList.test.tsx`
- Modify: `frontend/src/components/Positions/TradeList.tsx` — props + menu item
- Modify: `frontend/src/components/Positions/DetailPane.tsx:646` — new callback, wire to `<TradeList>`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/Positions/TradeList.test.tsx` with:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TradeList } from "./TradeList";
import type { Trade, TPair } from "../../api/domain-types";

const trades: Trade[] = [];
const pairs: TPair[] = [];

describe("TradeList — pull-recent menu item", () => {
  it("renders '拉取最新（近 1 周）' above '重新拉取（近 2 年）' and invokes onSyncRecentTrades", () => {
    const onSync = vi.fn();
    const onRefetch = vi.fn();

    render(
      <TradeList
        trades={trades}
        pairs={pairs}
        ticker="TSLA"
        onConfirmBind={vi.fn()}
        onExtendPair={vi.fn()}
        onSyncRecentTrades={onSync}
        onRefetchTrades={onRefetch}
      />,
    );

    // Open the gear menu.
    fireEvent.click(screen.getByLabelText("交易记录设置"));

    // Both items present; pull-recent placed above 2-year refetch.
    const sync = screen.getByText("拉取最新（近 1 周）");
    const refetch = screen.getByText("重新拉取（近 2 年）");
    expect(sync).toBeTruthy();
    expect(refetch).toBeTruthy();
    expect(sync.compareDocumentPosition(refetch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Click → callback fires, no confirm modal involved.
    fireEvent.click(sync);
    expect(onSync).toHaveBeenCalledTimes(1);
    expect(onRefetch).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test, expect FAIL**

```bash
cd frontend && npx vitest run src/components/Positions/TradeList.test.tsx
```

Expected: FAIL — `onSyncRecentTrades` prop and the menu text don't exist yet.

- [ ] **Step 3: Add the prop to `TradeList.tsx`**

Open `frontend/src/components/Positions/TradeList.tsx`. Find the `Props` interface ending around line 94. Add to the prop list (next to `onRefetchTrades`):

```ts
  /** Force-pull the last 7 days of broker fills for the current ticker
   *  and upsert into ``broker_executions`` (no delete; idempotent on
   *  order_id). Non-destructive — fires without a confirm modal. */
  onSyncRecentTrades?(): Promise<void> | void;
```

Then locate the menu item for "重新拉取（近 2 年）" (around line 404). Insert the new menu item **immediately before** that one, inside the same `<div className="trade-menu">`:

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

Then add `onSyncRecentTrades` to the destructured props at the top of the `TradeList` function — search the file for the line that destructures `onRefetchTrades` and add `onSyncRecentTrades` alongside it.

- [ ] **Step 4: Run the test, expect PASS**

```bash
cd frontend && npx vitest run src/components/Positions/TradeList.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Add `onSyncRecentTrades` callback in `DetailPane.tsx`**

Open `frontend/src/components/Positions/DetailPane.tsx`. Find `onRefetchTrades` (around line 646). Add this new callback **before** `onRefetchTrades` (so the lighter action's definition matches the lighter action's menu position):

```ts
  const onSyncRecentTrades = useCallback(async () => {
    try {
      setTradesInitialized(false);
      await api.syncExecutions(ticker, 7);
      const r = await api.executions(ticker, {
        offset: 0,
        limit: TRADES_INITIAL_LIMIT,
      });
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
        t_pair_tags:
          (e as { t_pair_tags?: [number, number][] }).t_pair_tags ?? [],
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

- [ ] **Step 6: Pass it down to `<TradeList>`**

In the same file, locate the `<TradeList>` JSX (search for `onRefetchTrades={onRefetchTrades}`). Add the new prop right next to it:

```tsx
        onSyncRecentTrades={onSyncRecentTrades}
        onRefetchTrades={onRefetchTrades}
```

- [ ] **Step 7: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

- [ ] **Step 8: Run the full frontend test suite**

```bash
cd frontend && npm test
```

Expected: all pass (the new test plus all existing tests).

- [ ] **Step 9: Manual smoke test**

Run the dev stack (`make dev` or per project README), open a position's detail pane, click the gear icon in the trade-list footer. Verify:

1. "拉取最新（近 1 周）" appears above "重新拉取（近 2 年）".
2. Clicking it does NOT open a confirm modal.
3. The trade list briefly shows "加载中…" (existing loading UI) and the row count / "上次更新" caption refresh.
4. Network panel: one `POST /api/broker/executions/sync?ticker=...&days=7` followed by one `GET /api/broker/executions?...`.
5. Clicking it a second time is a no-op data-wise (same row count; no duplicates introduced) — verifies `order_id` upsert.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/http.ts frontend/src/components/Positions/TradeList.tsx frontend/src/components/Positions/TradeList.test.tsx frontend/src/components/Positions/DetailPane.tsx
git commit -m "$(cat <<'EOF'
feat(positions): pull-recent (近 1 周) menu item in trade list

Adds a non-destructive refresh action in the trade-list gear menu,
above the existing 2-year re-fetch. Force-pulls the last 7 days of
broker fills for the current ticker and upserts into broker_executions
(idempotent on order_id). Useful when the user suspects a recent fill
was missed by the GET path's MAX(ts)-anchored incremental sync — that
path would skip any mid-window gap, this one fills it.

No confirm modal (non-destructive). Reuses the existing "加载中…"
indicator via setTradesInitialized(false).
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- ExecutionsSyncOut schema → Task 1 ✓
- POST /api/broker/executions/sync endpoint → Task 2 ✓
- `api.syncExecutions` wrapper → Task 3 ✓
- DetailPane `onSyncRecentTrades` callback → Task 4 (Step 5) ✓
- TradeList prop + menu item placement above 重新拉取 → Task 4 (Step 3) ✓
- Backend tests: happy path + 422 missing ticker + 422 days range → Task 2 (Steps 1, 5) ✓
- Frontend test: menu item exists + click invokes callback → Task 4 (Step 1) ✓
- No confirm modal → Task 4 Step 3 (callback wired without ConfirmModal) ✓
- Loading state via setTradesInitialized(false) → Task 4 Step 5 ✓
- console.error on failure → Task 4 Step 5 ✓

**Placeholder scan:** No "TBD", no "add error handling", every code step has its code. ✓

**Type consistency:**
- `onSyncRecentTrades?(): Promise<void> | void` — same signature shape used in TradeList props (Task 4 Step 3), the call site in TradeList menu (Task 4 Step 3), the callback definition in DetailPane (Task 4 Step 5), and the test (Task 4 Step 1). ✓
- `api.syncExecutions(ticker, days=7) → Promise<{ persisted: number }>` — declared in Task 3, called in Task 4 Step 5. ✓
- Backend response model `ExecutionsSyncOut(persisted: int)` — declared in Task 1, returned in Task 2 Step 3, asserted in Task 2 Step 1 (`{"persisted": 1}`). ✓
