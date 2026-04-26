# Lot-Reference Quantity Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the trader to compute stock order quantity from a referenced prior lot (e.g. "12.87 减一半 12.42 的 tsll") by looking up the reverse-side task in DB and multiplying its `tasks.quantity` by the parsed fraction. Falls back to current default-position behavior when any precondition is missing or no match is found.

**Architecture:** Adds a `referenced_lot_price: float | None` field to `Instruction`; introduces `sell_quantity_to_fraction` helper; adds an async `find_recent_task_by_ref` repo function plus a `TaskQueryRepo` Protocol bound to a sessionmaker; refactors trader's stock branch into `_qty_for_whitelisted_stock(...)` async helper that tries the lot path first then falls through to the existing `trade_quantity × position_size_to_fraction` path. Trader stays event-driven and gets the repo via dependency injection.

**Tech Stack:** Python 3.11, asyncio, SQLAlchemy 2.x async, Pydantic v2, pytest-asyncio. Source: `backend/app/`. Tests: `backend/tests/`. Test runner: `.venv/bin/python -m pytest` from `backend/`.

**Reference spec:** `docs/superpowers/specs/2026-04-26-lot-reference-qty-lookup-design.md`

---

## File map

**Modify:**
- `backend/app/domain/instruction.py` — add `referenced_lot_price` field
- `backend/app/storage/repo.py` — extend instruction JSON serdes; add `find_recent_task_by_ref` + `TaskQueryRepo` Protocol + `SqlTaskQueryRepo` class
- `backend/app/api/schemas.py` — add `referenced_lot_price` field on `InstructionOut`; update `instruction_to_out`
- `backend/app/whop/page_settings.py` — add `_SELL_FRACTION_MAP` + `sell_quantity_to_fraction`
- `backend/app/broker/trader.py` — extract `_qty_for_whitelisted_stock` async helper; add `task_query_repo` parameter to `register_trader`
- `backend/app/main.py` — construct `SqlTaskQueryRepo(session_factory)` and pass to `register_trader`
- `backend/tests/broker/_fakes.py` — add `FakeTaskQueryRepo`
- `backend/tests/storage/test_repo.py` — extend stock round-trip test to assert `referenced_lot_price` survives
- `backend/tests/whop/test_page_settings.py` — table-driven tests for `sell_quantity_to_fraction`

**Create:**
- `backend/tests/storage/test_task_query_repo.py` — SQL behavior tests (side filter, window, price tolerance, status filter, ordering)
- `backend/tests/broker/test_trader_lot_lookup.py` — end-to-end trader integration tests

---

## Pre-flight

Before starting, run the full backend test suite once to capture a known-green baseline. Working directory: `backend/`.

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: all green. If any tests are already red, stop and surface them — they are unrelated to this plan and should be fixed first or noted as pre-existing.

---

## Task 1: Add `referenced_lot_price` field to Instruction (domain + serdes + Pydantic)

**Files:**
- Modify: `backend/app/domain/instruction.py`
- Modify: `backend/app/storage/repo.py:49-124` (instruction JSON ser/de)
- Modify: `backend/app/api/schemas.py:45-66` (`InstructionOut`) and `:343-400` (`instruction_to_out`)
- Test: `backend/tests/storage/test_repo.py` (extend existing stock round-trip)

- [ ] **Step 1: Write the failing test**

Append to the stock round-trip test (`test_save_and_load_task_with_stock_instruction_roundtrip`) in `backend/tests/storage/test_repo.py`. Find the `_stock_inst()` helper (~line 60) and modify it to set `referenced_lot_price=12.42`; then add an assertion in the round-trip test on the loaded instruction.

In `_stock_inst()`:

```python
def _stock_inst() -> StockInstruction:
    return StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.50,
        price_range=None,
        quantity=500,
        position_size="小仓位",
        stop_loss_price=25.80,
        take_profit_price=None,
        context_source="group",
        parser_notes=["note1"],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
        referenced_lot_price=12.42,  # ← add this kwarg
    )
```

In the round-trip test (find the block of assertions on `li`):

```python
    assert li.sell_quantity is None
    assert li.referenced_lot_price == pytest.approx(12.42)  # ← add this line
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/storage/test_repo.py::test_save_and_load_task_with_stock_instruction_roundtrip -v
```

Expected: FAIL — `StockInstruction.__init__() got an unexpected keyword argument 'referenced_lot_price'`.

- [ ] **Step 3: Add the field to the dataclass**

Edit `backend/app/domain/instruction.py`. Add the field at the end of `Instruction`'s field list (BEFORE `parser_notes` so default-having fields stay grouped, but since `parser_notes` already has a default, putting it after is also valid; place it right before `parser_notes` to keep base-class defaults contiguous):

