"""Tests for storage/repo.py — business-level CRUD for Tasks / Messages /
Instructions / PushEvents.

9 test cases covering:
1. StockInstruction round-trip
2. OptionInstruction round-trip (expiry date!)
3. Task with no instruction (PARSE_ERROR)
4. Upsert: save v1 (PARSING) → save v2 (INSTRUCTION_READY) → load returns v2
5. append_push_event — two events appear ordered in loaded Task
6. list_tasks orders by created_at DESC
7. list_tasks filter by status
8. list_tasks pagination via cursor
9. load_task returns None for missing id
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.instruction import InstructionType, OptionInstruction, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task
from app.storage.repo import (
    append_push_event,
    list_tasks,
    load_task,
    load_task_by_order_id,
    save_task,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(id_: str = "msg-001", source: str = "stock") -> Message:
    return Message(
        id=id_,
        content="TSLL 26.5 买入",
        raw_content="TSLL 26.5 买入",
        author="trader",
        posted_at=datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 4, 25, 10, 0, 1, tzinfo=UTC),
        source=source,  # type: ignore[arg-type]
    )


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


def _option_inst() -> OptionInstruction:
    return OptionInstruction(
        instruction_type=InstructionType.BUY,
        price=None,
        price_range=(2.0, 2.5),
        quantity=10,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="AAPL",
        option_type="CALL",
        strike=135.0,
        expiry=date(2026, 4, 26),
        symbol="AAPL 260426C00135000",
    )


def _make_task(
    id_: str = "msg-001",
    status: Status = Status.RECEIVED,
    instruction: StockInstruction | OptionInstruction | None = None,
    created_at: datetime | None = None,
    source: str = "stock",
) -> Task:
    now = created_at or datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
    task = Task(
        id=id_,
        type="unknown",
        status=status,
        message=_msg(id_, source=source),
        instruction=instruction,
        created_at=now,
        updated_at=now,
    )
    if instruction is not None:
        if isinstance(instruction, OptionInstruction):
            task.type = "option"
        else:
            task.type = "stock"
    return task


def _push_event(id_: str, task_id: str, seq: int = 0) -> PushEvent:
    return PushEvent(
        id=id_,
        task_id=task_id,
        order_id="ORD-001",
        state=PushState.NEW,
        received_at=datetime(2026, 4, 25, 10, 0, seq, tzinfo=UTC),
        payload={"seq": seq},
    )


# ---------------------------------------------------------------------------
# 1. StockInstruction round-trip
# ---------------------------------------------------------------------------


async def test_save_and_load_task_with_stock_instruction_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inst = _stock_inst()
    task = _make_task("msg-stock-001", status=Status.INSTRUCTION_READY, instruction=inst)
    task.type = "stock"

    async with session_factory() as session:
        await save_task(session, task)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-stock-001")

    assert loaded is not None
    assert loaded.id == "msg-stock-001"
    assert loaded.status == Status.INSTRUCTION_READY
    assert loaded.type == "stock"

    # Message fields
    assert loaded.message.content == task.message.content
    assert loaded.message.source == "stock"
    assert loaded.message.author == "trader"

    # Instruction fields
    assert isinstance(loaded.instruction, StockInstruction)
    li = loaded.instruction
    assert li.instruction_type == InstructionType.BUY
    assert li.price == pytest.approx(26.50)
    assert li.price_range is None
    assert li.quantity == 500
    assert li.position_size == "小仓位"
    assert li.stop_loss_price == pytest.approx(25.80)
    assert li.take_profit_price is None
    assert li.context_source == "group"
    assert li.parser_notes == ["note1"]
    assert li.ticker == "TSLL"
    assert li.symbol == "TSLL.US"
    assert li.sell_quantity is None
    assert li.referenced_lot_price == pytest.approx(12.42)  # ← add this line

    # No push events on fresh task
    assert loaded.push_events == []


# ---------------------------------------------------------------------------
# 2. OptionInstruction round-trip (expiry date!)
# ---------------------------------------------------------------------------


async def test_save_and_load_task_with_option_instruction_roundtrip(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    inst = _option_inst()
    task = _make_task(
        "msg-opt-001", status=Status.INSTRUCTION_READY, instruction=inst, source="option"
    )
    task.type = "option"

    async with session_factory() as session:
        await save_task(session, task)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-opt-001")

    assert loaded is not None
    assert loaded.type == "option"
    assert isinstance(loaded.instruction, OptionInstruction)
    li = loaded.instruction

    # price_range round-trip: tuple[float, float]
    assert li.price_range == (2.0, 2.5)
    assert li.price is None
    assert li.quantity == 10
    assert li.ticker == "AAPL"
    assert li.option_type == "CALL"
    assert li.strike == pytest.approx(135.0)
    # expiry date round-trip
    assert li.expiry == date(2026, 4, 26)
    assert li.symbol == "AAPL 260426C00135000"


# ---------------------------------------------------------------------------
# 3. Task with no instruction (PARSE_ERROR)
# ---------------------------------------------------------------------------


async def test_save_task_without_instruction_parse_error_case(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task = _make_task("msg-err-001", status=Status.PARSE_ERROR, instruction=None)
    task.reject_reason = "无法识别 ticker"

    async with session_factory() as session:
        await save_task(session, task)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-err-001")

    assert loaded is not None
    assert loaded.status == Status.PARSE_ERROR
    assert loaded.instruction is None
    assert loaded.reject_reason == "无法识别 ticker"


# ---------------------------------------------------------------------------
# 4. Upsert: save v1 (PARSING) → save v2 (INSTRUCTION_READY) → load returns v2
# ---------------------------------------------------------------------------


async def test_save_task_upsert_updates_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # v1: no instruction, PARSE_ERROR-adjacent — let's use a raw task with RECEIVED status
    # Build a RECEIVED task then mutate it to PARSING by setting status directly
    task = _make_task("msg-upsert-001")
    task.status = Status.PARSING  # bypass state machine for test setup

    async with session_factory() as session:
        await save_task(session, task)

    # v2: attach instruction → INSTRUCTION_READY
    inst = _stock_inst()
    task.instruction = inst
    task.type = "stock"
    task.status = Status.INSTRUCTION_READY

    async with session_factory() as session:
        await save_task(session, task)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-upsert-001")

    assert loaded is not None
    assert loaded.status == Status.INSTRUCTION_READY
    assert isinstance(loaded.instruction, StockInstruction)
    assert loaded.instruction.ticker == "TSLL"


# ---------------------------------------------------------------------------
# 5. append_push_event — two events appear ordered in loaded Task
# ---------------------------------------------------------------------------


async def test_append_push_event_and_load_shows_in_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task = _make_task("msg-pe-001")

    async with session_factory() as session:
        await save_task(session, task)

    evt1 = _push_event("evt-001", "msg-pe-001", seq=0)
    evt2 = _push_event("evt-002", "msg-pe-001", seq=5)

    async with session_factory() as session:
        await append_push_event(session, evt1)

    async with session_factory() as session:
        await append_push_event(session, evt2)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-pe-001")

    assert loaded is not None
    assert len(loaded.push_events) == 2
    assert loaded.push_events[0].id == "evt-001"
    assert loaded.push_events[1].id == "evt-002"
    assert loaded.push_events[0].received_at < loaded.push_events[1].received_at


# ---------------------------------------------------------------------------
# 6. list_tasks orders by created_at DESC
# ---------------------------------------------------------------------------


async def test_list_tasks_orders_by_created_at_desc(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    t1 = _make_task("msg-list-001", created_at=datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC))
    t2 = _make_task("msg-list-002", created_at=datetime(2026, 4, 25, 11, 0, 0, tzinfo=UTC))
    t3 = _make_task("msg-list-003", created_at=datetime(2026, 4, 25, 12, 0, 0, tzinfo=UTC))

    async with session_factory() as session:
        await save_task(session, t1)
        await save_task(session, t2)
        await save_task(session, t3)

    async with session_factory() as session:
        results = await list_tasks(session)

    assert len(results) == 3
    assert results[0].id == "msg-list-003"  # newest first
    assert results[1].id == "msg-list-002"
    assert results[2].id == "msg-list-001"


# ---------------------------------------------------------------------------
# 7. list_tasks filter by status
# ---------------------------------------------------------------------------


async def test_list_tasks_filter_by_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    t_received = _make_task("msg-filt-001", status=Status.RECEIVED)
    t_parsing = _make_task("msg-filt-002", status=Status.PARSING)
    t_parse_error = _make_task("msg-filt-003", status=Status.PARSE_ERROR)

    async with session_factory() as session:
        await save_task(session, t_received)
        await save_task(session, t_parsing)
        await save_task(session, t_parse_error)

    async with session_factory() as session:
        results = await list_tasks(session, status=Status.PARSE_ERROR)

    assert len(results) == 1
    assert results[0].id == "msg-filt-003"
    assert results[0].status == Status.PARSE_ERROR


# ---------------------------------------------------------------------------
# 8. list_tasks pagination via cursor
# ---------------------------------------------------------------------------


async def test_list_tasks_pagination_via_cursor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tasks = [
        _make_task(
            f"msg-page-{i:03d}",
            created_at=datetime(2026, 4, 25, 10, i, 0, tzinfo=UTC),
        )
        for i in range(5)
    ]

    async with session_factory() as session:
        for t in tasks:
            await save_task(session, t)

    # Page 1
    async with session_factory() as session:
        page1 = await list_tasks(session, limit=2)
    assert len(page1) == 2
    assert page1[0].id == "msg-page-004"  # newest first (i=4 → 10:04)
    assert page1[1].id == "msg-page-003"

    # Page 2 — cursor is the last item's created_at
    cursor = page1[-1].created_at
    async with session_factory() as session:
        page2 = await list_tasks(session, limit=2, cursor_created_at=cursor)
    assert len(page2) == 2
    assert page2[0].id == "msg-page-002"
    assert page2[1].id == "msg-page-001"

    # Page 3
    cursor2 = page2[-1].created_at
    async with session_factory() as session:
        page3 = await list_tasks(session, limit=2, cursor_created_at=cursor2)
    assert len(page3) == 1
    assert page3[0].id == "msg-page-000"

    # All 5 items retrieved, no overlap
    all_ids = {t.id for t in page1 + page2 + page3}
    assert all_ids == {f"msg-page-{i:03d}" for i in range(5)}


# ---------------------------------------------------------------------------
# 9. load_task returns None for missing id
# ---------------------------------------------------------------------------


async def test_load_task_returns_none_when_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await load_task(session, "nonexistent-id-xyz")
    assert result is None


# ---------------------------------------------------------------------------
# 10. load_task_by_order_id — found
# ---------------------------------------------------------------------------


async def test_load_task_by_order_id_found(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task = _make_task("msg-oid-001", status=Status.PENDING)
    task.order_id = "ORD-XYZ-001"

    async with session_factory() as session:
        await save_task(session, task)

    async with session_factory() as session:
        loaded = await load_task_by_order_id(session, "ORD-XYZ-001")

    assert loaded is not None
    assert loaded.id == "msg-oid-001"
    assert loaded.order_id == "ORD-XYZ-001"
    assert loaded.status == Status.PENDING


# ---------------------------------------------------------------------------
# 11. load_task_by_order_id — not found returns None
# ---------------------------------------------------------------------------


async def test_load_task_by_order_id_not_found_returns_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await load_task_by_order_id(session, "does-not-exist-ord")
    assert result is None


# ---------------------------------------------------------------------------
# 12. messages.url round-trip — value persists through save → load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_url_persists_through_save_and_load(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    msg = Message(
        id="domid-with-url",
        content="x",
        raw_content="x",
        author="a",
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url="https://whop.com/joined/test/app/",
    )
    task = Task.new_from_message(msg)
    async with session_factory() as session:
        await save_task(session, task)
    async with session_factory() as session:
        loaded = await load_task(session, "domid-with-url")
    assert loaded is not None
    assert loaded.message.url == "https://whop.com/joined/test/app/"


# ---------------------------------------------------------------------------
# 13. messages.url defaults to None when not supplied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_url_default_none(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    msg = Message(
        id="domid-no-url",
        content="x",
        raw_content="x",
        author="a",
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
    )
    task = Task.new_from_message(msg)
    async with session_factory() as session:
        await save_task(session, task)
    async with session_factory() as session:
        loaded = await load_task(session, "domid-no-url")
    assert loaded is not None
    assert loaded.message.url is None


# ---------------------------------------------------------------------------
# 13b. messages.url is backfilled from NULL when re-saving with a non-null url
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_message_url_backfilled_on_resave_when_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Re-saving a Message with the same id but a non-null url backfills the url."""
    ts = datetime.now(UTC)
    # First write: url is None (legacy / pre-listener-injection scenario)
    msg_no_url = Message(
        id="dom-backfill",
        content="x",
        raw_content="x",
        author=None,
        posted_at=ts,
        received_at=ts,
        source="stock",
        url=None,
    )
    async with session_factory() as session:
        await save_task(session, Task.new_from_message(msg_no_url))
    # Second write: same id, now with url (listener republishing post-fix)
    msg_with_url = Message(
        id="dom-backfill",
        content="x",
        raw_content="x",
        author=None,
        posted_at=ts,
        received_at=ts,
        source="stock",
        url="https://whop.com/x/app/",
    )
    async with session_factory() as session:
        await save_task(session, Task.new_from_message(msg_with_url))
    async with session_factory() as session:
        loaded = await load_task(session, "dom-backfill")
    assert loaded is not None
    assert loaded.message.url == "https://whop.com/x/app/"


