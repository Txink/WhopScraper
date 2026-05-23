# 讨论区按天懒加载 — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标**：把讨论区（ChatBoardPanel）的消息加载从「整周一次性拉」改成「初始今天+昨天，切日按需拉」，DayPicker 圆点改由新增的月度计数接口驱动；同时删除 `week=` 参数。

**架构**：后端将 `/api/whop/pages/{id}/chat-messages` 改为按北京日（`day=YYYY-MM-DD`）查询；新增 `/api/whop/pages/{id}/chat-message-counts?month=YYYY-MM` 返回该月每天的消息数（仅 > 0）。前端 `chatStore` 改成 `(pageId, day)` 的缓存 + 单独的月度计数缓存，`ChatBoardPanel` 重写加载触发；WS `chat.message_stored` 只刷新「今天」+ 当月计数。

**Tech Stack**：FastAPI（Python 3.12+，uv）、SQLAlchemy async、Pydantic v2、SQLite（生产）、React 18、Zustand 5、Vite + Vitest、TypeScript。

**相关 spec**：`docs/superpowers/specs/2026-05-23-chat-lazy-day-loading-design.md`

---

## 共用命令参考

后端从仓库根目录运行：
- 跑单测：`cd backend && uv run pytest <path>::<test_name> -v`
- 跑某个文件：`cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py -v`

前端：
- 跑单测：`cd frontend && npm test -- src/stores/chatStore.test.ts`（vitest run 模式）
- typecheck：`cd frontend && npm run typecheck`
- 重新生成 OpenAPI 类型：`cd frontend && npm run gen:types`

集成：
- 启服务：`make dev`（同时启 backend:8000 + frontend:5173）

---

### Task 1: 新增 repo 函数 `count_chat_messages_per_day`

**Files:**
- Modify: `backend/app/storage/repo.py`（追加到 `list_chat_authors` 之后，`delete_chat_messages_by_page` 之前；约 1879 行）
- Test: `backend/tests/storage/test_chat_repo.py`（追加）

#### - [ ] Step 1: 写失败测试 — 多天计数 + 跳过 0 消息日

追加到 `backend/tests/storage/test_chat_repo.py`：

```python
async def test_count_chat_messages_per_day_groups_by_beijing_day(session_factory) -> None:
    # 三条消息分别落在 5-19、5-20（两条）；5-21 没消息
    msgs = [
        _row("a", posted_at=datetime(2026, 5, 19, 3, 0, tzinfo=UTC)),   # 北京 5-19 11:00
        _row("b", posted_at=datetime(2026, 5, 20, 1, 0, tzinfo=UTC)),   # 北京 5-20 09:00
        _row("c", posted_at=datetime(2026, 5, 20, 15, 0, tzinfo=UTC)),  # 北京 5-20 23:00
    ]
    async with session_scope(session_factory) as s:
        for r in msgs:
            await repo.upsert_chat_message(s, r)

    async with session_scope(session_factory) as s:
        out = await repo.count_chat_messages_per_day(
            s, "p1",
            datetime(2026, 5, 18, 16, tzinfo=UTC),   # 北京 5-19 00:00
            datetime(2026, 5, 25, 16, tzinfo=UTC),   # 北京 5-26 00:00
        )

    assert out == [("2026-05-19", 1), ("2026-05-20", 2)]
```

#### - [ ] Step 2: 跑测试确认失败

```bash
cd backend && uv run pytest tests/storage/test_chat_repo.py::test_count_chat_messages_per_day_groups_by_beijing_day -v
```

预期：`AttributeError: module 'app.storage.repo' has no attribute 'count_chat_messages_per_day'`

#### - [ ] Step 3: 实现 repo 函数

追加到 `backend/app/storage/repo.py`（在 `list_chat_authors` 之后）：

```python
async def count_chat_messages_per_day(
    session: AsyncSession,
    page_id: str,
    range_start_utc: datetime,
    range_end_utc: datetime,
) -> list[tuple[str, int]]:
    """按北京日历日 (YYYY-MM-DD) 聚合返回 ``(day, count)``，仅 ``count > 0``，
    按 day 升序。

    SQLite 用 ``strftime("%Y-%m-%d", datetime(posted_at, "+8 hours"))`` 把
    UTC 时间投影到 Asia/Shanghai 日历日。若未来换 Postgres，需要把这段
    SQL 改成 ``to_char(posted_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD')``。

    ``range_start_utc`` / ``range_end_utc`` 是半开 UTC 区间，调用方应传入
    与 ``[北京月初 00:00, 次月初 00:00)`` 等价的 UTC 边界。
    """
    day_expr = func.strftime(
        "%Y-%m-%d", func.datetime(ChatMessageRow.posted_at, "+8 hours")
    )
    stmt = (
        select(day_expr.label("day"), func.count(ChatMessageRow.id))
        .where(ChatMessageRow.page_id == page_id)
        .where(ChatMessageRow.posted_at >= range_start_utc)
        .where(ChatMessageRow.posted_at < range_end_utc)
        .group_by(day_expr)
        .order_by(day_expr.asc())
    )
    result = await session.execute(stmt)
    return [(day, count) for day, count in result.all()]
```

#### - [ ] Step 4: 跑测试确认通过

```bash
cd backend && uv run pytest tests/storage/test_chat_repo.py::test_count_chat_messages_per_day_groups_by_beijing_day -v
```

预期：PASS

#### - [ ] Step 5: 补一个跨月边界的测试

追加：

```python
async def test_count_chat_messages_per_day_respects_range(session_factory) -> None:
    # 一条在 4 月最后一天，一条在 5 月第一天（都按北京日历）
    async with session_scope(session_factory) as s:
        await repo.upsert_chat_message(
            s, _row("apr", posted_at=datetime(2026, 4, 30, 15, 0, tzinfo=UTC)),  # 北京 4-30 23:00
        )
        await repo.upsert_chat_message(
            s, _row("may", posted_at=datetime(2026, 5, 1, 1, 0, tzinfo=UTC)),    # 北京 5-1 09:00
        )

    # 仅查 5 月（北京月）
    async with session_scope(session_factory) as s:
        out = await repo.count_chat_messages_per_day(
            s, "p1",
            datetime(2026, 4, 30, 16, tzinfo=UTC),   # 北京 5-1 00:00
            datetime(2026, 5, 31, 16, tzinfo=UTC),   # 北京 6-1 00:00
        )

    assert out == [("2026-05-01", 1)]
```

