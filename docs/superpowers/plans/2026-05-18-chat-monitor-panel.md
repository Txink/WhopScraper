# Chat Monitor Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `source = "chat"` page type to the Whop monitoring dashboard. Chat pages capture raw messages into a new `chat_messages` table (no parsing, no tasks), and a new single-column card panel renders them with sender filtering and JSON export.

**Architecture:** Reuse the existing whop scraper / extractor / listener. Branch in `whop/listener.py` on `page.source == "chat"` → publish to a new topic `CHAT_MESSAGE_RECEIVED` → new `chat_writer` subscriber persists to `chat_messages` with denormalized quote fields. One new `GET /api/whop/pages/{page_id}/chat-messages` endpoint. Frontend `ChatBoardPanel` does all card grouping + JSON export client-side; existing `PageInfoBar` / `PageActionBar` are untouched.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (async) + Alembic on the backend; React 18 + Vite + TypeScript + vitest on the frontend; pytest backend. Uses the project's existing event bus (`app/core/events.py`) and CSS tokens (`frontend/src/styles/tokens.css`).

**Spec:** `docs/superpowers/specs/2026-05-18-chat-monitor-panel-design.md`

---

## File map

### Backend (create)
- `backend/app/whop/chat_writer.py` — event subscriber
- `backend/alembic/versions/<hash>_add_chat_messages.py` — schema migration
- `backend/tests/whop/test_listener_chat_branch.py`
- `backend/tests/whop/test_chat_writer.py`
- `backend/tests/storage/test_chat_repo.py`
- `backend/tests/api/test_chat_messages_endpoint.py`

### Backend (modify)
- `backend/app/core/events.py:31-68` — add Topics constants + Payload dataclasses
- `backend/app/storage/schema.py` — add `ChatMessageRow` ORM
- `backend/app/storage/repo.py` — add 4 chat functions
- `backend/app/whop/registry.py:36-38` — extend `_SourceLiteral`
- `backend/app/whop/page_settings.py:17-35,60` — extend `_SourceLiteral` + 2 new fields
- `backend/app/whop/listener.py:273-284` — branch on `page.source == "chat"`
- `backend/app/api/schemas.py:550-562,589-592` — extend schemas + 2 new fields + chat output models
- `backend/app/api/http.py:1335,1349-1353,1424` — POST/DELETE/PATCH + new GET endpoint
- `backend/app/api/ws.py:74-86` — bridge `CHAT_MESSAGE_STORED`
- `backend/app/main.py:179-188` — register `chat_writer`

### Frontend (create)
- `frontend/src/components/Chat/ChatBoardPanel.tsx`
- `frontend/src/components/Chat/ChatBoardPanel.css`
- `frontend/src/components/Chat/ChatMetaBar.tsx`
- `frontend/src/components/Chat/ChatSenderBar.tsx`
- `frontend/src/components/Chat/ChatCard.tsx`
- `frontend/src/components/Chat/chatCards.ts`
- `frontend/src/components/Chat/chatCards.test.ts`
- `frontend/src/components/Chat/chatExport.ts`
- `frontend/src/components/Chat/chatExport.test.ts`
- `frontend/src/api/chat.ts`
- `frontend/src/stores/chatStore.ts`

### Frontend (modify)
- `frontend/src/api/domain-types.ts:118-128` — regenerate from updated OpenAPI
- `frontend/src/App.tsx:~303` — dispatch on `activePage.source === "chat"`
- `frontend/src/components/Dashboard/Dashboard.css:11-13` — add `.tab-source-dot.chat`
- `frontend/src/components/Dashboard/PageSettingsModal.tsx` — disable `source` for existing pages; add chat fields

---

## Phase 1 — Events & topic plumbing

### Task 1: Add CHAT topics + payload dataclasses

**Files:**
- Modify: `backend/app/core/events.py:31-68`
- Test: `backend/tests/core/test_events_chat.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/core/test_events_chat.py`:

```python
from datetime import datetime, timezone

from app.core.events import (
    Topics,
    ChatMessagePayload,
    ChatMessageStored,
)
from app.domain.message import Message


def _msg() -> Message:
    return Message(
        id="m1",
        content="hi",
        raw_content="hi",
        author="alice",
        posted_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
        source="chat",
        url="https://whop.example/p1",
        quoted=None,
        history_hint=[],
    )


def test_topics_constants_exist() -> None:
    assert Topics.CHAT_MESSAGE_RECEIVED == "chat.message_received"
    assert Topics.CHAT_MESSAGE_STORED == "chat.message_stored"


def test_chat_message_payload_is_frozen_dataclass() -> None:
    payload = ChatMessagePayload(page_id="p1", message=_msg(), is_historical=False)
    assert payload.page_id == "p1"
    assert payload.is_historical is False


def test_chat_message_stored_carries_row_reference() -> None:
    # ChatMessageStored is a thin marker payload; we only need page_id + msg_id
    stored = ChatMessageStored(page_id="p1", message_id="m1")
    assert stored.page_id == "p1"
    assert stored.message_id == "m1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/core/test_events_chat.py -v
```

Expected: FAIL with `AttributeError: type object 'Topics' has no attribute 'CHAT_MESSAGE_RECEIVED'` or `ImportError: cannot import name 'ChatMessagePayload'`.

- [ ] **Step 3: Modify `backend/app/core/events.py`**

Insert two constants into `class Topics:` (after `WHOP_PAGE_CHANGED`, around line 43):

```python
    CHAT_MESSAGE_RECEIVED = "chat.message_received"
    CHAT_MESSAGE_STORED = "chat.message_stored"
```

Insert two dataclasses below `MessagePayload` (around line 68):

```python
@dataclass(frozen=True)
class ChatMessagePayload:
    """Payload for ``chat.message_received`` events.

    Emitted by listeners for pages whose source is "chat". Carries the
    full extracted :class:`Message` (including the optional ``quoted``
    nested message) plus the ``page_id`` so the writer knows where to
    persist the row without re-resolving the page from the URL.
    """

    page_id: str
    message: Message
    is_historical: bool = False


@dataclass(frozen=True)
class ChatMessageStored:
    """Payload for ``chat.message_stored`` events.

    Emitted after a non-historical chat message is persisted. WS bridges
    this to the frontend so it can append the message to the active
    page's in-memory cache and re-run card grouping.
    """

    page_id: str
    message_id: str
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/core/test_events_chat.py -v
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/events.py backend/tests/core/test_events_chat.py
git commit -m "feat(chat): add CHAT_MESSAGE_RECEIVED / CHAT_MESSAGE_STORED topics + payloads"
```

---

## Phase 2 — Schema, migration, repo

### Task 2: Add ChatMessageRow ORM mapping

**Files:**
- Modify: `backend/app/storage/schema.py` (append after `MessageRow`, around line 100)
- Test: `backend/tests/storage/test_chat_repo.py` (create — used in Task 4; create skeleton now)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/storage/test_chat_repo.py` with only the import sanity test:

```python
def test_chat_message_row_importable() -> None:
    from app.storage.schema import ChatMessageRow

    assert ChatMessageRow.__tablename__ == "chat_messages"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/storage/test_chat_repo.py::test_chat_message_row_importable -v
```

Expected: FAIL with `ImportError: cannot import name 'ChatMessageRow'`.

- [ ] **Step 3: Modify `backend/app/storage/schema.py`**

Append after the existing `MessageRow` class (around line 100):

```python
# ---------------------------------------------------------------------------
# chat_messages  (free-standing — no FK to tasks; page_id is a SOFT link
# because WhopPageEntry lives in data/whop_pages.json, not in DB)
# ---------------------------------------------------------------------------


