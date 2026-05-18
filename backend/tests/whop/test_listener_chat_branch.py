"""Tests for the listener's source-branching publish helper.

Verifies that ``_publish_message`` dispatches to the right topic based on
``source``:
- ``source == "chat"`` → ``Topics.CHAT_MESSAGE_RECEIVED`` with a
  ``ChatMessagePayload`` carrying ``page_id`` + ``message`` +
  ``is_historical``.
- everything else (``"stock"`` / ``"option"``) → ``Topics.MESSAGE_RECEIVED``
  with the legacy ``MessagePayload`` shape (unchanged so the existing task
  pipeline keeps working).

The bus is async fire-and-forget — every ``await bus.publish(...)`` is
followed by ``await bus.wait_idle(...)`` so handlers have run before the
assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.event_bus import Event, EventBus
from app.core.events import (
    ChatMessagePayload,
    MessagePayload,
    Topics,
)
from app.domain.message import Message
from app.whop.listener import _publish_message


def _msg(source: str = "chat") -> Message:
    return Message(
        id="m1",
        content="hi",
        raw_content="hi",
        author="alice",
        posted_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        received_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        source=source,  # type: ignore[arg-type]
        url="https://whop.example/p1",
        quoted=None,
        history_hint=[],
    )


async def test_publish_message_routes_chat_source_to_chat_topic() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def _capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, _capture)
    bus.subscribe(Topics.MESSAGE_RECEIVED, _capture)

    await _publish_message(
        bus,
        page_id="p1",
        source="chat",
        message=_msg("chat"),
        is_historical=False,
    )
    await bus.wait_idle(timeout=1)

    assert len(seen) == 1
    assert seen[0].topic == Topics.CHAT_MESSAGE_RECEIVED
    payload = seen[0].payload
    assert isinstance(payload, ChatMessagePayload)
    assert payload.page_id == "p1"
    assert payload.message.id == "m1"
    assert payload.is_historical is False


async def test_publish_message_routes_stock_source_to_legacy_topic() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def _capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(Topics.MESSAGE_RECEIVED, _capture)
    bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, _capture)

    await _publish_message(
        bus,
        page_id="p2",
        source="stock",
        message=_msg("stock"),
        is_historical=False,
    )
    await bus.wait_idle(timeout=1)

    assert len(seen) == 1
    assert seen[0].topic == Topics.MESSAGE_RECEIVED
    payload = seen[0].payload
    assert isinstance(payload, MessagePayload)
    assert payload.message.id == "m1"
    assert payload.is_historical is False


async def test_publish_message_routes_option_source_to_legacy_topic() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def _capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(Topics.MESSAGE_RECEIVED, _capture)
    bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, _capture)

    await _publish_message(
        bus,
        page_id="p3",
        source="option",
        message=_msg("option"),
        is_historical=False,
    )
    await bus.wait_idle(timeout=1)

    assert len(seen) == 1
    assert seen[0].topic == Topics.MESSAGE_RECEIVED


async def test_publish_message_propagates_is_historical_for_chat() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def _capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, _capture)

    await _publish_message(
        bus,
        page_id="p1",
        source="chat",
        message=_msg("chat"),
        is_historical=True,
    )
    await bus.wait_idle(timeout=1)

    assert len(seen) == 1
    payload = seen[0].payload
    assert isinstance(payload, ChatMessagePayload)
    assert payload.is_historical is True


async def test_publish_message_raises_when_chat_missing_page_id() -> None:
    """The helper's ValueError guards against accidentally writing chat rows
    with NULL page_id — chat_messages.page_id is NOT NULL and the soft-FK
    semantics rely on it being a real WhopPageEntry.id.
    """
    bus = EventBus()
    with pytest.raises(ValueError):
        await _publish_message(
            bus,
            page_id=None,
            source="chat",
            message=_msg("chat"),
            is_historical=False,
        )