跑：

```bash
cd backend && uv run pytest tests/storage/test_chat_repo.py -v -k count_chat_messages_per_day
```

预期：两条 PASS。

#### - [ ] Step 6: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add backend/app/storage/repo.py backend/tests/storage/test_chat_repo.py
git commit -m "feat(repo): count_chat_messages_per_day grouped by Beijing day"
```

---

### Task 2: 改 schemas — 新增 Day 窗口与 Counts 出参

**Files:**
- Modify: `backend/app/api/schemas.py:664-672`

#### - [ ] Step 1: 改 ChatMessagesOut，新增 ChatMessageCountsOut

把 `backend/app/api/schemas.py:664-672` 这一段：

```python
class ChatWeekWindowOut(BaseModel):
    start: datetime
    end: datetime


class ChatMessagesOut(BaseModel):
    messages: list[ChatMessageOut]
    authors: list[ChatAuthorOut]
    week: ChatWeekWindowOut
```

替换为：

```python
class ChatDayWindowOut(BaseModel):
    """北京日历日的半开 UTC 区间 ``[start, end)``。"""

    start: datetime
    end: datetime


class ChatMessagesOut(BaseModel):
    messages: list[ChatMessageOut]
    authors: list[ChatAuthorOut]
    day: ChatDayWindowOut


class ChatMessageCountsOut(BaseModel):
    """按北京日历日聚合的当月消息计数。``counts`` 仅包含 ``count > 0`` 的天。"""

    month: str  # "YYYY-MM"
    counts: dict[str, int]  # {"YYYY-MM-DD": count}
```

#### - [ ] Step 2: 跑 typecheck + 测试（预期编译/语法 OK，旧测试会因字段名变化失败 — 下一个 Task 处理）

```bash
cd backend && uv run python -c "from app.api.schemas import ChatMessagesOut, ChatMessageCountsOut, ChatDayWindowOut; print('ok')"
```

预期：`ok`

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py -v -x 2>&1 | head -40
```

预期：现有用例可能因为 `week` 字段消失或 endpoint 还没改而失败 — 不要在这步修，Task 4 一起处理。

#### - [ ] Step 3: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add backend/app/api/schemas.py
git commit -m "refactor(schemas): chat-messages day window + counts out"
```

---

### Task 3: 改 endpoint — `_beijing_day_bounds` + `day=` 必填、删除 `week=`

**Files:**
- Modify: `backend/app/api/http.py:125-142`（替换 `_iso_week_bounds`）
- Modify: `backend/app/api/http.py:1552-1596`（endpoint）

#### - [ ] Step 1: 替换辅助函数

把 `backend/app/api/http.py:125-142` 这一段：

```python
def _iso_week_bounds(week: str | None) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` for an ISO week label like ``"2026-W21"``.
    ...
    """
    if week is None:
        now = datetime.now(UTC)
        iso_year, iso_week, _ = now.isocalendar()
    else:
        try:
            year_s, week_s = week.split("-W", 1)
            iso_year, iso_week = int(year_s), int(week_s)
        except (ValueError, IndexError) as e:
            raise HTTPException(400, detail=f"invalid week: {week}") from e
    monday = datetime.fromisocalendar(iso_year, iso_week, 1).replace(tzinfo=UTC)
    return monday, monday + timedelta(days=7)
```

替换为：

```python
def _beijing_day_bounds(day: str) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` in UTC for a Beijing calendar day like
    ``"2026-05-23"``. The window is ``[day 00:00 +08:00, next 00:00 +08:00)``
    expressed as UTC datetimes — suitable for ``posted_at >= start AND < end``.
    """
    try:
        y, m, d = day.split("-")
        year, month, dom = int(y), int(m), int(d)
    except (ValueError, IndexError) as e:
        raise HTTPException(400, detail=f"invalid day: {day}") from e
    # Beijing 00:00 of `day` == UTC `day-1 16:00`
    start_utc = datetime(year, month, dom, tzinfo=UTC) - timedelta(hours=8)
    end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc


def _beijing_month_bounds(month: str) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` in UTC for a Beijing calendar month like
    ``"2026-05"``. End is the first instant of the next month, Beijing-local.
    """
    try:
        y, m = month.split("-")
        year, mon = int(y), int(m)
    except (ValueError, IndexError) as e:
        raise HTTPException(400, detail=f"invalid month: {month}") from e
    start_utc = datetime(year, mon, 1, tzinfo=UTC) - timedelta(hours=8)
    if mon == 12:
        next_year, next_mon = year + 1, 1
    else:
        next_year, next_mon = year, mon + 1
    end_utc = datetime(next_year, next_mon, 1, tzinfo=UTC) - timedelta(hours=8)
    return start_utc, end_utc
```

（保留 `_iso_week_bounds` 暂未必要 — 直接删除整段函数，本仓库里只有 chat-messages 端点和 `__init__.py` 重导出会引用它。下一步会验证。）

#### - [ ] Step 2: 确认 `_iso_week_bounds` 没有其它调用方

```bash
cd /Users/tianpengxuan/Documents/signal-station
grep -rn "_iso_week_bounds" backend/ 2>&1
```

预期：除了刚才编辑的 `http.py` 之外没有其他引用。如有，停下处理。

#### - [ ] Step 3: 改 endpoint

替换 `backend/app/api/http.py:1552-1596` 整段 `get_chat_messages`：

```python
        @router.get(
            "/api/whop/pages/{page_id}/chat-messages",
            response_model=ChatMessagesOut,
        )
        async def get_chat_messages(
            page_id: str,
            day: str,
            senders: str | None = None,
        ) -> ChatMessagesOut:
            """Return one Beijing-calendar-day's worth of chat messages
            for *page_id*.

            ``day=YYYY-MM-DD`` is required; the window is ``[day 00:00 +08:00,
            next 00:00 +08:00)`` expressed in UTC. ``senders`` is a
            comma-separated allow-list of authors; empty / absent → no filter.
            ``authors`` is the (author, count) breakdown for the *unfiltered*
            day — the chip bar should show every author seen in the window
            regardless of the active filter selection.
            """
            page = None
            for entry, _ll in whop_registry.list_pages(parent_chat_id=None):
                if entry.id == page_id:
                    page = entry
                    break
            if page is None:
                raise HTTPException(404, detail="page not found")

            day_start, day_end = _beijing_day_bounds(day)
            sender_list = (
                [s.strip() for s in senders.split(",") if s.strip()]
                if senders
                else None
            )

            async with session_scope(session_factory) as session:
                rows = await repo.list_chat_messages(
                    session, page_id, day_start, day_end, sender_list
                )
                authors = await repo.list_chat_authors(
                    session, page_id, day_start, day_end
                )

            return ChatMessagesOut(
                messages=[_row_to_chat_out(r) for r in rows],
                authors=[ChatAuthorOut(name=a, count=c) for a, c in authors],
                day=ChatDayWindowOut(start=day_start, end=day_end),
            )