class ChatMessageRow(Base):
    """ORM mapping for the ``chat_messages`` table.

    Rows are written directly by ``app.whop.chat_writer`` for pages whose
    ``WhopPageEntry.source == "chat"``; they never go through the task /
    instruction pipeline. The ``quoted_*`` columns are always denormalized
    so a row renders correctly even if the referenced message is missing
    (e.g., before scraping started, from a non-watched sender, or in a
    different week than the active view).
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("idx_chat_messages_page_posted", "page_id", "posted_at"),
        Index("idx_chat_messages_page_author_posted", "page_id", "author", "posted_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    page_id: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    raw_content: Mapped[str] = mapped_column(String, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_author: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_content: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
```

If `func` is not already imported at the top of the file, add `from sqlalchemy import func` alongside the existing sqlalchemy imports.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/storage/test_chat_repo.py::test_chat_message_row_importable -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/schema.py backend/tests/storage/test_chat_repo.py
git commit -m "feat(chat): add ChatMessageRow ORM mapping"
```

---

### Task 3: Generate alembic migration for chat_messages

**Files:**
- Create: `backend/alembic/versions/<auto-hash>_add_chat_messages.py`

- [ ] **Step 1: Generate the migration file**

```bash
cd backend && uv run alembic revision --autogenerate -m "add_chat_messages"
```

This creates a new file in `backend/alembic/versions/`. Open the generated file.

- [ ] **Step 2: Verify the autogenerated upgrade matches the schema**

The autogenerated `upgrade()` should look approximately like:

```python
def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("page_id", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("raw_content", sa.String(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("quoted_message_id", sa.String(), nullable=True),
        sa.Column("quoted_author", sa.String(), nullable=True),
        sa.Column("quoted_content", sa.String(), nullable=True),
        sa.Column("quoted_posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_chat_messages_page_posted", "chat_messages",
                    ["page_id", "posted_at"])
    op.create_index("idx_chat_messages_page_author_posted", "chat_messages",
                    ["page_id", "author", "posted_at"])


def downgrade() -> None:
    op.drop_index("idx_chat_messages_page_author_posted", table_name="chat_messages")
    op.drop_index("idx_chat_messages_page_posted", table_name="chat_messages")
    op.drop_table("chat_messages")
```

If autogenerate produced something different (e.g., extra unrelated table changes), trim it to only the `chat_messages` create/drop operations.

- [ ] **Step 3: Apply the migration**

```bash
cd backend && uv run alembic upgrade head
```

Expected: Output ends with `INFO  [alembic.runtime.migration] Running upgrade ... -> <new_hash>, add_chat_messages`.

- [ ] **Step 4: Verify the table exists**

```bash
cd backend && uv run python -c "from app.storage.db import sync_engine; from sqlalchemy import inspect; print(inspect(sync_engine()).get_table_names())"
```

Expected: Output contains `'chat_messages'`.

- [ ] **Step 5: Commit**

```bash
git add backend/alembic/versions/*_add_chat_messages.py
git commit -m "feat(chat): alembic migration for chat_messages table"
```

---

### Task 4: Add chat repo functions

**Files:**
- Modify: `backend/app/storage/repo.py` (append at end)
- Test: `backend/tests/storage/test_chat_repo.py` (extend)

- [ ] **Step 1: Write the failing tests**

Replace `backend/tests/storage/test_chat_repo.py` with:

```python
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.storage import repo
from app.storage.db import session_scope
from app.storage.schema import Base, ChatMessageRow


@pytest.fixture
async def session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _row(
    id_: str,
    *,
    page_id: str = "p1",
    author: str = "alice",
    posted_at: datetime | None = None,
    quoted_author: str | None = None,
) -> ChatMessageRow:
    posted_at = posted_at or datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc)
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
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        assert [r.id for r in out] == ["m1"]


async def test_upsert_chat_message_idempotent(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m1"))
        await repo.upsert_chat_message(s, _row("m1"))  # second insert → no-op

    async with session_scope(session_factory) as s:
        out = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        assert len(out) == 1


async def test_list_chat_messages_week_window(session_factory) -> None:
    last_week = datetime(2026, 5, 10, 12, tzinfo=timezone.utc)
    this_week = datetime(2026, 5, 18, 12, tzinfo=timezone.utc)
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(s, _row("m_last", posted_at=last_week))
        await repo.upsert_chat_message(s, _row("m_this", posted_at=this_week))

    async with session_scope(session_factory) as s:
        out = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 18, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
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
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
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
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        out_empty = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
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
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
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
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        assert len(remaining) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/storage/test_chat_repo.py -v
```

Expected: All FAIL with `AttributeError: module 'app.storage.repo' has no attribute 'upsert_chat_message'` (or similar).

- [ ] **Step 3: Add repo functions in `backend/app/storage/repo.py`**

Append at the end of the file (after the last existing function):

```python
# ---------------------------------------------------------------------------
# chat_messages
# ---------------------------------------------------------------------------


async def upsert_chat_message(session: AsyncSession, row: ChatMessageRow) -> None:
    """Insert a chat message; ignore duplicates by ``id`` (idempotent on replay).

    Uses dialect-agnostic INSERT-OR-IGNORE: try MERGE-style via
    ``sqlite_insert.on_conflict_do_nothing`` when on sqlite, else use
    ``postgresql_insert.on_conflict_do_nothing``. Both dialects are
    represented in the repo's existing code; pick the one matching the
    bind.
    """
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    stmt = sqlite_insert(ChatMessageRow.__table__).values(
        id=row.id,
        page_id=row.page_id,
        author=row.author,
        content=row.content,
        raw_content=row.raw_content,
        posted_at=row.posted_at,
        received_at=row.received_at,
        url=row.url,
        quoted_message_id=row.quoted_message_id,
        quoted_author=row.quoted_author,
        quoted_content=row.quoted_content,
        quoted_posted_at=row.quoted_posted_at,
    ).on_conflict_do_nothing(index_elements=["id"])
    await session.execute(stmt)


async def list_chat_messages(
    session: AsyncSession,
    page_id: str,
    week_start: datetime,
    week_end: datetime,
    senders: list[str] | None,
) -> list[ChatMessageRow]:
    """Return chat messages for *page_id* in [week_start, week_end), ordered by posted_at ASC.

    ``senders=None`` and ``senders=[]`` both mean "no filter".
    """
    stmt = (
        select(ChatMessageRow)
        .where(ChatMessageRow.page_id == page_id)
        .where(ChatMessageRow.posted_at >= week_start)
        .where(ChatMessageRow.posted_at < week_end)
        .order_by(ChatMessageRow.posted_at.asc())
    )
    if senders:
        stmt = stmt.where(ChatMessageRow.author.in_(senders))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_chat_authors(
    session: AsyncSession,
    page_id: str,
    week_start: datetime,
    week_end: datetime,
) -> list[tuple[str, int]]:
    """Return ``(author, count)`` pairs for chat messages in the week window."""
    stmt = (
        select(ChatMessageRow.author, func.count(ChatMessageRow.id))
        .where(ChatMessageRow.page_id == page_id)
        .where(ChatMessageRow.posted_at >= week_start)
        .where(ChatMessageRow.posted_at < week_end)
        .group_by(ChatMessageRow.author)
        .order_by(func.count(ChatMessageRow.id).desc())
    )
    result = await session.execute(stmt)
    return [(author, count) for author, count in result.all()]


async def delete_chat_messages_by_page(session: AsyncSession, page_id: str) -> int:
    """Delete all chat messages for *page_id*; returns the count removed.

    Called by the page-delete API route after removing the page from the
    whop registry (which lives in data/whop_pages.json, not the DB — so
    no FK cascade is possible).
    """
    from sqlalchemy import delete

    stmt = delete(ChatMessageRow).where(ChatMessageRow.page_id == page_id)
    result = await session.execute(stmt)
    return result.rowcount or 0
```

Ensure these imports exist at the top of the file (add if missing):

```python
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.storage.schema import ChatMessageRow
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/storage/test_chat_repo.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_chat_repo.py
git commit -m "feat(chat): repo functions upsert/list/delete chat messages"
```

---

## Phase 3 — Page settings + source literal

### Task 5: Extend `_SourceLiteral` to include "chat"

**Files:**
- Modify: `backend/app/whop/registry.py:36-38`
- Modify: `backend/app/whop/page_settings.py:60`
- Modify: `backend/app/api/schemas.py:591`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/whop/test_chat_source_literal.py`:

```python
from app.whop.page_settings import default_settings_for


def test_default_settings_for_chat_source() -> None:
    settings = default_settings_for("chat")
    assert settings.dedupe_processed_messages is True       # carries over
    assert settings.watched_senders == []
    assert settings.chat_card_max_msgs == 5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/whop/test_chat_source_literal.py -v
```

Expected: FAIL (either `Literal` validation error or AttributeError).

- [ ] **Step 3: Apply 3 edits**

`backend/app/whop/registry.py:38`:
```python
_SourceLiteral = Literal["stock", "option", "chat"]
```

`backend/app/whop/page_settings.py:60` (parameter annotation):
```python
def default_settings_for(source: Literal["stock", "option", "chat"]) -> PageSettings:
```

`backend/app/api/schemas.py:591`:
```python
    source: Literal["stock", "option", "chat"]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/whop/test_chat_source_literal.py -v
```

Expected: PASS (Task 6 will add the two new settings fields that this test asserts on; for now if the assertions on `watched_senders` / `chat_card_max_msgs` fail, that's expected — bundle this into a single test that the next task makes green).

If you want strict TDD per task: split this test into two — one for source acceptance (passes now), one for settings defaults (fails now, passes after Task 6).

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/registry.py backend/app/whop/page_settings.py backend/app/api/schemas.py backend/tests/whop/test_chat_source_literal.py
git commit -m "feat(chat): extend WhopPage source literal with 'chat'"
```

---

### Task 6: Add `watched_senders` + `chat_card_max_msgs` to PageSettings

**Files:**
- Modify: `backend/app/whop/page_settings.py:17-35,86` (PageSettings dataclass + `page_settings_to_dict`)
- Modify: `backend/app/api/schemas.py:550-562` (WhopPageSettingsPatch + WhopPageSettingsOut)
- Test: `backend/tests/whop/test_chat_source_literal.py` (already covers defaults)

- [ ] **Step 1: Add fields in `PageSettings` dataclass**

`backend/app/whop/page_settings.py`, after `parser_version` (around line 30):

```python
    watched_senders: list[str] = field(default_factory=list)
    chat_card_max_msgs: int = 5
```

- [ ] **Step 2: Update `page_settings_to_dict` to include the new fields**

In the same file (around line 86), add the new keys to the returned dict:

```python
def page_settings_to_dict(settings: PageSettings) -> dict[str, Any]:
    return {
        # ... existing fields ...
        "watched_senders": list(settings.watched_senders),
        "chat_card_max_msgs": settings.chat_card_max_msgs,
    }
```

Likewise update `page_settings_from_dict` to read these fields with safe defaults:

```python
def page_settings_from_dict(d: dict[str, Any]) -> PageSettings:
    return PageSettings(
        # ... existing fields ...
        watched_senders=list(d.get("watched_senders", []) or []),
        chat_card_max_msgs=int(d.get("chat_card_max_msgs", 5)),
    )
```

- [ ] **Step 3: Update API schemas**

`backend/app/api/schemas.py`, in `WhopPageSettingsPatch` (after `option_total_price_limit`, around line 562):

```python
    watched_senders: list[str] | None = None
    chat_card_max_msgs: int | None = Field(default=None, ge=1, le=50)
```

Also add the same fields to `WhopPageSettingsOut` (or whatever class the `GET /api/whop/pages` response uses for settings — locate it by searching `class WhopPageSettings` in `schemas.py`).

- [ ] **Step 4: Run the existing test from Task 5**

```bash
cd backend && uv run pytest tests/whop/test_chat_source_literal.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/page_settings.py backend/app/api/schemas.py
git commit -m "feat(chat): add watched_senders + chat_card_max_msgs to PageSettings"
```

---

### Task 7: Reject `source` change on PATCH page settings

**Files:**
- Modify: `backend/app/api/http.py:1424` (the PATCH settings endpoint)
- Test: `backend/tests/api/test_chat_messages_endpoint.py` (create skeleton)

- [ ] **Step 1: Verify current behavior**

Read `backend/app/api/http.py:1424` and surrounding lines. The `WhopPageSettingsPatch` schema (`schemas.py:550-562`) **does not** declare a `source` field, so it is already implicitly rejected by pydantic. No code change should be needed.

- [ ] **Step 2: Add a regression test**

Create `backend/tests/api/test_chat_messages_endpoint.py`:

```python
from fastapi.testclient import TestClient


def test_patch_settings_rejects_source_field(api_client: TestClient, sample_page) -> None:
    # ``sample_page`` is a fixture (assume defined in conftest) that POSTs a page
    # and returns its ``id``; if it doesn't exist yet, create one inline:
    # resp = api_client.post("/api/whop/pages", json={"url": "...", "source": "stock"})
    # page_id = resp.json()["id"]
    resp = api_client.patch(
        f"/api/whop/pages/{sample_page}/settings",
        json={"source": "chat"},   # not in the patch schema → ignored or 422
    )
    # pydantic strict-mode rejects unknown fields → 422; if extra=ignore → 200 + no change
    # Either way, source must not change.
    page_resp = api_client.get("/api/whop/pages").json()
    page = next(p for p in page_resp["pages"] if p["id"] == sample_page)
    assert page["source"] == "stock"
```

If the `api_client` and `sample_page` fixtures don't exist yet, mark the test `@pytest.mark.skip(reason="needs api client fixture in conftest")` and revisit after the GET endpoint task adds them.

- [ ] **Step 3: Run test**

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py::test_patch_settings_rejects_source_field -v
```

Expected: PASS (or SKIP). No production code change needed — pydantic already enforces this.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/api/test_chat_messages_endpoint.py
git commit -m "test(chat): regression — PATCH page settings cannot change source"
```

---

## Phase 4 — Listener branch + chat_writer

### Task 8: Add `chat_writer` event subscriber

**Files:**
- Create: `backend/app/whop/chat_writer.py`
- Create: `backend/tests/whop/test_chat_writer.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/whop/test_chat_writer.py`:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.events import (
    EventBus, Event, Topics, ChatMessagePayload, ChatMessageStored,
)
from app.domain.message import Message
from app.storage import repo
from app.storage.db import session_scope
from app.storage.schema import Base
from app.whop.chat_writer import register_chat_writer


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


def _msg(id_: str, author: str = "alice", quoted: Message | None = None) -> Message:
    return Message(
        id=id_,
        content=f"hi from {author}",
        raw_content=f"hi from {author}",
        author=author,
        posted_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
        source="chat",
        url="https://whop.example/p1",
        quoted=quoted,
        history_hint=[],
    )


async def test_chat_writer_persists_basic_message(session_factory) -> None:
    bus = EventBus()
    register_chat_writer(bus, session_factory)

    await bus.publish_async(Event(
        Topics.CHAT_MESSAGE_RECEIVED,
        ChatMessagePayload(page_id="p1", message=_msg("m1"), is_historical=False),
    ))

    async with session_scope(session_factory) as s:
        rows = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        assert [r.id for r in rows] == ["m1"]
        assert rows[0].quoted_author is None


async def test_chat_writer_denormalizes_quote(session_factory) -> None:
    bus = EventBus()
    register_chat_writer(bus, session_factory)

    quoted = _msg("m_quoted", author="bob")
    await bus.publish_async(Event(
        Topics.CHAT_MESSAGE_RECEIVED,
        ChatMessagePayload(page_id="p1", message=_msg("m1", quoted=quoted)),
    ))

    async with session_scope(session_factory) as s:
        rows = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        assert rows[0].quoted_author == "bob"
        assert rows[0].quoted_content == "hi from bob"
        assert rows[0].quoted_message_id == "m_quoted"


async def test_chat_writer_skips_broadcast_when_historical(session_factory) -> None:
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(Topics.CHAT_MESSAGE_STORED, lambda e: seen.append(e))
    register_chat_writer(bus, session_factory)

    await bus.publish_async(Event(
        Topics.CHAT_MESSAGE_RECEIVED,
        ChatMessagePayload(page_id="p1", message=_msg("m1"), is_historical=True),
    ))

    assert seen == []  # no STORED broadcast for historical replay


async def test_chat_writer_broadcasts_when_live(session_factory) -> None:
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(Topics.CHAT_MESSAGE_STORED, lambda e: seen.append(e))
    register_chat_writer(bus, session_factory)

    await bus.publish_async(Event(
        Topics.CHAT_MESSAGE_RECEIVED,
        ChatMessagePayload(page_id="p1", message=_msg("m1"), is_historical=False),
    ))

    assert len(seen) == 1
    payload: ChatMessageStored = seen[0].payload
    assert payload.page_id == "p1"
    assert payload.message_id == "m1"


async def test_chat_writer_idempotent_on_replay(session_factory) -> None:
    bus = EventBus()
    register_chat_writer(bus, session_factory)

    payload = ChatMessagePayload(page_id="p1", message=_msg("m1"))
    await bus.publish_async(Event(Topics.CHAT_MESSAGE_RECEIVED, payload))
    await bus.publish_async(Event(Topics.CHAT_MESSAGE_RECEIVED, payload))

    async with session_scope(session_factory) as s:
        rows = await repo.list_chat_messages(
            s, "p1",
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        assert len(rows) == 1
```

(If the project's `EventBus` only has a synchronous `publish` method, use that — adjust `publish_async` → `publish` and drop `await` from those lines. Inspect `backend/app/core/events.py` to confirm.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/whop/test_chat_writer.py -v
```

Expected: All FAIL with `ImportError: cannot import name 'register_chat_writer'`.

- [ ] **Step 3: Implement `backend/app/whop/chat_writer.py`**

```python
"""Event subscriber that persists chat messages to the ``chat_messages`` table.