```python
@dataclass
class Instruction:
    instruction_type: InstructionType
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: ContextSource | None
    parser_notes: list[str] = field(default_factory=list)
    referenced_lot_price: float | None = None
```

- [ ] **Step 4: Extend JSON serializer/deserializer**

Edit `backend/app/storage/repo.py`. In `_instruction_to_json` (~line 49), add to the common `payload` dict:

```python
    payload: dict[str, Any] = {
        "instruction_type": inst.instruction_type.value,
        "price": inst.price,
        "price_range": list(inst.price_range) if inst.price_range is not None else None,
        "quantity": inst.quantity,
        "position_size": inst.position_size,
        "stop_loss_price": inst.stop_loss_price,
        "take_profit_price": inst.take_profit_price,
        "context_source": inst.context_source,
        "parser_notes": list(inst.parser_notes),
        "referenced_lot_price": inst.referenced_lot_price,  # ← new
    }
```

In `_instruction_from_json` (~line 82), add to the `common` dict:

```python
    common: dict[str, Any] = {
        "instruction_type": instruction_type,
        "price": data.get("price"),
        "price_range": price_range,
        "quantity": data.get("quantity"),
        "position_size": data.get("position_size"),
        "stop_loss_price": data.get("stop_loss_price"),
        "take_profit_price": data.get("take_profit_price"),
        "context_source": data.get("context_source"),
        "parser_notes": data.get("parser_notes", []),
        "referenced_lot_price": data.get("referenced_lot_price"),  # ← new
    }
```

- [ ] **Step 5: Add the field to the Pydantic API model + converter**

Edit `backend/app/api/schemas.py`. In `InstructionOut` (~line 45):

```python
class InstructionOut(BaseModel):
    type: str = Field(..., description="stock | option")
    instruction_type: str
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: str | None
    parser_notes: list[str]
    referenced_lot_price: float | None = None  # ← new
    # Stock-only
    ticker: str | None = None
    symbol: str | None = None
    sell_quantity: str | None = None
    # Option-only
    option_type: str | None = None
    strike: float | None = None
    expiry: date | None = None
```

In `instruction_to_out` (~line 343), add `referenced_lot_price=inst.referenced_lot_price,` to **all three** branches (option, stock, base fallback). Example for the stock branch:

```python
    elif isinstance(inst, StockInstruction):
        return InstructionOut(
            type="stock",
            instruction_type=str(inst.instruction_type),
            price=inst.price,
            price_range=inst.price_range,
            quantity=inst.quantity,
            position_size=inst.position_size,
            stop_loss_price=inst.stop_loss_price,
            take_profit_price=inst.take_profit_price,
            context_source=inst.context_source,
            parser_notes=list(inst.parser_notes),
            referenced_lot_price=inst.referenced_lot_price,  # ← new
            ticker=inst.ticker,
            symbol=inst.symbol,
            sell_quantity=inst.sell_quantity,
            option_type=None,
            strike=None,
            expiry=None,
        )
```

Same one-line addition for the option branch and the base-fallback branch.

- [ ] **Step 6: Run the test to confirm it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/storage/test_repo.py -v
```

Expected: all storage repo tests PASS.

Run the broader test suite to make sure nothing else broke (Pydantic schemas are loaded by API tests):

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: still all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/domain/instruction.py backend/app/storage/repo.py backend/app/api/schemas.py backend/tests/storage/test_repo.py
git commit -m "$(cat <<'EOF'
feat(domain): add Instruction.referenced_lot_price (default None)

Field plumbed through dataclass, JSON serdes (storage/repo.py), and
Pydantic InstructionOut. Default None means existing payloads round-trip
unchanged. No consumer yet — trader integration lands in a later commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `sell_quantity_to_fraction` helper in `page_settings.py`

**Files:**
- Modify: `backend/app/whop/page_settings.py:140-180`
- Test: `backend/tests/whop/test_page_settings.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/whop/test_page_settings.py`. First, add `sell_quantity_to_fraction` to the import block at the top:

```python
from app.whop.page_settings import (
    DEFAULT_OPTION_SETTINGS,
    DEFAULT_STOCK_SETTINGS,
    PageSettings,
    TickerConfig,
    page_settings_from_dict,
    page_settings_to_dict,
    position_size_to_fraction,
    sell_quantity_to_fraction,  # ← new
)
```

Then add at the end of the file:

```python
def test_sell_quantity_to_fraction_known():
    assert sell_quantity_to_fraction(None) == 1.0
    assert sell_quantity_to_fraction("") == 1.0
    assert sell_quantity_to_fraction("1/2") == 0.5
    assert sell_quantity_to_fraction("1/3") == pytest.approx(1 / 3)
    assert sell_quantity_to_fraction("1/4") == 0.25
    assert sell_quantity_to_fraction("2/3") == pytest.approx(2 / 3)
    assert sell_quantity_to_fraction("3/4") == 0.75
    assert sell_quantity_to_fraction("全部") == 1.0
    assert sell_quantity_to_fraction("剩下") == 1.0
    assert sell_quantity_to_fraction("剩下一半") == 0.5  # decision 5: same as 1/2