@pytest.mark.asyncio
async def test_message_url_not_overwritten_when_already_set(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Re-saving with a different url does NOT overwrite an existing non-null url
    (preserves existing url; protects against accidental cross-listener writes)."""
    ts = datetime.now(UTC)
    msg_a = Message(
        id="dom-protected",
        content="x",
        raw_content="x",
        author=None,
        posted_at=ts,
        received_at=ts,
        source="stock",
        url="https://whop.com/a/app/",
    )
    async with session_factory() as session:
        await save_task(session, Task.new_from_message(msg_a))
    msg_b = Message(  # different url, same id (pretend cross-listener mishap)
        id="dom-protected",
        content="x",
        raw_content="x",
        author=None,
        posted_at=ts,
        received_at=ts,
        source="stock",
        url="https://whop.com/b/app/",
    )
    async with session_factory() as session:
        await save_task(session, Task.new_from_message(msg_b))
    async with session_factory() as session:
        loaded = await load_task(session, "dom-protected")
    assert loaded is not None
    assert loaded.message.url == "https://whop.com/a/app/"  # preserved


# ---------------------------------------------------------------------------
# 14. Concurrent save_task calls for the same Task.id must not raise UNIQUE conflict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_task_concurrent_same_id_no_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two concurrent save_task calls for the same Task.id must not raise UNIQUE conflict."""
    import asyncio

    from app.storage.db import session_scope

    task = _make_task()  # status=RECEIVED initially
    task.mark_parsing()

    async def _save_once() -> None:
        async with session_scope(session_factory) as session:
            await save_task(session, task)

    # Launch 5 concurrent saves of the same task
    await asyncio.gather(*(_save_once() for _ in range(5)))

    # Should still be loadable
    async with session_scope(session_factory) as session:
        loaded = await load_task(session, task.id)
    assert loaded is not None
    assert loaded.id == task.id


# ---------------------------------------------------------------------------
# 15. Terminal-status race protection
# ---------------------------------------------------------------------------
# Reproduces the production race that left tasks stuck at PENDING despite
# REJECTED push events. Two SDK pushes (NotReported → SUBMITTED, Rejected
# → REJECTED) for the same order_id arrive within ms. Their _handle_raw_push
# coroutines both load the task at PENDING. Coroutine B saves REJECTED.
# Coroutine A (slow) then tries to save the (still-in-memory) task as
# PENDING with state=SUBMITTED → without race protection this overwrites
# REJECTED with PENDING, and the UI shows "等待成交" indefinitely.


@pytest.mark.asyncio
async def test_save_task_does_not_overwrite_terminal_status_with_non_terminal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A subsequent save with a non-terminal status must NOT overwrite an
    existing terminal status row. (Race protection for concurrent push handlers.)
    """
    from app.storage.db import session_scope

    task_id = "msg-terminal-race"
    # First save: terminal REJECTED with reject_reason
    task_terminal = _make_task(task_id, status=Status.RECEIVED)
    task_terminal.mark_parsing()
    task_terminal.attach_instruction(_stock_inst())
    task_terminal.mark_submitting()
    task_terminal.mark_submitted(order_id="ORD-RACE", timing_ms=10.0)
    # transition PENDING → REJECTED
    task_terminal.append_push_event(
        PushEvent(
            id="evt-1",
            task_id=task_id,
            order_id="ORD-RACE",
            state=PushState.REJECTED,
            received_at=datetime(2026, 4, 26, 10, 0, 0, tzinfo=UTC),
            payload={},
            note="订单金额超出最大购买力",
        )
    )
    task_terminal.reject_reason = "订单金额超出最大购买力"
    async with session_scope(session_factory) as session:
        await save_task(session, task_terminal)

    # Second save: same task_id, non-terminal status PENDING with no reject_reason.
    # This simulates the race-y "later" coroutine whose in-memory task never
    # observed the REJECTED transition. The save MUST be a no-op on the
    # status / reject_reason fields — DB stays at REJECTED.
    task_stale = _make_task(task_id, status=Status.RECEIVED)
    task_stale.mark_parsing()
    task_stale.attach_instruction(_stock_inst())
    task_stale.mark_submitting()
    task_stale.mark_submitted(order_id="ORD-RACE", timing_ms=10.0)
    # leave at PENDING, no reject_reason
    async with session_scope(session_factory) as session:
        await save_task(session, task_stale)

    async with session_scope(session_factory) as session:
        loaded = await load_task(session, task_id)
    assert loaded is not None
    assert loaded.status == Status.REJECTED, (
        f"expected REJECTED to be preserved, got {loaded.status}"
    )
    assert loaded.reject_reason == "订单金额超出最大购买力"


@pytest.mark.asyncio
async def test_save_task_normal_progression_through_non_terminal_still_updates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Race protection must NOT block legitimate non-terminal → non-terminal
    or non-terminal → terminal updates. RECEIVED → PARSING → INSTRUCTION_READY
    → SUBMITTING → PENDING → REJECTED should all persist normally.
    """
    from app.storage.db import session_scope

    task_id = "msg-progression"
    task = _make_task(task_id, status=Status.RECEIVED)

    # RECEIVED → PARSING
    task.mark_parsing()
    async with session_scope(session_factory) as session:
        await save_task(session, task)

    # PARSING → INSTRUCTION_READY
    task.attach_instruction(_stock_inst())
    async with session_scope(session_factory) as session:
        await save_task(session, task)
    async with session_scope(session_factory) as session:
        loaded = await load_task(session, task_id)
    assert loaded is not None and loaded.status == Status.INSTRUCTION_READY

    # INSTRUCTION_READY → SUBMITTING → PENDING → REJECTED
    task.mark_submitting()
    task.mark_submitted(order_id="ORD-PROG", timing_ms=12.0)
    async with session_scope(session_factory) as session:
        await save_task(session, task)
    async with session_scope(session_factory) as session:
        loaded = await load_task(session, task_id)
    assert loaded is not None and loaded.status == Status.PENDING

    # Final: PENDING → REJECTED (legitimate terminal transition)
    task.append_push_event(
        PushEvent(
            id="evt-final",
            task_id=task_id,
            order_id="ORD-PROG",
            state=PushState.REJECTED,
            received_at=datetime(2026, 4, 26, 10, 0, 0, tzinfo=UTC),
            payload={},
            note="风控驳回",
        )
    )
    task.reject_reason = "风控驳回"
    async with session_scope(session_factory) as session:
        await save_task(session, task)

    async with session_scope(session_factory) as session:
        loaded = await load_task(session, task_id)
    assert loaded is not None
    assert loaded.status == Status.REJECTED
    assert loaded.reject_reason == "风控驳回"


@pytest.mark.asyncio
async def test_save_task_all_terminal_statuses_protected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every terminal status (PARSE_ERROR, SUBMIT_FAILED, FILLED, CANCELLED,
    REJECTED, SKIPPED) must be protected — not just REJECTED.
    """
    from app.storage.db import session_scope

    cases = [
        ("term-parse-err", Status.PARSE_ERROR),
        ("term-submit-fail", Status.SUBMIT_FAILED),
        ("term-filled", Status.FILLED),
        ("term-cancelled", Status.CANCELLED),
        ("term-rejected", Status.REJECTED),
        ("term-skipped", Status.SKIPPED),
    ]

    for task_id, terminal_status in cases:
        # Save row directly at terminal status
        task = _make_task(task_id, status=terminal_status)
        async with session_scope(session_factory) as session:
            await save_task(session, task)

        # Try to overwrite with a non-terminal status
        stale = _make_task(task_id, status=Status.RECEIVED)
        async with session_scope(session_factory) as session:
            await save_task(session, stale)

        async with session_scope(session_factory) as session:
            loaded = await load_task(session, task_id)
        assert loaded is not None
        assert loaded.status == terminal_status, (
            f"{terminal_status.value} was overwritten by RECEIVED — "
            f"got {loaded.status}"
        )
