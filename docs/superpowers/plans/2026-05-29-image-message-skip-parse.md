# 图片消息:跳过解析、当作图片展示 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 当正股(stock)或期权(option)消息带图片时,跳过指令解析,把它当作「图片消息」展示(复用聊天图片的服务端下载/代理),不再产生 PARSE_ERROR。

**Architecture:** 后端在 parser/service 收到消息后,若 `msg.image_url` 非空:先下载图片到本地(复用 chat 图片管线),把文件名存进 `messages.image_filename`,标记任务 `SKIPPED`(reason=图片消息),不跑解析。`MessageOut` 新增 `image_url` 字段(= 本地代理路径 `/api/messages/{id}/image`),前端据此渲染图片气泡。检测规则:只要有图片就算图片消息(图文混合也跳过),stock/option 都适用。

**Tech Stack:** Python (FastAPI, SQLAlchemy, Alembic, httpx, pytest) + React/TypeScript (Vite, vitest)。

**Spec:** `docs/superpowers/specs/2026-05-29-image-message-skip-parse-design.md`

---

## File Structure

后端:
- `backend/app/whop/image_store.py` — **新建**。共享图片下载工具 `download_image()`(从 `chat_writer.py` 抽出)。
- `backend/app/whop/chat_writer.py` — 改为调用 `image_store.download_image`。
- `backend/app/domain/message.py` — `Message` 新增 `image_filename`。
- `backend/app/storage/schema.py` — `MessageRow` 新增 `image_filename` 列。
- `backend/alembic/versions/<new>_add_messages_image_filename.py` — **新建**迁移。
- `backend/app/storage/repo.py` — `save_task` 写入 + `_row_to_message` 读取 `image_filename`。
- `backend/app/parser/service.py` — 图片消息跳过解析;`register_parser_service` 增 `data_dir` 参数。
- `backend/app/main.py` — 给 `register_parser_service` 传 `data_dir`。
- `backend/app/api/schemas.py` — `MessageOut` 新增 `image_url` + `message_to_out` 填充。
- `backend/app/api/http.py` — 新增 `GET /api/messages/{id}/image`。

前端:
- `frontend/src/api/types.ts` — 重新生成(获得 `MessageOut.image_url`)。
- `frontend/src/components/Chat/signalCardHelpers.ts` — `layersForTask` 增 `image` kind。
- `frontend/src/components/Chat/SignalBubble.tsx` — 渲染图片气泡。
- `frontend/src/components/Chat/SignalCard.css` — 图片样式(注意 **不能**复用 `ChatBoardPanel.css` 里的 `chat-group-image`,SignalBubble 不引那个文件)。

测试:
- `backend/tests/whop/test_chat_writer_image.py` — 更新 patch 目标(函数已移动)。
- `backend/tests/parser/test_service.py` — 新增图片跳过解析测试。
- `backend/tests/api/test_schemas.py` — 新增 `image_url` 转发测试。
- `backend/tests/api/test_messages_image.py` — **新建**,serve 端点测试。
- `frontend/src/components/Chat/signalCardHelpers.test.ts` — 新增 image kind 测试。
- `frontend/src/components/Chat/SignalBubble.test.tsx` — 新增图片渲染测试。

**测试命令约定:** 后端 `cd backend && uv run pytest <path> -v`;前端 `cd frontend && npx vitest run <path>`。

---

### Task 1: 抽出共享图片下载工具

**Files:**
- Create: `backend/app/whop/image_store.py`
- Modify: `backend/app/whop/chat_writer.py:23-84` (删除本地 `_download_image` + `_CONTENT_TYPE_EXT`,改为 import)
- Test: `backend/tests/whop/test_chat_writer_image.py` (更新 patch 目标与 import)

- [ ] **Step 1: 创建共享模块 `image_store.py`**

```python
"""Shared image downloader — fetches a remote (whop CDN) image and caches it
under ``<data_dir>/chat-images/<msg_id><ext>``.

Used by both ``app.whop.chat_writer`` (chat-source messages) and
``app.parser.service`` (stock/option image messages). whop attachment image
URLs are public CDN links, so no auth headers are needed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

_log = logging.getLogger(__name__)

_CONTENT_TYPE_EXT: dict[str, str] = {
    "image/avif": ".avif",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def download_image(
    msg_id: str, remote_url: str, data_dir: Path
) -> str | None:
    """Download *remote_url* into ``<data_dir>/chat-images/<msg_id><ext>``.

    Returns the filename (basename only) on success, or None on any failure
    (network error, HTTP error, timeout). All errors are caught and logged —
    image cache failures must not break message ingestion.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(remote_url)
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            ext = _CONTENT_TYPE_EXT.get(ct, ".bin")
            target_dir = data_dir / "chat-images"
            target_dir.mkdir(parents=True, exist_ok=True)
            # Path(...).name strips any "../" or "/" segments — defensive
            # against a malicious msg_id.
            filename = f"{Path(msg_id).name}{ext}"
            (target_dir / filename).write_bytes(resp.content)
            return filename
    except Exception:  # noqa: BLE001
        _log.warning(
            "image download failed for msg_id=%s url=%s",
            msg_id,
            remote_url,
            exc_info=True,
        )
        return None
```