def test_sell_quantity_to_fraction_strips_whitespace():
    assert sell_quantity_to_fraction("  1/2  ") == 0.5
    assert sell_quantity_to_fraction("\t全部\n") == 1.0


def test_sell_quantity_to_fraction_unknown_returns_one(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        assert sell_quantity_to_fraction("一点点") == 1.0
    assert any("unrecognized sell_quantity" in r.getMessage() for r in caplog.records)
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/whop/test_page_settings.py::test_sell_quantity_to_fraction_known -v
```

Expected: FAIL — `ImportError: cannot import name 'sell_quantity_to_fraction'`.

- [ ] **Step 3: Implement the helper**

Edit `backend/app/whop/page_settings.py`. After the existing `position_size_to_fraction` block (~line 180), add:

```python
_SELL_FRACTION_MAP: dict[str, float] = {
    "1/2": 0.5,
    "1/3": 1 / 3,
    "1/4": 0.25,
    "2/3": 2 / 3,
    "3/4": 0.75,
    "全部": 1.0,
    "剩下": 1.0,
    "剩下一半": 0.5,
}


def sell_quantity_to_fraction(s: str | None) -> float:
    """把 stock_parser 解出来的 sell_quantity 字符串 → 数量倍数。

    未识别 / None / 空 → 1.0（按引用 lot 全量计算）。
    未识别时记 warning。决策见 design 第 5 节：'剩下一半' 等同 1/2，不做
    lot 累计消耗追踪。
    """
    if not s:
        return 1.0
    s2 = s.strip()
    if s2 in _SELL_FRACTION_MAP:
        return _SELL_FRACTION_MAP[s2]
    logger.warning("unrecognized sell_quantity %r — falling back to 1.0", s2)
    return 1.0
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/whop/test_page_settings.py -v
```

Expected: all `test_sell_quantity_to_fraction_*` tests PASS along with existing ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/page_settings.py backend/tests/whop/test_page_settings.py
git commit -m "$(cat <<'EOF'
feat(page_settings): add sell_quantity_to_fraction helper

Maps parser-emitted sell_quantity strings (1/2, 1/3, 全部, 剩下一半, …)
to a multiplier. Unknown / None → 1.0 with warning. Decision: '剩下一半'
treated as 0.5 (no lot-consumption tracking; see design §4 decision 5).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `find_recent_task_by_ref` SQL function in `storage/repo.py`

**Files:**
- Modify: `backend/app/storage/repo.py` (add module-level async function near `load_task_by_order_id`)
- Test: `backend/tests/storage/test_task_query_repo.py` (CREATE)

- [ ] **Step 1: Write the failing test (file)**

Create `backend/tests/storage/test_task_query_repo.py`:

```python
"""Tests for find_recent_task_by_ref — the lot-lookup query.

Covers:
- Side filter (SELL doesn't match SELL when looking for BUY)
- Time window (within / outside `window_hours`)
- Exact price (±0.0001 tolerance, nothing wider)
- order_id IS NOT NULL (PARSE_ERROR / SUBMIT_FAILED don't count)
- ORDER BY created_at DESC LIMIT 1 (newest wins on ties)
- before is strict `<` (the task itself never matches itself)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.storage.repo import find_recent_task_by_ref, save_task


def _msg(id_: str, when: datetime) -> Message:
    return Message(
        id=id_,
        content="test",
        raw_content="test",
        author="t",
        posted_at=when,
        received_at=when,
        source="stock",
    )


def _stock_task(
    *,
    id_: str,
    when: datetime,
    side: InstructionType,
    price: float,
    quantity: int,
    order_id: str | None,
) -> Task:
    inst = StockInstruction(
        instruction_type=side,
        price=price,
        price_range=None,
        quantity=quantity,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    task = Task(
        id=id_,
        type="stock",
        status=Status.SUBMITTED if order_id else Status.PARSE_ERROR,
        order_id=order_id,
        message=_msg(id_, when),
        instruction=inst if order_id else None,
        created_at=when,
        updated_at=when,
    )
    return task


async def test_finds_recent_buy_for_sell_reference(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    buy = _stock_task(
        id_="t-buy", when=base, side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-1",
    )
    async with session_factory() as session:
        await save_task(session, buy)

    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session,
            ticker="TSLL",
            side=InstructionType.BUY,
            price=12.42,
            before=base + timedelta(hours=1),
            window_hours=24 * 7,
        )
    assert qty == 4000


async def test_side_filter_excludes_same_side(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    sell = _stock_task(
        id_="t-sell", when=base, side=InstructionType.SELL,
        price=12.42, quantity=2000, order_id="ORD-1",
    )
    async with session_factory() as session:
        await save_task(session, sell)

    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session,
            ticker="TSLL",
            side=InstructionType.BUY,  # looking for BUY only
            price=12.42,
            before=base + timedelta(hours=1),
            window_hours=24 * 7,
        )
    assert qty is None


async def test_window_excludes_old_match(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime(2026, 4, 30, 10, 0, 0, tzinfo=UTC)
    old_buy = _stock_task(
        id_="t-old",
        when=now - timedelta(days=8),  # 8 days ago, outside 7-day window
        side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-old",
    )
    async with session_factory() as session:
        await save_task(session, old_buy)

    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session,
            ticker="TSLL",
            side=InstructionType.BUY,
            price=12.42,
            before=now,
            window_hours=24 * 7,
        )
    assert qty is None


async def test_exact_price_tolerance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    buy = _stock_task(
        id_="t-buy", when=base, side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-1",
    )
    async with session_factory() as session:
        await save_task(session, buy)

    async with session_factory() as session:
        # Within ±0.0001 — match
        qty_match = await find_recent_task_by_ref(
            session, ticker="TSLL", side=InstructionType.BUY,
            price=12.42005, before=base + timedelta(hours=1), window_hours=24 * 7,
        )
        # Outside ±0.0001 — no match (12.4 is 0.02 away)
        qty_no_match = await find_recent_task_by_ref(
            session, ticker="TSLL", side=InstructionType.BUY,
            price=12.4, before=base + timedelta(hours=1), window_hours=24 * 7,
        )
    assert qty_match == 4000
    assert qty_no_match is None


async def test_excludes_tasks_without_order_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    parse_err = _stock_task(
        id_="t-err", when=base, side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id=None,  # no order_id
    )
    async with session_factory() as session:
        await save_task(session, parse_err)

    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session, ticker="TSLL", side=InstructionType.BUY,
            price=12.42, before=base + timedelta(hours=1), window_hours=24 * 7,
        )
    assert qty is None


async def test_picks_most_recent_on_tie(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    older = _stock_task(
        id_="t-old", when=base, side=InstructionType.BUY,
        price=12.42, quantity=2000, order_id="ORD-old",
    )
    newer = _stock_task(
        id_="t-new", when=base + timedelta(hours=2), side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-new",
    )
    async with session_factory() as session:
        await save_task(session, older)
        await save_task(session, newer)

    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session, ticker="TSLL", side=InstructionType.BUY,
            price=12.42, before=base + timedelta(hours=3), window_hours=24 * 7,
        )
    assert qty == 4000  # newer wins


async def test_before_is_strict_less_than(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A task should not match itself when before == its created_at."""
    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    buy = _stock_task(
        id_="t-buy", when=base, side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-1",
    )
    async with session_factory() as session:
        await save_task(session, buy)

    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session, ticker="TSLL", side=InstructionType.BUY,
            price=12.42, before=base, window_hours=24 * 7,
        )
    assert qty is None
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/storage/test_task_query_repo.py -v
```

Expected: FAIL on import — `cannot import name 'find_recent_task_by_ref'`.

- [ ] **Step 3: Implement `find_recent_task_by_ref`**

Edit `backend/app/storage/repo.py`. Find the existing `load_task_by_order_id` (~line 439) and add the new function right after it:

```python
async def find_recent_task_by_ref(
    session: AsyncSession,
    *,
    ticker: str,
    side: InstructionType,
    price: float,
    before: datetime,
    window_hours: int = 24 * 7,
) -> int | None:
    """Find the most recent submitted task whose ticker/side/price match.

    Used by the trader to resolve "lot @<price>" references in messages like
    "12.87 减一半 12.42 的 tsll" — looks up the prior reverse-side task and
    returns its planned quantity.

    Filters:
    - ticker exact match
    - side exact match (caller passes the *opposite* of current instruction)
    - ABS(price - :price) < 0.0001 (decision 7: strict exact)
    - order_id IS NOT NULL (decision 4: only tasks that submitted to broker)
    - created_at in (before - window_hours, before) — strict open interval

    Returns the matched task's `quantity`, or None if no row matches.
    """
    from sqlalchemy import select, func

    cutoff = before - timedelta(hours=window_hours)
    stmt = (
        select(TaskRow.quantity)
        .where(
            TaskRow.ticker == ticker,
            TaskRow.side == side.value,
            func.abs(TaskRow.price - price) < 0.0001,
            TaskRow.order_id.is_not(None),
            TaskRow.created_at < before,
            TaskRow.created_at >= cutoff,
        )
        .order_by(TaskRow.created_at.desc())
        .limit(1)
    )
    row = await session.execute(stmt)
    return row.scalar_one_or_none()
