"""AlertEngine — subscription management, evaluation, cooldown, oneshot.

Engine wires quote pushes through the project-wide SubscriptionManager
(not directly to the broker), so a separate listener — e.g. the WS
publisher — can coexist on the same broker push stream.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from app.alerts.engine import AlertEngine
from app.alerts.schemas import AlertCreate
from app.broker.subscription_manager import SubscriptionManager
from app.core.event_bus import EventBus
from app.core.events import Topics
from tests.broker._fakes import FakeBrokerClient


@pytest.fixture
def broker() -> FakeBrokerClient:
    return FakeBrokerClient()


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def mgr(broker: FakeBrokerClient) -> SubscriptionManager:
    loop = asyncio.get_running_loop()
    m = SubscriptionManager(broker, loop)
    m.attach()
    return m


def _make_engine(
    repo, bus: EventBus, mgr: SubscriptionManager | None,
) -> AlertEngine:
    return AlertEngine(
        repo=repo,
        event_bus=bus,
        subscription_manager_getter=lambda: mgr,
    )


@pytest.mark.asyncio
async def test_start_subscribes_enabled_symbols(repo, broker, bus, mgr):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    engine = _make_engine(repo, bus, mgr)
    await engine.start()
    assert broker.subscribed_quote_symbols == {"AAPL.US"}


@pytest.mark.asyncio
async def test_create_then_change_extends_subscription(repo, broker, bus, mgr):
    engine = _make_engine(repo, bus, mgr)
    await engine.start()
    a = await repo.create(AlertCreate(
        ticker="NVDA", symbol="NVDA.US", condition_type="price",
        operator=">=", threshold=500.0,
    ))
    await engine.on_alert_changed("created", a)
    assert "NVDA.US" in broker.subscribed_quote_symbols


@pytest.mark.asyncio
async def test_delete_releases_when_no_others(repo, broker, bus, mgr):
    a = await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    engine = _make_engine(repo, bus, mgr)
    await engine.start()
    await engine.on_alert_changed("deleted", a)
    assert broker.subscribed_quote_symbols == set()


@pytest.mark.asyncio
async def test_quote_below_threshold_does_not_fire(repo, broker, bus, mgr):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    fires: list = []
    async def handler(event):
        fires.append(event)
    bus.subscribe(Topics.ALERT_TRIGGERED, handler)
    engine = _make_engine(repo, bus, mgr)
    await engine.start()
    broker.emit_quote("AAPL.US", {
        "last_done": 199.50, "open": 198.0, "prev_close": 198.5, "volume": 1_000_000,
        "timestamp": datetime.now(UTC),
    })
    await asyncio.sleep(0.05)
    await bus.wait_idle()
    assert fires == []


@pytest.mark.asyncio
async def test_quote_above_threshold_fires_and_disables_one_shot(repo, broker, bus, mgr):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0, repeat_mode="one_shot",
    ))
    fires: list = []
    async def handler(event):
        fires.append(event)
    bus.subscribe(Topics.ALERT_TRIGGERED, handler)
    engine = _make_engine(repo, bus, mgr)
    await engine.start()
    broker.emit_quote("AAPL.US", {
        "last_done": 200.15, "open": 198.0, "prev_close": 198.5, "volume": 1_000_000,
        "timestamp": datetime.now(UTC),
    })
    await asyncio.sleep(0.05)
    await bus.wait_idle()
    assert len(fires) == 1
    updated = (await repo.list_by_ticker("AAPL"))[0]
    assert updated.enabled is False
    assert "AAPL.US" not in broker.subscribed_quote_symbols


@pytest.mark.asyncio
async def test_recurring_cooldown_skips_within_window(repo, broker, bus, mgr):
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
        repeat_mode="recurring", cooldown_seconds=60,
    ))
    fires: list = []
    async def handler(event):
        fires.append(event)
    bus.subscribe(Topics.ALERT_TRIGGERED, handler)
    engine = _make_engine(repo, bus, mgr)
    await engine.start()
    quote = {
        "last_done": 200.10, "open": 198.0, "prev_close": 198.5, "volume": 1_000_000,
        "timestamp": datetime.now(UTC),
    }
    broker.emit_quote("AAPL.US", quote)
    await asyncio.sleep(0.05)
    broker.emit_quote("AAPL.US", quote)
    await asyncio.sleep(0.05)
    await bus.wait_idle()
    assert len(fires) == 1


@pytest.mark.asyncio
async def test_engine_without_manager_skips_quote_wiring(repo, bus):
    """When the SubscriptionManager isn't bound yet (early startup),
    AlertEngine.start() should be a no-op for quote wiring but still
    load enabled alerts into memory so later ``rebind`` can resync."""
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    engine = AlertEngine(
        repo=repo,
        event_bus=bus,
        subscription_manager_getter=lambda: None,
    )
    await engine.start()  # must not raise


@pytest.mark.asyncio
async def test_rebind_reattaches_to_new_manager(repo, broker, bus):
    """After broker reload the SubscriptionManager is replaced. rebind()
    must re-register the listener + symbol set on the new manager so
    alerts keep firing without an engine restart."""
    loop = asyncio.get_running_loop()
    mgr_v1 = SubscriptionManager(broker, loop)
    mgr_v1.attach()
    current = {"mgr": mgr_v1}

    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    engine = AlertEngine(
        repo=repo,
        event_bus=bus,
        subscription_manager_getter=lambda: current["mgr"],
    )
    await engine.start()
    assert broker.subscribed_quote_symbols == {"AAPL.US"}

    # Simulate broker reload — old manager detached, new one attached.
    mgr_v1.detach()
    broker_v2 = FakeBrokerClient()
    mgr_v2 = SubscriptionManager(broker_v2, loop)
    mgr_v2.attach()
    current["mgr"] = mgr_v2

    await engine.rebind()
    assert broker_v2.subscribed_quote_symbols == {"AAPL.US"}

    # Pushes on the new broker should now reach the alert evaluator.
    fires: list = []
    async def handler(event):
        fires.append(event)
    bus.subscribe(Topics.ALERT_TRIGGERED, handler)
    broker_v2.emit_quote("AAPL.US", {
        "last_done": 200.15, "open": 198.0, "prev_close": 198.5,
        "volume": 1_000_000, "timestamp": datetime.now(UTC),
    })
    await asyncio.sleep(0.05)
    await bus.wait_idle()
    assert len(fires) == 1


@pytest.mark.asyncio
async def test_engine_listener_coexists_with_other_listeners(repo, broker, bus, mgr):
    """The bug we're fixing: a second consumer of broker push (the
    WS publisher) must keep receiving pushes while AlertEngine is also
    bound. Both listeners see the same tick stream via the
    SubscriptionManager union."""
    await repo.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))

    bus_publisher_seen: list[str] = []
    mgr.add_quote_listener(lambda s, _q: bus_publisher_seen.append(s))

    engine = _make_engine(repo, bus, mgr)
    await engine.start()

    broker.emit_quote("AAPL.US", {
        "last_done": 199.50, "open": 198.0, "prev_close": 198.5,
        "volume": 1_000_000, "timestamp": datetime.now(UTC),
    })

    assert bus_publisher_seen == ["AAPL.US"]
