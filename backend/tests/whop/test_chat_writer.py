"""Tests for the ``chat_writer`` event subscriber.

Verifies the handler:
- Persists a basic chat message to the ``chat_messages`` table.
- Denormalizes the optional ``quoted`` nested message into ``quoted_*``
  columns.
- Skips broadcasting ``CHAT_MESSAGE_STORED`` when ``is_historical=True``.
- Broadcasts ``CHAT_MESSAGE_STORED`` for live (non-historical) messages.
- Is idempotent on duplicate ids (delegates to repo's ``ON CONFLICT DO
  NOTHING``).

Reuses the shared ``session_factory`` fixture from ``tests/conftest.py``.
The bus is async and fire-and-forget (publish() schedules tasks via
``asyncio.create_task``), so every ``await bus.publish(...)`` is followed
by ``await bus.wait_idle(...)`` to drain in-flight handler tasks before
assertions.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.event_bus import Event, EventBus
from app.core.events import (
    ChatMessagePayload,
    ChatMessageStoredPayload,
    Topics,
)
from app.domain.message import Message
from app.storage import repo
from app.storage.db import session_scope
from app.whop.chat_writer import register_chat_writer


def _msg(id_: str, author: str = "alice", quoted: Message | None = None) -> Message:
    return Message(
        id=id_,
        content=f"hi from {author}",
        raw_content=f"hi from {author}",
        author=author,
        posted_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        received_at=datetime(2026, 5, 18, 9, 0, tzinfo=UTC),
        source="chat",
        url="https://whop.example/p1",
        quoted=quoted,
        history_hint=[],
    )


async def test_chat_writer_persists_basic_message(session_factory) -> None:
    bus = EventBus()
    register_chat_writer(bus, session_factory)

    await bus.publish(Event(
        topic=Topics.CHAT_MESSAGE_RECEIVED,
        payload=ChatMessagePayload(page_id="p1", message=_msg("m1"), is_historical=False),
    ))
    await bus.wait_idle(timeout=1)

    async with session_scope(session_factory) as s:
        rows = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        assert [r.id for r in rows] == ["m1"]
        assert rows[0].quoted_author is None


async def test_chat_writer_denormalizes_quote(session_factory) -> None:
    bus = EventBus()
    register_chat_writer(bus, session_factory)

    quoted = _msg("m_quoted", author="bob")
    await bus.publish(Event(
        topic=Topics.CHAT_MESSAGE_RECEIVED,
        payload=ChatMessagePayload(page_id="p1", message=_msg("m1", quoted=quoted)),
    ))
    await bus.wait_idle(timeout=1)

    async with session_scope(session_factory) as s:
        rows = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        assert rows[0].quoted_author == "bob"
        assert rows[0].quoted_content == "hi from bob"
        assert rows[0].quoted_message_id == "m_quoted"


async def test_chat_writer_skips_broadcast_when_historical(session_factory) -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def _capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(Topics.CHAT_MESSAGE_STORED, _capture)
    register_chat_writer(bus, session_factory)

    await bus.publish(Event(
        topic=Topics.CHAT_MESSAGE_RECEIVED,
        payload=ChatMessagePayload(page_id="p1", message=_msg("m1"), is_historical=True),
    ))
    await bus.wait_idle(timeout=1)

    assert seen == []  # no STORED broadcast for historical replay


async def test_chat_writer_broadcasts_when_live(session_factory) -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def _capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(Topics.CHAT_MESSAGE_STORED, _capture)
    register_chat_writer(bus, session_factory)

    await bus.publish(Event(
        topic=Topics.CHAT_MESSAGE_RECEIVED,
        payload=ChatMessagePayload(page_id="p1", message=_msg("m1"), is_historical=False),
    ))
    await bus.wait_idle(timeout=1)

    assert len(seen) == 1
    payload: ChatMessageStoredPayload = seen[0].payload
    assert payload.page_id == "p1"
    assert payload.message_id == "m1"


async def test_chat_writer_idempotent_on_replay(session_factory) -> None:
    bus = EventBus()
    register_chat_writer(bus, session_factory)

    payload = ChatMessagePayload(page_id="p1", message=_msg("m1"))
    await bus.publish(Event(topic=Topics.CHAT_MESSAGE_RECEIVED, payload=payload))
    await bus.wait_idle(timeout=1)
    await bus.publish(Event(topic=Topics.CHAT_MESSAGE_RECEIVED, payload=payload))
    await bus.wait_idle(timeout=1)

    async with session_scope(session_factory) as s:
        rows = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        assert len(rows) == 1
