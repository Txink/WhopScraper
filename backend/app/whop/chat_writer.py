"""Event subscriber that persists chat messages to the ``chat_messages`` table.

Mirrors :func:`app.storage.listeners.register_storage_listeners` in shape:
takes the bus + async session factory, returns a list of unsubscribe
callables, registers an async handler for ``Topics.CHAT_MESSAGE_RECEIVED``.

The handler:
- Builds a :class:`ChatMessageRow` from the incoming :class:`Message`,
  denormalizing the optional ``quoted`` nested message into the
  ``quoted_*`` columns so a row renders correctly even when the quoted
  message is not present in the local DB.
- Persists via :func:`repo.upsert_chat_message` (which is idempotent on
  primary-key conflict — duplicate ids are a no-op).
- For non-historical (live) messages only, broadcasts a follow-up
  ``Topics.CHAT_MESSAGE_STORED`` event so the WS bridge can push the new
  row to the frontend ChatBoardPanel. Historical replay (e.g., scrollback
  on listener startup) is intentionally NOT broadcast — it would flood
  the frontend with messages the user has already seen.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import Event, EventBus
from app.core.events import (
    ChatMessagePayload,
    ChatMessageStoredPayload,
    Topics,
)
from app.domain.message import Message
from app.storage import repo
from app.storage.db import session_scope
from app.storage.schema import ChatMessageRow


def _row_from_message(page_id: str, msg: Message) -> ChatMessageRow:
    """Build a ``ChatMessageRow`` from a domain :class:`Message`.

    Denormalizes the optional ``quoted`` nested message into the
    ``quoted_*`` columns. ``msg.author`` may be ``None`` in the domain
    model (Whop occasionally drops the author field on system messages),
    but the column is NOT NULL — coerce to "" so the upsert always
    succeeds.
    """
    q = msg.quoted
    return ChatMessageRow(
        id=msg.id,
        page_id=page_id,
        author=msg.author or "",
        content=msg.content,
        raw_content=msg.raw_content,
        posted_at=msg.posted_at,
        received_at=msg.received_at,
        url=msg.url,
        quoted_message_id=q.id if q else None,
        quoted_author=q.author if q else None,
        quoted_content=q.content if q else None,
        quoted_posted_at=q.posted_at if q else None,
    )


def register_chat_writer(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Callable[[], None]]:
    """Subscribe the chat-writer handler to *bus*.

    Returns a list of unsubscribe callables; call each to detach the
    handler. Matches the shape of
    :func:`app.storage.listeners.register_storage_listeners`.
    """

    async def _handler(event: Event) -> None:
        payload: ChatMessagePayload = event.payload  # pyright: ignore[reportAssignmentType]
        row = _row_from_message(payload.page_id, payload.message)
        async with session_scope(session_factory) as session:
            await repo.upsert_chat_message(session, row)
        if not payload.is_historical:
            await bus.publish(
                Event(
                    topic=Topics.CHAT_MESSAGE_STORED,
                    payload=ChatMessageStoredPayload(
                        page_id=payload.page_id,
                        message_id=row.id,
                    ),
                )
            )

    _handler.__name__ = f"_chat_writer_handler[{session_factory!r}]"
    return [bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, _handler)]
