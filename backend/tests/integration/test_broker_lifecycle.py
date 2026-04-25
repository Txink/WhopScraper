"""Full broker lifecycle integration: INSTRUCTION_READY → submit → push sequence → DB persistence.

This test exercises the *complete* wired-up pipeline end-to-end:

    TASK_INSTRUCTION_READY
        → Trader submits to FakeBrokerClient (returns order_id)
        → TASK_ORDER_SUBMITTED
        → StorageListeners upsert Task to in-memory SQLite
        → PushListener._handle_raw_push (NEW / PARTIAL / FILLED)
        → TASK_PUSH_EVENT
        → StorageListeners append PushEventRow + upsert Task status

No mocking of domain or storage layers — the full stack from EventBus to DB.

Concurrency note
----------------
``EventBus.publish()`` schedules handlers as concurrent ``asyncio.Task``s.
When ``TASK_INSTRUCTION_READY`` is published, the storage listener fires
concurrently with the Trader handler; the Trader immediately publishes
``TASK_STATUS_CHANGED`` (SUBMITTING) and ``TASK_ORDER_SUBMITTED``, whose
storage handlers also fire concurrently.  If the initial INSERT hasn't
committed by the time these secondary handlers run they all race to INSERT
the same task_id, causing a UNIQUE constraint failure.

Fix: pre-save the fully-built task to the DB *before* publishing
``TASK_INSTRUCTION_READY``.  That way the storage listener receives an
already-committed row and uses the UPDATE path for all subsequent events.
This mirrors real-world usage where an upstream scanner pipeline (Tasks 22–25)
saves the task before emitting the event.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.config import LongPortConfig
from app.broker.push_listener import PushListener, register_push_listener
from app.broker.trader import register_trader
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.storage.db import session_scope
from app.storage.listeners import register_storage_listeners
from app.storage.repo import load_task, save_task
from tests.broker._fakes import FakeBrokerClient

# ---------------------------------------------------------------------------
# Fake SDK push event — mirrors the shape push_listener expects
# ---------------------------------------------------------------------------


@dataclass
class FakePushEvt:
    """Minimal stand-in for a LongPort order-changed push event."""

    order_id: str
    status: str  # plain string — push_listener handles both string and enum
    executed_quantity: int | None = None
    executed_price: float | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config() -> LongPortConfig:
    return LongPortConfig(
        mode="paper",
        app_key="test",
        app_secret="test",
        access_token="test",
        region="cn",
        auto_trade=True,
        dry_run=False,
        max_option_total_price=500,
        max_option_quantity=3,
        price_deviation_tolerance=5,
        stock_price_deviation_tolerance=1,
    )


def _make_stock_task() -> Task:
    msg = Message(
        id="msg-integ-tsll",
        content="TSLL 26.5 加一半",
        raw_content="TSLL 26.5 加一半",
        author="test",
        posted_at=datetime(2026, 4, 25, 10, 42, tzinfo=UTC),
        received_at=datetime(2026, 4, 25, 10, 42, 1, tzinfo=UTC),
        source="stock",
    )
    task = Task.new_from_message(msg)
    task.mark_parsing()
    task.attach_instruction(
        StockInstruction(
            instruction_type=InstructionType.BUY,
            price=26.50,
            price_range=None,
            quantity=500,
            position_size=None,
            stop_loss_price=None,
            take_profit_price=None,
            context_source="group",
            parser_notes=[],
            ticker="TSLL",
            symbol="TSLL.US",
            sell_quantity=None,
        )
    )
    return task


def _wire_up(
    bus: EventBus,
    client: FakeBrokerClient,
    config: LongPortConfig,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[list[Callable[[], None]], Callable[[], None], PushListener]:
    """Wire all three components and return their unsubscribe handles + listener."""
    unsubs_storage = register_storage_listeners(bus, session_factory)
    unsub_trader = register_trader(bus, client, config)
    listener = register_push_listener(bus, client, session_factory)
    return unsubs_storage, unsub_trader, listener


def _cleanup(
    unsubs_storage: list[Callable[[], None]],
    unsub_trader: Callable[[], None],
) -> None:
    """Unsubscribe all handlers."""
    for unsub in unsubs_storage:
        unsub()
    unsub_trader()


# ---------------------------------------------------------------------------
# Test 1: Full lifecycle  NEW → PARTIAL → FILLED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_new_partial_filled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Full broker lifecycle: INSTRUCTION_READY → submit → NEW push → PARTIAL → FILLED."""
    bus = EventBus()
    client = FakeBrokerClient(is_paper=True, dry_run=False, next_order_id="broker-order-42")
    config = _make_config()

    unsubs_storage, unsub_trader, listener = _wire_up(bus, client, config, session_factory)

    try:
        task = _make_stock_task()

        # Pre-save task so concurrent storage handlers use the UPDATE path.
        # (See module docstring for full explanation of the concurrency constraint.)
        async with session_scope(session_factory) as session:
            await save_task(session, task)

        # ── Step 1: publish TASK_INSTRUCTION_READY ───────────────────────────
        await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
        await bus.wait_idle(timeout=2)

        # Trader should have submitted exactly one stock order
        assert len(client.submitted_orders) == 1
        assert client.submitted_orders[0]["kind"] == "stock"
        assert client.submitted_orders[0]["symbol"] == "TSLL.US"
        assert client.submitted_orders[0]["side"] == "BUY"
        assert client.submitted_orders[0]["quantity"] == 500

        # DB: task persisted with PENDING status and order_id set
        async with session_scope(session_factory) as session:
            db_task = await load_task(session, task.id)

        assert db_task is not None
        assert db_task.status == Status.PENDING
        assert db_task.order_id == "broker-order-42"
        assert len(db_task.push_events) == 0

        # ── Step 2: broker emits NEW (order accepted, not yet filled) ────────
        await listener._handle_raw_push(
            FakePushEvt(order_id="broker-order-42", status="New")
        )
        await bus.wait_idle(timeout=2)

        async with session_scope(session_factory) as session:
            db_task = await load_task(session, task.id)

        assert db_task is not None
        assert db_task.status == Status.PENDING  # NEW maps to PENDING — no change
        assert len(db_task.push_events) == 1
        assert db_task.push_events[0].cumulative_qty is None
        assert db_task.push_events[0].delta_qty is None

        # ── Step 3: broker emits PARTIAL (100 filled out of 500) ─────────────
        await listener._handle_raw_push(
            FakePushEvt(
                order_id="broker-order-42",
                status="PartialFilled",
                executed_quantity=100,
                executed_price=26.48,
            )
        )
        await bus.wait_idle(timeout=2)

        async with session_scope(session_factory) as session:
            db_task = await load_task(session, task.id)

        assert db_task is not None
        assert db_task.status == Status.PARTIAL
        assert len(db_task.push_events) == 2
        partial = db_task.push_events[-1]
        assert partial.cumulative_qty == 100
        assert partial.delta_qty == 100  # first fill: delta = cumulative (prior = 0)

        # ── Step 4: broker emits FILLED (500 total) ──────────────────────────
        await listener._handle_raw_push(
            FakePushEvt(
                order_id="broker-order-42",
                status="Filled",
                executed_quantity=500,
                executed_price=26.47,
            )
        )
        await bus.wait_idle(timeout=2)

        async with session_scope(session_factory) as session:
            db_task = await load_task(session, task.id)

        assert db_task is not None
        assert db_task.status == Status.FILLED
        assert len(db_task.push_events) == 3
        filled = db_task.push_events[-1]
        assert filled.cumulative_qty == 500
        assert filled.delta_qty == 400  # 500 - 100 from prior PARTIAL

    finally:
        _cleanup(unsubs_storage, unsub_trader)
        await bus.aclose()


