# 正股 / 期权交易信号卡嵌入聊天列表 · 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 chat 父页能挂载 stock/option 子监听；子页产生的 task 信号以 SignalCard bubble 形式嵌入到 chat 板的消息流里；chat 页设置弹窗里新增"挂载监听"区块管理子页生命周期。

**Architecture:** `WhopPageEntry` 增 `parent_chat_id`（JSON 持久化字段，无 DB 迁移）。子页对后端 listener/parser/trader 链路无差异；父子关系仅在 REST query 与前端渲染时使用。前端 `ChatBoardPanel` 合流 chat_messages 与 child tasks 成统一 timeline，按 filter / highlight 双模式渲染；filter 把所有 stock 信号聚合到一张卡、所有 option 信号到另一张卡；highlight 渲染单条扁平流。

**Tech Stack:** Python 3.11 + FastAPI + pydantic + SQLAlchemy（后端，但本期不动 DB schema） · React 18 + TypeScript strict + Zustand + vitest（前端） · pytest（后端测试） · Playwright async（whop 抓取，本期不改）

**Spec reference:** `docs/superpowers/specs/2026-05-20-stock-option-chat-cards-design.md`
**Visual reference:** `.design/signal-cards-in-chat.html` · `.design/chat-settings-monitors.html`

---

## File Map

### 后端 — 修改

- `backend/app/whop/registry.py` — `WhopPageEntry` 加 `parent_chat_id`；`add_page` 增参数 + 校验；`remove_page` 加 children 级联；`list_pages` 接受 parent 过滤。
- `backend/app/api/schemas.py` — `WhopPageOut` 暴露 `parent_chat_id`；`WhopPageCreate` 接受可选 `parent_chat_id`。
- `backend/app/api/http.py` — `GET /api/whop/pages` 加 `parent_chat_id` query；`POST /api/whop/pages` 透传；`GET /api/tasks` 加 `urls[]` + `week_start` + `week_end`。
- `backend/app/storage/repo.py` — `list_tasks` 增 `urls` 和 `posted_at_start / end` 过滤参数。

### 后端 — 测试

- `backend/tests/whop/test_registry_parent_chat.py` — 新建。
- `backend/tests/api/test_whop_pages_parent.py` — 新建。
- `backend/tests/api/test_tasks_filter.py` — 新建（或扩 existing tasks 测试文件）。

### 前端 — 修改

- `frontend/src/api/domain-types.ts` — `WhopPage` 加 `parent_chat_id?: string | null`。
- `frontend/src/api/http.ts` — `listTasks` 接受 `urls / week_start / week_end`；`listWhopPages` 接受 `parentChatId`；`addWhopPage` 接受 `parent_chat_id`。
- `frontend/src/App.tsx` — WS handler 路由 `whop.page_changed` 到 pageTabs 或 childPages store。
- `frontend/src/components/Chat/ChatBoardPanel.tsx` — 合流 + filter / highlight 双模式渲染。
- `frontend/src/components/Chat/ChatSenderBar.tsx` — 监听 chip 加 source dot 前缀。
- `frontend/src/components/Dashboard/PageSettingsModal.tsx` — 加 `<AttachedMonitorsSection>`。

### 前端 — 新建

- `frontend/src/stores/childPages.ts` — `useChildPagesStore`（child WhopPage[] by parent id）。
- `frontend/src/components/Chat/chatTimeline.ts` — 合流 + 模式分流的纯函数。
- `frontend/src/components/Chat/SignalCard.tsx` — 信号卡组件（折叠 + 展开）。
- `frontend/src/components/Chat/SignalCard.css`
- `frontend/src/components/Chat/signalCardHelpers.ts` — status → layer 描述符。
- `frontend/src/components/Chat/StreamView.tsx` — highlight 模式扁平流。
- `frontend/src/components/common/TickerWhitelistEditor.tsx` — 从 `PageWhitelistBar` 抽出。
- `frontend/src/components/common/OptionQuantityEditor.tsx` — 从 `PageSettingsModal` 抽出。
- `frontend/src/components/Dashboard/AttachedMonitorsSection.tsx` — 挂载监听区块。

### 前端 — 测试（vitest）

- `frontend/src/components/Chat/chatTimeline.test.ts`
- `frontend/src/components/Chat/SignalCard.test.tsx`
- `frontend/src/components/Chat/signalCardHelpers.test.ts`
- `frontend/src/components/Chat/StreamView.test.tsx`
- `frontend/src/components/Dashboard/AttachedMonitorsSection.test.tsx`

---

## Task 1: WhopPageEntry · parent_chat_id 字段 + 序列化

**Files:**
- Modify: `backend/app/whop/registry.py:66-106`
- Test: `backend/tests/whop/test_registry_parent_chat.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/whop/test_registry_parent_chat.py`:

```python
"""Tests for WhopPageEntry.parent_chat_id serialization."""
from datetime import UTC, datetime

from app.whop.registry import WhopPageEntry
from app.whop.settings import default_settings_for


def test_to_dict_includes_parent_chat_id_when_set():
    entry = WhopPageEntry(
        id="abc123",
        url="https://whop.com/c/foo",
        source="stock",
        name="TSLL 监听",
        added_at=datetime(2026, 5, 20, tzinfo=UTC),
        settings=default_settings_for("stock"),
        parent_chat_id="parent_xyz",
    )
    d = entry.to_dict()
    assert d["parent_chat_id"] == "parent_xyz"


def test_to_dict_emits_none_when_unset():
    entry = WhopPageEntry(
        id="abc123",
        url="https://whop.com/c/foo",
        source="stock",
        name="TSLL 监听",
        added_at=datetime(2026, 5, 20, tzinfo=UTC),
        settings=default_settings_for("stock"),
    )
    d = entry.to_dict()
    assert d["parent_chat_id"] is None


def test_from_dict_legacy_missing_field_defaults_to_none():
    legacy = {
        "id": "abc123",
        "url": "https://whop.com/c/foo",
        "source": "stock",
        "name": "TSLL 监听",
        "added_at": "2026-05-20T00:00:00+00:00",
        "settings": {"dedupe_processed_messages": True},
    }
    entry = WhopPageEntry.from_dict(legacy)
    assert entry.parent_chat_id is None


def test_from_dict_roundtrip_preserves_parent_chat_id():
    src = WhopPageEntry(
        id="abc123",
        url="https://whop.com/c/foo",
        source="stock",
        name="TSLL 监听",
        added_at=datetime(2026, 5, 20, tzinfo=UTC),
        settings=default_settings_for("stock"),
        parent_chat_id="parent_xyz",
    )
    dst = WhopPageEntry.from_dict(src.to_dict())
    assert dst.parent_chat_id == "parent_xyz"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v
```
Expected: FAIL — `WhopPageEntry.__init__() got an unexpected keyword argument 'parent_chat_id'`.

- [ ] **Step 3: Add the field + serialization**

Modify `backend/app/whop/registry.py`:

```python
@dataclass
class WhopPageEntry:
    id: str
    url: str
    source: str  # "stock" | "option" | "chat"
    name: str
    added_at: datetime
    settings: PageSettings = field(default_factory=lambda: default_settings_for("stock"))
    parent_chat_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "source": self.source,
            "name": self.name,
            "added_at": self.added_at.isoformat(),
            "settings": page_settings_to_dict(self.settings),
            "parent_chat_id": self.parent_chat_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WhopPageEntry:
        source = cast(_SourceLiteral, d["source"])
        settings_raw = d.get("settings")
        if settings_raw is None:
            settings = default_settings_for(source)
        else:
            settings = page_settings_from_dict(settings_raw, source=source)
        return cls(
            id=d["id"],
            url=d["url"],
            source=source,
            name=d.get("name") or d["url"],
            added_at=datetime.fromisoformat(d["added_at"]),
            settings=settings,
            parent_chat_id=d.get("parent_chat_id"),
        )
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Run full backend suite (smoke)**

```bash
cd backend && uv run pytest -x -q
```
Expected: ≥ 338 passed (current baseline). Legacy fixtures without `parent_chat_id` should still load.

- [ ] **Step 6: Commit**

```bash
git add backend/app/whop/registry.py backend/tests/whop/test_registry_parent_chat.py
git commit -m "feat(whop): add WhopPageEntry.parent_chat_id with backward-compat serialization"
```

---

## Task 2: WhopRegistry.add_page · parent_chat_id 校验

**Files:**
- Modify: `backend/app/whop/registry.py:189-226`
- Test: `backend/tests/whop/test_registry_parent_chat.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/whop/test_registry_parent_chat.py`:

```python
import pytest
from app.core.event_bus import EventBus
from app.core.config import Settings
from app.whop.registry import WhopRegistry


@pytest.fixture
def registry(tmp_path) -> WhopRegistry:
    return WhopRegistry(
        bus=EventBus(),
        settings=Settings(_env_file=None),
        pages_file=tmp_path / "pages.json",
    )


@pytest.mark.asyncio
async def test_add_page_with_valid_parent(registry):
    parent = await registry.add_page(
        url="https://whop.com/c/chat-1", source="chat", name="alpha-room"
    )
    child = await registry.add_page(
        url="https://whop.com/c/stock-1",
        source="stock",
        name="TSLL 监听",
        parent_chat_id=parent.id,
    )
    assert child.parent_chat_id == parent.id


@pytest.mark.asyncio
async def test_add_page_rejects_parent_not_found(registry):
    with pytest.raises(ValueError, match="parent_chat_id"):
        await registry.add_page(
            url="https://whop.com/c/stock-1",
            source="stock",
            name="TSLL",
            parent_chat_id="nonexistent",
        )


@pytest.mark.asyncio
async def test_add_page_rejects_non_chat_parent(registry):
    parent = await registry.add_page(
        url="https://whop.com/c/stock-parent", source="stock", name="Standalone TSLL"
    )
    with pytest.raises(ValueError, match="parent must be source=chat"):
        await registry.add_page(
            url="https://whop.com/c/stock-1",
            source="stock",
            name="TSLL",
            parent_chat_id=parent.id,
        )


@pytest.mark.asyncio
async def test_add_page_rejects_nested_sub(registry):
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    sub = await registry.add_page(
        url="https://whop.com/c/stock-1", source="stock", name="s", parent_chat_id=chat.id
    )
    with pytest.raises(ValueError, match="cannot nest"):
        await registry.add_page(
            url="https://whop.com/c/stock-2",
            source="stock",
            name="s2",
            parent_chat_id=sub.id,
        )


@pytest.mark.asyncio
async def test_add_page_rejects_chat_as_sub(registry):
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    with pytest.raises(ValueError, match="sub-monitor source must be stock or option"):
        await registry.add_page(
            url="https://whop.com/c/chat-2",
            source="chat",
            name="c2",
            parent_chat_id=chat.id,
        )
```

- [ ] **Step 2: Run failing**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v -k "test_add_page"
```
Expected: 5 FAILs — `add_page` doesn't accept `parent_chat_id`.

- [ ] **Step 3: Implement add_page validation**

Modify `add_page` signature + body in `backend/app/whop/registry.py`:

```python
async def add_page(
    self,
    *,
    url: str,
    source: str,
    name: str | None = None,
    parent_chat_id: str | None = None,
) -> WhopPageEntry:
    if source not in ("stock", "option", "chat"):
        raise ValueError(f"source must be stock|option|chat, got {source!r}")
    if not url or _is_placeholder_url(url):
        raise ValueError(f"invalid or placeholder URL: {url!r}")

    if parent_chat_id is not None:
        parent = self._entries.get(parent_chat_id)
        if parent is None:
            raise ValueError(f"parent_chat_id {parent_chat_id!r} not found")
        if parent.source != "chat":
            raise ValueError("parent must be source=chat")
        if parent.parent_chat_id is not None:
            raise ValueError("cannot nest sub-monitors (parent is itself a sub)")
        if source == "chat":
            raise ValueError("sub-monitor source must be stock or option")

    async with self._lock:
        new_canon = _canonicalize_url(url)
        for existing in self._entries.values():
            if _canonicalize_url(existing.url) == new_canon:
                raise ValueError(f"URL already monitored (id={existing.id})")

        entry = WhopPageEntry(
            id=uuid.uuid4().hex[:12],
            url=url,
            source=source,
            name=(name or url),
            added_at=datetime.now(UTC),
            settings=default_settings_for(cast(_SourceLiteral, source)),
            parent_chat_id=parent_chat_id,
        )
        self._entries[entry.id] = entry
        self._save_entries()
        self._rebuild_url_index()
        page_dict = self._build_page_dict(entry)
    await self._publish_page_event("added", page_dict)
    return entry
```

> Note: parent lookup happens BEFORE the lock to avoid recursive lock acquisition. The race is benign — the worst case is "parent deleted between check and insert"; the resulting orphan is just a top-level page (parent_chat_id pointing to nothing, will be cleaned on next reload via the strict-mode add_page already filtering live).

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v
```
Expected: all passed.

- [ ] **Step 5: Run full suite**

```bash
cd backend && uv run pytest -x -q
```
Expected: still green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/whop/registry.py backend/tests/whop/test_registry_parent_chat.py
git commit -m "feat(whop): validate parent_chat_id on add_page (must be chat, no nesting)"
```

---

## Task 3: WhopRegistry.remove_page · 子页级联归零

**Files:**
- Modify: `backend/app/whop/registry.py:228-244`
- Test: `backend/tests/whop/test_registry_parent_chat.py` (append)

- [ ] **Step 1: Write failing test**

Append:

