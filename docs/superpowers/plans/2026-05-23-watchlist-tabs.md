# Watchlist Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-defined watchlist tabs beside `正股`/`期权` in `PositionsPanel`, persisted backend-side per-LongBridge-account, with the active tab exclusively owning the live quote subscription.

**Architecture:**
- Backend: two new tables (`watchlist_tab`, `watchlist_item`) scoped by `account_id`, a thin async repo, a new FastAPI router `/api/watchlist*` that validates `POST item` by round-tripping to `quote_hub.fetch()`.
- Frontend: two new Zustand stores (`positionsTab`, `watchlist`), four new components (`PositionsTabStrip`, `WatchlistGrid`, `AddCardPlaceholder`, `WatchAddModal`), and a `usePositionsData` rewrite that subscribes to **only the active tab's symbols** with an explicit tear-down + re-subscribe lifecycle.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.x / Alembic; React 18 / Zustand / Vite / vitest + RTL.

**Reference spec:** `docs/superpowers/specs/2026-05-23-watchlist-tabs-design.md`

---

## File Map

### Backend (create)
- `backend/alembic/versions/<rev>_watchlist_tabs_and_items.py` — migration
- `backend/app/storage/watchlist_repo.py` — async repo for tabs/items
- `backend/app/api/watchlist.py` — FastAPI router
- `backend/tests/storage/test_watchlist_repo.py`
- `backend/tests/api/test_watchlist_http.py`

### Backend (modify)
- `backend/app/storage/schema.py` — add `WatchlistTabRow` + `WatchlistItemRow`
- `backend/app/api/schemas.py` — add `WatchlistTabOut`, `WatchlistItemOut`, `WatchlistTabCreateIn`, `WatchlistTabRenameIn`, `WatchlistItemCreateIn`, `WatchlistListOut`
- `backend/app/api/http.py` — `include_router(watchlist.router)` near the existing routers
- `backend/app/main.py` — pass `quote_hub` + `runtime_store` into the watchlist router

### Frontend (create)
- `frontend/src/stores/positionsTab.ts` — `view: "stocks" | "options" | <watchTabId>` + localStorage
- `frontend/src/stores/watchlist.ts` — tabs/items + optimistic CRUD
- `frontend/src/components/Positions/PositionsTabStrip.tsx` + `.css`
- `frontend/src/components/Positions/WatchlistGrid.tsx`
- `frontend/src/components/Positions/AddCardPlaceholder.tsx`
- `frontend/src/components/Positions/WatchAddModal.tsx` + `.css`
- `frontend/src/components/Positions/watchSymbol.ts` — pure symbol-assembly helpers
- `frontend/src/stores/positionsTab.test.ts`
- `frontend/src/stores/watchlist.test.ts`
- `frontend/src/components/Positions/PositionsTabStrip.test.tsx`
- `frontend/src/components/Positions/WatchlistGrid.test.tsx`
- `frontend/src/components/Positions/WatchAddModal.test.tsx`
- `frontend/src/components/Positions/watchSymbol.test.ts`

### Frontend (modify)
- `frontend/src/api/http.ts` — add `api.watchlist*` wrappers
- `frontend/src/api/domain-types.ts` (or where the OpenAPI-derived types live) — `WatchTab`, `WatchItem` aliases
- `frontend/src/components/Positions/PositionsPanel.tsx` — rewrite tab-strip + body routing + subscription effect
- `frontend/src/components/Positions/PositionCard.tsx` — accept `onRemove?`
- `frontend/src/components/Positions/OptionCard.tsx` — accept `onRemove?`
- `frontend/src/components/Positions/Positions.css` — `.pcard-x` / `.ocard-x` rules
- `frontend/src/components/Positions/DetailPane.tsx` — accept `watchOnly?: boolean`, gate pair + summary
- `frontend/src/components/Positions/PositionsPanel.test.tsx` — extend with subscription-lifecycle assertions
- `frontend/src/App.tsx` — call `useWatchlistStore.load()` on dashboard mount and `reset() + load()` after `api.reloadBroker()`

---

## Backend

### Task 1: Alembic migration — `watchlist_tab` + `watchlist_item`

**Files:**
- Create: `backend/alembic/versions/<rev>_watchlist_tabs_and_items.py`
- Test: `backend/tests/alembic/test_watchlist_migration.py` (or extend an existing migration test if there is a generic one)

- [ ] **Step 1: Generate migration skeleton**

Run: `cd backend && uv run alembic revision -m "watchlist tabs and items"`

This creates a new file under `backend/alembic/versions/` with an auto-generated `<rev>` prefix. Note the path.

- [ ] **Step 2: Fill in `upgrade()` and `downgrade()`**

Replace the body of the generated file with:

```python
"""watchlist tabs and items

Revision ID: <rev>
Revises: <previous head>
Create Date: 2026-05-23 ...
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "<rev>"
down_revision = "<previous head>"  # alembic fills this; verify
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_tab",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("account_id", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
    )
    op.create_index(
        "ix_watchlist_tab_account",
        "watchlist_tab",
        ["account_id"],
    )

    op.create_table(
        "watchlist_item",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column(
            "tab_id",
            sa.String,
            sa.ForeignKey("watchlist_tab.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column(
            "kind",
            sa.String,
            sa.CheckConstraint("kind IN ('stock','option')"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String, nullable=False),
        sa.Column("option_type", sa.String, nullable=True),
        sa.Column("option_strike", sa.Float, nullable=True),
        sa.Column("option_expiry", sa.String, nullable=True),
        sa.Column("sort_order", sa.Integer, nullable=False),
        sa.Column("created_at", sa.String, nullable=False),
        sa.UniqueConstraint("tab_id", "symbol", name="uq_watchlist_item_tab_symbol"),
    )
    op.create_index(
        "ix_watchlist_item_tab",
        "watchlist_item",
        ["tab_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_item_tab", table_name="watchlist_item")
    op.drop_table("watchlist_item")
    op.drop_index("ix_watchlist_tab_account", table_name="watchlist_tab")
    op.drop_table("watchlist_tab")
```

- [ ] **Step 3: Run migration up + down once locally**

```bash
cd backend
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: all three commands exit 0; the DB schema picks up the two new tables.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/<rev>_watchlist_tabs_and_items.py
git commit -m "feat(watchlist): add watchlist_tab + watchlist_item tables"
```

---

### Task 2: SQLAlchemy ORM rows

**Files:**
- Modify: `backend/app/storage/schema.py` (append two Row classes)

- [ ] **Step 1: Write failing import test**

`backend/tests/storage/test_schema.py` (extend if already present, else create):

```python
def test_watchlist_rows_import():
    from app.storage.schema import WatchlistTabRow, WatchlistItemRow

    assert WatchlistTabRow.__tablename__ == "watchlist_tab"
    assert WatchlistItemRow.__tablename__ == "watchlist_item"
```

Run: `cd backend && uv run pytest tests/storage/test_schema.py::test_watchlist_rows_import -v`
Expected: FAIL (ImportError).

- [ ] **Step 2: Add the ORM rows**

Append to `backend/app/storage/schema.py`:

```python
class WatchlistTabRow(Base):
    __tablename__ = "watchlist_tab"
    __table_args__ = (Index("ix_watchlist_tab_account", "account_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class WatchlistItemRow(Base):
    __tablename__ = "watchlist_item"
    __table_args__ = (
        Index("ix_watchlist_item_tab", "tab_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tab_id: Mapped[str] = mapped_column(
        String, ForeignKey("watchlist_tab.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    option_type: Mapped[str | None] = mapped_column(String, nullable=True)
    option_strike: Mapped[float | None] = mapped_column(nullable=True)
    option_expiry: Mapped[str | None] = mapped_column(String, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
```

Make sure `Float` is imported if needed:

```python
from sqlalchemy import Float
```

- [ ] **Step 3: Verify the test passes**

Run: `cd backend && uv run pytest tests/storage/test_schema.py::test_watchlist_rows_import -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/storage/schema.py backend/tests/storage/test_schema.py
git commit -m "feat(watchlist): WatchlistTabRow + WatchlistItemRow ORM"
```

---

### Task 3: Repo — `list_tabs`

**Files:**
- Create: `backend/app/storage/watchlist_repo.py`
- Create: `backend/tests/storage/test_watchlist_repo.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/storage/test_watchlist_repo.py`:

```python
import pytest
from app.storage.watchlist_repo import list_tabs


@pytest.mark.asyncio
async def test_list_tabs_empty(async_session):
    # async_session is the existing fixture from conftest.py
    out = await list_tabs(async_session, account_id="acct-A")
    assert out == []
```

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py::test_list_tabs_empty -v`
Expected: FAIL (ModuleNotFoundError).

- [ ] **Step 2: Implement `list_tabs`**

`backend/app/storage/watchlist_repo.py`:

```python
"""Async repo for watchlist tabs + items.

All functions take an explicit ``account_id`` and filter every read/write
through it; the router gets the active account id from
LongPortRuntimeStore before invoking.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.storage.schema import WatchlistItemRow, WatchlistTabRow


@dataclass(frozen=True)
class WatchlistItem:
    id: str
    tab_id: str
    symbol: str
    kind: Literal["stock", "option"]
    ticker: str
    option_type: str | None
    option_strike: float | None
    option_expiry: str | None
    sort_order: int


@dataclass(frozen=True)
class WatchlistTab:
    id: str
    name: str
    sort_order: int
    items: list[WatchlistItem]


def _row_to_item(row: WatchlistItemRow) -> WatchlistItem:
    return WatchlistItem(
        id=row.id,
        tab_id=row.tab_id,
        symbol=row.symbol,
        kind=row.kind,  # type: ignore[arg-type]
        ticker=row.ticker,
        option_type=row.option_type,
        option_strike=row.option_strike,
        option_expiry=row.option_expiry,
        sort_order=row.sort_order,
    )


async def list_tabs(session: AsyncSession, account_id: str) -> list[WatchlistTab]:
    stmt = (
        select(WatchlistTabRow)
        .where(WatchlistTabRow.account_id == account_id)
        .order_by(WatchlistTabRow.sort_order.asc())
    )
    result = await session.execute(stmt)
    tab_rows = list(result.scalars().all())
    if not tab_rows:
        return []

    tab_ids = [t.id for t in tab_rows]
    items_stmt = (
        select(WatchlistItemRow)
        .where(WatchlistItemRow.tab_id.in_(tab_ids))
        .order_by(WatchlistItemRow.sort_order.asc())
    )
    items_result = await session.execute(items_stmt)
    items_by_tab: dict[str, list[WatchlistItem]] = {tid: [] for tid in tab_ids}
    for row in items_result.scalars().all():
        items_by_tab[row.tab_id].append(_row_to_item(row))

    return [
        WatchlistTab(id=t.id, name=t.name, sort_order=t.sort_order, items=items_by_tab[t.id])
        for t in tab_rows
    ]
```

- [ ] **Step 3: Verify the test passes**

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py::test_list_tabs_empty -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/storage/watchlist_repo.py backend/tests/storage/test_watchlist_repo.py
git commit -m "feat(watchlist): repo.list_tabs"
```

---

### Task 4: Repo — `create_tab` + `delete_tab`

**Files:**
- Modify: `backend/app/storage/watchlist_repo.py`
- Modify: `backend/tests/storage/test_watchlist_repo.py`

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/storage/test_watchlist_repo.py`:

```python
from app.storage.watchlist_repo import create_tab, delete_tab, list_tabs


@pytest.mark.asyncio
async def test_create_tab_assigns_sort_order(async_session):
    t1 = await create_tab(async_session, account_id="acct-A", name="watch-1")
    t2 = await create_tab(async_session, account_id="acct-A", name="watch-2")
    assert t1.sort_order == 0
    assert t2.sort_order == 1
    tabs = await list_tabs(async_session, "acct-A")
    assert [t.name for t in tabs] == ["watch-1", "watch-2"]


@pytest.mark.asyncio
async def test_create_tab_accounts_are_isolated(async_session):
    await create_tab(async_session, "acct-A", "a")
    await create_tab(async_session, "acct-B", "b")
    a_tabs = await list_tabs(async_session, "acct-A")
    b_tabs = await list_tabs(async_session, "acct-B")
    assert [t.name for t in a_tabs] == ["a"]
    assert [t.name for t in b_tabs] == ["b"]


@pytest.mark.asyncio
async def test_delete_tab(async_session):
    t = await create_tab(async_session, "acct-A", "doomed")
    await delete_tab(async_session, "acct-A", t.id)
    assert await list_tabs(async_session, "acct-A") == []


@pytest.mark.asyncio
async def test_delete_tab_wrong_account_is_404(async_session):
    from app.storage.watchlist_repo import NotFoundError
    t = await create_tab(async_session, "acct-A", "a")
    with pytest.raises(NotFoundError):
        await delete_tab(async_session, "acct-B", t.id)
```

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py -v`
Expected: FAIL (functions and `NotFoundError` not defined).

- [ ] **Step 2: Implement**

Append to `backend/app/storage/watchlist_repo.py`:

```python
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func


class NotFoundError(Exception):
    """Raised when a tab/item is not under the given account."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def create_tab(session: AsyncSession, account_id: str, name: str) -> WatchlistTab:
    name = name.strip()
    if not name:
        raise ValueError("name must be non-empty")

    max_stmt = select(func.coalesce(func.max(WatchlistTabRow.sort_order), -1)).where(
        WatchlistTabRow.account_id == account_id
    )
    next_order = int((await session.execute(max_stmt)).scalar_one()) + 1

    row = WatchlistTabRow(
        id=str(uuid.uuid4()),
        account_id=account_id,
        name=name,
        sort_order=next_order,
        created_at=_now_iso(),
    )
    session.add(row)
    await session.flush()
    return WatchlistTab(id=row.id, name=row.name, sort_order=row.sort_order, items=[])