- [ ] **Step 2: 重构 `chat_writer.py` 使用共享工具**

删除 `chat_writer.py` 中的 `_CONTENT_TYPE_EXT`(45-52 行)、`_download_image`(55-84 行)和 `import httpx`(29 行)。在 import 区加入:

```python
from app.whop.image_store import download_image
```

把 handler 里(原 143 行)的调用从 `_download_image(...)` 改为 `download_image(...)`:

```python
        image_filename: str | None = None
        if msg.image_url:
            image_filename = await download_image(msg.id, msg.image_url, data_dir)
```

- [ ] **Step 3: 更新现有测试的 patch 目标(函数已搬家)**

在 `backend/tests/whop/test_chat_writer_image.py`:
- 第 25 行 import 改为:`from app.whop.image_store import download_image`;并删除原从 `chat_writer` 导入 `_download_image`(保留 `register_chat_writer` 的 import:`from app.whop.chat_writer import register_chat_writer`)。
- 把所有 `_download_image(` 调用改为 `download_image(`(4 处单元测试)。
- 把所有 `patch("app.whop.chat_writer.httpx.AsyncClient", ...)` 改为 `patch("app.whop.image_store.httpx.AsyncClient", ...)`(全部 7 处:4 个单元 + 3 个集成测试)。

- [ ] **Step 4: 运行测试,确认通过**

Run: `cd backend && uv run pytest tests/whop/test_chat_writer_image.py -v`
Expected: 全部 PASS(下载工具与 handler 行为不变,只是 import/patch 路径变了)。

- [ ] **Step 5: Commit**

```bash
git add backend/app/whop/image_store.py backend/app/whop/chat_writer.py backend/tests/whop/test_chat_writer_image.py
git commit -m "refactor(whop): extract shared download_image into image_store"
```

---

### Task 2: `messages.image_filename` 列(领域 + 表 + 迁移 + repo 读写)

**Files:**
- Modify: `backend/app/domain/message.py:22`
- Modify: `backend/app/storage/schema.py:113-120` (MessageRow 加列)
- Create: `backend/alembic/versions/<rev>_add_messages_image_filename.py`
- Modify: `backend/app/storage/repo.py` (`_row_to_message` 读取 + `save_task` 的 `msg_values` 写入)
- Test: `backend/tests/storage/test_messages_image_filename.py` (新建)

- [ ] **Step 1: 写失败测试(round-trip 持久化)**

创建 `backend/tests/storage/test_messages_image_filename.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.message import Message
from app.domain.task import Task
from app.storage.db import session_scope
from app.storage.repo import get_task, save_task

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
        loaded = await get_task(session, "img_msg_1")

    assert loaded is not None
    assert loaded.message.image_filename == "img_msg_1.png"
```

> 注:若 `repo` 中读取单任务的函数不叫 `get_task`,先 `grep "^async def get" backend/app/storage/repo.py` 确认实际名字并替换。

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd backend && uv run pytest tests/storage/test_messages_image_filename.py -v`
Expected: FAIL — `Message` 没有 `image_filename` 参数(TypeError),或断言失败。

- [ ] **Step 3: 领域 `Message` 加字段**

`backend/app/domain/message.py` 第 22 行后新增:

```python
    image_url: str | None = None  # 新增：聊天消息中的图片链接（临时，不持久化）
    image_filename: str | None = None  # 下载后的本地文件名（持久化，用于代理 URL）
```

- [ ] **Step 4: `MessageRow` 加列**

`backend/app/storage/schema.py`,在 `MessageRow` 的 `quoted_message_id`(120 行)之后新增:

```python
    image_filename: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