```python
@pytest.mark.asyncio
async def test_remove_chat_parent_orphans_children(registry):
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    a = await registry.add_page(
        url="https://whop.com/c/stock-a", source="stock", name="A", parent_chat_id=chat.id
    )
    b = await registry.add_page(
        url="https://whop.com/c/option-b", source="option", name="B", parent_chat_id=chat.id
    )
    ok = await registry.remove_page(chat.id)
    assert ok is True

    # Both children survive, parent_chat_id cleared.
    survivors = {e.id: e for e, _ in registry.list_pages()}
    assert chat.id not in survivors
    assert a.id in survivors and survivors[a.id].parent_chat_id is None
    assert b.id in survivors and survivors[b.id].parent_chat_id is None


@pytest.mark.asyncio
async def test_remove_chat_parent_persists_orphaning(registry, tmp_path):
    """After remove, restart from disk must see the children as top-level."""
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    await registry.add_page(
        url="https://whop.com/c/stock-a", source="stock", name="A", parent_chat_id=chat.id
    )
    await registry.remove_page(chat.id)

    fresh = WhopRegistry(
        bus=EventBus(),
        settings=Settings(_env_file=None),
        pages_file=tmp_path / "pages.json",
    )
    await fresh.load_entries()
    [(survivor, _)] = fresh.list_pages()
    assert survivor.parent_chat_id is None
```

- [ ] **Step 2: Run failing**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v -k "remove"
```
Expected: 2 FAILs — children currently keep dangling parent_chat_id.

- [ ] **Step 3: Implement cascade**

Replace `remove_page` body in `registry.py`:

```python
async def remove_page(self, page_id: str) -> bool:
    """Stop listener + remove entry + persist. Cascades children: any sub-
    monitors whose parent_chat_id == page_id have it cleared, surviving as
    top-level entries (their listeners continue running, no data loss)."""
    orphaned_dicts: list[dict[str, Any]] = []
    async with self._lock:
        entry = self._entries.pop(page_id, None)
        if entry is None:
            return False
        listener = self._listeners.pop(page_id, None)
        if listener is not None:
            try:
                await listener.stop()
            except Exception as e:  # noqa: BLE001
                logger.warning("error stopping removed listener: %s", e)

        # Cascade: children of a chat parent become independent top-level pages.
        for child in self._entries.values():
            if child.parent_chat_id == page_id:
                child.parent_chat_id = None
                orphaned_dicts.append(self._build_page_dict(child))

        self._save_entries()
        self._rebuild_url_index()
        page_dict = self._build_page_dict(entry)

    await self._publish_page_event("removed", page_dict)
    for od in orphaned_dicts:
        await self._publish_page_event("settings_updated", od)
    return True
```

> "settings_updated" is the existing event reused for "any non-lifecycle change" — frontend will read the new `parent_chat_id = null` from the payload and move the page between stores accordingly.

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v
```
Expected: all passed.

- [ ] **Step 5: Run full suite**

```bash
cd backend && uv run pytest -x -q
```
Expected: still green.

- [ ] **Step 6: Commit**

```bash
git add backend/app/whop/registry.py backend/tests/whop/test_registry_parent_chat.py
git commit -m "feat(whop): cascade children to top-level on chat parent removal"
```

---

## Task 4: WhopRegistry.list_pages · 父过滤参数

**Files:**
- Modify: `backend/app/whop/registry.py:366-368`
- Test: `backend/tests/whop/test_registry_parent_chat.py` (append)

- [ ] **Step 1: Write failing test**

Append:

```python
@pytest.mark.asyncio
async def test_list_pages_default_excludes_subs(registry):
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    await registry.add_page(
        url="https://whop.com/c/stock-a", source="stock", name="A", parent_chat_id=chat.id
    )
    await registry.add_page(url="https://whop.com/c/stock-x", source="stock", name="X")

    top = registry.list_pages()
    ids = {e.id for e, _ in top}
    assert chat.id in ids
    # standalone stock is included, sub-monitor is excluded
    standalone = next(e for e, _ in top if e.name == "X")
    assert standalone.id in ids
    assert all(e.parent_chat_id is None for e, _ in top)


@pytest.mark.asyncio
async def test_list_pages_filter_by_parent(registry):
    chat = await registry.add_page(url="https://whop.com/c/chat-1", source="chat", name="c")
    sub = await registry.add_page(
        url="https://whop.com/c/stock-a", source="stock", name="A", parent_chat_id=chat.id
    )
    await registry.add_page(url="https://whop.com/c/stock-x", source="stock", name="X")

    children = registry.list_pages(parent_chat_id=chat.id)
    assert len(children) == 1
    assert children[0][0].id == sub.id
```

- [ ] **Step 2: Run failing**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v -k "list_pages"
```
Expected: FAIL — current `list_pages` ignores `parent_chat_id`.

- [ ] **Step 3: Add parameter**

Replace `list_pages` in `registry.py`:

```python
def list_pages(
    self,
    *,
    parent_chat_id: str | None | _Sentinel = _DEFAULT,
) -> list[tuple[WhopPageEntry, WhopListener | None]]:
    """Return entries + their (optional) live listener.

    Default behaviour: only top-level entries (parent_chat_id IS NULL).
    Pass ``parent_chat_id=<id>`` to get that parent's sub-monitors.
    Pass ``parent_chat_id=None`` explicitly to opt in to all entries
    regardless of parent (internal use, e.g. URL routing).
    """
    if isinstance(parent_chat_id, _Sentinel):
        # default: top-level only
        return [
            (e, self._listeners.get(e.id))
            for e in self._entries.values()
            if e.parent_chat_id is None
        ]
    if parent_chat_id is None:
        return [(e, self._listeners.get(e.id)) for e in self._entries.values()]
    return [
        (e, self._listeners.get(e.id))
        for e in self._entries.values()
        if e.parent_chat_id == parent_chat_id
    ]
```

And add at module top:

```python
class _Sentinel:
    pass
_DEFAULT = _Sentinel()
```

> Sentinel pattern: distinguishes "caller passed None" (= include everything) from "caller didn't pass anything" (= default top-level only).

- [ ] **Step 4: Audit internal callers**

Search for existing `list_pages()` callers; they will now skip sub-monitors by default. Determine which need the new "all entries" behaviour by passing `parent_chat_id=None`:

```bash
cd backend && grep -rn "list_pages" app/ --include="*.py"
```

Internal callers that route URL → page (trader / push listener / URL→settings lookup) MUST keep seeing sub-monitors. Audit:
- `get_settings_for_url` already uses `_url_index` (not `list_pages`) — unaffected.
- `_publish_page_event` already uses `_build_page_dict` per entry — unaffected.
- HTTP endpoints (next task) will use the new default.

If any internal caller iterates `list_pages()` expecting all entries (e.g., shutdown loops), change to `list_pages(parent_chat_id=None)`. Most likely candidates:
- `shutdown_all` iterates `_listeners` directly, not `list_pages` — unaffected.

Run the full suite to surface any caller that breaks under the new default:

```bash
cd backend && uv run pytest -x -q
```

If any test fails because a caller expected all entries, update the caller in this commit to pass `parent_chat_id=None`.

- [ ] **Step 5: Run parent-chat tests**

```bash
cd backend && uv run pytest tests/whop/test_registry_parent_chat.py -v
```
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/whop/registry.py backend/tests/whop/test_registry_parent_chat.py
git commit -m "feat(whop): list_pages default excludes sub-monitors; add parent_chat_id filter"
```

---

## Task 5: REST schemas · 暴露 parent_chat_id

**Files:**
- Modify: `backend/app/api/schemas.py:585-610`
- Modify: `backend/app/api/schemas.py:850-870` (whop_page_to_out)
- Test: `backend/tests/api/test_whop_pages_parent.py` (new)

- [ ] **Step 1: Write failing test**

Create `backend/tests/api/test_whop_pages_parent.py`:

```python
"""Tests for parent_chat_id round-trip through REST."""
from httpx import AsyncClient
import pytest


@pytest.mark.asyncio
async def test_create_and_list_with_parent(client: AsyncClient):
    parent = (await client.post("/api/whop/pages", json={
        "url": "https://whop.com/c/chat-1",
        "source": "chat",
        "name": "alpha-room",
    })).json()
    child = (await client.post("/api/whop/pages", json={
        "url": "https://whop.com/c/stock-a",
        "source": "stock",
        "name": "TSLL 监听",
        "parent_chat_id": parent["id"],
    })).json()
    assert child["parent_chat_id"] == parent["id"]


@pytest.mark.asyncio
async def test_list_default_excludes_sub_monitors(client: AsyncClient):
    parent = (await client.post("/api/whop/pages", json={
        "url": "https://whop.com/c/chat-1",
        "source": "chat",
        "name": "c",
    })).json()
    await client.post("/api/whop/pages", json={
        "url": "https://whop.com/c/stock-a",
        "source": "stock",
        "name": "A",
        "parent_chat_id": parent["id"],
    })
    r = await client.get("/api/whop/pages")
    ids = {p["id"] for p in r.json()["pages"]}
    assert parent["id"] in ids
    assert all(p["parent_chat_id"] is None for p in r.json()["pages"])


@pytest.mark.asyncio
async def test_list_filter_by_parent(client: AsyncClient):
    parent = (await client.post("/api/whop/pages", json={
        "url": "https://whop.com/c/chat-1",
        "source": "chat",
        "name": "c",
    })).json()
    child = (await client.post("/api/whop/pages", json={
        "url": "https://whop.com/c/stock-a",
        "source": "stock",
        "name": "A",
        "parent_chat_id": parent["id"],
    })).json()
    r = await client.get(f"/api/whop/pages?parent_chat_id={parent['id']}")
    pages = r.json()["pages"]
    assert len(pages) == 1
    assert pages[0]["id"] == child["id"]


@pytest.mark.asyncio
async def test_create_rejects_invalid_parent(client: AsyncClient):
    r = await client.post("/api/whop/pages", json={
        "url": "https://whop.com/c/stock-a",
        "source": "stock",
        "name": "A",
        "parent_chat_id": "nonexistent",
    })
    assert r.status_code == 400
    assert "not found" in r.json()["detail"]
```

> Existing test setup probably has a `client` fixture; if naming differs, adapt. Check `backend/tests/conftest.py` for the canonical fixture name.

- [ ] **Step 2: Update schemas**

Modify `backend/app/api/schemas.py`:

```python
class WhopPageOut(BaseModel):
    id: str
    url: str
    source: str
    name: str
    added_at: datetime
    settings: WhopPageSettingsOut
    running: bool
    started_at: datetime | None
    last_poll_at: datetime | None
    messages_published: int
    last_error: str | None
    parent_chat_id: str | None = None  # NEW


class WhopPageCreate(BaseModel):
    url: str
    source: Literal["stock", "option", "chat"]
    name: str | None = None
    parent_chat_id: str | None = None  # NEW
```

And in `whop_page_to_out` (around line 850), include the field:

```python
def whop_page_to_out(entry: WhopPageEntry, listener: WhopListener | None) -> WhopPageOut:
    return WhopPageOut(
        id=entry.id,
        url=entry.url,
        # ... existing fields ...
        parent_chat_id=entry.parent_chat_id,
    )
```

- [ ] **Step 3: Update endpoints**

Modify `backend/app/api/http.py`:

```python
@router.get("/api/whop/pages", response_model=WhopPagesOut)
async def list_whop_pages(
    parent_chat_id: str | None = None,
) -> WhopPagesOut:
    # Sentinel `_DEFAULT` (parent_chat_id absent) → top-level only;
    # explicit query value → filter; "" or "null" string → treat as top-level.
    if parent_chat_id is None:
        pages = whop_registry.list_pages()  # default: top-level only
    else:
        pages = whop_registry.list_pages(parent_chat_id=parent_chat_id)
    return WhopPagesOut(pages=[whop_page_to_out(e, ll) for e, ll in pages])


@router.post("/api/whop/pages", response_model=WhopPageOut, status_code=201)
async def create_whop_page(body: WhopPageCreate) -> WhopPageOut:
    try:
        entry = await whop_registry.add_page(
            url=body.url,
            source=body.source,
            name=body.name,
            parent_chat_id=body.parent_chat_id,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    # need to fetch with the "all entries" view since sub-monitor isn't in default list
    for e, ll in whop_registry.list_pages(parent_chat_id=None):
        if e.id == entry.id:
            return whop_page_to_out(e, ll)
    raise HTTPException(500, detail="added but lost track")
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/api/test_whop_pages_parent.py -v
```
Expected: all passed.

- [ ] **Step 5: Run full suite**