```

同步把 import 行（`backend/app/api/http.py` 顶部附近的 schemas import）里的 `ChatWeekWindowOut` 换成 `ChatDayWindowOut`，新增 `ChatMessageCountsOut`：

```bash
cd /Users/tianpengxuan/Documents/signal-station
grep -n "ChatWeekWindowOut\|ChatMessagesOut\|ChatMessageCountsOut" backend/app/api/http.py
```

按需手工 Edit。

#### - [ ] Step 4: 跑 endpoint 测试（应有大量失败 — 下个 Task 修测试）

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py -v 2>&1 | tail -30
```

预期：原 `week=` 用例返回 422（缺少必填 `day`），或 body 里缺少 `week` 字段。**保留失败，下一 Task 修测试。**

#### - [ ] Step 5: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add backend/app/api/http.py
git commit -m "refactor(api): chat-messages day-based query; drop week= param"
```

---

### Task 4: 更新 chat-messages endpoint 测试

**Files:**
- Modify: `backend/tests/api/test_chat_messages_endpoint.py`

#### - [ ] Step 1: 改 `test_get_chat_messages_returns_shape`

把（约第 405-422 行）：

```python
def test_get_chat_messages_returns_shape(app_with_db) -> None:
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client)

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"week": "2026-W21", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "messages" in body
    assert "authors" in body
    assert "week" in body
    assert isinstance(body["messages"], list)
    assert isinstance(body["authors"], list)
    assert "start" in body["week"]
    assert "end" in body["week"]
```

改成：

```python
def test_get_chat_messages_returns_shape(app_with_db) -> None:
    """Endpoint returns messages, authors, day — all top-level keys present."""
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client)

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-23", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "messages" in body
    assert "authors" in body
    assert "day" in body
    assert "week" not in body
    assert isinstance(body["messages"], list)
    assert isinstance(body["authors"], list)
    assert "start" in body["day"]
    assert "end" in body["day"]


def test_get_chat_messages_requires_day(app_with_db) -> None:
    """``day`` is required; missing → 422."""
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client)

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"token": _TOKEN},
    )
    assert resp.status_code == 422


def test_get_chat_messages_rejects_invalid_day(app_with_db) -> None:
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client)

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "not-a-date", "token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "invalid day" in resp.text
```

#### - [ ] Step 2: 改 `test_get_chat_messages_filters_by_sender`

把现有的 `params={"week": "2026-W21", "senders": "alice", "token": _TOKEN}` 改成 `params={"day": "2026-05-20", "senders": "alice", "token": _TOKEN}`，并把种子里所有 `datetime(2026, 5, 20, 9, i, tzinfo=UTC)` 保持不变（UTC 9:00 = 北京 5-20 17:00，仍在 5-20 北京日内）。

#### - [ ] Step 3: 改 `test_get_chat_messages_posted_at_carries_utc_offset`

种子里的消息 `posted_at=datetime(2026, 5, 20, 23, 18, tzinfo=UTC)` 对应北京 5-21 07:18。把请求改成 `params={"day": "2026-05-21", "token": _TOKEN}`，断言保持「`posted_at` 序列化里带 UTC offset」即可。

#### - [ ] Step 4: 加北京日边界专项用例

追加：

```python
def test_get_chat_messages_beijing_day_boundary(app_with_db) -> None:  # noqa: ANN001
    """A message at UTC 16:30 on day D belongs to Beijing day D+1, not D."""
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/chat-bj-edge")

    # UTC 2026-05-23 16:30 == Beijing 2026-05-24 00:30
    async def _seed() -> None:
        async with factory() as s:
            await repo.upsert_chat_message(
                s,
                ChatMessageRow(
                    id="m-edge",
                    page_id=page_id,
                    author="alice",
                    content="x",
                    raw_content="x",
                    posted_at=datetime(2026, 5, 23, 16, 30, tzinfo=UTC),
                    received_at=datetime(2026, 5, 23, 16, 30, tzinfo=UTC),
                    url="https://whop.example/chat-bj-edge",
                    quoted_message_id=None,
                    quoted_author=None,
                    quoted_content=None,
                    quoted_posted_at=None,
                ),
            )
            await s.commit()

    loop.run_until_complete(_seed())

    # day=2026-05-23 (Beijing) -> message NOT in window
    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-23", "token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["messages"] == []

    # day=2026-05-24 (Beijing) -> message IS in window
    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-24", "token": _TOKEN},
    )
    assert resp.status_code == 200
    assert [m["id"] for m in resp.json()["messages"]] == ["m-edge"]
```

#### - [ ] Step 5: 跑测试

```bash
cd backend && uv run pytest tests/api/test_chat_messages_endpoint.py -v
```

预期：所有用例 PASS。

#### - [ ] Step 6: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add backend/tests/api/test_chat_messages_endpoint.py
git commit -m "test(api): chat-messages endpoint switched to day= param"
```

---

### Task 5: 新增 `/chat-message-counts` endpoint + 测试

**Files:**
- Modify: `backend/app/api/http.py`（紧跟在 `get_chat_messages` 之后注册）
- Create: `backend/tests/api/test_chat_message_counts_endpoint.py`

#### - [ ] Step 1: 写失败测试（含 0 消息日跳过、跨月边界）

新建 `backend/tests/api/test_chat_message_counts_endpoint.py`：

