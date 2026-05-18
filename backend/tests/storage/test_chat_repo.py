from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.storage import repo
from app.storage.db import session_scope
from app.storage.schema import ChatMessageRow


def _row(
    id_: str,
    *,
    page_id: str = "p1",
    author: str = "alice",
    posted_at: datetime | None = None,
    quoted_author: str | None = None,
) -> ChatMessageRow:
    posted_at = posted_at or datetime(2026, 5, 18, 9, 0, tzinfo=UTC)
    return ChatMessageRow(
        id=id_,
        page_id=page_id,
        author=author,
        content=f"hello from {author}",
        raw_content=f"hello from {author}",
        posted_at=posted_at,
        received_at=posted_at,
        url="https://whop.example/p1",
        quoted_message_id=None,
        quoted_author=quoted_author,
        quoted_content="quoted body" if quoted_author else None,
        quoted_posted_at=posted_at - timedelta(minutes=1) if quoted_author else None,
    )


async def test_upsert_chat_message_inserts_new(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m1"))

    async with session_scope(session_factory) as s:
        out = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        assert [r.id for r in out] == ["m1"]


async def test_upsert_chat_message_idempotent(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m1"))
        await repo.upsert_chat_message(s, _row("m1"))  # second insert -> no-op

    async with session_scope(session_factory) as s:
        out = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        assert len(out) == 1


async def test_list_chat_messages_week_window(session_factory) -> None:
    last_week = datetime(2026, 5, 10, 12, tzinfo=UTC)
    this_week = datetime(2026, 5, 18, 12, tzinfo=UTC)
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m_last", posted_at=last_week))
        await repo.upsert_chat_message(s, _row("m_this", posted_at=this_week))

    async with session_scope(session_factory) as s:
        out = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 18, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        assert [r.id for r in out] == ["m_this"]


async def test_list_chat_messages_sender_filter(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m_alice", author="alice"))
        await repo.upsert_chat_message(s, _row("m_bob", author="bob"))
        await repo.upsert_chat_message(s, _row("m_carol", author="carol"))

    async with session_scope(session_factory) as s:
        out = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            ["alice", "bob"],
        )
        assert sorted(r.id for r in out) == ["m_alice", "m_bob"]


async def test_list_chat_messages_empty_senders_is_no_filter(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m1", author="alice"))
        await repo.upsert_chat_message(s, _row("m2", author="bob"))

    async with session_scope(session_factory) as s:
        # None and [] both mean "no filter"
        out_none = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        out_empty = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            [],
        )
        assert len(out_none) == 2
        assert len(out_empty) == 2


async def test_list_chat_authors_counts(session_factory) -> None:
    async with session_scope(session_factory) as s:
        for i in range(3):
            await repo.upsert_chat_message(s, _row(f"a{i}", author="alice"))
        for i in range(5):
            await repo.upsert_chat_message(s, _row(f"b{i}", author="bob"))

    async with session_scope(session_factory) as s:
        out = await repo.list_chat_authors(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
        )
        assert dict(out) == {"alice": 3, "bob": 5}


async def test_delete_chat_messages_by_page(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m1", page_id="p1"))
        await repo.upsert_chat_message(s, _row("m2", page_id="p1"))
        await repo.upsert_chat_message(s, _row("m3", page_id="p2"))

    async with session_scope(session_factory) as s:
        deleted = await repo.delete_chat_messages_by_page(s, "p1")
        assert deleted == 2

    async with session_scope(session_factory) as s:
        remaining = await repo.list_chat_messages(
            s, "p2",
            datetime(2026, 5, 11, tzinfo=UTC),
            datetime(2026, 5, 25, tzinfo=UTC),
            None,
        )
        assert len(remaining) == 1
