"""Tests for repo.delete_tasks_by_url — Task Q.2."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.message import Message
from app.domain.task import Task
from app.storage import repo
from app.storage.schema import InstructionRow, MessageRow, PushEventRow, TaskRow


def _make_task(id_: str, url: str | None) -> Task:
    msg = Message(
        id=id_,
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url=url,
    )
    return Task.new_from_message(msg)


@pytest.mark.asyncio
async def test_delete_tasks_by_url_removes_only_matching(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    url_a = "https://whop.com/a/app/"
    url_b = "https://whop.com/b/app/"
    async with session_factory() as session:
        await repo.save_task(session, _make_task("a1", url_a))
        await repo.save_task(session, _make_task("a2", url_a))
        await repo.save_task(session, _make_task("b1", url_b))
        await repo.save_task(session, _make_task("orphan", None))

    async with session_factory() as session:
        deleted = await repo.delete_tasks_by_url(session, url_a)
    assert deleted == 2

    # Verify only url_a rows are gone
    async with session_factory() as session:
        ids = {r[0] for r in (await session.execute(select(TaskRow.id))).all()}
    assert ids == {"b1", "orphan"}

    async with session_factory() as session:
        msg_ids = {r[0] for r in (await session.execute(select(MessageRow.id))).all()}
    assert msg_ids == {"b1", "orphan"}  # cascade deleted a1, a2 messages


@pytest.mark.asyncio
async def test_delete_tasks_by_url_unknown_url_returns_zero(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        deleted = await repo.delete_tasks_by_url(session, "https://whop.com/unknown/")
    assert deleted == 0


@pytest.mark.asyncio
async def test_delete_tasks_by_url_cascades_push_events_and_instructions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    url = "https://whop.com/x/app/"
    task_id = "to-delete"
    async with session_factory() as session:
        await repo.save_task(session, _make_task(task_id, url))
        # Manually add an instruction + push event for this task
        session.add(
            InstructionRow(
                task_id=task_id,
                instruction_type="BUY",
                context_source=None,
                payload_json={},
            )
        )
        session.add(
            PushEventRow(
                id="pe-1",
                task_id=task_id,
                order_id="o1",
                state="NEW",
                received_at=datetime.now(UTC),
                payload_json={},
            )
        )
        await session.commit()

    async with session_factory() as session:
        deleted = await repo.delete_tasks_by_url(session, url)
    assert deleted == 1

    # Verify cascade
    async with session_factory() as session:
        inst_count = len((await session.execute(select(InstructionRow))).all())
        push_count = len((await session.execute(select(PushEventRow))).all())
        msg_count = len((await session.execute(select(MessageRow))).all())
        task_count = len((await session.execute(select(TaskRow))).all())
    assert inst_count == 0
    assert push_count == 0
    assert msg_count == 0
    assert task_count == 0
