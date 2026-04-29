"""Tests for storage/schema.py — 5 ORM table definitions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.schema import (
    InstructionRow,
    MessageRow,
    PositionRow,
    PushEventRow,
    TaskRow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)


def _task(id: str = "T1") -> TaskRow:
    return TaskRow(
        id=id,
        type="stock",
        status="RECEIVED",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _message(task_id: str = "T1") -> MessageRow:
    return MessageRow(
        id=task_id,
        content="Buy AAPL 10 @ 150",
        raw_content="Buy AAPL 10 @ 150",
        author="trader1",
        source="stock",
        posted_at=_NOW,
        received_at=_NOW,
    )


def _push_event(id: str, task_id: str = "T1", offset_seconds: int = 0) -> PushEventRow:
    ts = datetime(2024, 1, 15, 12, 0, offset_seconds, tzinfo=UTC)
    return PushEventRow(
        id=id,
        task_id=task_id,
        order_id="ORD-001",
        state="FILLED",
        received_at=ts,
        payload_json={"event": "fill", "seq": offset_seconds},
    )


# ---------------------------------------------------------------------------
# Test 1: all 5 tables created
# ---------------------------------------------------------------------------


async def test_create_all_produces_all_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """After Base.metadata.create_all, all 5 tables should exist in SQLite."""
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
        table_names = {row[0] for row in result.fetchall()}

    expected = {"tasks", "messages", "instructions", "push_events", "positions"}
    assert expected.issubset(table_names), (
        f"Missing tables: {expected - table_names}; found: {table_names}"
    )


# ---------------------------------------------------------------------------
# Test 2: TaskRow insert roundtrip
# ---------------------------------------------------------------------------


async def test_task_row_insert_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Insert a TaskRow with all fields, read back, all fields must match."""
    row = TaskRow(
        id="TASK-42",
        type="option",
        status="FILLED",
        order_id="ORD-999",
        ticker="AAPL",
        symbol="AAPL 240119C00150000",
        side="BUY",
        price=1.25,
        quantity=5,
        reject_reason=None,
        stage_timings_json={"parse": 18, "submit": 42},
        created_at=_NOW,
        updated_at=_NOW,
        submit_order_type="MARKET",
        submit_order_context="买入：现价 1.0 < 信号价 1.25 → 市价单",
        submit_quote_last_done=1.0,
    )
    async with session_factory() as session:
        session.add(row)
        await session.commit()

    async with session_factory() as session:
        fetched = await session.get(TaskRow, "TASK-42")
        assert fetched is not None
        assert fetched.id == "TASK-42"
        assert fetched.type == "option"
        assert fetched.status == "FILLED"
        assert fetched.order_id == "ORD-999"
        assert fetched.ticker == "AAPL"
        assert fetched.symbol == "AAPL 240119C00150000"
        assert fetched.side == "BUY"
        assert fetched.price == pytest.approx(1.25)
        assert fetched.quantity == 5
        assert fetched.reject_reason is None
        assert fetched.stage_timings_json == {"parse": 18, "submit": 42}
        assert fetched.submit_order_type == "MARKET"
        assert "市价" in (fetched.submit_order_context or "")
        assert fetched.submit_quote_last_done == pytest.approx(1.0)
        # SQLite (via aiosqlite) stores timestamps as naive UTC strings and
        # returns them as naive datetime objects.  Compare the UTC wall-clock
        # value, ignoring tzinfo, so the test works with both SQLite and
        # timezone-aware backends (Postgres, etc.).
        assert fetched.created_at.replace(tzinfo=None) == _NOW.replace(tzinfo=None)
        assert fetched.updated_at.replace(tzinfo=None) == _NOW.replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Test 3: MessageRow FK cascade delete
# ---------------------------------------------------------------------------


async def test_message_row_fk_cascade(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Deleting a TaskRow must cascade-delete the linked MessageRow."""
    # Insert task first (flush so FK constraint is satisfiable), then message.
    async with session_factory() as session:
        session.add(_task("T-CASCADE"))
        await session.flush()  # task row hits DB before message FK is checked
        session.add(_message("T-CASCADE"))
        await session.commit()

    # Verify message exists
    async with session_factory() as session:
        msg = await session.get(MessageRow, "T-CASCADE")
        assert msg is not None

    # Delete the task → message should cascade-delete
    async with session_factory() as session:
        task = await session.get(TaskRow, "T-CASCADE")
        assert task is not None
        await session.delete(task)
        await session.commit()

    # Message must be gone
    async with session_factory() as session:
        msg_after = await session.get(MessageRow, "T-CASCADE")
        assert msg_after is None, "MessageRow should have been cascade-deleted with the TaskRow"


# ---------------------------------------------------------------------------
# Test 4: PushEventRow multiple per task, ordered by received_at
# ---------------------------------------------------------------------------


async def test_push_event_row_multiple_per_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """3 push events for the same task_id, read back ordered by received_at."""
    # Flush task first so FK reference exists before push events are inserted.
    async with session_factory() as session:
        session.add(_task("T-PUSH"))
        await session.flush()  # task row must exist before push events
        session.add(_push_event("E3", "T-PUSH", offset_seconds=30))
        session.add(_push_event("E1", "T-PUSH", offset_seconds=0))
        session.add(_push_event("E2", "T-PUSH", offset_seconds=15))
        await session.commit()

    async with session_factory() as session:
        result = await session.execute(
            text("SELECT id FROM push_events WHERE task_id = 'T-PUSH' ORDER BY received_at ASC")
        )
        ids = [row[0] for row in result.fetchall()]

    assert ids == ["E1", "E2", "E3"]


# ---------------------------------------------------------------------------
# Test 5: PositionRow — stock with option fields all NULL (optional)
# ---------------------------------------------------------------------------


async def test_position_row_option_fields_optional(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Stock position with no option fields must insert without error."""
    stock_pos = PositionRow(
        symbol="AAPL",
        type="stock",
        ticker="AAPL",
        quantity=100,
        avg_cost=145.50,
        option_strike=None,
        option_expiry=None,
        option_type=None,
        updated_at=_NOW,
    )
    async with session_factory() as session:
        session.add(stock_pos)
        await session.commit()

    async with session_factory() as session:
        fetched = await session.get(PositionRow, "AAPL")
        assert fetched is not None
        assert fetched.type == "stock"
        assert fetched.option_strike is None
        assert fetched.option_expiry is None
        assert fetched.option_type is None


# ---------------------------------------------------------------------------
# Test 6: InstructionRow 1:1 — second row with same task_id must fail
# ---------------------------------------------------------------------------


async def test_instruction_row_1to1_with_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """InstructionRow.task_id is PK → two rows with same task_id = PK violation."""
    async with session_factory() as session:
        session.add(_task("T-INSTR"))
        await session.commit()

    async with session_factory() as session:
        session.add(
            InstructionRow(
                task_id="T-INSTR",
                instruction_type="stock_order",
                context_source="whop",
                payload_json={"ticker": "AAPL"},
            )
        )
        await session.commit()

    with pytest.raises((IntegrityError, Exception)):
        async with session_factory() as session:
            session.add(
                InstructionRow(
                    task_id="T-INSTR",
                    instruction_type="stock_order",
                    context_source="whop",
                    payload_json={"ticker": "MSFT"},
                )
            )
            await session.commit()