```python
"""GET /api/whop/pages/{page_id}/chat-message-counts — Beijing-day counts."""

from __future__ import annotations

from datetime import UTC, datetime

from app.storage import repo
from app.storage.schema import ChatMessageRow

# 复用现有 endpoint 测试模块的 fixture
from tests.api.test_chat_messages_endpoint import (  # noqa: F401
    _TOKEN,
    _make_chat_page,
    app_with_db,
    patch_browser,
    settings_test,
)


def _seed(loop, factory, page_id: str, msgs: list[tuple[str, datetime]]) -> None:
    async def _do() -> None:
        async with factory() as s:
            for mid, ts in msgs:
                await repo.upsert_chat_message(
                    s,
                    ChatMessageRow(
                        id=mid,
                        page_id=page_id,
                        author="alice",
                        content="x",
                        raw_content="x",
                        posted_at=ts,
                        received_at=ts,
                        url="https://whop.example/counts",
                        quoted_message_id=None,
                        quoted_author=None,
                        quoted_content=None,
                        quoted_posted_at=None,
                    ),
                )
            await s.commit()

    loop.run_until_complete(_do())


def test_chat_message_counts_returns_shape(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-shape")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"month": "2026-05", "counts": {}}


def test_chat_message_counts_omits_zero_days(app_with_db) -> None:  # noqa: ANN001
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-zero")

    # 5-19 一条；5-20 两条；5-21 没消息
    _seed(loop, factory, page_id, [
        ("a", datetime(2026, 5, 19, 3, 0, tzinfo=UTC)),
        ("b", datetime(2026, 5, 20, 1, 0, tzinfo=UTC)),
        ("c", datetime(2026, 5, 20, 15, 0, tzinfo=UTC)),
    ])

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "month": "2026-05",
        "counts": {"2026-05-19": 1, "2026-05-20": 2},
    }


def test_chat_message_counts_month_boundary(app_with_db) -> None:  # noqa: ANN001
    """A message at UTC 2026-04-30 15:00 == Beijing 2026-04-30 23:00; should
    appear under month=2026-04 only, not 2026-05."""
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-bound")

    _seed(loop, factory, page_id, [
        ("apr-end", datetime(2026, 4, 30, 15, 0, tzinfo=UTC)),   # 北京 4-30 23:00
        ("may-start", datetime(2026, 5, 1, 1, 0, tzinfo=UTC)),   # 北京 5-1 09:00
    ])

    resp_apr = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-04", "token": _TOKEN},
    )
    assert resp_apr.json()["counts"] == {"2026-04-30": 1}

    resp_may = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp_may.json()["counts"] == {"2026-05-01": 1}


def test_chat_message_counts_requires_month(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-req")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"token": _TOKEN},
    )
    assert resp.status_code == 422


def test_chat_message_counts_rejects_invalid_month(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-bad")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "abc", "token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "invalid month" in resp.text


def test_chat_message_counts_unknown_page_404(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    resp = client.get(
        "/api/whop/pages/no-such-page/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp.status_code == 404
```

#### - [ ] Step 2: 跑测试确认全部失败

```bash
cd backend && uv run pytest tests/api/test_chat_message_counts_endpoint.py -v
```

预期：所有用例 404 / 422（因 endpoint 还不存在）或类似。

#### - [ ] Step 3: 注册 endpoint

在 `backend/app/api/http.py` 中，紧跟 `get_chat_messages` 之后追加（同一个 `build_http_router` 闭包内）：

```python
        @router.get(
            "/api/whop/pages/{page_id}/chat-message-counts",
            response_model=ChatMessageCountsOut,
        )
        async def get_chat_message_counts(
            page_id: str,
            month: str,
        ) -> ChatMessageCountsOut:
            """Return per-Beijing-day message counts for the given month.

            Days with zero messages are omitted from ``counts``. The window
            is ``[month-01 00:00 +08:00, (month+1)-01 00:00 +08:00)``
            expressed in UTC.
            """
            page = None
            for entry, _ll in whop_registry.list_pages(parent_chat_id=None):
                if entry.id == page_id:
                    page = entry
                    break
            if page is None:
                raise HTTPException(404, detail="page not found")

            start, end = _beijing_month_bounds(month)
            async with session_scope(session_factory) as session:
                pairs = await repo.count_chat_messages_per_day(
                    session, page_id, start, end
                )

            return ChatMessageCountsOut(
                month=month,
                counts={day: count for day, count in pairs},
            )
```

确认 `ChatMessageCountsOut` 已加入 schemas import。

#### - [ ] Step 4: 跑测试确认通过

```bash
cd backend && uv run pytest tests/api/test_chat_message_counts_endpoint.py -v
```

预期：6 条全部 PASS。

#### - [ ] Step 5: 跑全量 backend 单测，看有无 collateral

```bash
cd backend && uv run pytest -v 2>&1 | tail -40
```

预期：所有用例通过。

#### - [ ] Step 6: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add backend/app/api/http.py backend/tests/api/test_chat_message_counts_endpoint.py
git commit -m "feat(api): GET /chat-message-counts — Beijing-day counts per month"
```

---

### Task 6: 重新生成 OpenAPI 类型

**Files:**
- Modify: `frontend/src/api/types.ts`（脚本生成）

#### - [ ] Step 1: 运行生成脚本

```bash
cd frontend && npm run gen:types
```

预期：`./openapi.json` 重新生成；`src/api/types.ts` 中 `chat-messages` paths 的 query 参数从 `week` 改为 `day`；新增 `chat-message-counts` path；`ChatMessagesOut.day` 字段出现；`ChatMessageCountsOut` 类型出现。

#### - [ ] Step 2: typecheck 看哪些前端文件因类型变化报错

```bash
cd frontend && npm run typecheck 2>&1 | tail -40
```

预期：`api/chat.ts`、`stores/chatStore.ts`、`components/Chat/ChatBoardPanel.tsx` 会有类型错（用了 `.week` 字段或 `week` 参数）。**不要在这步修，下面几个 Task 处理。**

#### - [ ] Step 3: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/api/types.ts frontend/openapi.json
git commit -m "chore(types): regen OpenAPI after chat day/counts endpoints"
```

---

### Task 7: 改前端 API 客户端（`api/chat.ts`）

**Files:**
- Modify: `frontend/src/api/chat.ts`

#### - [ ] Step 1: 替换 `listChatMessages` + 新增 counts 函数

把 `frontend/src/api/chat.ts:1-47` 这一段：

```ts
import type { ChatMessageOut } from "../components/Chat/chatCards";

/** GET /api/whop/pages/{page_id}/chat-messages response envelope. ... */
export interface ChatMessagesResponse {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  week: { start: string; end: string };
}

// ... authedUrl unchanged ...

export async function listChatMessages(
  pageId: string,
  week: string | null,
  senders: string[],
): Promise<ChatMessagesResponse> {
  const params: Record<string, string> = {};
  if (week) params.week = week;
  if (senders.length) params.senders = senders.join(",");
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/chat-messages`,
    params,
  );
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`listChatMessages ${pageId}: ${resp.status}`);
  }
  return resp.json();
}
```

替换为：

```ts
import type { ChatMessageOut } from "../components/Chat/chatCards";

