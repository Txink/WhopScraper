"""Event subscriber that persists chat messages to the ``chat_messages`` table.

Mirrors :func:`app.storage.listeners.register_storage_listeners` in shape:
takes the bus + async session factory, returns a list of unsubscribe
callables, registers an async handler for ``Topics.CHAT_MESSAGE_RECEIVED``.

The handler:
- Builds a :class:`ChatMessageRow` from the incoming :class:`Message`,
  denormalizing the optional ``quoted`` nested message into the
  ``quoted_*`` columns so a row renders correctly even when the quoted
  message is not present in the local DB.
- If the message carries an ``image_url``, downloads it to
  ``data_dir/chat-images/<msg_id>.<ext>`` and records the filename.
- Persists via :func:`repo.upsert_chat_message` (which is idempotent on
  primary-key conflict — duplicate ids are a no-op).
- For non-historical (live) messages only, broadcasts a follow-up
  ``Topics.CHAT_MESSAGE_STORED`` event so the WS bridge can push the new
  row to the frontend ChatBoardPanel. Historical replay (e.g., scrollback
  on listener startup) is intentionally NOT broadcast — it would flood
  the frontend with messages the user has already seen.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

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
from app.whop.image_store import download_image

_log = logging.getLogger(__name__)


def _row_from_message(
    page_id: str, msg: Message, image_filename: str | None
) -> ChatMessageRow:
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
        image_filename=image_filename,
    )


def register_chat_writer(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    data_dir: Path,
) -> list[Callable[[], None]]:
    """Subscribe the chat-writer handler to *bus*.

    Parameters
    ----------
    bus:
        The application event bus.
    session_factory:
        Async SQLAlchemy session factory.
    data_dir:
        Root data directory; images are saved under ``<data_dir>/chat-images/``.

    Returns a list of unsubscribe callables; call each to detach the
    handler. Matches the shape of
    :func:`app.storage.listeners.register_storage_listeners`.
    """

    async def _handler(event: Event) -> None:
        payload: ChatMessagePayload = event.payload  # pyright: ignore[reportAssignmentType]
        msg = payload.message

        image_filename: str | None = None
        if msg.image_url:
            image_filename = await download_image(msg.id, msg.image_url, data_dir)

        # Skip rows that have neither text content nor a successfully
        # downloaded image (covers the rare case where extraction caught
        # an image_url but the download failed AND content was empty).
        #
        # Note: for image-only messages where the first scrape's download
        # fails, the row is never written. ``upsert_chat_message`` is
        # idempotent on conflict, so a later re-scrape that succeeds will
        # write the row — but if the same id is seen again with another
        # failed download, it stays absent. In practice the live extractor
        # rarely re-emits the same id; this is the spec's accepted
        # tradeoff (image-only + cold-cache + expired URL = permanently
        # lost). Text-bearing messages are always written.
        if not msg.content and image_filename is None:
            return

        row = _row_from_message(payload.page_id, msg, image_filename)
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
