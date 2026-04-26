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
        status=Status.PENDING if order_id else Status.PARSE_ERROR,
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


async def test_cancelled_task_with_order_id_still_matches(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Decision 4: order_id IS NOT NULL is the only status filter — CANCELLED
    tasks still count as 'submitted to broker'. Locks in the spec promise
    so a future status-filter refactor can't silently break it."""
    base = datetime(2026, 4, 23, 10, 0, 0, tzinfo=UTC)
    cancelled = _stock_task(
        id_="t-cancelled", when=base, side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-1",
    )
    cancelled.status = Status.CANCELLED  # explicitly override the helper default
    async with session_factory() as session:
        await save_task(session, cancelled)

    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session, ticker="TSLL", side=InstructionType.BUY,
            price=12.42, before=base + timedelta(hours=1), window_hours=24 * 7,
        )
    assert qty == 4000


async def test_window_lower_bound_is_inclusive(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A task at exactly `before - window_hours` matches; one second earlier doesn't."""
    base = datetime(2026, 4, 30, 10, 0, 0, tzinfo=UTC)
    seven_days = timedelta(hours=24 * 7)

    on_edge = _stock_task(
        id_="t-edge", when=base - seven_days,  # exactly 7 days
        side=InstructionType.BUY,
        price=12.42, quantity=2000, order_id="ORD-edge",
    )
    just_outside = _stock_task(
        id_="t-out", when=base - seven_days - timedelta(seconds=1),  # 7d + 1s
        side=InstructionType.BUY,
        price=12.42, quantity=4000, order_id="ORD-out",
    )

    async with session_factory() as session:
        await save_task(session, on_edge)
        await save_task(session, just_outside)

    # Exactly-7-days task should match (cutoff is inclusive)
    async with session_factory() as session:
        qty = await find_recent_task_by_ref(
            session, ticker="TSLL", side=InstructionType.BUY,
            price=12.42, before=base, window_hours=24 * 7,
        )
    # The on_edge row is the more-recent qualifier (just_outside is excluded)
    assert qty == 2000


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