```

At the top of `backend/app/storage/repo.py`, the existing line is:

```python
from datetime import UTC, date, datetime, time
```

Add `timedelta` to it:

```python
from datetime import UTC, date, datetime, time, timedelta
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/storage/test_task_query_repo.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_task_query_repo.py
git commit -m "$(cat <<'EOF'
feat(storage): add find_recent_task_by_ref for lot lookup

Async repo function that finds the most recent submitted task matching
ticker + side + price (±0.0001) within the given time window, returning
its planned quantity. Used by the trader to resolve 'lot @<price>'
references in stock messages. Tests cover side filter, window edges,
price tolerance, order_id filter, ordering, and self-exclusion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `TaskQueryRepo` Protocol + `SqlTaskQueryRepo` adapter

**Files:**
- Modify: `backend/app/storage/repo.py` (add Protocol + class at the end)
- Test: `backend/tests/storage/test_task_query_repo.py` (extend with adapter test)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/storage/test_task_query_repo.py`:

```python
async def test_sql_task_query_repo_binds_session_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SqlTaskQueryRepo opens its own session per call from the factory."""
    from app.storage.repo import SqlTaskQueryRepo

    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    buy = _stock_task(
        id_="t-buy", when=base, side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-1",
    )
    async with session_factory() as session:
        await save_task(session, buy)

    repo = SqlTaskQueryRepo(session_factory)
    qty = await repo.find_recent_task_by_ref(
        ticker="TSLL",
        side=InstructionType.BUY,
        price=12.42,
        before=base + timedelta(hours=1),
        window_hours=24 * 7,
    )
    assert qty == 4000
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd backend && .venv/bin/python -m pytest tests/storage/test_task_query_repo.py::test_sql_task_query_repo_binds_session_factory -v
```

Expected: FAIL — `cannot import name 'SqlTaskQueryRepo'`.

- [ ] **Step 3: Implement Protocol + class**

Edit `backend/app/storage/repo.py`. The existing imports are:

```python
from typing import Any
...
from sqlalchemy.ext.asyncio import AsyncSession
```

Update them to:

```python
from typing import Any, Protocol
...
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
```

At the end of the file, add:

```python
# ---------------------------------------------------------------------------
# TaskQueryRepo — injection seam for the trader's lot lookup.
# ---------------------------------------------------------------------------


class TaskQueryRepo(Protocol):
    """Read-only task lookups for components outside the storage layer.

    Decoupled from AsyncSession so the trader (which doesn't own a session)
    can depend on this interface and tests can substitute a fake.
    """

    async def find_recent_task_by_ref(
        self,
        *,
        ticker: str,
        side: InstructionType,
        price: float,
        before: datetime,
        window_hours: int = 24 * 7,
    ) -> int | None: ...


class SqlTaskQueryRepo:
    """Production implementation: opens a session from the factory per call."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def find_recent_task_by_ref(
        self,
        *,
        ticker: str,
        side: InstructionType,
        price: float,
        before: datetime,
        window_hours: int = 24 * 7,
    ) -> int | None:
        async with self._factory() as session:
            return await find_recent_task_by_ref(
                session,
                ticker=ticker,
                side=side,
                price=price,
                before=before,
                window_hours=window_hours,
            )
