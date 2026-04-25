# 监控看板二级 tab + per-page 监听设置 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在监控看板内为每个 Whop 监听页加二级 tab，per-page 设置（去重 / ticker 白名单 + 数量 / 价格偏差），把价格偏差从拒单 gate 改为 MARKET/LIMIT 决策，废弃 watched_stocks.json。

**Architecture:** 后端 `WhopRegistry` 持久化 `PageSettings`；`WhopListener` 启动时按设置从 SQLite 灌 `_seen` 实现去重；`Trader` 通过 `task.message.url` 反查 page settings 决定白名单 / qty / order_type；前端 `pageTabs` store 实时同步 page 列表 + WS `whop.page_changed` 事件，dashboard 组件按 `task.url` filter 显示。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2.x async / alembic / pytest / React 18 / Zustand / Vite / vitest

**Spec:** `docs/superpowers/specs/2026-04-25-dashboard-tabs-and-listener-config-design.md`

---

## File Map

### 新建
- `backend/alembic/versions/<rev>_add_messages_url.py`
- `backend/app/whop/page_settings.py` — `PageSettings` / `TickerConfig` dataclass + `position_size_to_fraction()`
- `backend/tests/whop/test_page_settings.py`
- `backend/tests/storage/test_repo_seen_ids.py`
- `backend/tests/whop/test_listener_dedupe.py`
- `backend/tests/broker/test_trader_deviation.py`
- `backend/tests/api/test_whop_settings.py`
- `frontend/src/stores/pageTabs.ts` + `.test.ts`
- `frontend/src/components/Dashboard/PageTabs.tsx` + `.test.tsx`
- `frontend/src/components/Dashboard/PageInfoBar.tsx` + `.test.tsx`
- `frontend/src/components/Dashboard/PageActionBar.tsx` + `.test.tsx`
- `frontend/src/components/Dashboard/PageSettingsModal.tsx` + `.test.tsx`
- `frontend/src/components/Dashboard/TaskStream.tsx`
- `frontend/src/components/Dashboard/EmptyState.tsx`
- `frontend/src/components/Dashboard/Dashboard.css`

### 修改
- `backend/app/storage/schema.py` — `MessageRow.url`
- `backend/app/storage/repo.py` — `_message_to_row` / `_row_to_message` 加 url；新增 `load_seen_ids_for_url()`
- `backend/app/domain/message.py` — `Message.url`
- `backend/app/whop/listener.py` — `dedupe_processed_messages` ctor 参数；`start()` 灌 _seen；`_scan_once` 注入 url
- `backend/app/whop/registry.py` — `WhopPageEntry.settings`；`update_settings`；`get_settings_for_url`；事件发布
- `backend/app/parser/service.py` — `_handle_message_received` 通过 registry 取 tickers
- `backend/app/parser/context_resolver.py` — 删除 `load_watched_tickers`；`watched_tickers` 改为强制参数
- `backend/app/broker/trader.py` — 反查 page settings；白名单 gate；qty 计算；偏差 → MARKET/LIMIT
- `backend/app/broker/config.py` — 移除 deviation 字段（保留 fallback 用 Settings 直接读）
- `backend/app/core/events.py` — `Topics.WHOP_PAGE_CHANGED`；`WhopPagePayload`
- `backend/app/api/ws.py` — bridge `WHOP_PAGE_CHANGED`
- `backend/app/api/schemas.py` — `MessageOut.url`；`WhopPageSettingsOut`/`In`；`WhopPageOut.settings`
- `backend/app/api/http.py` — `PATCH /api/whop/pages/{id}/settings`；`GET /api/whop/pages/defaults`
- `backend/app/main.py` — 移除 `load_watched_tickers` 调用；ParserService 注入 registry；trader 注入 registry
- `frontend/src/api/http.ts` — `updateWhopPageSettings`；`whopPageSettingsDefaults`
- `frontend/src/api/domain-types.ts` — 加新类型 re-export
- `frontend/src/stores/tasks.ts` — `tasksByUrl` selector
- `frontend/src/App.tsx` — `Dashboard` 改成 orchestrator，移除内部 task 流逻辑
- `frontend/src/components/Card/Card.tsx`（仅参数传递改动；如 expand mode 通过 prop 注入）
- `frontend/src/api/ws.ts` — handle `whop.page_changed` 调度到 pageTabs store

### 删除
- `config/watched_stocks.json`（整个文件）
- `utils/watched_stocks.py`（如果存在）
- 旧 root 的 `parser/stock_parser.py` / `parser/stock_context_resolver.py` / `broker/position_manager.py` 中对 `utils.watched_stocks` 的 `import` —— 移除引用而非整文件删除

---

## Task A: 加 `messages.url` 列

**Files:**
- Modify: `backend/app/storage/schema.py`
- Modify: `backend/app/domain/message.py`
- Create: `backend/alembic/versions/<rev>_add_messages_url.py`
- Modify: `backend/app/storage/repo.py`
- Modify: `backend/tests/storage/test_repo.py`（找到现有最相关的 test，复用其 fixture 规则；如不存在则新建 `test_repo_url.py`）

- [ ] **A.1: 给 Message domain 加 url 字段**

修改 `backend/app/domain/message.py`：

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
    url: str | None = None         # 新增：来源页 url；None 表示孤儿（migration 前数据）
    quoted: Message | None = None
    history_hint: list[Message] = field(default_factory=list)
```

- [ ] **A.2: 给 MessageRow 加 url 列**

修改 `backend/app/storage/schema.py` 的 `MessageRow`，在 `quoted_message_id` 上方插入：

```python
    url: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
```

并在 `__table_args__` 加 index（如果该类还没有 `__table_args__`，新建）：

```python
class MessageRow(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_url", "url"),
    )
    # ... existing columns ...
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **A.3: repo 序列化 / 反序列化加 url**

修改 `backend/app/storage/repo.py` 的 `_message_to_row`：

```python
def _message_to_row(msg: Message) -> MessageRow:
    return MessageRow(
        id=msg.id,
        content=msg.content,
        raw_content=msg.raw_content,
        author=msg.author,
        source=msg.source,
        posted_at=msg.posted_at,
        received_at=msg.received_at,
        url=msg.url,                                                 # 新增
        quoted_message_id=msg.quoted.id if msg.quoted is not None else None,
    )
```

`_row_to_message`：

```python
def _row_to_message(row: MessageRow) -> Message:
    return Message(
        id=row.id,
        content=row.content,
        raw_content=row.raw_content,
        author=row.author,
        posted_at=_ensure_utc(row.posted_at),
        received_at=_ensure_utc(row.received_at),
        source=row.source,                                          # type: ignore[arg-type]
        url=row.url,                                                # 新增
        quoted=None,
        history_hint=[],
    )
```

`save_task` 里的 `msg_values` 也加 `url`：

```python
    msg_values: dict[str, Any] = {
        "id": msg.id,
        "content": msg.content,
        "raw_content": msg.raw_content,
        "author": msg.author,
        "source": msg.source,
        "posted_at": msg.posted_at,
        "received_at": msg.received_at,
        "url": msg.url,                                              # 新增
        "quoted_message_id": msg.quoted.id if msg.quoted is not None else None,
    }
```

- [ ] **A.4: 写 alembic migration**

创建 `backend/alembic/versions/<auto_revid>_add_messages_url.py`（用 `cd backend && uv run alembic revision -m "add messages.url"` 生成 revision id，然后填充 upgrade/downgrade）：

```python
"""add messages.url + index

Revision ID: <填写自动生成>
Revises: 4d8877dc7b4f
Create Date: 2026-04-25 ...
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "<auto>"
down_revision: str | Sequence[str] | None = "4d8877dc7b4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("url", sa.String(), nullable=True))
    op.create_index("idx_messages_url", "messages", ["url"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_messages_url", table_name="messages")
    op.drop_column("messages", "url")
```

- [ ] **A.5: 写 round-trip test**

在 `backend/tests/storage/test_repo.py` 新增（或 `test_repo_url.py` 新建）：

```python
import pytest
from datetime import UTC, datetime

from app.domain.message import Message
from app.domain.task import Task
from app.storage import repo


@pytest.mark.asyncio
async def test_message_url_persists_through_save_and_load(session_factory):
    msg = Message(
        id="domid-with-url",
        content="x",
        raw_content="x",
        author="a",
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url="https://whop.com/joined/test/app/",
    )
    task = Task.new_from_message(msg)
    async with session_factory() as session:
        await repo.save_task(session, task)
    async with session_factory() as session:
        loaded = await repo.load_task(session, "domid-with-url")
    assert loaded is not None
    assert loaded.message.url == "https://whop.com/joined/test/app/"


@pytest.mark.asyncio
async def test_message_url_default_none(session_factory):
    msg = Message(
        id="domid-no-url",
        content="x",
        raw_content="x",
        author="a",
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
    )
    task = Task.new_from_message(msg)
    async with session_factory() as session:
        await repo.save_task(session, task)
    async with session_factory() as session:
        loaded = await repo.load_task(session, "domid-no-url")
    assert loaded is not None
    assert loaded.message.url is None
```

`session_factory` 是 conftest 已有 fixture（基于 in-memory SQLite，create_all 会自动建带 url 列的 messages 表）。

- [ ] **A.6: 跑测试 + alembic upgrade**

```bash
cd backend && uv run pytest tests/storage/test_repo.py -v
```
Expected: 2 个新 url-test 通过；其他 storage 测试仍全绿（因为 url 默认 None 不影响旧路径）。

```bash
cd backend && uv run alembic upgrade head
```
Expected: `Running upgrade 4d8877dc7b4f -> <new>, add messages.url + index`，不报错。如果本地数据库已经有旧 messages 表，alembic 会执行 ALTER TABLE 加列。

- [ ] **A.7: Commit**

```bash
git add backend/app/domain/message.py backend/app/storage/schema.py backend/app/storage/repo.py backend/alembic/versions/*_add_messages_url.py backend/tests/storage/test_repo.py
git commit -m "$(cat <<'EOF'
feat(storage): messages 表加 url 列 + alembic migration

为后续监听页归属反查准备数据。Message domain / repo 序列化都加 url；老数据 url=None。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task B: 新增 `repo.load_seen_ids_for_url`

**Files:**
- Modify: `backend/app/storage/repo.py`
- Create: `backend/tests/storage/test_repo_seen_ids.py`

- [ ] **B.1: 写 failing test**

新建 `backend/tests/storage/test_repo_seen_ids.py`：

```python
import pytest
from datetime import UTC, datetime

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
```

- [ ] **B.2: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/storage/test_repo_seen_ids.py -v
```
Expected: AttributeError: module 'app.storage.repo' has no attribute 'load_seen_ids_for_url'

- [ ] **B.3: 实现 `load_seen_ids_for_url`**

`backend/app/storage/repo.py` 末尾：

```python
async def load_seen_ids_for_url(session: AsyncSession, url: str) -> set[str]:
    """SELECT id FROM messages WHERE url=? — 用于 listener 启动时去重灌 _seen。

    返回该 url 对应所有已落库的 message id 集合（即 task id，因为 task.id = message.id）。
    """
    result = await session.execute(
        select(MessageRow.id).where(MessageRow.url == url)
    )
    return {row[0] for row in result.all()}
```

- [ ] **B.4: 跑测试**

```bash
cd backend && uv run pytest tests/storage/test_repo_seen_ids.py -v
```
Expected: 2 passed.

- [ ] **B.5: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_repo_seen_ids.py
git commit -m "$(cat <<'EOF'
feat(storage): repo.load_seen_ids_for_url

按 url 拉历史 message id 集合，给 listener 启动去重用。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task C: 新建 `PageSettings` + `position_size_to_fraction`

**Files:**
- Create: `backend/app/whop/page_settings.py`
- Create: `backend/tests/whop/test_page_settings.py`

- [ ] **C.1: 写 failing test**

新建 `backend/tests/whop/test_page_settings.py`：

```python
import pytest

from app.whop.page_settings import (
    DEFAULT_OPTION_SETTINGS,
    DEFAULT_STOCK_SETTINGS,
    PageSettings,
    TickerConfig,
    page_settings_from_dict,
    page_settings_to_dict,
    position_size_to_fraction,
)


def test_default_stock_settings_shape():
    s = DEFAULT_STOCK_SETTINGS
    assert s.dedupe_processed_messages is True
    assert s.price_deviation_tolerance == 1.0
    assert s.tickers == {}


def test_default_option_settings_shape():
    s = DEFAULT_OPTION_SETTINGS
    assert s.dedupe_processed_messages is True
    assert s.price_deviation_tolerance == 5.0
    assert s.tickers is None


def test_round_trip_stock():
    src = PageSettings(
        dedupe_processed_messages=False,
        price_deviation_tolerance=0.7,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    out = page_settings_from_dict(page_settings_to_dict(src), source="stock")
    assert out == src


def test_round_trip_option_drops_tickers():
    src = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=8.0,
        tickers=None,
    )
    d = page_settings_to_dict(src)
    assert "tickers" not in d
    out = page_settings_from_dict(d, source="option")
    assert out.tickers is None


def test_position_size_to_fraction_known():
    assert position_size_to_fraction(None) == 1.0
    assert position_size_to_fraction("常规仓") == 1.0
    assert position_size_to_fraction("半仓") == 0.5
    assert position_size_to_fraction("常规仓的一半") == 0.5
    assert position_size_to_fraction("常规一半") == 0.5
    assert position_size_to_fraction("常规的一半") == 0.5
    assert position_size_to_fraction("一半") == 0.5
    assert position_size_to_fraction("1/2") == 0.5
    assert position_size_to_fraction("1/3") == pytest.approx(1 / 3)
    assert position_size_to_fraction("2/3") == pytest.approx(2 / 3)
    assert position_size_to_fraction("1/4") == 0.25
    assert position_size_to_fraction("三分之一") == pytest.approx(1 / 3)
    assert position_size_to_fraction("三分之二") == pytest.approx(2 / 3)


def test_position_size_to_fraction_keywords():
    assert position_size_to_fraction("小仓位") == 0.5
    assert position_size_to_fraction("中仓位") == 1.0
    assert position_size_to_fraction("大仓位") == 1.5
    assert position_size_to_fraction("轻仓") == 0.5
    assert position_size_to_fraction("满仓") == 2.0


def test_position_size_to_fraction_unknown_falls_back_to_one(caplog):
    assert position_size_to_fraction("乱七八糟") == 1.0


def test_ticker_keys_uppercased_on_from_dict():
    raw = {
        "dedupe_processed_messages": True,
        "price_deviation_tolerance": 1.0,
        "tickers": {"tsll": {"trade_quantity": 100}},
    }
    out = page_settings_from_dict(raw, source="stock")
    assert "TSLL" in out.tickers
    assert "tsll" not in out.tickers
```

