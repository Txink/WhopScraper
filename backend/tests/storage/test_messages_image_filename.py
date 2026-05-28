from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.message import Message
from app.domain.task import Task
from app.storage.db import session_scope
from app.storage.repo import load_task, save_task

_NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)


async def test_image_filename_round_trips(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    msg = Message(
        id="img_msg_1",
        content="",
        raw_content="",
        author="trader",
        posted_at=_NOW,
        received_at=_NOW,
        source="stock",
        image_url="https://whop.com/x.png",
        image_filename="img_msg_1.png",
    )
    task = Task.new_from_message(msg)
    task.mark_parsing()
    task.mark_skipped("图片消息")

    async with session_scope(session_factory) as session:
        await save_task(session, task)

    async with session_scope(session_factory) as session:
        loaded = await load_task(session, "img_msg_1")

    assert loaded is not None
    assert loaded.message.image_filename == "img_msg_1.png"