Mirrors ``app.storage.listeners.register_storage_listeners`` in shape:
takes the bus + async session factory, returns a list of unsubscribe
callables, registers handlers for ``Topics.CHAT_MESSAGE_RECEIVED``.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import (
    EventBus, Event, Topics, ChatMessagePayload, ChatMessageStored,
)
from app.domain.message import Message
from app.storage import repo
from app.storage.db import session_scope
from app.storage.schema import ChatMessageRow


def _row_from_message(page_id: str, msg: Message) -> ChatMessageRow:
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
    async def _handler(event: Event) -> None:
        payload: ChatMessagePayload = event.payload  # pyright: ignore[reportAssignmentType]
        row = _row_from_message(payload.page_id, payload.message)
        async with session_scope(session_factory) as s:
            await repo.upsert_chat_message(s, row)
        if not payload.is_historical:
            await bus.publish_async(Event(
                Topics.CHAT_MESSAGE_STORED,
                ChatMessageStored(page_id=payload.page_id, message_id=row.id),
            ))

    _handler.__name__ = f"_chat_writer_handler[{session_factory!r}]"
    return [bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, _handler)]
```

If `bus.publish_async` doesn't exist, use whatever the bus's publish method is (the existing parser/storage handlers will show the pattern — grep `bus.publish` in `app/parser/service.py`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/whop/test_chat_writer.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/chat_writer.py backend/tests/whop/test_chat_writer.py
git commit -m "feat(chat): chat_writer event subscriber persists chat messages"
```

---

### Task 9: Branch in whop/listener.py on `source == "chat"`

**Files:**
- Modify: `backend/app/whop/listener.py:273-284`
- Create: `backend/tests/whop/test_listener_chat_branch.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/whop/test_listener_chat_branch.py`. First, **read the file** at `backend/app/whop/listener.py:265-290` to confirm the exact publish call, and **locate** how `self._page` is set on the listener (it's likely passed in `__init__` from registry). The test should construct a listener with a `source="chat"` page mock and assert that the published topic is `CHAT_MESSAGE_RECEIVED` rather than `MESSAGE_RECEIVED`.

A starting test skeleton:

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.core.events import EventBus, Topics
from app.domain.message import Message
from app.whop.listener import _publish_message   # or whatever the publish helper is named


def _msg() -> Message:
    return Message(
        id="m1",
        content="hi",
        raw_content="hi",
        author="alice",
        posted_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc),
        source="chat",
        url="https://whop.example/p1",
        quoted=None,
        history_hint=[],
    )


def test_listener_publishes_chat_topic_for_chat_pages() -> None:
    bus = EventBus()
    seen = []
    bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, lambda e: seen.append(e))
    bus.subscribe(Topics.MESSAGE_RECEIVED, lambda e: seen.append(e))

    page = MagicMock(id="p1", source="chat", url="https://whop.example/p1")
    _publish_message(bus, page, _msg(), is_historical=False)

    assert len(seen) == 1
    assert seen[0].topic == Topics.CHAT_MESSAGE_RECEIVED
    assert seen[0].payload.page_id == "p1"


def test_listener_publishes_message_topic_for_stock_pages() -> None:
    bus = EventBus()
    seen = []
    bus.subscribe(Topics.MESSAGE_RECEIVED, lambda e: seen.append(e))
    bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, lambda e: seen.append(e))

    page = MagicMock(id="p2", source="stock", url="https://whop.example/p2")
    _publish_message(bus, page, _msg(), is_historical=False)

    assert len(seen) == 1
    assert seen[0].topic == Topics.MESSAGE_RECEIVED
```

If the publish logic in `listener.py:273-284` is inline inside a class method (not a helper), refactor it into a small free function `_publish_message(bus, page, message, *, is_historical)` first (as a pure refactor before adding behavior). This keeps the test surface small.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/whop/test_listener_chat_branch.py -v
```