```


- [ ] **Step 4: Run the test to confirm it passes**

```bash
cd backend && .venv/bin/python -m pytest tests/storage/test_task_query_repo.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_task_query_repo.py
git commit -m "$(cat <<'EOF'
feat(storage): add TaskQueryRepo Protocol + SqlTaskQueryRepo adapter

TaskQueryRepo is the injection seam used by trader to perform lot
lookups without owning an AsyncSession. SqlTaskQueryRepo wraps a
sessionmaker; tests use a fake.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `FakeTaskQueryRepo` test fake

**Files:**
- Modify: `backend/tests/broker/_fakes.py`

This task has no dedicated test — the fake is exercised by Task 6. We commit it standalone so Task 6's diff stays focused on trader changes.

- [ ] **Step 1: Add the fake**

Edit `backend/tests/broker/_fakes.py`. Add at the end:

```python
@dataclass
class FakeTaskQueryRepo:
    """Test fake for TaskQueryRepo. Stores qty by (ticker, side_value, price)."""

    matches: dict[tuple[str, str, float], int] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def find_recent_task_by_ref(
        self,
        *,
        ticker: str,
        side: Any,  # InstructionType — kept Any to avoid circular imports here
        price: float,
        before: Any,
        window_hours: int = 24 * 7,
    ) -> int | None:
        self.calls.append({
            "ticker": ticker, "side": side, "price": price,
            "before": before, "window_hours": window_hours,
        })
        side_value = side.value if hasattr(side, "value") else side
        return self.matches.get((ticker, side_value, price))
```

