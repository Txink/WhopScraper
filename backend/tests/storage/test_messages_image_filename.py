from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.message import Message
from app.domain.task import Task
from app.storage.db import session_scope
from app.storage.repo import load_task, save_task

_NOW = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)


def dataclasses_replace_filename(msg, filename):
    return dataclasses.replace(msg, image_filename=filename)


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


async def test_image_filename_backfilled_on_resave(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """旧行:先以 image_filename=None 落库(模拟改动前的 PARSE_ERROR 图片消息),
    再以带 image_filename 的同 id 重存(模拟 restart 重抓)→ 回填成功。"""
    base = Message(
        id="bf_1", content="", raw_content="", author="t",
        posted_at=_NOW, received_at=_NOW, source="stock",
        image_filename=None,
    )
    t1 = Task.new_from_message(base)
    t1.mark_parsing()
    t1.mark_parse_failed("无法解析为交易指令")  # 终态 PARSE_ERROR，无 image
    async with session_scope(session_factory) as session:
        await save_task(session, t1)

    # 重抓:同 id，这次带 image_filename
    msg2 = Message(
        id="bf_1", content="", raw_content="", author="t",
        posted_at=_NOW, received_at=_NOW, source="stock",
        image_filename="bf_1.png",
    )
    t2 = Task.new_from_message(msg2)
    t2.mark_parsing()
    t2.mark_skipped("图片消息")
    async with session_scope(session_factory) as session:
        await save_task(session, t2)

    async with session_scope(session_factory) as session:
        loaded = await load_task(session, "bf_1")
    assert loaded is not None
    assert loaded.message.image_filename == "bf_1.png"  # 已回填


async def test_existing_image_filename_not_overwritten(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """已有 image_filename 不被后续重存覆盖(coalesce 只填空)。"""
    msg1 = Message(
        id="bf_2", content="", raw_content="", author="t",
        posted_at=_NOW, received_at=_NOW, source="stock",
        image_filename="original.png",
    )
    t1 = Task.new_from_message(msg1)
    t1.mark_parsing()
    t1.mark_skipped("图片消息")
    async with session_scope(session_factory) as session:
        await save_task(session, t1)

    msg2 = dataclasses_replace_filename(msg1, "different.png")
    t2 = Task.new_from_message(msg2)
    t2.mark_parsing()
    t2.mark_skipped("图片消息")
    async with session_scope(session_factory) as session:
        await save_task(session, t2)

    async with session_scope(session_factory) as session:
        loaded = await load_task(session, "bf_2")
    assert loaded is not None
    assert loaded.message.image_filename == "original.png"  # 未被覆盖