/** GET /api/whop/pages/{page_id}/chat-messages — single Beijing-day window. */
export interface ChatMessagesResponse {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  day: { start: string; end: string };
}

/** GET /api/whop/pages/{page_id}/chat-message-counts — per-day counts for
 *  one Beijing calendar month. Days with zero messages are omitted. */
export interface ChatMessageCountsResponse {
  month: string;
  counts: Record<string, number>;
}

// authedUrl unchanged below ...

export async function listChatMessagesForDay(
  pageId: string,
  day: string,
  senders: string[],
): Promise<ChatMessagesResponse> {
  const params: Record<string, string> = { day };
  if (senders.length) params.senders = senders.join(",");
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/chat-messages`,
    params,
  );
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`listChatMessagesForDay ${pageId} ${day}: ${resp.status}`);
  }
  return resp.json();
}

export async function listChatMessageCounts(
  pageId: string,
  month: string,
): Promise<ChatMessageCountsResponse> {
  const url = authedUrl(
    `/api/whop/pages/${encodeURIComponent(pageId)}/chat-message-counts`,
    { month },
  );
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`listChatMessageCounts ${pageId} ${month}: ${resp.status}`);
  }
  return resp.json();
}
```

保留 `patchWatchedSenders` 不变。

#### - [ ] Step 2: typecheck

```bash
cd frontend && npm run typecheck 2>&1 | tail -30
```

预期：`api/chat.ts` 本身不报错；`stores/chatStore.ts` 仍然报错（用旧 `listChatMessages`、`.week` 字段）— 下一 Task 修。

#### - [ ] Step 3: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/api/chat.ts
git commit -m "refactor(api/chat): day-based listChatMessagesForDay + listChatMessageCounts"
```

---

### Task 8: 重塑 `chatStore`

**Files:**
- Modify: `frontend/src/stores/chatStore.ts`
- Create: `frontend/src/stores/chatStore.test.ts`

#### - [ ] Step 1: 写失败测试

新建 `frontend/src/stores/chatStore.test.ts`：

```ts
import { describe, expect, it, beforeEach, vi } from "vitest";
import { useChatStore } from "./chatStore";
import * as chatApi from "../api/chat";

function resetStore() {
  useChatStore.setState({ caches: {}, counts: {} });
}

describe("chatStore", () => {
  beforeEach(() => {
    resetStore();
    vi.restoreAllMocks();
  });

  it("fetchDay populates caches[pid|day]", async () => {
    vi.spyOn(chatApi, "listChatMessagesForDay").mockResolvedValue({
      messages: [
        { id: "m1", page_id: "p1", author: "alice", content: "hi",
          posted_at: "2026-05-23T01:00:00Z", quoted: null, image_url: null },
      ] as any,
      authors: [{ name: "alice", count: 1 }],
      day: { start: "2026-05-22T16:00:00Z", end: "2026-05-23T16:00:00Z" },
    });

    await useChatStore.getState().fetchDay("p1", "2026-05-23", []);
    const cache = useChatStore.getState().caches["p1|2026-05-23"];
    expect(cache).toBeDefined();
    expect(cache.messages).toHaveLength(1);
    expect(cache.authors[0].name).toBe("alice");
  });

  it("fetchCounts populates counts[pid|month] and excludes zero days", async () => {
    vi.spyOn(chatApi, "listChatMessageCounts").mockResolvedValue({
      month: "2026-05",
      counts: { "2026-05-22": 14, "2026-05-23": 3 },
    });

    await useChatStore.getState().fetchCounts("p1", "2026-05");
    const c = useChatStore.getState().counts["p1|2026-05"];
    expect(c.counts["2026-05-22"]).toBe(14);
    expect(c.counts["2026-05-21"]).toBeUndefined();
  });

  it("applyStoredMessage appends + dedupes within a cached day", () => {
    useChatStore.setState({
      caches: {
        "p1|2026-05-23": {
          messages: [
            { id: "m1", page_id: "p1", author: "a", content: "x",
              posted_at: "2026-05-23T01:00:00Z", quoted: null, image_url: null } as any,
          ],
          authors: [],
          day: { start: "2026-05-22T16:00:00Z", end: "2026-05-23T16:00:00Z" },
          fetchedAt: 0,
        },
      },
      counts: {},
    });

    const newMsg = {
      id: "m2", page_id: "p1", author: "a", content: "y",
      posted_at: "2026-05-23T02:00:00Z", quoted: null, image_url: null,
    } as any;
    useChatStore.getState().applyStoredMessage("p1", "2026-05-23", newMsg);
    useChatStore.getState().applyStoredMessage("p1", "2026-05-23", newMsg);  // dedupe

    expect(useChatStore.getState().caches["p1|2026-05-23"].messages.map(m => m.id))
      .toEqual(["m1", "m2"]);
  });

  it("applyStoredMessage drops update for uncached day", () => {
    const newMsg = {
      id: "m1", page_id: "p1", author: "a", content: "x",
      posted_at: "2026-05-23T01:00:00Z", quoted: null, image_url: null,
    } as any;
    useChatStore.getState().applyStoredMessage("p1", "2026-05-23", newMsg);
    expect(useChatStore.getState().caches["p1|2026-05-23"]).toBeUndefined();
  });

  it("fetchDay dedupes in-flight requests for the same (pid, day)", async () => {
    const spy = vi.spyOn(chatApi, "listChatMessagesForDay").mockImplementation(
      () => new Promise((resolve) => setTimeout(() => resolve({
        messages: [], authors: [],
        day: { start: "", end: "" },
      }), 10)),
    );

    const fetchDay = useChatStore.getState().fetchDay;
    await Promise.all([
      fetchDay("p1", "2026-05-23", []),
      fetchDay("p1", "2026-05-23", []),
    ]);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
```

#### - [ ] Step 2: 跑测试确认失败

```bash
cd frontend && npm test -- src/stores/chatStore.test.ts
```

预期：旧 `chatStore` 没有 `fetchDay` / `fetchCounts` / `counts`，全部失败。

#### - [ ] Step 3: 重写 chatStore

把 `frontend/src/stores/chatStore.ts` 整体替换为：

```ts
import { create } from "zustand";
import {
  listChatMessagesForDay,
  listChatMessageCounts,
  type ChatMessagesResponse,
  type ChatMessageCountsResponse,
} from "../api/chat";
import type { ChatMessageOut } from "../components/Chat/chatCards";

/** Cached slice for a single ``(page_id, day)`` pair (day = Beijing YYYY-MM-DD). */
interface ChatDayCache {
  messages: ChatMessageOut[];
  authors: { name: string; count: number }[];
  day: { start: string; end: string };
  fetchedAt: number;
}

/** Cached per-day message counts for one Beijing calendar month. */
interface ChatMonthCounts {
  month: string;
  counts: Record<string, number>;  // dayKey -> count, omits zero-days
  fetchedAt: number;
}

interface ChatStore {
  /** Keyed by ``${pageId}|${day}``. */
  caches: Record<string, ChatDayCache>;
  /** Keyed by ``${pageId}|${month}`` (month = YYYY-MM Beijing). */
  counts: Record<string, ChatMonthCounts>;

  fetchDay: (pageId: string, day: string, senders: string[]) => Promise<void>;
  fetchCounts: (pageId: string, month: string) => Promise<void>;

  /** WS-triggered insert. Drops the update if no cache entry exists for
   *  ``(pageId, day)`` (we'd be staging a fragment for a slice the user
   *  never opened) or if the message id is already present (dedupe). */
  applyStoredMessage: (
    pageId: string,
    day: string,
    message: ChatMessageOut,
  ) => void;
}

const dayKey = (pageId: string, day: string): string => `${pageId}|${day}`;
const monthKey = (pageId: string, month: string): string => `${pageId}|${month}`;

// In-flight request dedupe — concurrent fetchDay/fetchCounts for the same
// key share a single promise so the page-mount + selectedDate-effect race
// doesn't double-fetch today's slice.
const inflightDays = new Map<string, Promise<void>>();
const inflightCounts = new Map<string, Promise<void>>();

export const useChatStore = create<ChatStore>((set, get) => ({
  caches: {},
  counts: {},

  fetchDay: async (pageId, day, senders) => {
    const k = dayKey(pageId, day);
    const existing = inflightDays.get(k);
    if (existing) return existing;
    const p = (async () => {
      try {
        const r: ChatMessagesResponse = await listChatMessagesForDay(
          pageId, day, senders,
        );
        set((state) => ({
          caches: {
            ...state.caches,
            [k]: {
              messages: r.messages,
              authors: r.authors,
              day: r.day,
              fetchedAt: Date.now(),
            },
          },
        }));
      } finally {
        inflightDays.delete(k);
      }
    })();
    inflightDays.set(k, p);
    return p;
  },

  fetchCounts: async (pageId, month) => {
    const k = monthKey(pageId, month);
    const existing = inflightCounts.get(k);
    if (existing) return existing;
    const p = (async () => {
      try {
        const r: ChatMessageCountsResponse = await listChatMessageCounts(
          pageId, month,
        );
        set((state) => ({
          counts: {
            ...state.counts,
            [k]: { month: r.month, counts: r.counts, fetchedAt: Date.now() },
          },
        }));
      } finally {
        inflightCounts.delete(k);
      }
    })();
    inflightCounts.set(k, p);
    return p;
  },

  applyStoredMessage: (pageId, day, message) => {
    const k = dayKey(pageId, day);
    const existing = get().caches[k];
    if (!existing) return;
    if (existing.messages.some((m) => m.id === message.id)) return;
    const next = [...existing.messages, message].sort((a, b) =>
      a.posted_at.localeCompare(b.posted_at),
    );
    set((state) => ({
      caches: { ...state.caches, [k]: { ...existing, messages: next } },
    }));
  },
}));
```

#### - [ ] Step 4: 跑测试确认通过

```bash
cd frontend && npm test -- src/stores/chatStore.test.ts
```

预期：5 条全部 PASS。

#### - [ ] Step 5: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/stores/chatStore.ts frontend/src/stores/chatStore.test.ts
git commit -m "refactor(chatStore): day-keyed cache + month counts; in-flight dedupe"
```

---

### Task 9: `ChatBoardPanel` 重接线

**Files:**
- Modify: `frontend/src/components/Chat/ChatBoardPanel.tsx`

#### - [ ] Step 1: 替换 imports + state + 加载逻辑

按以下顺序在 `ChatBoardPanel.tsx` 内做替换。

**1a.** 顶部的 `import` 块（约第 15-22 行）：

```tsx
import {
  dayKeyOf,
  isoWeekBounds,
  isoWeekOfDay,
  monthOf,
  todayInShanghai,
  weeksCoveringMonth,
} from "../Dashboard/weekUtils";
```

改成：

```tsx
import {
  addDays,
  dayKeyOf,
  isoWeekBounds,
  isoWeekOfDay,
  monthOf,
  todayInShanghai,
} from "../Dashboard/weekUtils";
```

（移除 `weeksCoveringMonth`，新增 `addDays`。`dayKeyOf` 仍保留 —— 后面 `dayFilteredChildTasks` 还用它过滤 child tasks。）

**1b.** 在 `useState(...)` 之后，把（第 61-66 行）：

```tsx
const selectedWeek = isoWeekOfDay(selectedDate);
const today = todayInShanghai();

const cache = useChatStore((s) => s.caches[`${page.id}|${selectedWeek}`]);
const fetch = useChatStore((s) => s.fetch);
const allCaches = useChatStore((s) => s.caches);
```

替换为：

```tsx
const today = todayInShanghai();

const cache = useChatStore((s) => s.caches[`${page.id}|${selectedDate}`]);
const allCaches = useChatStore((s) => s.caches);
const allCounts = useChatStore((s) => s.counts);
const fetchDay = useChatStore((s) => s.fetchDay);
const fetchCounts = useChatStore((s) => s.fetchCounts);
```

**1c.** 替换两个加载 `useEffect`。把（第 87-92 行）：

```tsx
useEffect(() => {
  fetch(page.id, selectedWeek, []);
}, [page.id, selectedWeek, fetch]);
```

替换为：

```tsx
// 进入 page：并行拉「今天」+「昨天」+ 当月计数。
useEffect(() => {
  const t = todayInShanghai();
  const y = addDays(t, -1);
  fetchDay(page.id, t, []);
  fetchDay(page.id, y, []);
  fetchCounts(page.id, monthOf(t));
}, [page.id, fetchDay, fetchCounts]);

// selectedDate 变化：缺缓存就拉那一天；跨月就拉那月 counts。
useEffect(() => {
  const dayKey = `${page.id}|${selectedDate}`;
  if (!allCaches[dayKey]) fetchDay(page.id, selectedDate, []);
  const m = monthOf(selectedDate);
  const monthKey = `${page.id}|${m}`;
  if (!allCounts[monthKey]) fetchCounts(page.id, m);
  // 这两个 effect 在 page.id 变化的 mount 瞬间会同时调 fetchDay(today)；
  // chatStore 内部 in-flight dedupe 保证只发一次。
}, [page.id, selectedDate, allCaches, allCounts, fetchDay, fetchCounts]);
```

**1d.** 把子任务 fetch 那段（第 115-139 行）里的 `selectedWeek` 引用改成 `isoWeekOfDay(selectedDate)`：

```tsx
const { start, end } = isoWeekBounds(isoWeekOfDay(selectedDate));
```

依赖数组从 `[page.id, selectedWeek]` 改成 `[page.id, selectedDate]`。

（子任务还是用周窗口拉是合理的 —— 它来自 `useTasksStore`，与 chat 解耦；保留不动。）

#### - [ ] Step 2: 简化消息派生 — 删除客户端日过滤

把（第 150-160 行）：

```tsx
const rawMessages = cache?.messages ?? [];
const authors = cache?.authors ?? [];

const messages = useMemo(
  () => rawMessages.filter((m) => dayKeyOf(m.posted_at) === selectedDate),
  [rawMessages, selectedDate],
);
```

替换为：

```tsx
// 后端按北京日切片，cache 里的 messages 已经是当天的；不再做客户端过滤。
const messages = cache?.messages ?? [];
```

`dayFilteredChildTasks` 那段保留不动（child tasks 用 `useTasksStore`，按 day 在客户端过滤，仍依赖 `dayKeyOf`）。

#### - [ ] Step 3: 作者 chip bar 形状 — 聚合已缓存所有天

替换 `dayScopedAuthors` 整段（约第 174-189 行）以及 `authorsWithMonitors` 中复用它的部分，新逻辑如下：

把现在的：

```tsx
const dayScopedAuthors = useMemo(() => {
  const dayCounts = new Map<string, number>();
  for (const m of messages) {
    dayCounts.set(m.author, (dayCounts.get(m.author) ?? 0) + 1);
  }
  const seen = new Set<string>();
  const out: { name: string; count: number }[] = [];
  for (const a of authors) {
    out.push({ name: a.name, count: dayCounts.get(a.name) ?? 0 });
    seen.add(a.name);
  }
  for (const [name, count] of dayCounts) {
    if (!seen.has(name)) out.push({ name, count });
  }
  return out;
}, [messages, authors]);
```

替换为：

```tsx
/** chip 列表「形状」基于本 page 下所有已缓存天的作者并集；优先把当天的
 *  作者排在最前，保持视觉上「今天看到的人」在前。 */
const allAuthorsForPage = useMemo(() => {
  const order: string[] = [];
  const seen = new Set<string>();
  const prefix = `${page.id}|`;
  // 先放当天的
  const todayCache = allCaches[`${page.id}|${selectedDate}`];
  if (todayCache) {
    for (const a of todayCache.authors) {
      if (!seen.has(a.name)) { order.push(a.name); seen.add(a.name); }
    }
  }
  // 再补其它已缓存天的
  for (const key of Object.keys(allCaches)) {
    if (!key.startsWith(prefix)) continue;
    if (key === `${page.id}|${selectedDate}`) continue;
    for (const a of allCaches[key].authors) {
      if (!seen.has(a.name)) { order.push(a.name); seen.add(a.name); }
    }
  }
  return order;
}, [allCaches, page.id, selectedDate]);

/** 当天的作者计数（用于 chip 上的 badge）。 */
const dayCountsByAuthor = useMemo(() => {
  const m = new Map<string, number>();
  for (const msg of messages) m.set(msg.author, (m.get(msg.author) ?? 0) + 1);
  return m;
}, [messages]);

const dayScopedAuthors = useMemo(
  () => allAuthorsForPage.map((name) => ({
    name, count: dayCountsByAuthor.get(name) ?? 0,
  })),
  [allAuthorsForPage, dayCountsByAuthor],
);
```

注意：`authors` 这个变量在原代码中也用到了别的地方（`const authors = cache?.authors ?? []`）—— 上面 Step 2 中保留 `cache?.authors` 仅供调试输入；我们直接删掉它，让 `dayScopedAuthors` 从新逻辑里来：

把原 Step 2 替换后的：

```tsx
const messages = cache?.messages ?? [];
```

**前面那行** `const authors = cache?.authors ?? [];` 也一并删除。

#### - [ ] Step 4: `hasMessagesOnDay` 改读 counts

替换（第 279-287 行）：

```tsx
const hasMessagesOnDay = useCallback(
  (dayKey: string) => {
    const week = isoWeekOfDay(dayKey);
    const c = allCaches[`${page.id}|${week}`];
    if (!c) return false;
    return c.messages.some((m) => dayKeyOf(m.posted_at) === dayKey);
  },
  [allCaches, page.id],
);
```

替换为：

```tsx
const hasMessagesOnDay = useCallback(
  (d: string) => {
    const c = allCounts[`${page.id}|${monthOf(d)}`];
    return c ? (c.counts[d] ?? 0) > 0 : false;
  },
  [allCounts, page.id],
);
```

#### - [ ] Step 5: 删除整月预取循环 + 重写 `prefetching`

替换（第 261-277 行）：

```tsx
const [calendarOpen, setCalendarOpen] = useState(false);
const [calendarMonth, setCalendarMonth] = useState<string>(monthOf(selectedDate));

useEffect(() => {
  if (!calendarOpen) return;
  for (const w of weeksCoveringMonth(calendarMonth)) {
    const key = `${page.id}|${w}`;
    if (!allCaches[key]) fetch(page.id, w, []);
  }
}, [calendarOpen, calendarMonth, page.id, fetch, allCaches]);

const prefetching = useMemo(() => {
  if (!calendarOpen) return false;
  return weeksCoveringMonth(calendarMonth).some(
    (w) => !allCaches[`${page.id}|${w}`],
  );
}, [calendarOpen, calendarMonth, page.id, allCaches]);
```

替换为：

```tsx
const [calendarOpen, setCalendarOpen] = useState(false);
const [calendarMonth, setCalendarMonth] = useState<string>(monthOf(selectedDate));

// 翻月时按需拉那月 counts。
useEffect(() => {
  if (!calendarOpen) return;
  const k = `${page.id}|${calendarMonth}`;
  if (!allCounts[k]) fetchCounts(page.id, calendarMonth);
}, [calendarOpen, calendarMonth, page.id, fetchCounts, allCounts]);

const prefetching = useMemo(() => {
  if (!calendarOpen) return false;
  return !allCounts[`${page.id}|${calendarMonth}`];
}, [calendarOpen, calendarMonth, page.id, allCounts]);
```

#### - [ ] Step 6: typecheck

```bash
cd frontend && npm run typecheck 2>&1 | tail -20
```

预期：`ChatBoardPanel.tsx` 不再报错；`App.tsx` 仍会因为 WS 分支用了旧 store API 报错 — 下一 Task 修。

#### - [ ] Step 7: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/components/Chat/ChatBoardPanel.tsx
git commit -m "refactor(chat-panel): day-based lazy loading + counts-driven dots"
```

---

### Task 10: WS 处理器（`App.tsx`）

**Files:**
- Modify: `frontend/src/App.tsx:208-225`

#### - [ ] Step 1: 替换 `chat.message_stored` 分支

把 `frontend/src/App.tsx:208-225`：

```tsx
} else if (evt.type === "chat.message_stored") {
  // WS payload is just ``{page_id, message_id}`` (see
  // backend/app/api/ws.py:_payload_to_dict). Re-fetch every cached
  // ``(page_id, week)`` slice for that page so the new message is
  // pulled in via the chat-messages endpoint — applyStoredMessage
  // would need the full row we don't have here. Fire-and-forget;
  // errors are not user-facing (mirrors other WS branches).
  const p = evt.payload as { page_id?: string; message_id?: number };
  if (p?.page_id) {
    const caches = useChatStore.getState().caches;
    const prefix = `${p.page_id}|`;
    for (const key of Object.keys(caches)) {
      if (key.startsWith(prefix)) {
        const week = key.slice(prefix.length);
        void useChatStore.getState().fetch(p.page_id, week, []);
      }
    }
  }
}
```

替换为：

```tsx
} else if (evt.type === "chat.message_stored") {
  // WS payload is ``{page_id, message_id}`` only — we don't have the
  // posted_at, so we can't route the update by day. Assume the event
  // is for "now" (the scraper publishes events as messages arrive,
  // see backend/app/whop/chat_writer.py), and refresh only the
  // current Beijing-day slice + current-month counts for that page,
  // if either is already cached. Fire-and-forget.
  const p = evt.payload as { page_id?: string; message_id?: number };
  if (p?.page_id) {
    const today = todayInShanghai();
    const month = monthOf(today);
    const store = useChatStore.getState();
    if (store.caches[`${p.page_id}|${today}`]) {
      void store.fetchDay(p.page_id, today, []);
    }
    if (store.counts[`${p.page_id}|${month}`]) {
      void store.fetchCounts(p.page_id, month);
    }
  }
}
```

确保 `App.tsx` 顶部 import 包含 `todayInShanghai` 和 `monthOf`：

```bash
grep -n "todayInShanghai\|monthOf" frontend/src/App.tsx
```

如缺则在 imports 处补：

```tsx
import { monthOf, todayInShanghai } from "./components/Dashboard/weekUtils";
```

#### - [ ] Step 2: typecheck

```bash
cd frontend && npm run typecheck
```

预期：无错。

#### - [ ] Step 3: 跑完整前端单测

```bash
cd frontend && npm test 2>&1 | tail -30
```

预期：所有 vitest 用例通过（含 chatStore.test.ts）。

#### - [ ] Step 4: 提交

```bash
cd /Users/tianpengxuan/Documents/signal-station
git add frontend/src/App.tsx
git commit -m "refactor(ws): chat.message_stored refreshes today + month counts only"
```

---

### Task 11: 手动冒烟验证

**Files:** （无代码改动）

#### - [ ] Step 1: 启服务

```bash
cd /Users/tianpengxuan/Documents/signal-station && make dev
```

等到日志显示 `frontend ready` 且 `backend Application startup complete`，浏览器打开 http://localhost:5173 并登录。

#### - [ ] Step 2: 打开 DevTools Network 面板，进入一个讨论区（chat-source page）

预期初始网络请求：
- 2 个 `/api/whop/pages/<id>/chat-messages?day=<today>` 和 `?day=<yesterday>`（并发）
- 1 个 `/api/whop/pages/<id>/chat-message-counts?month=<YYYY-MM>`
- **不应再有 `?week=` 请求**

#### - [ ] Step 3: 选一个更早的日期（DayPicker 中点击或左箭头多次）

切到一个未缓存的日期时：
- 预期：1 个 `?day=<that-day>` 请求
- 同月内来回切：之前看过的天再切回去**不**发新请求
- 跨月切：补 1 个 `?month=<that-month>` 计数请求

#### - [ ] Step 4: 打开日历翻到上个月

预期：1 个新 `?month=` 请求；**不再有整月多周 `?week=` 预取**。
日历上有消息的天显示圆点（来自新 counts）。

#### - [ ] Step 5: 实时验证 — 触发一条新 chat 消息（手动让 chat scraper 抓到一条，或在 DB 里 INSERT 一条带当前时间戳的消息走 WS 通道）

预期：
- 1 个 `?day=<today>` 请求（刷新今天视图）
- 1 个 `?month=<this-month>` 请求（刷新圆点）
- **不应** refetch 其它已缓存的天

如果你没法触发真实新消息，跳过此步并在 PR 描述里标 "WS 路径未实测"。

#### - [ ] Step 6: 切到另一个讨论区 page

预期：新 page 重新触发「今天 + 昨天 + 当月 counts」三个请求；切回原 page 命中缓存不再请求。

#### - [ ] Step 7: 关停服务

`Ctrl+C` 停 `make dev`。

---

## 自检清单

- [ ] `cd backend && uv run pytest -v` 全绿
- [ ] `cd frontend && npm test` 全绿
- [ ] `cd frontend && npm run typecheck` 无错
- [ ] `cd backend && uv run mypy app` 无错
- [ ] `git log --oneline` 至少 10 个分步 commit（每 Task 一个）
- [ ] 网络面板冒烟 Step 2-6 全部对得上预期

完成后可创建 PR 或合并到 main。