```

- [ ] **Step 5: 写 Alembic 迁移**

先确认当前 head:

Run: `cd backend && uv run alembic heads`
Expected: 单一 head(本计划撰写时为 `0746c8880387`)。把下面的 `down_revision` 设为该 head。

创建 `backend/alembic/versions/a7c1image01_add_messages_image_filename.py`:

```python
"""add_messages_image_filename

Adds the ``image_filename`` column to ``messages`` (stock/option messages),
mirroring the chat_messages column. Stores only the basename; the API
composes the proxy URL at response time. Nullable, no default.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c1image01"
down_revision: str | Sequence[str] | None = "0746c8880387"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("image_filename", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "image_filename")
```

- [ ] **Step 6: repo 写入 — `save_task` 的 `msg_values`**

`backend/app/storage/repo.py` 的 `save_task`,在 `msg_values` 字典里(`quoted_message_id` 之后)新增:

```python
        "image_filename": msg.image_filename,
```

> 注:新消息在创建 Task **之前**就下载并写好 `image_filename`(见 Task 3),首次 INSERT 即带上。**旧数据回填**靠 Task 8 扩展 ON CONFLICT(此处不改 ON CONFLICT)。

- [ ] **Step 7: repo 读取 — `_row_to_message`**

`backend/app/storage/repo.py` 的 `_row_to_message`,在 `Message(...)` 构造里(`url=row.url` 之后)新增:

```python
        image_filename=row.image_filename,
```

- [ ] **Step 8: 运行测试 + 迁移,确认通过**

Run: `cd backend && uv run alembic upgrade head && uv run pytest tests/storage/test_messages_image_filename.py -v`
Expected: 迁移成功;测试 PASS。

- [ ] **Step 9: Commit**

```bash
git add backend/app/domain/message.py backend/app/storage/schema.py backend/alembic/versions/a7c1image01_add_messages_image_filename.py backend/app/storage/repo.py backend/tests/storage/test_messages_image_filename.py
git commit -m "feat(storage): persist messages.image_filename"
```

---

### Task 3: parser/service 对图片消息跳过解析

**Files:**
- Modify: `backend/app/parser/service.py:51-159` (加 `data_dir` 参数 + 图片分支)
- Modify: `backend/app/main.py:200`
- Test: `backend/tests/parser/test_service.py` (新增 2 个测试)

- [ ] **Step 1: 写失败测试**

在 `backend/tests/parser/test_service.py` 末尾新增。注意顶部已 import `Status`、`MessagePayload`、`TaskPayload`、`Topics`、`Message`、`register_parser_service`、`_run`。新增 import:

```python
from pathlib import Path
from unittest.mock import AsyncMock, patch
```

测试:

```python
def _stock_image_msg(id_: str, content: str = "") -> Message:
    return Message(
        id=id_,
        content=content,
        raw_content=content,
        author="trader",
        posted_at=_NOW,
        received_at=_NOW,
        source="stock",
        image_url="https://whop.com/pic.png",
    )


async def _run_status(bus: EventBus, msg: Message) -> list[Event]:
    """Like _run but also captures TASK_STATUS_CHANGED (used for skips)."""
    observed: list[Event] = []

    async def _capture(evt: Event) -> None:
        observed.append(evt)

    for topic in (
        Topics.TASK_CREATED,
        Topics.TASK_INSTRUCTION_READY,
        Topics.TASK_PARSE_FAILED,
        Topics.TASK_STATUS_CHANGED,
    ):
        bus.subscribe(topic, _capture)

    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await bus.wait_idle(timeout=5)
    await bus.wait_idle(timeout=5)
    return observed


@pytest.mark.asyncio
async def test_image_message_skips_parsing(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Stock message with image_url → SKIPPED (reason=图片消息), no parse,
    image downloaded → image_filename set on the persisted message."""
    bus = EventBus()
    register_parser_service(bus, session_factory, registry=None, data_dir=tmp_path)

    msg = _stock_image_msg("img1")
    with patch(
        "app.parser.service.download_image",
        AsyncMock(return_value="img1.png"),
    ):
        observed = await _run_status(bus, msg)

    # No parse outcome events
    assert not [e for e in observed if e.topic == Topics.TASK_INSTRUCTION_READY]
    assert not [e for e in observed if e.topic == Topics.TASK_PARSE_FAILED]

    # A status-changed event carrying SKIPPED + reason + filename
    skipped = [
        e for e in observed
        if e.topic == Topics.TASK_STATUS_CHANGED
        and e.payload.task.status == Status.SKIPPED
    ]
    assert len(skipped) == 1
    task = skipped[0].payload.task
    assert task.reject_reason == "图片消息"
    assert task.message.image_filename == "img1.png"