- [ ] **Step 2: Sanity-check the existing tests still pass**

```bash
cd backend && .venv/bin/python -m pytest tests/broker/ -v
```

Expected: all PASS (no test consumes the fake yet, but the file still imports cleanly).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/broker/_fakes.py
git commit -m "$(cat <<'EOF'
test(broker): add FakeTaskQueryRepo for trader lot-lookup tests

Stores preset qty by (ticker, side_value, price) tuple. Records calls
for assertions. Used by upcoming trader integration tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Trader's `_qty_for_whitelisted_stock` async helper + lot path

**Files:**
- Modify: `backend/app/broker/trader.py:51` (`register_trader` signature) and `:184-196` (stock branch)
- Test: `backend/tests/broker/test_trader_lot_lookup.py` (CREATE)

- [ ] **Step 1: Write the failing tests (file)**

Create `backend/tests/broker/test_trader_lot_lookup.py`:

```python
"""End-to-end trader tests for the lot-reference qty path.

Driven through the event bus with FakeBrokerClient + FakeTaskQueryRepo.
Asserts on the qty submitted to the broker via fake.submitted_orders.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.broker.config import LongPortConfig
from app.broker.trader import register_trader
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.task import Task
from app.whop.page_settings import PageSettings, TickerConfig
from tests.broker._fakes import FakeBrokerClient, FakeTaskQueryRepo


def _msg() -> Message:
    return Message(
        id="msg-test-001",
        content="test",
        raw_content="test",
        author="t",
        posted_at=datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 4, 24, 10, 0, 0, 1000, tzinfo=UTC),
        source="stock",
    )


def _stock_task(
    *,
    side: InstructionType,
    price: float,
    referenced_lot_price: float | None = None,
    sell_quantity: str | None = None,
) -> Task:
    task = Task.new_from_message(_msg())
    task.mark_parsing()
    inst = StockInstruction(
        instruction_type=side,
        price=price,
        price_range=None,
        quantity=2000,  # parser/page default; will be overwritten by trader
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=sell_quantity,
        referenced_lot_price=referenced_lot_price,
    )
    task.attach_instruction(inst)
    return task


def _config() -> LongPortConfig:
    return LongPortConfig(
        mode="paper", app_key="k", app_secret="s", access_token="t",
        auto_trade=True, dry_run=False,
        max_option_total_price=500.0, max_option_quantity=3,
    )


def _registry_with_default(default_qty: int = 2000):
    """A WhopRegistry-like stub returning page settings with one whitelisted ticker."""
    page = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        block_non_today_messages=False,
        launch_headless=False,
        tickers={"TSLL": TickerConfig(trade_quantity=default_qty)},
    )

    class _Registry:
        def get_settings_for_url(self, url):
            return page

    return _Registry()


@pytest.mark.asyncio
async def test_lot_path_sell_half_uses_prior_buy_qty() -> None:
    """SELL with ref to BUY @12.42 (qty 4000), sell_quantity '1/2' → 2000."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),  # default would mismatch
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(fake.submitted_orders) == 1
    assert fake.submitted_orders[0]["quantity"] == 2000


@pytest.mark.asyncio
async def test_lot_path_buy_full_uses_prior_sell_qty() -> None:
    """BUY referencing prior SELL @12.87 (qty 2000), sell_quantity '全部' → 2000."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "SELL", 12.87): 2000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.BUY, price=12.32,
        referenced_lot_price=12.87, sell_quantity="全部",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 2000


@pytest.mark.asyncio
async def test_lot_miss_falls_back_to_default_position() -> None:
    """No matching prior lot → falls back to page default × position_size_to_fraction."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={})  # empty
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=300),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=87.4,
        referenced_lot_price=85.65, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    # Falls back: default trade_quantity 300 × position_size_to_fraction(None)=1.0 → 300
    assert fake.submitted_orders[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_no_repo_injected_falls_back_silently() -> None:
    """task_query_repo=None → instruction's lot ref is ignored, fallback used."""
    bus = EventBus()
    fake = FakeBrokerClient()
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=300),
        task_query_repo=None,  # explicitly absent
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_missing_sell_quantity_falls_back() -> None:
    """ref_price set but sell_quantity=None → fallback (incomplete reference)."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=300),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity=None,  # missing
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_unknown_sell_quantity_uses_one_with_warning() -> None:
    """sell_quantity '一点点' is unknown → fraction 1.0 (full lot) + warning."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 2000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="一点点",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 2000  # 2000 × 1.0


@pytest.mark.asyncio
async def test_remainder_half_treated_as_one_half() -> None:
    """sell_quantity '剩下一半' → 0.5 (decision 5: no lot consumption tracking)."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 11.73): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(default_qty=999),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.37,
        referenced_lot_price=11.73, sell_quantity="剩下一半",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert fake.submitted_orders[0]["quantity"] == 2000  # 4000 × 0.5


@pytest.mark.asyncio
async def test_repo_called_with_opposite_side() -> None:
    """SELL with ref → repo asked for opposite side BUY."""
    bus = EventBus()
    fake = FakeBrokerClient()
    repo = FakeTaskQueryRepo(matches={("TSLL", "BUY", 12.42): 4000})
    register_trader(
        bus, fake, _config(),
        registry=_registry_with_default(),
        task_query_repo=repo,
    )

    task = _stock_task(
        side=InstructionType.SELL, price=12.87,
        referenced_lot_price=12.42, sell_quantity="1/2",
    )
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(repo.calls) == 1
    assert repo.calls[0]["side"] == InstructionType.BUY
    assert repo.calls[0]["price"] == 12.42
    assert repo.calls[0]["window_hours"] == 24 * 7
```

