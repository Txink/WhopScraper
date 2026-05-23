# Watchlist Tabs — Design

**Date:** 2026-05-23
**Branch:** worktree-feat+chat-system-notice

## Problem

The right zone of the dashboard ships with exactly two tabs — **正股** and **期权** — both populated from the user's broker positions. There is no way to follow a symbol the user does not currently hold. Users who want to "watch" a name (waiting for an entry, tracking an unrelated ticker, monitoring a basket they considered but rejected) have to leave the dashboard and switch to another tool.

We want to keep the two existing tabs intact, but let the user pin **N user-defined tabs** beside them, each containing a freely curated list of stocks and options that render with the same card visuals as the position tabs and drill into the same DetailPane.

## Goal

In `PositionsPanel.tsx`, replace the hard-coded `PanelView = "stocks" | "options"` enum with a data-driven tab strip whose tail is filled by N user-created **watch tabs**:

- A `+` button at the end of the tab strip opens a "create tab" input. Submitting creates a new tab and switches to it.
- Hovering a watch tab reveals a red × in its top-right corner. Clicking × removes the tab (and all its items) instantly, no confirmation modal.
- A watch tab's body is a card grid. Cards are `PositionCard` (`kind: "stock"`) or `OptionCard` (`kind: "option"`), reusing the existing visuals but with empty `quantity`/`avg_cost`. The grid **always ends** with an `AddCardPlaceholder`; clicking it opens `WatchAddModal` which submits to the backend to create a new item.
- Hovering a real card reveals a red × in its top-right corner. Clicking × removes the item (no confirmation).
- Clicking a real card drills into the same `DetailPane` used by positions tabs, via `useDetailViewStore.selectSymbol(symbol)`; DetailPane runs in a new `watchOnly` mode that suppresses 做T pair binding and the portfolio summary cells that depend on holdings.
- The 正股 and 期权 tabs are **not removable**, are **not renamable**, and have **no ×**.

Watchlist rows are persisted in the backend and scoped to the active LongBridge account. Account switch triggers a refetch.

**Live-quote rule (important):** the right zone's WebSocket quote subscription is scoped to the **currently visible tab only**. Switching tabs tears down the prior subscription and re-establishes one for the new tab's symbols. Adding or removing an item inside the active watch tab triggers the same tear-down + re-subscribe cycle. This replaces today's "watch every position symbol regardless of which tab is active" behavior.

### Out of scope (YAGNI)

- Drag-reorder of tabs or items. Tabs append at the end of creation order; items append at the end of the grid (before the placeholder).
- Sharing/exporting watchlists across users or LongBridge accounts. Each `(account_id)` keeps its own list.
- Real-time multi-device push for watchlist mutations. A second browser session sees the change only after a manual reload or account-switch refetch.
- Notifications/alerts for watched symbols (price crossing, etc.). Cards are purely informational.
- Validation of expiry/strike against a real option chain. The backend's only validity check is "can `quote_hub` return a quote for this symbol?".

## Existing scaffolding (no changes)

```
backend  app/broker/runtime_settings.py     — LongPortRuntimeSettings.active_account_id
         app/api/http.py:1364               — POST /api/longport/oauth/activate + /broker/reload
         app/api/http.py:337..390           — GET /api/quote, POST /api/quotes/watch
         app/core/events.py                 — domain bus (not used by this feature)
frontend src/components/Positions/PositionsPanel.tsx — current 2-tab panel
         src/components/Positions/PositionCard.tsx
         src/components/Positions/OptionCard.tsx
         src/components/Positions/DetailPane.tsx
         src/stores/positions.ts            — broker positions store
         src/stores/detailView.ts           — selectSymbol(symbol)
         src/stores/quotes.ts               — pushed quote map (live)
         src/stores/candlesticks.ts         — candle cache + cacheKey
         src/api/http.ts:337                — api.quotes / api.watchQuotes / api.candlesticks
         src/App.tsx:526                    — broker-reload handler (the seam for account-switch reset)
```

