# Chat Image Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse, persist, serve, and render images attached to Whop chat messages — end-to-end through extractor → DB → API → React bubble.

**Architecture:** Live extractor pulls the `<img>` URL from `[data-attachment-id]` blocks and attaches it to the domain `Message`. The chat-writer subscriber downloads the image at scrape time (signed S3 URLs expire in ~24h, so we cache locally) and stores the filename on `ChatMessageRow`. A new `/api/chat-images/{message_id}` route serves the file. The frontend `ChatMessageOut` type carries `image_url`, and `PlainBubble` / `ChatCard` render an `<img>` inside the existing bubble.

**Tech Stack:** Python (FastAPI, SQLAlchemy 2.x async, BeautifulSoup, httpx, pytest), TypeScript (React, Vitest).

**Spec:** `docs/superpowers/specs/2026-05-21-chat-image-support-design.md`

---

## Task Overview

| # | Task | Layer |
|---|---|---|
| 1 | Add `image_url` field to domain `Message` | Backend domain |
| 2 | Extract image URL in `backend/app/whop/extractor.py` | Backend scrape |
| 3 | Add `image_filename` column to `ChatMessageRow` + migration | Backend storage |
| 4 | Implement `_download_image` and wire into `chat_writer._handler` | Backend writer |
| 5 | Expose `image_url` in API response + new `/api/chat-images/{id}` route | Backend API |
| 6 | Add `image_url` field to frontend `ChatMessageOut` type | Frontend type |
| 7 | Render image in `PlainBubble` | Frontend UI |
| 8 | Wire `image_url` through `ChatMessage` and `ChatCard` callers | Frontend UI |
| 9 | Add bubble image CSS | Frontend styles |

---

## Task 1: Add `image_url` field to domain `Message`

**Files:**
- Modify: `backend/app/domain/message.py`
- Test: `backend/tests/domain/test_message.py` *(or wherever existing domain tests live — see Step 1 discovery)*

The domain `Message` dataclass is frozen and uses default values for optional fields (current source: `id, content, raw_content, author, posted_at, received_at, source, url=None, quoted=None, history_hint=[]`). We add a transient `image_url: str | None = None` — transient because it's only carried on the `CHAT_MESSAGE_RECEIVED` event and never persisted directly (the writer downloads it and stores `image_filename` instead).

- [ ] **Step 1: Locate the existing domain test file**

Run: `grep -rln "from app.domain.message\|from backend.app.domain.message" --include="*.py" | head`
Identify the file that already constructs `Message(...)` in a test. Use that file (or create `backend/tests/domain/test_message_image.py` if no dedicated `Message` test exists).

- [ ] **Step 2: Write the failing test**

Add to the test file:

```python
from datetime import datetime, timezone
from app.domain.message import Message


def test_message_accepts_image_url():
    msg = Message(
        id="m1",
        content="hi",
        raw_content="hi",
        author="a",
        posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        source="chat",
        image_url="https://example.com/x.png",
    )
    assert msg.image_url == "https://example.com/x.png"


def test_message_image_url_defaults_to_none():
    msg = Message(
        id="m2",
        content="hi",
        raw_content="hi",
        author="a",
        posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        source="chat",
    )
    assert msg.image_url is None
```

- [ ] **Step 3: Run the test, expect failure**

