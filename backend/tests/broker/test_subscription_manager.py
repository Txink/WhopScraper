"""Tests for SubscriptionManager — unified broker push dispatch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.broker.subscription_manager import (
    SubscriptionManager,
    _normalize_execution,
)
from tests.broker._fakes import FakeBrokerClient


@pytest.fixture()
def broker() -> FakeBrokerClient:
    return FakeBrokerClient()


def _push_order(
    *,
    order_id: str = "o-1",
    status: str = "Filled",
    symbol: str = "TSLA.US",
    side: str = "OrderSide.Buy",
    qty: int = 10,
    price: float = 245.5,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    """Build a PushOrderChanged-shaped stub. ``status`` and ``side`` are
    stringified the same way the SDK enums serialise — the normalizer
    splits on '.' and lowercases."""
    return SimpleNamespace(
        order_id=order_id,
        status=SimpleNamespace(__str__=lambda self: f"OrderStatus.{status}"),
        symbol=symbol,
        side=SimpleNamespace(__str__=lambda self: side),
        executed_quantity=qty,
        executed_price=price,
        updated_at=updated_at or datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )


# Because SimpleNamespace doesn't honor __str__ via dunder lookup, build a
# class-level helper instead.
class _Enum:
    def __init__(self, name: str) -> None:
        self._name = name

    def __str__(self) -> str:
        return self._name


def _push(
    *,
    order_id: str = "o-1",
    status: str = "Filled",
    symbol: str = "TSLA.US",
    side: str = "OrderSide.Buy",
    qty: int = 10,
    price: float = 245.5,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        order_id=order_id,
        status=_Enum(f"OrderStatus.{status}"),
        symbol=symbol,
        side=_Enum(side),
        executed_quantity=qty,
        executed_price=price,
        updated_at=updated_at or datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )


# --- normalizer ----------------------------------------------------------


def test_normalize_filled_stock() -> None:
    d = _normalize_execution(_push())
    assert d is not None
    assert d["order_id"] == "o-1"
    assert d["symbol"] == "TSLA.US"
    assert d["ticker"] == "TSLA"
    assert d["side"] == "BUY"
    assert d["qty"] == 10
    assert d["price"] == 245.5
    assert d["ts"] == "2026-05-15T12:00:00+00:00"


def test_normalize_filled_option_uses_underlying_ticker() -> None:
    d = _normalize_execution(_push(symbol="HOOD260618C100000.US", side="OrderSide.Sell"))
    assert d is not None
    assert d["ticker"] == "HOOD"
    assert d["side"] == "SELL"


def test_normalize_drops_non_fill_status() -> None:
    for s in ("New", "NotReported", "Canceled", "Rejected", "WaitToNew"):
        assert _normalize_execution(_push(status=s)) is None


def test_normalize_drops_zero_qty() -> None:
    assert _normalize_execution(_push(qty=0)) is None


# --- listener fan-out -----------------------------------------------------


async def test_attach_installs_both_push_slots(broker: FakeBrokerClient) -> None:
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    assert getattr(broker, "quote_handler", None) is None
    assert broker.push_handlers == []
    mgr.attach()
    assert callable(broker.quote_handler)
    assert len(broker.push_handlers) == 1


async def test_quote_listener_invoked_only_for_watched_symbols(broker: FakeBrokerClient) -> None:
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()
    await mgr.watch_quotes(["TSLA.US"])

    captured: list[tuple[str, dict]] = []
    mgr.add_quote_listener(lambda s, q: captured.append((s, q)))

    # Watched — should fan out.
    broker.emit_quote("TSLA.US", {"last_done": 250.0})
    # Unwatched — should be dropped.
    broker.emit_quote("AAPL.US", {"last_done": 180.0})

    assert captured == [("TSLA.US", {"last_done": 250.0})]


async def test_multiple_quote_listeners_all_invoked(broker: FakeBrokerClient) -> None:
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()
    await mgr.watch_quotes(["TSLA.US"])

    a: list[str] = []
    b: list[str] = []
    mgr.add_quote_listener(lambda s, _q: a.append(s))
    mgr.add_quote_listener(lambda s, _q: b.append(s))

    broker.emit_quote("TSLA.US", {"last_done": 250.0})
    assert a == ["TSLA.US"]
    assert b == ["TSLA.US"]


async def test_unsubscribe_handle_removes_listener(broker: FakeBrokerClient) -> None:
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()
    await mgr.watch_quotes(["TSLA.US"])

    captured: list[str] = []
    unsub = mgr.add_quote_listener(lambda s, _q: captured.append(s))
    broker.emit_quote("TSLA.US", {"last_done": 250.0})
    unsub()
    broker.emit_quote("TSLA.US", {"last_done": 251.0})
    assert captured == ["TSLA.US"]  # only the first one


async def test_execution_listener_filters_non_fills(broker: FakeBrokerClient) -> None:
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()

    captured: list[dict] = []
    mgr.add_execution_listener(lambda d: captured.append(d))

    # Fills — should land.
    broker.emit_push(_push(order_id="o-1", status="Filled", qty=10))
    broker.emit_push(_push(order_id="o-2", status="PartialFilled", qty=5))
    # Non-fills — should be dropped.
    broker.emit_push(_push(order_id="o-3", status="New", qty=10))
    broker.emit_push(_push(order_id="o-4", status="Canceled", qty=10))

    assert [d["order_id"] for d in captured] == ["o-1", "o-2"]


async def test_watch_quotes_diffs_subscribe_unsubscribe(broker: FakeBrokerClient) -> None:
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()

    r = await mgr.watch_quotes(["TSLA.US", "AAPL.US"])
    assert r == {"added": 2, "removed": 0, "total": 2}
    assert broker.subscribed_quote_symbols == {"TSLA.US", "AAPL.US"}

    r = await mgr.watch_quotes(["TSLA.US", "NVDA.US"])
    assert r == {"added": 1, "removed": 1, "total": 2}
    assert broker.subscribed_quote_symbols == {"TSLA.US", "NVDA.US"}

    r = await mgr.watch_quotes([])
    assert r == {"added": 0, "removed": 2, "total": 0}
    assert broker.subscribed_quote_symbols == set()


async def test_detach_unsubscribes_all_watched(broker: FakeBrokerClient) -> None:
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()
    await mgr.watch_quotes(["TSLA.US", "AAPL.US"])
    assert broker.subscribed_quote_symbols == {"TSLA.US", "AAPL.US"}
    mgr.detach()
    assert broker.subscribed_quote_symbols == set()
    assert mgr.watched_symbols == set()


async def test_set_symbols_per_owner_unions_across_owners(
    broker: FakeBrokerClient,
) -> None:
    """Two owners can declare independent symbol sets; the SDK sees
    the union. Replacing one owner's set never strips a symbol another
    owner still wants."""
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()

    # Positions wants TSLA + AAPL.
    r = await mgr.set_symbols_for_owner("positions", ["TSLA.US", "AAPL.US"])
    assert r == {"added": 2, "removed": 0, "total": 2}
    assert broker.subscribed_quote_symbols == {"TSLA.US", "AAPL.US"}

    # Alerts wants AAPL (already subscribed) + NVDA (new). Only NVDA
    # actually hits the SDK; AAPL is reused via the union.
    r = await mgr.set_symbols_for_owner("alerts", ["AAPL.US", "NVDA.US"])
    assert r == {"added": 1, "removed": 0, "total": 3}
    assert broker.subscribed_quote_symbols == {"TSLA.US", "AAPL.US", "NVDA.US"}

    # Positions narrows to just TSLA. AAPL stays subscribed (alerts
    # still wants it); only the positions-only symbols leave.
    r = await mgr.set_symbols_for_owner("positions", ["TSLA.US"])
    assert r == {"added": 0, "removed": 0, "total": 3}
    assert broker.subscribed_quote_symbols == {"TSLA.US", "AAPL.US", "NVDA.US"}

    # Alerts drops AAPL — now nothing wants it; it unsubscribes.
    r = await mgr.set_symbols_for_owner("alerts", ["NVDA.US"])
    assert r == {"added": 0, "removed": 1, "total": 2}
    assert broker.subscribed_quote_symbols == {"TSLA.US", "NVDA.US"}


async def test_dispatch_quote_unions_across_owners(broker: FakeBrokerClient) -> None:
    """The dispatch filter uses the union — a symbol any owner watches
    gets pushed to all listeners.

    Regression guard for the bug where the broker's single ``set_on_quote``
    slot was being clobbered by a second registrar (AlertEngine), making
    SubscriptionManager's bus publisher invisible. Listeners registered
    via ``add_quote_listener`` must always see pushes for any union-watched
    symbol, regardless of which owner contributed it.
    """
    loop = asyncio.get_running_loop()
    mgr = SubscriptionManager(broker, loop)
    mgr.attach()
    await mgr.set_symbols_for_owner("positions", ["TSLA.US"])
    await mgr.set_symbols_for_owner("alerts", ["AAPL.US"])

    a: list[str] = []
    b: list[str] = []
    mgr.add_quote_listener(lambda s, _q: a.append(s))
    mgr.add_quote_listener(lambda s, _q: b.append(s))

    broker.emit_quote("TSLA.US", {"last_done": 250.0})
    broker.emit_quote("AAPL.US", {"last_done": 180.0})
    broker.emit_quote("ZZZZ.US", {"last_done": 1.0})  # unwatched — dropped

    assert a == ["TSLA.US", "AAPL.US"]
    assert b == ["TSLA.US", "AAPL.US"]
