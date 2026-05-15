"""Tests for t_pair repo functions — allocation, CRUD, extension."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage import repo
from app.storage.schema import BrokerExecutionRow, TPairRow

_ACCOUNT = "acct-test"


# ---------------------------------------------------------------------------
# Pure allocation helpers (no DB)
# ---------------------------------------------------------------------------


def test_allocate_fifo_basic() -> None:
    """Allocate 100 across two trades of 60 each → 60 + 40."""
    out = repo.allocate_fifo(
        trade_ids=["a", "b"],
        trade_qty={"a": 60, "b": 60},
        already_allocated={},
        target=100,
    )
    assert out == [{"trade_id": "a", "qty": 60}, {"trade_id": "b", "qty": 40}]


def test_allocate_fifo_skips_fully_used() -> None:
    out = repo.allocate_fifo(
        trade_ids=["a", "b"],
        trade_qty={"a": 60, "b": 60},
        already_allocated={"a": 60},
        target=50,
    )
    assert out == [{"trade_id": "b", "qty": 50}]


def test_allocate_fifo_target_zero() -> None:
    assert repo.allocate_fifo(["a"], {"a": 10}, {}, 0) == []


def test_allocate_fifo_stops_at_availability() -> None:
    """If total avail < target, return what's possible."""
    out = repo.allocate_fifo(
        trade_ids=["a"],
        trade_qty={"a": 30},
        already_allocated={},
        target=100,
    )
    assert out == [{"trade_id": "a", "qty": 30}]


def test_aggregate_allocated_sums_across_pairs() -> None:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    pairs = [
        TPairRow(
            account_id=_ACCOUNT, ticker="X",
            buys_json=[{"trade_id": "a", "qty": 40}],
            sells_json=[{"trade_id": "b", "qty": 40}],
            created_at=now, updated_at=now,
        ),
        TPairRow(
            account_id=_ACCOUNT, ticker="X",
            buys_json=[{"trade_id": "a", "qty": 20}, {"trade_id": "c", "qty": 50}],
            sells_json=[],
            created_at=now, updated_at=now,
        ),
    ]
    agg = repo.aggregate_allocated(pairs)
    assert agg == {"a": 60, "b": 40, "c": 50}


# ---------------------------------------------------------------------------
# DB-backed CRUD
# ---------------------------------------------------------------------------


async def _seed_executions(
    session: AsyncSession,
    fills: dict[str, tuple[str, int, float]],
) -> None:
    """Seed broker_executions rows so create_pair / _sync_pair_tags can
    resolve trade_ids → prices and write t_pair_tags.

    ``fills`` maps order_id → (side, qty, price).
    """
    now = datetime(2024, 1, 1, tzinfo=UTC)
    for order_id, (side, qty, price) in fills.items():
        session.add(
            BrokerExecutionRow(
                order_id=order_id,
                account_id=_ACCOUNT,
                task_id=None,
                symbol="TSLA.US",
                ticker="TSLA",
                side=side,
                qty=qty,
                price=price,
                ts=now,
                t_pair_tags=[],
            )
        )
    await session.commit()