Run: `pytest backend/tests/domain/ -k message_image -v` *(adjust path to match Step 1's location)*

Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'image_url'`

- [ ] **Step 4: Add the field**

In `backend/app/domain/message.py`, the `Message` dataclass currently ends with these field declarations (lines 14-23):

```python
@dataclass(frozen=True)
class Message:
    id: str
    content: str
    raw_content: str
    author: str | None
    posted_at: datetime
    received_at: datetime
    source: Source
    url: str | None = None
    quoted: Message | None = None
    history_hint: list[Message] = field(default_factory=list)
```

Add `image_url: str | None = None` between `url` and `quoted`:

```python
@dataclass(frozen=True)
class Message:
    id: str
    content: str
    raw_content: str
    author: str | None
    posted_at: datetime
    received_at: datetime
    source: Source
    url: str | None = None
    image_url: str | None = None
    quoted: Message | None = None
    history_hint: list[Message] = field(default_factory=list)
```

- [ ] **Step 5: Run the test, expect pass**

Run: `pytest backend/tests/domain/ -k message_image -v`

Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/domain/message.py backend/tests/domain/test_message_image.py
git commit -m "feat(domain): add transient image_url field to Message"
```

---

## Task 2: Extract image URL in `backend/app/whop/extractor.py`

**Files:**
- Modify: `backend/app/whop/extractor.py` (specifically lines 560-600 area, around `has_attachment` detection)
- Create: `backend/tests/whop/fixtures/message_with_image.html`
- Test: `backend/tests/whop/test_extractor_image.py`

Current state (lines 577-582):

```python
has_attachment = bool(
    msg_el.find(attrs={"data-attachment-id": True})
    or msg_el.find("img", src=re.compile(r"whop\.com"))
)
if has_attachment and (not content or re.match(r"^(由\s*)?\d+\s*阅读$", content)):
    continue  # pure image with only read-count text
```

This drops image-only messages outright. We replace it with: extract the image URL, then skip only when **both** content is empty AND no image was extracted.

- [ ] **Step 1: Create the HTML fixture**

Create `backend/tests/whop/fixtures/message_with_image.html` containing a minimal version of the reference DOM (matches the structure in the spec):

```html
<div class="group/message" data-message-id="post_1CbE4Lcw7sLL2ze9wsR3Xg" data-has-message-above="false" data-has-message-below="false">
  <div class="inline-flex items-center gap-1">
    <span>•</span><span>Yesterday at 11:29 PM</span>
  </div>
  <span role="button" class="truncate cursor-pointer fui-HoverCardTrigger">xiaozhaolucky</span>
  <div data-attachment-id="file_zIf87lPvDcDN5">
    <img alt="image.png" src="https://img-v2-prod.whop.com/unsafe/rs:fit:3840:0/plain/https%3A%2F%2Fexample.png" />
  </div>
</div>
```

And a text-only fixture `backend/tests/whop/fixtures/message_text_only.html`:

```html
<div class="group/message" data-message-id="post_text_only" data-has-message-above="false" data-has-message-below="false">
  <div class="inline-flex items-center gap-1">
    <span>•</span><span>Today 10:00 AM</span>
  </div>
  <span role="button" class="truncate cursor-pointer fui-HoverCardTrigger">alice</span>
  <div class="bg-gray-3 rounded-[18px] px-3 py-1.5">
    <div class="whitespace-pre-wrap"><p>hello world</p></div>
  </div>
</div>
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/whop/test_extractor_image.py`:

```python
from pathlib import Path
from bs4 import BeautifulSoup

from app.whop.extractor import _extract_image_url

FIXTURES = Path(__file__).parent / "fixtures"


def _msg_el(name: str):
    html = (FIXTURES / name).read_text()
    return BeautifulSoup(html, "html.parser").find(attrs={"data-message-id": True})


def test_extract_image_url_from_message_with_image():
    el = _msg_el("message_with_image.html")
    url = _extract_image_url(el)
    assert url == (
        "https://img-v2-prod.whop.com/unsafe/rs:fit:3840:0/plain/"
        "https%3A%2F%2Fexample.png"
    )


def test_extract_image_url_returns_none_for_text_only():
    el = _msg_el("message_text_only.html")
    assert _extract_image_url(el) is None


def test_extract_image_url_ignores_non_whop_images():
    html = """
    <div data-message-id="m" data-attachment-id="a">
      <img src="https://other.cdn.com/foo.png" />
    </div>
    """
    el = BeautifulSoup(html, "html.parser").find(attrs={"data-message-id": True})
    assert _extract_image_url(el) is None
```

- [ ] **Step 3: Run the test, expect failure**

Run: `pytest backend/tests/whop/test_extractor_image.py -v`

Expected: FAIL — `ImportError: cannot import name '_extract_image_url'`.

- [ ] **Step 4: Implement `_extract_image_url`**

Add this function near the top of `backend/app/whop/extractor.py` (alongside the other private extraction helpers — find where `_extract_content` lives and add it adjacent):

```python
def _extract_image_url(msg_el) -> str | None:
    """Return the first whop.com-hosted image URL inside any attachment
    block of this message element, or None.

    We scope to ``[data-attachment-id]`` rather than scanning the whole
    message tree to avoid accidentally matching avatars or reply
    previews."""
    for attach in msg_el.find_all(attrs={"data-attachment-id": True}):
        img = attach.find("img", src=re.compile(r"whop\.com"))
        if img and img.get("src"):
            return img["src"]
    return None
```

(`re` is already imported at the top of `extractor.py`.)

- [ ] **Step 5: Run the test, expect pass**

Run: `pytest backend/tests/whop/test_extractor_image.py -v`

Expected: PASS (3 tests).

- [ ] **Step 6: Update the extractor loop to use the new helper**

In `backend/app/whop/extractor.py`, replace lines 577-582 (`has_attachment` block + early `continue`) with:

```python
# Extract image URL (if any).
image_url = _extract_image_url(msg_el)

# Skip messages with neither content nor image. Pure image-only
# messages now flow through; the writer will download the image.
if not content and image_url is None:
    continue
```

Also remove the now-redundant `if not content: continue` that sits just above on line 569 — it's covered by the new combined check.

Then locate the `Message(...)` construction a few lines below (currently lines 584-594) and add `image_url=image_url` to the kwargs:

```python
message = Message(
    id=msg_id,
    content=content,
    raw_content=raw_content,
    author=author,
    posted_at=current_posted_at,
    received_at=received_at,
    source=source,
    quoted=quoted,
    image_url=image_url,
    history_hint=[],
)
```

Do the same for the `Message(...)` construction in the missing-content branch around lines 555-563 (set `image_url=None` there since that branch is for entries we couldn't extract content from — they don't have images we care about).

- [ ] **Step 7: Add an end-to-end extractor test**

Append to `backend/tests/whop/test_extractor_image.py`:

```python
from app.whop.extractor import extract_messages  # adjust if name differs


def test_extract_messages_image_only_flows_through():
    """A message with only an image (no caption) should produce a Message
    with content="" and image_url set, not be silently dropped."""
    fixture = FIXTURES / "message_with_image.html"
    html = fixture.read_text()
    # extract_messages signature: confirm in Step 7a below before running.
    messages = extract_messages(html, source="chat", url=None)
    assert len(messages) == 1
    assert messages[0].image_url is not None
    assert messages[0].image_url.endswith("example.png")
```

> **Step 7a — verify signature:** run `grep -n "^def extract_messages\|^def extract" backend/app/whop/extractor.py` to confirm the public extractor function name and its kwargs. Adjust the test call to match. If the function expects raw HTML vs. a soup vs. a Playwright element, wrap the fixture accordingly.

- [ ] **Step 8: Run all extractor tests**

Run: `pytest backend/tests/whop/ -v`

Expected: PASS (existing tests still green; new tests green; no test that relied on image-only filtering should remain — if any do, update them to reflect the new behavior).

- [ ] **Step 9: Commit**

```bash
git add backend/app/whop/extractor.py backend/tests/whop/test_extractor_image.py backend/tests/whop/fixtures/
git commit -m "feat(extractor): extract whop image URL; allow image-only messages"
```

---

## Task 3: Add `image_filename` column to `ChatMessageRow` + migration

**Files:**
- Modify: `backend/app/storage/schema.py`
- Modify: schema bootstrap call site (see Step 1 discovery)
- Test: `backend/tests/storage/test_chat_messages_image.py`

Discovery is needed: I need the implementer to confirm the SQLAlchemy `mapped_column` style used by `ChatMessageRow` and the bootstrap mechanism (Alembic vs `metadata.create_all`).

- [ ] **Step 1: Discovery — read existing schema and migration patterns**

Run:

```bash
sed -n '1,200p' backend/app/storage/schema.py
grep -rn "create_all\|alembic\|Alembic\|metadata\.create" backend/app/storage backend/app/main.py | head
ls backend/alembic 2>/dev/null || ls backend/migrations 2>/dev/null || echo "no alembic dir"
```

Note:
- The exact column declaration style for nullable string columns on `ChatMessageRow` (e.g. `Mapped[str | None] = mapped_column(String, nullable=True)` — copy the prevailing pattern).
- Whether schema is bootstrapped via `Base.metadata.create_all` at startup, via Alembic, or via a hand-rolled SQL block.
- If Alembic: the path to the versions dir, e.g. `backend/alembic/versions/`.
- If `create_all`: the call site (probably in `backend/app/main.py` startup hook or `backend/app/storage/db.py`).

- [ ] **Step 2: Write the failing test**

Create `backend/tests/storage/test_chat_messages_image.py`:

```python
import pytest
from datetime import datetime, timezone

from app.storage.schema import ChatMessageRow
# Test fixture name varies by project — use whatever existing chat-message
# test uses. Common patterns: `session` (async), `db_session`, `async_session`.
# Confirm with: `grep -rln "ChatMessageRow" backend/tests | head -3`


@pytest.mark.asyncio
async def test_chat_message_row_persists_image_filename(session):
    row = ChatMessageRow(
        id="m_img_1",
        page_id="page_1",
        author="alice",
        content="",
        raw_content="",
        posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        url=None,
        quoted_message_id=None,
        quoted_author=None,
        quoted_content=None,
        quoted_posted_at=None,
        image_filename="m_img_1.avif",
    )
    session.add(row)
    await session.flush()

    fetched = await session.get(ChatMessageRow, "m_img_1")
    assert fetched is not None
    assert fetched.image_filename == "m_img_1.avif"


@pytest.mark.asyncio
async def test_chat_message_row_image_filename_defaults_to_none(session):
    row = ChatMessageRow(
        id="m_img_2",
        page_id="page_1",
        author="alice",
        content="hi",
        raw_content="hi",
        posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        url=None,
        quoted_message_id=None,
        quoted_author=None,
        quoted_content=None,
        quoted_posted_at=None,
    )
    session.add(row)
    await session.flush()

    fetched = await session.get(ChatMessageRow, "m_img_2")
    assert fetched.image_filename is None
```

If your test fixture is named differently (e.g. `db_session`, `async_session`), do a global rename. Look at any existing test that inserts a `ChatMessageRow` for the convention.

- [ ] **Step 3: Run the test, expect failure**

Run: `pytest backend/tests/storage/test_chat_messages_image.py -v`

Expected: FAIL — `TypeError: 'image_filename' is an invalid keyword argument for ChatMessageRow`.

- [ ] **Step 4: Add the column to `ChatMessageRow`**

In `backend/app/storage/schema.py`, find the `ChatMessageRow` class. Append a new column declaration following the same `mapped_column` style as the existing nullable string columns (the discovery in Step 1 told you the pattern). Place it after the `quoted_*` columns and before `created_at`. Example using the conventional style:

```python
image_filename: Mapped[str | None] = mapped_column(
    String, nullable=True, default=None
)
```

> If `ChatMessageRow` uses positional `Column(String, nullable=True)` declarations instead of `mapped_column`, match that style instead.

- [ ] **Step 5: Add the migration**

**If the project uses `Base.metadata.create_all`** (i.e., no Alembic): add a startup-time `ALTER TABLE` shim. Find the existing schema bootstrap call. If there's a function like `ensure_schema(engine)` or similar in `backend/app/storage/db.py`, add this after `metadata.create_all`:

```python
async with engine.begin() as conn:
    # Idempotent column add — SQLite tolerates ADD COLUMN IF NOT EXISTS via
    # PRAGMA-driven check. We use the introspection approach for portability:
    cols = await conn.run_sync(
        lambda sync_conn: {
            row[1]
            for row in sync_conn.execute(
                text("PRAGMA table_info(chat_messages)")
            ).fetchall()
        }
    )
    if "image_filename" not in cols:
        await conn.execute(text("ALTER TABLE chat_messages ADD COLUMN image_filename TEXT"))
```

Imports needed: `from sqlalchemy import text`.

**If the project uses Alembic**: create a new revision:

```bash
cd backend && alembic revision -m "add chat_messages.image_filename"
```

Then in the generated revision file (`backend/alembic/versions/<hash>_add_chat_messages_image_filename.py`):

```python
def upgrade() -> None:
    op.add_column(
        "chat_messages",
        sa.Column("image_filename", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chat_messages", "image_filename")
```

- [ ] **Step 6: Run the test, expect pass**

Run: `pytest backend/tests/storage/test_chat_messages_image.py -v`

Expected: PASS (2 tests).

Also run any existing chat-message storage tests to confirm no regression:

Run: `pytest backend/tests/storage/ -v`

- [ ] **Step 7: Commit**

```bash
git add backend/app/storage/schema.py backend/tests/storage/test_chat_messages_image.py
# Plus the migration file(s) from Step 5
git commit -m "feat(storage): add image_filename column to chat_messages"
```

---

## Task 4: Implement `_download_image` and wire into `chat_writer._handler`

**Files:**
- Modify: `backend/app/whop/chat_writer.py`
- Test: `backend/tests/whop/test_chat_writer_image.py`

Current `chat_writer.py` (full source already known):

```python
def _row_from_message(page_id: str, msg: Message) -> ChatMessageRow:
    q = msg.quoted
    return ChatMessageRow(
        id=msg.id, page_id=page_id, author=msg.author or "",
        content=msg.content, raw_content=msg.raw_content,
        posted_at=msg.posted_at, received_at=msg.received_at,
        url=msg.url,
        quoted_message_id=q.id if q else None,
        quoted_author=q.author if q else None,
        quoted_content=q.content if q else None,
        quoted_posted_at=q.posted_at if q else None,
    )


def register_chat_writer(bus, session_factory):
    async def _handler(event):
        payload = event.payload
        row = _row_from_message(payload.page_id, payload.message)
        async with session_scope(session_factory) as session:
            await repo.upsert_chat_message(session, row)
        if not payload.is_historical:
            await bus.publish(Event(
                topic=Topics.CHAT_MESSAGE_STORED,
                payload=ChatMessageStoredPayload(
                    page_id=payload.page_id, message_id=row.id,
                ),
            ))
    return [bus.subscribe(Topics.CHAT_MESSAGE_RECEIVED, _handler)]
```

We add: an async `_download_image` helper; an `image_filename` parameter on `_row_from_message`; a download step in `_handler`. We also need a `data_dir` — `register_chat_writer` needs to accept it.

- [ ] **Step 1: Discovery — find how `data_dir` is wired**

Run:

```bash
grep -rn "data_dir\|DATA_DIR\|Settings\|chat-images" backend/app/main.py backend/app/storage/db.py backend/app/core | head
grep -rn "register_chat_writer" backend/app | head
```

Note:
- Where `register_chat_writer` is called from (the implementer must pass `data_dir` through that call site too).
- Whether there's a `Settings` Pydantic class with `data_dir` already, or just a constant.
- Whether `httpx` is already a dep: `grep "httpx" backend/pyproject.toml backend/requirements*.txt 2>/dev/null`.

If `httpx` is not present, add it:
```bash
cd backend && pip install httpx && pip freeze | grep httpx >> requirements.txt
# or, if poetry: poetry add httpx
```

- [ ] **Step 2: Write the failing test for `_download_image`**

Create `backend/tests/whop/test_chat_writer_image.py`:

```python
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.whop.chat_writer import _download_image


@pytest.mark.asyncio
async def test_download_image_happy_path(tmp_path):
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.content = b"fakebytes"
    fake_resp.headers = {"Content-Type": "image/avif"}
    fake_resp.raise_for_status = MagicMock()

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.whop.chat_writer.httpx.AsyncClient", return_value=fake_client):
        filename = await _download_image(
            "msg_1", "https://example.com/x.avif", tmp_path
        )

    assert filename == "msg_1.avif"
    assert (tmp_path / "chat-images" / "msg_1.avif").read_bytes() == b"fakebytes"


@pytest.mark.asyncio
async def test_download_image_maps_content_types(tmp_path):
    cases = [
        ("image/png", "msg_a.png"),
        ("image/jpeg", "msg_b.jpg"),
        ("image/webp", "msg_c.webp"),
        ("application/octet-stream", "msg_d.bin"),
    ]
    for ct, expected_name in cases:
        msg_id = expected_name.split(".")[0]
        fake_resp = MagicMock(
            status_code=200, content=b"x", headers={"Content-Type": ct}
        )
        fake_resp.raise_for_status = MagicMock()
        fake_client = AsyncMock()
        fake_client.get = AsyncMock(return_value=fake_resp)
        fake_client.__aenter__.return_value = fake_client
        fake_client.__aexit__.return_value = None

        with patch("app.whop.chat_writer.httpx.AsyncClient", return_value=fake_client):
            filename = await _download_image(msg_id, "https://example.com/x", tmp_path)

        assert filename == expected_name


@pytest.mark.asyncio
async def test_download_image_returns_none_on_http_error(tmp_path):
    import httpx as _httpx

    fake_resp = MagicMock(status_code=403, content=b"", headers={})
    fake_resp.raise_for_status = MagicMock(
        side_effect=_httpx.HTTPStatusError("403", request=MagicMock(), response=fake_resp)
    )
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.whop.chat_writer.httpx.AsyncClient", return_value=fake_client):
        filename = await _download_image("msg_x", "https://example.com/x", tmp_path)

    assert filename is None
    assert not (tmp_path / "chat-images").exists() or not any(
        (tmp_path / "chat-images").iterdir()
    )


@pytest.mark.asyncio
async def test_download_image_returns_none_on_timeout(tmp_path):
    import httpx as _httpx

    fake_client = AsyncMock()
    fake_client.get = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    with patch("app.whop.chat_writer.httpx.AsyncClient", return_value=fake_client):
        filename = await _download_image("msg_y", "https://example.com/x", tmp_path)

    assert filename is None
```

- [ ] **Step 3: Run the tests, expect failure**

Run: `pytest backend/tests/whop/test_chat_writer_image.py -v`

Expected: FAIL — `ImportError: cannot import name '_download_image'`.

- [ ] **Step 4: Implement `_download_image`**

Add to `backend/app/whop/chat_writer.py`:

```python
import logging
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)

_CONTENT_TYPE_EXT = {
    "image/avif": ".avif",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def _download_image(
    msg_id: str, remote_url: str, data_dir: Path
) -> str | None:
    """Download *remote_url* into ``<data_dir>/chat-images/<msg_id><ext>``.

    Returns the filename (basename only) on success, or None on any
    failure (network error, HTTP error, timeout). All errors are caught
    and logged — image cache failures must not break message ingestion.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(remote_url)
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = _CONTENT_TYPE_EXT.get(ct, ".bin")
            target_dir = data_dir / "chat-images"
            target_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{msg_id}{ext}"
            (target_dir / filename).write_bytes(resp.content)
            return filename
    except Exception:  # noqa: BLE001
        _log.warning(
            "chat image download failed for msg_id=%s url=%s",
            msg_id, remote_url, exc_info=True,
        )
        return None
```

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest backend/tests/whop/test_chat_writer_image.py -v`

Expected: PASS (4 tests).

- [ ] **Step 6: Wire `_download_image` into `_handler`**

Modify `register_chat_writer` to accept `data_dir`, and add the download step. Replace the existing function body:

```python
def register_chat_writer(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    data_dir: Path,
) -> list[Callable[[], None]]:
    async def _handler(event: Event) -> None:
        payload: ChatMessagePayload = event.payload  # pyright: ignore
        msg = payload.message

        image_filename: str | None = None
        if msg.image_url:
            image_filename = await _download_image(msg.id, msg.image_url, data_dir)

        # Skip rows that have neither text content nor a successfully
        # downloaded image (covers the rare case where extraction caught
        # an image_url but the download failed AND content was empty).
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
```

And update `_row_from_message` to take the filename:

```python
def _row_from_message(
    page_id: str, msg: Message, image_filename: str | None,
) -> ChatMessageRow:
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
```

- [ ] **Step 7: Update the `register_chat_writer` call site to pass `data_dir`**

The discovery in Step 1 told you where this is called from. The call site needs to thread `data_dir` from the app's settings / Settings class. Example assuming a `Settings` object with `data_dir: Path`:

```python
register_chat_writer(bus, session_factory, settings.data_dir)
```

If there's no settings layer yet, pick a sane default (e.g. `Path("data")` relative to repo root) at the call site only — do not hardcode inside `chat_writer.py`.

- [ ] **Step 8: Write an integration test for the wired handler**

Append to `backend/tests/whop/test_chat_writer_image.py`:

```python
from datetime import datetime, timezone

from app.core.event_bus import Event, EventBus
from app.core.events import ChatMessagePayload, Topics
from app.domain.message import Message
from app.storage.schema import ChatMessageRow
from app.whop.chat_writer import register_chat_writer


@pytest.mark.asyncio
async def test_handler_downloads_image_and_writes_row(
    tmp_path, session_factory  # adjust fixture name to match project
):
    bus = EventBus()
    register_chat_writer(bus, session_factory, tmp_path)

    fake_resp = MagicMock(
        status_code=200, content=b"PNG", headers={"Content-Type": "image/png"}
    )
    fake_resp.raise_for_status = MagicMock()
    fake_client = AsyncMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__.return_value = fake_client
    fake_client.__aexit__.return_value = None

    msg = Message(
        id="m_int_1",
        content="caption",
        raw_content="caption",
        author="alice",
        posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
        source="chat",
        image_url="https://example.com/x.png",
    )
    payload = ChatMessagePayload(
        page_id="page_1", message=msg, is_historical=False
    )

    with patch("app.whop.chat_writer.httpx.AsyncClient", return_value=fake_client):
        await bus.publish(Event(topic=Topics.CHAT_MESSAGE_RECEIVED, payload=payload))

    # File written
    assert (tmp_path / "chat-images" / "m_int_1.png").read_bytes() == b"PNG"

    # Row written with image_filename
    async with session_factory() as session:
        row = await session.get(ChatMessageRow, "m_int_1")
        assert row is not None
        assert row.image_filename == "m_int_1.png"
```

> The exact `session_factory` fixture name depends on the project's existing test infrastructure — copy from any existing chat_writer test or storage integration test.

- [ ] **Step 9: Run all writer tests**

Run: `pytest backend/tests/whop/test_chat_writer_image.py -v`

Expected: PASS (5 tests, including the new integration test).

- [ ] **Step 10: Commit**

```bash
git add backend/app/whop/chat_writer.py backend/tests/whop/test_chat_writer_image.py
# Plus the call site change from Step 7 (likely backend/app/main.py)
git commit -m "feat(chat-writer): download image at scrape time, persist filename"
```

---

## Task 5: Expose `image_url` in API response + new `/api/chat-images/{id}` route

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/http.py`
- Test: `backend/tests/api/test_chat_images.py`

The current API surface (lines from earlier discovery):
- `ChatMessageOut` (schemas.py:649-655) has fields `id, page_id, author, content, posted_at, quoted` — no image.
- `_row_to_chat_out` (http.py:144-167) converts a row to a `ChatMessageOut`.
- `GET /api/whop/pages/{page_id}/chat-messages` (http.py:1528-1570) is the existing chat-messages route.

- [ ] **Step 1: Discovery — read the existing API surface**

Run:

```bash
sed -n '140,175p' backend/app/api/http.py     # _row_to_chat_out
sed -n '1520,1580p' backend/app/api/http.py   # chat-messages route
grep -n "data_dir\|Settings" backend/app/api/http.py | head
```

Note:
- Whether the route uses `Depends(get_settings)` or `Depends(get_data_dir)` to access `data_dir`.
- Whether `FileResponse` is imported.
- The existing app router prefix (probably `/api` already).

- [ ] **Step 2: Write the failing test for `ChatMessageOut.image_url`**

Create `backend/tests/api/test_chat_images.py`:

```python
import pytest
from httpx import AsyncClient
from datetime import datetime, timezone

from app.storage.schema import ChatMessageRow


@pytest.mark.asyncio
async def test_chat_message_out_includes_image_url(client: AsyncClient, session_factory):
    """An /api/whop/pages/.../chat-messages response carries image_url
    pointing at the new chat-images endpoint when image_filename is set."""
    async with session_factory() as session:
        session.add(ChatMessageRow(
            id="m_api_1",
            page_id="page_1",
            author="alice",
            content="",
            raw_content="",
            posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            url=None,
            quoted_message_id=None,
            quoted_author=None,
            quoted_content=None,
            quoted_posted_at=None,
            image_filename="m_api_1.png",
        ))
        await session.commit()

    resp = await client.get("/api/whop/pages/page_1/chat-messages")
    assert resp.status_code == 200
    body = resp.json()
    msg = next(m for m in body["messages"] if m["id"] == "m_api_1")
    assert msg["image_url"] == "/api/chat-images/m_api_1"


@pytest.mark.asyncio
async def test_chat_message_out_image_url_null_when_no_image(
    client: AsyncClient, session_factory
):
    async with session_factory() as session:
        session.add(ChatMessageRow(
            id="m_api_2",
            page_id="page_1",
            author="alice",
            content="just text",
            raw_content="just text",
            posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            url=None,
            quoted_message_id=None,
            quoted_author=None,
            quoted_content=None,
            quoted_posted_at=None,
        ))
        await session.commit()

    resp = await client.get("/api/whop/pages/page_1/chat-messages")
    msg = next(m for m in resp.json()["messages"] if m["id"] == "m_api_2")
    assert msg.get("image_url") is None
```

> Fixture names (`client`, `session_factory`) — adapt to whatever the existing API tests use. Look in `backend/tests/api/conftest.py` for the convention.

- [ ] **Step 3: Run the test, expect failure**

Run: `pytest backend/tests/api/test_chat_images.py::test_chat_message_out_includes_image_url -v`

Expected: FAIL — `image_url` key missing from response.

- [ ] **Step 4: Add `image_url` to the API schema**

In `backend/app/api/schemas.py`, modify `ChatMessageOut` (currently lines 649-655):

```python
class ChatMessageOut(BaseModel):
    id: str
    page_id: str
    author: str
    content: str
    posted_at: datetime
    quoted: QuotedRefOut | None = None
    image_url: str | None = None
```

- [ ] **Step 5: Update `_row_to_chat_out`**

In `backend/app/api/http.py` (around line 144-167), modify `_row_to_chat_out` to populate `image_url`. The current function builds `ChatMessageOut(...)` — add:

```python
return ChatMessageOut(
    id=row.id,
    page_id=row.page_id,
    author=row.author,
    content=row.content,
    posted_at=row.posted_at,
    quoted=_quoted_ref_from_row(row),  # whatever the existing call is
    image_url=(
        f"/api/chat-images/{row.id}" if row.image_filename else None
    ),
)
```

> Preserve the existing function's exact `quoted=` construction — only add the `image_url=` line.

- [ ] **Step 6: Run the first two tests, expect pass**

Run: `pytest backend/tests/api/test_chat_images.py -k "chat_message_out" -v`

Expected: PASS (2 tests).

- [ ] **Step 7: Write the failing test for the new `/api/chat-images/{id}` route**

Append to `backend/tests/api/test_chat_images.py`:

```python
@pytest.mark.asyncio
async def test_get_chat_image_returns_file(
    client: AsyncClient, session_factory, tmp_path, monkeypatch
):
    """The /api/chat-images/<id> endpoint serves the cached image
    bytes with the correct media type."""
    # Write a fake image into the chat-images cache dir
    monkeypatch.setattr("app.api.http.DATA_DIR", tmp_path)  # adjust to actual path
    (tmp_path / "chat-images").mkdir()
    (tmp_path / "chat-images" / "m_route_1.png").write_bytes(b"PNGBYTES")

    async with session_factory() as session:
        session.add(ChatMessageRow(
            id="m_route_1",
            page_id="page_1",
            author="alice",
            content="",
            raw_content="",
            posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            url=None,
            quoted_message_id=None,
            quoted_author=None,
            quoted_content=None,
            quoted_posted_at=None,
            image_filename="m_route_1.png",
        ))
        await session.commit()

    resp = await client.get("/api/chat-images/m_route_1")
    assert resp.status_code == 200
    assert resp.content == b"PNGBYTES"
    assert resp.headers["content-type"].startswith("image/png")


@pytest.mark.asyncio
async def test_get_chat_image_404_when_missing(
    client: AsyncClient, session_factory
):
    # Row exists but image_filename is None
    async with session_factory() as session:
        session.add(ChatMessageRow(
            id="m_route_2",
            page_id="page_1",
            author="alice",
            content="text only",
            raw_content="text only",
            posted_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            received_at=datetime(2026, 5, 21, tzinfo=timezone.utc),
            url=None,
            quoted_message_id=None,
            quoted_author=None,
            quoted_content=None,
            quoted_posted_at=None,
        ))
        await session.commit()

    resp = await client.get("/api/chat-images/m_route_2")
    assert resp.status_code == 404

    resp2 = await client.get("/api/chat-images/does_not_exist")
    assert resp2.status_code == 404
```

> Tune the `monkeypatch` target to match how `data_dir` is actually resolved in `http.py` (likely `Depends(get_settings)`; in that case override the settings fixture instead).

- [ ] **Step 8: Run the test, expect failure**

Run: `pytest backend/tests/api/test_chat_images.py::test_get_chat_image_returns_file -v`

Expected: FAIL — 404 (route doesn't exist).

- [ ] **Step 9: Implement the route**

In `backend/app/api/http.py`, add:

```python
from fastapi.responses import FileResponse

# Maps file extension to media type for FileResponse
_IMAGE_MEDIA_TYPES = {
    ".avif": "image/avif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bin": "application/octet-stream",
}


@router.get("/api/chat-images/{message_id}")
async def get_chat_image(
    message_id: str,
    session: AsyncSession = Depends(get_session),  # match existing dep style
    settings: Settings = Depends(get_settings),    # match existing dep style
) -> FileResponse:
    row = await session.get(ChatMessageRow, message_id)
    if row is None or not row.image_filename:
        raise HTTPException(status_code=404, detail="image not found")
    path = settings.data_dir / "chat-images" / row.image_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="image file missing")
    ext = path.suffix.lower()
    media_type = _IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media_type)
```

Adjust `Depends(...)` callables to match the project's existing dependency-injection style (the discovery in Step 1 told you whether it's `get_session`, `Depends(async_session)`, etc.).

- [ ] **Step 10: Run all tests in this task, expect pass**

Run: `pytest backend/tests/api/test_chat_images.py -v`

Expected: PASS (4 tests).

- [ ] **Step 11: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/http.py backend/tests/api/test_chat_images.py
git commit -m "feat(api): expose image_url; serve cached chat images"
```

---

## Task 6: Add `image_url` field to frontend `ChatMessageOut` type

**Files:**
- Modify: `frontend/src/components/Chat/chatCards.ts`

Current shape (lines 8-15 of `chatCards.ts`):

```typescript
export interface ChatMessageOut {
  id: string;
  page_id: string;
  author: string;
  content: string;
  posted_at: string;
  quoted?: QuotedRef;
}
```

- [ ] **Step 1: Add the field**

```typescript
export interface ChatMessageOut {
  id: string;
  page_id: string;
  author: string;
  content: string;
  posted_at: string;
  quoted?: QuotedRef;
  image_url?: string | null;
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`

Expected: PASS (no errors). The field is optional, so existing call sites that don't construct `ChatMessageOut` literals (which is most of them — they come from API responses) are unaffected.

If any test fixtures or mocks construct `ChatMessageOut` literals, they continue to work since the field is optional.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Chat/chatCards.ts
git commit -m "feat(frontend): add image_url to ChatMessageOut type"
```

---

## Task 7: Render image in `PlainBubble`

**Files:**
- Modify: `frontend/src/components/Chat/PlainBubble.tsx`
- Modify: `frontend/src/components/Chat/PlainBubble.test.tsx`

Current `PlainBubble` (full source):

```typescript
export interface PlainBubbleProps {
  content: string;
  quoted?: { author: string; content: string } | null;
}

export function PlainBubble({ content, quoted }: PlainBubbleProps): JSX.Element {
  return (
    <div className="chat-group-bubble">
      {quoted && (
        <div className="chat-group-quoted" title={quoted.content}>
          <span className="chat-group-quoted-sender">{quoted.author}</span>
          <span className="chat-group-quoted-body">{quoted.content}</span>
        </div>
      )}
      {content}
    </div>
  );
}
```

- [ ] **Step 1: Read the existing test file**

Run: `cat frontend/src/components/Chat/PlainBubble.test.tsx`

Note the test runner (Vitest), the existing rendering helper (`@testing-library/react`'s `render` plus `screen`), and the imports.

- [ ] **Step 2: Write failing tests**

Append to `PlainBubble.test.tsx`:

```typescript
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PlainBubble } from "./PlainBubble";

describe("PlainBubble image rendering", () => {
  it("renders <img> when imageUrl is set", () => {
    render(<PlainBubble content="caption" imageUrl="/api/chat-images/abc" />);
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "/api/chat-images/abc");
    expect(screen.getByText("caption")).toBeInTheDocument();
  });

  it("renders image-only bubble when content is empty", () => {
    const { container } = render(
      <PlainBubble content="" imageUrl="/api/chat-images/abc" />
    );
    expect(screen.getByRole("img")).toBeInTheDocument();
    // The bubble div has the image-only marker class
    expect(container.querySelector(".chat-group-bubble--image-only")).toBeTruthy();
  });

  it("renders no <img> when imageUrl is null/undefined", () => {
    render(<PlainBubble content="just text" />);
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("just text")).toBeInTheDocument();
  });
});
```

> If the existing test file already has `describe` blocks at the top level, append the new `describe` block at the bottom (don't nest).

- [ ] **Step 3: Run tests, expect failure**

Run: `cd frontend && npx vitest run src/components/Chat/PlainBubble.test.tsx`

Expected: FAIL — `Type '{ content: string; imageUrl: string; }' is not assignable to type 'PlainBubbleProps'.`

- [ ] **Step 4: Update `PlainBubble`**

Replace the contents of `frontend/src/components/Chat/PlainBubble.tsx`:

```typescript
export interface PlainBubbleProps {
  content: string;
  quoted?: { author: string; content: string } | null;
  imageUrl?: string | null;
}

export function PlainBubble({
  content, quoted, imageUrl,
}: PlainBubbleProps): JSX.Element {
  const imageOnly = !!imageUrl && content.length === 0;
  const cls = imageOnly
    ? "chat-group-bubble chat-group-bubble--image-only"
    : "chat-group-bubble";
  return (
    <div className={cls}>
      {quoted && (
        <div className="chat-group-quoted" title={quoted.content}>
          <span className="chat-group-quoted-sender">{quoted.author}</span>
          <span className="chat-group-quoted-body">{quoted.content}</span>
        </div>
      )}
      {imageUrl && (
        <img className="chat-group-image" src={imageUrl} alt="" />
      )}
      {content}
    </div>
  );
}
```

- [ ] **Step 5: Run tests, expect pass**

Run: `cd frontend && npx vitest run src/components/Chat/PlainBubble.test.tsx`

Expected: PASS (existing tests still green + 3 new tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/PlainBubble.tsx frontend/src/components/Chat/PlainBubble.test.tsx
git commit -m "feat(frontend): render image inside PlainBubble"
```

---

## Task 8: Wire `image_url` through `ChatMessage` and `ChatCard` callers

**Files:**
- Modify: `frontend/src/components/Chat/ChatMessage.tsx`
- Modify: `frontend/src/components/Chat/ChatCard.tsx`

Current `ChatMessage.tsx`:

```typescript
export function ChatMessage({
  sender, firstAt, messages, align, dim,
}: ChatMessageProps): JSX.Element {
  return (
    <MessageShell sender={sender} firstAt={firstAt} align={align} dim={dim}>
      {messages.map((m) => (
        <PlainBubble key={m.id} content={m.content} quoted={m.quoted ?? null} />
      ))}
    </MessageShell>
  );
}
```

Current `ChatCard.tsx` (bubble rendering, lines 86-100):

```tsx
{b.msgs.map((m) => (
  <div key={m.id} className="chat-group-bubble">
    {m.quoted && (
      <div className="chat-group-quoted" title={m.quoted.content}>
        <span className="chat-group-quoted-sender">{m.quoted.author}</span>
        <span className="chat-group-quoted-body">{m.quoted.content}</span>
      </div>
    )}
    {m.content}
  </div>
))}
```

- [ ] **Step 1: Update `ChatMessage.tsx`**

Replace the `PlainBubble` call:

```typescript
{messages.map((m) => (
  <PlainBubble
    key={m.id}
    content={m.content}
    quoted={m.quoted ?? null}
    imageUrl={m.image_url ?? null}
  />
))}
```

- [ ] **Step 2: Update `ChatCard.tsx`**

Replace the bubble rendering loop (around lines 86-100) with:

```tsx
{b.msgs.map((m) => {
  const imageOnly = !!m.image_url && m.content.length === 0;
  const cls = imageOnly
    ? "chat-group-bubble chat-group-bubble--image-only"
    : "chat-group-bubble";
  return (
    <div key={m.id} className={cls}>
      {m.quoted && (
        <div className="chat-group-quoted" title={m.quoted.content}>
          <span className="chat-group-quoted-sender">{m.quoted.author}</span>
          <span className="chat-group-quoted-body">{m.quoted.content}</span>
        </div>
      )}
      {m.image_url && (
        <img className="chat-group-image" src={m.image_url} alt="" />
      )}
      {m.content}
    </div>
  );
})}
```

- [ ] **Step 3: Type-check + run all Chat tests**

Run:

```bash
cd frontend && npx tsc --noEmit
cd frontend && npx vitest run src/components/Chat/
```

Expected: PASS — no type errors, all chat tests green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/ChatMessage.tsx frontend/src/components/Chat/ChatCard.tsx
git commit -m "feat(frontend): wire image_url through ChatMessage and ChatCard"
```

---

## Task 9: Add bubble image CSS

**Files:**
- Modify: the CSS file that currently defines `.chat-group-bubble` (see Step 1 discovery)

- [ ] **Step 1: Find the existing bubble styles**

Run: `grep -rn "\.chat-group-bubble" frontend/src --include="*.css" --include="*.scss"`

Open the file that defines `.chat-group-bubble`.

- [ ] **Step 2: Add image styles**

Append (placement near the existing `.chat-group-bubble` rules):

```css
.chat-group-bubble .chat-group-image {
  display: block;
  max-width: 100%;
  max-height: 360px;
  border-radius: 8px;
  margin-bottom: 4px;
}

/* Image-only bubble: tighten padding so the image looks framed.
   The standard bubble has padding for text — image bubbles shouldn't. */
.chat-group-bubble--image-only {
  padding: 4px;
}

.chat-group-bubble--image-only .chat-group-image {
  margin-bottom: 0;
}
```

- [ ] **Step 3: Manual visual check**

Run the dev server (whatever the project uses, likely `npm run dev` from `frontend/`), navigate to a chat view that contains an image-bearing message, and confirm:

1. Image renders inline above the caption.
2. Image is bounded to 360px height (no full-page-tall images).
3. Image-only bubble is tightly framed (no big text padding around the image).
4. Quoted bubbles still render correctly (image goes below the quote block, above content).

If the dev environment makes this hard to exercise on real data, you can add a temporary mock message in your local data fixture to force-trigger an image bubble.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/<path-to-css-file>
git commit -m "feat(frontend): style chat bubble images"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Covered by |
|---|---|
| Parse image URL from DOM | Task 2 |
| Download at scrape time, persist locally | Task 4 |
| Render image in bubble above text | Tasks 7-9 |
| Allow image-only messages | Tasks 2 + 4 (extraction passes them; writer keeps them if download succeeds) |
| `Message.image_url` (transient, domain) | Task 1 |
| `image_filename` DB column | Task 3 |
| `ChatMessageOut.image_url` (API + frontend) | Tasks 5, 6 |
| `/api/chat-images/{message_id}` endpoint | Task 5 |
| Bubble image CSS | Task 9 |
| Download failure → row with `image_filename=None` | Task 4 (handler logs + continues) |
| Skip empty-content + no-image messages | Task 2 (extractor) + Task 4 (writer fallback) |
| Tests for extractor, downloader, route, bubble | Tasks 2, 4, 5, 7 |

All spec items have at least one task.

**Placeholder scan:** Discovery steps in Tasks 3, 4, 5, 7, 9 are not placeholders — each tells the implementer exactly what to grep and what shape to expect, with the surrounding code spelled out concretely. No "TBD" or "add appropriate X" left.

**Type / name consistency:**
- `image_url` (snake_case) is used consistently on the API and frontend `ChatMessageOut` and on the domain `Message`.
- `image_filename` (snake_case) is used consistently on the DB row and as the return value of `_download_image`.
- `imageUrl` (camelCase) is used consistently for the React prop.
- `_download_image`, `_extract_image_url` — names match between tasks and tests.
- `_row_from_message` signature changes from `(page_id, msg)` to `(page_id, msg, image_filename)` — applied consistently in Task 4.