@pytest.mark.asyncio
async def test_option_image_message_skips_parsing(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Same behavior for option-source image messages."""
    bus = EventBus()
    register_parser_service(bus, session_factory, registry=None, data_dir=tmp_path)

    msg = Message(
        id="img2",
        content="",
        raw_content="",
        author="trader",
        posted_at=_NOW,
        received_at=_NOW,
        source="option",
        image_url="https://whop.com/opt.png",
    )
    with patch(
        "app.parser.service.download_image",
        AsyncMock(return_value="img2.png"),
    ):
        observed = await _run_status(bus, msg)

    assert not [e for e in observed if e.topic == Topics.TASK_PARSE_FAILED]
    skipped = [
        e for e in observed
        if e.topic == Topics.TASK_STATUS_CHANGED
        and e.payload.task.status == Status.SKIPPED
    ]
    assert len(skipped) == 1
    assert skipped[0].payload.task.message.image_filename == "img2.png"
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd backend && uv run pytest tests/parser/test_service.py::test_image_message_skips_parsing -v`
Expected: FAIL — `register_parser_service` 不接受 `data_dir`(TypeError),或图片消息走了解析 → 出现 TASK_PARSE_FAILED。

- [ ] **Step 3: 给 `register_parser_service` 加 `data_dir` 参数**

`backend/app/parser/service.py`,顶部 import 区新增:

```python
import dataclasses
from pathlib import Path

from app.whop.image_store import download_image
```

签名(51-56 行)改为:

```python
def register_parser_service(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    registry: _RegistryLike | None = None,
    data_dir: Path | None = None,
) -> Callable[[], None]:
```

- [ ] **Step 4: 在 handler 里加图片分支**

`_handle_message_received` 里,把开头(73-78 行)改为:**先下载并替换 msg,再创建 Task**,保证 image_filename 在第一次持久化时就写入:

```python
        msg = payload.message

        # Image message: skip instruction parsing entirely, render as image.
        # Download before creating the Task so image_filename lands on the
        # first persisted row (messages are immutable on conflict).
        if msg.image_url is not None:
            image_filename: str | None = None
            if data_dir is not None:
                image_filename = await download_image(msg.id, msg.image_url, data_dir)
            msg = dataclasses.replace(msg, image_filename=image_filename)
            task = Task.new_from_message(msg, is_historical=payload.is_historical)
            task.mark_parsing()
            await bus.publish(Event(Topics.TASK_CREATED, TaskPayload(task)))
            task.mark_skipped("图片消息")
            await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
            return

        task = Task.new_from_message(msg, is_historical=payload.is_historical)
        task.mark_parsing()

        # Publish TASK_CREATED (status=PARSING) so storage has a record
        await bus.publish(Event(Topics.TASK_CREATED, TaskPayload(task)))
```

> 其余解析逻辑(80 行起)保持不变。

- [ ] **Step 5: main.py 传 `data_dir`**

`backend/app/main.py:200` 改为:

```python
            register_parser_service(
                bus,
                session_factory,
                registry=state.whop_registry,
                data_dir=settings.data_dir,
            )
```

- [ ] **Step 6: 运行测试,确认通过**

Run: `cd backend && uv run pytest tests/parser/test_service.py -v`
Expected: 全部 PASS(含新增 2 个 + 原有 5 个未受影响)。

- [ ] **Step 7: Commit**

```bash
git add backend/app/parser/service.py backend/app/main.py backend/tests/parser/test_service.py
git commit -m "feat(parser): image messages skip parsing, mark SKIPPED"
```

---

### Task 4: `MessageOut.image_url` 字段转发

**Files:**
- Modify: `backend/app/api/schemas.py:29-38` (MessageOut), `:696-708` (message_to_out)
- Test: `backend/tests/api/test_schemas.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/api/test_schemas.py` 新增(`message_to_out` 已 import;`_make_message` 是该文件已有 helper):

```python
def test_message_to_out_image_url_from_filename() -> None:
    msg = _make_message(msg_id="img-9")
    msg = dataclasses.replace(msg, image_filename="img-9.png")
    out = message_to_out(msg)
    assert out.image_url == "/api/messages/img-9/image"


def test_message_to_out_image_url_none_without_filename() -> None:
    out = message_to_out(_make_message())
    assert out.image_url is None
```

文件顶部若无 `import dataclasses` 则加上。

> 若 `_make_message` 不支持 `dataclasses.replace`(它返回的是 frozen `Message`,replace 可用),直接用即可。

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd backend && uv run pytest tests/api/test_schemas.py::test_message_to_out_image_url_from_filename -v`
Expected: FAIL — `MessageOut` 没有 `image_url` 属性。

- [ ] **Step 3: `MessageOut` 加字段**

`backend/app/api/schemas.py` 的 `MessageOut`(29-38 行),在 `quoted_message_id` 之后新增:

```python
    image_url: str | None = None
```

- [ ] **Step 4: `message_to_out` 填充**

`backend/app/api/schemas.py` 的 `message_to_out`(698-708 行),在 `MessageOut(...)` 里 `quoted_message_id=...` 之后新增:

```python
        image_url=(
            f"/api/messages/{msg.id}/image" if msg.image_filename else None
        ),
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `cd backend && uv run pytest tests/api/test_schemas.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/tests/api/test_schemas.py
git commit -m "feat(api): MessageOut.image_url proxy path from image_filename"
```

---

### Task 5: serve 端点 `GET /api/messages/{id}/image`

**Files:**
- Modify: `backend/app/api/http.py` (新增路由 + 确保 `MessageRow` 已 import)
- Test: `backend/tests/api/test_messages_image.py` (新建)

- [ ] **Step 1: 写失败测试**

`backend/tests/api/test_chat_images.py` 把 `settings_test` + `app_with_db` fixture 定义在文件内(不在 conftest),用同步 `TestClient` 且所有请求带 `params={"token": _TOKEN}`。新文件复制这两个 fixture,并用 `repo.save_task` 播种(messages 行的 FK 指向 tasks.id,save_task 会一并写好 task+message,避免手填 TaskRow 列)。

创建 `backend/tests/api/test_messages_image.py`:

```python
"""Tests for GET /api/messages/{id}/image (stock/option image serve)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http import build_http_router
from app.broker.noop_client import NoopBrokerClient
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.domain.message import Message
from app.domain.task import Task
from app.storage import repo
from app.storage.db import Base, create_engine, make_session_factory
from app.whop.registry import WhopRegistry

_TOKEN = "test-messages-image-token"
_NOW = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)


