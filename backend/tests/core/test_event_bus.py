"""Tests for core/event_bus.py — asyncio pub/sub with fan-out + failure isolation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.event_bus import Event, EventBus


@pytest.mark.asyncio
async def test_subscribe_and_publish_calls_handler() -> None:
    bus = EventBus()
    called: list[Event] = []

    async def handler(evt: Event) -> None:
        called.append(evt)

    bus.subscribe("topic.a", handler)
    await bus.publish(Event(topic="topic.a", payload={"x": 1}))
    await bus.wait_idle(timeout=1)

    assert len(called) == 1
    assert called[0].topic == "topic.a"
    assert called[0].payload == {"x": 1}


@pytest.mark.asyncio
async def test_multiple_subscribers_same_topic_all_called() -> None:
    bus = EventBus()
    h1 = AsyncMock()
    h2 = AsyncMock()
    h3 = AsyncMock()
    bus.subscribe("topic.a", h1)
    bus.subscribe("topic.a", h2)
    bus.subscribe("topic.a", h3)

    await bus.publish(Event(topic="topic.a", payload=None))
    await bus.wait_idle(timeout=1)

    assert h1.call_count == 1
    assert h2.call_count == 1
    assert h3.call_count == 1


@pytest.mark.asyncio
async def test_subscribers_isolated_by_topic() -> None:
    bus = EventBus()
    on_a = AsyncMock()
    on_b = AsyncMock()
    bus.subscribe("topic.a", on_a)
    bus.subscribe("topic.b", on_b)

    await bus.publish(Event(topic="topic.a", payload=None))
    await bus.wait_idle(timeout=1)

    assert on_a.call_count == 1
    assert on_b.call_count == 0


@pytest.mark.asyncio
async def test_unsubscribe_stops_further_delivery() -> None:
    bus = EventBus()
    handler = AsyncMock()
    unsub = bus.subscribe("topic.a", handler)

    await bus.publish(Event(topic="topic.a", payload=None))
    await bus.wait_idle(timeout=1)
    assert handler.call_count == 1

    unsub()
    await bus.publish(Event(topic="topic.a", payload=None))
    await bus.wait_idle(timeout=1)
    assert handler.call_count == 1  # unchanged


@pytest.mark.asyncio
async def test_unsubscribe_is_idempotent() -> None:
    bus = EventBus()

    async def handler(_evt: Event) -> None:
        pass

    unsub = bus.subscribe("topic.a", handler)
    unsub()
    unsub()  # must not raise


@pytest.mark.asyncio
async def test_handler_raising_does_not_affect_others() -> None:
    bus = EventBus()
    good = AsyncMock()

    async def bad(_evt: Event) -> None:
        raise RuntimeError("handler failed")

    bus.subscribe("topic.a", bad)
    bus.subscribe("topic.a", good)

    await bus.publish(Event(topic="topic.a", payload=None))
    await bus.wait_idle(timeout=1)

    assert good.call_count == 1  # good handler still ran


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_is_noop() -> None:
    bus = EventBus()
    await bus.publish(Event(topic="nobody.here", payload=None))
    await bus.wait_idle(timeout=1)  # should complete without error


@pytest.mark.asyncio
async def test_handlers_run_concurrently_not_serially() -> None:
    bus = EventBus()
    start_order: list[str] = []

    async def slow(evt: Event) -> None:
        start_order.append("slow-start")
        await asyncio.sleep(0.05)
        start_order.append("slow-end")

    async def fast(evt: Event) -> None:
        start_order.append("fast")

    bus.subscribe("topic.a", slow)
    bus.subscribe("topic.a", fast)

    await bus.publish(Event(topic="topic.a", payload=None))
    await bus.wait_idle(timeout=1)

    # fast should start AND finish before slow finishes
    assert start_order[0] == "slow-start"
    assert start_order[1] == "fast"
    assert start_order[2] == "slow-end"


@pytest.mark.asyncio
async def test_aclose_cancels_in_flight_tasks() -> None:
    bus = EventBus()
    cancelled = False

    async def slow(_evt: Event) -> None:
        nonlocal cancelled
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled = True
            raise

    bus.subscribe("topic.a", slow)
    await bus.publish(Event(topic="topic.a", payload=None))
    # give the task a tick to start
    await asyncio.sleep(0.01)
    await bus.aclose()
    assert cancelled is True