Four facts that make this small:

1. `PositionCard` and `OptionCard` already accept a `Position` with optional fields; passing `quantity: 0, avg_cost: null` renders cleanly because every consumer guards `null`.
2. `DetailPane` works on a `Position` by symbol — the made-up 0-quantity Position is enough for its non-pair branches.
3. `useDetailViewStore.selectSymbol(symbol)` already drives PositionsPanel's "detail or grid" branch (`PositionsPanel.tsx:213-225`); we only need to feed it a symbol resolved against either positions or the active watch tab.
4. The current `usePositionsData` hook centralises every quote/candle/execution fetch and the `watchQuotes` push-set sync. Replacing "all positions" with "active tab symbols" is a one-place edit.

## Design

### 1. Backend

#### 1.1 Schema (Alembic migration)

A new migration `<rev>_watchlist_tabs_and_items.py` adds:

```sql
CREATE TABLE watchlist_tab (
  id           TEXT PRIMARY KEY,            -- uuid4
  account_id   TEXT NOT NULL,
  name         TEXT NOT NULL,
  sort_order   INTEGER NOT NULL,
  created_at   TEXT NOT NULL                -- ISO-8601 UTC, default CURRENT_TIMESTAMP
);
CREATE INDEX ix_watchlist_tab_account ON watchlist_tab(account_id);

CREATE TABLE watchlist_item (
  id             TEXT PRIMARY KEY,
  tab_id         TEXT NOT NULL REFERENCES watchlist_tab(id) ON DELETE CASCADE,
  symbol         TEXT NOT NULL,
  kind           TEXT NOT NULL CHECK (kind IN ('stock','option')),
  ticker         TEXT NOT NULL,
  option_type    TEXT,                      -- 'CALL' | 'PUT' | NULL
  option_strike  REAL,
  option_expiry  TEXT,                      -- 'YYYY-MM-DD' | NULL
  sort_order     INTEGER NOT NULL,
  created_at     TEXT NOT NULL,
  UNIQUE (tab_id, symbol)
);
CREATE INDEX ix_watchlist_item_tab ON watchlist_item(tab_id);
```

`sort_order` is **not** unique-constrained per account/tab; concurrent inserts simply take `max(sort_order)+1` at insert time. Frontend never sends `sort_order`; backend assigns.

#### 1.2 Repo

`backend/app/storage/watchlist_repo.py` exposes:

```python
def list_tabs(session, account_id: str) -> list[WatchlistTab]:
    """All tabs (with their items) for account_id, ordered by sort_order asc."""

def create_tab(session, account_id: str, name: str) -> WatchlistTab:
    """Assigns sort_order = max+1. Allows duplicate names."""

def rename_tab(session, account_id: str, tab_id: str, name: str) -> WatchlistTab:
    """404 if tab_id not found under account_id."""

def delete_tab(session, account_id: str, tab_id: str) -> None:
    """ON DELETE CASCADE drops items."""

def add_item(session, account_id: str, tab_id: str, draft: WatchlistItemDraft) -> WatchlistItem:
    """409 (IntegrityError → mapped) if (tab_id, symbol) already present."""

def delete_item(session, account_id: str, item_id: str) -> None:
    """No-op (returns) if item not under account_id."""
```

`account_id` is enforced at the repo layer: every read/write filters by it. The router passes it in from `LongPortRuntimeStore.active_account_id`.

#### 1.3 REST router

`backend/app/api/watchlist.py`:

