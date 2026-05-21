from __future__ import annotations

from datetime import datetime, timezone

UTC = timezone.utc

import pytest

from app.storage.db import session_scope
from app.storage.schema import ChatMessageRow


def _base_row(id_: str, **kwargs) -> ChatMessageRow:
    defaults = dict(
        page_id="page_1",
        author="alice",
        content="",
        raw_content="",
        posted_at=datetime(2026, 5, 21, tzinfo=UTC),
        received_at=datetime(2026, 5, 21, tzinfo=UTC),
        url=None,
        quoted_message_id=None,
        quoted_author=None,
        quoted_content=None,
        quoted_posted_at=None,
    )
    defaults.update(kwargs)
    return ChatMessageRow(id=id_, **defaults)


async def test_chat_message_row_persists_image_filename(session_factory) -> None:
    async with session_scope(session_factory) as s:
        row = _base_row("m_img_1", image_filename="m_img_1.avif")
        s.add(row)
        await s.flush()
        fetched = await s.get(ChatMessageRow, "m_img_1")
        assert fetched is not None
        assert fetched.image_filename == "m_img_1.avif"


async def test_chat_message_row_image_filename_defaults_to_none(session_factory) -> None:
    async with session_scope(session_factory) as s:
        row = _base_row("m_img_2")
        s.add(row)
        await s.flush()
        fetched = await s.get(ChatMessageRow, "m_img_2")
        assert fetched is not None
        assert fetched.image_filename is None