@pytest.fixture
def settings_test(tmp_path: Path) -> Settings:
    return Settings(
        app_token=_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        whop_poll_interval=0.05,
        whop_headless=True,
        data_dir=tmp_path,
    )


@pytest.fixture
def app_with_db(
    settings_test: Settings, tmp_path: Path
) -> Iterator[tuple[TestClient, Any, asyncio.AbstractEventLoop]]:
    bus = EventBus()
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(db_url)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        async def _create_schema() -> None:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        loop.run_until_complete(_create_schema())
        factory = make_session_factory(engine)
        registry = WhopRegistry(
            bus=bus, settings=settings_test, session_factory=factory,
            pages_file=tmp_path / "pages.json",
        )
        loop.run_until_complete(registry.load_entries())
        app = FastAPI()
        app.include_router(
            build_http_router(
                session_factory=factory, broker=NoopBrokerClient(),
                settings=settings_test, bus=bus, whop_registry=registry,
            )
        )
        app.dependency_overrides[get_settings] = lambda: settings_test
        yield TestClient(app, raise_server_exceptions=True), factory, loop
    finally:
        with contextlib.suppress(Exception):
            loop.run_until_complete(registry.shutdown_all())
        with contextlib.suppress(Exception):
            loop.run_until_complete(engine.dispose())
        loop.close()
        asyncio.set_event_loop(None)


def _seed_message(
    factory: Any, loop: asyncio.AbstractEventLoop,
    msg_id: str, image_filename: str | None,
) -> None:
    async def _do() -> None:
        msg = Message(
            id=msg_id, content="", raw_content="", author="t",
            posted_at=_NOW, received_at=_NOW, source="stock",
            image_filename=image_filename,
        )
        task = Task.new_from_message(msg)
        task.mark_parsing()
        task.mark_skipped("图片消息")
        async with factory() as session:
            await repo.save_task(session, task)
    loop.run_until_complete(_do())


def test_serves_image_bytes(app_with_db, settings_test: Settings) -> None:  # noqa: ANN001
    client, factory, loop = app_with_db
    _seed_message(factory, loop, "mi_1", "mi_1.png")
    (settings_test.data_dir / "chat-images").mkdir(exist_ok=True)
    (settings_test.data_dir / "chat-images" / "mi_1.png").write_bytes(b"PNGBYTES")

    resp = client.get("/api/messages/mi_1/image", params={"token": _TOKEN})
    assert resp.status_code == 200, resp.text
    assert resp.content == b"PNGBYTES"
    assert resp.headers["content-type"].startswith("image/png")