```
GET    /api/watchlist
  resp 200 { tabs: [ { id, name, sort_order, items: [WatchItem...] } ] }
  resp 400 if no active account

POST   /api/watchlist/tab        body { name: str }
  resp 200 WatchTab (sort_order assigned by server)
  resp 400 if name is empty/whitespace

PATCH  /api/watchlist/tab/{id}   body { name: str }
  resp 200 WatchTab
  resp 404 if tab not found under active account

DELETE /api/watchlist/tab/{id}
  resp 200 { ok: true }
  resp 404 if tab not found under active account

POST   /api/watchlist/item       body { tab_id, symbol, kind, ticker,
                                        option_type?, option_strike?, option_expiry? }
  step 1: call quote_hub.fetch(symbol) — must return a non-empty quote
  resp 200 WatchItem
  resp 400 { code: "quote_unavailable" } if step 1 fails
  resp 404 if tab_id not under active account
  resp 409 { code: "duplicate" } if (tab_id, symbol) already exists

DELETE /api/watchlist/item/{id}
  resp 200 { ok: true }
  resp 404 if item not under active account
```

Account scoping: every router handler reads `runtime_store.active_account_id` and 400s with `"no active broker account"` (matching existing `/api/broker/today_executions` etc.) when null.

`backend/app/main.py` registers the router via the existing `app.include_router(...)` pattern next to whop / dashboard routers.

#### 1.4 Domain-type / OpenAPI

`backend/app/api/schemas.py` adds `WatchlistTabOut`, `WatchlistItemOut`, `WatchlistTabCreateIn`, `WatchlistItemCreateIn`. The frontend regenerates `frontend/src/api/types.ts` via the existing OpenAPI codegen and adds thin wrappers to `frontend/src/api/http.ts`:

```ts
api.watchlistList(): Promise<WatchlistListOut>
api.watchlistCreateTab(name: string): Promise<WatchlistTabOut>
api.watchlistRenameTab(id: string, name: string): Promise<WatchlistTabOut>
api.watchlistDeleteTab(id: string): Promise<{ ok: true }>
api.watchlistAddItem(draft: WatchlistItemCreateIn): Promise<WatchlistItemOut>
api.watchlistDeleteItem(id: string): Promise<{ ok: true }>
```

### 2. Frontend

#### 2.1 Component decomposition

```
components/Positions/
  PositionsPanel.tsx          ← thin router: picks tab body based on view
  PositionsTabStrip.tsx       ← pure tab strip (no store); props-driven
  PositionsTabStrip.css       ← × + + button styles
  WatchlistGrid.tsx           ← cards + AddCardPlaceholder
  WatchAddModal.tsx           ← segmented 股票/期权 form
  WatchAddModal.css
  AddCardPlaceholder.tsx      ← dashed empty cell that opens the modal
```

`PositionsTabStrip` props:

```ts
{
  view: ActiveTabView;                       // "stocks" | "options" | string
  tabs: WatchTab[];                          // user tabs only; built-ins are implicit
  onSelect(view: ActiveTabView): void;
  onAdd(name: string): void;                 // + button → inline name input → submit
  onRename(id: string, name: string): void;  // double-click to enter rename mode
  onRemoveTab(id: string): void;
}
```

Hover-driven × visibility is pure CSS (`.positions-tabs button:hover .tab-x { opacity: 1 }`). Tab × button uses `stopPropagation` to avoid triggering the tab's `onSelect`. The 正股 / 期权 buttons never render a × — `PositionsTabStrip` hard-codes them and only emits × for tabs from the `tabs` prop.

#### 2.2 State

`frontend/src/stores/watchlist.ts`:

```ts
export type WatchKind = "stock" | "option";

export interface WatchItem {
  id: string;                  // server uuid (or "tmp-..." during optimistic insert)
  tabId: string;
  symbol: string;              // LongBridge format, e.g. "AAPL.US" or "AAPL250620C00170000"
  kind: WatchKind;
  ticker: string;              // display label (AAPL / 700 / TSLA)
  optionType?: "CALL" | "PUT";
  optionStrike?: number;
  optionExpiry?: string;       // "YYYY-MM-DD"
  sortOrder: number;
}

export interface WatchTab {
  id: string;
  name: string;
  sortOrder: number;
  items: WatchItem[];
}

interface WatchlistState {
  tabs: WatchTab[];
  loaded: boolean;
  loadError: string | null;

  load(): Promise<void>;                       // GET /api/watchlist
  createTab(name: string): Promise<WatchTab>;
  renameTab(id: string, name: string): Promise<void>;
  removeTab(id: string): Promise<void>;
  addItem(tabId: string, draft: WatchItemDraft): Promise<void>;
  removeItem(tabId: string, itemId: string): Promise<void>;
  reset(): void;                               // clear + set loaded=false
}
```

