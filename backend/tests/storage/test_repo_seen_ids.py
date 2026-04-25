from datetime import UTC, datetime

import pytest

from app.domain.message import Message
from app.domain.task import Task
from app.storage import repo


@pytest.mark.asyncio
async def test_load_seen_ids_for_url_returns_only_matching(session_factory):
    url_a = "https://whop.com/a/app/"
    url_b = "https://whop.com/b/app/"
    msgs = [
        ("dom-a1", url_a),
        ("dom-a2", url_a),
        ("dom-b1", url_b),
        ("dom-orphan", None),
    ]
    async with session_factory() as session:
        for mid, u in msgs:
            msg = Message(
                id=mid,
                content="x",
                raw_content="x",
                author=None,
                posted_at=datetime.now(UTC),
                received_at=datetime.now(UTC),
                source="stock",
                url=u,
            )
            await repo.save_task(session, Task.new_from_message(msg))

    async with session_factory() as session:
        ids = await repo.load_seen_ids_for_url(session, url_a)
    assert ids == {"dom-a1", "dom-a2"}

    async with session_factory() as session:
        ids_b = await repo.load_seen_ids_for_url(session, url_b)
    assert ids_b == {"dom-b1"}


@pytest.mark.asyncio
async def test_load_seen_ids_for_url_empty(session_factory):
    async with session_factory() as session:
        ids = await repo.load_seen_ids_for_url(session, "https://whop.com/none/app/")
    assert ids == set()