def test_404_when_no_filename(app_with_db) -> None:  # noqa: ANN001
    client, factory, loop = app_with_db
    _seed_message(factory, loop, "mi_2", None)
    resp = client.get("/api/messages/mi_2/image", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_404_when_file_missing(app_with_db) -> None:  # noqa: ANN001
    client, factory, loop = app_with_db
    _seed_message(factory, loop, "mi_3", "ghost.png")
    resp = client.get("/api/messages/mi_3/image", params={"token": _TOKEN})
    assert resp.status_code == 404
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd backend && uv run pytest tests/api/test_messages_image.py -v`
Expected: FAIL — 404(路由不存在)。

- [ ] **Step 3: 确认 `MessageRow` 已 import**

在 `backend/app/api/http.py` 顶部 import 区确认有 `MessageRow`;若只 import 了 `ChatMessageRow`,改为:

```python
from app.storage.schema import ChatMessageRow, MessageRow
```

(以实际 import 行为准追加 `MessageRow`。)

- [ ] **Step 4: 新增路由(紧挨 `get_chat_image` 之后)**

在 `backend/app/api/http.py` 的 `@router.get("/api/chat-images/{message_id}")` 处理函数之后,新增:

```python
        @router.get("/api/messages/{message_id}/image")
        async def get_message_image(message_id: str) -> FileResponse:
            """Serve a cached stock/option message image.

            Images are downloaded by ``app.parser.service`` (via
            ``image_store.download_image``) into ``<data_dir>/chat-images/``,
            the same directory chat images use. 404 if the row is missing,
            has no image, or the file is gone.
            """
            async with session_scope(session_factory) as session:
                row = await session.get(MessageRow, message_id)
            if row is None or not row.image_filename:
                raise HTTPException(404, detail="image not found")
            images_root = (settings.data_dir / "chat-images").resolve()
            path = (images_root / row.image_filename).resolve()
            if not path.is_relative_to(images_root):
                raise HTTPException(404, detail="image not found")
            if not path.exists():
                raise HTTPException(404, detail="image file missing")
            media_type = _IMAGE_MEDIA_TYPES.get(
                path.suffix.lower(), "application/octet-stream"
            )
            return FileResponse(path, media_type=media_type)
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `cd backend && uv run pytest tests/api/test_messages_image.py -v`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_messages_image.py
git commit -m "feat(api): GET /api/messages/{id}/image serve endpoint"
```

---

### Task 6: 前端类型 + `layersForTask` 图片 kind

**Files:**
- Modify: `frontend/src/api/types.ts` (重新生成)
- Modify: `frontend/src/components/Chat/signalCardHelpers.ts:1-31` (类型), `:54-74` (逻辑)
- Test: `frontend/src/components/Chat/signalCardHelpers.test.ts`

- [ ] **Step 1: 重新生成类型(后端需可被 uv 运行)**

Run: `cd frontend && npm run gen:types`
Expected: `src/api/types.ts` 中 `MessageOut` 出现 `image_url?: string | null;`。

- [ ] **Step 2: 写失败测试**

该文件已有本地工厂 `task(over: Partial<TaskSummary>)`(注意它通过 `...over` 整体替换 `message`)。新增测试时先取一个基准 task,再展开其 `message` 仅覆盖 `image_url`/`content`:

```ts
it("image message → kind 'image' with imageUrl, no sig/ord", () => {
  const base = task({});
  const t: TaskSummary = {
    ...base,
    status: "SKIPPED",
    instruction: null,
    message: { ...base.message, content: "", image_url: "/api/messages/x/image" },
  };
  const layers = layersForTask(t);
  expect(layers.kind).toBe("image");
  expect(layers.imageUrl).toBe("/api/messages/x/image");
  expect(layers.sig).toBeNull();
  expect(layers.ord).toBeNull();
});
```

- [ ] **Step 3: 运行测试,确认失败**

Run: `cd frontend && npx vitest run src/components/Chat/signalCardHelpers.test.ts`
Expected: FAIL — `kind` 不是 `"image"`(走了 SKIPPED → ord 分支)。

- [ ] **Step 4: 扩展类型**

`frontend/src/components/Chat/signalCardHelpers.ts`:
- 第 4 行 `LayerKind` 加 `"image"`:

```ts
export type LayerKind = "normal" | "parse_error" | "neutral" | "image";
```

- `CardLayers` 接口(25-31 行)新增 `imageUrl`:

```ts
export interface CardLayers {
  kind: LayerKind;
  msg: string;
  sig: SigLayer | null;
  ord: OrdLayer | null;
  imageUrl: string | null;
}
```

> 注:这会让 TS 要求所有返回 `CardLayers` 的地方都带 `imageUrl`。Step 5 在两个现有 return 里补 `imageUrl: null`。

- [ ] **Step 5: 加图片分支 + 补现有 return**

`layersForTask`(54 行起),在 `const inst = task.instruction;`(60 行)之后、`if (task.status === "PARSE_ERROR")` 之前插入:

```ts
  if (task.message.image_url) {
    return { kind: "image", msg, sig: null, ord: null, imageUrl: task.message.image_url };
  }
```

并在现有两个 return 补 `imageUrl: null`:
- `PARSE_ERROR` 分支的返回对象(63-73 行)末尾加 `imageUrl: null,`。
- 函数末尾 `return { kind: "normal", msg, sig, ord };`(150 行)改为 `return { kind: "normal", msg, sig, ord, imageUrl: null };`。

- [ ] **Step 6: 运行测试,确认通过**

Run: `cd frontend && npx vitest run src/components/Chat/signalCardHelpers.test.ts`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/components/Chat/signalCardHelpers.ts frontend/src/components/Chat/signalCardHelpers.test.ts
git commit -m "feat(chat): layersForTask returns image kind for image messages"
```

---

### Task 7: `SignalBubble` 渲染图片气泡 + 样式

**Files:**
- Modify: `frontend/src/components/Chat/SignalBubble.tsx`
- Modify: `frontend/src/components/Chat/SignalCard.css`
- Test: `frontend/src/components/Chat/SignalBubble.test.tsx`

- [ ] **Step 1: 写失败测试**

该文件用 `makeStockTask(over)` 工厂(from `../../test/fixtures`)。新增测试,展开其 `message` 注入 `image_url`:

```ts
it("renders an image bubble for image messages", () => {
  const base = makeStockTask();
  const task = {
    ...base,
    status: "SKIPPED",
    message: { ...base.message, content: "", image_url: "/api/messages/x/image" },
  };
  const { container } = render(
    <SignalBubble task={task} pushEvents={[]} expanded={false}
      onToggle={() => {}} autoTrade={true} variant="stock" />,
  );
  const img = container.querySelector("img.signal-bubble-image");
  expect(img).not.toBeNull();
  // 不应出现解析报错文案
  expect(container.textContent).not.toContain("未解析");
});
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd frontend && npx vitest run src/components/Chat/SignalBubble.test.tsx`
Expected: FAIL — 找不到 `img.signal-bubble-image`。

- [ ] **Step 3: SignalBubble 渲染图片分支**

`frontend/src/components/Chat/SignalBubble.tsx`:
- 顶部 import 区加入(已 import `fmtBeijingFull, submitEndIso`):

```ts
import { authedAssetUrl } from "../../api/http";
```

- 在 `const layers = layersForTask(task, { autoTrade });` 之后加:

```ts
  const isImage = layers.kind === "image";
```

- 把 `return (` 里根 `<div className={...signal-bubble...}>` 的**子内容**改为按 `isImage` 分支。即把现有的 `<div className="signal-summary">...</div>` 和 `{expanded && (<div className="signal-detail">...)}` 包到 `{isImage ? (...) : (<>...原内容...</>)}`:

```tsx
      {isImage ? (
        <div className="signal-summary">
          {layers.imageUrl && (
            <img
              className="signal-bubble-image"
              src={authedAssetUrl(layers.imageUrl)}
              alt=""
            />
          )}
          {layers.msg && (
            <div className="layer-msg" title={layers.msg}>{layers.msg}</div>
          )}
        </div>
      ) : (
        <>
          {/* …现有的 signal-summary + expanded signal-detail 原样放这里… */}
        </>
      )}
```

> 保持根 `<div className={`signal-bubble ${sourceClass}`} ...onClick/onKeyDown...>` 不变。图片分支不渲染 sig/ord/解析层与展开详情。

- [ ] **Step 4: 加样式(注意不要依赖 ChatBoardPanel.css)**

`frontend/src/components/Chat/SignalCard.css` 末尾新增(SignalBubble 只 import 这个文件,`chat-group-image` 在 ChatBoardPanel.css 里、此处不可用):

```css
.signal-bubble-image {
  display: block;
  max-width: 260px;
  max-height: 260px;
  border-radius: 8px;
  margin-bottom: 4px;
}
```

- [ ] **Step 5: 运行测试,确认通过**

Run: `cd frontend && npx vitest run src/components/Chat/SignalBubble.test.tsx`
Expected: PASS。

- [ ] **Step 6: 全量前端校验**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep -E "SignalBubble|signalCardHelpers|types.ts" || echo OK`
Expected: 无本特性相关报错(其它既有的无关测试文件报错忽略)。

Run: `cd frontend && npx vitest run src/components/Chat`
Expected: Chat 目录测试全过(必要时用 `-u` 更新受影响的快照,并人工核对快照 diff 合理)。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/Chat/SignalBubble.tsx frontend/src/components/Chat/SignalCard.css frontend/src/components/Chat/SignalBubble.test.tsx
git commit -m "feat(chat): render image bubble in SignalBubble for image messages"
```

---

### Task 8: 旧数据回填 — `messages` UPSERT 可回填 `image_filename`

**Files:**
- Modify: `backend/app/storage/repo.py` (`save_task` 的 messages UPSERT)
- Test: `backend/tests/storage/test_messages_image_filename.py` (新增 2 个测试)

**背景:** 旧的图片消息已是终态 `PARSE_ERROR`、`messages` 行 `image_filename` 为空且不可变。要让「重抓 whop 历史」(调已有的 `POST /api/whop/pages/{id}/restart`)能修好它们,需让 messages 的 UPSERT 在 `image_filename` 为空时回填它。前端 `layersForTask` 把图片判断放在 `PARSE_ERROR` 之前,所以补上 `image_filename` 后即显示图片,无需改任务状态(终态保护会保留 PARSE_ERROR,无妨)。`func` 已在 `repo.py:28` 导入。

- [ ] **Step 1: 写失败测试**

在 `backend/tests/storage/test_messages_image_filename.py` 新增。复用文件已有 import(`Message`、`Task`、`save_task`、`get_task`、`session_scope`、`_NOW`):

```python
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
        loaded = await get_task(session, "bf_1")
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
        loaded = await get_task(session, "bf_2")
    assert loaded is not None
    assert loaded.message.image_filename == "original.png"  # 未被覆盖
```

在该测试文件顶部加 helper(避免在断言里写 dataclasses 噪音):

```python
import dataclasses


def dataclasses_replace_filename(msg, filename):
    return dataclasses.replace(msg, image_filename=filename)
```

- [ ] **Step 2: 运行测试,确认失败**

Run: `cd backend && uv run pytest tests/storage/test_messages_image_filename.py -v`
Expected: `test_image_filename_backfilled_on_resave` FAIL — 回填前 messages UPSERT 只 backfill `url`,`image_filename` 维持 None。

- [ ] **Step 3: 扩展 messages UPSERT 回填**

`backend/app/storage/repo.py` 的 `save_task`,把现有 messages UPSERT(只 backfill `url`)改为同时 coalesce 回填 `url` 与 `image_filename`:

```python
    msg_stmt = sqlite_insert(MessageRow).values(**msg_values)
    msg_stmt = msg_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={
            "url": func.coalesce(MessageRow.url, msg_stmt.excluded.url),
            "image_filename": func.coalesce(
                MessageRow.image_filename, msg_stmt.excluded.image_filename
            ),
        },
        where=MessageRow.url.is_(None) | MessageRow.image_filename.is_(None),
    )
    await session.execute(msg_stmt)
```

> `coalesce(existing, excluded)` 保证仅在原值为空时填入,不覆盖已有非空值;`where` 用 OR 让任一列为空时都进入 UPDATE 分支(两列都已填的「真不可变」行仍是 no-op)。

- [ ] **Step 4: 运行测试,确认通过(含既有 url 回填测试无回归)**

Run: `cd backend && uv run pytest tests/storage/test_messages_image_filename.py tests/storage/test_repo.py -v`
Expected: 新增 2 个 PASS;`test_repo.py` 里既有的 messages.url 回填测试仍 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_messages_image_filename.py
git commit -m "feat(storage): backfill messages.image_filename on upsert for re-scrape"
```

---

## 回填操作流程(部署后执行,非代码)

1. 部署本特性(Task 1–8 全部上线、迁移已 `alembic upgrade head`)。
2. 在 whop 前端把含旧图片消息的页面**向上滚动**,让那些消息重新进入 DOM(listener 只抓当前可见 DOM)。
3. 对该页面调用:`POST /api/whop/pages/{page_id}/restart`(带 `token`)。`restart_page` 以 `skip_initial=False` 重启 listener,重新发布可见消息 → 走新解析路径:图片消息下载图片 → messages UPSERT 回填 `image_filename` → 前端显示图片。
4. **限制**:只能恢复仍能在 whop 加载到的历史;更早/已过期、URL 不可得的消息无法恢复。

---

## 收尾验证(全部任务完成后)

- [ ] 后端全量:`cd backend && uv run pytest -q`(关注 parser/storage/api 相关无回归)。
- [ ] 前端全量:`cd frontend && npx vitest run`(本特性相关全过;预先存在的无关失败不在本次范围)。
- [ ] 手动联调(可选但推荐):起后端 + `cd frontend && npm run dev`,等一条带图片的正股/期权消息进来,确认气泡显示图片而非「未解析」;刷新页面后图片仍在(走 `/api/messages/{id}/image` 代理)。

## 注意事项 / 已知边界

- **下载失败**:`image_filename` 为 None → 任务仍 SKIPPED(reason=图片消息),`MessageOut.image_url` 为 null → 前端 `layersForTask` 不命中 image 分支,落到 SKIPPED → ord 文案显示「图片消息」。这是可接受的退化(不显示破图)。
- **存量旧数据**:通过 Task 8(messages UPSERT 回填 image_filename)+ 上面的「回填操作流程」(restart 重抓可见历史)修复。前端按 image_url 优先渲染,旧任务状态留 PARSE_ERROR 无妨。仅能恢复 whop 仍加载得到的历史;更早/过期消息无法恢复。
- **真实 SKIPPED**(人工/规则跳过):无 image_url,前端照旧显示「已跳过」。
- **`_message_to_row`**(repo.py:180)目前是死代码(无调用方),本计划不动它;持久化走 `save_task` 内联的 `msg_values`。