async def delete_tab(session: AsyncSession, account_id: str, tab_id: str) -> None:
    # Verify ownership first
    stmt = select(WatchlistTabRow).where(
        WatchlistTabRow.id == tab_id, WatchlistTabRow.account_id == account_id
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        raise NotFoundError(tab_id)
    await session.execute(delete(WatchlistTabRow).where(WatchlistTabRow.id == tab_id))
```

Note: `ON DELETE CASCADE` was declared at the FK level in the migration; relying on the DB to cascade items is enough.

- [ ] **Step 3: Run the new tests**

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py -v`
Expected: PASS for all four added tests.

- [ ] **Step 4: Commit**

```bash
git add backend/app/storage/watchlist_repo.py backend/tests/storage/test_watchlist_repo.py
git commit -m "feat(watchlist): repo.create_tab + delete_tab"
```

---

### Task 5: Repo — `rename_tab`

**Files:**
- Modify: `backend/app/storage/watchlist_repo.py`
- Modify: `backend/tests/storage/test_watchlist_repo.py`

- [ ] **Step 1: Write failing tests**

```python
from app.storage.watchlist_repo import rename_tab


@pytest.mark.asyncio
async def test_rename_tab(async_session):
    t = await create_tab(async_session, "acct-A", "old")
    out = await rename_tab(async_session, "acct-A", t.id, "new")
    assert out.name == "new"
    tabs = await list_tabs(async_session, "acct-A")
    assert tabs[0].name == "new"


@pytest.mark.asyncio
async def test_rename_tab_wrong_account_is_404(async_session):
    from app.storage.watchlist_repo import NotFoundError
    t = await create_tab(async_session, "acct-A", "x")
    with pytest.raises(NotFoundError):
        await rename_tab(async_session, "acct-B", t.id, "hijack")
```

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py -v -k rename`
Expected: FAIL (rename_tab not defined).

- [ ] **Step 2: Implement**

```python
async def rename_tab(
    session: AsyncSession, account_id: str, tab_id: str, name: str
) -> WatchlistTab:
    name = name.strip()
    if not name:
        raise ValueError("name must be non-empty")
    stmt = select(WatchlistTabRow).where(
        WatchlistTabRow.id == tab_id, WatchlistTabRow.account_id == account_id
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError(tab_id)
    row.name = name
    await session.flush()
    return WatchlistTab(id=row.id, name=row.name, sort_order=row.sort_order, items=[])
```

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py -v -k rename`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/storage/watchlist_repo.py backend/tests/storage/test_watchlist_repo.py
git commit -m "feat(watchlist): repo.rename_tab"
```

---

### Task 6: Repo — `add_item` + `delete_item` + cascade

**Files:**
- Modify: `backend/app/storage/watchlist_repo.py`
- Modify: `backend/tests/storage/test_watchlist_repo.py`

- [ ] **Step 1: Write failing tests**

```python
from app.storage.watchlist_repo import (
    add_item, delete_item, DuplicateError,
)


@pytest.mark.asyncio
async def test_add_item_stock(async_session):
    tab = await create_tab(async_session, "acct-A", "t")
    item = await add_item(
        async_session,
        account_id="acct-A",
        tab_id=tab.id,
        draft=dict(
            symbol="AAPL.US", kind="stock", ticker="AAPL",
            option_type=None, option_strike=None, option_expiry=None,
        ),
    )
    assert item.symbol == "AAPL.US"
    assert item.sort_order == 0


@pytest.mark.asyncio
async def test_add_item_duplicate_is_409(async_session):
    tab = await create_tab(async_session, "acct-A", "t")
    draft = dict(symbol="AAPL.US", kind="stock", ticker="AAPL",
                 option_type=None, option_strike=None, option_expiry=None)
    await add_item(async_session, "acct-A", tab.id, draft)
    with pytest.raises(DuplicateError):
        await add_item(async_session, "acct-A", tab.id, draft)


@pytest.mark.asyncio
async def test_delete_item(async_session):
    tab = await create_tab(async_session, "acct-A", "t")
    item = await add_item(
        async_session, "acct-A", tab.id,
        dict(symbol="AAPL.US", kind="stock", ticker="AAPL",
             option_type=None, option_strike=None, option_expiry=None),
    )
    await delete_item(async_session, "acct-A", item.id)
    tabs = await list_tabs(async_session, "acct-A")
    assert tabs[0].items == []


@pytest.mark.asyncio
async def test_delete_tab_cascades_items(async_session):
    tab = await create_tab(async_session, "acct-A", "t")
    await add_item(
        async_session, "acct-A", tab.id,
        dict(symbol="AAPL.US", kind="stock", ticker="AAPL",
             option_type=None, option_strike=None, option_expiry=None),
    )
    await delete_tab(async_session, "acct-A", tab.id)
    # Verify item is gone too (no orphan)
    from app.storage.schema import WatchlistItemRow
    result = await async_session.execute(select(WatchlistItemRow))
    assert result.scalars().all() == []
```

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py -v -k "add_item or delete_item or cascade"`
Expected: FAIL.

- [ ] **Step 2: Implement**

Append to `watchlist_repo.py`:

```python
from sqlalchemy.exc import IntegrityError


class DuplicateError(Exception):
    """Raised when (tab_id, symbol) already exists."""


async def add_item(
    session: AsyncSession,
    account_id: str,
    tab_id: str,
    draft: dict,
) -> WatchlistItem:
    # Verify the tab belongs to the account.
    tab_stmt = select(WatchlistTabRow).where(
        WatchlistTabRow.id == tab_id, WatchlistTabRow.account_id == account_id
    )
    if (await session.execute(tab_stmt)).scalar_one_or_none() is None:
        raise NotFoundError(tab_id)

    max_stmt = select(func.coalesce(func.max(WatchlistItemRow.sort_order), -1)).where(
        WatchlistItemRow.tab_id == tab_id
    )
    next_order = int((await session.execute(max_stmt)).scalar_one()) + 1

    row = WatchlistItemRow(
        id=str(uuid.uuid4()),
        tab_id=tab_id,
        symbol=draft["symbol"],
        kind=draft["kind"],
        ticker=draft["ticker"],
        option_type=draft.get("option_type"),
        option_strike=draft.get("option_strike"),
        option_expiry=draft.get("option_expiry"),
        sort_order=next_order,
        created_at=_now_iso(),
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as e:
        # UNIQUE (tab_id, symbol) violation maps to 409
        await session.rollback()
        raise DuplicateError(f"{tab_id}:{draft['symbol']}") from e
    return _row_to_item(row)


async def delete_item(session: AsyncSession, account_id: str, item_id: str) -> None:
    # Join through tabs to enforce account scope.
    stmt = (
        select(WatchlistItemRow)
        .join(WatchlistTabRow, WatchlistTabRow.id == WatchlistItemRow.tab_id)
        .where(
            WatchlistItemRow.id == item_id,
            WatchlistTabRow.account_id == account_id,
        )
    )
    if (await session.execute(stmt)).scalar_one_or_none() is None:
        raise NotFoundError(item_id)
    await session.execute(delete(WatchlistItemRow).where(WatchlistItemRow.id == item_id))
```

- [ ] **Step 3: Run tests**

Run: `cd backend && uv run pytest tests/storage/test_watchlist_repo.py -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/app/storage/watchlist_repo.py backend/tests/storage/test_watchlist_repo.py
git commit -m "feat(watchlist): repo.add_item / delete_item with dup + cascade"
```

---

### Task 7: Pydantic schemas

**Files:**
- Modify: `backend/app/api/schemas.py`

- [ ] **Step 1: Write failing import test**

`backend/tests/api/test_schemas.py` (extend existing):

```python
def test_watchlist_schemas_import():
    from app.api.schemas import (
        WatchlistItemOut, WatchlistTabOut, WatchlistListOut,
        WatchlistTabCreateIn, WatchlistTabRenameIn, WatchlistItemCreateIn,
    )
    # smoke
    payload = WatchlistTabOut(
        id="t1", name="hi", sort_order=0, items=[]
    )
    assert payload.id == "t1"
```

Run: `cd backend && uv run pytest tests/api/test_schemas.py::test_watchlist_schemas_import -v`
Expected: FAIL.

- [ ] **Step 2: Add schemas**

Append to `backend/app/api/schemas.py`:

```python
class WatchlistItemOut(BaseModel):
    id: str
    tab_id: str
    symbol: str
    kind: Literal["stock", "option"]
    ticker: str
    option_type: Literal["CALL", "PUT"] | None = None
    option_strike: float | None = None
    option_expiry: str | None = None
    sort_order: int


class WatchlistTabOut(BaseModel):
    id: str
    name: str
    sort_order: int
    items: list[WatchlistItemOut] = []


class WatchlistListOut(BaseModel):
    tabs: list[WatchlistTabOut]


class WatchlistTabCreateIn(BaseModel):
    name: str


class WatchlistTabRenameIn(BaseModel):
    name: str


class WatchlistItemCreateIn(BaseModel):
    tab_id: str
    symbol: str
    kind: Literal["stock", "option"]
    ticker: str
    option_type: Literal["CALL", "PUT"] | None = None
    option_strike: float | None = None
    option_expiry: str | None = None
```

Make sure `Literal` is imported from `typing`.

- [ ] **Step 3: Run test**

Run: `cd backend && uv run pytest tests/api/test_schemas.py::test_watchlist_schemas_import -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/schemas.py backend/tests/api/test_schemas.py
git commit -m "feat(watchlist): pydantic schemas for watchlist endpoints"
```

---

### Task 8: FastAPI router — read + tab CUD

**Files:**
- Create: `backend/app/api/watchlist.py`
- Create: `backend/tests/api/test_watchlist_http.py`
- Modify: `backend/app/api/http.py` (wire router in)

- [ ] **Step 1: Write failing tests for tab CRUD**

`backend/tests/api/test_watchlist_http.py`:

```python
from fastapi.testclient import TestClient


def test_watchlist_list_empty_no_active_account(client_no_account: TestClient):
    r = client_no_account.get("/api/watchlist")
    assert r.status_code == 400


def test_watchlist_list_empty(client: TestClient):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    assert r.json() == {"tabs": []}


def test_watchlist_create_tab(client: TestClient):
    r = client.post("/api/watchlist/tab", json={"name": "watch-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "watch-1"
    assert body["sort_order"] == 0
    assert body["items"] == []


def test_watchlist_create_tab_empty_name_400(client: TestClient):
    r = client.post("/api/watchlist/tab", json={"name": "  "})
    assert r.status_code == 400


def test_watchlist_rename_tab(client: TestClient):
    created = client.post("/api/watchlist/tab", json={"name": "old"}).json()
    r = client.patch(f"/api/watchlist/tab/{created['id']}", json={"name": "new"})
    assert r.status_code == 200
    assert r.json()["name"] == "new"


def test_watchlist_delete_tab(client: TestClient):
    created = client.post("/api/watchlist/tab", json={"name": "doomed"}).json()
    r = client.delete(f"/api/watchlist/tab/{created['id']}")
    assert r.status_code == 200
    assert client.get("/api/watchlist").json() == {"tabs": []}


def test_watchlist_delete_tab_404(client: TestClient):
    r = client.delete("/api/watchlist/tab/does-not-exist")
    assert r.status_code == 404
```

The `client` and `client_no_account` fixtures: follow the existing pattern in `backend/tests/api/test_http.py` (which uses `make_app` + `TestClient`). Add a `client` fixture in the same file with an active account preset (call `runtime_store.add_account("acct-test"); runtime_store.set_active("acct-test")`). `client_no_account` skips `set_active`.

Run: `cd backend && uv run pytest tests/api/test_watchlist_http.py -v`
Expected: FAIL (router not registered).

- [ ] **Step 2: Implement the router**

`backend/app/api/watchlist.py`:

```python
"""/api/watchlist* — user-defined watchlist tabs.

Each row is scoped to the active LongBridge account_id; the router
reads that from the LongPortRuntimeStore on every call. There is no
account_id query parameter — clients always speak to the active account.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import require_app_token
from app.api.schemas import (
    WatchlistItemCreateIn,
    WatchlistItemOut,
    WatchlistListOut,
    WatchlistTabCreateIn,
    WatchlistTabOut,
    WatchlistTabRenameIn,
)
from app.broker.runtime_settings import LongPortRuntimeStore
from app.storage import watchlist_repo as repo
from app.storage.watchlist_repo import (
    DuplicateError,
    NotFoundError,
    WatchlistItem,
    WatchlistTab,
)


def _item_to_out(item: WatchlistItem) -> WatchlistItemOut:
    return WatchlistItemOut(
        id=item.id,
        tab_id=item.tab_id,
        symbol=item.symbol,
        kind=item.kind,
        ticker=item.ticker,
        option_type=item.option_type,
        option_strike=item.option_strike,
        option_expiry=item.option_expiry,
        sort_order=item.sort_order,
    )


def _tab_to_out(tab: WatchlistTab) -> WatchlistTabOut:
    return WatchlistTabOut(
        id=tab.id,
        name=tab.name,
        sort_order=tab.sort_order,
        items=[_item_to_out(i) for i in tab.items],
    )


def build_router(
    *,
    session_factory,  # async session callable () -> AsyncSession
    runtime_store: LongPortRuntimeStore,
    fetch_quote,      # async (symbol: str) -> object | None
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(require_app_token)])

    def _active_account() -> str:
        acct = runtime_store.get().active_account_id
        if not acct:
            raise HTTPException(400, detail="no active broker account")
        return acct

    @router.get("/api/watchlist", response_model=WatchlistListOut)
    async def get_watchlist() -> WatchlistListOut:
        acct = _active_account()
        async with session_factory() as session:
            tabs = await repo.list_tabs(session, acct)
        return WatchlistListOut(tabs=[_tab_to_out(t) for t in tabs])

    @router.post("/api/watchlist/tab", response_model=WatchlistTabOut)
    async def post_tab(body: WatchlistTabCreateIn) -> WatchlistTabOut:
        acct = _active_account()
        try:
            async with session_factory() as session:
                tab = await repo.create_tab(session, acct, body.name)
                await session.commit()
        except ValueError as e:
            raise HTTPException(400, detail=str(e)) from e
        return _tab_to_out(tab)

    @router.patch("/api/watchlist/tab/{tab_id}", response_model=WatchlistTabOut)
    async def patch_tab(tab_id: str, body: WatchlistTabRenameIn) -> WatchlistTabOut:
        acct = _active_account()
        try:
            async with session_factory() as session:
                tab = await repo.rename_tab(session, acct, tab_id, body.name)
                await session.commit()
        except NotFoundError as e:
            raise HTTPException(404, detail="tab not found") from e
        except ValueError as e:
            raise HTTPException(400, detail=str(e)) from e
        return _tab_to_out(tab)

    @router.delete("/api/watchlist/tab/{tab_id}")
    async def delete_tab(tab_id: str) -> dict:
        acct = _active_account()
        try:
            async with session_factory() as session:
                await repo.delete_tab(session, acct, tab_id)
                await session.commit()
        except NotFoundError as e:
            raise HTTPException(404, detail="tab not found") from e
        return {"ok": True}

    @router.post("/api/watchlist/item", response_model=WatchlistItemOut)
    async def post_item(body: WatchlistItemCreateIn) -> WatchlistItemOut:
        acct = _active_account()
        # 1. Validate symbol via quote_hub.
        quote = await fetch_quote(body.symbol)
        if quote is None:
            raise HTTPException(400, detail={"code": "quote_unavailable", "symbol": body.symbol})
        # 2. Persist.
        try:
            async with session_factory() as session:
                item = await repo.add_item(
                    session,
                    acct,
                    body.tab_id,
                    {
                        "symbol": body.symbol,
                        "kind": body.kind,
                        "ticker": body.ticker,
                        "option_type": body.option_type,
                        "option_strike": body.option_strike,
                        "option_expiry": body.option_expiry,
                    },
                )
                await session.commit()
        except NotFoundError as e:
            raise HTTPException(404, detail="tab not found") from e
        except DuplicateError as e:
            raise HTTPException(409, detail={"code": "duplicate"}) from e
        return _item_to_out(item)

    @router.delete("/api/watchlist/item/{item_id}")
    async def delete_item(item_id: str) -> dict:
        acct = _active_account()
        try:
            async with session_factory() as session:
                await repo.delete_item(session, acct, item_id)
                await session.commit()
        except NotFoundError as e:
            raise HTTPException(404, detail="item not found") from e
        return {"ok": True}

    return router
```

- [ ] **Step 3: Wire router into the app**

In `backend/app/api/http.py`, inside `make_router(...)` (or whichever factory builds the main router), import `app.api.watchlist` and call `app.include_router(watchlist.build_router(session_factory=..., runtime_store=runtime_store, fetch_quote=...))`. The `fetch_quote` callable should reuse the existing `/api/quote` machinery — pass in the same coroutine that returns `None` when quote_hub can't resolve a symbol.

In `backend/app/main.py`, wire the watchlist router after the existing routers are mounted. Pass in the broker's `quote_hub` accessor (e.g. `lambda s: quote_hub.fetch_one(s)`).

- [ ] **Step 4: Implement the test fixtures**

In `backend/tests/api/test_watchlist_http.py`, add a fixture that wires up a TestClient with a fake `fetch_quote` that always returns a non-None placeholder (we'll exercise the None path in Task 9):

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

@pytest.fixture
def client(make_app):
    # Reuse the same make_app fixture from test_http.py (or duplicate).
    app, runtime_store = make_app(active_account="acct-test", fetch_quote=lambda s: {"symbol": s})
    return TestClient(app)


@pytest.fixture
def client_no_account(make_app):
    app, _ = make_app(active_account=None, fetch_quote=lambda s: {"symbol": s})
    return TestClient(app)
```

If `make_app` doesn't accept `active_account` / `fetch_quote`, extend it.

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/api/test_watchlist_http.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/watchlist.py backend/app/api/http.py backend/app/main.py \
        backend/tests/api/test_watchlist_http.py
git commit -m "feat(watchlist): /api/watchlist router (read + tab CRUD)"
```

---

### Task 9: Router — item endpoints + quote validation

**Files:**
- Modify: `backend/tests/api/test_watchlist_http.py` (add item tests)

The item endpoints were implemented in Task 8 for completeness; this task adds the targeted tests.

- [ ] **Step 1: Write failing tests for item endpoints**

Append to `backend/tests/api/test_watchlist_http.py`:

```python
def test_watchlist_add_item_unknown_symbol_400(make_app):
    app, _ = make_app(active_account="acct-test", fetch_quote=lambda s: None)
    c = TestClient(app)
    tab = c.post("/api/watchlist/tab", json={"name": "t"}).json()
    r = c.post("/api/watchlist/item", json={
        "tab_id": tab["id"], "symbol": "BOGUS.US", "kind": "stock", "ticker": "BOGUS",
    })
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "quote_unavailable"


def test_watchlist_add_item_ok(client: TestClient):
    tab = client.post("/api/watchlist/tab", json={"name": "t"}).json()
    r = client.post("/api/watchlist/item", json={
        "tab_id": tab["id"], "symbol": "AAPL.US", "kind": "stock", "ticker": "AAPL",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AAPL.US"
    assert body["sort_order"] == 0


def test_watchlist_add_item_duplicate_409(client: TestClient):
    tab = client.post("/api/watchlist/tab", json={"name": "t"}).json()
    draft = {"tab_id": tab["id"], "symbol": "AAPL.US", "kind": "stock", "ticker": "AAPL"}
    assert client.post("/api/watchlist/item", json=draft).status_code == 200
    r2 = client.post("/api/watchlist/item", json=draft)
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "duplicate"


def test_watchlist_add_item_option(client: TestClient):
    tab = client.post("/api/watchlist/tab", json={"name": "t"}).json()
    r = client.post("/api/watchlist/item", json={
        "tab_id": tab["id"],
        "symbol": "AAPL250620C00170000",
        "kind": "option",
        "ticker": "AAPL",
        "option_type": "CALL",
        "option_strike": 170.0,
        "option_expiry": "2025-06-20",
    })
    assert r.status_code == 200
    assert r.json()["option_type"] == "CALL"


def test_watchlist_delete_item(client: TestClient):
    tab = client.post("/api/watchlist/tab", json={"name": "t"}).json()
    item = client.post("/api/watchlist/item", json={
        "tab_id": tab["id"], "symbol": "AAPL.US", "kind": "stock", "ticker": "AAPL",
    }).json()
    r = client.delete(f"/api/watchlist/item/{item['id']}")
    assert r.status_code == 200
    tabs = client.get("/api/watchlist").json()["tabs"]
    assert tabs[0]["items"] == []


def test_watchlist_account_isolation(make_app):
    app, runtime_store = make_app(active_account="acct-A", fetch_quote=lambda s: {"x": s})
    c = TestClient(app)
    c.post("/api/watchlist/tab", json={"name": "a-tab"})
    runtime_store.add_account("acct-B")
    runtime_store.set_active("acct-B")
    assert c.get("/api/watchlist").json() == {"tabs": []}
    runtime_store.set_active("acct-A")
    assert [t["name"] for t in c.get("/api/watchlist").json()["tabs"]] == ["a-tab"]
```

- [ ] **Step 2: Run them**

Run: `cd backend && uv run pytest tests/api/test_watchlist_http.py -v`
Expected: all PASS (router was already implemented in Task 8).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/api/test_watchlist_http.py
git commit -m "test(watchlist): item endpoints + quote-validation + account isolation"
```

---

## Frontend

### Task 10: `api.watchlist*` HTTP wrappers

**Files:**
- Modify: `frontend/src/api/http.ts`
- Modify: `frontend/src/api/domain-types.ts` (or wherever shared types live; if codegen, regenerate first)

- [ ] **Step 1: Regenerate `api/types.ts` from the backend OpenAPI**

Run the existing codegen command (look at `frontend/package.json` scripts; typically `npm run gen-types` or similar). After regen, `WatchlistTabOut`, `WatchlistItemOut`, etc. should be present in `frontend/src/api/types.ts`.

- [ ] **Step 2: Add typed wrappers**

Append to `frontend/src/api/http.ts` (near `api.quotes` / `api.watchQuotes`):

```ts
  async watchlistList(): Promise<{ tabs: WatchTab[] }> {
    return request<{ tabs: WatchTab[] }>("/api/watchlist");
  },

  async watchlistCreateTab(name: string): Promise<WatchTab> {
    return request<WatchTab>("/api/watchlist/tab", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
  },

  async watchlistRenameTab(id: string, name: string): Promise<WatchTab> {
    return request<WatchTab>(`/api/watchlist/tab/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    });
  },

  async watchlistDeleteTab(id: string): Promise<{ ok: true }> {
    return request(`/api/watchlist/tab/${encodeURIComponent(id)}`, { method: "DELETE" });
  },

  async watchlistAddItem(draft: WatchItemCreate): Promise<WatchItem> {
    return request<WatchItem>("/api/watchlist/item", {
      method: "POST",
      body: JSON.stringify(draft),
    });
  },

  async watchlistDeleteItem(id: string): Promise<{ ok: true }> {
    return request(`/api/watchlist/item/${encodeURIComponent(id)}`, { method: "DELETE" });
  },
```

Add the type imports / re-exports:

```ts
import type { WatchTab, WatchItem, WatchItemCreate } from "./domain-types";
```

In `frontend/src/api/domain-types.ts`, re-export the generated types under nicer aliases:

```ts
export type WatchTab = components["schemas"]["WatchlistTabOut"];
export type WatchItem = components["schemas"]["WatchlistItemOut"];
export type WatchItemCreate = components["schemas"]["WatchlistItemCreateIn"];
```

- [ ] **Step 3: Build the frontend to catch type errors**

Run: `cd frontend && npm run build`
Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/http.ts frontend/src/api/domain-types.ts frontend/src/api/types.ts
git commit -m "feat(watchlist): api wrappers + generated types"
```

---

### Task 11: `usePositionsTabStore`

**Files:**
- Create: `frontend/src/stores/positionsTab.ts`
- Create: `frontend/src/stores/positionsTab.test.ts`

- [ ] **Step 1: Write failing test**

`frontend/src/stores/positionsTab.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { usePositionsTabStore } from "./positionsTab";

describe("positionsTabStore", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    usePositionsTabStore.setState({ view: "stocks" });
    localStorage.clear();
  });

  it("defaults to stocks when localStorage empty", () => {
    expect(usePositionsTabStore.getState().view).toBe("stocks");
  });

  it("setView persists to localStorage", () => {
    usePositionsTabStore.getState().setView("options");
    expect(localStorage.getItem("positionsPanel.view")).toBe("options");
  });

  it("setView accepts a watch tab id", () => {
    usePositionsTabStore.getState().setView("watch-uuid-123");
    expect(usePositionsTabStore.getState().view).toBe("watch-uuid-123");
  });
});
```

Run: `cd frontend && npx vitest run src/stores/positionsTab.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 2: Implement**

`frontend/src/stores/positionsTab.ts`:

```ts
import { create } from "zustand";

export type ActiveTabView = "stocks" | "options" | string;

const LS_KEY = "positionsPanel.view";

function load(): ActiveTabView {
  try {
    const v = localStorage.getItem(LS_KEY);
    if (v) return v;
  } catch { /* private mode */ }
  return "stocks";
}

interface PositionsTabState {
  view: ActiveTabView;
  setView(v: ActiveTabView): void;
}

export const usePositionsTabStore = create<PositionsTabState>((set) => ({
  view: load(),
  setView: (v) => {
    try { localStorage.setItem(LS_KEY, v); } catch { /* noop */ }
    set({ view: v });
  },
}));
```

- [ ] **Step 3: Test**

Run: `cd frontend && npx vitest run src/stores/positionsTab.test.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/positionsTab.ts frontend/src/stores/positionsTab.test.ts
git commit -m "feat(watchlist): usePositionsTabStore (active sub-tab)"
```

---

### Task 12: `useWatchlistStore` — load + create + remove tab

**Files:**
- Create: `frontend/src/stores/watchlist.ts`
- Create: `frontend/src/stores/watchlist.test.ts`

- [ ] **Step 1: Write failing tests**

`frontend/src/stores/watchlist.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useWatchlistStore } from "./watchlist";
import { api } from "../api/http";

describe("watchlistStore", () => {
  beforeEach(() => {
    useWatchlistStore.getState().reset();
    vi.restoreAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it("starts empty and not loaded", () => {
    expect(useWatchlistStore.getState().tabs).toEqual([]);
    expect(useWatchlistStore.getState().loaded).toBe(false);
  });

  it("load() populates tabs from the server", async () => {
    const tabs = [{ id: "t1", name: "watch-1", sort_order: 0, items: [] }];
    vi.spyOn(api, "watchlistList").mockResolvedValue({ tabs });
    await useWatchlistStore.getState().load();
    expect(useWatchlistStore.getState().tabs).toHaveLength(1);
    expect(useWatchlistStore.getState().loaded).toBe(true);
  });

  it("createTab inserts optimistically, swaps id when server returns", async () => {
    vi.spyOn(api, "watchlistCreateTab").mockResolvedValue(
      { id: "real-1", name: "x", sort_order: 0, items: [] }
    );
    const p = useWatchlistStore.getState().createTab("x");
    // Optimistic row visible while in flight
    expect(useWatchlistStore.getState().tabs[0].id).toMatch(/^tmp-/);
    await p;
    expect(useWatchlistStore.getState().tabs[0].id).toBe("real-1");
  });

  it("createTab rolls back on error", async () => {
    vi.spyOn(api, "watchlistCreateTab").mockRejectedValue(new Error("boom"));
    await expect(useWatchlistStore.getState().createTab("x")).rejects.toThrow("boom");
    expect(useWatchlistStore.getState().tabs).toEqual([]);
  });

  it("removeTab removes locally and rolls back on error", async () => {
    useWatchlistStore.setState({
      loaded: true,
      tabs: [{ id: "t1", name: "x", sort_order: 0, items: [] }],
    });
    vi.spyOn(api, "watchlistDeleteTab").mockRejectedValue(new Error("nope"));
    await expect(useWatchlistStore.getState().removeTab("t1")).rejects.toThrow("nope");
    expect(useWatchlistStore.getState().tabs).toHaveLength(1);
  });
});
```

Run: `cd frontend && npx vitest run src/stores/watchlist.test.ts`
Expected: FAIL.

- [ ] **Step 2: Implement (partial)**

`frontend/src/stores/watchlist.ts`:

```ts
import { create } from "zustand";
import { api } from "../api/http";
import type { WatchTab, WatchItem } from "../api/domain-types";

interface WatchlistState {
  tabs: WatchTab[];
  loaded: boolean;
  loadError: string | null;

  load(): Promise<void>;
  createTab(name: string): Promise<WatchTab>;
  removeTab(id: string): Promise<void>;
  renameTab(id: string, name: string): Promise<void>;
  addItem(tabId: string, draft: WatchItemDraft): Promise<void>;
  removeItem(tabId: string, itemId: string): Promise<void>;
  reset(): void;
}

export interface WatchItemDraft {
  symbol: string;
  kind: "stock" | "option";
  ticker: string;
  option_type?: "CALL" | "PUT";
  option_strike?: number;
  option_expiry?: string;
}

let tmpCounter = 0;
function tmpId(): string {
  tmpCounter += 1;
  return `tmp-${tmpCounter}-${Math.random().toString(36).slice(2)}`;
}

export const useWatchlistStore = create<WatchlistState>((set, get) => ({
  tabs: [],
  loaded: false,
  loadError: null,

  reset() {
    set({ tabs: [], loaded: false, loadError: null });
  },

  async load() {
    try {
      const { tabs } = await api.watchlistList();
      set({ tabs, loaded: true, loadError: null });
    } catch (e) {
      set({ loadError: String(e), loaded: false });
    }
  },

  async createTab(name) {
    const optimistic: WatchTab = {
      id: tmpId(),
      name,
      sort_order: get().tabs.length,
      items: [],
    };
    set((s) => ({ tabs: [...s.tabs, optimistic] }));
    try {
      const real = await api.watchlistCreateTab(name);
      set((s) => ({
        tabs: s.tabs.map((t) => (t.id === optimistic.id ? real : t)),
      }));
      return real;
    } catch (e) {
      set((s) => ({ tabs: s.tabs.filter((t) => t.id !== optimistic.id) }));
      throw e;
    }
  },

  async removeTab(id) {
    const prev = get().tabs;
    set((s) => ({ tabs: s.tabs.filter((t) => t.id !== id) }));
    try {
      await api.watchlistDeleteTab(id);
    } catch (e) {
      set({ tabs: prev });
      throw e;
    }
  },

  async renameTab(id, name) {
    const prev = get().tabs;
    set((s) => ({
      tabs: s.tabs.map((t) => (t.id === id ? { ...t, name } : t)),
    }));
    try {
      await api.watchlistRenameTab(id, name);
    } catch (e) {
      set({ tabs: prev });
      throw e;
    }
  },

  async addItem(_tabId, _draft) {
    throw new Error("implemented in Task 13");
  },

  async removeItem(_tabId, _itemId) {
    throw new Error("implemented in Task 13");
  },
}));
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/stores/watchlist.test.ts`
Expected: PASS (all five).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/watchlist.ts frontend/src/stores/watchlist.test.ts
git commit -m "feat(watchlist): useWatchlistStore load + createTab + removeTab"
```

---

### Task 13: `useWatchlistStore` — addItem + removeItem

**Files:**
- Modify: `frontend/src/stores/watchlist.ts`
- Modify: `frontend/src/stores/watchlist.test.ts`

- [ ] **Step 1: Write failing tests**

Append to `watchlist.test.ts`:

```ts
it("addItem inserts optimistically and swaps id", async () => {
  useWatchlistStore.setState({
    loaded: true,
    tabs: [{ id: "t1", name: "x", sort_order: 0, items: [] }],
  });
  vi.spyOn(api, "watchlistAddItem").mockResolvedValue({
    id: "real-i1", tab_id: "t1", symbol: "AAPL.US", kind: "stock",
    ticker: "AAPL", sort_order: 0,
  });
  const p = useWatchlistStore.getState().addItem("t1", {
    symbol: "AAPL.US", kind: "stock", ticker: "AAPL",
  });
  expect(useWatchlistStore.getState().tabs[0].items[0].id).toMatch(/^tmp-/);
  await p;
  expect(useWatchlistStore.getState().tabs[0].items[0].id).toBe("real-i1");
});

it("addItem rolls back on rejection", async () => {
  useWatchlistStore.setState({
    loaded: true,
    tabs: [{ id: "t1", name: "x", sort_order: 0, items: [] }],
  });
  vi.spyOn(api, "watchlistAddItem").mockRejectedValue(new Error("bad symbol"));
  await expect(
    useWatchlistStore.getState().addItem("t1", {
      symbol: "BOGUS", kind: "stock", ticker: "BOGUS",
    })
  ).rejects.toThrow("bad symbol");
  expect(useWatchlistStore.getState().tabs[0].items).toHaveLength(0);
});

it("removeItem removes locally and rolls back on rejection", async () => {
  useWatchlistStore.setState({
    loaded: true,
    tabs: [{
      id: "t1", name: "x", sort_order: 0,
      items: [{ id: "i1", tab_id: "t1", symbol: "AAPL.US", kind: "stock",
                ticker: "AAPL", sort_order: 0 }],
    }],
  });
  vi.spyOn(api, "watchlistDeleteItem").mockRejectedValue(new Error("nope"));
  await expect(
    useWatchlistStore.getState().removeItem("t1", "i1")
  ).rejects.toThrow("nope");
  expect(useWatchlistStore.getState().tabs[0].items).toHaveLength(1);
});
```

Run: `cd frontend && npx vitest run src/stores/watchlist.test.ts`
Expected: 3 new tests FAIL (current impl just throws).

- [ ] **Step 2: Implement**

Replace the placeholder `addItem` / `removeItem`:

```ts
async addItem(tabId, draft) {
  const optimistic: WatchItem = {
    id: tmpId(),
    tab_id: tabId,
    symbol: draft.symbol,
    kind: draft.kind,
    ticker: draft.ticker,
    option_type: draft.option_type ?? null,
    option_strike: draft.option_strike ?? null,
    option_expiry: draft.option_expiry ?? null,
    sort_order: 0,
  };
  set((s) => ({
    tabs: s.tabs.map((t) =>
      t.id !== tabId ? t : { ...t, items: [...t.items, optimistic] }
    ),
  }));
  try {
    const real = await api.watchlistAddItem({ tab_id: tabId, ...draft });
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.id !== tabId
          ? t
          : {
              ...t,
              items: t.items.map((i) => (i.id === optimistic.id ? real : i)),
            }
      ),
    }));
  } catch (e) {
    set((s) => ({
      tabs: s.tabs.map((t) =>
        t.id !== tabId
          ? t
          : { ...t, items: t.items.filter((i) => i.id !== optimistic.id) }
      ),
    }));
    throw e;
  }
},

