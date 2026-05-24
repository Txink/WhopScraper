"""OrdersService — submit, replace, cancel, list paths against a fake broker."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import Event, EventBus
from app.core.events import Topics
from app.orders.schemas import ReplaceOrderRequest, SubmitOrderRequest
from app.orders.service import OrdersService
from app.storage.schema import TaskRow


class FakeBroker:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.replaced: list[dict] = []
        self.cancelled: list[str] = []
        self.next_order_id = "ord-1"
        self.is_paper = True
        self.dry_run = False
        self.account_id = "acct-1"

    def submit_stock_order(self, **kwargs):  # type: ignore[no-untyped-def]
        self.submitted.append(kwargs)
        return self.next_order_id

    def replace_order(
        self, order_id: str, *, quantity: int | None = None, price: float | None = None
    ) -> None:
        self.replaced.append({"order_id": order_id, "qty": quantity, "price": price})

    def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    def today_orders(self, *, ticker: str | None = None) -> list[dict]:
        return [{
            "order_id": "ord-1", "symbol": "AAPL.US", "ticker": "AAPL",
            "side": "Buy", "order_type": "LO", "price": 199.0, "quantity": 200,
            "executed_quantity": 0, "status": "NewStatus", "submitted_at": None,
        }]


@pytest.mark.asyncio
async def test_submit_creates_task_and_emits_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    received: list[dict] = []

    async def _handler(event: Event) -> None:
        received.append(event.payload)

    bus.subscribe(Topics.ORDER_CHANGED, _handler)
    svc = OrdersService(broker=FakeBroker(), event_bus=bus, session_factory=session_factory)
    req = SubmitOrderRequest(
        symbol="AAPL.US", side="BUY", qty=200, order_type="LIMIT", price=199.0,
    )
    out = await svc.submit(req)
    assert out.order_id == "ord-1"
    assert out.source == "manual"
    await bus.wait_idle()
    assert any(p["action"] == "created" for p in received)


@pytest.mark.asyncio
async def test_replace_calls_broker_and_updates_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    broker = FakeBroker()
    svc = OrdersService(broker=broker, event_bus=bus, session_factory=session_factory)
    await svc.submit(SubmitOrderRequest(
        symbol="AAPL.US", side="BUY", qty=200, order_type="LIMIT", price=199.0,
    ))
    await svc.replace("ord-1", ReplaceOrderRequest(price=199.5))
    assert broker.replaced == [{"order_id": "ord-1", "qty": None, "price": 199.5}]


@pytest.mark.asyncio
async def test_replace_requires_at_least_one_field(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    svc = OrdersService(broker=FakeBroker(), event_bus=EventBus(), session_factory=session_factory)
    with pytest.raises(ValueError, match="price or qty"):
        await svc.replace("ord-1", ReplaceOrderRequest())


@pytest.mark.asyncio
async def test_cancel_calls_broker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    broker = FakeBroker()
    svc = OrdersService(broker=broker, event_bus=EventBus(), session_factory=session_factory)
    await svc.cancel("ord-1")
    assert broker.cancelled == ["ord-1"]


@pytest.mark.asyncio
async def test_list_today_merges_broker_orders_with_manual_tasks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    broker = FakeBroker()
    svc = OrdersService(broker=broker, event_bus=EventBus(), session_factory=session_factory)
    await svc.submit(SubmitOrderRequest(
        symbol="AAPL.US", side="BUY", qty=200, order_type="LIMIT", price=199.0,
    ))
    rows = await svc.list_today("AAPL")
    assert len(rows) == 1
    # Same order_id from manual submit AND broker today_orders → single merged row,
    # source=manual takes precedence.
    assert rows[0].source == "manual"


@pytest.mark.asyncio
async def test_list_today_excludes_stale_manual_tasks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A manual task created 2 days ago must NOT appear in list_today."""
    broker = FakeBroker()
    # Use a broker that returns NO broker rows so we can isolate the DB filter.
    broker_no_orders = FakeBroker()
    broker_no_orders.today_orders = lambda *, ticker=None: []  # type: ignore[method-assign]

    svc = OrdersService(broker=broker_no_orders, event_bus=EventBus(), session_factory=session_factory)
    await svc.submit(SubmitOrderRequest(
        symbol="AAPL.US", side="BUY", qty=100, order_type="LIMIT", price=150.0,
    ))

    # Back-date the task's created_at to 2 days ago so it predates today's UTC midnight.
    two_days_ago = datetime.now(timezone.utc) - timedelta(days=2)
    async with session_factory() as session:
        stmt = select(TaskRow).where(TaskRow.source == "manual", TaskRow.ticker == "AAPL")
        task = (await session.execute(stmt)).scalar_one()
        task.created_at = two_days_ago
        await session.commit()

    rows = await svc.list_today("AAPL")
    assert rows == [], "stale manual task from 2 days ago should be filtered out"