```bash
cd backend && uv run pytest -x -q && uv run mypy app
```
Expected: green + mypy strict clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schemas.py backend/app/api/http.py backend/tests/api/test_whop_pages_parent.py
git commit -m "feat(api): expose parent_chat_id on WhopPage; filter list endpoint by parent"
```

---

## Task 6: `list_tasks` repo · urls + posted_at window

**Files:**
- Modify: `backend/app/storage/repo.py:530-598`
- Test: `backend/tests/storage/test_repo_list_tasks_filters.py` (new)

- [ ] **Step 1: Write failing test**

Create `backend/tests/storage/test_repo_list_tasks_filters.py`:

```python
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
            s.add(MessageRow(
                id=tid, url=url, source="whop", author="x", content="m",
                posted_at=datetime(2026, 5, 20, 9, 0),
                received_at=datetime(2026, 5, 20, 9, 0),
            ))
            s.add(TaskRow(
                id=tid, type="stock", status="FILLED",
                created_at=datetime(2026, 5, 20, 9, 0),
                updated_at=datetime(2026, 5, 20, 9, 0),
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
            s.add(MessageRow(
                id=tid, url="https://x", source="whop", author="a", content="m",
                posted_at=ts, received_at=ts,
            ))
            s.add(TaskRow(
                id=tid, type="stock", status="FILLED",
                created_at=ts, updated_at=ts,
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
async def test_list_tasks_urls_combines_with_other_filters(session_factory):
    async with session_factory() as s:
        for tid, url, status in [
            ("a-ok", "https://a", "FILLED"),
            ("a-bad", "https://a", "PARSE_ERROR"),
            ("b-ok", "https://b", "FILLED"),
        ]:
            s.add(MessageRow(
                id=tid, url=url, source="whop", author="x", content="m",
                posted_at=datetime(2026, 5, 20, 9, 0),
                received_at=datetime(2026, 5, 20, 9, 0),
            ))
            s.add(TaskRow(
                id=tid, type="stock", status=status,
                created_at=datetime(2026, 5, 20, 9, 0),
                updated_at=datetime(2026, 5, 20, 9, 0),
            ))
        await s.commit()

    async with session_factory() as s:
        from app.domain.status import Status
        tasks = await repo.list_tasks(s, urls=["https://a"], status=Status.FILLED)
    ids = {t.id for t in tasks}
    assert ids == {"a-ok"}
```

> If `session_factory` fixture name differs, adapt — check `backend/tests/conftest.py`.

- [ ] **Step 2: Run failing**

```bash
cd backend && uv run pytest tests/storage/test_repo_list_tasks_filters.py -v
```
Expected: FAIL — `list_tasks` doesn't accept these kwargs.

- [ ] **Step 3: Extend list_tasks**

Modify `backend/app/storage/repo.py`:

```python
async def list_tasks(
    session: AsyncSession,
    *,
    limit: int = 50,
    cursor_created_at: datetime | None = None,
    status: Status | None = None,
    type_: str | None = None,
    symbol: str | None = None,
    ticker: str | None = None,
    statuses: list[Status] | None = None,
    urls: list[str] | None = None,
    posted_at_start: datetime | None = None,
    posted_at_end: datetime | None = None,
) -> list[Task]:
    """... (existing docstring +) 

    ``urls``: filter to tasks whose message.url is in the list. ``None`` = no
    filter. Empty list = match nothing (returns []).

    ``posted_at_start`` / ``posted_at_end``: half-open [start, end) window on
    message.posted_at. Either bound is optional.
    """
    if urls is not None and len(urls) == 0:
        return []

    stmt = select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit)

    if cursor_created_at is not None:
        cursor_naive = cursor_created_at.replace(tzinfo=None)
        stmt = stmt.where(TaskRow.created_at < cursor_naive)

    if statuses is not None:
        stmt = stmt.where(TaskRow.status.in_([s.value for s in statuses]))
    elif status is not None:
        stmt = stmt.where(TaskRow.status == status.value)

    if type_ is not None:
        stmt = stmt.where(TaskRow.type == type_)

    if symbol is not None:
        stmt = stmt.where(TaskRow.symbol == symbol)

    if ticker is not None:
        stmt = stmt.where(TaskRow.ticker == ticker)

    # New filters: join MessageRow on id (TaskRow.id == MessageRow.id by spec)
    needs_msg_join = (
        urls is not None
        or posted_at_start is not None
        or posted_at_end is not None
    )
    if needs_msg_join:
        stmt = stmt.join(MessageRow, MessageRow.id == TaskRow.id)
        if urls is not None:
            stmt = stmt.where(MessageRow.url.in_(urls))
        if posted_at_start is not None:
            stmt = stmt.where(MessageRow.posted_at >= posted_at_start.replace(tzinfo=None))
        if posted_at_end is not None:
            stmt = stmt.where(MessageRow.posted_at < posted_at_end.replace(tzinfo=None))

    result = await session.execute(stmt)
    task_rows = list(result.scalars().all())

    tasks: list[Task] = []
    for task_row in task_rows:
        msg_row = await session.get(MessageRow, task_row.id)
        if msg_row is None:
            continue
        inst_row = await session.get(InstructionRow, task_row.id)
        tasks.append(_rows_to_task(task_row, msg_row, inst_row, []))

    if tasks:
        latest = await latest_push_per_task(session, [t.id for t in tasks])
        for t in tasks:
            evt = latest.get(t.id)
            if evt is not None:
                t.push_events = [evt]

    return tasks
```

- [ ] **Step 4: Run tests**

```bash
cd backend && uv run pytest tests/storage/test_repo_list_tasks_filters.py -v
```
Expected: all passed.

- [ ] **Step 5: Run full suite**

```bash
cd backend && uv run pytest -x -q && uv run mypy app
```
Expected: green + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_repo_list_tasks_filters.py
git commit -m "feat(storage): list_tasks accepts urls + posted_at window filters"
```

---

## Task 7: REST `/api/tasks` 接受 urls / week_start / week_end

**Files:**
- Modify: `backend/app/api/http.py:227-260`
- Test: `backend/tests/api/test_tasks_filter.py` (new)

- [ ] **Step 1: Write failing test**

Create `backend/tests/api/test_tasks_filter.py`:

```python
"""Tests for /api/tasks?urls=&week_start=&week_end= filters."""
import pytest


@pytest.mark.asyncio
async def test_tasks_multi_url_query(client, seed_tasks):
    """seed_tasks fixture creates tasks tied to a few urls; verify multi-value
    `?urls=` filter narrows the result set."""
    r = await client.get(
        "/api/tasks?urls=https://a.example&urls=https://c.example"
    )
    assert r.status_code == 200
    ids = {t["id"] for t in r.json()["tasks"]}
    assert ids == {"task-a", "task-c"}


@pytest.mark.asyncio
async def test_tasks_week_window(client, seed_tasks):
    r = await client.get(
        "/api/tasks?week_start=2026-05-18T00:00:00&week_end=2026-05-25T00:00:00"
    )
    ids = {t["id"] for t in r.json()["tasks"]}
    assert "task-a" in ids
    assert "task-old" not in ids


@pytest.mark.asyncio
async def test_tasks_window_plus_urls(client, seed_tasks):
    r = await client.get(
        "/api/tasks?urls=https://a.example&urls=https://b.example"
        "&week_start=2026-05-18T00:00:00&week_end=2026-05-25T00:00:00"
    )
    ids = {t["id"] for t in r.json()["tasks"]}
    assert ids == {"task-a", "task-b"}
```

> If `seed_tasks` fixture doesn't exist, add it to a new `conftest.py` in `tests/api/` that inserts a handful of MessageRow+TaskRow pairs with controlled urls and posted_at. Mirror the seed used in Task 6.

- [ ] **Step 2: Update endpoint**

Modify `backend/app/api/http.py` `list_tasks_endpoint`:

```python
from typing import Annotated
from fastapi import Query


@router.get("/api/tasks", response_model=TaskListOut)
async def list_tasks_endpoint(
    limit: int = Query(50, ge=1, le=500),
    cursor: datetime | None = None,
    status: str | None = None,
    type: Annotated[str | None, Query(alias="type")] = None,
    symbol: str | None = None,
    urls: Annotated[list[str] | None, Query()] = None,
    week_start: datetime | None = None,
    week_end: datetime | None = None,
) -> TaskListOut:
    """Return a paginated, filtered list of tasks.

    Multi-value URL filter: pass ``?urls=u1&urls=u2``. Time window:
    ``week_start`` / ``week_end`` apply a half-open [start, end) filter on
    ``message.posted_at``.
    """
    status_enum: Status | None = None
    if status is not None:
        try:
            status_enum = Status(status)
        except ValueError as exc:
            raise HTTPException(400, detail=f"unknown status: {status!r}") from exc

    async with session_scope(session_factory) as session:
        tasks = await repo.list_tasks(
            session,
            limit=limit,
            cursor_created_at=cursor,
            status=status_enum,
            type_=type,
            symbol=symbol,
            urls=urls,
            posted_at_start=week_start,
            posted_at_end=week_end,
        )
    summaries = [task_to_summary(t) for t in tasks]
    next_cur: datetime | None = tasks[-1].created_at if len(tasks) == limit else None
    return TaskListOut(tasks=summaries, next_cursor=next_cur)
```

- [ ] **Step 3: Run tests**

```bash
cd backend && uv run pytest tests/api/test_tasks_filter.py -v
```
Expected: all passed.

- [ ] **Step 4: Run full suite**

```bash
cd backend && uv run pytest -x -q && uv run mypy app
```
Expected: green + mypy clean.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_tasks_filter.py
git commit -m "feat(api): /api/tasks accepts urls[] and week_start/end window filters"
```

---

## Task 8: Frontend types · WhopPage.parent_chat_id + API method signatures

**Files:**
- Modify: `frontend/src/api/domain-types.ts:124-129`
- Modify: `frontend/src/api/http.ts` (list_tasks / list_whop_pages / add_whop_page signatures)

- [ ] **Step 1: Extend types**

Modify `frontend/src/api/domain-types.ts`:

```ts
export type WhopPage = Omit<components["schemas"]["WhopPageOut"], "settings"> & {
  settings: WhopPageSettings;
  /** Set when this page is a sub-monitor under a chat parent. */
  parent_chat_id?: string | null;
};

export type WhopPageCreate = components["schemas"]["WhopPageCreate"] & {
  parent_chat_id?: string | null;
};
```

> Until the next `npm run gen:types` regen, this manual extension is necessary.

- [ ] **Step 2: Extend API methods**

Find existing `listTasks`, `listWhopPages`, `addWhopPage` in `frontend/src/api/http.ts`. Extend:

```ts
// listTasks
async listTasks(params?: {
  limit?: number;
  cursor?: string;
  status?: string;
  type?: string;
  symbol?: string;
  urls?: string[];
  week_start?: string;
  week_end?: string;
}): Promise<TaskList> {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.cursor) qs.set("cursor", params.cursor);
  if (params?.status) qs.set("status", params.status);
  if (params?.type) qs.set("type", params.type);
  if (params?.symbol) qs.set("symbol", params.symbol);
  if (params?.urls) for (const u of params.urls) qs.append("urls", u);
  if (params?.week_start) qs.set("week_start", params.week_start);
  if (params?.week_end) qs.set("week_end", params.week_end);
  return this.get(`/api/tasks?${qs}`);
},

// listWhopPages
async listWhopPages(opts?: { parentChatId?: string }): Promise<WhopPages> {
  const qs = opts?.parentChatId
    ? `?parent_chat_id=${encodeURIComponent(opts.parentChatId)}`
    : "";
  return this.get(`/api/whop/pages${qs}`);
},

// addWhopPage: ensure body type includes parent_chat_id
async addWhopPage(body: WhopPageCreate): Promise<WhopPage> {
  return this.post(`/api/whop/pages`, body);
},
```

- [ ] **Step 3: Tsc check**

```bash
cd frontend && npx tsc --noEmit
```
Expected: clean.

- [ ] **Step 4: Run vitest (smoke; existing tests should still pass)**

```bash
cd frontend && npm test -- --run
```
Expected: all green (no behavioural change yet).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/domain-types.ts frontend/src/api/http.ts
git commit -m "feat(api): WhopPage.parent_chat_id + listTasks/listWhopPages query params"
```

---

## Task 9: `useChildPagesStore` · 子页注册表

**Files:**
- Create: `frontend/src/stores/childPages.ts`
- Test: `frontend/src/stores/childPages.test.ts`

- [ ] **Step 1: Write failing test**

Create `frontend/src/stores/childPages.test.ts`:

```ts
import { beforeEach, describe, expect, it } from "vitest";
import type { WhopPage } from "../api/domain-types";
import { useChildPagesStore } from "./childPages";

function makePage(over: Partial<WhopPage>): WhopPage {
  return {
    id: "p1",
    url: "https://x",
    source: "stock",
    name: "P1",
    added_at: new Date().toISOString(),
    settings: { dedupe_processed_messages: true } as WhopPage["settings"],
    running: true,
    started_at: null,
    last_poll_at: null,
    messages_published: 0,
    last_error: null,
    parent_chat_id: "chat1",
    ...over,
  };
}

describe("useChildPagesStore", () => {
  beforeEach(() => {
    useChildPagesStore.setState({ byParent: {} });
  });

  it("setByParent replaces the list for that parent", () => {
    const a = makePage({ id: "a" });
    const b = makePage({ id: "b" });
    useChildPagesStore.getState().setByParent("chat1", [a, b]);
    expect(useChildPagesStore.getState().byParent["chat1"]).toHaveLength(2);
    useChildPagesStore.getState().setByParent("chat1", [a]);
    expect(useChildPagesStore.getState().byParent["chat1"]).toHaveLength(1);
  });

  it("upsert places child under its parent and replaces existing by id", () => {
    const a = makePage({ id: "a", name: "old" });
    useChildPagesStore.getState().upsert(a);
    expect(useChildPagesStore.getState().byParent["chat1"][0].name).toBe("old");
    useChildPagesStore.getState().upsert({ ...a, name: "new" });
    expect(useChildPagesStore.getState().byParent["chat1"][0].name).toBe("new");
  });

  it("upsert moves child between parents when parent_chat_id changes", () => {
    const a = makePage({ id: "a", parent_chat_id: "chat1" });
    useChildPagesStore.getState().upsert(a);
    useChildPagesStore.getState().upsert({ ...a, parent_chat_id: "chat2" });
    expect(useChildPagesStore.getState().byParent["chat1"]).toBeUndefined();
    expect(useChildPagesStore.getState().byParent["chat2"]).toHaveLength(1);
  });

  it("upsert with parent_chat_id=null removes from child store", () => {
    const a = makePage({ id: "a" });
    useChildPagesStore.getState().upsert(a);
    useChildPagesStore.getState().upsert({ ...a, parent_chat_id: null });
    expect(useChildPagesStore.getState().byParent["chat1"] ?? []).toHaveLength(0);
  });

  it("remove drops the child by id", () => {
    useChildPagesStore.getState().upsert(makePage({ id: "a" }));
    useChildPagesStore.getState().remove("a");
    expect(useChildPagesStore.getState().byParent["chat1"] ?? []).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run failing**

```bash
cd frontend && npm test -- --run childPages
```
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement store**

Create `frontend/src/stores/childPages.ts`:

```ts
import { create } from "zustand";
import type { WhopPage } from "../api/domain-types";

interface ChildPagesState {
  /** parent chat id → list of its sub-monitor pages. Pages without a
   *  parent (top-level) never appear here. */
  byParent: Record<string, WhopPage[]>;

  setByParent(parentId: string, pages: WhopPage[]): void;
  upsert(page: WhopPage): void;
  remove(pageId: string): void;
}

export const useChildPagesStore = create<ChildPagesState>((set, get) => ({
  byParent: {},

  setByParent(parentId, pages) {
    set((s) => ({ byParent: { ...s.byParent, [parentId]: pages } }));
  },

  upsert(page) {
    set((s) => {
      // Drop the page from every parent bucket first — this handles both the
      // "moved to a different parent" and "promoted to top-level" cases.
      const cleaned: Record<string, WhopPage[]> = {};
      for (const [pid, list] of Object.entries(s.byParent)) {
        const filtered = list.filter((p) => p.id !== page.id);
        if (filtered.length > 0) cleaned[pid] = filtered;
      }
      if (page.parent_chat_id == null) return { byParent: cleaned };
      const existing = cleaned[page.parent_chat_id] ?? [];
      return {
        byParent: { ...cleaned, [page.parent_chat_id]: [...existing, page] },
      };
    });
  },

  remove(pageId) {
    set((s) => {
      const next: Record<string, WhopPage[]> = {};
      for (const [pid, list] of Object.entries(s.byParent)) {
        const filtered = list.filter((p) => p.id !== pageId);
        if (filtered.length > 0) next[pid] = filtered;
      }
      return { byParent: next };
    });
  },
}));
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm test -- --run childPages
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/childPages.ts frontend/src/stores/childPages.test.ts
git commit -m "feat(stores): useChildPagesStore for chat→sub-monitor mapping"
```

---

## Task 10: WS handler · 路由 `whop.page_changed` 到正确 store

**Files:**
- Modify: `frontend/src/App.tsx:163-200`

- [ ] **Step 1: Update WS handler**

Find the `client = createWsClient({ onEvent: ... })` block. Add a branch BEFORE the existing `whop.page_changed → applyPageChanged` line:

```ts
if (evt.type === "whop.page_changed") {
  const payload = evt.payload as { page?: WhopPage; reason?: string };
  if (payload.page) {
    // Sub-monitor: route into childPagesStore; ensure it does NOT show in
    // top-level pageTabs (the page-tabs store filters parent_chat_id ≠ null
    // out itself, but we also do not call applyPageChanged for clarity).
    if (payload.page.parent_chat_id != null) {
      useChildPagesStore.getState().upsert(payload.page);
      // If a page was previously top-level and is now a sub, drop it from
      // pageTabsStore as well (rare; happens via PATCH that changes parent).
      usePageTabsStore.getState().removePageIfPresent?.(payload.page.id);
    } else {
      // Top-level: ensure childPagesStore drops it (in case it was a sub
      // that got promoted by a parent removal cascade), then forward to
      // the page-tabs store as today.
      useChildPagesStore.getState().remove(payload.page.id);
      usePageTabsStore.getState().applyPageChanged(evt);
    }
  } else {
    // No page payload (removal events) → delegate as today.
    usePageTabsStore.getState().applyPageChanged(evt);
  }
}
```

Add imports at top of `App.tsx`:

```ts
import { useChildPagesStore } from "./stores/childPages";
```

> `usePageTabsStore.removePageIfPresent` may not exist yet. If it doesn't, add it to `frontend/src/stores/pageTabs.ts` as a no-op-safe action:
>
> ```ts
> removePageIfPresent(pageId: string) {
>   set((s) => ({ pages: s.pages.filter((p) => p.id !== pageId) }));
> },
> ```

- [ ] **Step 2: Visual smoke**

```bash
cd frontend && npx tsc --noEmit
```
Expected: clean.

```bash
cd frontend && npm test -- --run
```
Expected: all green.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.tsx frontend/src/stores/pageTabs.ts
git commit -m "feat(ws): route whop.page_changed to child store when parent_chat_id set"
```

---

## Task 11: `signalCardHelpers.ts` · status → layer 描述符

**Files:**
- Create: `frontend/src/components/Chat/signalCardHelpers.ts`
- Test: `frontend/src/components/Chat/signalCardHelpers.test.ts`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/Chat/signalCardHelpers.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { layersForTask } from "./signalCardHelpers";
import type { TaskSummary } from "../../api/domain-types";

function task(over: Partial<TaskSummary>): TaskSummary {
  return {
    id: "t1",
    type: "stock",
    status: "FILLED",
    message: {
      id: "msg1",
      source: "whop",
      author: "TSLL 监听",
      content: "buying tsla calls dip 200",
      posted_at: "2026-05-20T01:32:15Z",
      received_at: "2026-05-20T01:32:15Z",
      url: "https://whop.com/c/stock-a",
    },
    instruction: {
      instruction_type: "BUY",
      ticker: "TSLL",
      symbol: "TSLL.US",
      price: 200,
      quantity: 100,
    },
    last_cum_qty: 100,
    last_cum_avg_price: 199.87,
    created_at: "2026-05-20T01:32:15Z",
    updated_at: "2026-05-20T01:32:16Z",
    ...over,
  } as TaskSummary;
}

describe("layersForTask", () => {
  it("FILLED stock task: ord layer is the cum/avg form", () => {
    const layers = layersForTask(task({ status: "FILLED" }));
    expect(layers.kind).toBe("normal");
    expect(layers.ord?.text).toContain("已成交");
    expect(layers.ord?.dot).toBe("ok");
  });

  it("PARSE_ERROR: sig layer is the error variant, ord hidden", () => {
    const layers = layersForTask(task({
      status: "PARSE_ERROR",
      instruction: null,
      reject_reason: "regex no match",
    }));
    expect(layers.kind).toBe("parse_error");
    expect(layers.sig?.error).toContain("未解析");
    expect(layers.ord).toBeNull();
  });

  it("INSTRUCTION_READY + auto_trade off: sig layer carries confirm pair flag", () => {
    const layers = layersForTask(
      task({ status: "INSTRUCTION_READY" }),
      { autoTrade: false }
    );
    expect(layers.sig?.showConfirmActions).toBe(true);
    expect(layers.ord?.dot).toBe("warn");
  });

  it("INSTRUCTION_READY + auto_trade on: no confirm actions", () => {
    const layers = layersForTask(
      task({ status: "INSTRUCTION_READY" }),
      { autoTrade: true }
    );
    expect(layers.sig?.showConfirmActions).toBe(false);
  });

  it("SKIPPED: ord shows reject_reason with orange dot", () => {
    const layers = layersForTask(task({
      status: "SKIPPED",
      reject_reason: "block_historical_messages",
    }));
    expect(layers.ord?.text).toContain("block_historical_messages");
    expect(layers.ord?.dot).toBe("warn");
  });

  it("SUBMIT_FAILED: ord shows error with red dot", () => {
    const layers = layersForTask(task({
      status: "SUBMIT_FAILED",
      reject_reason: "broker rejected",
    }));
    expect(layers.ord?.dot).toBe("err");
    expect(layers.ord?.text).toContain("提交失败");
  });

  it("PARTIAL: ord shows cum/total with warn dot", () => {
    const layers = layersForTask(task({
      status: "PARTIAL",
      last_cum_qty: 60,
      last_cum_avg_price: 201.36,
    }));
    expect(layers.ord?.dot).toBe("warn");
    expect(layers.ord?.text).toContain("部分成交");
  });

  it("option task: sig layer includes contract", () => {
    const layers = layersForTask(task({
      type: "option",
      instruction: {
        instruction_type: "BUY",
        ticker: "NVDA",
        symbol: "NVDA.US",
        strike: 880,
        expiry: "2026-12-15",
        price: 5.2,
        quantity: 5,
      } as TaskSummary["instruction"],
    }));
    expect(layers.sig?.contract).toBe("880C 12/15");
  });
});
```

- [ ] **Step 2: Run failing**

```bash
cd frontend && npm test -- --run signalCardHelpers
```
Expected: FAIL — module missing.

- [ ] **Step 3: Implement helpers**

Create `frontend/src/components/Chat/signalCardHelpers.ts`:

```ts
import type { TaskSummary, Instruction } from "../../api/domain-types";

export type DotColor = "ok" | "warn" | "err" | "muted";
export type LayerKind = "normal" | "parse_error" | "neutral";

export interface SigLayer {
  side: "BUY" | "SELL" | null;
  ticker: string | null;
  contract: string | null;       // option-only: "880C 12/15"
  price: number | null;
  quantity: number | null;
  showConfirmActions: boolean;   // auto_trade off + INSTRUCTION_READY
  error: string | null;          // PARSE_ERROR text
  ctx: string | null;
  parseDeltaMs: number | null;
}

export interface OrdLayer {
  dot: DotColor;
  text: string;                  // 已成交 / 部分成交 / 提交失败 …
  cum: string | null;            // "100/100 @ $199.87"
  statusPill: string | null;     // optional pill label, e.g. "PARSE_ERROR"
}

export interface CardLayers {
  kind: LayerKind;
  /** raw whop text. Always set; folded view 1-line clips, expanded wraps. */
  msg: string;
  sig: SigLayer | null;
  ord: OrdLayer | null;
}

function formatExpiryMMDD(iso: string): string {
  // "2026-12-15" → "12/15"
  const [, mm, dd] = iso.split("-");
  return `${mm}/${dd}`;
}

function formatContract(inst: Instruction): string | null {
  if (inst.strike == null || !inst.expiry) return null;
  return `${inst.strike}C ${formatExpiryMMDD(inst.expiry)}`;
}

export function layersForTask(
  task: TaskSummary,
  opts?: { autoTrade?: boolean },
): CardLayers {
  const autoTrade = opts?.autoTrade ?? true;
  const msg = task.message.content ?? "";
  const inst = task.instruction;

  if (task.status === "PARSE_ERROR") {
    return {
      kind: "parse_error",
      msg,
      sig: {
        side: null, ticker: null, contract: null, price: null, quantity: null,
        showConfirmActions: false,
        error: "未解析 · 正则未匹配",
        ctx: null, parseDeltaMs: null,
      },
      ord: null,
    };
  }

  const sig: SigLayer | null = inst
    ? {
        side: inst.instruction_type as "BUY" | "SELL",
        ticker: inst.symbol ?? inst.ticker ?? null,
        contract: task.type === "option" ? formatContract(inst) : null,
        price: inst.price ?? null,
        quantity: inst.quantity ?? null,
        showConfirmActions:
          !autoTrade && task.status === "INSTRUCTION_READY",
        error: null,
        ctx: inst.context_source ?? null,
        parseDeltaMs: task.stage_timings?.parse ?? null,
      }
    : null;

  let ord: OrdLayer | null = null;
  switch (task.status) {
    case "INSTRUCTION_READY":
      ord = { dot: autoTrade ? "warn" : "warn", text: "等待人工确认",
              cum: "auto_trade 已关闭", statusPill: null };
      break;
    case "SUBMITTING":
    case "PENDING":
      ord = { dot: "warn", text: "等待成交", cum: null, statusPill: null };
      break;
    case "PARTIAL":
      ord = {
        dot: "warn",
        text: "部分成交",
        cum: task.last_cum_qty != null && task.last_cum_avg_price != null
          ? `${task.last_cum_qty}/${task.instruction?.quantity ?? "—"} @ $${task.last_cum_avg_price.toFixed(2)}`
          : null,
        statusPill: null,
      };
      break;
    case "FILLED":
      ord = {
        dot: "ok",
        text: "已成交",
        cum: task.last_cum_qty != null && task.last_cum_avg_price != null
          ? `${task.last_cum_qty}/${task.instruction?.quantity ?? "—"} @ $${task.last_cum_avg_price.toFixed(2)}`
          : null,
        statusPill: null,
      };
      break;
    case "CANCELLED":
    case "REJECTED":
      ord = { dot: "err", text: task.status, cum: task.reject_reason ?? null, statusPill: null };
      break;
    case "SUBMIT_FAILED":
      ord = { dot: "err", text: `提交失败 · ${task.reject_reason ?? ""}`,
              cum: null, statusPill: null };
      break;
    case "SKIPPED":
      ord = { dot: "warn", text: task.reject_reason ?? "已跳过",
              cum: null, statusPill: null };
      break;
    default:
      ord = null;
  }

  return { kind: "normal", msg, sig, ord };
}
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm test -- --run signalCardHelpers
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/signalCardHelpers.ts frontend/src/components/Chat/signalCardHelpers.test.ts
git commit -m "feat(chat): signalCardHelpers · status-to-layer descriptors for SignalCard"
```

---

## Task 12: `SignalCard.tsx` + CSS · 渲染折叠 + 展开

**Files:**
- Create: `frontend/src/components/Chat/SignalCard.tsx`
- Create: `frontend/src/components/Chat/SignalCard.css`
- Test: `frontend/src/components/Chat/SignalCard.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/Chat/SignalCard.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { TaskSummary } from "../../api/domain-types";
import { SignalCard } from "./SignalCard";

function task(over: Partial<TaskSummary>): TaskSummary {
  return {
    id: "t1",
    type: "stock",
    status: "FILLED",
    message: {
      id: "msg1",
      source: "whop",
      author: "TSLL 监听",
      content: "buying tsla calls dip 200",
      posted_at: "2026-05-20T01:32:15Z",
      received_at: "2026-05-20T01:32:15Z",
      url: "https://whop.com/x",
    },
    instruction: {
      instruction_type: "BUY", ticker: "TSLL", symbol: "TSLL.US",
      price: 200, quantity: 100,
    },
    last_cum_qty: 100, last_cum_avg_price: 199.87,
    created_at: "2026-05-20T01:32:15Z",
    updated_at: "2026-05-20T01:32:16Z",
    ...over,
  } as TaskSummary;
}

describe("SignalCard", () => {
  it("folded renders the three-layer summary", () => {
    render(<SignalCard task={task({})} pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={true} />);
    expect(screen.getByText(/buying tsla calls/)).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText(/TSLL\.US/)).toBeInTheDocument();
    expect(screen.getByText(/已成交/)).toBeInTheDocument();
  });

  it("PARSE_ERROR shows red sig line and hides ord", () => {
    render(<SignalCard
      task={task({ status: "PARSE_ERROR", instruction: null, reject_reason: "no match" })}
      pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={true}
    />);
    expect(screen.getByText(/未解析/)).toBeInTheDocument();
    expect(screen.queryByText(/已成交/)).not.toBeInTheDocument();
  });

  it("INSTRUCTION_READY + auto_trade off shows confirm buttons", () => {
    render(<SignalCard
      task={task({ status: "INSTRUCTION_READY" })}
      pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={false}
    />);
    expect(screen.getByRole("button", { name: /确认/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /跳过/ })).toBeInTheDocument();
  });

  it("click bubble triggers onToggle", () => {
    const onToggle = vi.fn();
    const { container } = render(
      <SignalCard task={task({})} pushEvents={[]} expanded={false} onToggle={onToggle} autoTrade={true} />
    );
    fireEvent.click(container.querySelector(".signal-bubble")!);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("expanded shows the detail blocks", () => {
    render(<SignalCard
      task={task({})} pushEvents={[]} expanded={true} onToggle={() => {}} autoTrade={true}
    />);
    expect(screen.getByText(/MSG/)).toBeInTheDocument();
    expect(screen.getByText(/posted/)).toBeInTheDocument();
  });

  it("option task renders contract label", () => {
    render(<SignalCard
      task={task({
        type: "option",
        instruction: {
          instruction_type: "BUY", ticker: "NVDA", symbol: "NVDA.US",
          strike: 880, expiry: "2026-12-15", price: 5.2, quantity: 5,
        } as TaskSummary["instruction"],
      })}
      pushEvents={[]} expanded={false} onToggle={() => {}} autoTrade={true}
    />);
    expect(screen.getByText("880C 12/15")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run failing**

```bash
cd frontend && npm test -- --run SignalCard
```
Expected: FAIL — module missing.

- [ ] **Step 3: Implement component (folded + expanded)**

Create `frontend/src/components/Chat/SignalCard.tsx`:

```tsx
import type { TaskSummary, PushEvent } from "../../api/domain-types";
import { layersForTask } from "./signalCardHelpers";
import { ConfirmActions } from "../Card/ConfirmActions";
import { PushChain } from "../Card/PushChain";
import { fmtBeijingFull } from "../Card/cardHelpers";
import "./SignalCard.css";

export interface SignalCardProps {
  task: TaskSummary;
  pushEvents: PushEvent[];
  expanded: boolean;
  onToggle(): void;
  autoTrade: boolean;
}

function fmtTime(iso: string): string {
  const normalized = /[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

export function SignalCard({
  task, pushEvents, expanded, onToggle, autoTrade,
}: SignalCardProps): JSX.Element {
  const layers = layersForTask(task, { autoTrade });
  const sourceClass =
    layers.kind === "parse_error" ? "neutral" : task.type === "option" ? "option" : "stock";

  return (
    <div
      className={`signal-bubble ${sourceClass}`}
      data-state={expanded ? "expanded" : "folded"}
      role="button"
      tabIndex={0}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest(".confirm-pair, .push-tail")) return;
        onToggle();
      }}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); } }}
    >
      <div className="signal-summary">
        {/* Layer 1: MSG */}
        <div className="layer-msg" title={layers.msg}>{layers.msg}</div>

        {/* Layer 2: SIG */}
        {layers.sig && (
          <div className="layer-sig">
            {layers.sig.error ? (
              <span className="layer-error">{layers.sig.error}</span>
            ) : (
              <>
                {layers.sig.side && (
                  <span className={`side-chip ${layers.sig.side.toLowerCase()}`}>{layers.sig.side}</span>
                )}
                {layers.sig.ticker && <span className="ticker">{layers.sig.ticker}</span>}
                {layers.sig.contract && <span className="contract">{layers.sig.contract}</span>}
                {layers.sig.price != null && <span className="price">${layers.sig.price.toFixed(2)}</span>}
                {layers.sig.quantity != null && (
                  <span className="qty">× {layers.sig.quantity}{task.type === "option" ? " 张" : ""}</span>
                )}
                {layers.sig.showConfirmActions && (
                  <span className="confirm-pair">
                    <ConfirmActions taskId={task.id} variant="compact" />
                  </span>
                )}
              </>
            )}
          </div>
        )}

        {/* Layer 3: ORD */}
        {layers.ord && (
          <div className="layer-ord">
            <span className={`state-dot ${layers.ord.dot}`} />
            <span className="state-text">{layers.ord.text}</span>
            {layers.ord.cum && <span className="cum">{layers.ord.cum}</span>}
            <span className="expander">▾</span>
          </div>
        )}
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div className="signal-detail">
          <div className="detail-block">
            <div className="detail-label">MSG · 原始消息</div>
            <div className="detail-meta">
              domID {task.message.id} · posted {fmtBeijingFull(task.message.posted_at)}
              {task.message.url && (
                <> · <a href={task.message.url} target="_blank" rel="noopener noreferrer">url ↗</a></>
              )}
            </div>
          </div>
          {task.instruction && (
            <div className="detail-block">
              <div className="detail-label">SIG · 解析指令</div>
              <div className="detail-meta">
                {layers.sig?.ctx && <>ctx = {layers.sig.ctx} · </>}
                {layers.sig?.parseDeltaMs != null && <>parse +{layers.sig.parseDeltaMs.toFixed(3)}ms</>}
                {task.type === "option" && task.instruction.strike != null && <> · strike {task.instruction.strike}</>}
                {task.type === "option" && task.instruction.expiry && <> · expiry {task.instruction.expiry}</>}
              </div>
            </div>
          )}
          {(pushEvents.length > 0 || task.order_id) && (
            <div className="detail-block">
              <div className="detail-label">ORD · 推送链</div>
              <PushChain
                events={pushEvents}
                taskStatus={task.status}
                totalQty={task.instruction?.quantity}
                submitOrderId={task.order_id ?? null}
                submitEndIso={null}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

> `ConfirmActions` and `PushChain` are existing components reused directly.

- [ ] **Step 4: Add CSS**

Create `frontend/src/components/Chat/SignalCard.css` — copy the relevant `.signal-bubble`, `.signal-summary`, `.layer-msg / -sig / -ord`, `.side-chip`, `.signal-detail`, etc. blocks from `.design/signal-cards-in-chat.html` (search for `── Signal bubble`). Adapt `--bg-2`, `--source-stock`, etc. references to existing `frontend/src/styles/` palette vars (they should already match).

> If a token isn't defined in the existing frontend CSS, either add it to `frontend/src/styles/tokens.css` or hardcode the literal hex.

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm test -- --run SignalCard
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/SignalCard.tsx frontend/src/components/Chat/SignalCard.css frontend/src/components/Chat/SignalCard.test.tsx
git commit -m "feat(chat): SignalCard component · 3-layer summary + click-to-expand detail"
```

---

## Task 13: `chatTimeline.ts` · 合流 + 模式分流

**Files:**
- Create: `frontend/src/components/Chat/chatTimeline.ts`
- Test: `frontend/src/components/Chat/chatTimeline.test.ts`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/Chat/chatTimeline.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { TaskSummary } from "../../api/domain-types";
import type { ChatMessageOut } from "./chatCards";
import {
  buildTimeline, buildFilterBlocks, buildStreamGroups,
} from "./chatTimeline";

function msg(id: string, author: string, at: string, content = "x"): ChatMessageOut {
  return { id, page_id: "p1", author, posted_at: at, content };
}
function signalTask(id: string, at: string, type: "stock" | "option", url: string): TaskSummary {
  return {
    id, type, status: "FILLED",
    message: {
      id, source: "whop", author: "monitor", content: "x",
      posted_at: at, received_at: at, url,
    },
    instruction: { instruction_type: "BUY", ticker: "X", symbol: "X.US", price: 1, quantity: 1 },
    last_cum_qty: 1, last_cum_avg_price: 1,
    created_at: at, updated_at: at,
  } as TaskSummary;
}
const urlToName: Record<string, string> = {
  "https://stock-a": "TSLL 监听",
  "https://opt-b": "NVDA 期权监听",
};

describe("buildTimeline", () => {
  it("interleaves msgs and signals by posted_at", () => {
    const tl = buildTimeline(
      [msg("m1", "a", "2026-05-20T01:00Z"), msg("m2", "a", "2026-05-20T01:03Z")],
      [signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a")],
      urlToName,
    );
    expect(tl.map(e => e.kind)).toEqual(["msg", "signal", "msg"]);
  });
});

describe("buildFilterBlocks", () => {
  it("aggregates all stock signals into one 正股 card, opt into 期权 card", () => {
    const tl = buildTimeline(
      [msg("m1", "alpha", "2026-05-20T01:00Z")],
      [
        signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a"),
        signalTask("t2", "2026-05-20T01:02Z", "stock", "https://stock-a"),
        signalTask("t3", "2026-05-20T01:03Z", "option", "https://opt-b"),
      ],
      urlToName,
    );
    const blocks = buildFilterBlocks(tl, new Set(["alpha", "TSLL 监听", "NVDA 期权监听"]));
    const kinds = blocks.map(b => b.kind);
    expect(kinds).toContain("chat");
    expect(kinds).toContain("aggregate-stock");
    expect(kinds).toContain("aggregate-option");
    const stockBlock = blocks.find(b => b.kind === "aggregate-stock");
    expect(stockBlock?.tasks).toHaveLength(2);
  });

  it("aggregate card hidden when none of its monitor chips watched", () => {
    const tl = buildTimeline(
      [], [signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a")],
      urlToName,
    );
    const blocks = buildFilterBlocks(tl, new Set([]));
    expect(blocks.find(b => b.kind === "aggregate-stock")).toBeUndefined();
  });
});

describe("buildStreamGroups", () => {
  it("merges consecutive same-author msgs into one group", () => {
    const tl = buildTimeline(
      [
        msg("m1", "a", "2026-05-20T01:00Z"),
        msg("m2", "a", "2026-05-20T01:01Z"),
        msg("m3", "b", "2026-05-20T01:02Z"),
      ], [],
      urlToName,
    );
    const groups = buildStreamGroups(tl, urlToName);
    expect(groups).toHaveLength(2);
    expect(groups[0].entries).toHaveLength(2);
    expect(groups[1].entries).toHaveLength(1);
  });

  it("signal task breaks a group", () => {
    const tl = buildTimeline(
      [
        msg("m1", "a", "2026-05-20T01:00Z"),
        msg("m2", "a", "2026-05-20T01:02Z"),
      ],
      [signalTask("t1", "2026-05-20T01:01Z", "stock", "https://stock-a")],
      urlToName,
    );
    const groups = buildStreamGroups(tl, urlToName);
    expect(groups.map(g => g.sender)).toEqual(["a", "TSLL 监听", "a"]);
  });
});
```

- [ ] **Step 2: Run failing**

```bash
cd frontend && npm test -- --run chatTimeline
```
Expected: FAIL.

- [ ] **Step 3: Implement chatTimeline**

Create `frontend/src/components/Chat/chatTimeline.ts`:

```ts
import type { TaskSummary } from "../../api/domain-types";
import type { ChatMessageOut } from "./chatCards";

export type TimelineEntry =
  | { kind: "msg"; msg: ChatMessageOut }
  | { kind: "signal"; task: TaskSummary };

function postedAt(e: TimelineEntry): string {
  return e.kind === "msg" ? e.msg.posted_at : e.task.message.posted_at;
}

export function buildTimeline(
  messages: ChatMessageOut[],
  tasks: TaskSummary[],
  _urlToMonitorName: Record<string, string>,
): TimelineEntry[] {
  const entries: TimelineEntry[] = [
    ...messages.map((m): TimelineEntry => ({ kind: "msg", msg: m })),
    ...tasks.map((t): TimelineEntry => ({ kind: "signal", task: t })),
  ];
  entries.sort((a, b) => postedAt(a).localeCompare(postedAt(b)));
  return entries;
}

export type FilterBlock =
  | { kind: "chat"; sender: string; messages: ChatMessageOut[] }
  | { kind: "aggregate-stock"; tasks: TaskSummary[]; monitorNames: string[] }
  | { kind: "aggregate-option"; tasks: TaskSummary[]; monitorNames: string[] };

/** Filter mode: build per-sender chat cards + 0-1 aggregate stock card +
 *  0-1 aggregate option card. ``watched`` is the union of selected sender
 *  chip names (humans + monitor names). */
export function buildFilterBlocks(
  timeline: TimelineEntry[],
  watched: Set<string>,
  urlToMonitorName: Record<string, string> = {},
): FilterBlock[] {
  const bySender = new Map<string, ChatMessageOut[]>();
  const stockTasks: TaskSummary[] = [];
  const optionTasks: TaskSummary[] = [];
  const stockMonitors = new Set<string>();
  const optionMonitors = new Set<string>();

  for (const e of timeline) {
    if (e.kind === "msg") {
      if (!watched.has(e.msg.author)) continue;
      const list = bySender.get(e.msg.author) ?? [];
      list.push(e.msg);
      bySender.set(e.msg.author, list);
    } else {
      const name = urlToMonitorName[e.task.message.url ?? ""] ?? "(unknown)";
      if (!watched.has(name)) continue;
      if (e.task.type === "option") {
        optionTasks.push(e.task);
        optionMonitors.add(name);
      } else {
        stockTasks.push(e.task);
        stockMonitors.add(name);
      }
    }
  }

  const blocks: FilterBlock[] = [];
  for (const [sender, messages] of bySender) {
    blocks.push({ kind: "chat", sender, messages });
  }
  if (stockTasks.length > 0) {
    blocks.push({ kind: "aggregate-stock", tasks: stockTasks, monitorNames: [...stockMonitors] });
  }
  if (optionTasks.length > 0) {
    blocks.push({ kind: "aggregate-option", tasks: optionTasks, monitorNames: [...optionMonitors] });
  }
  return blocks;
}

export type StreamGroup =
  | { kind: "msgs"; sender: string; entries: ChatMessageOut[] }
  | { kind: "signal"; sender: string; task: TaskSummary };

/** Highlight (stream) mode: flat chronological list, consecutive same-
 *  sender msg entries merged. Signals are always their own group. */
export function buildStreamGroups(
  timeline: TimelineEntry[],
  urlToMonitorName: Record<string, string> = {},
): StreamGroup[] {
  const out: StreamGroup[] = [];
  let pending: { sender: string; entries: ChatMessageOut[] } | null = null;

  const flush = () => { if (pending) { out.push({ kind: "msgs", ...pending }); pending = null; } };

  for (const e of timeline) {
    if (e.kind === "msg") {
      const sender = e.msg.author;
      if (pending && pending.sender === sender) {
        pending.entries.push(e.msg);
      } else {
        flush();
        pending = { sender, entries: [e.msg] };
      }
    } else {
      flush();
      const sender = urlToMonitorName[e.task.message.url ?? ""] ?? "(unknown)";
      out.push({ kind: "signal", sender, task: e.task });
    }
  }
  flush();
  return out;
}

/** Compatibility helper for callers expecting `groups` semantics that read `.sender`. */
export type StreamGroupForTests = StreamGroup & { sender: string };
```

- [ ] **Step 4: Run tests**

```bash
cd frontend && npm test -- --run chatTimeline
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Chat/chatTimeline.ts frontend/src/components/Chat/chatTimeline.test.ts
git commit -m "feat(chat): chatTimeline merger + filter blocks + stream groups (pure fns)"
```

---

## Task 14: `StreamView.tsx` · highlight 模式扁平流

**Files:**
- Create: `frontend/src/components/Chat/StreamView.tsx`
- Test: `frontend/src/components/Chat/StreamView.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/Chat/StreamView.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StreamView } from "./StreamView";
import type { StreamGroup } from "./chatTimeline";

function makeStream(): StreamGroup[] {
  return [
    {
      kind: "msgs",
      sender: "alpha",
      entries: [
        { id: "m1", page_id: "p", author: "alpha", content: "hi", posted_at: "2026-05-20T01:00Z" },
        { id: "m2", page_id: "p", author: "alpha", content: "again", posted_at: "2026-05-20T01:01Z" },
      ],
    },
    {
      kind: "signal",
      sender: "TSLL 监听",
      task: {
        id: "t1", type: "stock", status: "FILLED",
        message: { id: "t1", source: "whop", author: "TSLL 监听",
                  content: "buy", posted_at: "2026-05-20T01:02Z",
                  received_at: "2026-05-20T01:02Z", url: "https://x" },
        instruction: { instruction_type: "BUY", ticker: "TSLL", symbol: "TSLL.US", price: 200, quantity: 100 },
        last_cum_qty: 100, last_cum_avg_price: 199.87,
        created_at: "x", updated_at: "x",
      } as any,
    },
  ];
}

describe("StreamView", () => {
  it("renders consecutive msg group + signal group", () => {
    render(<StreamView groups={makeStream()} watched={new Set(["alpha"])}
      pushEventsByTask={{}} expandedTaskId={null} onToggleTask={() => {}}
      autoTrade={true} />);
    expect(screen.getByText("hi")).toBeInTheDocument();
    expect(screen.getByText("again")).toBeInTheDocument();
    expect(screen.getByText(/TSLL\.US/)).toBeInTheDocument();
  });

  it("watched flag applies class for tinted bubble", () => {
    const { container } = render(<StreamView groups={makeStream()}
      watched={new Set(["alpha"])} pushEventsByTask={{}}
      expandedTaskId={null} onToggleTask={() => {}} autoTrade={true} />);
    const alphaGroup = container.querySelector('[data-sender="alpha"]');
    expect(alphaGroup?.classList.contains("watched")).toBe(true);
  });
});
```

- [ ] **Step 2: Run failing**

```bash
cd frontend && npm test -- --run StreamView
```
Expected: FAIL.

- [ ] **Step 3: Implement StreamView**

Create `frontend/src/components/Chat/StreamView.tsx`:

```tsx
import type { PushEvent } from "../../api/domain-types";
import { paletteColorFor } from "./avatarPalette";
import { SignalCard } from "./SignalCard";
import type { StreamGroup } from "./chatTimeline";

interface StreamViewProps {
  groups: StreamGroup[];
  watched: Set<string>;
  pushEventsByTask: Record<string, PushEvent[]>;
  expandedTaskId: string | null;
  onToggleTask(taskId: string): void;
  autoTrade: boolean;
}

function fmtTime(iso: string): string {
  const normalized = /[Zz]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`;
  const d = new Date(normalized);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function StreamView({
  groups, watched, pushEventsByTask, expandedTaskId, onToggleTask, autoTrade,
}: StreamViewProps): JSX.Element {
  return (
    <div className="stream-view">
      {groups.map((g, i) => (
        <div
          key={i}
          className={`stream-group${watched.has(g.sender) ? " watched" : ""}`}
          data-sender={g.sender}
        >
          <div className="stream-head">
            <span
              className="avatar-sm"
              style={{ background: paletteColorFor(g.sender) }}
            >
              {g.sender.slice(-1)}
            </span>
            <span className="stream-author">{g.sender}</span>
            <span className="stream-time">
              {fmtTime(g.kind === "msgs" ? g.entries[0].posted_at : g.task.message.posted_at)}
            </span>
          </div>
          <div className="stream-body">
            {g.kind === "msgs"
              ? g.entries.map((m) => <div key={m.id} className="stream-bubble">{m.content}</div>)
              : (
                <SignalCard
                  task={g.task}
                  pushEvents={pushEventsByTask[g.task.id] ?? []}
                  expanded={expandedTaskId === g.task.id}
                  onToggle={() => onToggleTask(g.task.id)}
                  autoTrade={autoTrade}
                />
              )}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Add stream-view CSS**

Append to `frontend/src/components/Chat/ChatBoardPanel.css` (or create a new `StreamView.css` if preferred). Copy the `.stream-view / -group / -head / -body / -bubble` blocks from `.design/signal-cards-in-chat.html`.

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm test -- --run StreamView
```
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Chat/StreamView.tsx frontend/src/components/Chat/StreamView.test.tsx frontend/src/components/Chat/ChatBoardPanel.css
git commit -m "feat(chat): StreamView for highlight-mode flat chronological list"
```

---

## Task 15: `ChatBoardPanel` 集成 · 拉子页 + 合流 + 双模式渲染

**Files:**
- Modify: `frontend/src/components/Chat/ChatBoardPanel.tsx`

- [ ] **Step 1: Update component**

Rewrite the body of `ChatBoardPanel` to:

1. On mount + when `activePage.source === "chat"`, fetch children via `api.listWhopPages({ parentChatId: page.id })` → `useChildPagesStore.setByParent`.
2. After children load, build `childUrls = children.map(c => c.url)`. Fetch tasks for the current week: `api.listTasks({ urls: childUrls, week_start, week_end, limit: 500 })` → `useTasksStore.setInitialTasks` or per-task `upsertTask`.
3. Compute `urlToMonitorName: Record<string, string>` from children.
4. Build `timeline = buildTimeline(messages, childTasks, urlToMonitorName)`.
5. If `mode === "filter"`: `blocks = buildFilterBlocks(timeline, watchedSet, urlToMonitorName)`; render each block. Render chat blocks via existing `ChatCard`; render aggregate-stock / aggregate-option as new inline JSX (header + thread of `SignalCard`s).
6. If `mode === "highlight"`: `groups = buildStreamGroups(timeline, urlToMonitorName)`; render `<StreamView groups={groups} watched={watchedSet} … />`.

Key replacement of current routing logic (around lines 107-123):

```tsx
const children = useChildPagesStore((s) => s.byParent[page.id] ?? []);
const childUrls = useMemo(() => children.map(c => c.url), [children]);
const urlToMonitorName = useMemo(() =>
  Object.fromEntries(children.map(c => [c.url, c.name])),
  [children]
);
const childTasks = useTasksStore((s) =>
  s.tasks.filter(t => t.message.url != null && childUrls.includes(t.message.url))
);
const pushEventsByTask = useTasksStore((s) => s.pushEventsByTask);

// Fetch children + child tasks on mount / page change
useEffect(() => {
  let alive = true;
  (async () => {
    try {
      const r = await api.listWhopPages({ parentChatId: page.id });
      if (!alive) return;
      useChildPagesStore.getState().setByParent(page.id, r.pages);

      const urls = r.pages.map(p => p.url);
      if (urls.length === 0) return;
      // week bounds derived from current week ISO key; helper:
      const { start, end } = isoWeekBounds(week);
      const tr = await api.listTasks({
        urls, week_start: start, week_end: end, limit: 500
      });
      if (!alive) return;
      for (const t of tr.tasks) useTasksStore.getState().upsertTask(t);
    } catch (e) { console.warn("chat children fetch failed:", e); }
  })();
  return () => { alive = false; };
}, [page.id, week]);

const [expandedSignalId, setExpandedSignalId] = useState<string | null>(null);
const toggleSignal = (taskId: string) =>
  setExpandedSignalId(curr => curr === taskId ? null : taskId);

const watchedSet = new Set(watchedSenders);

const timeline = useMemo(
  () => buildTimeline(messages, childTasks, urlToMonitorName),
  [messages, childTasks, urlToMonitorName]
);

// Routing
let body: React.ReactNode;
if (timeline.length === 0) {
  body = <div className="chat-empty">本周无消息</div>;
} else if (mode === "filter" && watchedSenders.length > 0) {
  const blocks = buildFilterBlocks(timeline, watchedSet, urlToMonitorName);
  body = blocks.map((b, i) => {
    if (b.kind === "chat") {
      // Reuse existing groupIntoCards for a single-sender slice (no signals)
      const cards = groupIntoCards(b.messages, new Set([b.sender]));
      return cards.map(c => <ChatCard key={c.id} card={c} />);
    }
    const sourceCls = b.kind === "aggregate-stock" ? "stock" : "option";
    const title = b.kind === "aggregate-stock" ? "正股信号" : "期权信号";
    return (
      <div key={i} className={`chat-card aggregate ${sourceCls}`}>
        <div className="chat-card-head">
          <span className="avatar-lg" style={{ background: sourceCls === "stock" ? "#5fbf8b" : "#8b6fcf" }}>∑</span>
          <span className="sender-name">{title}</span>
          <span className="meta">
            <span className="msg-count">{b.tasks.length} signals</span>
            <span>{b.monitorNames.join(" + ")}</span>
          </span>
        </div>
        <div className="chat-thread">
          {b.tasks.map(t => (
            <div key={t.id} className="chat-row">
              <SignalCard
                task={t}
                pushEvents={pushEventsByTask[t.id] ?? []}
                expanded={expandedSignalId === t.id}
                onToggle={() => toggleSignal(t.id)}
                autoTrade={autoTrade}
              />
            </div>
          ))}
        </div>
      </div>
    );
  });
} else {
  // highlight mode (or no watched in filter mode → also fall through to stream)
  const groups = buildStreamGroups(timeline, urlToMonitorName);
  body = <StreamView
    groups={groups}
    watched={watchedSet}
    pushEventsByTask={pushEventsByTask}
    expandedTaskId={expandedSignalId}
    onToggleTask={toggleSignal}
    autoTrade={autoTrade}
  />;
}
```

> `isoWeekBounds(week)` should return ISO datetimes for week start (Mon 00:00) and end (next Mon 00:00). Use the existing util in `frontend/src/components/Dashboard/weekUtils.ts` if it exposes one; else add a small helper.

> `autoTrade` flag needs to be passed in; either prop-drill from `App.tsx`'s `Dashboard` or read from `useConnStore`. Use `useConnStore((s) => s.autoTrade)`.

- [ ] **Step 2: Tsc + vitest smoke**

```bash
cd frontend && npx tsc --noEmit && npm test -- --run
```
Expected: clean + green (existing tests unaffected; new code may add tests in following tasks).

- [ ] **Step 3: Manual sanity check**

```bash
make backend-dev      # terminal 1
make frontend-dev     # terminal 2
```

In browser:
- Add a chat page in Whop 管理.
- Open chat page → Settings (modal NOT yet has 挂载监听 section; that's Task 19).
- Confirm panel still renders existing chat behaviour (no monitors → no signals shown).
- Add a stock sub-monitor via REST manually (or wait for Task 19), verify it appears in the merged stream.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/ChatBoardPanel.tsx
git commit -m "feat(chat): merge sub-monitor tasks into ChatBoardPanel · filter / highlight render"
```

---

## Task 16: `ChatSenderBar` 监听 chip 加 source dot 前缀

**Files:**
- Modify: `frontend/src/components/Chat/ChatSenderBar.tsx`
- Modify: `frontend/src/components/Chat/ChatBoardPanel.tsx` (pass monitor info)

- [ ] **Step 1: Plumb monitor info through props**

Update `ChatSenderBar` to accept `monitorSources: Record<string, "stock" | "option">` keyed by author name; in `ChatBoardPanel`, build it from `children`:

```ts
const monitorSources = Object.fromEntries(
  children.map(c => [c.name, c.source as "stock" | "option"])
);
```

Pass to `<ChatSenderBar ... monitorSources={monitorSources} />`.

Also extend the `authors` array passed in to merge in child page names:

```ts
const authorsWithMonitors = useMemo(() => {
  const set = new Set([...authors.map(a => a.name), ...children.map(c => c.name)]);
  return Array.from(set).map(name => {
    const existing = authors.find(a => a.name === name);
    return existing ?? { name, count: 0 };
  });
}, [authors, children]);
```

- [ ] **Step 2: Render the dot in `ChatSenderBar`**

In `ChatSenderBar.tsx`, when rendering each chip, if `monitorSources[name]` is set, render a leading 6px dot in the appropriate color:

```tsx
const source = monitorSources[name];
return (
  <button className={`sender-chip ${source ? "monitor" : ""} ${watched ? "on" : ""}`} key={name}>
    {source && <span className={`src-dot ${source}`} />}
    <span className="avatar">{name.slice(-1)}</span>
    {name}
    <span className="cnt">{count}</span>
  </button>
);
```

CSS in `ChatSenderBar.css` (or wherever chip styles live): copy `.sender-chip.monitor / .src-dot` rules from `.design/signal-cards-in-chat.html`.

- [ ] **Step 3: Tsc + tests**

```bash
cd frontend && npx tsc --noEmit && npm test -- --run
```
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/ChatSenderBar.tsx frontend/src/components/Chat/ChatBoardPanel.tsx frontend/src/components/Chat/ChatSenderBar.css
git commit -m "feat(chat): ChatSenderBar shows monitor sender chips with source dot prefix"
```

---

## Task 17: 抽 `TickerWhitelistEditor` 自 `PageWhitelistBar`

**Files:**
- Create: `frontend/src/components/common/TickerWhitelistEditor.tsx`
- Modify: `frontend/src/components/Dashboard/PageWhitelistBar.tsx` (refactor to use new component)

- [ ] **Step 1: Identify the pure-UI core**

Read `frontend/src/components/Dashboard/PageWhitelistBar.tsx` to identify:
- Input props it would need if turned into pure UI: `tickers: Record<string, {trade_quantity: number}>`, `onChange(next): void`, `disabled?: boolean`, `error?: string | null`.
- Side effects (API calls) it does now → move those OUT to remain in `PageWhitelistBar` (which becomes a wrapper).

- [ ] **Step 2: Create the pure component**

Create `frontend/src/components/common/TickerWhitelistEditor.tsx`:

```tsx
import { useState } from "react";
import type { TickerConfig } from "../../api/domain-types";

interface Props {
  tickers: Record<string, TickerConfig>;
  onChange(next: Record<string, TickerConfig>): void;
  disabled?: boolean;
  error?: string | null;
}

export function TickerWhitelistEditor({ tickers, onChange, disabled, error }: Props) {
  const [draft, setDraft] = useState<{ symbol: string; qty: string }>({ symbol: "", qty: "" });

  const removeOne = (sym: string) => {
    const next = { ...tickers };
    delete next[sym];
    onChange(next);
  };

  const addOne = () => {
    const sym = draft.symbol.trim().toUpperCase();
    const qty = Number(draft.qty);
    if (!sym || !Number.isFinite(qty) || qty <= 0) return;
    onChange({ ...tickers, [sym]: { trade_quantity: qty } });
    setDraft({ symbol: "", qty: "" });
  };

  return (
    <div className="ticker-whitelist-editor">
      <div className="ticker-chips">
        {Object.entries(tickers).map(([sym, cfg]) => (
          <button
            key={sym}
            type="button"
            className="tk-chip"
            disabled={disabled}
            onClick={() => removeOne(sym)}
            title={`点击删除 ${sym}`}
          >
            <span>{sym}</span>
            <span className="tk-qty">· {cfg.trade_quantity}</span>
            <span className="tk-x">✕</span>
          </button>
        ))}
        <div className="tk-add-form">
          <input
            placeholder="SYMBOL"
            value={draft.symbol}
            disabled={disabled}
            onChange={(e) => setDraft({ ...draft, symbol: e.target.value })}
            style={{ width: 80 }}
          />
          <input
            placeholder="qty"
            type="number"
            min={1}
            value={draft.qty}
            disabled={disabled}
            onChange={(e) => setDraft({ ...draft, qty: e.target.value })}
            style={{ width: 60 }}
          />
          <button type="button" className="tk-add" disabled={disabled} onClick={addOne}>
            + 添加
          </button>
        </div>
      </div>
      {error && <div className="whitelist-error">{error}</div>}
    </div>
  );
}
```

- [ ] **Step 3: Refactor `PageWhitelistBar`**

Update `PageWhitelistBar.tsx` to be a thin shell:
- Holds local pending state + error.
- On `onChange` from editor, debounce + call `api.updateWhopPageSettings(page.id, { tickers: next })`.
- Renders `<TickerWhitelistEditor tickers={page.settings.tickers ?? {}} onChange={...} error={err} />`.

Keep existing `PageWhitelistBar` API (props / outer styling) so the Dashboard route doesn't change.

- [ ] **Step 4: Tsc + tests**

```bash
cd frontend && npx tsc --noEmit && npm test -- --run
```
Expected: green. Existing `PageWhitelistBar` tests should still pass since the wrapper behaviour is preserved.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/common/TickerWhitelistEditor.tsx frontend/src/components/Dashboard/PageWhitelistBar.tsx
git commit -m "refactor(chat): extract TickerWhitelistEditor for reuse by attached-monitors"
```

---

## Task 18: 抽 `OptionQuantityEditor` 自 `PageSettingsModal` 期权块

**Files:**
- Create: `frontend/src/components/common/OptionQuantityEditor.tsx`
- Modify: `frontend/src/components/Dashboard/PageSettingsModal.tsx` (replace inline option block)

- [ ] **Step 1: Create the pure component**

Create `frontend/src/components/common/OptionQuantityEditor.tsx`:

```tsx
interface OptionQtyValue {
  option_buy_quantity_enabled: boolean;
  option_buy_quantity: number | null;
  option_total_price_limit_enabled: boolean;
  option_total_price_limit: number | null;
}

interface Props {
  value: OptionQtyValue;
  onChange(next: OptionQtyValue): void;
  disabled?: boolean;
}

export function OptionQuantityEditor({ value, onChange, disabled }: Props) {
  return (
    <div className="option-qty-editor">
      <div className="option-rule-row">
        <label className="option-rule-toggle">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value.option_buy_quantity_enabled}
            onChange={(e) => onChange({ ...value, option_buy_quantity_enabled: e.target.checked })}
          />
          <span>启用期权购买张数</span>
        </label>
        <input
          type="number" min={1} step={1}
          disabled={disabled || !value.option_buy_quantity_enabled}
          value={value.option_buy_quantity ?? ""}
          placeholder="期权购买张数"
          className="option-rule-input"
          onChange={(e) => {
            const n = e.target.value === "" ? null : Number(e.target.value);
            onChange({ ...value, option_buy_quantity: n });
          }}
        />
        <p className="hint small option-rule-desc">固定按该张数下单</p>
      </div>

      <div className="option-rule-row">
        <label className="option-rule-toggle">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value.option_total_price_limit_enabled}
            onChange={(e) => onChange({ ...value, option_total_price_limit_enabled: e.target.checked })}
          />
          <span>启用期权总价上限（USD）</span>
        </label>
        <input
          type="number" min={0} step={0.01}
          disabled={disabled || !value.option_total_price_limit_enabled}
          value={value.option_total_price_limit ?? ""}
          placeholder="期权总价上限（USD）"
          className="option-rule-input"
          onChange={(e) => {
            const n = e.target.value === "" ? null : Number(e.target.value);
            onChange({ ...value, option_total_price_limit: n });
          }}
        />
        <p className="hint small option-rule-desc">按总价可覆盖的最大张数</p>
      </div>

      <p className="hint small">
        两项都不启用时，trader 会跳过下单并 SKIPPED；启用一项按该规则计算，启用两项按"取更小张数"。
      </p>
    </div>
  );
}
```

- [ ] **Step 2: Refactor `PageSettingsModal` option block**

Replace the existing `if (page.source === "option") { ... two raw inline rule rows ... }` section with:

```tsx
{page.source === "option" && (
  <section>
    <h4>期权购买数量配置</h4>
    <OptionQuantityEditor
      value={{
        option_buy_quantity_enabled: optionBuyQtyEnabled,
        option_buy_quantity: optionBuyQty === "" ? null : Number(optionBuyQty),
        option_total_price_limit_enabled: optionTotalLimitEnabled,
        option_total_price_limit: optionTotalLimit === "" ? null : Number(optionTotalLimit),
      }}
      onChange={(v) => {
        setOptionBuyQtyEnabled(v.option_buy_quantity_enabled);
        setOptionBuyQty(v.option_buy_quantity == null ? "" : String(v.option_buy_quantity));
        setOptionTotalLimitEnabled(v.option_total_price_limit_enabled);
        setOptionTotalLimit(v.option_total_price_limit == null ? "" : String(v.option_total_price_limit));
      }}
    />
  </section>
)}
```

- [ ] **Step 3: Tsc + existing test suite**

```bash
cd frontend && npx tsc --noEmit && npm test -- --run
```
Expected: green; the PageSettingsModal test should still pass (its option-block behaviour is unchanged).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/common/OptionQuantityEditor.tsx frontend/src/components/Dashboard/PageSettingsModal.tsx
git commit -m "refactor: extract OptionQuantityEditor for reuse by attached-monitors"
```

---

## Task 19: `AttachedMonitorsSection` · 子页列表 + 行展开 + 添加表单

**Files:**
- Create: `frontend/src/components/Dashboard/AttachedMonitorsSection.tsx`
- Create: `frontend/src/components/Dashboard/AttachedMonitorsSection.css`
- Test: `frontend/src/components/Dashboard/AttachedMonitorsSection.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/src/components/Dashboard/AttachedMonitorsSection.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AttachedMonitorsSection } from "./AttachedMonitorsSection";
import type { WhopPage } from "../../api/domain-types";

const stockChild: WhopPage = {
  id: "s1", url: "https://stock", source: "stock", name: "TSLL 监听",
  added_at: "x", running: true, started_at: null, last_poll_at: null,
  messages_published: 0, last_error: null, parent_chat_id: "chat1",
  settings: { tickers: { "TSLL.US": { trade_quantity: 100 } } } as any,
};

vi.mock("../../api/http", () => ({
  api: {
    addWhopPage: vi.fn().mockResolvedValue({}),
    startWhopPage: vi.fn(),
    stopWhopPage: vi.fn(),
    restartWhopPage: vi.fn(),
    removeWhopPage: vi.fn(),
    updateWhopPageSettings: vi.fn(),
  },
}));

describe("AttachedMonitorsSection", () => {
  it("renders a row per child + add form", () => {
    render(<AttachedMonitorsSection parentId="chat1" children={[stockChild]} onRefresh={() => {}} />);
    expect(screen.getByText("TSLL 监听")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /添加监听/ })).toBeInTheDocument();
  });

  it("expands a row to show the editor block", () => {
    render(<AttachedMonitorsSection parentId="chat1" children={[stockChild]} onRefresh={() => {}} />);
    fireEvent.click(screen.getByText("TSLL 监听").closest(".mon-head")!);
    expect(screen.getByText(/Ticker 白名单/)).toBeInTheDocument();
  });

  it("disables chat option in source select", () => {
    render(<AttachedMonitorsSection parentId="chat1" children={[]} onRefresh={() => {}} />);
    const chatOption = screen.getByRole("option", { name: /聊天/ }) as HTMLOptionElement;
    expect(chatOption.disabled).toBe(true);
  });
});
```

- [ ] **Step 2: Run failing**

```bash
cd frontend && npm test -- --run AttachedMonitorsSection
```
Expected: FAIL.

- [ ] **Step 3: Implement component**

Create `frontend/src/components/Dashboard/AttachedMonitorsSection.tsx`:

```tsx
import { useState } from "react";
import type { WhopPage, WhopPageSettings, TickerConfig } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { TickerWhitelistEditor } from "../common/TickerWhitelistEditor";
import { OptionQuantityEditor } from "../common/OptionQuantityEditor";
import "./AttachedMonitorsSection.css";

interface Props {
  parentId: string;
  children: WhopPage[];
  onRefresh(): void;
}

export function AttachedMonitorsSection({ parentId, children, onRefresh }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [addForm, setAddForm] = useState({ url: "", source: "stock" as "stock" | "option", name: "" });
  const [addErr, setAddErr] = useState<string | null>(null);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setAddErr(null);
    try {
      await api.addWhopPage({
        url: addForm.url.trim(),
        source: addForm.source,
        name: addForm.name.trim() || null,
        parent_chat_id: parentId,
      });
      setAddForm({ url: "", source: "stock", name: "" });
      onRefresh();
    } catch (e) {
      setAddErr(e instanceof HttpError ? e.message : String(e));
    }
  };

  return (
    <section className="attached-monitors">
      <h4>挂载监听 <span className="count">{children.length} 个</span></h4>
      <p className="hint">从这里管理本聊天页关联的正股 / 期权监听 — 每个 URL 对应一个 sender，消息会以信号卡形式出现在聊天列表里。</p>

      <div className="mon-list">
        {children.map((c) => (
          <MonRow
            key={c.id}
            page={c}
            expanded={expandedId === c.id}
            onToggle={() => setExpandedId(curr => curr === c.id ? null : c.id)}
            onRefresh={onRefresh}
          />
        ))}
      </div>

      <form className="add-form" onSubmit={handleAdd}>
        <div className="add-title">添加新监听</div>
        <input
          type="url"
          placeholder="https://whop.com/joined/<channel>/app/"
          value={addForm.url}
          onChange={(e) => setAddForm({ ...addForm, url: e.target.value })}
          required
        />
        <div className="add-row">
          <select
            value={addForm.source}
            onChange={(e) => setAddForm({ ...addForm, source: e.target.value as "stock" | "option" })}
          >
            <option value="stock">正股 (stock)</option>
            <option value="option">期权 (option)</option>
            <option value="chat" disabled>聊天 (chat) — 子监听不可</option>
          </select>
          <input
            type="text"
            placeholder="名称（如：TSLL 监听）"
            value={addForm.name}
            onChange={(e) => setAddForm({ ...addForm, name: e.target.value })}
          />
        </div>
        {addErr && <div className="add-error">{addErr}</div>}
        <button type="submit" className="btn primary">+ 添加监听</button>
      </form>
    </section>
  );
}

interface RowProps {
  page: WhopPage;
  expanded: boolean;
  onToggle(): void;
  onRefresh(): void;
}

function MonRow({ page, expanded, onToggle, onRefresh }: RowProps) {
  const [acting, setActing] = useState(false);

  const guard = async (fn: () => Promise<unknown>) => {
    setActing(true);
    try { await fn(); onRefresh(); }
    catch (e) { alert(e instanceof Error ? e.message : String(e)); }
    finally { setActing(false); }
  };

  const isRunning = page.running;
  const isError = Boolean(page.last_error);

  return (
    <div className={`mon-row ${page.source} ${expanded ? "expanded" : ""} ${isError ? "error" : ""}`}>
      <div className="mon-head" onClick={(e) => {
        if ((e.target as HTMLElement).closest(".mon-btn")) return;
        onToggle();
      }}>
        <span className={`src-dot ${page.source}`} />
        <span className={`type-chip ${page.source}`}>{page.source === "stock" ? "正股" : "期权"}</span>
        <span className="mon-name">{page.name}</span>
        <span className="mon-url" title={page.url}>{page.url}</span>
        <span className="mon-actions">
          <span className={`mon-status ${isError ? "error" : isRunning ? "running" : "stopped"}`}>
            <span className="state-dot" />
            {isError ? "错误" : isRunning ? "运行中" : "已停"}
          </span>
          <button type="button" className="mon-btn icon-only" disabled={acting}
            onClick={(e) => { e.stopPropagation(); guard(() => isRunning ? api.stopWhopPage(page.id) : api.startWhopPage(page.id)); }}>
            {isRunning ? "⏸" : "▶"}
          </button>
          <button type="button" className="mon-btn icon-only" disabled={acting}
            onClick={(e) => { e.stopPropagation(); guard(() => api.restartWhopPage(page.id)); }}>
            ↻
          </button>
          <button type="button" className="mon-btn icon-only danger" disabled={acting}
            onClick={(e) => {
              e.stopPropagation();
              if (!confirm(`确认移除 "${page.name}"？`)) return;
              guard(() => api.removeWhopPage(page.id));
            }}>
            ✕
          </button>
          <span className="mon-expand">▾</span>
        </span>
      </div>

      {expanded && (
        <div className="mon-body">
          {isError && page.last_error && (
            <div className="error-banner">last_error: {page.last_error}</div>
          )}
          {page.source === "stock" && (
            <div className="editor-block">
              <div className="editor-label">Ticker 白名单</div>
              <TickerWhitelistEditor
                tickers={(page.settings.tickers ?? {}) as Record<string, TickerConfig>}
                onChange={(next) => api.updateWhopPageSettings(page.id, { tickers: next } as Partial<WhopPageSettings>).then(onRefresh)}
              />
            </div>
          )}
          {page.source === "option" && (
            <div className="editor-block">
              <div className="editor-label">期权购买数量配置</div>
              <OptionQuantityEditor
                value={{
                  option_buy_quantity_enabled: Boolean(page.settings.option_buy_quantity_enabled),
                  option_buy_quantity: page.settings.option_buy_quantity ?? null,
                  option_total_price_limit_enabled: Boolean(page.settings.option_total_price_limit_enabled),
                  option_total_price_limit: page.settings.option_total_price_limit ?? null,
                }}
                onChange={(v) => api.updateWhopPageSettings(page.id, v as Partial<WhopPageSettings>).then(onRefresh)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

> If `api.startWhopPage / stopWhopPage` aren't in `http.ts`, add them as small wrappers around `POST /api/whop/pages/{id}/start` and `/stop`.

- [ ] **Step 4: CSS**

Create `frontend/src/components/Dashboard/AttachedMonitorsSection.css` — copy `.mon-list / .mon-row / .mon-head / .mon-status / .mon-btn / .mon-body / .error-banner / .editor-block / .add-form` rules from `.design/chat-settings-monitors.html`.

- [ ] **Step 5: Run tests**

```bash
cd frontend && npm test -- --run AttachedMonitorsSection
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Dashboard/AttachedMonitorsSection.tsx frontend/src/components/Dashboard/AttachedMonitorsSection.css frontend/src/components/Dashboard/AttachedMonitorsSection.test.tsx
git commit -m "feat(dashboard): AttachedMonitorsSection · sub-monitor CRUD + inline editors"
```

---

## Task 20: `PageSettingsModal` · 接入 AttachedMonitorsSection

**Files:**
- Modify: `frontend/src/components/Dashboard/PageSettingsModal.tsx`

- [ ] **Step 1: Insert section when source === "chat"**

In `PageSettingsModal.tsx` body, after the general-config sections and before the danger-zone, add:

```tsx
{page.source === "chat" && (
  <AttachedMonitorsSection
    parentId={page.id}
    children={children}
    onRefresh={refetchChildren}
  />
)}
```

Add at the top of the component body:

```tsx
const children = useChildPagesStore((s) => s.byParent[page.id] ?? []);

const refetchChildren = useCallback(async () => {
  try {
    const r = await api.listWhopPages({ parentChatId: page.id });
    useChildPagesStore.getState().setByParent(page.id, r.pages);
  } catch (e) {
    console.warn("refetch children failed:", e);
  }
}, [page.id]);

useEffect(() => {
  if (page.source === "chat") refetchChildren();
}, [page.id, page.source, refetchChildren]);
```

- [ ] **Step 2: Tsc + tests**

```bash
cd frontend && npx tsc --noEmit && npm test -- --run
```
Expected: green.

- [ ] **Step 3: Smoke**

```bash
make backend-dev      # 1
make frontend-dev     # 2
```

- Add a chat page.
- Open its settings → "挂载监听" section appears with empty list + add form.
- Add a stock sub-monitor → row appears.
- Click row to expand → ticker whitelist editor shows.
- Add ticker → it persists across modal close + reopen.
- Stop / start / restart buttons work; state dot updates.
- Close modal → return to chat board → signal cards appear when listener emits messages.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Dashboard/PageSettingsModal.tsx
git commit -m "feat(dashboard): chat pages' settings modal shows AttachedMonitorsSection"
```

---

## Task 21: 集成验收测试 (e2e)

**Files:**
- Modify or extend: `backend/tests/e2e/test_chat_signal_cards.py` (new)

- [ ] **Step 1: Write e2e**

Create `backend/tests/e2e/test_chat_signal_cards.py`:

```python
"""e2e: chat parent page with attached stock sub-monitor renders signal."""
import asyncio
import pytest


@pytest.mark.asyncio
async def test_chat_with_stock_submonitor_produces_signal(client, event_bus, fake_whop):
    # 1. Create chat parent
    chat = (await client.post("/api/whop/pages", json={
        "url": fake_whop.url_for("alpha-room"),
        "source": "chat",
        "name": "alpha-room",
    })).json()

    # 2. Attach a stock sub-monitor
    sub = (await client.post("/api/whop/pages", json={
        "url": fake_whop.url_for("tsll-signals"),
        "source": "stock",
        "name": "TSLL 监听",
        "parent_chat_id": chat["id"],
    })).json()

    # 3. Start the sub-monitor listener
    await client.post(f"/api/whop/pages/{sub['id']}/start")

    # 4. Make fake_whop emit a message matching stock parser
    fake_whop.push_message(
        page="tsll-signals",
        author="alpha_trader",
        content="buying TSLL @ 200 × 100",
    )

    # 5. Wait for the task pipeline to complete
    await asyncio.sleep(0.5)

    # 6. Query tasks by url for the sub
    r = await client.get(f"/api/tasks?urls={sub['url']}")
    tasks = r.json()["tasks"]
    assert len(tasks) == 1
    assert tasks[0]["type"] == "stock"
    assert tasks[0]["instruction"]["ticker"] == "TSLL"

    # 7. List children of the chat parent (REST shape used by ChatBoardPanel)
    r = await client.get(f"/api/whop/pages?parent_chat_id={chat['id']}")
    assert any(p["id"] == sub["id"] for p in r.json()["pages"])

    # 8. List the standalone top-level pages — sub should NOT appear
    r = await client.get("/api/whop/pages")
    assert all(p["parent_chat_id"] is None for p in r.json()["pages"])
    assert sub["id"] not in {p["id"] for p in r.json()["pages"]}


@pytest.mark.asyncio
async def test_removing_chat_orphans_sub_monitor(client, fake_whop):
    chat = (await client.post("/api/whop/pages", json={
        "url": fake_whop.url_for("alpha-room"),
        "source": "chat",
        "name": "alpha-room",
    })).json()
    sub = (await client.post("/api/whop/pages", json={
        "url": fake_whop.url_for("tsll-signals"),
        "source": "stock",
        "name": "TSLL 监听",
        "parent_chat_id": chat["id"],
    })).json()

    # Remove the chat parent
    r = await client.delete(f"/api/whop/pages/{chat['id']}")
    assert r.status_code == 204

    # Sub-monitor survives, now top-level
    r = await client.get("/api/whop/pages")
    ids = {p["id"] for p in r.json()["pages"]}
    assert sub["id"] in ids
    survivor = next(p for p in r.json()["pages"] if p["id"] == sub["id"])
    assert survivor["parent_chat_id"] is None
```

> If a `fake_whop` fixture doesn't exist, this becomes the canonical place to add it — a Playwright stub that exposes a `push_message` API. Or replace with an existing in-memory fake; check `backend/tests/conftest.py` for the helper.

- [ ] **Step 2: Run**

```bash
cd backend && uv run pytest tests/e2e/test_chat_signal_cards.py -v
```
Expected: pass (may take a few seconds due to async listener bootstrap).

- [ ] **Step 3: Run full suite + mypy + frontend tests**

```bash
cd backend && uv run pytest -x -q && uv run mypy app && cd ../frontend && npm test -- --run && npx tsc --noEmit
```
Expected: green.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/e2e/test_chat_signal_cards.py
git commit -m "test(e2e): chat parent + stock sub-monitor produces signal; cascade removal"
```

---

## Task 22: 文档 + 收尾

**Files:**
- Modify: `README.md` (mini section on挂载监听 if a relevant module-list table exists)

- [ ] **Step 1: README touch**

Find the "Frontend (`frontend/src/`)" module table in README. Add rows for:

```
| `components/Chat/SignalCard.tsx`          | 信号卡（folded + expanded） |
| `components/Chat/StreamView.tsx`          | highlight 模式扁平流          |
| `components/Chat/chatTimeline.ts`         | chat msg + child task 合流 / 模式分流 |
| `components/Dashboard/AttachedMonitorsSection.tsx` | chat 页设置弹窗的挂载监听区块 |
| `stores/childPages.ts`                    | chat parent → sub-monitor 注册表 |
```

If the README has a feature-list or "Whop 监听 UI 工作流" subsection, add a 1-2 line note: "chat 页的设置弹窗内可挂载 stock/option 子监听，子监听产生的信号以 SignalCard bubble 嵌入到聊天流里"。

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: note chat-page sub-monitor feature in module map"
```

- [ ] **Step 3: 最终全套验证**

```bash
cd backend && uv run pytest -x -q && uv run mypy app && uv run ruff check app
cd ../frontend && npm test -- --run && npx tsc --noEmit
```
Expected: all green.

---

## Self-Review Notes (during plan authoring)

- ✅ 每个 spec 章节都映射到至少一个任务：
  - §"数据模型 / 后端持久层" → Task 1, 2, 3, 4
  - §"REST 接口变更" → Task 5, 7
  - §"前端类型" → Task 8
  - §"卡片视觉" → Task 11, 12
  - §"ChatBoardPanel 时间序合流" → Task 13, 14, 15
  - §"ChatSenderBar 集成" → Task 16
  - §"设置弹窗 挂载监听" → Task 17, 18, 19, 20
  - §"WS 实时事件路由" → Task 10
  - §"stores" → Task 9
  - §"测试" → Task 21（+ 每任务的内嵌单测）
- ✅ 类型名一致性：`WhopPage.parent_chat_id`、`useChildPagesStore`、`buildTimeline / buildFilterBlocks / buildStreamGroups`、`layersForTask` 在所有引用任务中拼写一致。
- ✅ 无 placeholder / TBD。
- ✅ Yagni cut 落到位：本期不做现有独立 stock/option 页的迁移 UI；不暴露子页对父 chat 通用配置的 override；现 export pipeline 不变。