async removeItem(tabId, itemId) {
  const prev = get().tabs;
  set((s) => ({
    tabs: s.tabs.map((t) =>
      t.id !== tabId ? t : { ...t, items: t.items.filter((i) => i.id !== itemId) }
    ),
  }));
  try {
    await api.watchlistDeleteItem(itemId);
  } catch (e) {
    set({ tabs: prev });
    throw e;
  }
},
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/stores/watchlist.test.ts`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/watchlist.ts frontend/src/stores/watchlist.test.ts
git commit -m "feat(watchlist): store addItem + removeItem"
```

---

### Task 14: Symbol-assembly helpers

**Files:**
- Create: `frontend/src/components/Positions/watchSymbol.ts`
- Create: `frontend/src/components/Positions/watchSymbol.test.ts`

- [ ] **Step 1: Write failing tests**

`watchSymbol.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { buildStockSymbol, buildOptionSymbol } from "./watchSymbol";

describe("buildStockSymbol", () => {
  it("uppercases ticker and appends market", () => {
    expect(buildStockSymbol("aapl", "US")).toBe("AAPL.US");
    expect(buildStockSymbol("700", "HK")).toBe("700.HK");
  });

  it("rejects empty ticker", () => {
    expect(() => buildStockSymbol("", "US")).toThrow();
  });
});

describe("buildOptionSymbol", () => {
  it("assembles LongBridge format: TICKER + YYMMDD + C|P + strike*1000 padded to 8", () => {
    expect(
      buildOptionSymbol({ ticker: "AAPL", expiry: "2025-06-20", optionType: "CALL", strike: 170 })
    ).toBe("AAPL250620C00170000");
  });

  it("handles fractional strikes", () => {
    expect(
      buildOptionSymbol({ ticker: "TSLA", expiry: "2024-12-20", optionType: "PUT", strike: 437.5 })
    ).toBe("TSLA241220P00437500");
  });

  it("rejects malformed expiry", () => {
    expect(() => buildOptionSymbol({
      ticker: "AAPL", expiry: "2025/06/20", optionType: "CALL", strike: 170,
    })).toThrow();
  });
});
```