All mutations use **optimistic updates with rollback**: insert/remove the row locally before `await`, then either confirm (swap `tmp-` id for the server id) or roll back on error and re-throw so callers (the modal, the × handler) can surface the error.

`reset()` is called from `App.tsx` inside the existing `onReloadBroker` handler (`App.tsx:526`), right after `api.reloadBroker()` returns: `useWatchlistStore.getState().reset(); void useWatchlistStore.getState().load()`. Dashboard mount also calls `load()` once.

#### 2.3 `PositionsPanel` rewrite (key sections)

> **Note:** `stores/view.ts` already exists but holds the **top-level** page view (`dashboard | whop | database`). The panel's sub-tab state is a separate concern. We add a new tiny store `frontend/src/stores/positionsTab.ts`:
>
> ```ts
> export type ActiveTabView = "stocks" | "options" | string;  // string = watch tab id
>
> interface PositionsTabState {
>   view: ActiveTabView;
>   setView(v: ActiveTabView): void;
> }
> ```
>
> Persists `view` to `localStorage["positionsPanel.view"]`. On hydration, if the stored view is a watch-tab id that no longer exists (account switch, deletion in another session), `usePositionsTabStore` falls back to `"stocks"` after `useWatchlistStore.load()` resolves.

```tsx
const view = usePositionsTabStore(s => s.view);
const tabs = useWatchlistStore(s => s.tabs);

// Resolve active tab's symbol set (for the watchQuotes effect).
const activeSymbols = useMemo<string[]>(() => {
  if (view === "stocks")  return stocks.map(p => p.symbol);
  if (view === "options") return options.map(p => p.symbol);
  const tab = tabs.find(t => t.id === view);
  return tab ? tab.items.map(i => i.symbol) : [];
}, [view, stocks, options, tabs]);

// Strict "subscribe to currently-visible tab only".
// Each change tears down the prior subscription and re-establishes one.
useEffect(() => {
  let cancelled = false;
  void (async () => {
    await api.watchQuotes([]);                       // 中断
    if (cancelled) return;
    if (activeSymbols.length > 0) {
      await api.watchQuotes(activeSymbols);          // 重启
    }
  })();
  return () => {
    cancelled = true;
    void api.watchQuotes([]).catch(() => undefined);
  };
}, [view, activeSymbols.join(",")]);
```

When `removeTab(activeTabId)` succeeds and `view` no longer resolves against any tab, `usePositionsTabStore.setView("stocks")` is called from the same removal flow.

One-shot fetches (`api.quotes`, `api.candlesticks`, `api.todayExecutions`) **stay as they are** in `usePositionsData` for stocks/options. For watch-tab items, candles are fetched lazily on first render of the watch tab's body (mirroring the existing per-symbol candle fetch in `usePositionsData`), keyed by `candleCacheKey` so subsequent tab switches hit the cache.

#### 2.4 Card-level integration

Add an optional `onRemove?(): void` prop to `PositionCard` and `OptionCard`. When present, render a red × button at the card's top-right corner; `:hover` reveals it; `stopPropagation` on click so the card's existing `onClick` (drill-down) doesn't fire.

CSS: a `.pcard-x` / `.ocard-x` rule with `position: absolute; top: 6px; right: 6px; opacity: 0`, plus `.pcard:hover .pcard-x { opacity: 1 }`. Color = `var(--err)` for the icon stroke.

#### 2.5 DetailPane "watch-only" mode