- [ ] **Step 2: Run the tests to confirm they fail**

```bash
cd backend && .venv/bin/python -m pytest tests/broker/test_trader_lot_lookup.py -v
```

Expected: FAIL — `register_trader() got an unexpected keyword argument 'task_query_repo'`.

- [ ] **Step 3: Add `task_query_repo` parameter and helper imports**

Edit `backend/app/broker/trader.py`. At the top imports, add:

```python
from app.storage.repo import TaskQueryRepo
from app.whop.page_settings import position_size_to_fraction, sell_quantity_to_fraction
```

(Replace the existing `from app.whop.page_settings import position_size_to_fraction` line with the combined import.)

Update `register_trader` signature (~line 51) to include the new optional parameter:

```python
def register_trader(
    bus: EventBus,
    client: BrokerClient,
    config: LongPortConfig,
    *,
    registry: Any | None = None,
    auto_trade_getter: Callable[[], bool] | None = None,
    task_query_repo: TaskQueryRepo | None = None,
) -> Callable[[], None]:
```

Update the docstring's "Parameters" section to mention `task_query_repo` (one sentence, e.g. "Optional `TaskQueryRepo`. When provided, instructions carrying both `referenced_lot_price` and `sell_quantity` resolve qty via the prior reverse-side task. None disables the path entirely.").

- [ ] **Step 4: Replace the stock qty branch with the helper call**

In the same file, replace lines ~184-196 (the existing `if isinstance(inst, StockInstruction):` block in `_handle_instruction_ready`) with:

```python
        if isinstance(inst, StockInstruction):
            ticker_upper = (inst.ticker or "").upper()
            if page_settings is not None and page_settings.tickers is not None:
                computed_qty = await _qty_for_whitelisted_stock(
                    inst,
                    ticker_upper,
                    page_settings,
                    task_query_repo=task_query_repo,
                    now=task.created_at,
                )
            else:
                computed_qty = inst.quantity or 0
                if computed_qty <= 0:
                    await _publish_skip(task, "orphan stock task missing instruction.quantity")
                    return
```

- [ ] **Step 5: Add the helper at module level**

Still in `backend/app/broker/trader.py`. Add at the top (near `_format_broker_error`, before `register_trader`):

```python
async def _qty_for_whitelisted_stock(
    inst: StockInstruction,
    ticker_upper: str,
    page_settings: PageSettings,
    *,
    task_query_repo: TaskQueryRepo | None,
    now: datetime,
) -> int:
    """Compute submit qty for a whitelisted stock task.

    Lot path: if instruction carries (referenced_lot_price, sell_quantity)
    and a TaskQueryRepo is injected, look up the most recent reverse-side
    task and multiply by sell_quantity_to_fraction(...). Falls through to
    the default page-settings × position_size path on any miss / missing
    precondition.
    """
    if (
        inst.referenced_lot_price is not None
        and inst.sell_quantity is not None
        and task_query_repo is not None
    ):
        opposite = (
            InstructionType.BUY
            if inst.instruction_type == InstructionType.SELL
            else InstructionType.SELL
        )
        prior_qty = await task_query_repo.find_recent_task_by_ref(
            ticker=ticker_upper,
            side=opposite,
            price=inst.referenced_lot_price,
            before=now,
            window_hours=24 * 7,
        )
        if prior_qty is not None:
            fraction = sell_quantity_to_fraction(inst.sell_quantity)
            qty = max(int(prior_qty * fraction), 1)
            logger.info(
                "Trader: lot ref @%.4f qty=%d × %s → %d (ticker=%s)",
                inst.referenced_lot_price,
                prior_qty,
                inst.sell_quantity,
                qty,
                ticker_upper,
            )
            return qty
        logger.info(
            "Trader: no prior %s within 7d for %s @%.4f, falling back to default qty",
            opposite.value,
            ticker_upper,
            inst.referenced_lot_price,
        )

    base_qty = page_settings.tickers[ticker_upper].trade_quantity
    fraction = position_size_to_fraction(inst.position_size)
    return max(int(base_qty * fraction), 1)
```