Run: `cd frontend && npx vitest run src/components/Positions/watchSymbol.test.ts`
Expected: FAIL.

- [ ] **Step 2: Implement**

`watchSymbol.ts`:

```ts
export type Market = "US" | "HK" | "SH" | "SZ";

export function buildStockSymbol(ticker: string, market: Market): string {
  const t = ticker.trim().toUpperCase();
  if (!t) throw new Error("ticker required");
  return `${t}.${market}`;
}

export interface OptionInput {
  ticker: string;
  expiry: string;          // YYYY-MM-DD
  optionType: "CALL" | "PUT";
  strike: number;
}

export function buildOptionSymbol(o: OptionInput): string {
  const m = o.expiry.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) throw new Error(`bad expiry: ${o.expiry}`);
  const yymmdd = `${m[1].slice(2)}${m[2]}${m[3]}`;
  const cp = o.optionType === "CALL" ? "C" : "P";
  // Strike encoded as integer with implicit 3 decimals, padded to 8 digits.
  const strikeKey = Math.round(o.strike * 1000).toString().padStart(8, "0");
  const ticker = o.ticker.trim().toUpperCase();
  if (!ticker) throw new Error("ticker required");
  return `${ticker}${yymmdd}${cp}${strikeKey}`;
}
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/components/Positions/watchSymbol.test.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/watchSymbol.ts frontend/src/components/Positions/watchSymbol.test.ts
git commit -m "feat(watchlist): symbol-assembly helpers"
```