Expected: FAIL (either `ImportError` or `assert seen[0].topic == CHAT_MESSAGE_RECEIVED` since the chat branch doesn't exist yet).

- [ ] **Step 3: Refactor + branch in `backend/app/whop/listener.py`**

Read lines 265-290 first to confirm the exact context. The publish site is:

```python
tagged = dataclasses.replace(msg, url=self._url)
publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=tagged, is_historical=...)))
```

Replace with a call to a new module-level helper:

```python
# At module top (near imports):
from app.core.events import (
    Event, EventBus, Topics, MessagePayload, ChatMessagePayload,
)


def _publish_message(
    bus: EventBus,
    page,  # WhopPageEntry — avoid circular import by leaving untyped
    message: Message,
    *,
    is_historical: bool,
) -> None:
    """Branch on page.source and publish to the right topic."""
    if page.source == "chat":
        bus.publish(Event(
            Topics.CHAT_MESSAGE_RECEIVED,
            ChatMessagePayload(
                page_id=page.id, message=message, is_historical=is_historical,
            ),
        ))
    else:
        bus.publish(Event(
            Topics.MESSAGE_RECEIVED,
            MessagePayload(message=message, is_historical=is_historical),
        ))
```

In the listener method around line 273-284, replace the direct publish with:

```python
tagged = dataclasses.replace(msg, url=self._url)
_publish_message(self._bus, self._page, tagged, is_historical=is_historical)
```

(Use the attribute names that actually exist on the listener — read the surrounding `__init__` if needed.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/whop/test_listener_chat_branch.py -v
```

Expected: Both tests PASS. Also run the full whop test suite to confirm no regression:

```bash
cd backend && uv run pytest tests/whop/ -v
```

Expected: All existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/listener.py backend/tests/whop/test_listener_chat_branch.py
git commit -m "feat(chat): listener branches on page.source — chat → CHAT_MESSAGE_RECEIVED"
```

---

### Task 10: Wire `register_chat_writer` into main.py

**Files:**
- Modify: `backend/app/main.py:179-188`
- Test: covered by existing wiring + manual smoke test in Task 29

- [ ] **Step 1: Add import + registration**

In `backend/app/main.py`, add to imports near line 27:

```python
from app.whop.chat_writer import register_chat_writer
```

In the listener wiring block (lines 179-188), after `register_storage_listeners`:

```python
        state.unsubs.extend(register_chat_writer(bus, session_factory))
```

- [ ] **Step 2: Verify app boots**

```bash
cd backend && uv run python -c "from app.main import create_app; create_app(); print('OK')"
```

Expected: `OK` printed, no exceptions.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(chat): register chat_writer subscriber at app startup"
```

---

### Task 11: Page deletion clears chat_messages

**Files:**
- Modify: `backend/app/api/http.py:1349-1353`
- Test: `backend/tests/api/test_chat_messages_endpoint.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/test_chat_messages_endpoint.py`:

```python
async def test_delete_chat_page_removes_chat_messages(
    api_client, session_factory, sample_chat_page_with_messages,
):
    page_id = sample_chat_page_with_messages   # fixture creates page + N rows

    resp = api_client.delete(f"/api/whop/pages/{page_id}")
    assert resp.status_code == 204

    async with session_scope(session_factory) as s:
        from app.storage import repo
        from datetime import datetime, timezone
        out = await repo.list_chat_messages(
            s, page_id,
            datetime(2026, 5, 11, tzinfo=timezone.utc),
            datetime(2026, 5, 25, tzinfo=timezone.utc),
            None,
        )
        assert out == []
```

You'll need a `sample_chat_page_with_messages` fixture in `conftest.py`. If `conftest.py` setup is large, add a minimal version inline in the test file. The point: a chat page with rows → DELETE → rows gone.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py::test_delete_chat_page_removes_chat_messages -v
```

Expected: FAIL — rows survive deletion.

- [ ] **Step 3: Modify the DELETE endpoint at `http.py:1349-1353`**

```python
        @router.delete("/api/whop/pages/{page_id}", status_code=204)
        async def delete_whop_page(page_id: str) -> None:
            # Read source BEFORE removing the page so we know whether to clean chat rows.
            page = await whop_registry.get_page(page_id)
            if page is None:
                raise HTTPException(404, detail="page not found")
            source = page.source

            ok = await whop_registry.remove_page(page_id)
            if not ok:
                raise HTTPException(404, detail="page not found")

            if source == "chat":
                async with session_scope(session_factory) as s:
                    await repo.delete_chat_messages_by_page(s, page_id)
```

Adjust the names (`get_page` / `remove_page` / `session_factory`) to match what's actually in scope in this endpoint — check the imports at the top of `http.py` and the surrounding endpoint signatures. The `session_factory` is typically injected via a FastAPI dependency or pulled from app state.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py::test_delete_chat_page_removes_chat_messages -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_chat_messages_endpoint.py
git commit -m "feat(chat): page DELETE clears chat_messages for chat pages"
```

---

### Task 12: WS bridges CHAT_MESSAGE_STORED to frontend

**Files:**
- Modify: `backend/app/api/ws.py:74-86`

- [ ] **Step 1: Add the topic to the bridge list**

In `backend/app/api/ws.py:74-86`, the list of topics bridged to WS clients. Add:

```python
            Topics.CHAT_MESSAGE_STORED,
```

into the topic list (alongside `WHOP_PAGE_CHANGED` etc.).

- [ ] **Step 2: Verify the WS module still imports cleanly**

```bash
cd backend && uv run python -c "from app.api.ws import *; print('OK')"
```

Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/ws.py
git commit -m "feat(chat): WS bridges CHAT_MESSAGE_STORED to frontend"
```

---

## Phase 5 — API endpoint

### Task 13: Add ChatMessagesOut + ChatMessageOut response schemas

**Files:**
- Modify: `backend/app/api/schemas.py` (append at end)

- [ ] **Step 1: Add schemas**

Append:

```python
class QuotedRefOut(BaseModel):
    message_id: str | None = None
    author: str
    content: str
    posted_at: datetime | None = None


class ChatMessageOut(BaseModel):
    id: str
    page_id: str
    author: str
    content: str
    posted_at: datetime
    quoted: QuotedRefOut | None = None


class ChatAuthorOut(BaseModel):
    name: str
    count: int


class ChatWeekWindowOut(BaseModel):
    start: datetime
    end: datetime


class ChatMessagesOut(BaseModel):
    messages: list[ChatMessageOut]
    authors: list[ChatAuthorOut]
    week: ChatWeekWindowOut
```

- [ ] **Step 2: Verify**

```bash
cd backend && uv run python -c "from app.api.schemas import ChatMessagesOut; print(ChatMessagesOut.model_json_schema()['properties'].keys())"
```

Expected: `dict_keys(['messages', 'authors', 'week'])`.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/schemas.py
git commit -m "feat(chat): API response schemas ChatMessagesOut / ChatMessageOut"
```

---

### Task 14: Add `GET /api/whop/pages/{page_id}/chat-messages`

**Files:**
- Modify: `backend/app/api/http.py` (insert near the existing whop endpoints, around line 1330)
- Test: `backend/tests/api/test_chat_messages_endpoint.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/api/test_chat_messages_endpoint.py`:

```python
def test_get_chat_messages_returns_shape(api_client, sample_chat_page_with_messages):
    page_id = sample_chat_page_with_messages
    resp = api_client.get(
        f"/api/whop/pages/{page_id}/chat-messages?week=2026-W21",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "messages" in body
    assert "authors" in body
    assert "week" in body
    assert isinstance(body["messages"], list)


def test_get_chat_messages_filters_by_sender(api_client, sample_chat_page_with_messages):
    page_id = sample_chat_page_with_messages
    resp = api_client.get(
        f"/api/whop/pages/{page_id}/chat-messages"
        f"?week=2026-W21&senders=alice",
    )
    body = resp.json()
    assert all(m["author"] == "alice" for m in body["messages"])


def test_get_chat_messages_unknown_page_404(api_client):
    resp = api_client.get("/api/whop/pages/no-such-page/chat-messages?week=2026-W21")
    assert resp.status_code == 404


def test_get_chat_messages_defaults_to_current_week(api_client, sample_chat_page_with_messages):
    page_id = sample_chat_page_with_messages
    resp = api_client.get(f"/api/whop/pages/{page_id}/chat-messages")
    assert resp.status_code == 200
    # week.start should be a Monday 00:00 UTC of "current ISO week"; assertion
    # left loose to avoid time-flake — just confirm fields exist:
    assert "start" in resp.json()["week"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py -v
```

Expected: All 4 new tests FAIL with `404` (endpoint doesn't exist).

- [ ] **Step 3: Add the endpoint in `backend/app/api/http.py`**

Insert near the existing `/api/whop/pages` endpoints (around line 1330):

```python
        @router.get("/api/whop/pages/{page_id}/chat-messages")
        async def get_chat_messages(
            page_id: str,
            week: str | None = None,
            senders: str | None = None,
        ) -> ChatMessagesOut:
            page = await whop_registry.get_page(page_id)
            if page is None:
                raise HTTPException(404, detail="page not found")

            week_start, week_end = _iso_week_bounds(week)
            sender_list = (
                [s.strip() for s in senders.split(",") if s.strip()]
                if senders else None
            )

            async with session_scope(session_factory) as s:
                rows = await repo.list_chat_messages(
                    s, page_id, week_start, week_end, sender_list,
                )
                authors = await repo.list_chat_authors(s, page_id, week_start, week_end)

            return ChatMessagesOut(
                messages=[_row_to_chat_out(r) for r in rows],
                authors=[ChatAuthorOut(name=a, count=c) for a, c in authors],
                week=ChatWeekWindowOut(start=week_start, end=week_end),
            )
```

Add the two helpers in the same file (top-level or in a small `_chat_helpers` module):

```python
def _iso_week_bounds(week: str | None) -> tuple[datetime, datetime]:
    """Return [start, end) for an ISO week label like "2026-W21".

    ``None`` means the current week (UTC).
    """
    if week is None:
        now = datetime.now(timezone.utc)
        iso_year, iso_week, _ = now.isocalendar()
    else:
        # parse "YYYY-Www"
        try:
            year_s, week_s = week.split("-W", 1)
            iso_year, iso_week = int(year_s), int(week_s)
        except (ValueError, IndexError) as e:
            raise HTTPException(400, detail=f"invalid week: {week}") from e

    # Monday of the ISO week:
    monday = datetime.fromisocalendar(iso_year, iso_week, 1).replace(tzinfo=timezone.utc)
    return monday, monday + timedelta(days=7)


def _row_to_chat_out(row: ChatMessageRow) -> ChatMessageOut:
    quoted = None
    if row.quoted_author is not None:
        quoted = QuotedRefOut(
            message_id=row.quoted_message_id,
            author=row.quoted_author,
            content=row.quoted_content or "",
            posted_at=row.quoted_posted_at,
        )
    return ChatMessageOut(
        id=row.id, page_id=row.page_id, author=row.author,
        content=row.content, posted_at=row.posted_at,
        quoted=quoted,
    )
```

Ensure imports at top of `http.py`:

```python
from datetime import datetime, timedelta, timezone
from app.api.schemas import (
    ChatMessagesOut, ChatMessageOut, ChatAuthorOut, ChatWeekWindowOut, QuotedRefOut,
)
from app.storage.schema import ChatMessageRow
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_chat_messages_endpoint.py
git commit -m "feat(chat): GET /api/whop/pages/{page_id}/chat-messages endpoint"
```

---

## Phase 6 — Frontend pure logic (TDD-friendly)

### Task 15: `chatCards.ts` — grouping function

**Files:**
- Create: `frontend/src/components/Chat/chatCards.ts`
- Create: `frontend/src/components/Chat/chatCards.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Chat/chatCards.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { groupIntoCards, type ChatMessageOut } from "./chatCards";

function msg(
  id: string, author: string, posted_at: string,
  opts: { quoted?: { author: string; content: string } } = {},
): ChatMessageOut {
  return {
    id, page_id: "p1", author, content: `body ${id}`,
    posted_at,
    quoted: opts.quoted ? { message_id: null, ...opts.quoted, posted_at: null } : undefined,
  };
}

describe("groupIntoCards", () => {
  it("returns [] for empty input", () => {
    expect(groupIntoCards([], new Set(["alice"]), 5)).toEqual([]);
  });

  it("skips non-watched senders entirely", () => {
    const out = groupIntoCards(
      [msg("m1", "bob", "2026-05-18T09:00:00Z")],
      new Set(["alice"]),
      5,
    );
    expect(out).toEqual([]);
  });

  it("collapses consecutive unquoted msgs from one watched sender into one batch", () => {
    const msgs = ["09:00", "09:01", "09:02"].map((t, i) =>
      msg(`m${i}`, "alice", `2026-05-18T${t}:00Z`),
    );
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("batch");
    if (out[0].kind === "batch") {
      expect(out[0].msgs.map(m => m.id)).toEqual(["m0", "m1", "m2"]);
      expect(out[0].overflow).toBe(0);
      expect(out[0].id).toBe("batch:m0");
    }
  });

  it("caps batch at maxN and counts overflow", () => {
    const msgs = Array.from({ length: 7 }, (_, i) =>
      msg(`m${i}`, "alice", `2026-05-18T09:${String(i).padStart(2, "0")}:00Z`),
    );
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      expect(out[0].msgs).toHaveLength(5);
      expect(out[0].overflow).toBe(2);
    }
  });

  it("makes one quote card per quoted reply", () => {
    const m = msg("m1", "alice", "2026-05-18T09:00:00Z", {
      quoted: { author: "bob", content: "earlier" },
    });
    const out = groupIntoCards([m], new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe("quote");
    if (out[0].kind === "quote") {
      expect(out[0].id).toBe("m1");
      expect(out[0].quoted.author).toBe("bob");
    }
  });

  it("the 4+1+3 example splits into 3 cards (batch / quote / batch)", () => {
    const msgs = [
      ...["09:00", "09:01", "09:02", "09:03"].map((t, i) =>
        msg(`a${i}`, "alice", `2026-05-18T${t}:00Z`)),
      msg("q1", "alice", "2026-05-18T09:05:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
      ...["09:06", "09:07", "09:08"].map((t, i) =>
        msg(`b${i}`, "alice", `2026-05-18T${t}:00Z`)),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out.map(c => c.kind)).toEqual(["batch", "quote", "batch"]);
    if (out[0].kind === "batch") expect(out[0].msgs).toHaveLength(4);
    if (out[2].kind === "batch") expect(out[2].msgs).toHaveLength(3);
  });

  it("non-watched sender interleave does NOT split the batch", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("c1", "carol", "2026-05-18T09:02:00Z"),  // not watched
      msg("a2", "alice", "2026-05-18T09:03:00Z"),
      msg("a3", "alice", "2026-05-18T09:04:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice"]), 5);
    expect(out).toHaveLength(1);
    if (out[0].kind === "batch") {
      expect(out[0].msgs.map(m => m.id)).toEqual(["a0", "a1", "a2", "a3"]);
    }
  });

  it("two watched senders alternating split into per-author batches", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("b0", "bob", "2026-05-18T09:01:00Z"),
      msg("a1", "alice", "2026-05-18T09:02:00Z"),
      msg("b1", "bob", "2026-05-18T09:03:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set(["alice", "bob"]), 5);
    expect(out).toHaveLength(4);
    expect(out.every(c => c.kind === "batch")).toBe(true);
  });

  it("empty watchedSenders → treat all as watched", () => {
    const msgs = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("b0", "bob", "2026-05-18T09:01:00Z"),
    ];
    const out = groupIntoCards(msgs, new Set<string>(), 5);
    expect(out.length).toBeGreaterThan(0);
    // alice and bob both yield batches (different authors → 2 cards)
    expect(out).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm test -- chatCards.test.ts
```

Expected: FAIL — file does not exist.

- [ ] **Step 3: Implement `frontend/src/components/Chat/chatCards.ts`**

```ts
export interface QuotedRef {
  message_id: string | null;
  author: string;
  content: string;
  posted_at: string | null;
}

export interface ChatMessageOut {
  id: string;
  page_id: string;
  author: string;
  content: string;
  posted_at: string;
  quoted?: QuotedRef;
}

export type ChatCard =
  | {
      kind: "quote";
      id: string;           // = target.id
      target: ChatMessageOut;
      quoted: QuotedRef;
    }
  | {
      kind: "batch";
      id: string;           // = `batch:${msgs[0].id}`
      target_author: string;
      msgs: ChatMessageOut[];
      overflow: number;
    };

export function groupIntoCards(
  messages: ChatMessageOut[],
  watchedSenders: Set<string>,
  maxN: number,
): ChatCard[] {
  const out: ChatCard[] = [];
  let currentBatch: Extract<ChatCard, { kind: "batch" }> | null = null;

  const isWatched = (author: string): boolean =>
    watchedSenders.size === 0 || watchedSenders.has(author);

  for (const m of messages) {
    if (!isWatched(m.author)) continue;   // skip; do not break currentBatch

    if (m.quoted) {
      // close current batch (if any), push quote card
      if (currentBatch) {
        out.push(currentBatch);
        currentBatch = null;
      }
      out.push({
        kind: "quote",
        id: m.id,
        target: m,
        quoted: m.quoted,
      });
      continue;
    }

    // unquoted watched message
    const opensNewBatch =
      currentBatch === null || currentBatch.target_author !== m.author;
    if (opensNewBatch) {
      if (currentBatch) out.push(currentBatch);
      currentBatch = {
        kind: "batch",
        id: `batch:${m.id}`,
        target_author: m.author,
        msgs: [m],
        overflow: 0,
      };
    } else {
      if (currentBatch.msgs.length < maxN) {
        currentBatch.msgs.push(m);
      } else {
        currentBatch.overflow += 1;
      }
    }
  }

  if (currentBatch) out.push(currentBatch);
  return out;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && npm test -- chatCards.test.ts
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/chatCards.ts frontend/src/components/Chat/chatCards.test.ts
git commit -m "feat(chat): chatCards.ts — pure card grouping function"
```

---

### Task 16: `chatExport.ts` — JSON payload builder + download

**Files:**
- Create: `frontend/src/components/Chat/chatExport.ts`
- Create: `frontend/src/components/Chat/chatExport.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/Chat/chatExport.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import { buildExportPayload } from "./chatExport";
import { groupIntoCards, type ChatMessageOut } from "./chatCards";

function msg(id: string, author: string, posted_at: string,
             opts: { quoted?: { author: string; content: string } } = {}): ChatMessageOut {
  return {
    id, page_id: "p1", author, content: `body ${id}`, posted_at,
    quoted: opts.quoted ? { message_id: null, ...opts.quoted, posted_at: null } : undefined,
  };
}

describe("buildExportPayload", () => {
  it("emits card_index increasing from 0", () => {
    const messages = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("a1", "alice", "2026-05-18T09:01:00Z"),
      msg("q1", "alice", "2026-05-18T09:02:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
    ];
    const cards = groupIntoCards(messages, new Set(["alice"]), 5);
    const payload = buildExportPayload({
      page_id: "p1", page_name: "Test Page",
      week: { start: "2026-05-18", end: "2026-05-25" },
      watched_senders: ["alice"],
      messages, cards,
    });
    expect(payload.cards.map((c) => c.card_index)).toEqual([0, 1]);
  });

  it("messages preserve order and carry card_index", () => {
    const messages = [
      msg("a0", "alice", "2026-05-18T09:00:00Z"),
      msg("q1", "alice", "2026-05-18T09:02:00Z", {
        quoted: { author: "bob", content: "earlier" },
      }),
    ];
    const cards = groupIntoCards(messages, new Set(["alice"]), 5);
    const payload = buildExportPayload({
      page_id: "p1", page_name: "Test", week: { start: "x", end: "y" },
      watched_senders: ["alice"], messages, cards,
    });
    expect(payload.messages.map(m => m.id)).toEqual(["a0", "q1"]);
    expect(payload.messages[0].card_index).toBe(0);
    expect(payload.messages[1].card_index).toBe(1);
  });

  it("excludes overflow msgs from the messages array", () => {
    // 7 unquoted msgs, maxN=5 → 5 visible + 2 overflow; export drops the 2.
    const messages = Array.from({ length: 7 }, (_, i) =>
      msg(`m${i}`, "alice", `2026-05-18T09:0${i}:00Z`));
    const cards = groupIntoCards(messages, new Set(["alice"]), 5);
    const payload = buildExportPayload({
      page_id: "p1", page_name: "Test", week: { start: "x", end: "y" },
      watched_senders: ["alice"], messages, cards,
    });
    expect(payload.messages).toHaveLength(5);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && npm test -- chatExport.test.ts
```

Expected: FAIL — file does not exist.

- [ ] **Step 3: Implement `frontend/src/components/Chat/chatExport.ts`**

```ts
import type { ChatCard, ChatMessageOut } from "./chatCards";

export interface ExportPayloadInput {
  page_id: string;
  page_name: string;
  week: { start: string; end: string };
  watched_senders: string[];
  messages: ChatMessageOut[];
  cards: ChatCard[];
}

export interface ExportPayload {
  page_id: string;
  page_name: string;
  exported_at: string;
  week: { start: string; end: string };
  watched_senders: string[];
  cards: ExportCard[];
  messages: ExportMessage[];
}

type ExportCard =
  | { card_index: number; kind: "batch"; target_author: string;
      msg_ids: string[]; overflow: number }
  | { card_index: number; kind: "quote"; target_msg_id: string;
      quoted: { author: string; content: string; posted_at: string | null;
                message_id: string | null } };

interface ExportMessage extends ChatMessageOut {
  card_index: number;
}

export function buildExportPayload(input: ExportPayloadInput): ExportPayload {
  const cardsOut: ExportCard[] = [];
  const messageIndex = new Map<string, number>();

  input.cards.forEach((card, idx) => {
    if (card.kind === "batch") {
      cardsOut.push({
        card_index: idx, kind: "batch",
        target_author: card.target_author,
        msg_ids: card.msgs.map(m => m.id),
        overflow: card.overflow,
      });
      for (const m of card.msgs) messageIndex.set(m.id, idx);
    } else {
      cardsOut.push({
        card_index: idx, kind: "quote",
        target_msg_id: card.target.id,
        quoted: { ...card.quoted },
      });
      messageIndex.set(card.target.id, idx);
    }
  });

  const messagesOut: ExportMessage[] = input.messages
    .filter(m => messageIndex.has(m.id))
    .map(m => ({ ...m, card_index: messageIndex.get(m.id)! }));

  return {
    page_id: input.page_id,
    page_name: input.page_name,
    exported_at: new Date().toISOString(),
    week: input.week,
    watched_senders: input.watched_senders,
    cards: cardsOut,
    messages: messagesOut,
  };
}

export function triggerJsonDownload(filename: string, payload: ExportPayload): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)],
                       { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), {
    href: url, download: filename,
  });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd frontend && npm test -- chatExport.test.ts
```

Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/chatExport.ts frontend/src/components/Chat/chatExport.test.ts
git commit -m "feat(chat): chatExport.ts — JSON payload builder + download trigger"
```

---

### Task 17: `frontend/src/api/chat.ts` — thin API client

**Files:**
- Create: `frontend/src/api/chat.ts`

- [ ] **Step 1: Look at an existing api client to match style**

Read `frontend/src/api/index.ts` or `frontend/src/api/*.ts` for the existing wrapper pattern (typically thin `fetch` wrappers around the typed `WhopPage` etc.).

- [ ] **Step 2: Implement**

```ts
import type { ChatMessageOut } from "../components/Chat/chatCards";

export interface ChatMessagesResponse {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  week: { start: string; end: string };
}

export async function listChatMessages(
  pageId: string,
  week: string | null,
  senders: string[],
): Promise<ChatMessagesResponse> {
  const params = new URLSearchParams();
  if (week) params.set("week", week);
  if (senders.length) params.set("senders", senders.join(","));
  const qs = params.toString();
  const url = `/api/whop/pages/${encodeURIComponent(pageId)}/chat-messages${qs ? `?${qs}` : ""}`;
  const resp = await fetch(url, { credentials: "include" });
  if (!resp.ok) throw new Error(`listChatMessages ${pageId}: ${resp.status}`);
  return resp.json();
}

export async function patchWatchedSenders(
  pageId: string,
  watchedSenders: string[],
): Promise<void> {
  const resp = await fetch(`/api/whop/pages/${encodeURIComponent(pageId)}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({ watched_senders: watchedSenders }),
  });
  if (!resp.ok) throw new Error(`patchWatchedSenders ${pageId}: ${resp.status}`);
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/chat.ts
git commit -m "feat(chat): API client wrappers — listChatMessages / patchWatchedSenders"
```

---

### Task 18: `chatStore.ts` — per-(page, week) cache + WS apply

**Files:**
- Create: `frontend/src/stores/chatStore.ts`

- [ ] **Step 1: Look at an existing store to match style**

Read `frontend/src/stores/pageTabs.ts` for the zustand pattern used in this project.

- [ ] **Step 2: Implement**

```ts
import { create } from "zustand";
import { listChatMessages, type ChatMessagesResponse } from "../api/chat";
import type { ChatMessageOut } from "../components/Chat/chatCards";

interface CacheKey {
  pageId: string;
  week: string;
}

interface ChatCache {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  week: { start: string; end: string };
  fetchedAt: number;
}

interface ChatStore {
  // key = `${pageId}|${week}`
  caches: Record<string, ChatCache>;
  fetch: (pageId: string, week: string, senders: string[]) => Promise<void>;
  applyStoredMessage: (
    pageId: string, week: string, message: ChatMessageOut,
  ) => void;
}

const k = (pageId: string, week: string) => `${pageId}|${week}`;

export const useChatStore = create<ChatStore>((set, get) => ({
  caches: {},

  fetch: async (pageId, week, senders) => {
    const r: ChatMessagesResponse = await listChatMessages(pageId, week, senders);
    set((state) => ({
      caches: {
        ...state.caches,
        [k(pageId, week)]: {
          messages: r.messages, authors: r.authors, week: r.week,
          fetchedAt: Date.now(),
        },
      },
    }));
  },

  applyStoredMessage: (pageId, week, message) => {
    const key = k(pageId, week);
    const existing = get().caches[key];
    if (!existing) return;
    // Insert in posted_at-sorted position; dedupe by id.
    if (existing.messages.some((m) => m.id === message.id)) return;
    const next = [...existing.messages, message].sort(
      (a, b) => a.posted_at.localeCompare(b.posted_at),
    );
    set((state) => ({
      caches: { ...state.caches, [key]: { ...existing, messages: next } },
    }));
  },
}));
```

The WS subscription is wired in `ChatBoardPanel` (Task 22) where the component knows the active `pageId` + `week`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/stores/chatStore.ts
git commit -m "feat(chat): chatStore — per-(page, week) cache + WS apply hook"
```

---

### Task 19: Regenerate OpenAPI types

**Files:**
- Modify: `frontend/src/api/types.ts` (regenerated from backend OpenAPI schema)
- The hand-written wrapper `frontend/src/api/domain-types.ts:118-128` consumes
  `components["schemas"]["WhopPageCreate"]` from `types.ts`, so it picks up
  the literal change automatically once `types.ts` is regenerated.

- [ ] **Step 1: Regenerate types**

```bash
cd frontend && npm run gen:types
```

This runs `uv run --project ../backend python ../scripts/dump_openapi.py ./openapi.json && openapi-typescript ./openapi.json -o src/api/types.ts` (per `frontend/package.json:13`).

- [ ] **Step 2: Verify the regenerated types include "chat"**

```bash
cd frontend && grep -n '"chat"' src/api/types.ts | head
```

Expected: at least one match showing `"stock" | "option" | "chat"` in `WhopPageCreate.source`.

- [ ] **Step 3: Type-check the frontend**

```bash
cd frontend && npm run typecheck    # or: npx tsc --noEmit
```

Expected: No type errors. Any consumer of `WhopPage.source` that was narrowing to just `"stock" | "option"` will now need a third branch — fix those locally (the dispatch in Task 24 already adds the `=== "chat"` branch, so this should be clean).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/types.ts frontend/openapi.json
git commit -m "feat(chat): regenerate OpenAPI types — source includes 'chat'"
```

---

## Phase 7 — Frontend UI components

### Task 20: `ChatCard.tsx` — renders quote + batch cards

**Files:**
- Create: `frontend/src/components/Chat/ChatCard.tsx`
- Create: `frontend/src/components/Chat/ChatBoardPanel.css`

- [ ] **Step 1: Implement `ChatCard.tsx`**

```tsx
import React from "react";
import type { ChatCard as ChatCardData } from "./chatCards";

interface Props {
  card: ChatCardData;
}

export function ChatCard({ card }: Props): JSX.Element {
  if (card.kind === "quote") {
    return (
      <div className="chat-card" data-kind="quote">
        <div className="chat-card-head">
          <span className="chat-avatar chat-avatar-target">
            {card.target.author.slice(-1)}
          </span>
          <span className="chat-card-sender">{card.target.author}</span>
          <span className="chat-card-badge">引用</span>
          <span className="chat-card-time">
            {fmtTime(card.target.posted_at)}
          </span>
        </div>
        <div className="chat-thread">
          <div className="chat-row chat-row-left">
            <span className="chat-avatar-sm">
              {card.quoted.author.slice(-1)}
            </span>
            <div className="chat-bubble chat-bubble-left">
              <div>{card.quoted.content}</div>
              <div className="chat-bubble-meta">
                <span className="chat-sender-tag">{card.quoted.author}</span>
                {card.quoted.posted_at && (
                  <span>{fmtTime(card.quoted.posted_at)}</span>
                )}
              </div>
            </div>
          </div>
          <div className="chat-row chat-row-right">
            <div className="chat-bubble chat-bubble-right">
              <div>{card.target.content}</div>
              <div className="chat-bubble-meta">
                <span>{fmtTime(card.target.posted_at)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-card" data-kind="batch">
      <div className="chat-card-head">
        <span className="chat-avatar chat-avatar-target">
          {card.target_author.slice(-1)}
        </span>
        <span className="chat-card-sender">{card.target_author}</span>
        <span className="chat-card-msg-count">{card.msgs.length}</span>
        <span className="chat-card-time">
          {fmtTime(card.msgs[card.msgs.length - 1].posted_at)}
        </span>
      </div>
      <div className="chat-thread">
        {card.msgs.map((m) => (
          <div key={m.id} className="chat-row chat-row-right">
            <div className="chat-bubble chat-bubble-right">
              <div>{m.content}</div>
              <div className="chat-bubble-meta">
                <span>{fmtTime(m.posted_at)}</span>
              </div>
            </div>
          </div>
        ))}
        {card.overflow > 0 && (
          <div className="chat-overflow">+{card.overflow} 更多</div>
        )}
      </div>
    </div>
  );
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
```

- [ ] **Step 2: Implement `ChatBoardPanel.css`**

Mirror the CSS from `.design/chat-monitor-variants.html` for variant C (`.board.variant-c`), namespaced under `.chat-board`. Copy the bubble/card/thread styles from the variant-C section. Use the same tokens (`--bg-1` / `--brand` / etc.) — they're already imported globally via `tokens.css`.

```css
.chat-board {
  display: flex; flex-direction: column;
  gap: 14px;
  max-width: 880px;
  margin: 0 auto;
  padding: 14px;
}

.chat-card {
  background: var(--bg-1);
  border: 1px solid var(--line);
  border-radius: var(--radius-card);
  overflow: hidden;
}

.chat-card-head {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px;
  background: var(--bg-2);
  border-bottom: 1px solid var(--line);
}

.chat-avatar, .chat-avatar-sm {
  border-radius: 50%;
  display: grid; place-items: center;
  color: var(--bg-0); font-weight: 600;
}
.chat-avatar { width: 22px; height: 22px; font-size: 10px; }
.chat-avatar-sm { width: 18px; height: 18px; font-size: 9px;
                  background: var(--bg-3); color: var(--fg-2); }
.chat-avatar-target { background: var(--brand); }

.chat-card-sender { font-size: 12px; color: var(--fg-1); font-weight: 500; }
.chat-card-time   { margin-left: auto; font-family: var(--font-mono);
                    font-size: 10.5px; color: var(--fg-3); }
.chat-card-msg-count { background: var(--bg-3); color: var(--fg-2);
                       padding: 1px 6px; border-radius: 3px; font-size: 10px; }
.chat-card-badge { font-size: 9.5px; letter-spacing: 0.06em;
                   text-transform: uppercase; color: var(--warn);
                   background: rgba(231,167,61,0.10);
                   border: 1px solid rgba(231,167,61,0.32);
                   padding: 1px 6px; border-radius: 3px; }

.chat-thread { padding: 10px 12px; display: flex; flex-direction: column;
               gap: 8px; }

.chat-row { display: flex; gap: 8px; align-items: flex-end; }
.chat-row-right { justify-content: flex-end; }

.chat-bubble { position: relative; max-width: 78%; padding: 6px 10px;
               border-radius: 8px; font-size: 12px; line-height: 1.5;
               word-break: break-word; }
.chat-bubble-left  { background: var(--bg-2); border: 1px solid var(--line);
                     border-bottom-left-radius: 2px; color: var(--fg-1); }
.chat-bubble-right { background: rgba(var(--brand-rgb), 0.10);
                     border: 1px solid rgba(var(--brand-rgb), 0.32);
                     border-bottom-right-radius: 2px; color: var(--fg-1); }
.chat-bubble-meta { margin-top: 4px; font-family: var(--font-mono);
                    font-size: 9.5px; color: var(--fg-3);
                    display: flex; gap: 6px; justify-content: flex-end; }
.chat-sender-tag { color: var(--fg-2); }

.chat-overflow { font-family: var(--font-mono); font-size: 11px;
                 color: var(--fg-3); padding-left: 4px; }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Chat/ChatCard.tsx frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "feat(chat): ChatCard component + CSS"
```

---

### Task 21: `ChatSenderBar.tsx` — sender filter chips

**Files:**
- Create: `frontend/src/components/Chat/ChatSenderBar.tsx`

- [ ] **Step 1: Implement**

```tsx
import React from "react";
import { patchWatchedSenders } from "../../api/chat";

interface Author { name: string; count: number; }

interface Props {
  pageId: string;
  authors: Author[];
  watchedSenders: string[];
  onChange: (next: string[]) => void;
}

export function ChatSenderBar({ pageId, authors, watchedSenders, onChange }: Props) {
  const watched = new Set(watchedSenders);
  async function toggle(name: string) {
    const next = watched.has(name)
      ? watchedSenders.filter((s) => s !== name)
      : [...watchedSenders, name];
    onChange(next);
    try { await patchWatchedSenders(pageId, next); } catch { /* surfaced via store later */ }
  }

  return (
    <div className="chat-sender-bar">
      <span className="chat-sender-bar-label">发送者</span>
      {authors.map((a) => {
        const on = watched.has(a.name);
        return (
          <button
            key={a.name}
            className={`chat-sender-chip${on ? " on" : ""}`}
            onClick={() => toggle(a.name)}
            type="button"
          >
            <span className="chat-sender-chip-avatar">{a.name.slice(-1)}</span>
            {a.name}
            <span className="chat-sender-chip-count">· {a.count}</span>
          </button>
        );
      })}
    </div>
  );
}
```

Append to `ChatBoardPanel.css`:

```css
.chat-sender-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
                   padding: 8px 14px; border-bottom: 1px solid var(--line);
                   background: var(--bg-1); }
.chat-sender-bar-label { font-size: 10.5px; letter-spacing: 0.06em;
                         text-transform: uppercase; color: var(--fg-3); }
.chat-sender-chip { display: inline-flex; align-items: center; gap: 6px;
                    padding: 3px 10px; border-radius: 999px;
                    border: 1px solid var(--line-strong); background: transparent;
                    color: var(--fg-2); font-family: var(--font-mono);
                    font-size: 11px; cursor: pointer;
                    transition: all 150ms cubic-bezier(0.2,0.6,0.2,1); }
.chat-sender-chip:hover { border-color: var(--fg-3); color: var(--fg-1); }
.chat-sender-chip.on { border-color: rgba(var(--brand-rgb), 0.50);
                       background: rgba(var(--brand-rgb), 0.10);
                       color: var(--brand); }
.chat-sender-chip-avatar { width: 14px; height: 14px; border-radius: 50%;
                           background: var(--bg-3); display: grid; place-items: center;
                           font-size: 9px; color: var(--fg-2);
                           font-family: var(--font-sans); }
.chat-sender-chip.on .chat-sender-chip-avatar { background: var(--brand);
                                                color: var(--bg-0); }
.chat-sender-chip-count { font-size: 10px; color: var(--fg-3); }
.chat-sender-chip.on .chat-sender-chip-count { color: var(--brand); opacity: 0.7; }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Chat/ChatSenderBar.tsx frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "feat(chat): ChatSenderBar — sender filter chips"
```

---

### Task 22: `ChatMetaBar.tsx` — chat-specific meta + export button

**Files:**
- Create: `frontend/src/components/Chat/ChatMetaBar.tsx`

- [ ] **Step 1: Implement**

```tsx
import React from "react";

interface Props {
  messageCount: number;
  watchedCount: number;
  onExport: () => void;
}

export function ChatMetaBar({ messageCount, watchedCount, onExport }: Props) {
  return (
    <div className="chat-meta-bar">
      <span className="chat-meta-text">
        本周抓取 <strong>{messageCount}</strong> 条
        · 关注 <strong>{watchedCount}</strong> 位发送者
      </span>
      <button className="chat-meta-export" onClick={onExport} type="button">
        导出 JSON
      </button>
    </div>
  );
}
```

Append to `ChatBoardPanel.css`:

```css
.chat-meta-bar { display: flex; align-items: center; gap: 12px;
                 padding: 8px 14px; border-bottom: 1px solid var(--line);
                 background: var(--bg-1); }
.chat-meta-text { font-size: 12px; color: var(--fg-2); }
.chat-meta-text strong { color: var(--fg-1); font-weight: 500;
                         font-family: var(--font-mono); }
.chat-meta-export { margin-left: auto; background: rgba(var(--brand-rgb), 0.10);
                    border: 1px solid rgba(var(--brand-rgb), 0.42);
                    color: var(--brand); padding: 4px 10px;
                    cursor: pointer; border-radius: var(--radius-chip);
                    font-size: 12px; font: inherit;
                    transition: background 150ms, border-color 150ms; }
.chat-meta-export:hover { background: rgba(var(--brand-rgb), 0.18);
                          border-color: var(--brand); }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Chat/ChatMetaBar.tsx frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "feat(chat): ChatMetaBar — meta info + export JSON button"
```

---

### Task 23: `ChatBoardPanel.tsx` — composes everything

**Files:**
- Create: `frontend/src/components/Chat/ChatBoardPanel.tsx`

- [ ] **Step 1: Implement**

```tsx
import React, { useEffect, useMemo } from "react";
import type { WhopPage } from "../../api/domain-types";
import { useChatStore } from "../../stores/chatStore";
import { groupIntoCards } from "./chatCards";
import { buildExportPayload, triggerJsonDownload } from "./chatExport";
import { ChatCard } from "./ChatCard";
import { ChatSenderBar } from "./ChatSenderBar";
import { ChatMetaBar } from "./ChatMetaBar";
import "./ChatBoardPanel.css";

interface Props {
  page: WhopPage;
  week: string;                  // e.g., "2026-W21"
}

export function ChatBoardPanel({ page, week }: Props) {
  const cache = useChatStore((s) => s.caches[`${page.id}|${week}`]);
  const fetch = useChatStore((s) => s.fetch);

  const watchedSenders = page.settings.watched_senders ?? [];
  const maxN = page.settings.chat_card_max_msgs ?? 5;

  useEffect(() => {
    fetch(page.id, week, watchedSenders);
  }, [page.id, week, fetch]);   // intentionally NOT depending on watchedSenders — we filter client-side too

  const messages = cache?.messages ?? [];
  const authors = cache?.authors ?? [];

  const cards = useMemo(
    () => groupIntoCards(messages, new Set(watchedSenders), maxN),
    [messages, watchedSenders, maxN],
  );

  function handleExport() {
    const payload = buildExportPayload({
      page_id: page.id,
      page_name: page.name ?? page.url,
      week: cache?.week ?? { start: "", end: "" },
      watched_senders: watchedSenders,
      messages,
      cards,
    });
    triggerJsonDownload(`chat-${page.id}-${week}.json`, payload);
  }

  function handleSenderChange(_next: string[]) {
    // PATCH already fired in ChatSenderBar. Optimistic UI update is handled by
    // the parent store when the page settings refresh after PATCH success;
    // for now, re-fetch to pick up the new server-side filter.
    fetch(page.id, week, _next);
  }

  return (
    <div className="chat-panel">
      <ChatMetaBar
        messageCount={messages.length}
        watchedCount={watchedSenders.length}
        onExport={handleExport}
      />
      <ChatSenderBar
        pageId={page.id}
        authors={authors}
        watchedSenders={watchedSenders}
        onChange={handleSenderChange}
      />
      <div className="chat-board">
        {cards.length === 0
          ? <div className="chat-empty">本周无聊天消息 · 切换周或调整发送者过滤</div>
          : cards.map((c) => <ChatCard key={c.id} card={c} />)}
      </div>
    </div>
  );
}
```

Append to `ChatBoardPanel.css`:

```css
.chat-panel { display: flex; flex-direction: column; height: 100%;
              min-height: 0; }
.chat-panel .chat-board { flex: 1; min-height: 0; overflow-y: auto; }
.chat-empty { padding: 60px 20px; text-align: center; color: var(--fg-2); }
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/Chat/ChatBoardPanel.tsx frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "feat(chat): ChatBoardPanel — compose meta + senders + cards"
```

---

### Task 24: Dispatch ChatBoardPanel from App.tsx

**Files:**
- Modify: `frontend/src/App.tsx:~303`

- [ ] **Step 1: Find the current render site**

Read `frontend/src/App.tsx:295-315` to find where the current task stream / panel is rendered for the active page.

- [ ] **Step 2: Add the dispatch**

Replace the existing single-component render with a conditional:

```tsx
{activePage.source === "chat" ? (
  <ChatBoardPanel page={activePage} week={activeWeek} />
) : (
  /* existing render path — TaskStream / DatabaseRecordsPanel */
  <TaskStream ... />
)}
```

Add the import at the top of `App.tsx`:

```tsx
import { ChatBoardPanel } from "./components/Chat/ChatBoardPanel";
```

The `activeWeek` value should come from the existing WeekPaginator state — locate where it's stored (likely in a store or local state in the Dashboard component) and pass it through.

- [ ] **Step 3: Subscribe to WS for chat updates**

In the same component, subscribe to the WS bridge for `chat.message_stored` events and call `chatStore.applyStoredMessage`. The existing WS subscription block in `App.tsx` (or its store) handles other topics — add a new case:

```tsx
// inside the existing WS dispatch switch / handler:
if (event.topic === "chat.message_stored") {
  const { page_id, message_id } = event.payload;
  // Need the full message — refetch the cache for that page+week:
  const week = useChatStore.getState().getActiveWeekFor(page_id);  // or pass via context
  if (week) useChatStore.getState().fetch(page_id, week, []);
}
```

(The simplest implementation: re-fetch the cache for the affected page on each WS notification. Optimization to apply individual messages can come later.)

- [ ] **Step 4: Smoke test in dev mode**

```bash
cd frontend && npm run dev
```

Manually navigate to a chat-source page (create one via the existing UI). The `ChatBoardPanel` should render. Until backend has data, you'll see the empty-state message.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(chat): Dashboard dispatches ChatBoardPanel for source=='chat'"
```

---

### Task 25: PageTabs dot color for chat

**Files:**
- Modify: `frontend/src/components/Dashboard/Dashboard.css:11-13`

- [ ] **Step 1: Add CSS**

After line 13 of `frontend/src/components/Dashboard/Dashboard.css`:

```css
.tab-source-dot.chat { background: #c688ff; }
```

(Matches the design HTML's chat-purple `#c688ff`.)

- [ ] **Step 2: Verify the dot renders**

In `frontend/src/components/Dashboard/PageTabs.tsx:13-24`, the existing code does `<span className={`tab-source-dot ${p.source}`} />`. Since `p.source` is now also `"chat"`, the new CSS rule applies automatically. No TS change needed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Dashboard/Dashboard.css
git commit -m "feat(chat): page tab dot color for chat pages"
```

---

## Phase 8 — PageSettingsModal extensions

### Task 26: Disable `source` field for existing pages + add chat fields

**Files:**
- Modify: `frontend/src/components/Dashboard/PageSettingsModal.tsx`

- [ ] **Step 1: Disable `source` field on existing pages**

Find the input/select for `source` in `PageSettingsModal.tsx`. Add `disabled={!!page.id}` so the source can only be set when creating a new page.

(Read the file first — the modal might be used only for editing existing pages, in which case the source field may not even be there. If it's not present, this step is a no-op.)

- [ ] **Step 2: Add `watched_senders` editor for chat pages**

Inside the existing `if (page.source === "option") { ... }` block, add a parallel block:

```tsx
{page.source === "chat" && (
  <>
    <SettingRow label="关注的发送者（白名单）">
      <ChipEditor
        values={settings.watched_senders ?? []}
        onChange={(next) => patchSetting({ watched_senders: next })}
        placeholder="新增发送者名…"
      />
    </SettingRow>
    <SettingRow label="每张卡片最多展示消息数">
      <input
        type="number"
        min={1} max={50}
        value={settings.chat_card_max_msgs ?? 5}
        onChange={(e) => patchSetting({ chat_card_max_msgs: Number(e.target.value) })}
      />
    </SettingRow>
  </>
)}
```

If `ChipEditor` doesn't exist, write a minimal inline version (an input that pushes on Enter, plus removable chips). For consistency with existing `PageWhitelistBar`, you can lift its inline-edit pattern.

- [ ] **Step 3: Smoke test**

Open the settings modal for a chat page in dev mode; verify the two new controls appear and PATCH the settings on change.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Dashboard/PageSettingsModal.tsx
git commit -m "feat(chat): PageSettingsModal — watched_senders + chat_card_max_msgs"
```

---

## Phase 9 — Verification

### Task 27: Self-review the full diff

- [ ] **Step 1: Diff summary**

```bash
git log --oneline main..HEAD
git diff --stat main..HEAD
```

Read the file list. Verify only files in the **File map** at the top of this plan were touched.

- [ ] **Step 2: Run full backend test suite**

```bash
cd backend && uv run pytest -v
```

Expected: All tests pass (existing + new).

- [ ] **Step 3: Run full frontend test suite**

```bash
cd frontend && npm test
```

Expected: All tests pass.

- [ ] **Step 4: TypeScript type check**

```bash
cd frontend && npm run typecheck    # or `tsc --noEmit`
```

Expected: No type errors.

### Task 28: Manual smoke test

- [ ] **Step 1: Start backend + frontend in dev mode**

Two terminals:
```bash
cd backend && uv run uvicorn app.main:app --reload
cd frontend && npm run dev
```

- [ ] **Step 2: Create a chat page via UI**

In the dashboard, click the "+" tab to add a new whop page. Set source = `"chat"` and provide a URL. Verify the new page appears in PageTabs with the purple dot.

- [ ] **Step 3: Verify empty state**

Select the new chat page. `ChatBoardPanel` should render the "本周无聊天消息" empty state.

- [ ] **Step 4: Verify settings**

Open settings for the chat page. Add a few sender names to `watched_senders`. Set `chat_card_max_msgs` to 3.

- [ ] **Step 5: Seed test data (manual SQL)**

```bash
cd backend && uv run python -c "
import asyncio
from datetime import datetime, timezone
from app.storage.db import async_session_factory
from app.storage import repo
from app.storage.schema import ChatMessageRow

async def main():
    factory = async_session_factory()
    async with factory() as s:
        for i, (author, text) in enumerate([
            ('alice', 'first message'),
            ('alice', 'second'),
            ('bob', 'third'),
            ('alice', 'reply to carol'),
        ]):
            row = ChatMessageRow(
                id=f'test-m{i}',
                page_id='<YOUR_CHAT_PAGE_ID>',
                author=author, content=text, raw_content=text,
                posted_at=datetime.now(timezone.utc),
                received_at=datetime.now(timezone.utc),
                url='https://example/p',
                quoted_message_id=None,
                quoted_author='carol' if i == 3 else None,
                quoted_content='earlier carol msg' if i == 3 else None,
                quoted_posted_at=datetime.now(timezone.utc) if i == 3 else None,
            )
            await repo.upsert_chat_message(s, row)
        await s.commit()

asyncio.run(main())
"
```

(Substitute `<YOUR_CHAT_PAGE_ID>` with the actual id from `GET /api/whop/pages`.)

- [ ] **Step 6: Reload UI, verify cards**

Refresh the panel. You should see:
- 1 batch card with `alice`'s 2 unquoted messages
- 1 quote card with alice quoting carol
- Bob's message is filtered out unless bob is in watched_senders

- [ ] **Step 7: Verify export**

Click "导出 JSON". A file `chat-<page-id>-2026-W21.json` should download. Open it and verify:
- `cards` array has 2 entries with correct `card_index`
- `messages` array carries `card_index` per message

- [ ] **Step 8: Cleanup**

Delete the test chat page via the UI. Verify with:

```bash
cd backend && uv run python -c "
import asyncio
from app.storage.db import async_session_factory
from sqlalchemy import select, func
from app.storage.schema import ChatMessageRow

async def main():
    factory = async_session_factory()
    async with factory() as s:
        result = await s.execute(select(func.count(ChatMessageRow.id)))
        print('chat_messages count:', result.scalar())

asyncio.run(main())
"
```

Expected: `chat_messages count: 0`.

---

## Self-review checklist (spec coverage)

| Spec section | Covered by task(s) |
|---|---|
| 数据模型 — chat_messages table | Task 2, 3 |
| 数据模型 — PageSettings 新字段 | Task 5, 6 |
| 数据模型 — 与 messages 表独立 | Task 2 (no FK to tasks) |
| 抓取与写入 — listener 分流 | Task 9 |
| 抓取与写入 — chat_writer | Task 8 |
| 抓取与写入 — quote denorm | Task 8 (test covers it) |
| 抓取与写入 — 幂等 upsert | Task 4 (idempotent test), Task 8 |
| 抓取与写入 — historical 不广播 | Task 8 |
| 抓取与写入 — repo 函数 4 个 | Task 4 |
| 抓取与写入 — WS 桥接 | Task 12 |
| 抓取与写入 — 页面删除清理 | Task 11 |
| 抓取与写入 — alembic 迁移 | Task 3 |
| API — GET endpoint | Task 14 |
| API — POST 接受 chat | Task 5 |
| API — PATCH 不允许改 source | Task 7 |
| API — schemas | Task 13 |
| 前端 — ChatBoardPanel | Task 23 |
| 前端 — ChatMetaBar | Task 22 |
| 前端 — ChatSenderBar | Task 21 |
| 前端 — ChatCard | Task 20 |
| 前端 — chatCards 分组规则 | Task 15 |
| 前端 — chatExport 导出 | Task 16 |
| 前端 — chatStore | Task 18 |
| 前端 — api/chat client | Task 17 |
| 前端 — App.tsx dispatch | Task 24 |
| 前端 — PageTabs dot color | Task 25 |
| 前端 — PageSettingsModal 扩展 | Task 26 |
| 错误/边界 — 全表 | Test cases in Tasks 4, 8, 14, 15 |
| 测试 — 后端单测 | Tasks 1, 4, 8, 9, 14 |
| 测试 — 前端单测 | Tasks 15, 16 |
| 测试 — e2e | Task 28 (manual) |