At the top of `backend/app/broker/trader.py`, add `from datetime import datetime` after the existing `import time` line:

```python
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
```

(`PageSettings` is already in the existing `TYPE_CHECKING` block — no change needed there. The existing `import time` is the standard `time` module for `time.perf_counter`; `from datetime import datetime` is the class — no conflict.)

- [ ] **Step 6: Run the new tests to confirm they pass**

```bash
cd backend && .venv/bin/python -m pytest tests/broker/test_trader_lot_lookup.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 7: Run the existing trader tests to confirm no regression**

```bash
cd backend && .venv/bin/python -m pytest tests/broker/test_trader.py -v
```

Expected: all 13 tests still PASS (the existing stock branches must keep working unchanged).

- [ ] **Step 8: Commit**

```bash
git add backend/app/broker/trader.py backend/tests/broker/test_trader_lot_lookup.py
git commit -m "$(cat <<'EOF'
feat(trader): add lot-reference qty path for whitelisted stocks

When an instruction carries both referenced_lot_price and sell_quantity
and a TaskQueryRepo is injected, trader looks up the most recent
opposite-side task within 7 days and multiplies its planned quantity by
sell_quantity_to_fraction(...). Falls back to the existing default
trade_quantity × position_size path on any miss. Existing trader tests
remain green.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Wire `SqlTaskQueryRepo` into `main.py`

**Files:**
- Modify: `backend/app/main.py:198-210` (`_register_trader_and_push`)

This is a wiring task. The trader has a working test path now; we just need production runtime to inject the real repo.

- [ ] **Step 1: Construct `SqlTaskQueryRepo` and pass to `register_trader`**

Edit `backend/app/main.py`. Find the `_register_trader_and_push` closure (~line 198) and update it:

```python
        def _register_trader_and_push() -> None:
            from app.storage.repo import SqlTaskQueryRepo

            state.trader_unsub = register_trader(
                bus,
                state.broker,
                _make_trader_cfg(),
                registry=state.whop_registry,
                auto_trade_getter=lambda: state.longport_runtime.get().auto_trade,
                task_query_repo=SqlTaskQueryRepo(session_factory),
            )
            state.push_listener = register_push_listener(
                bus, state.broker, session_factory
            )
```

The `session_factory` variable is in scope here (already used by `register_push_listener` on the next line).

- [ ] **Step 2: Run the full backend test suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: all green. No new tests are added — this step verifies that the wiring change doesn't regress existing main/api tests.

- [ ] **Step 3: Smoke-check the import resolves**

```bash
cd backend && .venv/bin/python -c "from app.main import create_app; print('ok')"
```

Expected output: `ok`. (Catches any circular-import surprises from the new `from app.storage.repo import SqlTaskQueryRepo` line inside the closure.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/main.py
git commit -m "$(cat <<'EOF'
wire(main): inject SqlTaskQueryRepo into trader

Production trader now resolves stock lot references via DB. No-op for
parsers that don't yet emit referenced_lot_price (decision 6: silent
fallback to default qty).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Final verification

- [ ] **Step 1: Run the full backend test suite**

```bash
cd backend && .venv/bin/python -m pytest -q
```

Expected: all green.

- [ ] **Step 2: Confirm no orphaned imports / dead code**

```bash
cd backend && .venv/bin/python -m ruff check app/ tests/ 2>&1 | head -20
```

Expected: no new lint errors related to this plan's changes. (Pre-existing project-wide lint state is fine to leave alone.)

- [ ] **Step 3: Manually verify the diff**

```bash
git log --oneline a9660a8..HEAD
git diff a9660a8..HEAD --stat
```

Expected: 7 commits, one per task, with reasonable file-change counts.

---

## Out of scope (intentionally — see spec §3 and §9)

- **Parser changes** — this plan assumes parser will eventually fill `referenced_lot_price` and `sell_quantity` correctly. Today neither field gets set for the message patterns in the issue list, so this PR is dormant infrastructure until the parser track lands.
- **Option lot references** — only stock path is wired.
- **Real-fill / push-event accounting** — qty source is `tasks.quantity` (planned), not actual fills.
- **`PageSettings.lot_lookup_window_hours`** — 7 days hardcoded; promote to config later.
- **UI display of lot references** — no card-level surface added; can be done after parser starts emitting.