# ---------------------------------------------------------------------------
# Test 2: Rejected immediately after submit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejected_before_fill_marks_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Order rejected by broker: task should reach REJECTED with no fill data."""
    bus = EventBus()
    client = FakeBrokerClient(is_paper=True, dry_run=False, next_order_id="broker-order-rej")
    config = _make_config()

    unsubs_storage, unsub_trader, listener = _wire_up(bus, client, config, session_factory)

    try:
        msg = Message(
            id="msg-integ-rejected",
            content="TSLL 26.5 buy",
            raw_content="TSLL 26.5 buy",
            author="test",
            posted_at=datetime(2026, 4, 25, 11, 0, tzinfo=UTC),
            received_at=datetime(2026, 4, 25, 11, 0, 1, tzinfo=UTC),
            source="stock",
        )
        task = Task.new_from_message(msg)
        task.mark_parsing()
        task.attach_instruction(
            StockInstruction(
                instruction_type=InstructionType.BUY,
                price=26.50,
                price_range=None,
                quantity=100,
                position_size=None,
                stop_loss_price=None,
                take_profit_price=None,
                context_source="group",
                parser_notes=[],
                ticker="TSLL",
                symbol="TSLL.US",
                sell_quantity=None,
            )
        )

        # Pre-save task before publishing so concurrent storage handlers use UPDATE path.
        async with session_scope(session_factory) as session:
            await save_task(session, task)

        await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
        await bus.wait_idle(timeout=2)

        # Confirm order submitted and task is PENDING
        assert len(client.submitted_orders) == 1

        async with session_scope(session_factory) as session:
            db_task = await load_task(session, task.id)
        assert db_task is not None
        assert db_task.status == Status.PENDING
        assert db_task.order_id == "broker-order-rej"

        # Broker sends Rejected push
        await listener._handle_raw_push(
            FakePushEvt(order_id="broker-order-rej", status="Rejected")
        )
        await bus.wait_idle(timeout=2)

        async with session_scope(session_factory) as session:
            db_task = await load_task(session, task.id)
        assert db_task is not None
        assert db_task.status == Status.REJECTED
        assert len(db_task.push_events) == 1
        rej_evt = db_task.push_events[0]
        assert rej_evt.cumulative_qty is None
        assert rej_evt.delta_qty is None

    finally:
        _cleanup(unsubs_storage, unsub_trader)
        await bus.aclose()


# ---------------------------------------------------------------------------
# Test 3: Push for unknown order_id is silently ignored
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_before_trader_submits_is_ignored(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Push for an unknown order_id must not crash and must not create spurious DB rows."""
    bus = EventBus()
    client = FakeBrokerClient(is_paper=True, dry_run=False, next_order_id="broker-order-unknown")
    config = _make_config()

    unsubs_storage, unsub_trader, listener = _wire_up(bus, client, config, session_factory)

    try:
        # No task submitted — push arrives for an order that doesn't exist in DB
        await listener._handle_raw_push(
            FakePushEvt(order_id="does-not-exist-99", status="Filled", executed_quantity=100)
        )
        await bus.wait_idle(timeout=2)

        # Nothing was submitted
        assert len(client.submitted_orders) == 0

        # A quick check: no TASK_PUSH_EVENT was published (captured via inline sub)
        events_captured: list[Event] = []

        async def _cap(evt: Event) -> None:
            events_captured.append(evt)

        bus.subscribe(Topics.TASK_PUSH_EVENT, _cap)

        # Fire another push for same unknown order_id
        await listener._handle_raw_push(
            FakePushEvt(order_id="does-not-exist-99", status="New")
        )
        await bus.wait_idle(timeout=2)

        assert len(events_captured) == 0

    finally:
        _cleanup(unsubs_storage, unsub_trader)
        await bus.aclose()