---

### Task 15: `PositionCard` + `OptionCard` — `onRemove` prop

**Files:**
- Modify: `frontend/src/components/Positions/PositionCard.tsx`
- Modify: `frontend/src/components/Positions/OptionCard.tsx`
- Modify: `frontend/src/components/Positions/Positions.css`

- [ ] **Step 1: Extend test for PositionCard**

`PositionCard.test.tsx` (extend or append):

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { PositionCard } from "./PositionCard";

it("renders an × button when onRemove is provided", () => {
  const onRemove = vi.fn();
  const onClick = vi.fn();
  render(
    <PositionCard
      position={{
        symbol: "AAPL.US", ticker: "AAPL", quantity: 0, avg_cost: null,
        type: "stock", option_type: null, option_strike: null, option_expiry: null,
      } as any}
      quote={undefined} intraday={undefined} executions={[]}
      onClick={onClick}
      onRemove={onRemove}
    />,
  );
  const btn = screen.getByLabelText("移除卡片");
  fireEvent.click(btn);
  expect(onRemove).toHaveBeenCalled();
  expect(onClick).not.toHaveBeenCalled();   // stopPropagation
});

it("does not render × when onRemove is omitted", () => {
  render(
    <PositionCard
      position={{ symbol: "AAPL.US", ticker: "AAPL", quantity: 100, avg_cost: 150,
                  type: "stock", option_type: null, option_strike: null, option_expiry: null } as any}
      quote={undefined} intraday={undefined} executions={[]}
    />,
  );
  expect(screen.queryByLabelText("移除卡片")).toBeNull();
});
```

Run: `cd frontend && npx vitest run src/components/Positions/PositionCard.test.tsx`
Expected: 2 tests FAIL.

- [ ] **Step 2: Implement on PositionCard**

In `PositionCard.tsx`:

1. Add `onRemove?: () => void` to `Props`.
2. Inside the root `<div class="pcard">`, render this snippet *before* the existing content:

```tsx
{onRemove && (
  <button
    type="button"
    className="pcard-x"
    aria-label="移除卡片"
    onClick={(e) => { e.stopPropagation(); onRemove(); }}
  >
    ×
  </button>
)}
```

- [ ] **Step 3: Mirror on OptionCard**

Apply the same change to `OptionCard.tsx` (add `onRemove?: () => void`, render `<button class="ocard-x">` with the same handler, same `aria-label="移除卡片"`).

- [ ] **Step 4: Add CSS**

Append to `Positions.css`:

```css
/* Hover-revealed × on watchlist cards. .pcard / .ocard already have
 * position: relative + a hover state, so anchoring is straightforward. */
.pcard-x,
.ocard-x {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: var(--err);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  border-radius: 50%;
  opacity: 0;
  transition: opacity var(--dur) var(--ease), background var(--dur) var(--ease);
}
.pcard:hover .pcard-x,
.ocard:hover .ocard-x,
.pcard-x:focus-visible,
.ocard-x:focus-visible {
  opacity: 1;
}
.pcard-x:hover,
.ocard-x:hover {
  background: rgba(239, 91, 91, 0.12);
}
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/Positions/`
Expected: existing + new tests all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Positions/PositionCard.tsx \
        frontend/src/components/Positions/OptionCard.tsx \
        frontend/src/components/Positions/Positions.css \
        frontend/src/components/Positions/PositionCard.test.tsx
git commit -m "feat(watchlist): PositionCard / OptionCard onRemove × affordance"
```

---

### Task 16: `AddCardPlaceholder` component

**Files:**
- Create: `frontend/src/components/Positions/AddCardPlaceholder.tsx`

- [ ] **Step 1: Write the file**

```tsx
interface Props {
  onClick(): void;
}

export function AddCardPlaceholder({ onClick }: Props) {
  return (
    <button
      type="button"
      className="addcard-placeholder"
      onClick={onClick}
      aria-label="添加关注标的"
    >
      <span className="addcard-plus">＋</span>
      <span className="addcard-label">添加关注</span>
    </button>
  );
}
```

- [ ] **Step 2: CSS**

Append to `Positions.css`:

```css
.addcard-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 160px;
  background: transparent;
  border: 1.5px dashed var(--line);
  border-radius: var(--radius-card);
  color: var(--fg-3);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease),
              background var(--dur) var(--ease);
}
.addcard-placeholder:hover {
  border-color: var(--brand);
  color: var(--brand);
  background: rgba(var(--brand-rgb), 0.04);
}
.addcard-plus { font-size: 28px; font-weight: 300; line-height: 1; }
.addcard-label { font-size: 11px; letter-spacing: 0.1em; text-transform: uppercase; }
```

- [ ] **Step 3: Smoke build**

Run: `cd frontend && npm run build`
Expected: builds clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/AddCardPlaceholder.tsx \
        frontend/src/components/Positions/Positions.css
git commit -m "feat(watchlist): AddCardPlaceholder"
```

---

### Task 17: `PositionsTabStrip` component

**Files:**
- Create: `frontend/src/components/Positions/PositionsTabStrip.tsx`
- Create: `frontend/src/components/Positions/PositionsTabStrip.css`
- Create: `frontend/src/components/Positions/PositionsTabStrip.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PositionsTabStrip } from "./PositionsTabStrip";