async def test_create_pair_auto_balances(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """BUY 100 + SELL 150 → allocates 100/100, SELL has 50 leftover."""
    async with session_factory() as session:
        await _seed_executions(
            session,
            {"b1": ("BUY", 100, 100.0), "s1": ("SELL", 150, 110.0)},
        )
        pair = await repo.create_pair(
            session,
            ticker="TSLA",
            symbol="TSLA.US",
            buy_trade_ids=["b1"],
            sell_trade_ids=["s1"],
            trade_qty={"b1": 100, "s1": 150},
            account_id=_ACCOUNT,
        )
    assert pair is not None
    assert pair.id is not None and isinstance(pair.id, int)
    assert pair.buys_json == [{"trade_id": "b1", "qty": 100}]
    assert pair.sells_json == [{"trade_id": "s1", "qty": 100}]
    # Matched 100 × (110 - 100) = 1000.
    assert pair.profit == 1000.0


async def test_create_pair_persists_t_pair_tags(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pair create denormalizes ``[pair_id, qty]`` into both referenced trades."""
    async with session_factory() as session:
        await _seed_executions(
            session,
            {"b1": ("BUY", 80, 50.0), "s1": ("SELL", 80, 55.0)},
        )
        pair = await repo.create_pair(
            session,
            ticker="TSLA",
            symbol=None,
            buy_trade_ids=["b1"],
            sell_trade_ids=["s1"],
            trade_qty={"b1": 80, "s1": 80},
            account_id=_ACCOUNT,
        )
        assert pair is not None
        b_row = await session.get(BrokerExecutionRow, "b1")
        s_row = await session.get(BrokerExecutionRow, "s1")
        assert b_row is not None and s_row is not None
        assert b_row.t_pair_tags == [[pair.id, 80]]
        assert s_row.t_pair_tags == [[pair.id, 80]]


async def test_create_pair_one_sided(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Selection with only BUYs creates a one-sided (partial) pair."""
    async with session_factory() as session:
        await _seed_executions(session, {"b1": ("BUY", 100, 50.0)})
        pair = await repo.create_pair(
            session,
            ticker="TSLA",
            symbol=None,
            buy_trade_ids=["b1"],
            sell_trade_ids=[],
            trade_qty={"b1": 100},
            account_id=_ACCOUNT,
        )
    assert pair is not None
    assert pair.buys_json == [{"trade_id": "b1", "qty": 100}]
    assert pair.sells_json == []
    # One-sided → profit is zero (no matched portion).
    assert pair.profit == 0.0


async def test_create_pair_returns_none_when_no_avail(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If every selected trade has 0 avail (e.g. unknown ids), no pair is created."""
    async with session_factory() as session:
        pair = await repo.create_pair(
            session,
            ticker="TSLA",
            symbol=None,
            buy_trade_ids=["unknown"],
            sell_trade_ids=["alsounknown"],
            trade_qty={},  # no qty info
            account_id=_ACCOUNT,
        )
    assert pair is None


async def test_create_pair_respects_existing_allocations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A trade already in another pair has its allocated qty deducted from avail."""
    async with session_factory() as session:
        await _seed_executions(
            session,
            {"b1": ("BUY", 100, 50.0), "s1": ("SELL", 60, 55.0)},
        )
        first = await repo.create_pair(
            session,
            ticker="TSLA", symbol="TSLA.US",
            buy_trade_ids=["b1"], sell_trade_ids=["s1"],
            trade_qty={"b1": 100, "s1": 60},
            account_id=_ACCOUNT,
        )
        assert first is not None
        # s1 had 60 qty, all allocated → avail = 0. New pair using b1+s1
        # should only consume b1's remaining 40 BUY → SELL side is empty.
        second = await repo.create_pair(
            session,
            ticker="TSLA", symbol="TSLA.US",
            buy_trade_ids=["b1"], sell_trade_ids=["s1"],
            trade_qty={"b1": 100, "s1": 60},
            account_id=_ACCOUNT,
        )
    assert second is not None
    assert second.buys_json == [{"trade_id": "b1", "qty": 40}]
    assert second.sells_json == []


async def test_list_pairs_filters_by_ticker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await _seed_executions(
            session,
            {
                "b1": ("BUY", 50, 10.0), "s1": ("SELL", 50, 12.0),
                "b2": ("BUY", 30, 20.0), "s2": ("SELL", 30, 22.0),
            },
        )
        p1 = await repo.create_pair(
            session, ticker="TSLA", symbol=None,
            buy_trade_ids=["b1"], sell_trade_ids=["s1"],
            trade_qty={"b1": 50, "s1": 50},
            account_id=_ACCOUNT,
        )
        p2 = await repo.create_pair(
            session, ticker="NVDA", symbol=None,
            buy_trade_ids=["b2"], sell_trade_ids=["s2"],
            trade_qty={"b2": 30, "s2": 30},
            account_id=_ACCOUNT,
        )
        assert p1 and p2
        tsla = await repo.list_pairs(session, ticker="TSLA", account_id=_ACCOUNT)
        nvda = await repo.list_pairs(session, ticker="NVDA", account_id=_ACCOUNT)
        all_pairs = await repo.list_pairs(session, account_id=_ACCOUNT)
    assert [p.id for p in tsla] == [p1.id]
    assert [p.id for p in nvda] == [p2.id]
    assert len(all_pairs) == 2


async def test_delete_pair_returns_false_when_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        ok = await repo.delete_pair(session, 9999)
    assert ok is False


async def test_delete_pair_clears_tags_from_referenced_trades(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Removing a pair must strip its ``[pair_id, qty]`` from every
    broker_execution that referenced it — otherwise pending-做T SQL would
    still treat those qty as allocated."""
    async with session_factory() as session:
        await _seed_executions(
            session,
            {"b1": ("BUY", 50, 10.0), "s1": ("SELL", 50, 12.0)},
        )
        pair = await repo.create_pair(
            session,
            ticker="TSLA", symbol=None,
            buy_trade_ids=["b1"], sell_trade_ids=["s1"],
            trade_qty={"b1": 50, "s1": 50},
            account_id=_ACCOUNT,
        )
        assert pair is not None
        ok = await repo.delete_pair(session, pair.id)
        assert ok is True
        b_row = await session.get(BrokerExecutionRow, "b1")
        s_row = await session.get(BrokerExecutionRow, "s1")
        assert b_row is not None and s_row is not None
        assert b_row.t_pair_tags == []
        assert s_row.t_pair_tags == []


async def test_extend_pair_fills_gap_then_leaves_leftover(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pair starts {BUY 100, SELL 60} (partial, missing 40 SELL).
    Add SELL of 80 qty → 40 fills the gap, 40 stays as leftover on trade."""
    async with session_factory() as session:
        await _seed_executions(
            session,
            {
                "b1": ("BUY", 100, 50.0),
                "s1": ("SELL", 60, 52.0),
                "s2": ("SELL", 80, 53.0),
            },
        )
        now = datetime(2024, 1, 1, tzinfo=UTC)
        pair = TPairRow(
            account_id=_ACCOUNT, ticker="TSLA", symbol=None,
            buys_json=[{"trade_id": "b1", "qty": 100}],
            sells_json=[{"trade_id": "s1", "qty": 60}],
            created_at=now, updated_at=now,
        )
        session.add(pair)
        await session.flush()
        # Seed t_pair_tags by hand so the extend's _sync_pair_tags has a
        # consistent starting state to mutate.
        b1 = await session.get(BrokerExecutionRow, "b1")
        s1 = await session.get(BrokerExecutionRow, "s1")
        assert b1 is not None and s1 is not None
        b1.t_pair_tags = [[pair.id, 100]]
        s1.t_pair_tags = [[pair.id, 60]]
        await session.commit()

        updated = await repo.extend_pair(
            session,
            pair_id=pair.id,
            buy_trade_ids=[],
            sell_trade_ids=["s2"],
            trade_qty={"b1": 100, "s1": 60, "s2": 80},
            account_id=_ACCOUNT,
        )
        assert updated is not None
        # gap was 40 → s2 contributes 40, remaining 40 stays on s2 for next pair
        assert updated.sells_json == [
            {"trade_id": "s1", "qty": 60},
            {"trade_id": "s2", "qty": 40},
        ]
        # s2 now carries the pair tag too.
        s2 = await session.get(BrokerExecutionRow, "s2")
        assert s2 is not None
        assert s2.t_pair_tags == [[pair.id, 40]]


async def test_extend_pair_one_sided_creates_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Extending a matched pair with only BUYs creates an intentional
    mismatch (UI shows '部分做T'). The leftover SELL side is unchanged."""
    async with session_factory() as session:
        await _seed_executions(
            session,
            {
                "b1": ("BUY", 50, 10.0),
                "s1": ("SELL", 50, 12.0),
                "b2": ("BUY", 30, 11.0),
            },
        )
        now = datetime(2024, 1, 1, tzinfo=UTC)
        pair = TPairRow(
            account_id=_ACCOUNT, ticker="TSLA", symbol=None,
            buys_json=[{"trade_id": "b1", "qty": 50}],
            sells_json=[{"trade_id": "s1", "qty": 50}],
            created_at=now, updated_at=now,
        )
        session.add(pair)
        await session.flush()
        b1 = await session.get(BrokerExecutionRow, "b1")
        s1 = await session.get(BrokerExecutionRow, "s1")
        assert b1 is not None and s1 is not None
        b1.t_pair_tags = [[pair.id, 50]]
        s1.t_pair_tags = [[pair.id, 50]]
        await session.commit()

        updated = await repo.extend_pair(
            session,
            pair_id=pair.id,
            buy_trade_ids=["b2"],
            sell_trade_ids=[],
            trade_qty={"b1": 50, "s1": 50, "b2": 30},
            account_id=_ACCOUNT,
        )
        assert updated is not None
        assert updated.buys_json == [
            {"trade_id": "b1", "qty": 50},
            {"trade_id": "b2", "qty": 30},
        ]
        assert updated.sells_json == [{"trade_id": "s1", "qty": 50}]


async def test_extend_pair_missing_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await repo.extend_pair(
            session, pair_id=9999,
            buy_trade_ids=["x"], sell_trade_ids=[],
            trade_qty={"x": 10},
        )
    assert result is None
