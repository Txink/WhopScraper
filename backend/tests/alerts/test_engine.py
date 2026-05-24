"""AlertEngine — subscription management, evaluation, cooldown, oneshot."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.alerts.engine import AlertEngine
from app.alerts.schemas import AlertCreate
from app.core.event_bus import EventBus
from app.core.events import Topics


class FakeBroker:
    def __init__(self) -> None:
        self.subscribed: set[str] = set()
        self._cb = None
        self.is_paper = True

    def is_noop(self) -> bool:
        return False

    def subscribe_quotes(self, symbols):
        self.subscribed.update(symbols)

    def unsubscribe_quotes(self, symbols):
        self.subscribed.difference_update(symbols)

    def set_on_quote(self, cb):
        self._cb = cb

    def fire_quote(self, symbol, payload):
        assert self._cb is not None
        self._cb(symbol, payload)


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
async def test_start_subscribes_enabled_symbols(repo, broker, bus):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    engine = AlertEngine(repo=repo, broker=broker, event_bus=bus)
    await engine.start()
    assert broker.subscribed == {"AAPL.US"}


@pytest.mark.asyncio
async def test_create_then_change_extends_subscription(repo, broker, bus):
    engine = AlertEngine(repo=repo, broker=broker, event_bus=bus)
    await engine.start()
    a = await repo.create(AlertCreate(
        ticker="NVDA", symbol="NVDA.US", condition_type="price",
        operator=">=", threshold=500.0,
    ))
    await engine.on_alert_changed("created", a)
    assert "NVDA.US" in broker.subscribed


@pytest.mark.asyncio
async def test_delete_releases_when_no_others(repo, broker, bus):
    a = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    engine = AlertEngine(repo=repo, broker=broker, event_bus=bus)
    await engine.start()
    await engine.on_alert_changed("deleted", a)
    assert broker.subscribed == set()


@pytest.mark.asyncio
async def test_quote_below_threshold_does_not_fire(repo, broker, bus):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    fires: list = []
    # NOTE: The exact pattern for subscribing to a Topic depends on this
    # project's EventBus. Use whichever signature exists — likely
    # bus.subscribe(Topics.ALERT_TRIGGERED, async_or_sync_handler)
    # or bus.subscribe(handler, topic=...). See how Task 3 tests subscribe
    # to Topics.ORDER_CHANGED in tests/orders/test_service.py for the pattern.
    async def handler(event):
        fires.append(event)
    bus.subscribe(Topics.ALERT_TRIGGERED, handler)
    engine = AlertEngine(repo=repo, broker=broker, event_bus=bus)
    await engine.start()
    broker.fire_quote("AAPL.US", {
        "last_done": 199.50, "open": 198.0, "prev_close": 198.5, "volume": 1_000_000,
        "timestamp": datetime.now(UTC),
    })
    await asyncio.sleep(0.05)
    await bus.wait_idle()
    assert fires == []


@pytest.mark.asyncio
async def test_quote_above_threshold_fires_and_disables_one_shot(repo, broker, bus):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0, repeat_mode="one_shot",
    ))
    fires: list = []
    async def handler(event):
        fires.append(event)
    bus.subscribe(Topics.ALERT_TRIGGERED, handler)
    engine = AlertEngine(repo=repo, broker=broker, event_bus=bus)
    await engine.start()
    broker.fire_quote("AAPL.US", {
        "last_done": 200.15, "open": 198.0, "prev_close": 198.5, "volume": 1_000_000,
        "timestamp": datetime.now(UTC),
    })
    await asyncio.sleep(0.05)
    await bus.wait_idle()
    assert len(fires) == 1
    updated = (await repo.list_by_ticker("AAPL"))[0]
    assert updated.enabled is False
    assert "AAPL.US" not in broker.subscribed


@pytest.mark.asyncio
async def test_recurring_cooldown_skips_within_window(repo, broker, bus):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
        repeat_mode="recurring", cooldown_seconds=60,
    ))
    fires: list = []
    async def handler(event):
        fires.append(event)
    bus.subscribe(Topics.ALERT_TRIGGERED, handler)
    engine = AlertEngine(repo=repo, broker=broker, event_bus=bus)
    await engine.start()
    quote = {
        "last_done": 200.10, "open": 198.0, "prev_close": 198.5, "volume": 1_000_000,
        "timestamp": datetime.now(UTC),
    }
    broker.fire_quote("AAPL.US", quote)
    await asyncio.sleep(0.05)
    broker.fire_quote("AAPL.US", quote)
    await asyncio.sleep(0.05)
    await bus.wait_idle()
    assert len(fires) == 1


@pytest.mark.asyncio
async def test_noop_broker_skips_subscription(repo, bus):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))

    class NoopFake:
        is_paper = True
        def is_noop(self): return True
        def subscribe_quotes(self, syms): raise AssertionError("should not subscribe")
        def unsubscribe_quotes(self, syms): pass
        def set_on_quote(self, cb): pass

    engine = AlertEngine(repo=repo, broker=NoopFake(), event_bus=bus)
    await engine.start()  # must not raise