describe("PositionsTabStrip", () => {
  const tabs = [
    { id: "watch-1", name: "watch-1", sort_order: 0, items: [] },
    { id: "watch-2", name: "watch-2", sort_order: 1, items: [] },
  ];

  it("renders [正股, 期权, ...user tabs, +] in order", () => {
    render(
      <PositionsTabStrip
        view="stocks"
        stocksCount={3}
        optionsCount={2}
        tabs={tabs}
        onSelect={() => {}}
        onAdd={() => {}}
        onRemoveTab={() => {}}
        onRename={() => {}}
      />
    );
    const buttons = screen.getAllByRole("tab");
    expect(buttons[0]).toHaveTextContent("正股");
    expect(buttons[1]).toHaveTextContent("期权");
    expect(buttons[2]).toHaveTextContent("watch-1");
    expect(buttons[3]).toHaveTextContent("watch-2");
    expect(screen.getByLabelText("新增关注 tab")).toBeInTheDocument();
  });

  it("正股 and 期权 tabs do not render a remove ×", () => {
    render(
      <PositionsTabStrip
        view="stocks" stocksCount={0} optionsCount={0} tabs={tabs}
        onSelect={() => {}} onAdd={() => {}} onRemoveTab={() => {}} onRename={() => {}}
      />
    );
    const xs = screen.getAllByLabelText("删除 tab");
    expect(xs).toHaveLength(2);   // exactly the two user tabs
  });

  it("clicking × on a watch tab calls onRemoveTab and stops propagation", () => {
    const onSelect = vi.fn();
    const onRemoveTab = vi.fn();
    render(
      <PositionsTabStrip
        view="stocks" stocksCount={0} optionsCount={0} tabs={tabs}
        onSelect={onSelect} onAdd={() => {}} onRemoveTab={onRemoveTab} onRename={() => {}}
      />
    );
    fireEvent.click(screen.getAllByLabelText("删除 tab")[0]);
    expect(onRemoveTab).toHaveBeenCalledWith("watch-1");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("clicking + reveals an input; submitting calls onAdd", () => {
    const onAdd = vi.fn();
    render(
      <PositionsTabStrip
        view="stocks" stocksCount={0} optionsCount={0} tabs={tabs}
        onSelect={() => {}} onAdd={onAdd} onRemoveTab={() => {}} onRename={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText("新增关注 tab"));
    const input = screen.getByPlaceholderText("tab 名字");
    fireEvent.change(input, { target: { value: "半导体" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onAdd).toHaveBeenCalledWith("半导体");
  });
});
```

Run: `cd frontend && npx vitest run src/components/Positions/PositionsTabStrip.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 2: Implement**

`PositionsTabStrip.tsx`:

```tsx
import { useState } from "react";
import type { WatchTab } from "../../api/domain-types";
import type { ActiveTabView } from "../../stores/positionsTab";
import "./PositionsTabStrip.css";

interface Props {
  view: ActiveTabView;
  stocksCount: number;
  optionsCount: number;
  tabs: WatchTab[];
  onSelect(v: ActiveTabView): void;
  onAdd(name: string): void;
  onRemoveTab(id: string): void;
  onRename(id: string, name: string): void;
}

export function PositionsTabStrip({
  view, stocksCount, optionsCount, tabs,
  onSelect, onAdd, onRemoveTab, onRename,
}: Props) {
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");
  const [renameId, setRenameId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const submitAdd = () => {
    const v = newName.trim();
    if (v) onAdd(v);
    setAdding(false);
    setNewName("");
  };
  const submitRename = () => {
    if (!renameId) return;
    const v = renameValue.trim();
    if (v) onRename(renameId, v);
    setRenameId(null);
    setRenameValue("");
  };

  return (
    <div className="positions-tabs" role="tablist" aria-label="持仓与关注分类">
      <button
        role="tab"
        aria-selected={view === "stocks"}
        className={view === "stocks" ? "active" : ""}
        onClick={() => onSelect("stocks")}
        type="button"
      >
        正股 <span className="count">{stocksCount}</span>
      </button>
      <button
        role="tab"
        aria-selected={view === "options"}
        className={view === "options" ? "active" : ""}
        onClick={() => onSelect("options")}
        type="button"
      >
        期权 <span className="count">{optionsCount}</span>
      </button>

      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={view === t.id}
          className={`watch-tab${view === t.id ? " active" : ""}`}
          onClick={() => onSelect(t.id)}
          onDoubleClick={() => {
            setRenameId(t.id);
            setRenameValue(t.name);
          }}
          type="button"
        >
          {renameId === t.id ? (
            <input
              autoFocus
              className="tab-rename-input"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") submitRename();
                if (e.key === "Escape") { setRenameId(null); setRenameValue(""); }
              }}
              onBlur={submitRename}
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <>
              {t.name} <span className="count">{t.items.length}</span>
              <span
                role="button"
                tabIndex={0}
                aria-label="删除 tab"
                className="tab-x"
                onClick={(e) => { e.stopPropagation(); onRemoveTab(t.id); }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.stopPropagation(); onRemoveTab(t.id);
                  }
                }}
              >
                ×
              </span>
            </>
          )}
        </button>
      ))}

      {adding ? (
        <input
          autoFocus
          className="tab-new-input"
          placeholder="tab 名字"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitAdd();
            if (e.key === "Escape") { setAdding(false); setNewName(""); }
          }}
          onBlur={submitAdd}
        />
      ) : (
        <button
          type="button"
          aria-label="新增关注 tab"
          className="tab-add"
          onClick={() => setAdding(true)}
        >
          ＋
        </button>
      )}
    </div>
  );
}
```

`PositionsTabStrip.css`:

```css
/* User-tab × button — hover-revealed inside .positions-tabs button. */
.positions-tabs .watch-tab { position: relative; padding-right: 22px; }
.positions-tabs .tab-x {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  margin-left: 6px;
  border-radius: 50%;
  color: var(--err);
  font-size: 14px;
  line-height: 1;
  opacity: 0;
  transition: opacity var(--dur) var(--ease);
}
.positions-tabs .watch-tab:hover .tab-x { opacity: 1; }
.positions-tabs .tab-x:hover { background: rgba(239, 91, 91, 0.12); }

/* New-tab + button — same chip surface as existing tab buttons. */
.positions-tabs .tab-add {
  background: transparent;
  border: none;
  color: var(--fg-3);
  font-size: 14px;
  padding: 4px 10px;
  cursor: pointer;
  border-radius: calc(var(--radius-chip) - 2px);
}
.positions-tabs .tab-add:hover { color: var(--fg-1); background: var(--bg-hover); }

.positions-tabs .tab-new-input,
.positions-tabs .tab-rename-input {
  background: transparent;
  border: 1px solid var(--line);
  border-radius: calc(var(--radius-chip) - 2px);
  padding: 2px 8px;
  font-size: 11px;
  color: var(--fg-1);
  outline: none;
  min-width: 80px;
}
.positions-tabs .tab-new-input:focus,
.positions-tabs .tab-rename-input:focus { border-color: var(--brand); }
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/components/Positions/PositionsTabStrip.test.tsx`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/PositionsTabStrip.tsx \
        frontend/src/components/Positions/PositionsTabStrip.css \
        frontend/src/components/Positions/PositionsTabStrip.test.tsx
git commit -m "feat(watchlist): PositionsTabStrip with + and × affordances"
```

---

### Task 18: `WatchAddModal` component

**Files:**
- Create: `frontend/src/components/Positions/WatchAddModal.tsx`
- Create: `frontend/src/components/Positions/WatchAddModal.css`
- Create: `frontend/src/components/Positions/WatchAddModal.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WatchAddModal } from "./WatchAddModal";

describe("WatchAddModal", () => {
  it("defaults to stock mode and submits with assembled symbol", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<WatchAddModal tabId="t1" onSubmit={onSubmit} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("代码"), { target: { value: "aapl" } });
    fireEvent.change(screen.getByLabelText("市场"), { target: { value: "US" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      symbol: "AAPL.US", kind: "stock", ticker: "AAPL",
    }));
  });

  it("switches to option mode and assembles option symbol", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<WatchAddModal tabId="t1" onSubmit={onSubmit} onClose={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "期权" }));
    fireEvent.change(screen.getByLabelText("代码"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByLabelText("到期日"), { target: { value: "2025-06-20" } });
    fireEvent.change(screen.getByLabelText("行权价"), { target: { value: "170" } });
    fireEvent.click(screen.getByLabelText("看涨"));
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      symbol: "AAPL250620C00170000",
      kind: "option",
      ticker: "AAPL",
      option_type: "CALL",
      option_strike: 170,
      option_expiry: "2025-06-20",
    }));
  });

  it("renders inline error when onSubmit rejects", async () => {
    const onSubmit = vi.fn().mockRejectedValue(
      Object.assign(new Error("bad"), { status: 400, body: { detail: { code: "quote_unavailable" } } })
    );
    render(<WatchAddModal tabId="t1" onSubmit={onSubmit} onClose={() => {}} />);
    fireEvent.change(screen.getByLabelText("代码"), { target: { value: "BOGUS" } });
    fireEvent.click(screen.getByRole("button", { name: "添加" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/找不到该 symbol 的行情/)
    );
  });
});
```

Run: `cd frontend && npx vitest run src/components/Positions/WatchAddModal.test.tsx`
Expected: FAIL.

- [ ] **Step 2: Implement**

`WatchAddModal.tsx`:

```tsx
import { useState } from "react";
import { buildOptionSymbol, buildStockSymbol, type Market } from "./watchSymbol";
import "./WatchAddModal.css";
import type { WatchItemDraft } from "../../stores/watchlist";

interface Props {
  tabId: string;
  onSubmit(draft: WatchItemDraft): Promise<void>;
  onClose(): void;
}

type Mode = "stock" | "option";

const ERROR_MESSAGES: Record<string, string> = {
  quote_unavailable: "找不到该 symbol 的行情，请检查代码",
  duplicate: "这个 symbol 已经在此 tab 里",
};

