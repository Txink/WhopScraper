"""Tests for storage/listeners.py — event bus → auto-persistence bridge.

6 test cases:
1. TASK_CREATED → task row saved to DB
2. TASK_CREATED (PARSING) then TASK_INSTRUCTION_READY → DB shows final status
3. TASK_PUSH_EVENT → both task row and push_events row persisted
4. TASK_PARSE_FAILED → DB reflects PARSE_ERROR + reject_reason
5. Unsubscribing stops further persistence
6. Handler exception isolation — a broken payload doesn't prevent subsequent events from persisting
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, TaskPushPayload, Topics
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task
from app.storage.listeners import register_storage_listeners
from app.storage.repo import load_task

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(id_: str = "msg-001") -> Message:
    return Message(
        id=id_,
        content="TSLL 26.5 买入",
        raw_content="TSLL 26.5 买入",
        author="trader",
        posted_at=datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 4, 25, 10, 0, 1, tzinfo=UTC),
        source="stock",
    )


def _make_task(
    id_: str = "msg-001",
    status: Status = Status.RECEIVED,
    reject_reason: str | None = None,
) -> Task:
    now = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
    task = Task(
        id=id_,
        type="unknown",
        status=status,
        message=_msg(id_),
        created_at=now,
        updated_at=now,
        reject_reason=reject_reason,
    )
    return task


def _make_stock_task(id_: str = "msg-stock-001") -> Task:
    now = datetime(2026, 4, 25, 10, 0, 0, tzinfo=UTC)
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.50,
        price_range=None,
        quantity=500,
        position_size=None,
        stop_loss_price=25.80,
        take_profit_price=None,
        context_source="group",
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    task = Task(
        id=id_,
        type="stock",
        status=Status.INSTRUCTION_READY,
        message=_msg(id_),
        instruction=inst,
        created_at=now,
        updated_at=now,
    )
    return task


def _push_event(id_: str, task_id: str) -> PushEvent:
    return PushEvent(
        id=id_,
        task_id=task_id,
        order_id="ORD-001",
        state=PushState.NEW,
        received_at=datetime(2026, 4, 25, 10, 0, 5, tzinfo=UTC),
        payload={"seq": 1},
    )


# ---------------------------------------------------------------------------
# Test 1: TASK_CREATED → saves task to DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_created_event_saves_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    register_storage_listeners(bus, session_factory)

    task = _make_task("msg-created-001", status=Status.RECEIVED)
    await bus.publish(Event(topic=Topics.TASK_CREATED, payload=TaskPayload(task=task)))
    await bus.wait_idle(timeout=1)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-created-001")

    assert loaded is not None
    assert loaded.id == "msg-created-001"
    assert loaded.status == Status.RECEIVED

    await bus.aclose()


# ---------------------------------------------------------------------------
# Test 2: TASK_CREATED (PARSING) then TASK_INSTRUCTION_READY → DB shows final status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_instruction_ready_updates_existing_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    register_storage_listeners(bus, session_factory)

    # First publish: PARSING
    task_v1 = _make_task("msg-upsert-001", status=Status.PARSING)
    await bus.publish(Event(topic=Topics.TASK_CREATED, payload=TaskPayload(task=task_v1)))
    await bus.wait_idle(timeout=1)

    # Verify PARSING was stored
    async with session_factory() as session:
        loaded_v1 = await load_task(session, "msg-upsert-001")
    assert loaded_v1 is not None
    assert loaded_v1.status == Status.PARSING

    # Second publish: INSTRUCTION_READY
    task_v2 = _make_stock_task("msg-upsert-001")
    task_v2.status = Status.INSTRUCTION_READY
    await bus.publish(Event(topic=Topics.TASK_INSTRUCTION_READY, payload=TaskPayload(task=task_v2)))
    await bus.wait_idle(timeout=1)

    async with session_factory() as session:
        loaded_v2 = await load_task(session, "msg-upsert-001")

    assert loaded_v2 is not None
    assert loaded_v2.status == Status.INSTRUCTION_READY
    assert loaded_v2.instruction is not None

    await bus.aclose()


# ---------------------------------------------------------------------------
# Test 3: TASK_PUSH_EVENT → both task row and push_events row persisted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_push_event_persists_both_task_and_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    register_storage_listeners(bus, session_factory)

    task = _make_task("msg-push-001", status=Status.PENDING)
    push_evt = _push_event("evt-push-001", task_id="msg-push-001")

    await bus.publish(
        Event(
            topic=Topics.TASK_PUSH_EVENT,
            payload=TaskPushPayload(task=task, push_event=push_evt),
        )
    )
    await bus.wait_idle(timeout=1)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-push-001")

    assert loaded is not None
    assert loaded.status == Status.PENDING
    assert len(loaded.push_events) == 1
    assert loaded.push_events[0].id == "evt-push-001"
    assert loaded.push_events[0].state == PushState.NEW

    await bus.aclose()


# ---------------------------------------------------------------------------
# Test 4: TASK_PARSE_FAILED → DB reflects PARSE_ERROR + reject_reason
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_parse_failed_persists_parse_error_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    register_storage_listeners(bus, session_factory)

    task = _make_task(
        "msg-parse-err-001",
        status=Status.PARSE_ERROR,
        reject_reason="无法识别 ticker",
    )
    await bus.publish(Event(topic=Topics.TASK_PARSE_FAILED, payload=TaskPayload(task=task)))
    await bus.wait_idle(timeout=1)

    async with session_factory() as session:
        loaded = await load_task(session, "msg-parse-err-001")

    assert loaded is not None
    assert loaded.status == Status.PARSE_ERROR
    assert loaded.reject_reason == "无法识别 ticker"

    await bus.aclose()


# ---------------------------------------------------------------------------
# Test 5: Unsubscribing stops further persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unsubscribe_stops_persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    unsubs = register_storage_listeners(bus, session_factory)

    # Verify subscribe works: first publish goes through
    task_before = _make_task("msg-unsub-before", status=Status.RECEIVED)
    await bus.publish(Event(topic=Topics.TASK_CREATED, payload=TaskPayload(task=task_before)))
    await bus.wait_idle(timeout=1)

    async with session_factory() as session:
        loaded_before = await load_task(session, "msg-unsub-before")
    assert loaded_before is not None, "task should be persisted before unsubscribe"

    # Unsubscribe all
    for unsub in unsubs:
        unsub()

    # Publish after unsubscribe — DB should NOT receive this task
    task_after = _make_task("msg-unsub-after", status=Status.RECEIVED)
    await bus.publish(Event(topic=Topics.TASK_CREATED, payload=TaskPayload(task=task_after)))
    await bus.wait_idle(timeout=1)

    async with session_factory() as session:
        loaded_after = await load_task(session, "msg-unsub-after")
    assert loaded_after is None, "task should NOT be persisted after unsubscribe"

    await bus.aclose()


# ---------------------------------------------------------------------------
# Test 6: Handler exception isolation — broken first event doesn't block subsequent events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_exception_isolated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Patch save_task to raise on the first call, succeed on subsequent calls.

    The bus must still process the second (well-formed) event normally.
    """
    bus = EventBus()
    register_storage_listeners(bus, session_factory)

    call_count = 0
    original_save_task = __import__("app.storage.repo", fromlist=["save_task"]).save_task

    async def _flaky_save(session: AsyncSession, task: Task) -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated first-call failure")
        await original_save_task(session, task)

    with patch("app.storage.listeners.save_task", side_effect=_flaky_save):
        # Re-register with the patched save_task already in place via module patch
        bus2 = EventBus()
        register_storage_listeners(bus2, session_factory)

        task_bad = _make_task("msg-isolated-bad", status=Status.RECEIVED)
        task_good = _make_task("msg-isolated-good", status=Status.RECEIVED)

        await bus2.publish(Event(topic=Topics.TASK_CREATED, payload=TaskPayload(task=task_bad)))
        await bus2.publish(Event(topic=Topics.TASK_CREATED, payload=TaskPayload(task=task_good)))
        await bus2.wait_idle(timeout=1)

    # "good" task should be persisted; "bad" task's handler raised so it won't be
    async with session_factory() as session:
        loaded_good = await load_task(session, "msg-isolated-good")
    async with session_factory() as session:
        loaded_bad = await load_task(session, "msg-isolated-bad")

    assert loaded_good is not None, "good task should be persisted despite earlier failure"
    assert loaded_bad is None, "bad task's handler raised before save; row should not exist"

    await bus2.aclose()
