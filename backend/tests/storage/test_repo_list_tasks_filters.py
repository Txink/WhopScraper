"""Tests for list_tasks(urls, posted_at_start, posted_at_end)."""
from datetime import datetime, timezone

import pytest

from app.storage import repo
from app.storage.schema import MessageRow, TaskRow


@pytest.mark.asyncio
async def test_list_tasks_filter_by_urls(session_factory):
    """Only tasks whose message.url matches any of the urls list are returned."""
    async with session_factory() as s:
        for tid, url in [("t1", "https://a"), ("t2", "https://b"), ("t3", "https://c")]:
            s.add(TaskRow(
                id=tid, type="stock", status="FILLED",
                created_at=datetime(2026, 5, 20, 9, 0),
                updated_at=datetime(2026, 5, 20, 9, 0),
            ))
            await s.flush()  # task row must exist before message FK is checked
            s.add(MessageRow(
                id=tid, url=url, source="stock", author="x", content="m",
                raw_content="m",
                posted_at=datetime(2026, 5, 20, 9, 0),
                received_at=datetime(2026, 5, 20, 9, 0),
            ))
        await s.commit()

    async with session_factory() as s:
        tasks = await repo.list_tasks(s, urls=["https://a", "https://c"])
    ids = {t.id for t in tasks}
    assert ids == {"t1", "t3"}


@pytest.mark.asyncio
async def test_list_tasks_filter_by_posted_at_window(session_factory):
    """posted_at_start (inclusive) / posted_at_end (exclusive) clip to a range."""
    async with session_factory() as s:
        for tid, ts in [
            ("early", datetime(2026, 5, 18, 9, 0)),
            ("inside", datetime(2026, 5, 20, 9, 0)),
            ("late", datetime(2026, 5, 25, 9, 0)),
        ]:
            s.add(TaskRow(
                id=tid, type="stock", status="FILLED",
                created_at=ts, updated_at=ts,
            ))
            await s.flush()  # task row must exist before message FK is checked
            s.add(MessageRow(
                id=tid, url="https://x", source="stock", author="a", content="m",
                raw_content="m",
                posted_at=ts, received_at=ts,
            ))
        await s.commit()

    async with session_factory() as s:
        tasks = await repo.list_tasks(
            s,
            posted_at_start=datetime(2026, 5, 19),
            posted_at_end=datetime(2026, 5, 22),
        )
    ids = {t.id for t in tasks}
    assert ids == {"inside"}


@pytest.mark.asyncio
async def test_list_tasks_urls_combines_with_status(session_factory):
    async with session_factory() as s:
        for tid, url, status in [
            ("a-ok", "https://a", "FILLED"),
            ("a-bad", "https://a", "PARSE_ERROR"),
            ("b-ok", "https://b", "FILLED"),
        ]:
            s.add(TaskRow(
                id=tid, type="stock", status=status,
                created_at=datetime(2026, 5, 20, 9, 0),
                updated_at=datetime(2026, 5, 20, 9, 0),
            ))
            await s.flush()  # task row must exist before message FK is checked
            s.add(MessageRow(
                id=tid, url=url, source="stock", author="x", content="m",
                raw_content="m",
                posted_at=datetime(2026, 5, 20, 9, 0),
                received_at=datetime(2026, 5, 20, 9, 0),
            ))
        await s.commit()

    async with session_factory() as s:
        from app.domain.status import Status
        tasks = await repo.list_tasks(s, urls=["https://a"], status=Status.FILLED)
    ids = {t.id for t in tasks}
    assert ids == {"a-ok"}


@pytest.mark.asyncio
async def test_list_tasks_empty_urls_returns_empty(session_factory):
    """Empty urls list = match nothing (explicit short-circuit)."""
    async with session_factory() as s:
        s.add(TaskRow(
            id="t1", type="stock", status="FILLED",
            created_at=datetime(2026, 5, 20, 9, 0),
            updated_at=datetime(2026, 5, 20, 9, 0),
        ))
        await s.flush()  # task row must exist before message FK is checked
        s.add(MessageRow(
            id="t1", url="https://a", source="stock", author="x", content="m",
            raw_content="m",
            posted_at=datetime(2026, 5, 20, 9, 0),
            received_at=datetime(2026, 5, 20, 9, 0),
        ))
        await s.commit()

    async with session_factory() as s:
        tasks = await repo.list_tasks(s, urls=[])
    assert tasks == []