export function WatchAddModal({ tabId, onSubmit, onClose }: Props) {
  const [mode, setMode] = useState<Mode>("stock");
  const [ticker, setTicker] = useState("");
  const [market, setMarket] = useState<Market>("US");
  const [expiry, setExpiry] = useState("");
  const [strike, setStrike] = useState("");
  const [optionType, setOptionType] = useState<"CALL" | "PUT">("CALL");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  void tabId;   // tabId is consumed by the caller via onSubmit; we don't echo it here

  const handleSubmit = async () => {
    setError(null);
    let draft: WatchItemDraft;
    try {
      if (mode === "stock") {
        draft = {
          symbol: buildStockSymbol(ticker, market),
          kind: "stock",
          ticker: ticker.trim().toUpperCase(),
        };
      } else {
        draft = {
          symbol: buildOptionSymbol({
            ticker, expiry, optionType, strike: Number(strike),
          }),
          kind: "option",
          ticker: ticker.trim().toUpperCase(),
          option_type: optionType,
          option_strike: Number(strike),
          option_expiry: expiry,
        };
      }
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit(draft);
      onClose();
    } catch (e: any) {
      const code = e?.body?.detail?.code as string | undefined;
      setError(code ? (ERROR_MESSAGES[code] ?? "添加失败，请重试") : "添加失败，请重试");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="watch-modal-overlay" onClick={onClose}>
      <div className="watch-modal" onClick={(e) => e.stopPropagation()}>
        <header className="watch-modal-head">
          <div className="watch-modal-segments">
            <button
              type="button"
              className={mode === "stock" ? "active" : ""}
              onClick={() => setMode("stock")}
            >
              股票
            </button>
            <button
              type="button"
              className={mode === "option" ? "active" : ""}
              onClick={() => setMode("option")}
            >
              期权
            </button>
          </div>
          <button type="button" className="watch-modal-close" onClick={onClose}>×</button>
        </header>

        <div className="watch-modal-body">
          <label>
            <span>代码</span>
            <input
              aria-label="代码"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              autoFocus
            />
          </label>
          <label>
            <span>市场</span>
            <select
              aria-label="市场"
              value={market}
              onChange={(e) => setMarket(e.target.value as Market)}
            >
              <option value="US">US</option>
              <option value="HK">HK</option>
              <option value="SH">SH</option>
              <option value="SZ">SZ</option>
            </select>
          </label>

          {mode === "option" && (
            <>
              <label>
                <span>到期日</span>
                <input
                  aria-label="到期日"
                  type="date"
                  value={expiry}
                  onChange={(e) => setExpiry(e.target.value)}
                />
              </label>
              <label>
                <span>行权价</span>
                <input
                  aria-label="行权价"
                  type="number"
                  step="0.001"
                  value={strike}
                  onChange={(e) => setStrike(e.target.value)}
                />
              </label>
              <div className="watch-modal-cp">
                <label>
                  <input
                    aria-label="看涨"
                    type="radio"
                    checked={optionType === "CALL"}
                    onChange={() => setOptionType("CALL")}
                  /> 看涨 Call
                </label>
                <label>
                  <input
                    aria-label="看跌"
                    type="radio"
                    checked={optionType === "PUT"}
                    onChange={() => setOptionType("PUT")}
                  /> 看跌 Put
                </label>
              </div>
            </>
          )}

          {error && <div role="alert" className="watch-modal-error">{error}</div>}
        </div>

        <footer className="watch-modal-foot">
          <button type="button" onClick={onClose}>取消</button>
          <button
            type="button"
            className="watch-modal-submit"
            onClick={handleSubmit}
            disabled={submitting || !ticker.trim() ||
              (mode === "option" && (!expiry || !strike))}
          >
            {submitting ? "提交中…" : "添加"}
          </button>
        </footer>
      </div>
    </div>
  );
}
```

`WatchAddModal.css`:

```css
.watch-modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0, 0, 0, 0.42);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.watch-modal {
  background: var(--bg-1);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  min-width: 340px;
  padding: 16px 18px;
  box-shadow: 0 8px 36px rgba(0, 0, 0, 0.5);
}
.watch-modal-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 12px;
}
.watch-modal-segments {
  display: inline-flex; gap: 2px;
  background: var(--bg-2);
  border: 1px solid var(--line);
  border-radius: var(--radius-chip);
  padding: 2px;
}
.watch-modal-segments button {
  background: transparent; border: none; color: var(--fg-3);
  font-size: 11px; letter-spacing: 0.08em; padding: 4px 12px;
  border-radius: calc(var(--radius-chip) - 2px); cursor: pointer;
}
.watch-modal-segments button.active {
  background: var(--bg-hover); color: var(--fg-1);
}
.watch-modal-close {
  background: transparent; border: none; color: var(--fg-3); font-size: 18px; cursor: pointer;
}
.watch-modal-body { display: flex; flex-direction: column; gap: 10px; }
.watch-modal-body label {
  display: flex; align-items: center; gap: 12px;
  font-size: 12px; color: var(--fg-3);
}
.watch-modal-body label > span { width: 70px; }
.watch-modal-body input,
.watch-modal-body select {
  flex: 1; background: var(--bg-2); border: 1px solid var(--line);
  color: var(--fg-1); padding: 6px 8px; border-radius: 4px;
  font-family: var(--font-mono); font-size: 12px;
}
.watch-modal-cp { display: flex; gap: 16px; font-size: 12px; color: var(--fg-2); }
.watch-modal-error {
  margin-top: 6px;
  color: var(--err);
  font-size: 11px;
  padding: 6px 8px;
  background: rgba(239, 91, 91, 0.10);
  border-radius: 4px;
}
.watch-modal-foot {
  display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px;
}
.watch-modal-foot button {
  font-size: 12px; padding: 5px 14px;
  border-radius: var(--radius-chip);
  border: 1px solid var(--line);
  background: var(--bg-2);
  color: var(--fg-2); cursor: pointer;
}
.watch-modal-foot .watch-modal-submit {
  background: var(--brand); color: #0b0f14; border-color: var(--brand);
}
.watch-modal-foot button:disabled { opacity: 0.4; cursor: not-allowed; }
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/components/Positions/WatchAddModal.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/WatchAddModal.tsx \
        frontend/src/components/Positions/WatchAddModal.css \
        frontend/src/components/Positions/WatchAddModal.test.tsx
git commit -m "feat(watchlist): WatchAddModal (stock/option segmented form)"
```

---

### Task 19: `WatchlistGrid` component

**Files:**
- Create: `frontend/src/components/Positions/WatchlistGrid.tsx`
- Create: `frontend/src/components/Positions/WatchlistGrid.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { WatchlistGrid } from "./WatchlistGrid";
import type { WatchTab } from "../../api/domain-types";

const emptyTab: WatchTab = { id: "t1", name: "x", sort_order: 0, items: [] };
const fullTab: WatchTab = {
  id: "t2", name: "y", sort_order: 1, items: [
    { id: "i1", tab_id: "t2", symbol: "AAPL.US", kind: "stock",
      ticker: "AAPL", sort_order: 0,
      option_type: null, option_strike: null, option_expiry: null,
    } as any,
    { id: "i2", tab_id: "t2", symbol: "AAPL250620C00170000", kind: "option",
      ticker: "AAPL", option_type: "CALL", option_strike: 170, option_expiry: "2025-06-20",
      sort_order: 1,
    } as any,
  ],
};

describe("WatchlistGrid", () => {
  it("0 items renders just the placeholder", () => {
    render(<WatchlistGrid tab={emptyTab} quotesBySymbol={{}} candleByKey={{}}
      onAdd={() => {}} onRemoveItem={() => {}} onCardClick={() => {}} />);
    expect(screen.getByLabelText("添加关注标的")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /移除卡片/ })).toBeNull();
  });

  it("N items renders N cards + placeholder", () => {
    render(<WatchlistGrid tab={fullTab} quotesBySymbol={{}} candleByKey={{}}
      onAdd={() => {}} onRemoveItem={() => {}} onCardClick={() => {}} />);
    expect(screen.getAllByLabelText("移除卡片")).toHaveLength(2);
    expect(screen.getByLabelText("添加关注标的")).toBeInTheDocument();
  });

  it("clicking × calls onRemoveItem with the item id, not onCardClick", () => {
    const onRemove = vi.fn();
    const onClick = vi.fn();
    render(<WatchlistGrid tab={fullTab} quotesBySymbol={{}} candleByKey={{}}
      onAdd={() => {}} onRemoveItem={onRemove} onCardClick={onClick} />);
    fireEvent.click(screen.getAllByLabelText("移除卡片")[0]);
    expect(onRemove).toHaveBeenCalledWith("i1");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("clicking + calls onAdd with the tab id", () => {
    const onAdd = vi.fn();
    render(<WatchlistGrid tab={emptyTab} quotesBySymbol={{}} candleByKey={{}}
      onAdd={onAdd} onRemoveItem={() => {}} onCardClick={() => {}} />);
    fireEvent.click(screen.getByLabelText("添加关注标的"));
    expect(onAdd).toHaveBeenCalledWith("t1");
  });
});
```

Run: `cd frontend && npx vitest run src/components/Positions/WatchlistGrid.test.tsx`
Expected: FAIL.

- [ ] **Step 2: Implement**

```tsx
import type { Position, Quote, Candlesticks } from "../../api/domain-types";
import type { WatchTab, WatchItem } from "../../api/domain-types";
import { PositionCard } from "./PositionCard";
import { OptionCard } from "./OptionCard";
import { AddCardPlaceholder } from "./AddCardPlaceholder";
import { candleCacheKey } from "../../stores/candlesticks";

interface Props {
  tab: WatchTab;
  quotesBySymbol: Record<string, Quote | undefined>;
  candleByKey: Record<string, Candlesticks | undefined>;
  onAdd(tabId: string): void;
  onRemoveItem(itemId: string): void;
  onCardClick(symbol: string): void;
}

export function watchItemToPosition(item: WatchItem): Position {
  return {
    symbol: item.symbol,
    ticker: item.ticker,
    quantity: 0,
    avg_cost: null,
    type: item.kind === "option" ? "option" : "stock",
    option_type: item.option_type ?? null,
    option_strike: item.option_strike ?? null,
    option_expiry: item.option_expiry ?? null,
  } as Position;
}

export function WatchlistGrid({
  tab, quotesBySymbol, candleByKey, onAdd, onRemoveItem, onCardClick,
}: Props) {
  return (
    <div className="positions-grid">
      {tab.items.map((item) => {
        const pseudo = watchItemToPosition(item);
        if (item.kind === "stock") {
          return (
            <PositionCard
              key={item.id}
              position={pseudo}
              quote={quotesBySymbol[item.symbol]}
              intraday={candleByKey[candleCacheKey(item.symbol, "today", "分时", "regular")]}
              executions={[]}
              onClick={() => onCardClick(item.symbol)}
              onRemove={() => onRemoveItem(item.id)}
            />
          );
        }
        return (
          <OptionCard
            key={item.id}
            position={pseudo}
            quote={quotesBySymbol[item.symbol]}
            history={candleByKey[candleCacheKey(item.symbol, "30")]}
            executions={[]}
            onClick={() => onCardClick(item.symbol)}
            onRemove={() => onRemoveItem(item.id)}
          />
        );
      })}
      <AddCardPlaceholder onClick={() => onAdd(tab.id)} />
    </div>
  );
}
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/components/Positions/WatchlistGrid.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/WatchlistGrid.tsx \
        frontend/src/components/Positions/WatchlistGrid.test.tsx
git commit -m "feat(watchlist): WatchlistGrid (cards + placeholder)"
```

---

### Task 20: `DetailPane` `watchOnly` prop

**Files:**
- Modify: `frontend/src/components/Positions/DetailPane.tsx`

- [ ] **Step 1: Inspect existing pair / summary branches**

Read `DetailPane.tsx` and locate:
- The 做T pair fetch (likely uses `usePairsStore` or `api.pairs(...)`).
- The portfolio-summary / position-aggregate header (cells with 持仓 / 均价 / 浮盈).

- [ ] **Step 2: Add `watchOnly` prop with gates**

```tsx
interface DetailPaneProps {
  position: Position;
  onBack(): void;
  watchOnly?: boolean;
}
```

Inside the component:

- If `watchOnly`, skip the pair fetch effect (`if (watchOnly) return;` at the top of the effect body).
- Conditionally render the position-aggregate header: `{!watchOnly && <PositionAggregateHeader ... />}`.
- The made-T pair tab/section: wrap its render in `!watchOnly && (...)`.
- Trade-list + chart sections render unchanged.

- [ ] **Step 3: Smoke test**

`DetailPane.test.tsx` (extend if it exists, else create):

```tsx
it("hides pair section in watchOnly mode", () => {
  render(<DetailPane
    position={makeFakePosition({ quantity: 0, avg_cost: null })}
    onBack={() => {}}
    watchOnly
  />);
  expect(screen.queryByText(/做T/)).toBeNull();
});
```

Run: `cd frontend && npx vitest run src/components/Positions/DetailPane.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Positions/DetailPane.tsx \
        frontend/src/components/Positions/DetailPane.test.tsx
git commit -m "feat(watchlist): DetailPane watchOnly mode"
```

---

### Task 21: Rewrite `PositionsPanel` — tab strip + body routing + subscription effect

**Files:**
- Modify: `frontend/src/components/Positions/PositionsPanel.tsx`

This is the most invasive task. Read the current `PositionsPanel.tsx` end-to-end before starting.

- [ ] **Step 1: Replace tab-strip with `PositionsTabStrip`**

Remove the inline `tabs` JSX block (`PositionsPanel.tsx:227-248`) and instead import + render:

```tsx
import { PositionsTabStrip } from "./PositionsTabStrip";
import { usePositionsTabStore } from "../../stores/positionsTab";
import { useWatchlistStore } from "../../stores/watchlist";
import { WatchlistGrid } from "./WatchlistGrid";
import { WatchAddModal } from "./WatchAddModal";