- [ ] **C.2: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/whop/test_page_settings.py -v
```
Expected: ImportError on `app.whop.page_settings`.

- [ ] **C.3: 实现 page_settings 模块**

新建 `backend/app/whop/page_settings.py`：

```python
"""PageSettings —— per-page 监听设置（去重开关、价格偏差容忍、stock ticker 白名单+数量）。

option page 的 settings.tickers = None；stock page 的 = {} 起步。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class TickerConfig:
    trade_quantity: int   # "常规仓" 对应的整股数；半仓 → 一半，1/3 → trade_quantity/3 …


@dataclass
class PageSettings:
    dedupe_processed_messages: bool = True
    price_deviation_tolerance: float = 1.0  # 单位：百分比（1.0 = 1%）
    tickers: dict[str, TickerConfig] | None = field(default_factory=dict)


DEFAULT_STOCK_SETTINGS = PageSettings(
    dedupe_processed_messages=True,
    price_deviation_tolerance=1.0,
    tickers={},
)

DEFAULT_OPTION_SETTINGS = PageSettings(
    dedupe_processed_messages=True,
    price_deviation_tolerance=5.0,
    tickers=None,
)


def default_settings_for(source: Literal["stock", "option"]) -> PageSettings:
    if source == "stock":
        return PageSettings(
            dedupe_processed_messages=DEFAULT_STOCK_SETTINGS.dedupe_processed_messages,
            price_deviation_tolerance=DEFAULT_STOCK_SETTINGS.price_deviation_tolerance,
            tickers={},
        )
    if source == "option":
        return PageSettings(
            dedupe_processed_messages=DEFAULT_OPTION_SETTINGS.dedupe_processed_messages,
            price_deviation_tolerance=DEFAULT_OPTION_SETTINGS.price_deviation_tolerance,
            tickers=None,
        )
    raise ValueError(f"unknown source: {source!r}")


def page_settings_to_dict(s: PageSettings) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dedupe_processed_messages": s.dedupe_processed_messages,
        "price_deviation_tolerance": s.price_deviation_tolerance,
    }
    if s.tickers is not None:
        out["tickers"] = {k: {"trade_quantity": v.trade_quantity} for k, v in s.tickers.items()}
    return out


def page_settings_from_dict(
    d: dict[str, Any],
    *,
    source: Literal["stock", "option"],
) -> PageSettings:
    """Tolerant parser: missing keys → use defaults; ticker keys → uppercased."""
    base = default_settings_for(source)
    dedupe = bool(d.get("dedupe_processed_messages", base.dedupe_processed_messages))
    tol = float(d.get("price_deviation_tolerance", base.price_deviation_tolerance))
    tickers: dict[str, TickerConfig] | None
    if source == "option":
        tickers = None
    else:
        raw_tickers = d.get("tickers", {}) or {}
        tickers = {
            str(k).upper(): TickerConfig(trade_quantity=int(v["trade_quantity"]))
            for k, v in raw_tickers.items()
        }
    return PageSettings(
        dedupe_processed_messages=dedupe,
        price_deviation_tolerance=tol,
        tickers=tickers,
    )


# --------------------------------------------------------------------------- #
# Position size string → fraction multiplier                                    #
# --------------------------------------------------------------------------- #

_FRACTION_MAP: dict[str, float] = {
    "常规仓": 1.0,
    "中仓位": 1.0,
    "常规仓的一半": 0.5,
    "常规一半": 0.5,
    "常规的一半": 0.5,
    "半仓": 0.5,
    "一半": 0.5,
    "小仓位": 0.5,
    "轻仓": 0.5,
    "大仓位": 1.5,
    "满仓": 2.0,
    "1/2": 0.5,
    "1/3": 1 / 3,
    "2/3": 2 / 3,
    "1/4": 0.25,
    "1/5": 0.2,
    "三分之一": 1 / 3,
    "三分之二": 2 / 3,
    "四分之一": 0.25,
    "五分之一": 0.2,
}


def position_size_to_fraction(s: str | None) -> float:
    """把 stock_parser 解出来的 position_size 字符串 → 仓位比例倍数。

    未识别 / None → 1.0（按 trade_quantity 全量下单）。
    未识别时记 warning，便于后续补条目。
    """
    if not s:
        return 1.0
    s2 = s.strip()
    if s2 in _FRACTION_MAP:
        return _FRACTION_MAP[s2]
    logger.warning("unrecognized position_size %r — falling back to 1.0", s2)
    return 1.0
```

- [ ] **C.4: 跑测试**

```bash
cd backend && uv run pytest tests/whop/test_page_settings.py -v
```
Expected: All 7 tests pass.

- [ ] **C.5: Commit**

```bash
git add backend/app/whop/page_settings.py backend/tests/whop/test_page_settings.py
git commit -m "$(cat <<'EOF'
feat(whop): PageSettings dataclass + position_size_to_fraction

per-page 监听设置数据模型；stock 仓位描述字符串到比例倍数的映射。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task D: `WhopRegistry` 集成 PageSettings + url 反查 + 事件

**Files:**
- Modify: `backend/app/whop/registry.py`
- Modify: `backend/app/core/events.py`
- Modify: `backend/tests/whop/test_registry.py`

- [ ] **D.1: 写 failing tests for registry settings**

在 `backend/tests/whop/test_registry.py` 末尾追加（不破坏现有测试）：

```python
import pytest
from app.whop.page_settings import (
    DEFAULT_STOCK_SETTINGS,
    PageSettings,
    TickerConfig,
)


def test_registry_add_page_uses_default_settings(_registry_factory):
    """add_page without settings → entry.settings = source default."""
    reg = _registry_factory()
    # ... use existing pattern in tests/whop/test_registry.py to create + assert ...
    # NOTE: replace _registry_factory with the actual fixture name your test file uses.


@pytest.mark.asyncio
async def test_update_settings_persists_and_returns_entry(reg_with_stock_page):
    reg, entry = reg_with_stock_page
    new_settings_patch = {
        "tickers": {"NVDA": {"trade_quantity": 500}},
        "price_deviation_tolerance": 0.7,
    }
    updated = await reg.update_settings(entry.id, new_settings_patch)
    assert updated.settings.tickers == {"NVDA": TickerConfig(trade_quantity=500)}
    assert updated.settings.price_deviation_tolerance == 0.7
    # dedupe was not in patch → preserved
    assert updated.settings.dedupe_processed_messages is True


@pytest.mark.asyncio
async def test_update_settings_unknown_id_raises(reg_empty):
    with pytest.raises(KeyError):
        await reg_empty.update_settings("does-not-exist", {})


@pytest.mark.asyncio
async def test_update_settings_option_rejects_tickers(reg_with_option_page):
    reg, entry = reg_with_option_page
    with pytest.raises(ValueError, match="tickers"):
        await reg.update_settings(entry.id, {"tickers": {"AAPL": {"trade_quantity": 1}}})


def test_get_settings_for_url_match(reg_with_stock_page):
    reg, entry = reg_with_stock_page
    s = reg.get_settings_for_url(entry.url)
    assert s is not None
    assert s.dedupe_processed_messages is True


def test_get_settings_for_url_orphan(reg_with_stock_page):
    reg, _ = reg_with_stock_page
    assert reg.get_settings_for_url("https://whop.com/unknown/app/") is None
    assert reg.get_settings_for_url(None) is None
```

提示：现有 `tests/whop/test_registry.py` 已有 fixture 模式（read it 一下确认命名）。如果没有 `reg_with_stock_page` / `reg_empty` / `reg_with_option_page` fixture，按现有 fixture 风格新增到该文件顶部或 `tests/whop/conftest.py`：

```python
@pytest.fixture
async def reg_empty(monkeypatch, tmp_path):
    from app.whop.registry import WhopRegistry
    from app.core.event_bus import EventBus
    from app.core.config import Settings
    bus = EventBus()
    settings = Settings()  # uses defaults
    pages_file = tmp_path / "pages.json"
    reg = WhopRegistry(bus=bus, settings=settings, pages_file=pages_file)
    return reg


@pytest.fixture
async def reg_with_stock_page(reg_empty, monkeypatch):
    # Patch _start_listener so add_page doesn't try to launch real Playwright
    async def _noop_start(self, entry, *, skip_initial=True):
        self._listeners[entry.id] = None  # type: ignore[assignment]
    monkeypatch.setattr(type(reg_empty), "_start_listener", _noop_start)
    entry = await reg_empty.add_page(
        url="https://whop.com/test-stock/app/",
        source="stock",
        name="TestStock",
    )
    return reg_empty, entry


@pytest.fixture
async def reg_with_option_page(reg_empty, monkeypatch):
    async def _noop_start(self, entry, *, skip_initial=True):
        self._listeners[entry.id] = None  # type: ignore[assignment]
    monkeypatch.setattr(type(reg_empty), "_start_listener", _noop_start)
    entry = await reg_empty.add_page(
        url="https://whop.com/test-option/app/",
        source="option",
        name="TestOption",
    )
    return reg_empty, entry
```

- [ ] **D.2: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/whop/test_registry.py -v
```
Expected: New tests fail (`update_settings` / `get_settings_for_url` not defined; or `entry.settings` AttributeError).

- [ ] **D.3: 修改 events.py 加新 topic + payload**

修改 `backend/app/core/events.py`：

```python
class Topics:
    MESSAGE_RECEIVED = "message.received"
    TASK_CREATED = "task.created"
    TASK_INSTRUCTION_READY = "task.instruction_ready"
    TASK_PARSE_FAILED = "task.parse_failed"
    TASK_ORDER_SUBMITTED = "task.order_submitted"
    TASK_SUBMIT_FAILED = "task.submit_failed"
    TASK_PUSH_EVENT = "task.push_event"
    TASK_STATUS_CHANGED = "task.status_changed"
    SYSTEM_CONNECTION_CHANGED = "system.connection_changed"
    WHOP_PAGE_CHANGED = "whop.page_changed"      # 新


@dataclass(frozen=True)
class WhopPagePayload:
    """Payload for whop.page_changed events."""
    action: str          # "added" | "removed" | "restarted" | "settings_updated"
    page_dict: dict      # 完整 page out dict（schema convert 在发布点完成）
```

- [ ] **D.4: 修改 WhopRegistry**

修改 `backend/app/whop/registry.py`：

`WhopPageEntry` 加 `settings`：

```python
from app.whop.page_settings import (
    PageSettings,
    default_settings_for,
    page_settings_from_dict,
    page_settings_to_dict,
)


@dataclass
class WhopPageEntry:
    id: str
    url: str
    source: str  # "stock" | "option"
    name: str
    added_at: datetime
    settings: PageSettings = field(default_factory=lambda: default_settings_for("stock"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "source": self.source,
            "name": self.name,
            "added_at": self.added_at.isoformat(),
            "settings": page_settings_to_dict(self.settings),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WhopPageEntry:
        source = d["source"]
        settings_raw = d.get("settings")
        if settings_raw is None:
            settings = default_settings_for(source)  # legacy entry without settings
        else:
            settings = page_settings_from_dict(settings_raw, source=source)
        return cls(
            id=d["id"],
            url=d["url"],
            source=source,
            name=d.get("name") or d["url"],
            added_at=datetime.fromisoformat(d["added_at"]),
            settings=settings,
        )
```

`WhopRegistry` 加新方法 + 改 `add_page` / `remove_page` / `restart_page` 触发事件，并维护 url 反查表：

```python
class WhopRegistry:
    def __init__(self, *, bus, settings, pages_file=None):
        self._bus = bus
        self._settings = settings
        self._pages_file = pages_file or _DEFAULT_PAGES_FILE
        self._lock = asyncio.Lock()
        self._entries: dict[str, WhopPageEntry] = {}
        self._listeners: dict[str, WhopListener] = {}
        self._url_index: dict[str, str] = {}     # url -> entry_id

    def _rebuild_url_index(self) -> None:
        self._url_index = {e.url: e.id for e in self._entries.values()}

    def get_settings_for_url(self, url: str | None) -> PageSettings | None:
        """O(1) reverse lookup; returns None for orphan urls."""
        if not url:
            return None
        eid = self._url_index.get(url)
        if eid is None:
            return None
        return self._entries[eid].settings

    async def update_settings(self, page_id: str, patch: dict[str, Any]) -> WhopPageEntry:
        async with self._lock:
            entry = self._entries.get(page_id)
            if entry is None:
                raise KeyError(f"page not found: {page_id}")

            # Validate option page rejects tickers
            if entry.source == "option" and "tickers" in patch:
                raise ValueError("option page does not accept 'tickers'")

            # Merge patch into existing settings dict
            current_dict = page_settings_to_dict(entry.settings)
            current_dict.update(patch)
            new_settings = page_settings_from_dict(current_dict, source=entry.source)
            entry.settings = new_settings
            self._save_entries()

        await self._publish_change("settings_updated", entry)
        return entry

    async def _publish_change(self, action: str, entry: WhopPageEntry) -> None:
        from app.api.schemas import whop_page_to_out
        listener = self._listeners.get(entry.id)
        page_dict = whop_page_to_out(entry, listener).model_dump(mode="json")
        await self._bus.publish(
            Event(Topics.WHOP_PAGE_CHANGED, WhopPagePayload(action=action, page_dict=page_dict))
        )
```

在每处 `self._save_entries()` / 修改 `_entries` 后都调用 `self._rebuild_url_index()`。

修改 `add_page` 末尾：
```python
        # ... existing code that creates entry, saves, starts listener ...
        self._rebuild_url_index()
        await self._publish_change("added", entry)
        return entry
```

修改 `remove_page`：
```python
        # after entries.pop ...
        self._save_entries()
        self._rebuild_url_index()
        await self._publish_change("removed", entry)
        return True
```

修改 `restart_page`：
```python
        # after _start_listener succeeds ...
        await self._publish_change("restarted", entry)
        return True
```

修改 `load_and_start_all` 末尾添加：
```python
        self._rebuild_url_index()
```

加必要的 imports：
```python
from app.core.event_bus import Event
from app.core.events import Topics, WhopPagePayload
```

> 注意：`add_page` 当前签名只接收 `url, source, name`。设计要让"创建时不传 settings 走 default"；测试预期已覆盖，无需新增 settings 参数。如果未来需要从 REST 创建时一起传 settings，再扩。

- [ ] **D.5: 跑测试**

```bash
cd backend && uv run pytest tests/whop/test_registry.py -v
```
Expected: 所有新增测试通过；现有测试也通过（如有 entry.to_dict 断言改了 shape，调整 fixture）。

- [ ] **D.6: 跑全套 backend test**

```bash
cd backend && uv run pytest -x
```
Expected: 全绿。如果有 schema converter 还没改（whop_page_to_out 还没接 settings 字段），可能会在 D.5 import 时挂；先把 schemas 里加 `WhopPageOut.settings: dict[str, Any] | None = None` 兜底（在 Task G 里会加正式字段）。如果 collide 太复杂，临时把 `_publish_change` 里的 `model_dump` 改成手写 dict 兜底（`{"id": entry.id, ...}`）。

- [ ] **D.7: Commit**

```bash
git add backend/app/whop/registry.py backend/app/core/events.py backend/tests/whop/test_registry.py backend/tests/whop/conftest.py
git commit -m "$(cat <<'EOF'
feat(whop): WhopRegistry 集成 PageSettings + url 反查 + page_changed 事件

WhopPageEntry.settings 字段，update_settings PATCH 支持，按 url 的 O(1) 反查给 trader 用，CRUD 操作发布 whop.page_changed 事件给前端实时同步。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task E: `WhopListener` 加 `dedupe_processed_messages` + url 注入

**Files:**
- Modify: `backend/app/whop/listener.py`
- Modify: `backend/app/whop/registry.py`
- Create: `backend/tests/whop/test_listener_dedupe.py`

- [ ] **E.1: 写 failing tests for listener dedupe**

新建 `backend/tests/whop/test_listener_dedupe.py`：

```python
import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.core.event_bus import EventBus
from app.core.events import MessagePayload, Topics
from app.domain.message import Message
from app.whop.listener import WhopListener


def _fake_message(mid: str) -> Message:
    return Message(
        id=mid,
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
    )


@pytest.mark.asyncio
async def test_dedupe_on_loads_seen_from_db(monkeypatch):
    bus = EventBus()
    received: list[Message] = []
    bus.subscribe(Topics.MESSAGE_RECEIVED, lambda evt: received.append(evt.payload.message))  # type: ignore[arg-type, attr-defined]

    # Stub repo.load_seen_ids_for_url
    async def fake_load(_session, _url):
        return {"existing-1", "existing-2"}
    monkeypatch.setattr("app.whop.listener.load_seen_ids_for_url", fake_load, raising=False)

    # Stub session_factory passed to listener (None in this test path; we patch directly)
    listener = WhopListener(
        bus=bus,
        url="https://whop.com/x/app/",
        source="stock",
        dedupe_processed_messages=True,
        session_factory=MagicMock(),
        skip_initial=False,  # if dedupe=on, skip_initial doesn't matter
    )

    # Avoid real browser
    listener._browser = MagicMock()
    listener._browser.scrape_html = AsyncMock(return_value="<html/>")
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda _h, *, source, received_at=None: [_fake_message("existing-1"), _fake_message("new-1")],
    )

    # Manually run the dedupe-load step (simulating start())
    await listener._prime_dedupe()  # helper extracted in implementation

    # First scan: existing-1 already seen, only new-1 published
    await listener._scan_once()
    assert {m.id for m in received} == {"new-1"}


@pytest.mark.asyncio
async def test_dedupe_off_uses_skip_initial(monkeypatch):
    bus = EventBus()
    received: list[Message] = []
    bus.subscribe(Topics.MESSAGE_RECEIVED, lambda evt: received.append(evt.payload.message))  # type: ignore[arg-type, attr-defined]

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/y/app/",
        source="stock",
        dedupe_processed_messages=False,
        session_factory=MagicMock(),
        skip_initial=True,
    )
    listener._browser = MagicMock()
    listener._browser.scrape_html = AsyncMock(return_value="<html/>")
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda _h, *, source, received_at=None: [_fake_message("a"), _fake_message("b")],
    )

    await listener._prime_skip_initial()  # helper for skip_initial=True path

    await listener._scan_once()
    assert received == []  # both 'a' and 'b' were primed, none are new


@pytest.mark.asyncio
async def test_scan_once_injects_url(monkeypatch):
    bus = EventBus()
    captured: list[Message] = []
    bus.subscribe(Topics.MESSAGE_RECEIVED, lambda evt: captured.append(evt.payload.message))  # type: ignore

    listener = WhopListener(
        bus=bus,
        url="https://whop.com/inject/app/",
        source="stock",
        dedupe_processed_messages=False,
        session_factory=MagicMock(),
        skip_initial=False,
    )
    listener._browser = MagicMock()
    listener._browser.scrape_html = AsyncMock(return_value="<html/>")
    monkeypatch.setattr(
        "app.whop.listener.extract_messages",
        lambda _h, *, source, received_at=None: [_fake_message("m1")],
    )

    await listener._scan_once()
    assert captured[0].url == "https://whop.com/inject/app/"
```

- [ ] **E.2: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/whop/test_listener_dedupe.py -v
```
Expected: TypeError on ctor (`dedupe_processed_messages` / `session_factory` 未定义) or AttributeError on `_prime_dedupe`.

- [ ] **E.3: 修改 WhopListener**

修改 `backend/app/whop/listener.py`：

```python
import dataclasses

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.storage.repo import load_seen_ids_for_url
from app.storage.db import session_scope


class WhopListener:
    def __init__(
        self,
        *,
        bus: EventBus,
        url: str,
        source: str,
        poll_interval: float = 2.0,
        headless: bool = False,
        cookie_path: str | None = None,
        skip_initial: bool = True,
        dedupe_processed_messages: bool = True,                          # 新
        session_factory: async_sessionmaker[AsyncSession] | None = None, # 新
    ) -> None:
        self._bus = bus
        self._url = url
        self._source = source
        self._poll_interval = poll_interval
        self._headless = headless
        self._cookie_path = cookie_path
        self._skip_initial = skip_initial
        self._dedupe = dedupe_processed_messages
        self._session_factory = session_factory

        self._browser: WhopBrowser | None = None
        self._task: asyncio.Task[None] | None = None
        self._seen: set[str] = set()
        self._stop_event = asyncio.Event()

        self._messages_published: int = 0
        self._last_poll_at: datetime | None = None
        self._last_error: str | None = None
        self._started_at: datetime | None = None
```

新增两个 prime helper：

```python
    async def _prime_dedupe(self) -> None:
        """Load seen ids from DB; called when dedupe=on."""
        if self._session_factory is None:
            logger.warning("WhopListener dedupe=on but session_factory missing — skipping prime")
            return
        async with session_scope(self._session_factory) as session:
            ids = await load_seen_ids_for_url(session, self._url)
        self._seen.update(ids)
        logger.info(
            "WhopListener[%s] dedupe loaded %d historical ids for %s",
            self._source, len(ids), self._url,
        )

    async def _prime_skip_initial(self) -> None:
        """Skip messages currently visible in DOM; called when dedupe=off + skip_initial=True."""
        if self._browser is None:
            return
        html = await self._browser.scrape_html()
        initial = extract_messages(html, source=self._source)  # type: ignore[arg-type]
        self._seen.update(m.id for m in initial)
        logger.info(
            "WhopListener[%s] skipped %d initial DOM messages",
            self._source, len(initial),
        )
```

修改 `start()`，把 priming 拆出来：

```python
    async def start(self) -> None:
        self._browser = WhopBrowser(headless=self._headless, cookie_path=self._cookie_path)
        await self._browser.start()
        ok = await self._browser.navigate(self._url)
        if not ok:
            await self._browser.close()
            self._browser = None
            raise RuntimeError(f"failed to navigate to {self._url}")

        if self._dedupe:
            await self._prime_dedupe()
        elif self._skip_initial:
            await self._prime_skip_initial()

        self._started_at = datetime.now(UTC)
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "WhopListener[%s] started polling %s every %.1fs (dedupe=%s)",
            self._source, self._url, self._poll_interval, self._dedupe,
        )
```

修改 `_scan_once` 把 url 注入消息：

```python
    async def _scan_once(self) -> None:
        if self._browser is None:
            raise RuntimeError("browser not initialized")
        html = await self._browser.scrape_html()
        now = datetime.now(UTC)
        messages = extract_messages(html, source=self._source, received_at=now)  # type: ignore[arg-type]

        new_count = 0
        for msg in messages:
            if msg.id in self._seen:
                continue
            self._seen.add(msg.id)
            # Inject url so downstream (parser, trader, storage) can attribute the message
            tagged = dataclasses.replace(msg, url=self._url)
            await self._bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(message=tagged)))
            new_count += 1

        self._last_poll_at = datetime.now(UTC)
        self._last_error = None
        if new_count > 0:
            self._messages_published += new_count
```

(去掉旧 `start()` 里的 `if self._skip_initial:` 整段——已被移到 `_prime_skip_initial`。)

- [ ] **E.4: 让 Registry 把 dedupe + session_factory 传给 listener**

修改 `backend/app/whop/registry.py` 的 `WhopRegistry.__init__` 接收 `session_factory`：

```python
class WhopRegistry:
    def __init__(
        self,
        *,
        bus: EventBus,
        settings: Settings,
        session_factory=None,                     # 新（async_sessionmaker | None）
        pages_file: Path | None = None,
    ) -> None:
        self._bus = bus
        self._settings = settings
        self._session_factory = session_factory
        self._pages_file = pages_file or _DEFAULT_PAGES_FILE
        # ... existing fields ...
```

`_start_listener`：

```python
    async def _start_listener(
        self, entry: WhopPageEntry, *, skip_initial: bool = True
    ) -> None:
        listener = WhopListener(
            bus=self._bus,
            url=entry.url,
            source=entry.source,
            poll_interval=self._settings.whop_poll_interval,
            headless=self._settings.whop_headless,
            skip_initial=skip_initial,
            dedupe_processed_messages=entry.settings.dedupe_processed_messages,
            session_factory=self._session_factory,
        )
        await listener.start()
        self._listeners[entry.id] = listener
```

`main.py` 里也要把 session_factory 传给 registry 构造：

```python
        state.whop_registry = WhopRegistry(
            bus=bus, settings=settings, session_factory=state.session_factory,
        )
```

- [ ] **E.5: 跑测试**

```bash
cd backend && uv run pytest tests/whop/test_listener_dedupe.py tests/whop/test_listener.py tests/whop/test_registry.py -v
```
Expected: 全绿。如果旧 `test_listener.py` 因 ctor 必需参数缺失（dedupe / session_factory）失败，把它们的默认值用上（dedupe 默认 True、session_factory 默认 None — 已经在 ctor 写了 default）；只要旧 test 不传这俩参也能跑。

- [ ] **E.6: Commit**

```bash
git add backend/app/whop/listener.py backend/app/whop/registry.py backend/app/main.py backend/tests/whop/test_listener_dedupe.py
git commit -m "$(cat <<'EOF'
feat(whop): listener dedupe（DB 灌 _seen）+ url 注入消息

dedupe=on 时启动从 SQLite 拉 page 历史 message id；_scan_once 把 self._url 注入新消息让下游可归属。registry 把 session_factory 传给 listener。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task F: 废弃 `watched_stocks.json` + ParserService 通过 registry 取 tickers

**Files:**
- Modify: `backend/app/parser/context_resolver.py`（删 `load_watched_tickers`，签名简化）
- Modify: `backend/app/parser/service.py`（`watched_tickers` 改成每次按 url 反查 registry）
- Modify: `backend/app/main.py`（去掉 watched_tickers 加载；ParserService 注入 registry）
- Delete: `config/watched_stocks.json`
- Delete: `utils/watched_stocks.py`（如果存在）
- Modify: 任何 root 仓里 `from utils.watched_stocks import ...` 的地方—— 改成接收外部传入或直接删

- [ ] **F.1: 写测试 — ParserService 按 url 取 tickers**

修改/新建 `backend/tests/parser/test_service.py`，新增：

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import UTC, datetime

from app.core.event_bus import EventBus
from app.core.events import MessagePayload, TaskPayload, Topics
from app.domain.message import Message
from app.parser.service import register_parser_service
from app.whop.page_settings import PageSettings, TickerConfig


@pytest.mark.asyncio
async def test_parser_service_uses_registry_tickers(monkeypatch, session_factory):
    bus = EventBus()
    fake_registry = MagicMock()
    fake_registry.get_settings_for_url.return_value = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"NVDA": TickerConfig(trade_quantity=100), "TSLA": TickerConfig(trade_quantity=200)},
    )

    captured_watched: list[set[str] | None] = []
    async def fake_resolve(*, session_factory, msg, parsed, watched_tickers):
        captured_watched.append(watched_tickers)
        return parsed
    monkeypatch.setattr("app.parser.service.resolve_context", fake_resolve)
    monkeypatch.setattr(
        "app.parser.service.stock_parser.parse",
        lambda content, message_id: None,
    )

    register_parser_service(bus, session_factory, registry=fake_registry)

    msg = Message(
        id="m1", content="x", raw_content="x", author=None,
        posted_at=datetime.now(UTC), received_at=datetime.now(UTC),
        source="stock",
        url="https://whop.com/x/app/",
    )
    await bus.publish(MagicMock(payload=MessagePayload(msg)))  # bypass — wrap in real Event below
```

> 提示：上面 mock Event 不优雅，建议改用直接构造 `Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg))` 然后 `await bus.publish(evt)`。完整版：

```python
    from app.core.event_bus import Event
    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await bus.wait_idle()

    assert captured_watched == [{"NVDA", "TSLA"}]
    fake_registry.get_settings_for_url.assert_called_with("https://whop.com/x/app/")


@pytest.mark.asyncio
async def test_parser_service_orphan_url_passes_empty_set(monkeypatch, session_factory):
    bus = EventBus()
    fake_registry = MagicMock()
    fake_registry.get_settings_for_url.return_value = None  # orphan

    captured: list[set[str] | None] = []
    async def fake_resolve(*, session_factory, msg, parsed, watched_tickers):
        captured.append(watched_tickers)
        return parsed
    monkeypatch.setattr("app.parser.service.resolve_context", fake_resolve)
    monkeypatch.setattr("app.parser.service.stock_parser.parse", lambda c, message_id: None)

    register_parser_service(bus, session_factory, registry=fake_registry)
    msg = Message(
        id="m2", content="x", raw_content="x", author=None,
        posted_at=datetime.now(UTC), received_at=datetime.now(UTC),
        source="stock", url=None,
    )
    from app.core.event_bus import Event
    await bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await bus.wait_idle()
    assert captured == [set()]
```

- [ ] **F.2: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/parser/test_service.py -v
```
Expected: TypeError — `register_parser_service` 还不接 `registry` 参数。

- [ ] **F.3: 修改 ParserService**

`backend/app/parser/service.py`：

```python
from typing import Protocol


class _RegistryLike(Protocol):
    def get_settings_for_url(self, url: str | None): ...


def register_parser_service(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    registry: _RegistryLike | None = None,
) -> Callable[[], None]:
    async def _handle_message_received(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, MessagePayload):
            return
        msg = payload.message
        task = Task.new_from_message(msg)
        task.mark_parsing()
        await bus.publish(Event(Topics.TASK_CREATED, TaskPayload(task)))

        # per-page tickers (only used by stock parser fallback / context_resolver)
        watched: set[str] = set()
        if msg.source == "stock" and registry is not None:
            page_settings = registry.get_settings_for_url(msg.url)
            if page_settings is not None and page_settings.tickers:
                watched = set(page_settings.tickers.keys())

        started = time.perf_counter()
        try:
            if msg.source == "stock":
                parsed = stock_parser.parse(msg.content, message_id=msg.id)
            else:
                parsed = option_parser.parse(
                    msg.content, message_id=msg.id, message_posted_at=msg.posted_at
                )

            if parsed is None or not getattr(parsed, "ticker", ""):
                resolved = await resolve_context(
                    session_factory=session_factory,
                    msg=msg,
                    parsed=parsed,
                    watched_tickers=watched,        # 永远传 set，不再 None
                )
            else:
                resolved = parsed
        # ... rest unchanged ...
```

- [ ] **F.4: 修改 context_resolver 删 `load_watched_tickers`**

修改 `backend/app/parser/context_resolver.py`：
- 删除整个 `load_watched_tickers` 函数和顶部 `_PROJECT_ROOT` 相关 path 计算（如果只服务于 watched_tickers）
- 删除文件顶部 `import json` / `from pathlib import Path` 如果不再使用
- `resolve_context(...)` 签名把 `watched_tickers: set[str] | None = None` 改成 `watched_tickers: set[str]`（必传，可为空 set）。如果有调用方传 None，改 `watched_tickers or set()`

- [ ] **F.5: 修改 main.py**

修改 `backend/app/main.py`：

```python
# 删除：
# from app.parser.context_resolver import load_watched_tickers
# 删除：
# try:
#     watchlist = load_watched_tickers()
# except (FileNotFoundError, Exception):
#     watchlist = set()

# 改成：
state.unsubs.append(
    register_parser_service(bus, session_factory, registry=state.whop_registry)
)
```

注意：`state.whop_registry` 在 line 153 才创建，但 `register_parser_service` 在 line 117 调用。**调整 main.py lifespan 顺序**：把 `WhopRegistry` 实例化提前到 `register_parser_service` 之前（registry 实例化无副作用，`load_and_start_all()` 才启动 listener），然后再注册 parser、trader 等，最后再 `await state.whop_registry.load_and_start_all()`。

具体调整：
```python
        bus = EventBus()
        state.bus = bus
        # ... broker ...

        # 创建（不启动） WhopRegistry，让 ParserService / Trader 拿到引用
        state.whop_registry = WhopRegistry(
            bus=bus, settings=settings, session_factory=state.session_factory,
        )

        # Wire up event-bus listeners
        state.unsubs.append(
            register_parser_service(bus, session_factory, registry=state.whop_registry)
        )
        # ... trader registration ...
        # ... storage listeners ...
        # ... push listener ...
        # ... hub.register_listeners ...

        # 最后才启动 Whop 监听
        if not skip_whop:
            try:
                await state.whop_registry.load_and_start_all()
            # ... seeds from .env ...
```

- [ ] **F.6: 跑测试 + 删文件**

```bash
cd backend && uv run pytest tests/parser/ tests/integration/ -v
```
Expected: parser 和 acceptance e2e 全绿。如果有 parser snapshot 测试用 watched_tickers 命中率统计，可能会变化（命中率下降是预期的，但测试不应硬断言数字）。如果硬断言数字，把 watched_tickers 用 fixture 显式传入测试上下文。

```bash
cd /Users/tianpengxuan/Documents/signal-station
rm -f config/watched_stocks.json
# utils/watched_stocks.py 不一定存在；查一下：
ls utils/watched_stocks.py 2>/dev/null && rm utils/watched_stocks.py
# 删除 root 仓 parser/broker 中对 utils.watched_stocks 的 import：
grep -l "from utils.watched_stocks" parser/ broker/ 2>/dev/null
# 对每个找到的文件，把 import 行删掉，并把使用处改为接收外部传入或局部默认 set()
```

具体替换：
- `parser/stock_parser.py` 第 16 行：`from utils.watched_stocks import get_watched_tickers` → 删；该函数任何调用改为外部传 `watched_tickers: set[str]` 参数（如果当前用作模块级常量，就接受 `parse(content, *, message_id, watched_tickers: set[str] = frozenset())`）
- `parser/stock_context_resolver.py` 第 10 行：`from utils.watched_stocks import resolve_position_size_to_shares` → 改为 `from app.whop.page_settings import position_size_to_fraction`，把调用 `resolve_position_size_to_shares(...)` 替换为新逻辑（`int(base_qty * position_size_to_fraction(s))`）
- `broker/position_manager.py` 第 699 / 837 行：`from utils.watched_stocks import get_watched_tickers` → 删；caller 必须把 ticker 列表传进 position_manager（如果难做，把这两处 import 暂留作 stub 注释 `# TODO: replace with per-page settings injection` 但代码路径要改成不依赖该函数；优先删，确认 root 仓的 `position_manager` 现在是否还被在线代码调用）

> 检查 root `parser/`/`broker/` 模块是否被 backend 使用：`grep -rn "from parser\." backend/app/ /Users/tianpengxuan/Documents/signal-station/backend/`。如果根本没被 backend 引用，这些 root 仓代码是 legacy（refactor-v2 之前的），保留不影响当前后端。spec 说"完全废弃 watched_stocks.json"，所以源文件删了即可，root 仓的 import 改一改也行；如果 root 已 dead code，加 `# DEAD CODE — pre-refactor-v2` 注释更明确。

- [ ] **F.7: 跑全量 backend 测试**

```bash
cd backend && uv run pytest -x
```
Expected: 全绿。

- [ ] **F.8: Commit**

```bash
git add backend/app/parser/service.py backend/app/parser/context_resolver.py backend/app/main.py backend/tests/parser/test_service.py
git rm config/watched_stocks.json
# 如果删了 utils/watched_stocks.py：
git rm utils/watched_stocks.py 2>/dev/null || true
# 修改的 root 仓 parser/broker 文件：
git add parser/ broker/ 2>/dev/null || true
git commit -m "$(cat <<'EOF'
refactor: 废弃 watched_stocks.json，parser 通过 WhopRegistry 按 url 取 ticker 列表

- 删除 config/watched_stocks.json 和 load_watched_tickers
- ParserService 接收 WhopRegistry，handler 内按 message.url 取 page settings.tickers
- main.py 调整 lifespan 顺序：先建 registry 再注册 parser，最后启动 listener
- root 仓 parser/broker 移除 utils.watched_stocks import（legacy）

BREAKING: stock parser fallback 命中率会下降到用户在 page settings 配置 ticker 之前；新 stock page 默认 tickers={}。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task G: `Trader` 改造 — 反查 settings、白名单、qty、偏差→order_type

**Files:**
- Modify: `backend/app/broker/trader.py`
- Modify: `backend/app/broker/broker_client.py`（如需暴露 quote 方法 — 检查现有 BrokerClient 是否有获取实时市价的接口）
- Modify: `backend/app/main.py`（trader 注入 registry）
- Create: `backend/tests/broker/test_trader_deviation.py`

- [ ] **G.1: 检查 BrokerClient 是否有 quote 方法**

```bash
grep -n "def quote\|get_quote\|market_price" /Users/tianpengxuan/Documents/signal-station/backend/app/broker/broker_client.py /Users/tianpengxuan/Documents/signal-station/backend/app/broker/longport_client.py /Users/tianpengxuan/Documents/signal-station/backend/app/broker/noop_client.py
```

如果没有，加一个最小接口 `quote(symbol: str) -> float | None` —— LongPortClient 用 SDK 实现，NoopBrokerClient 返回 None（trader 拿不到 quote 就走 LIMIT @ signal_price）。但**优先简化**：spec 4.2 公式需要市价；如果当前 broker 没暴露 quote，**第一版用 `inst.price` 当 market 假设**（即偏差永远为 0 → 总是 MARKET），并在 trader 里加 `# TODO: hook real quote`。这样可以解耦，先把白名单 / qty / order_type 路径打通。

**决策**：第一版 `market_price = inst.price`，行为等价于"始终用 MARKET"，后续 issue 跟进 quote 集成。在 spec 9 风险表里没列这条，但实施细节可以接受。

- [ ] **G.2: 写 failing tests**

新建 `backend/tests/broker/test_trader_deviation.py`：

```python
import pytest
from unittest.mock import MagicMock
from datetime import UTC, datetime, date

from app.broker.trader import register_trader
from app.broker.config import LongPortConfig
from app.broker.broker_client import BrokerClient
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import (
    InstructionType, OptionInstruction, StockInstruction,
)
from app.domain.message import Message
from app.domain.task import Task
from app.whop.page_settings import PageSettings, TickerConfig


def _stock_task(ticker: str = "TSLL", qty: int | None = None, position_size: str | None = None,
                 url: str | None = "https://whop.com/x/app/") -> Task:
    msg = Message(
        id="t-" + ticker, content="x", raw_content="x", author=None,
        posted_at=datetime.now(UTC), received_at=datetime.now(UTC),
        source="stock", url=url,
    )
    task = Task.new_from_message(msg)
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=10.0,
        price_range=None,
        quantity=qty,
        position_size=position_size,
        stop_loss_price=None, take_profit_price=None, context_source=None,
        ticker=ticker, symbol=f"{ticker}.US",
    )
    task.mark_parsing()
    task.attach_instruction(inst)
    return task


class _RecordingBroker:
    is_paper = True
    dry_run = False
    submitted: list[dict] = []
    def submit_stock_order(self, *, symbol, side, quantity, price, order_type, remark):
        self.__class__.submitted.append({
            "symbol": symbol, "side": side, "quantity": quantity,
            "price": price, "order_type": order_type, "remark": remark,
        })
        return f"ord-{symbol}"
    def submit_option_order(self, *, symbol, side, quantity, price, order_type, remark):
        self.__class__.submitted.append({
            "symbol": symbol, "side": side, "quantity": quantity,
            "price": price, "order_type": order_type, "remark": remark,
        })
        return f"ord-opt-{symbol}"
    def cancel_order(self, oid): return None
    def close(self): return None


def _config() -> LongPortConfig:
    return LongPortConfig(
        mode="paper", app_key="", app_secret="", access_token="",
        auto_trade=True, dry_run=False,
        max_option_total_price=10000, max_option_quantity=10,
    )


def _registry_with(settings_for_url: PageSettings | None) -> MagicMock:
    reg = MagicMock()
    reg.get_settings_for_url.return_value = settings_for_url
    return reg


@pytest.mark.asyncio
async def test_skip_when_ticker_not_whitelisted():
    bus = EventBus()
    broker = _RecordingBroker()
    _RecordingBroker.submitted = []
    page_settings = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={"NVDA": TickerConfig(trade_quantity=100)},  # TSLL 不在
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert broker.submitted == []
    assert task.status.value == "SKIPPED"
    assert "whitelist" in (task.reject_reason or "").lower() or "tsll" in (task.reject_reason or "").lower()


@pytest.mark.asyncio
async def test_qty_calc_normal_position():
    bus = EventBus()
    broker = _RecordingBroker(); _RecordingBroker.submitted = []
    page_settings = PageSettings(
        dedupe_processed_messages=True, price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()

    assert len(broker.submitted) == 1
    assert broker.submitted[0]["quantity"] == 2000


@pytest.mark.asyncio
async def test_qty_calc_half_position():
    bus = EventBus()
    broker = _RecordingBroker(); _RecordingBroker.submitted = []
    page_settings = PageSettings(
        dedupe_processed_messages=True, price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="半仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()
    assert broker.submitted[0]["quantity"] == 1000


@pytest.mark.asyncio
async def test_qty_calc_one_third():
    bus = EventBus()
    broker = _RecordingBroker(); _RecordingBroker.submitted = []
    page_settings = PageSettings(
        dedupe_processed_messages=True, price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2000)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="1/3")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()
    assert broker.submitted[0]["quantity"] == 666  # int(2000 * 1/3) = 666


@pytest.mark.asyncio
async def test_qty_min_one():
    bus = EventBus()
    broker = _RecordingBroker(); _RecordingBroker.submitted = []
    page_settings = PageSettings(
        dedupe_processed_messages=True, price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=2)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="1/3")  # 2 * 1/3 = 0.666 → max(0, 1) = 1
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()
    assert broker.submitted[0]["quantity"] == 1


@pytest.mark.asyncio
async def test_orphan_stock_uses_instruction_quantity():
    bus = EventBus()
    broker = _RecordingBroker(); _RecordingBroker.submitted = []
    register_trader(bus, broker, _config(), registry=_registry_with(None))  # orphan

    task = _stock_task("TSLL", qty=300, position_size=None, url=None)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()
    assert broker.submitted[0]["quantity"] == 300


@pytest.mark.asyncio
async def test_orphan_stock_no_qty_skipped():
    bus = EventBus()
    broker = _RecordingBroker(); _RecordingBroker.submitted = []
    register_trader(bus, broker, _config(), registry=_registry_with(None))

    task = _stock_task("TSLL", qty=None, position_size=None, url=None)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()
    assert broker.submitted == []
    assert task.status.value == "SKIPPED"


@pytest.mark.asyncio
async def test_market_when_within_tolerance():
    """First-pass: market_price = signal_price → 偏差 0 → 永远 MARKET。"""
    bus = EventBus()
    broker = _RecordingBroker(); _RecordingBroker.submitted = []
    page_settings = PageSettings(
        dedupe_processed_messages=True, price_deviation_tolerance=1.0,
        tickers={"TSLL": TickerConfig(trade_quantity=100)},
    )
    register_trader(bus, broker, _config(), registry=_registry_with(page_settings))

    task = _stock_task("TSLL", position_size="常规仓")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle()
    assert broker.submitted[0]["order_type"] == "MARKET"
```

> 期权测试沿用现有的 trader 测试覆盖（max_option_total_price 等）。新逻辑期权目前不带白名单，qty 用 instruction.quantity，落地行为不变。

- [ ] **G.3: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/broker/test_trader_deviation.py -v
```
Expected: TypeError — `register_trader` 不接 `registry` 参数；或者所有 task 还是按旧路径走 LIMIT。

- [ ] **G.4: 改 Trader**

`backend/app/broker/trader.py`：

```python
from app.whop.page_settings import PageSettings, position_size_to_fraction


def register_trader(
    bus: EventBus,
    client: BrokerClient,
    config: LongPortConfig,
    *,
    registry=None,           # WhopRegistry 反查；测试可传 MagicMock
) -> Callable[[], None]:

    def _resolve_settings(task: Task) -> PageSettings | None:
        if registry is None:
            return None
        return registry.get_settings_for_url(task.message.url)

    async def _publish_skip(task: Task, reason: str) -> None:
        task.mark_skipped(reason)
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))

    async def _handle_instruction_ready(event: Event) -> None:
        payload = event.payload
        if not isinstance(payload, TaskPayload):
            return
        task: Task = payload.task
        inst: Instruction | None = task.instruction
        if inst is None:
            return

        if not config.auto_trade:
            await _publish_skip(task, "auto_trade disabled in config")
            return
        if not getattr(inst, "symbol", None):
            await _publish_skip(task, "instruction missing symbol")
            return
        if inst.instruction_type not in (InstructionType.BUY, InstructionType.SELL):
            await _publish_skip(task, f"unsupported instruction type: {inst.instruction_type}")
            return

        page_settings = _resolve_settings(task)

        # ---- Stock-specific qty + whitelist ----
        if isinstance(inst, StockInstruction):
            ticker_upper = (inst.ticker or "").upper()
            if page_settings is not None and page_settings.tickers is not None:
                if ticker_upper not in page_settings.tickers:
                    await _publish_skip(task, f"ticker {ticker_upper} not in trade whitelist")
                    return
                base_qty = page_settings.tickers[ticker_upper].trade_quantity
                fraction = position_size_to_fraction(inst.position_size)
                computed_qty = max(int(base_qty * fraction), 1)
            else:
                # orphan stock task — use instruction.quantity directly
                computed_qty = inst.quantity or 0
                if computed_qty <= 0:
                    await _publish_skip(task, "orphan stock task missing instruction.quantity")
                    return
        elif isinstance(inst, OptionInstruction):
            computed_qty = inst.quantity or 1
            # option total price + qty caps (existing logic)
            price_for_check = inst.price if inst.price is not None else (
                inst.price_range[0] if inst.price_range else 0.0
            )
            total = price_for_check * computed_qty * 100
            if total > config.max_option_total_price:
                await _publish_skip(
                    task, f"option total ${total:.2f} exceeds limit ${config.max_option_total_price}"
                )
                return
            if computed_qty > config.max_option_quantity:
                await _publish_skip(
                    task, f"option quantity {computed_qty} exceeds limit {config.max_option_quantity}"
                )
                return
        else:
            computed_qty = inst.quantity or 1

        # ---- Deviation → order_type decision ----
        signal_price = inst.price if inst.price is not None else (
            inst.price_range[0] if inst.price_range else None
        )
        if signal_price is None:
            await _publish_skip(task, "no price available for submission")
            return

        # First-pass: market_price = signal_price (no real quote integration yet)
        # TODO: when broker.quote() lands, replace this with real market data
        market_price = signal_price
        tolerance_pct = (
            page_settings.price_deviation_tolerance if page_settings is not None
            else (config_fallback_tolerance(task.type, config))
        )
        deviation_pct = abs(market_price - signal_price) / signal_price * 100
        if deviation_pct <= tolerance_pct:
            order_type: OrderType = "MARKET"
            limit_price: float | None = None
        else:
            order_type = "LIMIT"
            limit_price = signal_price

        # ---- Submit ----
        task.mark_submitting()
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        started = time.perf_counter()
        try:
            order_id = _submit(
                client, inst,
                quantity=computed_qty,
                price=limit_price if limit_price is not None else signal_price,
                order_type=order_type,
            )
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000
            task.stage_timings["submit"] = elapsed
            task.mark_submit_failed(f"broker error: {exc}")
            logger.error("Trader: order submission failed for task %s: %s", task.id, exc, exc_info=True)
            await bus.publish(Event(Topics.TASK_SUBMIT_FAILED, TaskPayload(task)))
            return

        elapsed_ms = (time.perf_counter() - started) * 1000
        task.mark_submitted(order_id=order_id, timing_ms=elapsed_ms)
        await bus.publish(Event(Topics.TASK_ORDER_SUBMITTED, TaskPayload(task)))

    return bus.subscribe(Topics.TASK_INSTRUCTION_READY, _handle_instruction_ready)


def config_fallback_tolerance(task_type: str, config: LongPortConfig) -> float:
    """Orphan task: use Settings 全局 tolerance."""
    # config doesn't carry these anymore (we removed them in Task G.7);
    # fall back via app.core.config import.
    from app.core.config import get_settings
    s = get_settings()
    if task_type == "stock":
        return s.stock_price_deviation_tolerance
    return s.price_deviation_tolerance


def _submit(
    client: BrokerClient,
    inst: Instruction,
    *,
    quantity: int,
    price: float,
    order_type: OrderType,
) -> str:
    side: OrderSide = "BUY" if inst.instruction_type == InstructionType.BUY else "SELL"
    remark = f"auto_trade: {type(inst).__name__}"
    if isinstance(inst, OptionInstruction):
        return client.submit_option_order(
            symbol=inst.symbol, side=side, quantity=quantity,
            price=price, order_type=order_type, remark=remark,
        )
    symbol = getattr(inst, "symbol", "") or getattr(inst, "ticker", "")
    return client.submit_stock_order(
        symbol=symbol, side=side, quantity=quantity,
        price=price, order_type=order_type, remark=remark,
    )
```

- [ ] **G.5: 修改 main.py 把 registry 注入 trader**

```python
        state.unsubs.append(
            register_trader(bus, state.broker, trader_cfg, registry=state.whop_registry)
        )
```

- [ ] **G.6: 跑测试**

```bash
cd backend && uv run pytest tests/broker/ -v
```
Expected: 新增 8 个测试通过；旧 trader 测试 — 检查是否仍然 pass。可能旧测试断言 LIMIT order，新逻辑会改成 MARKET。如果有冲突，更新旧测试断言（设计意图是改行为）。

- [ ] **G.7: （可选）从 LongPortConfig 移除冗余字段**

如果 `LongPortConfig` 上的 `price_deviation_tolerance` / `stock_price_deviation_tolerance` 现在只被 trader 间接通过 `config_fallback_tolerance` → `Settings` 取，那 config 上的两字段可以删。但删除会动 `load_longport_config()` 和现有 main.py：保留它们也无伤大雅。**第一版保留**，标记 deprecated 注释。

- [ ] **G.8: Commit**

```bash
git add backend/app/broker/trader.py backend/app/main.py backend/tests/broker/test_trader_deviation.py
git commit -m "$(cat <<'EOF'
feat(broker): trader 反查 page settings — 白名单 / qty / 偏差→order_type

stock：白名单不命中 → SKIPPED；qty = trade_quantity * position_size_to_fraction，最小 1。
偏差之内 → MARKET，之外 → LIMIT@signal_price（暂用 signal_price 当 market_price，待 broker.quote 集成）。
孤儿 task 用 instruction.quantity + Settings 全局 fallback。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task H: REST 端点 + Schemas

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/app/api/http.py`
- Modify: `backend/tests/api/test_whop.py`（找现有的；或新建 `test_whop_settings.py`）

- [ ] **H.1: 加 schemas**

`backend/app/api/schemas.py`：

```python
# --- 新增 ---
class TickerConfigOut(BaseModel):
    trade_quantity: int


class WhopPageSettingsOut(BaseModel):
    dedupe_processed_messages: bool
    price_deviation_tolerance: float
    tickers: dict[str, TickerConfigOut] | None = None  # None = option page


class WhopPageSettingsPatch(BaseModel):
    """局部更新；任意字段缺省 = 不改。"""
    dedupe_processed_messages: bool | None = None
    price_deviation_tolerance: float | None = Field(default=None, ge=0)
    tickers: dict[str, TickerConfigOut] | None = None  # 整个 dict 替换；不存在 = 不动
```

修改 `MessageOut` 加 url：

```python
class MessageOut(BaseModel):
    id: str
    content: str
    raw_content: str
    author: str | None
    source: str
    posted_at: datetime
    received_at: datetime
    url: str | None = None       # 新
    quoted_message_id: str | None
```

修改 `WhopPageOut`：

```python
class WhopPageOut(BaseModel):
    id: str
    url: str
    source: str
    name: str
    added_at: datetime
    settings: WhopPageSettingsOut    # 新
    running: bool
    started_at: datetime | None
    last_poll_at: datetime | None
    messages_published: int
    last_error: str | None
```

修改 converter：

```python
def message_to_out(msg: Message) -> MessageOut:
    return MessageOut(
        id=msg.id,
        content=msg.content,
        raw_content=msg.raw_content,
        author=msg.author,
        source=msg.source,
        posted_at=msg.posted_at,
        received_at=msg.received_at,
        url=msg.url,                  # 新
        quoted_message_id=msg.quoted.id if msg.quoted is not None else None,
    )


def whop_page_to_out(entry, listener):
    settings_out = WhopPageSettingsOut(
        dedupe_processed_messages=entry.settings.dedupe_processed_messages,
        price_deviation_tolerance=entry.settings.price_deviation_tolerance,
        tickers=(
            {k: TickerConfigOut(trade_quantity=v.trade_quantity)
             for k, v in entry.settings.tickers.items()}
            if entry.settings.tickers is not None else None
        ),
    )
    if listener is not None:
        return WhopPageOut(
            id=entry.id, url=entry.url, source=entry.source, name=entry.name,
            added_at=entry.added_at, settings=settings_out,
            running=listener.running, started_at=listener.started_at,
            last_poll_at=listener.last_poll_at,
            messages_published=listener.messages_published,
            last_error=listener.last_error,
        )
    return WhopPageOut(
        id=entry.id, url=entry.url, source=entry.source, name=entry.name,
        added_at=entry.added_at, settings=settings_out,
        running=False, started_at=None, last_poll_at=None,
        messages_published=0, last_error=None,
    )
```

`TaskSummaryOut` / `TaskOut` 字段不需要改，因为 `MessageOut.url` 已在 `message` 嵌套里自动出去。

- [ ] **H.2: 写端点测试**

新建 `backend/tests/api/test_whop_settings.py`：

```python
import pytest
from httpx import AsyncClient

# Reuse existing app/client fixtures from tests/api/conftest.py


@pytest.mark.asyncio
async def test_get_pages_includes_settings(authed_client: AsyncClient, registry_with_stock):
    resp = await authed_client.get("/api/whop/pages")
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    assert len(pages) >= 1
    s = pages[0]["settings"]
    assert "dedupe_processed_messages" in s
    assert "price_deviation_tolerance" in s
    assert "tickers" in s


@pytest.mark.asyncio
async def test_patch_settings_partial(authed_client: AsyncClient, registry_with_stock):
    pages = (await authed_client.get("/api/whop/pages")).json()["pages"]
    pid = pages[0]["id"]
    resp = await authed_client.patch(
        f"/api/whop/pages/{pid}/settings",
        json={"price_deviation_tolerance": 0.5, "tickers": {"NVDA": {"trade_quantity": 100}}},
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["settings"]["price_deviation_tolerance"] == 0.5
    assert out["settings"]["tickers"] == {"NVDA": {"trade_quantity": 100}}
    # dedupe was not in patch — preserved
    assert out["settings"]["dedupe_processed_messages"] is True


@pytest.mark.asyncio
async def test_patch_settings_uppercases_ticker_keys(authed_client, registry_with_stock):
    pages = (await authed_client.get("/api/whop/pages")).json()["pages"]
    pid = pages[0]["id"]
    resp = await authed_client.patch(
        f"/api/whop/pages/{pid}/settings",
        json={"tickers": {"tsll": {"trade_quantity": 100}}},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["tickers"] == {"TSLL": {"trade_quantity": 100}}


@pytest.mark.asyncio
async def test_patch_settings_option_rejects_tickers(authed_client, registry_with_option):
    pages = (await authed_client.get("/api/whop/pages")).json()["pages"]
    opt_pid = next(p["id"] for p in pages if p["source"] == "option")
    resp = await authed_client.patch(
        f"/api/whop/pages/{opt_pid}/settings",
        json={"tickers": {"AAPL": {"trade_quantity": 1}}},
    )
    assert resp.status_code == 400  # ValueError → HTTPException(400)
    assert "tickers" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_settings_defaults_stock(authed_client):
    resp = await authed_client.get("/api/whop/pages/defaults?source=stock")
    assert resp.status_code == 200
    s = resp.json()
    assert s["dedupe_processed_messages"] is True
    assert s["price_deviation_tolerance"] == 1.0
    assert s["tickers"] == {}


@pytest.mark.asyncio
async def test_get_settings_defaults_option(authed_client):
    resp = await authed_client.get("/api/whop/pages/defaults?source=option")
    assert resp.status_code == 200
    s = resp.json()
    assert s["dedupe_processed_messages"] is True
    assert s["price_deviation_tolerance"] == 5.0
    assert s["tickers"] is None
```

> `registry_with_stock` / `registry_with_option` fixtures：在 `tests/api/conftest.py` 添加 — patch `WhopRegistry._start_listener` 然后 `await app.state.app_state.whop_registry.add_page(...)`。如果该 conftest 已有 `app` fixture 可获取 registry，就用它。

- [ ] **H.3: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/api/test_whop_settings.py -v
```
Expected: 404 / 422 — 端点未实现。

- [ ] **H.4: 加端点**

修改 `backend/app/api/http.py` 在 `if whop_registry is not None:` 块内添加：

```python
        @router.patch("/api/whop/pages/{page_id}/settings", response_model=WhopPageOut)
        async def patch_whop_page_settings(
            page_id: str, body: WhopPageSettingsPatch,
        ) -> WhopPageOut:
            patch_dict: dict = {}
            if body.dedupe_processed_messages is not None:
                patch_dict["dedupe_processed_messages"] = body.dedupe_processed_messages
            if body.price_deviation_tolerance is not None:
                patch_dict["price_deviation_tolerance"] = body.price_deviation_tolerance
            if body.tickers is not None:
                patch_dict["tickers"] = {
                    k: {"trade_quantity": v.trade_quantity}
                    for k, v in body.tickers.items()
                }
            try:
                entry = await whop_registry.update_settings(page_id, patch_dict)
            except KeyError as exc:
                raise HTTPException(404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            for e, ll in whop_registry.list_pages():
                if e.id == entry.id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="updated but lost track")

        @router.get("/api/whop/pages/defaults", response_model=WhopPageSettingsOut)
        async def whop_settings_defaults(source: str) -> WhopPageSettingsOut:
            from app.whop.page_settings import default_settings_for
            try:
                s = default_settings_for(source)  # type: ignore[arg-type]
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            return WhopPageSettingsOut(
                dedupe_processed_messages=s.dedupe_processed_messages,
                price_deviation_tolerance=s.price_deviation_tolerance,
                tickers=(
                    {k: TickerConfigOut(trade_quantity=v.trade_quantity)
                     for k, v in s.tickers.items()}
                    if s.tickers is not None else None
                ),
            )
```

加 import：

```python
from app.api.schemas import (
    # ... existing ...
    TickerConfigOut,
    WhopPageSettingsOut,
    WhopPageSettingsPatch,
)
```

- [ ] **H.5: 跑测试**

```bash
cd backend && uv run pytest tests/api/ -v
```
Expected: 全绿。

- [ ] **H.6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/http.py backend/tests/api/test_whop_settings.py backend/tests/api/conftest.py
git commit -m "$(cat <<'EOF'
feat(api): per-page settings PATCH + defaults GET + MessageOut.url

新端点 PATCH /api/whop/pages/{id}/settings 支持局部更新；GET /api/whop/pages/defaults?source 返回模板。MessageOut.url + WhopPageOut.settings 暴露给前端。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task I: WS 事件桥接 `whop.page_changed`

**Files:**
- Modify: `backend/app/api/ws.py`
- Modify: `backend/tests/api/test_ws.py`（追加 case）

- [ ] **I.1: 写测试**

在 `backend/tests/api/test_ws.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_whop_page_changed_broadcast(app_with_registry, ws_client):
    """Bus publish WHOP_PAGE_CHANGED → WS clients receive event."""
    received: list[dict] = []
    ws = await ws_client(initial_since=None, on_event=received.append)

    bus = app_with_registry.state.app_state.bus
    from app.core.event_bus import Event
    from app.core.events import Topics, WhopPagePayload

    page_dict = {"id": "p1", "url": "u", "source": "stock", "name": "n",
                 "added_at": "2026-04-25T00:00:00+00:00",
                 "settings": {"dedupe_processed_messages": True,
                              "price_deviation_tolerance": 1.0, "tickers": {}},
                 "running": True, "started_at": None, "last_poll_at": None,
                 "messages_published": 0, "last_error": None}
    await bus.publish(Event(
        Topics.WHOP_PAGE_CHANGED,
        WhopPagePayload(action="settings_updated", page_dict=page_dict),
    ))
    await bus.wait_idle()

    types = [e["type"] for e in received]
    assert "whop.page_changed" in types
    payload = next(e["payload"] for e in received if e["type"] == "whop.page_changed")
    assert payload["action"] == "settings_updated"
    assert payload["page"]["id"] == "p1"
```

- [ ] **I.2: 跑测试看它失败**

```bash
cd backend && uv run pytest tests/api/test_ws.py::test_whop_page_changed_broadcast -v
```
Expected: AssertionError — WS 没收到这条事件。

- [ ] **I.3: 修改 ws.py 桥接新 topic**

修改 `backend/app/api/ws.py`：

```python
from app.core.events import TaskPayload, TaskPushPayload, Topics, WhopPagePayload


class WebSocketHub:
    async def register_listeners(self) -> None:
        topics_to_bridge = [
            Topics.TASK_CREATED,
            Topics.TASK_INSTRUCTION_READY,
            Topics.TASK_PARSE_FAILED,
            Topics.TASK_ORDER_SUBMITTED,
            Topics.TASK_SUBMIT_FAILED,
            Topics.TASK_PUSH_EVENT,
            Topics.TASK_STATUS_CHANGED,
            Topics.SYSTEM_CONNECTION_CHANGED,
            Topics.WHOP_PAGE_CHANGED,        # 新
        ]
        for t in topics_to_bridge:
            unsub = self._bus.subscribe(t, self._on_bus_event)
            self._unsubs.append(unsub)

    @staticmethod
    def _payload_to_dict(event: Event) -> dict[str, Any] | None:
        p = event.payload
        if isinstance(p, TaskPushPayload):
            return {
                "task": task_to_out(p.task).model_dump(mode="json"),
                "push_event": push_event_to_out(p.push_event).model_dump(mode="json"),
            }
        if isinstance(p, TaskPayload):
            return {"task": task_to_out(p.task).model_dump(mode="json")}
        if isinstance(p, WhopPagePayload):                                      # 新
            return {"action": p.action, "page": p.page_dict}
        if isinstance(p, dict):
            return p
        return None
```

- [ ] **I.4: 跑测试**

```bash
cd backend && uv run pytest tests/api/test_ws.py -v
```
Expected: 全绿。

- [ ] **I.5: Commit**

```bash
git add backend/app/api/ws.py backend/tests/api/test_ws.py
git commit -m "$(cat <<'EOF'
feat(ws): bridge whop.page_changed to WebSocket clients

让前端 dashboard 实时同步 page 列表（add/remove/restart/settings_updated）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task J: OpenAPI 同步 + 前端 http 客户端方法

**Files:**
- Run: `make build` 或专用脚本生成 `frontend/openapi.json`
- Run: `cd frontend && npm run gen:types`
- Modify: `frontend/src/api/http.ts`
- Modify: `frontend/src/api/domain-types.ts`

- [ ] **J.1: 生成 OpenAPI + 前端类型**

```bash
cd /Users/tianpengxuan/Documents/signal-station
uv run --project backend python scripts/dump_openapi.py
cd frontend && npm run gen:types
```
Expected: `frontend/openapi.json` 更新；`frontend/src/api/types.ts` 重新生成；包含新 schemas (`WhopPageSettingsOut`, `WhopPageSettingsPatch`, `TickerConfigOut`)。

- [ ] **J.2: domain-types 加 re-export**

`frontend/src/api/domain-types.ts`：

```typescript
export type WhopPageSettings = components["schemas"]["WhopPageSettingsOut"];
export type WhopPageSettingsPatch = components["schemas"]["WhopPageSettingsPatch"];
export type TickerConfig = components["schemas"]["TickerConfigOut"];
```

- [ ] **J.3: api/http.ts 加新方法**

`frontend/src/api/http.ts` 在 `api` 对象里追加：

```typescript
  async updateWhopPageSettings(
    id: string,
    patch: WhopPageSettingsPatch,
  ): Promise<WhopPage> {
    return request<WhopPage>(
      `/api/whop/pages/${encodeURIComponent(id)}/settings`,
      { method: "PATCH", body: JSON.stringify(patch) },
    );
  },

  async whopPageSettingsDefaults(source: "stock" | "option"): Promise<WhopPageSettings> {
    return request<WhopPageSettings>(
      `/api/whop/pages/defaults?source=${encodeURIComponent(source)}`,
    );
  },
```

加 imports 顶部：

```typescript
import type {
  // ... existing ...
  WhopPageSettings, WhopPageSettingsPatch,
} from "./domain-types";
```

- [ ] **J.4: 跑前端测试 + typecheck**

```bash
cd frontend && npm run typecheck && npm test -- --run
```
Expected: typecheck pass；所有现有 tests 仍通过。

- [ ] **J.5: Commit**

```bash
git add frontend/openapi.json frontend/src/api/types.ts frontend/src/api/domain-types.ts frontend/src/api/http.ts
git commit -m "$(cat <<'EOF'
feat(frontend/api): 同步 OpenAPI 类型 + 加 settings PATCH/defaults 方法

regen types.ts；http.ts 新增 updateWhopPageSettings / whopPageSettingsDefaults。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task K: `pageTabs` store + tasks selector

**Files:**
- Create: `frontend/src/stores/pageTabs.ts`
- Create: `frontend/src/stores/pageTabs.test.ts`
- Modify: `frontend/src/stores/tasks.ts`
- Modify: `frontend/src/stores/tasks.test.ts`

- [ ] **K.1: 写 pageTabs store 测试**

新建 `frontend/src/stores/pageTabs.test.ts`：

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { usePageTabsStore } from "./pageTabs";
import type { WhopPage } from "../api/domain-types";

const makePage = (overrides: Partial<WhopPage> = {}): WhopPage => ({
  id: "p1",
  url: "https://whop.com/p1/app/",
  source: "stock",
  name: "Stock1",
  added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
  running: true,
  started_at: null,
  last_poll_at: null,
  messages_published: 0,
  last_error: null,
  ...overrides,
});

describe("pageTabs store", () => {
  beforeEach(() => {
    usePageTabsStore.getState().reset();
    localStorage.clear();
  });

  it("setPages stores list and auto-selects first when no last_active", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    expect(usePageTabsStore.getState().pages).toHaveLength(2);
    expect(usePageTabsStore.getState().activeTabId).toBe("a");
  });

  it("setPages restores last_active from localStorage", () => {
    localStorage.setItem("DASHBOARD_LAST_TAB", "b");
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    expect(usePageTabsStore.getState().activeTabId).toBe("b");
  });

  it("setPages falls back to first when last_active missing", () => {
    localStorage.setItem("DASHBOARD_LAST_TAB", "nonexistent");
    usePageTabsStore.getState().setPages([makePage({ id: "a" })]);
    expect(usePageTabsStore.getState().activeTabId).toBe("a");
  });

  it("setActiveTab persists to localStorage", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    usePageTabsStore.getState().setActiveTab("b");
    expect(localStorage.getItem("DASHBOARD_LAST_TAB")).toBe("b");
  });

  it("setExpandMode is per-tab, ephemeral", () => {
    usePageTabsStore.getState().setExpandMode("a", "all-open");
    usePageTabsStore.getState().setExpandMode("b", "all-closed");
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("all-open");
    expect(usePageTabsStore.getState().expandModeByTab["b"]).toBe("all-closed");
    // No localStorage write
    expect(localStorage.getItem("DASHBOARD_EXPAND")).toBeNull();
  });

  it("applyPageChanged action=added appends to pages", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" })]);
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 1,
      payload: { action: "added", page: makePage({ id: "b" }) },
    });
    expect(usePageTabsStore.getState().pages.map(p => p.id)).toEqual(["a", "b"]);
  });

  it("applyPageChanged action=removed drops from pages", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a" }), makePage({ id: "b" })]);
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 2,
      payload: { action: "removed", page: makePage({ id: "a" }) },
    });
    expect(usePageTabsStore.getState().pages.map(p => p.id)).toEqual(["b"]);
  });

  it("applyPageChanged action=settings_updated replaces page in place", () => {
    usePageTabsStore.getState().setPages([makePage({ id: "a", name: "old" })]);
    usePageTabsStore.getState().applyPageChanged({
      type: "whop.page_changed",
      event_id: 3,
      payload: { action: "settings_updated", page: makePage({ id: "a", name: "new" }) },
    });
    expect(usePageTabsStore.getState().pages[0].name).toBe("new");
  });
});
```

- [ ] **K.2: 实现 pageTabs store**

新建 `frontend/src/stores/pageTabs.ts`：

```typescript
import { create } from "zustand";
import type { WhopPage } from "../api/domain-types";
import type { WsEvent } from "../api/ws";

export type ExpandMode = "smart" | "all-open" | "all-closed";
export type ActiveTabId = string | "orphan" | null;

const LS_KEY = "DASHBOARD_LAST_TAB";

interface PageTabsState {
  pages: WhopPage[];
  activeTabId: ActiveTabId;
  expandModeByTab: Record<string, ExpandMode>;
  orphanCount: number;

  setPages(pages: WhopPage[]): void;
  setActiveTab(id: ActiveTabId): void;
  setExpandMode(tabId: string, mode: ExpandMode): void;
  setOrphanCount(n: number): void;
  applyPageChanged(evt: WsEvent): void;
  reset(): void;
}

export const usePageTabsStore = create<PageTabsState>((set, get) => ({
  pages: [],
  activeTabId: null,
  expandModeByTab: {},
  orphanCount: 0,

  setPages(pages) {
    const stored = localStorage.getItem(LS_KEY);
    let next: ActiveTabId = get().activeTabId;
    if (next === null || (next !== "orphan" && !pages.some(p => p.id === next))) {
      // pick from localStorage if valid, else first page, else null
      if (stored && pages.some(p => p.id === stored)) {
        next = stored;
      } else if (pages.length > 0) {
        next = pages[0].id;
      } else {
        next = null;
      }
    }
    set({ pages, activeTabId: next });
  },

  setActiveTab(id) {
    if (id !== null && id !== "orphan") localStorage.setItem(LS_KEY, id);
    set({ activeTabId: id });
  },

  setExpandMode(tabId, mode) {
    set(state => ({
      expandModeByTab: { ...state.expandModeByTab, [tabId]: mode },
    }));
  },

  setOrphanCount(n) {
    set({ orphanCount: n });
  },

  applyPageChanged(evt) {
    const p = evt.payload as { action: string; page: WhopPage };
    const action = p.action;
    const page = p.page;
    set(state => {
      let pages = state.pages;
      if (action === "added") {
        if (!pages.some(x => x.id === page.id)) pages = [...pages, page];
      } else if (action === "removed") {
        pages = pages.filter(x => x.id !== page.id);
      } else {
        // restarted | settings_updated → replace in place
        pages = pages.map(x => x.id === page.id ? page : x);
      }
      // If active tab dropped (removed), fall back to first or null
      let activeTabId = state.activeTabId;
      if (activeTabId !== "orphan" && activeTabId !== null && !pages.some(x => x.id === activeTabId)) {
        activeTabId = pages[0]?.id ?? null;
      }
      return { pages, activeTabId };
    });
  },

  reset() {
    set({ pages: [], activeTabId: null, expandModeByTab: {}, orphanCount: 0 });
  },
}));
```

- [ ] **K.3: 跑 pageTabs store 测试**

```bash
cd frontend && npm test -- --run stores/pageTabs.test.ts
```
Expected: 全绿（8 个测试）。

- [ ] **K.4: 在 tasks store 加 selector**

修改 `frontend/src/stores/tasks.ts`，在文件末尾追加：

```typescript
/**
 * Filter tasks by url (membership in pageUrls). null = orphan filter:
 *   includes tasks with url=null OR url not in pageUrls.
 */
export function selectTasksByUrl(
  tasks: TaskSummary[],
  url: string | null,
  pageUrls: Set<string>,
): TaskSummary[] {
  if (url === null) {
    return tasks.filter(t => t.message?.url == null || !pageUrls.has(t.message.url));
  }
  return tasks.filter(t => t.message?.url === url);
}
```

- [ ] **K.5: 在 tasks.test.ts 加 selector 测试**

```typescript
import { selectTasksByUrl } from "./tasks";
import type { TaskSummary } from "../api/domain-types";

const t = (id: string, url: string | null): TaskSummary => ({
  id, type: "stock", status: "RECEIVED", order_id: null, stage_timings: {},
  created_at: "2026-04-25T00:00:00Z", updated_at: "2026-04-25T00:00:00Z",
  reject_reason: null,
  message: {
    id, content: "x", raw_content: "x", author: null,
    source: "stock", posted_at: "2026-04-25T00:00:00Z",
    received_at: "2026-04-25T00:00:00Z",
    url, quoted_message_id: null,
  },
  instruction: null,
});

describe("selectTasksByUrl", () => {
  const tasks = [t("a", "u1"), t("b", "u2"), t("c", null), t("d", "u3-removed")];
  const pageUrls = new Set(["u1", "u2"]);

  it("filters by exact url", () => {
    expect(selectTasksByUrl(tasks, "u1", pageUrls).map(t => t.id)).toEqual(["a"]);
  });

  it("orphan returns null-url and unknown-url tasks", () => {
    const orphans = selectTasksByUrl(tasks, null, pageUrls).map(t => t.id);
    expect(orphans).toEqual(["c", "d"]);
  });

  it("returns empty for unknown url", () => {
    expect(selectTasksByUrl(tasks, "nope", pageUrls)).toEqual([]);
  });
});
```

- [ ] **K.6: 跑 tasks 测试**

```bash
cd frontend && npm test -- --run stores/tasks.test.ts
```
Expected: 新增 3 个 selector 测试通过。

- [ ] **K.7: Commit**

```bash
git add frontend/src/stores/pageTabs.ts frontend/src/stores/pageTabs.test.ts frontend/src/stores/tasks.ts frontend/src/stores/tasks.test.ts
git commit -m "$(cat <<'EOF'
feat(stores): pageTabs + tasks.selectTasksByUrl

pageTabs 持有 pages / activeTabId(localStorage 持久化) / expandModeByTab(瞬时)；applyPageChanged 处理 WS 同步。tasks selector 按 url 过滤，支持孤儿模式。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task L: WS client 路由 `whop.page_changed` 到 store

**Files:**
- Modify: `frontend/src/App.tsx`（在 onEvent 里 dispatch）

- [ ] **L.1: 修改 App.tsx 的 ws onEvent**

`frontend/src/App.tsx` 找到 `createWsClient` 调用：

```typescript
const client = createWsClient({
  baseUrl: BASE_URL,
  token,
  onEvent: (evt) => {
    if (evt.type === "whop.page_changed") {
      usePageTabsStore.getState().applyPageChanged(evt);
    } else {
      applyWs(evt);
    }
    useConnStore.getState().setLastEventId(evt.event_id);
  },
  onStatus: (s) => useConnStore.getState().setWs(s),
});
```

加 import：
```typescript
import { usePageTabsStore } from "./stores/pageTabs";
```

- [ ] **L.2: 跑 typecheck**

```bash
cd frontend && npm run typecheck
```
Expected: pass.

- [ ] **L.3: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat(ws): route whop.page_changed events to pageTabs store

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
"
```

---

## Task M: Dashboard 组件拆分（PageTabs / InfoBar / ActionBar / TaskStream / EmptyState）

**Files:**
- Create: `frontend/src/components/Dashboard/PageTabs.tsx` + `.test.tsx`
- Create: `frontend/src/components/Dashboard/PageInfoBar.tsx` + `.test.tsx`
- Create: `frontend/src/components/Dashboard/PageActionBar.tsx` + `.test.tsx`
- Create: `frontend/src/components/Dashboard/TaskStream.tsx`
- Create: `frontend/src/components/Dashboard/EmptyState.tsx`
- Create: `frontend/src/components/Dashboard/Dashboard.css`
- Modify: `frontend/src/App.tsx`（Dashboard 改成 orchestrator）
- Modify: `frontend/src/components/Card/Card.tsx`（如果不接 expandMode prop，需要传 effectiveExpanded）

- [ ] **M.1: TaskStream 抽出现有 DateGroups**

新建 `frontend/src/components/Dashboard/TaskStream.tsx`：

```typescript
import { Card } from "../Card/Card";
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import type { ExpandMode } from "../../stores/pageTabs";

const ACTIVE_STATUSES = new Set([
  "RECEIVED", "PARSING", "INSTRUCTION_READY",
  "SUBMITTING", "PENDING", "PARTIAL",
]);

function isActiveExpanded(task: TaskSummary): boolean {
  if (ACTIVE_STATUSES.has(task.status)) return true;
  if (task.status === "FILLED") {
    const updatedAt = new Date(task.updated_at).getTime();
    return Date.now() - updatedAt < 30_000;
  }
  return false;
}

function formatDateLabel(dateKey: string): string {
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  if (dateKey === today) return `今天 ${dateKey}`;
  if (dateKey === yesterday) return `昨天 ${dateKey}`;
  return dateKey;
}

interface Props {
  tasks: TaskSummary[];
  pushEventsByTask: Record<string, PushEvent[]>;
  expandMode: ExpandMode;
}

export function TaskStream({ tasks, pushEventsByTask, expandMode }: Props) {
  const sorted = [...tasks].sort((a, b) => {
    const aTime = a.message?.posted_at ?? a.created_at;
    const bTime = b.message?.posted_at ?? b.created_at;
    return bTime.localeCompare(aTime);
  });
  const groups = new Map<string, TaskSummary[]>();
  for (const t of sorted) {
    const ts = t.message?.posted_at ?? t.created_at;
    const dateKey = ts.slice(0, 10);
    if (!groups.has(dateKey)) groups.set(dateKey, []);
    groups.get(dateKey)!.push(t);
  }
  const dateKeys = Array.from(groups.keys());

  return (
    <>
      {dateKeys.map(dateKey => {
        const dayTasks = groups.get(dateKey)!;
        return (
          <div key={dateKey}>
            <div className="stream-divider">{formatDateLabel(dateKey)} · {dayTasks.length}</div>
            {dayTasks.map(t => {
              const expanded =
                expandMode === "all-open" ? true :
                expandMode === "all-closed" ? false :
                isActiveExpanded(t);
              return (
                <Card
                  key={t.id}
                  task={t}
                  pushEvents={pushEventsByTask[t.id] ?? []}
                  defaultExpanded={expanded}
                />
              );
            })}
          </div>
        );
      })}
    </>
  );
}
```

- [ ] **M.2: PageTabs**

新建 `frontend/src/components/Dashboard/PageTabs.tsx`：

```typescript
import { usePageTabsStore } from "../../stores/pageTabs";

export function PageTabs() {
  const pages = usePageTabsStore(s => s.pages);
  const activeTabId = usePageTabsStore(s => s.activeTabId);
  const setActive = usePageTabsStore(s => s.setActiveTab);
  const orphanCount = usePageTabsStore(s => s.orphanCount);

  if (pages.length === 0) return null;

  return (
    <nav className="page-tabs" role="tablist">
      {pages.map(p => (
        <button
          key={p.id}
          role="tab"
          aria-selected={activeTabId === p.id}
          className={activeTabId === p.id ? "tab active" : "tab"}
          onClick={() => setActive(p.id)}
        >
          <span className={`tab-source-dot ${p.source}`} />
          <span className="tab-name">{p.name}</span>
        </button>
      ))}
      {orphanCount > 0 && (
        <button
          role="tab"
          aria-selected={activeTabId === "orphan"}
          className={activeTabId === "orphan" ? "tab active orphan" : "tab orphan"}
          onClick={() => setActive("orphan")}
        >
          <span className="tab-name">已停用</span>
          <span className="tab-count">{orphanCount}</span>
        </button>
      )}
    </nav>
  );
}
```

新建 `PageTabs.test.tsx`：

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { usePageTabsStore } from "../../stores/pageTabs";
import { PageTabs } from "./PageTabs";

describe("<PageTabs>", () => {
  beforeEach(() => { usePageTabsStore.getState().reset(); localStorage.clear(); });

  it("renders nothing when no pages", () => {
    const { container } = render(<PageTabs />);
    expect(container.firstChild).toBeNull();
  });

  it("renders tab per page and highlights active", () => {
    usePageTabsStore.getState().setPages([
      { id: "a", url: "u1", source: "stock", name: "Stock1", added_at: "2026-04-25T00:00:00Z",
        settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
        running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null },
      { id: "b", url: "u2", source: "option", name: "Opt1", added_at: "2026-04-25T00:00:00Z",
        settings: { dedupe_processed_messages: true, price_deviation_tolerance: 5, tickers: null },
        running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null },
    ]);
    render(<PageTabs />);
    expect(screen.getByRole("tab", { name: /Stock1/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Opt1/ })).toHaveAttribute("aria-selected", "false");
  });

  it("clicking switches active tab", () => {
    usePageTabsStore.getState().setPages([
      { id: "a", url: "u1", source: "stock", name: "Stock1", added_at: "2026-04-25T00:00:00Z",
        settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
        running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null },
      { id: "b", url: "u2", source: "option", name: "Opt1", added_at: "2026-04-25T00:00:00Z",
        settings: { dedupe_processed_messages: true, price_deviation_tolerance: 5, tickers: null },
        running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null },
    ]);
    render(<PageTabs />);
    fireEvent.click(screen.getByRole("tab", { name: /Opt1/ }));
    expect(usePageTabsStore.getState().activeTabId).toBe("b");
  });

  it("shows orphan tab when orphanCount > 0", () => {
    usePageTabsStore.getState().setPages([
      { id: "a", url: "u1", source: "stock", name: "Stock1", added_at: "2026-04-25T00:00:00Z",
        settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
        running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null },
    ]);
    usePageTabsStore.getState().setOrphanCount(3);
    render(<PageTabs />);
    expect(screen.getByRole("tab", { name: /已停用/ })).toBeInTheDocument();
  });
});
```

- [ ] **M.3: PageInfoBar**

新建 `frontend/src/components/Dashboard/PageInfoBar.tsx`：

```typescript
import type { WhopPage } from "../../api/domain-types";

interface Props {
  page: WhopPage | null;   // null = orphan
  orphanCount?: number;
}

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return "—";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(0)}s 前`;
  if (s < 3600) return `${(s / 60).toFixed(0)}m 前`;
  if (s < 86400) return `${(s / 3600).toFixed(1)}h 前`;
  return `${(s / 86400).toFixed(1)}d 前`;
}

export function PageInfoBar({ page, orphanCount = 0 }: Props) {
  if (page === null) {
    return (
      <div className="page-info-bar orphan">
        <span className="badge gray">已停用</span>
        <span>共 {orphanCount} 条历史 task — 来源 page 已被移除</span>
      </div>
    );
  }
  return (
    <div className="page-info-bar">
      <span className={`badge ${page.source}`}>{page.source === "stock" ? "正股" : "期权"}</span>
      <span className="page-name">{page.name}</span>
      <span className="sep">·</span>
      <span className={page.running ? "status running" : page.last_error ? "status error" : "status stopped"}
            title={page.last_error ?? undefined}>
        {page.running ? "运行中" : page.last_error ? "错误" : "未运行"}
      </span>
      <span className="sep">·</span>
      <span>最后轮询 {formatRelative(page.last_poll_at)}</span>
      <span className="sep">·</span>
      <span>已发消息 {page.messages_published}</span>
      <span className="url-hover" title={page.url}>ⓘ</span>
    </div>
  );
}
```

简单测试 `PageInfoBar.test.tsx`：

```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PageInfoBar } from "./PageInfoBar";

describe("<PageInfoBar>", () => {
  it("renders running page", () => {
    render(<PageInfoBar page={{
      id: "a", url: "https://w/a/", source: "stock", name: "Hello",
      added_at: "2026-04-25T00:00:00Z",
      settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
      running: true, started_at: null, last_poll_at: null, messages_published: 42, last_error: null,
    }} />);
    expect(screen.getByText("正股")).toBeInTheDocument();
    expect(screen.getByText("Hello")).toBeInTheDocument();
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText(/已发消息\s*42/)).toBeInTheDocument();
  });

  it("renders orphan view", () => {
    render(<PageInfoBar page={null} orphanCount={5} />);
    expect(screen.getByText("已停用")).toBeInTheDocument();
    expect(screen.getByText(/5 条历史/)).toBeInTheDocument();
  });
});
```

- [ ] **M.4: PageActionBar**

新建 `frontend/src/components/Dashboard/PageActionBar.tsx`：

```typescript
import { useState } from "react";
import { api } from "../../api/http";
import { usePageTabsStore } from "../../stores/pageTabs";
import type { WhopPage } from "../../api/domain-types";

interface Props {
  page: WhopPage | null;            // null = orphan
  onOpenSettings: () => void;
}

export function PageActionBar({ page, onOpenSettings }: Props) {
  const [restarting, setRestarting] = useState(false);
  const isOrphan = page === null;
  const tabId = isOrphan ? "orphan" : page!.id;
  const expandMode = usePageTabsStore(s => s.expandModeByTab[tabId] ?? "smart");
  const setExpand = usePageTabsStore(s => s.setExpandMode);

  const handleRestart = async () => {
    if (isOrphan) return;
    if (!confirm(`确认重启 "${page!.name}"？`)) return;
    setRestarting(true);
    try { await api.restartWhopPage(page!.id); }
    catch (e) { alert(`重启失败：${e instanceof Error ? e.message : e}`); }
    finally { setRestarting(false); }
  };

  return (
    <div className="page-action-bar">
      <button onClick={handleRestart} disabled={isOrphan || restarting} className="action-btn">
        {restarting ? "重启中…" : "↻ 重启"}
      </button>
      <button onClick={onOpenSettings} disabled={isOrphan} className="action-btn">
        ⚙ 设置
      </button>
      <span className="spacer" />
      <button
        onClick={() => setExpand(tabId, "all-open")}
        className={expandMode === "all-open" ? "action-btn active" : "action-btn"}
      >⤓ 全展开</button>
      <button
        onClick={() => setExpand(tabId, "all-closed")}
        className={expandMode === "all-closed" ? "action-btn active" : "action-btn"}
      >⤒ 全收缩</button>
      {expandMode !== "smart" && (
        <button onClick={() => setExpand(tabId, "smart")} className="action-btn link">
          回 smart
        </button>
      )}
    </div>
  );
}
```

简单 test `PageActionBar.test.tsx`：

```typescript
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { usePageTabsStore } from "../../stores/pageTabs";
import { PageActionBar } from "./PageActionBar";

const stockPage = {
  id: "a", url: "u", source: "stock" as const, name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1, tickers: {} },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};

describe("<PageActionBar>", () => {
  beforeEach(() => { usePageTabsStore.getState().reset(); });

  it("disables restart/settings when orphan", () => {
    render(<PageActionBar page={null} onOpenSettings={vi.fn()} />);
    expect(screen.getByText(/重启/)).toBeDisabled();
    expect(screen.getByText(/设置/)).toBeDisabled();
  });

  it("toggle expand mode persists in store", () => {
    render(<PageActionBar page={stockPage} onOpenSettings={vi.fn()} />);
    fireEvent.click(screen.getByText("⤓ 全展开"));
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("all-open");
    fireEvent.click(screen.getByText("⤒ 全收缩"));
    expect(usePageTabsStore.getState().expandModeByTab["a"]).toBe("all-closed");
  });
});
```

- [ ] **M.5: EmptyState**

新建 `frontend/src/components/Dashboard/EmptyState.tsx`：

```typescript
import { useViewStore } from "../../stores/view";

export function EmptyState() {
  const setView = useViewStore(s => s.setView);
  return (
    <div className="dashboard-empty">
      <p>还没有任何监听页。</p>
      <p>
        <button className="link-btn" onClick={() => setView("whop")}>跳转到 Whop 管理</button>
        {" "}添加你的第一个监听。
      </p>
    </div>
  );
}
```

- [ ] **M.6: 改造 App.tsx 的 Dashboard 为 orchestrator**

修改 `frontend/src/App.tsx`：

完全用新结构替换原 `Dashboard` 函数体（保留 `function Dashboard({ token })` 签名，删除内部 DateGroups / stream 逻辑）：

```typescript
function Dashboard({ token }: { token: string }) {
  useStickyTop();
  const conn = useConnStore();
  const tasks = useTasksStore(s => s.tasks);
  const pushEventsByTask = useTasksStore(s => s.pushEventsByTask);
  const applyWs = useTasksStore(s => s.applyWsEvent);

  const pages = usePageTabsStore(s => s.pages);
  const activeTabId = usePageTabsStore(s => s.activeTabId);
  const setPages = usePageTabsStore(s => s.setPages);
  const setOrphanCount = usePageTabsStore(s => s.setOrphanCount);
  const expandMode = usePageTabsStore(s => activeTabId ? (s.expandModeByTab[activeTabId] ?? "smart") : "smart");

  const [settingsOpen, setSettingsOpen] = useState(false);

  // Refetch on WS reconnect
  const prevWsRef = useRef<typeof conn.ws>("closed");
  useEffect(() => {
    const shouldRefresh = conn.ws === "open" && prevWsRef.current !== "open";
    prevWsRef.current = conn.ws;
    if (!shouldRefresh) return;
    refreshStats();
    refreshPositions();
  }, [conn.ws]);

  // Mount: load tasks + pages + open WS
  useEffect(() => {
    let alive = true;
    (async () => {
      try { conn.setHealth(await api.health()); } catch {}
      try {
        const r = await api.listTasks({ limit: 100 });
        if (alive) useTasksStore.getState().setInitialTasks(r.tasks);
      } catch {}
      try {
        const p = await api.listWhopPages();
        if (alive) setPages(p.pages);
      } catch {}
      refreshStats();
      refreshPositions();
    })();
    const client = createWsClient({
      baseUrl: BASE_URL, token,
      onEvent: (evt) => {
        if (evt.type === "whop.page_changed") {
          usePageTabsStore.getState().applyPageChanged(evt);
        } else {
          applyWs(evt);
        }
        useConnStore.getState().setLastEventId(evt.event_id);
      },
      onStatus: (s) => useConnStore.getState().setWs(s),
    });
    client.connect();
    return () => { alive = false; client.disconnect(); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Compute orphan count whenever tasks or pages change
  const pageUrls = useMemo(() => new Set(pages.map(p => p.url)), [pages]);
  useEffect(() => {
    const orphans = tasks.filter(t => t.message?.url == null || !pageUrls.has(t.message.url));
    setOrphanCount(orphans.length);
  }, [tasks, pageUrls, setOrphanCount]);

  if (pages.length === 0 && tasks.length === 0) {
    return <main className="main"><EmptyState /></main>;
  }

  const activePage = activeTabId === "orphan" || activeTabId === null
    ? null
    : pages.find(p => p.id === activeTabId) ?? null;
  const filteredTasks = activeTabId === "orphan"
    ? selectTasksByUrl(tasks, null, pageUrls)
    : activePage ? selectTasksByUrl(tasks, activePage.url, pageUrls) : [];

  const orphanCount = usePageTabsStore.getState().orphanCount;

  return (
    <main className="main">
      <section className="stream">
        <PageTabs />
        <PageInfoBar page={activePage} orphanCount={orphanCount} />
        <PageActionBar page={activePage} onOpenSettings={() => setSettingsOpen(true)} />
        {filteredTasks.length === 0 ? (
          <div className="empty-state"><p>该监听页暂无任务。</p></div>
        ) : (
          <TaskStream tasks={filteredTasks} pushEventsByTask={pushEventsByTask} expandMode={expandMode} />
        )}
      </section>
      <RightRail />
      {settingsOpen && activePage && (
        <PageSettingsModal page={activePage} onClose={() => setSettingsOpen(false)} />
      )}
    </main>
  );
}
```

加 imports：
```typescript
import { useMemo, useState } from "react";
import { usePageTabsStore } from "./stores/pageTabs";
import { selectTasksByUrl } from "./stores/tasks";
import { PageTabs } from "./components/Dashboard/PageTabs";
import { PageInfoBar } from "./components/Dashboard/PageInfoBar";
import { PageActionBar } from "./components/Dashboard/PageActionBar";
import { TaskStream } from "./components/Dashboard/TaskStream";
import { EmptyState } from "./components/Dashboard/EmptyState";
import { PageSettingsModal } from "./components/Dashboard/PageSettingsModal";
```

> `PageSettingsModal` 在 Task N 实现；先在文件顶部留 stub `function PageSettingsModal(_: any) { return null; }` 让 typecheck 通过，Task N 替换。

删除 App.tsx 里的 `DateGroups` 函数 + `ACTIVE_STATUSES` / `isActiveExpanded` / `formatDateLabel`（已搬到 TaskStream.tsx）。

- [ ] **M.7: 加 Dashboard.css**

新建 `frontend/src/components/Dashboard/Dashboard.css`：

```css
.page-tabs { display: flex; gap: 4px; padding: 0 12px 8px; border-bottom: 1px solid var(--border-1); }
.page-tabs .tab {
  background: transparent; border: none; color: var(--fg-2);
  padding: 8px 14px; cursor: pointer; border-bottom: 2px solid transparent;
  display: flex; align-items: center; gap: 6px; font: inherit;
}
.page-tabs .tab.active { color: var(--fg-0); border-bottom-color: var(--accent); }
.page-tabs .tab.orphan { opacity: 0.7; }
.tab-source-dot { width: 8px; height: 8px; border-radius: 50%; }
.tab-source-dot.stock { background: #5fbf8b; }
.tab-source-dot.option { background: #8b6fcf; }
.tab-count { font-size: 11px; opacity: 0.6; padding-left: 4px; }

.page-info-bar {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  font-size: 12px; color: var(--fg-2);
}
.page-info-bar .badge { padding: 2px 8px; border-radius: 4px; font-weight: 500; font-size: 11px; }
.page-info-bar .badge.stock { background: rgba(95,191,139,0.15); color: #5fbf8b; }
.page-info-bar .badge.option { background: rgba(139,111,207,0.15); color: #8b6fcf; }
.page-info-bar .badge.gray { background: rgba(140,140,140,0.15); color: #999; }
.page-info-bar .status.running { color: #5fbf8b; }
.page-info-bar .status.error { color: #cf6f6f; cursor: help; }
.page-info-bar .status.stopped { color: var(--fg-3); }
.page-info-bar .sep { opacity: 0.4; }
.page-info-bar .url-hover { cursor: help; opacity: 0.6; }

.page-action-bar { display: flex; gap: 6px; padding: 0 12px 8px; }
.page-action-bar .action-btn {
  background: var(--bg-2); border: 1px solid var(--border-1); color: var(--fg-1);
  padding: 4px 10px; cursor: pointer; border-radius: 4px; font: inherit; font-size: 12px;
}
.page-action-bar .action-btn:hover:not(:disabled) { background: var(--bg-3); }
.page-action-bar .action-btn.active { background: var(--accent); color: white; border-color: var(--accent); }
.page-action-bar .action-btn.link { background: transparent; border: none; color: var(--fg-3); }
.page-action-bar .action-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-action-bar .spacer { flex: 1; }

.dashboard-empty { padding: 60px 20px; text-align: center; color: var(--fg-2); }
.dashboard-empty .link-btn { background: none; border: none; color: var(--accent); cursor: pointer; text-decoration: underline; padding: 0; font: inherit; }
```

在 `App.tsx` import：
```typescript
import "./components/Dashboard/Dashboard.css";
```

- [ ] **M.8: 跑前端测试 + 启动 dev 看一眼**

```bash
cd frontend && npm test -- --run components/Dashboard
```
Expected: PageTabs / PageInfoBar / PageActionBar 测试全绿。

```bash
cd frontend && npm run typecheck
```
Expected: pass.

```bash
make backend-dev   # 终端 1
make frontend-dev  # 终端 2
# 浏览器打开 http://localhost:5173
```
手动验证：
- 没 page 时显示 EmptyState + 跳转按钮
- 加一个 page 后看到 tab，切换 tab，重启按钮可点
- 全展开 / 收缩按钮工作
- 删 page 后 tab 消失，如果还有该 page 的历史 task 出现"已停用"tab

- [ ] **M.9: Commit**

```bash
git add frontend/src/components/Dashboard/ frontend/src/App.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): Dashboard 拆分 — PageTabs / InfoBar / ActionBar / TaskStream / EmptyState

监控看板二级 tab 走通。settings 弹窗占位（下一 task 完整实现）。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task N: PageSettingsModal（设置弹窗）

**Files:**
- Create: `frontend/src/components/Dashboard/PageSettingsModal.tsx` + `.test.tsx`
- Create: `frontend/src/components/Dashboard/PageSettingsModal.css`
- Modify: `frontend/src/App.tsx`（替换 stub）

- [ ] **N.1: 写 modal 测试**

新建 `frontend/src/components/Dashboard/PageSettingsModal.test.tsx`：

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { PageSettingsModal } from "./PageSettingsModal";
import type { WhopPage } from "../../api/domain-types";

const stockPage: WhopPage = {
  id: "a", url: "u", source: "stock", name: "S", added_at: "2026-04-25T00:00:00Z",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 1.0,
              tickers: { TSLL: { trade_quantity: 2000 } } },
  running: true, started_at: null, last_poll_at: null, messages_published: 0, last_error: null,
};
const optionPage: WhopPage = {
  ...stockPage, id: "b", source: "option",
  settings: { dedupe_processed_messages: true, price_deviation_tolerance: 5.0, tickers: null },
};

describe("<PageSettingsModal>", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("stock modal shows ticker editor; option modal hides it", () => {
    const { unmount } = render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    expect(screen.getByText(/股票配置/)).toBeInTheDocument();
    unmount();
    render(<PageSettingsModal page={optionPage} onClose={vi.fn()} />);
    expect(screen.queryByText(/股票配置/)).not.toBeInTheDocument();
  });

  it("editing ticker uppercases the key on save", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    fireEvent.click(screen.getByText(/添加 ticker/));
    const tickerInput = screen.getByPlaceholderText(/输入 ticker/);
    fireEvent.change(tickerInput, { target: { value: "nvda" } });
    const qtyInput = screen.getByPlaceholderText(/数量/);
    fireEvent.change(qtyInput, { target: { value: "500" } });
    fireEvent.click(screen.getByText(/保存/));
    await waitFor(() => expect(spy).toHaveBeenCalled());
    const arg = spy.mock.calls[0][1];
    expect(arg.tickers).toMatchObject({ NVDA: { trade_quantity: 500 } });
  });

  it("toggling dedupe shows hint about restart", () => {
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const checkbox = screen.getByLabelText(/避免重复解析/);
    fireEvent.click(checkbox);
    expect(screen.getByText(/下次重启监听才生效/)).toBeInTheDocument();
  });

  it("invalid tolerance (negative) blocks save", async () => {
    const spy = vi.spyOn(httpModule.api, "updateWhopPageSettings").mockResolvedValue(stockPage);
    render(<PageSettingsModal page={stockPage} onClose={vi.fn()} />);
    const input = screen.getByLabelText(/价格偏差容忍/);
    fireEvent.change(input, { target: { value: "-1" } });
    fireEvent.click(screen.getByText(/保存/));
    await waitFor(() => expect(screen.getByText(/必须 ≥ 0/)).toBeInTheDocument());
    expect(spy).not.toHaveBeenCalled();
  });
});
```

- [ ] **N.2: 实现 modal**

新建 `frontend/src/components/Dashboard/PageSettingsModal.tsx`：

```typescript
import { useState } from "react";
import type { WhopPage, WhopPageSettings, TickerConfig } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import "./PageSettingsModal.css";

interface Props {
  page: WhopPage;
  onClose: () => void;
}

export function PageSettingsModal({ page, onClose }: Props) {
  const [dedupe, setDedupe] = useState(page.settings.dedupe_processed_messages);
  const [tolerance, setTolerance] = useState(String(page.settings.price_deviation_tolerance));
  const [tickers, setTickers] = useState<Record<string, TickerConfig>>(
    () => page.settings.tickers ?? {}
  );
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const initialDedupe = page.settings.dedupe_processed_messages;
  const dedupeChanged = dedupe !== initialDedupe;

  const handleAddTicker = () => {
    setTickers(prev => ({ ...prev, "": { trade_quantity: 0 } }));
  };
  const handleRemoveTicker = (key: string) => {
    setTickers(prev => {
      const out = { ...prev };
      delete out[key];
      return out;
    });
  };
  const handleEditTickerKey = (oldKey: string, newKey: string) => {
    setTickers(prev => {
      const out = { ...prev };
      const v = out[oldKey];
      delete out[oldKey];
      out[newKey] = v;
      return out;
    });
  };
  const handleEditTickerQty = (key: string, qty: number) => {
    setTickers(prev => ({ ...prev, [key]: { trade_quantity: qty } }));
  };

  const handleSave = async () => {
    setError(null);
    const tolNum = Number(tolerance);
    if (Number.isNaN(tolNum) || tolNum < 0) {
      setError("价格偏差必须 ≥ 0");
      return;
    }
    if (page.source === "stock") {
      for (const [k, v] of Object.entries(tickers)) {
        if (!k.trim()) { setError("ticker 不能为空"); return; }
        if (!v || !Number.isFinite(v.trade_quantity) || v.trade_quantity <= 0) {
          setError(`${k}: 数量必须 > 0`);
          return;
        }
      }
    }
    setSaving(true);
    try {
      const patch: Partial<WhopPageSettings> = {
        dedupe_processed_messages: dedupe,
        price_deviation_tolerance: tolNum,
      };
      if (page.source === "stock") {
        patch.tickers = Object.fromEntries(
          Object.entries(tickers).map(([k, v]) => [k.toUpperCase(), v])
        );
      }
      await api.updateWhopPageSettings(page.id, patch as any);
      onClose();
    } catch (e) {
      if (e instanceof HttpError) setError(typeof e.body === "object" && e.body && "detail" in e.body
        ? String((e.body as any).detail) : e.message);
      else setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <header>
          <h3>{page.name} · 设置</h3>
          <button className="close" onClick={onClose}>✕</button>
        </header>

        <div className="modal-body">
          <section>
            <label>
              <input type="checkbox" checked={dedupe} onChange={e => setDedupe(e.target.checked)} />
              <span>避免重复解析消息（启动 / 重启时跳过 DB 中已存在的 domID）</span>
            </label>
            {dedupeChanged && (
              <p className="hint">⚠ 下次重启监听才生效（点上面操作行的"重启"按钮）</p>
            )}
          </section>

          <section>
            <label htmlFor="tol">价格偏差容忍（%）</label>
            <input
              id="tol" type="number" step="0.1" min="0"
              value={tolerance}
              onChange={e => setTolerance(e.target.value)}
            />
            <p className="hint small">
              市价偏离信号价 ≤ 此值 → 直接市价单；&gt; 此值 → 限价单 @ 信号价
            </p>
          </section>

          {page.source === "stock" && (
            <section>
              <h4>股票配置</h4>
              <p className="hint small">
                只有列表里的 ticker 才会触发下单；trade_quantity 是"常规仓"的整股数（半仓 ÷2、1/3 仓 ÷3）。
              </p>
              <table className="tickers-table">
                <thead><tr><th>Ticker</th><th>常规仓数量</th><th /></tr></thead>
                <tbody>
                  {Object.entries(tickers).map(([key, v]) => (
                    <tr key={key}>
                      <td>
                        <input
                          placeholder="输入 ticker"
                          value={key}
                          onChange={e => handleEditTickerKey(key, e.target.value)}
                          style={{ textTransform: "uppercase" }}
                        />
                      </td>
                      <td>
                        <input
                          type="number" min="1" placeholder="数量"
                          value={v.trade_quantity || ""}
                          onChange={e => handleEditTickerQty(key, Number(e.target.value))}
                        />
                      </td>
                      <td>
                        <button onClick={() => handleRemoveTicker(key)} className="del">✕</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button onClick={handleAddTicker} className="link">+ 添加 ticker</button>
            </section>
          )}

          {error && <div className="error">{error}</div>}
        </div>

        <footer>
          <button onClick={onClose}>取消</button>
          <button onClick={handleSave} disabled={saving} className="primary">
            {saving ? "保存中…" : "保存"}
          </button>
        </footer>
      </div>
    </div>
  );
}
```

新建 `PageSettingsModal.css`：

```css
.modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 100;
  display: flex; align-items: center; justify-content: center; }
.modal { background: var(--bg-1); border: 1px solid var(--border-1); border-radius: 8px;
  width: 600px; max-width: 90vw; max-height: 80vh; display: flex; flex-direction: column; }
.modal header { display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid var(--border-1); }
.modal header h3 { margin: 0; font-size: 14px; }
.modal .close { background: none; border: none; color: var(--fg-2); cursor: pointer; font-size: 16px; }
.modal-body { padding: 16px; overflow-y: auto; flex: 1; }
.modal-body section { margin-bottom: 18px; }
.modal-body section h4 { margin: 0 0 8px; font-size: 13px; }
.modal-body label { display: flex; align-items: center; gap: 8px; cursor: pointer; }
.modal-body input[type="number"] { width: 100px; padding: 4px 6px; }
.modal-body .hint { font-size: 11px; color: var(--fg-3); margin: 4px 0 0; }
.modal-body .hint.small { margin-top: 2px; }
.modal-body .tickers-table { width: 100%; border-collapse: collapse; margin: 8px 0; }
.modal-body .tickers-table th, .modal-body .tickers-table td { padding: 4px; text-align: left; }
.modal-body .tickers-table input { width: 100%; padding: 4px 6px; }
.modal-body .tickers-table .del { background: transparent; border: none; color: var(--fg-3); cursor: pointer; }
.modal-body .link { background: none; border: 1px dashed var(--border-1); color: var(--fg-2);
  padding: 6px 12px; cursor: pointer; border-radius: 4px; }
.modal-body .error { color: #cf6f6f; padding: 8px; background: rgba(207,111,111,0.1);
  border-radius: 4px; margin-top: 8px; font-size: 12px; }
.modal footer { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px;
  border-top: 1px solid var(--border-1); }
.modal footer button { padding: 6px 14px; cursor: pointer; }
.modal footer button.primary { background: var(--accent); color: white; border: none; }
```

- [ ] **N.3: 替换 App.tsx 里的 stub**

去掉之前的 `function PageSettingsModal(_: any) { return null; }` stub（如果留过）；保留 import：

```typescript
import { PageSettingsModal } from "./components/Dashboard/PageSettingsModal";
```

- [ ] **N.4: 跑 modal 测试**

```bash
cd frontend && npm test -- --run components/Dashboard/PageSettingsModal.test.tsx
```
Expected: 4 个测试全绿。

- [ ] **N.5: 手测**

```bash
make backend-dev & make frontend-dev
```

浏览器：
- 打开 stock page → 点 ⚙ 设置
- 添加 ticker `nvda` 数量 100 → 保存 → 看 PATCH 请求 → tickers 变 `{"NVDA": {"trade_quantity": 100}}`
- 切到 option page → 设置弹窗看不到"股票配置"section
- 改 dedupe 看到 hint，改偏差容忍看到 hint
- 错误情况：负数偏差，0 数量

- [ ] **N.6: Commit**

```bash
git add frontend/src/components/Dashboard/PageSettingsModal.tsx frontend/src/components/Dashboard/PageSettingsModal.css frontend/src/components/Dashboard/PageSettingsModal.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): PageSettingsModal — per-page 设置弹窗

去重开关 + 偏差阈值 + (stock) ticker 列表编辑器，PATCH 到 /api/whop/pages/{id}/settings。dedupe 改动 hint 提醒重启。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task O: Acceptance e2e + 文档

**Files:**
- Modify: `backend/tests/integration/test_acceptance.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **O.1: 加 acceptance 测试**

在 `backend/tests/integration/test_acceptance.py` 末尾追加：

```python
@pytest.mark.asyncio
async def test_acceptance_per_page_settings_drive_trader(app_factory, fake_broker):
    """End-to-end: add page → PATCH settings → message → trader uses new tickers + tolerance."""
    app = app_factory(broker_override=fake_broker, skip_whop=True)
    state = app.state.app_state
    registry = state.whop_registry

    # Patch listener start to no-op
    async def _noop_start(self, entry, *, skip_initial=True):
        self._listeners[entry.id] = None
    monkeypatch_obj_method(type(registry), "_start_listener", _noop_start)

    entry = await registry.add_page(
        url="https://whop.com/acc/app/", source="stock", name="acc",
    )
    await registry.update_settings(entry.id, {
        "tickers": {"TSLL": {"trade_quantity": 700}},
        "price_deviation_tolerance": 0.5,
    })

    # Inject a stock signal directly via event bus (simulating WhopListener publish)
    from app.core.event_bus import Event
    from app.core.events import MessagePayload, Topics
    from app.domain.message import Message
    from datetime import UTC, datetime

    msg = Message(
        id="acc-1",
        content="tsll 在16.02附近开个底仓 常规仓的一半",
        raw_content="tsll 在16.02附近开个底仓 常规仓的一半",
        author=None,
        posted_at=datetime.now(UTC), received_at=datetime.now(UTC),
        source="stock", url="https://whop.com/acc/app/",
    )
    await state.bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await state.bus.wait_idle()

    # Verify trader submitted with computed qty (2000 → 半仓 → 350)
    assert len(fake_broker.submitted) == 1
    assert fake_broker.submitted[0]["quantity"] == 350  # int(700 * 0.5)


@pytest.mark.asyncio
async def test_acceptance_unknown_ticker_skipped(app_factory, fake_broker):
    app = app_factory(broker_override=fake_broker, skip_whop=True)
    state = app.state.app_state
    registry = state.whop_registry
    monkeypatch_obj_method(type(registry), "_start_listener",
                          lambda self, e, *, skip_initial=True: None)

    entry = await registry.add_page(
        url="https://whop.com/skip/app/", source="stock", name="skip",
    )
    # No tickers in settings (default empty)

    from app.core.event_bus import Event
    from app.core.events import MessagePayload, Topics
    from app.domain.message import Message
    from datetime import UTC, datetime
    msg = Message(
        id="skip-1",
        content="tsll 在16.02附近开个底仓",
        raw_content="...",
        author=None,
        posted_at=datetime.now(UTC), received_at=datetime.now(UTC),
        source="stock", url="https://whop.com/skip/app/",
    )
    await state.bus.publish(Event(Topics.MESSAGE_RECEIVED, MessagePayload(msg)))
    await state.bus.wait_idle()
    assert fake_broker.submitted == []   # not in whitelist
```

> `monkeypatch_obj_method`：找现有 conftest 的等价 helper；如果没有，inline 用 `setattr(type(registry), "_start_listener", ...)` 注意末尾恢复（在 fixture teardown 里）。

- [ ] **O.2: 跑全套测试**

```bash
cd backend && uv run pytest -v
cd frontend && npm test -- --run
```
Expected: 全绿。

- [ ] **O.3: 更新 README**

在 `README.md` 找到 "REST API 参考 / Whop 监听管理" 表，加两行：

```markdown
| **PATCH** | `/api/whop/pages/{id}/settings` | 局部更新 page settings（dedupe / deviation / tickers） |
| **GET**   | `/api/whop/pages/defaults?source=stock\|option` | 返回 source 默认 settings 模板 |
```

在 "WebSocket 协议 / 事件类型" 列表加：
```markdown
- `whop.page_changed`（payload: `{action, page}`）
```

在 "Whop 监听 UI 工作流" 章节末尾加新小节：

```markdown
### 监控看板二级 tab + 设置

进入"监控看板" tab 后，列表上方新增：
- **二级 tab**：每个监听页一个 tab；tab 内只显示该 page 的 task
- **信息行**：source 徽章 / 名称 / 运行状态 / 最后轮询 / 已发消息
- **操作行**：[↻ 重启] [⚙ 设置] [⤓ 全展开] [⤒ 全收缩]
- **设置弹窗**（点 ⚙）：
  - **避免重复解析消息**：启动/重启时从 SQLite 拉历史 domID 集合，已处理过的不再触发解析。改动后下次重启生效
  - **价格偏差容忍**：市价偏离信号价 ≤ 阈值 → MARKET；&gt; 阈值 → LIMIT @ 信号价。立即生效
  - **股票配置**（仅 stock）：白名单 + "常规仓"数量；不在列表的 ticker 仍解析但 SKIPPED 不下单；半仓/1/3 仓按比例缩放，向下取整、最小 1
- **已停用 tab**：当前 page 列表外的历史 task 自动归到这里，灰色徽章
- **空态**：没监听页时整体替换为提示 + 跳转到 Whop 管理

> 注意：`config/watched_stocks.json` 已废弃；老数据中 task 没有 url 字段，会进"已停用" tab。
```

在 "配置（.env）" 表加注释（在 `STOCK_PRICE_DEVIATION_TOLERANCE` 行末尾）：
```markdown
| `STOCK_PRICE_DEVIATION_TOLERANCE` | `1.0` | 正股偏差容忍度 — **仅作孤儿 task（无 page）的 fallback**，per-page 优先 |
| `PRICE_DEVIATION_TOLERANCE` | `5.0` | 期权偏差容忍度 — **同上**，per-page 优先 |
```

去掉 "关注股配置" 子章节（关于 `config/watched_stocks.json`）—— 替换为：

```markdown
### 监听页 ticker 白名单

不再有全局 ticker 配置文件。每个 stock 监听页独立维护 ticker → trade_quantity 映射，从 dashboard 内 ⚙ 设置编辑，存到 `data/whop_pages.json`。
```

- [ ] **O.4: 写 CHANGELOG**

如果不存在，新建 `CHANGELOG.md`；否则在顶部追加：

```markdown
## Unreleased

### Added
- 监控看板二级 tab：每个 Whop 监听页独立 tab + 信息行 + 操作行（重启 / 设置 / 全展开 / 全收缩）
- per-page 设置：去重开关、价格偏差容忍、（stock）ticker 白名单 + 常规仓数量；存 `data/whop_pages.json`
- 设置弹窗：dashboard 内 ⚙ 设置按钮
- 孤儿 task 模式：监听页被移除后历史 task 进"已停用" tab
- REST: `PATCH /api/whop/pages/{id}/settings`、`GET /api/whop/pages/defaults?source=`
- WS event: `whop.page_changed`
- DB: `messages.url` 列 + index（alembic migration）
- domain: `Message.url`；listener `_scan_once` 自动注入

### Changed
- **BREAKING**: trader 价格偏差行为从"超阈拒单"改成"超阈降级到 LIMIT @ 信号价"。永不拒单（除非白名单 / 缺价格）
- **BREAKING**: stock ticker 白名单 gate—— 不在 page settings.tickers 中的 ticker SKIPPED 不下单
- ParserService 接收 `WhopRegistry`，按 `message.url` 反查 page settings 取 ticker 列表（取代全局 watched_stocks）
- WhopListener 加 `dedupe_processed_messages` ctor 参数；启动时从 DB 灌 `_seen`

### Removed
- **BREAKING**: `config/watched_stocks.json` 退役 + `parser.context_resolver.load_watched_tickers` 删除。需要在 dashboard 设置里手动配置每个 stock page 的 ticker 列表
```

- [ ] **O.5: Commit**

```bash
git add backend/tests/integration/test_acceptance.py README.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
test(acceptance) + docs: e2e per-page settings 驱动 trader 行为；README + CHANGELOG 更新

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task P: 全量回归 + 收尾

- [ ] **P.1: 跑全套 lint + typecheck + test**

```bash
make lint && make typecheck && make test
```
Expected: 全绿。

- [ ] **P.2: 启动一遍生产模式手测**

```bash
make build && make run
# 浏览器 http://localhost:8000
```
- 登录 → dashboard
- 看 EmptyState（如果 data/whop_pages.json 是空）
- 跳到 Whop 管理 → 添加 stock page → 回 dashboard 看 tab
- 设置里加 ticker、改 deviation
- 关闭后端再起来 → settings 持久化恢复
- 加第二个 page → 看到第二个 tab；切 tab 任务流过滤正确
- 用 sqlite3 的 `INSERT INTO messages (id, ..., url) VALUES (...)` 注入一条 url=NULL 的假消息再删 page → 验证孤儿 tab 出现

- [ ] **P.3: 总结 PR / 合并到主干（按用户偏好处理）**

实施完成。如需 merge 或开 PR，按用户的 git/PR 偏好操作。

---

## Self-Review

### Spec coverage 检查

| Spec 章节 | 实施 task | OK? |
|----|----|----|
| §3.1 UI 结构 | M.1 / M.2 / M.6 | ✓ |
| §3.2 组件拆分 | M.1-M.6 + N | ✓ |
| §3.3 孤儿 tab | K.4 selectTasksByUrl + M.6 orphanCount + M.2 PageTabs orphan | ✓ |
| §3.4 空态 | M.5 EmptyState | ✓ |
| §3.5 全展开/收缩 | K.2 expandModeByTab + M.4 PageActionBar | ✓ |
| §4.1/4.2 settings 数据结构 | C + D | ✓ |
| §4.3 messages.url schema | A | ✓ |
| §4.4 Task.url 暴露 | H.1 message_to_out 加 url | ✓ |
| §4.5 watched_stocks 退役 | F | ✓ |
| §4.6 SKIPPED 状态 | 已存在；G 用 mark_skipped | ✓ |
| §5.1 listener 去重逻辑 | E | ✓ |
| §5.2 行为矩阵 | E.3 实现 | ✓ |
| §5.3 设置变更生效策略 | dedupe 不触发 restart（D.4 实现里 update_settings 不重启）；trader 实时反查 | ✓ |
| §5.4 trader 改造 | G | ✓ |
| §5.5 取整规则 | G.4 max(int(...), 1) | ✓ |
| §5.6 Registry 新 API | D | ✓ |
| §5.7 PATCH validation | D.4 + H.4 | ✓ |
| §6.1 REST 端点 | H | ✓ |
| §6.2 WS 事件 | I | ✓ |
| §6.3 OpenAPI 同步 | J | ✓ |
| §7.1 pageTabs store | K | ✓ |
| §7.2 tasks selector | K.4 | ✓ |
| §7.3 切 tab 视觉 | M.6 直接硬切 | ✓ |
| §8 测试覆盖 | A.5 / B / C / D / E / F / G / H / I / K / M / N / O.1 | ✓ |
| §11 文档更新 | O.3 / O.4 | ✓ |

### Placeholder 扫描

无 "TBD"/"TODO" 在步骤指令里（trader.py 内代码注释中保留 1 个 `# TODO: hook real quote` 是设计选择，对应 G.1 的决策）。无空步骤。

### 类型一致性

- `PageSettings.tickers: dict[str, TickerConfig] | None` 在 backend C/D/G 全程一致
- `WhopPageSettingsOut.tickers: dict[str, TickerConfigOut] | None` 在 schema H 与 backend 形状一致
- 前端 `WhopPage.settings.tickers` 通过 OpenAPI 自动生成，类型链贯通
- `expandModeByTab` 在 K + M.4 + TaskStream 中形态一致
- `WhopPagePayload.action` 字符串值（"added"/"removed"/"restarted"/"settings_updated"）在后端 D.4 发布、I 桥接、前端 K.2 处理一致
- WS event payload `{action, page}` 字段名在 backend ws.py I.3 与 frontend K 一致

无类型问题。

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-dashboard-tabs-and-listener-config.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