No new flag is added to `useDetailViewStore`. The watch-only mode is **derived** by `PositionsPanel` while resolving `selectedSymbol`:

```ts
let resolved: Position | undefined;
let watchOnly = false;
resolved = stocks.find(p => p.symbol === selectedSymbol)
        ?? options.find(p => p.symbol === selectedSymbol);
if (!resolved) {
  // Fall back to the active watch tab's items.
  const tab = tabs.find(t => t.id === view);
  const item = tab?.items.find(i => i.symbol === selectedSymbol);
  if (item) {
    resolved = synthesizePosition(item);  // quantity: 0, avg_cost: null
    watchOnly = true;
  }
}
```

`synthesizePosition` shapes a `Position` with `quantity: 0`, `avg_cost: null`, `type: item.kind`, and (for options) `option_type / option_strike / option_expiry` copied from the item.

`DetailPane` accepts a new optional prop `watchOnly?: boolean`. When true:

- Skips the 做T pair fetch + tab.
- Hides the position-aggregate header.
- Keeps the chart + trade-list views (live quote + historical fills are still meaningful for a watched name).

#### 2.6 `WatchAddModal` flow

Segmented top: `[ 股票 | 期权 ]`. Stock mode form:

- 市场 dropdown: `US | HK | SH | SZ`
- Ticker input (uppercase auto)
- Submit → assemble `symbol = `${ticker}.${market}`` → `api.watchlistAddItem({ kind: "stock", ticker, symbol, ... })`

Option mode form:

- 市场 dropdown (US only for v1; HK options not supported by current LongBridge wrapper as far as the existing UI shows)
- Ticker input
- 到期日 date picker (YYYY-MM-DD)
- 行权价 number input
- Call/Put radio
- Submit → assemble the LongBridge option symbol (`{ticker}{YYMMDD}{C|P}{strike*1000 padded to 8}`) → `api.watchlistAddItem(...)`

Error surface: backend 400 (`quote_unavailable`) and 409 (`duplicate`) render as red inline text under the form. Submit button shows a spinner while in flight.

### 3. Live-quote behaviour summary

| Trigger                                                       | What happens                                                              |
|---------------------------------------------------------------|---------------------------------------------------------------------------|
| Dashboard mount                                               | Quote/candle/exec one-shot; `watchQuotes([])` (no view yet) → `watchQuotes(stocks)` once view defaults to `"stocks"`. |
| Switch view stocks ↔ options                                  | `watchQuotes([])` then `watchQuotes(new tab's symbols)`.                  |
| Switch to a watch tab                                         | Same: tear-down then re-subscribe with watch-tab symbols.                 |
| Add a card to the active watch tab                            | `activeSymbols` changes → effect re-runs → tear-down + re-subscribe.      |
| Remove a card from the active watch tab                       | Same.                                                                     |
| Account switch (`broker/reload`)                              | `watchlist.reset() + load()`; positions store also resets; effect re-runs.|
| Dashboard unmount                                             | Cleanup runs `watchQuotes([])`.                                           |

### 4. Error handling

| Scenario                                                        | UX                                                                       |
|-----------------------------------------------------------------|--------------------------------------------------------------------------|
| `GET /api/watchlist` fails on mount                             | `loaded = false`, `loadError = msg`. No watch tabs render. Retry once after 3 s. If still failing, inline error strip at the right end of the tab row. |
| `POST /api/watchlist/item` → 400 quote_unavailable              | Modal inline red: "找不到该 symbol 的行情，请检查代码".                  |
| `POST /api/watchlist/item` → 409 duplicate                      | Modal inline red: "这个 symbol 已经在此 tab 里".                         |
| `POST /api/watchlist/item` → other                              | Modal inline red: generic "添加失败，请重试". Rollback optimistic row.    |
| `DELETE /api/watchlist/item` fails                              | Rollback locally. `console.warn` only — no toast.                        |
| `POST /api/watchlist/tab` empty/whitespace name                 | Disable confirm button client-side; never sent.                          |
| `DELETE /api/watchlist/tab` fails                               | Roll the tab back into the list. View stays on the fallback target.     |
| `watchQuotes` fails                                             | Existing 3-attempt retry path in `usePositionsData` reused; next view-change or mutation retries automatically. |
| `account.switched` flow fails (reset succeeds, load fails)      | Same as initial-load failure.                                            |
| Active watch tab is the one being deleted                       | Optimistic remove → `view` no longer resolves → fall back to `"stocks"` → effect tears down + re-subscribes with positions stock symbols. If DELETE fails, tab returns; view stays on stocks (does **not** auto-switch back). |