// ...
const view = usePositionsTabStore((s) => s.view);
const setView = usePositionsTabStore((s) => s.setView);
const tabs = useWatchlistStore((s) => s.tabs);
const removeTab = useWatchlistStore((s) => s.removeTab);
const renameTab = useWatchlistStore((s) => s.renameTab);
const createTab = useWatchlistStore((s) => s.createTab);
const addItem = useWatchlistStore((s) => s.addItem);
const removeItem = useWatchlistStore((s) => s.removeItem);

// Replace local useState<PanelView> with the store.
```

In the JSX, replace the old `{tabs}` variable with:

```tsx
<PositionsTabStrip
  view={view}
  stocksCount={stocks.length}
  optionsCount={options.length}
  tabs={tabs}
  onSelect={setView}
  onAdd={async (name) => {
    const t = await createTab(name);
    setView(t.id);
  }}
  onRemoveTab={async (id) => {
    await removeTab(id);
    if (view === id) setView("stocks");
  }}
  onRename={renameTab}
/>
```

- [ ] **Step 2: Add the watch-add modal state**

```tsx
const [addModalTabId, setAddModalTabId] = useState<string | null>(null);

// ...
{addModalTabId && (
  <WatchAddModal
    tabId={addModalTabId}
    onClose={() => setAddModalTabId(null)}
    onSubmit={async (draft) => {
      await addItem(addModalTabId, draft);
    }}
  />
)}
```

- [ ] **Step 3: Replace the body switch**

Replace the body `{view === "stocks" ? ... : ...}` block. Resolve `view` against `stocks` / `options` / `tabs`:

```tsx
const activeWatchTab =
  view !== "stocks" && view !== "options"
    ? tabs.find((t) => t.id === view) ?? null
    : null;

// ... in the body:
{view === "stocks" ? (
  /* existing stocks grid */
) : view === "options" ? (
  /* existing options grid */
) : activeWatchTab ? (
  <WatchlistGrid
    tab={activeWatchTab}
    quotesBySymbol={quotesBySymbol}
    candleByKey={candleByKey}
    onAdd={(id) => setAddModalTabId(id)}
    onRemoveItem={(id) => void removeItem(activeWatchTab.id, id)}
    onCardClick={(sym) => selectSymbol(sym)}
  />
) : (
  /* view points at a deleted tab; fall back */
  null
)}
```

Hide the portfolio summary on watch tabs:

```tsx
const summary =
  view === "stocks"
    ? stocks.length > 0 && <PortfolioSummary stocks={stocks} />
    : view === "options"
    ? options.length > 0 && <PortfolioSummary stocks={[]} options={options} />
    : null;
```

- [ ] **Step 4: Implement the active-tab quote subscription**

Replace the current `usePositionsData` effect that calls `watchQuotes(allSymbols)` with one keyed to the active view:

```tsx
const activeSymbols = useMemo<string[]>(() => {
  if (view === "stocks")  return stocks.map((p) => p.symbol);
  if (view === "options") return options.map((p) => p.symbol);
  return activeWatchTab ? activeWatchTab.items.map((i) => i.symbol) : [];
}, [view, stocks, options, activeWatchTab]);

useEffect(() => {
  let cancelled = false;
  void (async () => {
    try { await api.watchQuotes([]); } catch { /* swallow */ }
    if (cancelled) return;
    if (activeSymbols.length > 0) {
      try { await api.watchQuotes(activeSymbols); } catch (e) {
        console.warn("watchQuotes failed", e);
      }
    }
  })();
  return () => {
    cancelled = true;
    void api.watchQuotes([]).catch(() => undefined);
  };
}, [view, activeSymbols.join(",")]);
```

Keep the one-shot `api.quotes`, `api.candlesticks`, `api.todayExecutions` fetches in `usePositionsData` (they're cheap and pre-warm the caches). Also extend them to include watch-tab item symbols, lazy-fetched on first appearance.

- [ ] **Step 5: Update DetailPane lookup to handle watch items**

Replace the existing `selectedSymbol` lookup (`PositionsPanel.tsx:213-225`) with:

```tsx
if (selectedSymbol) {
  let resolved: Position | undefined =
    stocks.find((p) => p.symbol === selectedSymbol) ??
    options.find((p) => p.symbol === selectedSymbol);
  let watchOnly = false;
  if (!resolved && activeWatchTab) {
    const w = activeWatchTab.items.find((i) => i.symbol === selectedSymbol);
    if (w) {
      resolved = watchItemToPosition(w);
      watchOnly = true;
    }
  }
  if (resolved) {
    return (
      <aside className="positions-panel">
        <SparkDefs />
        <DetailPane position={resolved} watchOnly={watchOnly} onBack={() => selectSymbol(null)} />
      </aside>
    );
  }
}
```

Where `watchItemToPosition` is imported from `WatchlistGrid.tsx` (or extracted to a small shared helper).

- [ ] **Step 6: Build**

Run: `cd frontend && npm run build`
Expected: clean.

- [ ] **Step 7: Run vitest sweep**

Run: `cd frontend && npx vitest run`
Expected: all existing tests still pass. Some `PositionsPanel.test.tsx` cases referring to the old `useState`-based view will likely break — that's expected, those tests are updated in Task 22.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Positions/PositionsPanel.tsx
git commit -m "feat(watchlist): PositionsPanel routes watch tabs + active-only subscription"
```

---

### Task 22: `PositionsPanel.test.tsx` — assert subscription lifecycle

**Files:**
- Modify: `frontend/src/components/Positions/PositionsPanel.test.tsx`

- [ ] **Step 1: Adapt existing tests**

Update any test that asserts on `useState`-based view to use `usePositionsTabStore.setState({ view })` instead.

- [ ] **Step 2: Add subscription-lifecycle tests**

```tsx
import { api } from "../../api/http";
import { useWatchlistStore } from "../../stores/watchlist";
import { usePositionsTabStore } from "../../stores/positionsTab";

it("on switch to a watch tab: watchQuotes called with [] then the tab's symbols", async () => {
  const calls: string[][] = [];
  vi.spyOn(api, "watchQuotes").mockImplementation(async (syms: string[]) => {
    calls.push(syms);
    return { added: 0, removed: 0, total: syms.length };
  });

  useWatchlistStore.setState({
    loaded: true,
    tabs: [{
      id: "t1", name: "w", sort_order: 0,
      items: [
        { id: "i1", tab_id: "t1", symbol: "AAPL.US", kind: "stock",
          ticker: "AAPL", sort_order: 0,
          option_type: null, option_strike: null, option_expiry: null } as any,
      ],
    }],
  });
  usePositionsTabStore.setState({ view: "stocks" });

  // mount PositionsPanel (using your existing test wrapper)
  render(<PositionsPanel />);
  await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));

  // Switch to the watch tab
  usePositionsTabStore.getState().setView("t1");
  await waitFor(() => {
    const last = calls.at(-1) ?? [];
    expect(last).toEqual(["AAPL.US"]);
  });
  // Penultimate must be [] (the tear-down)
  const penultimate = calls.at(-2) ?? [];
  expect(penultimate).toEqual([]);
});

it("removing the active watch tab falls back to stocks view", async () => {
  vi.spyOn(api, "watchlistDeleteTab").mockResolvedValue({ ok: true });
  useWatchlistStore.setState({
    loaded: true,
    tabs: [{ id: "t1", name: "w", sort_order: 0, items: [] }],
  });
  usePositionsTabStore.setState({ view: "t1" });

  render(<PositionsPanel />);
  fireEvent.click(screen.getByLabelText("删除 tab"));
  await waitFor(() =>
    expect(usePositionsTabStore.getState().view).toBe("stocks")
  );
});
```

Run: `cd frontend && npx vitest run src/components/Positions/PositionsPanel.test.tsx`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Positions/PositionsPanel.test.tsx
git commit -m "test(watchlist): subscription lifecycle + active-tab fallback"
```

---

### Task 23: `App.tsx` — bootstrap + broker-reload hook

**Files:**
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Hook in load() on dashboard mount + reset/load on broker reload**

Locate the existing `onReloadBroker={async () => {...}}` block (around `App.tsx:526`). Modify:

```tsx
onReloadBroker={async () => {
  try {
    const status = await api.reloadBroker();
    useConnStore.getState().setBrokerStatus({
      is_real: status.is_real,
      last_init_error: status.last_init_error ?? null,
    });
    // Reset + reload watchlist (per-account isolation)
    useWatchlistStore.getState().reset();
    void useWatchlistStore.getState().load();
  } catch (e) {
    console.warn("broker reload failed:", e);
  }
}}
```

And add a bootstrap `useEffect` near where other one-shot effects live in `App.tsx`:

```tsx
useEffect(() => {
  void useWatchlistStore.getState().load();
}, []);
```

Make sure to add the import:

```tsx
import { useWatchlistStore } from "./stores/watchlist";
```

- [ ] **Step 2: Smoke test manually**

Build + run dev server, switch accounts in the LongPort settings modal, watch the network tab — `/api/watchlist` should fire on reload.

```bash
cd frontend && npm run build
cd ../backend && uv run uvicorn app.main:app --reload
# (separately) cd frontend && npm run dev
```

Confirm: account switch triggers a fresh `GET /api/watchlist`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(watchlist): bootstrap + reset/load on account switch"
```

---

### Task 24: End-to-end manual verification

**Files:** none

- [ ] **Step 1: Run the full dev stack**

```bash
cd /Users/tianpengxuan/Documents/signal-station/.claude/worktrees/<this worktree>
make dev
```

- [ ] **Step 2: Walk the spec checklist in the browser**

Confirm each of these works:

- Open the dashboard. Right zone shows 正股 + 期权 + `+` button.
- Click `+`. Inline input appears. Type "半导体" + Enter. New tab appears, view switches to it.
- The empty tab shows a single dashed AddCardPlaceholder.
- Click the placeholder. WatchAddModal opens in 股票 mode.
- Type "AAPL", market US, Submit. Modal closes, a real AAPL card appears, placeholder remains at the end.
- Hover the AAPL card. Red × appears in top-right. Click × — card disappears.
- Click placeholder again, switch to 期权 mode, fill AAPL / 2025-06-20 / 170 / Call, Submit. Option card appears.
- Click the option card — drills into DetailPane. Confirm 做T section is gone and chart + trade list still render.
- Click ← back. Hover the new tab in the tab strip. Red × appears. Click it. Tab disappears, view falls back to 正股, the 正股 cards start ticking again.
- Switch to 期权 tab. Switch back to 正股. Quotes resume.
- Open LongPort settings, switch accounts. `/api/watchlist` re-fires; the watch tabs you created vanish (per-account isolation). Switch back: they reappear.

- [ ] **Step 3: Commit nothing (manual check)**

If everything passes, you're done. Document any defects as separate issues.

---

## Final Self-Review (run after all tasks are complete)

- [ ] **Spec coverage scan**: every section of `docs/superpowers/specs/2026-05-23-watchlist-tabs-design.md` maps to at least one task above. The "Out of scope" items intentionally have no tasks.
- [ ] **Test suite green**: `cd backend && uv run pytest` + `cd frontend && npx vitest run` + `cd frontend && npm run build` all pass.
- [ ] **No lint regressions**: `cd frontend && npm run lint` (if a lint script exists) reports no new warnings.
- [ ] **Backend `/api/watchlist` reachable**: hit it manually with `curl -H "..." localhost:8000/api/watchlist`.
- [ ] **Spec self-check items**:
  - Active tab subscription is exclusive (no leakage into other tabs).
  - 正股 / 期权 tabs cannot be removed (× not rendered for them).
  - Empty card is permanent at the end of the watch grid.
  - Per-account isolation works after a broker switch.