### 5. Testing

#### 5.1 Unit (store / repo)

- `stores/watchlist.test.ts`:
  - `load()` populates `tabs` in `sort_order` ascending and flips `loaded` to true.
  - `addItem` lays a `tmp-…` row before the fetch resolves; awaiting the call swaps it for the real id.
  - `addItem` failure rolls the row back and re-throws.
  - `removeTab` removes the tab and its items locally; rolls back on rejection.
  - `reset()` clears `tabs`, sets `loaded = false`, `loadError = null`.

- `backend/tests/test_watchlist_repo.py`:
  - `create_tab` assigns sort_order = max+1; `list_tabs` returns ordered.
  - Adding the same `(tab_id, symbol)` twice maps `IntegrityError` → repo raises `DuplicateError` (router translates to 409).
  - `delete_tab` cascade-removes items.
  - Account isolation: tabs under account A are invisible to a call with account B.

#### 5.2 Integration (FastAPI)

- `backend/tests/test_watchlist_api.py` with a fake broker / quote_hub:
  - `POST /api/watchlist/item` with a symbol the quote hub rejects → 400 `quote_unavailable`.
  - Second POST with the same symbol on the same tab → 409 `duplicate`.
  - `DELETE /api/watchlist/tab/{id}` removes children; subsequent `GET /api/watchlist` doesn't return them.
  - `set_active(account_id)` then `GET /api/watchlist` returns only that account's tabs.
  - No active account → all endpoints return 400.

#### 5.3 Component (RTL)

- `PositionsTabStrip.test.tsx`:
  - Renders `[正股, 期权, ...user tabs, +]` in order.
  - 正股 / 期权 hover does **not** reveal × (`queryByLabelText("删除 tab")` returns null on those buttons).
  - User tabs hover reveals ×; clicking × calls `onRemoveTab(id)` and does **not** call `onSelect`.
  - Clicking `+` opens the inline name input; submitting calls `onAdd(name)`.

- `WatchlistGrid.test.tsx`:
  - 0 items → renders only the AddCardPlaceholder.
  - 3 items → renders 3 cards (stock or option per `kind`) + placeholder at the end.
  - Card hover reveals ×; click × calls `onRemoveItem(itemId)` without triggering card `onClick`.

- `WatchAddModal.test.tsx`:
  - Default mode is 股票; switching to 期权 reveals strike/expiry/call-put.
  - Stock submit assembles `AAPL.US` from ticker=AAPL, market=US.
  - Option submit assembles `AAPL250620C00170000` from ticker=AAPL, expiry=2025-06-20, type=CALL, strike=170.
  - Mock 400 → inline error; mock 409 → inline error; mock 200 → modal closes + `onAdded` fires.

- `PositionsPanel.test.tsx` (extend existing):
  - `view=stocks` → `watchQuotes` last called with stocks symbols.
  - Switch to a watch tab → assert `watchQuotes` called once with `[]`, then once with the tab's symbols (two-step lifecycle).
  - Add an item to the active watch tab → asserts the same two-step lifecycle re-runs with the new set.
  - Remove the active watch tab → `view` falls back to `"stocks"`; `watchQuotes` re-runs with stocks.

#### 5.4 Out of scope

- No Playwright/Cypress; project has no E2E layer.
- No load-test for the new endpoints (low-traffic personal feature).
