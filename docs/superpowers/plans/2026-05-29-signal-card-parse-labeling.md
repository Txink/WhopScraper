# 信号卡片解析标注按钮 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给正股/期权/解析失败卡片的展开详情底部加一排标注按钮（✓解析正确 / ✎校正），把人工标注存进新表 `instruction_labels`，纯评测数据，不影响交易。

**Architecture:** 后端新建以 `task_id` 为键的 `instruction_labels` 表（覆盖没有 instruction 行的 PARSE_ERROR 卡），标注随域对象 `Task.label` 经现有转换器流到 `TaskOut`/`TaskSummaryOut`。前端把标注状态放进 tasks store 的 `labelsByTask` map（与现有 `pushEventsByTask` 同构），**不直接读 task 对象上的 label**——这样 WS 推送的整条 task 替换不会清掉已显示的标注。

**Tech Stack:** 后端 FastAPI + SQLAlchemy async + SQLite + Pydantic；前端 React + Zustand + Vitest；类型由 `npm run gen:types` 从 OpenAPI 生成。

**关键约束 / 设计决策（实现前必读）：**
- 数据库表由 `app/main.py` 的 `Base.metadata.create_all` 幂等创建，**新表无需手写迁移**；测试用 `tests/conftest.py` 的 `session_factory` fixture（内存库 + create_all）。
- WS 广播走 `task_to_out(p.task)`，`p.task` 是内存域对象，其 `label` 恒为 `None`。前端 `upsertTask` 是整条替换。因此前端 label 显示状态**只能**来自 `labelsByTask` map，由 REST（列表/详情/标注接口）填充，WS 永不写入。
- `verdict` 取值固定为 `"correct"` | `"corrected"`。
- `corrected_payload` 字段集合：`type`(stock|option) · `action`(BUY|SELL|CLOSE|MODIFY) · `ticker` · `price` · `quantity` · `strike` · `expiry` · `option_type`(CALL|PUT)。期权字段仅 option 时填。

---

## 文件结构

**后端：**
- 修改 `backend/app/storage/schema.py` — 新增 `InstructionLabelRow`。
- 修改 `backend/app/domain/task.py` — 新增 `InstructionLabel` dataclass + `Task.label` 字段。
- 修改 `backend/app/storage/repo.py` — `set_label` / `clear_label` / `labels_for_tasks` / `_row_to_label`，并在 `load_task`、`list_tasks` 填充 `task.label`。
- 修改 `backend/app/api/schemas.py` — `CorrectedInstruction` / `InstructionLabelOut` / `InstructionLabelIn`，给 `TaskOut`+`TaskSummaryOut` 加 `label`，新增 `label_to_out`，两个转换器转发 `task.label`。
- 修改 `backend/app/api/http.py` — `PUT`/`DELETE /api/tasks/{task_id}/label` 两个端点。
- 修改 `backend/tests/api/test_endpoint_field_forwarding.py` — 把 `label` 加进 `optional_fields`。
- 新增 `backend/tests/storage/test_instruction_labels.py`。
- 新增 `backend/tests/api/test_task_label_endpoints.py`。

**前端：**
- 修改 `frontend/src/api/types.ts` — 由 `npm run gen:types` 重新生成（勿手改）。
- 修改 `frontend/src/api/domain-types.ts` — `InstructionLabel` / `CorrectedInstruction` 类型别名。
- 修改 `frontend/src/api/http.ts` — `setTaskLabel` / `clearTaskLabel`。
- 修改 `frontend/src/api/http.test.ts` — 两个方法的测试。
- 修改 `frontend/src/stores/tasks.ts` — `labelsByTask` + seed/merge/clear。
- 修改 `frontend/src/stores/tasks.test.ts` — labelsByTask 行为测试。
- 新增 `frontend/src/components/Card/LabelCorrectionDialog.tsx` + `.test.tsx`。
- 新增 `frontend/src/components/Card/LabelActions.tsx` + `.test.tsx`。
- 新增 `frontend/src/components/Card/LabelActions.css`。
- 修改 `frontend/src/components/Chat/SignalBubble.tsx` — 在 `signal-detail` 底部接入 `<LabelActions>`。
- 修改 `frontend/src/test/fixtures.ts` — 给 task fixtures 加 `label: null`（如类型需要）。

---

## Task 1: 后端 — `instruction_labels` 表 + 域对象 `InstructionLabel`

**Files:**
- Modify: `backend/app/storage/schema.py`（在 `InstructionRow` 之后插入）
- Modify: `backend/app/domain/task.py`
- Test: `backend/tests/storage/test_instruction_labels.py`（本任务先验证表建得起来）

- [ ] **Step 1: 写 ORM 表**

在 `backend/app/storage/schema.py` 的 `InstructionRow` 类之后新增：

```python
# ---------------------------------------------------------------------------
# instruction_labels  (1:1 with tasks — task_id PK + FK, CASCADE on delete)
#   人工解析质量标注。与 instructions 分表的原因：PARSE_ERROR 任务没有
#   instructions 行，但仍需标注，故以 task_id 独立建表覆盖所有任务。
# ---------------------------------------------------------------------------


class InstructionLabelRow(Base):
    """ORM mapping for the ``instruction_labels`` table."""

    __tablename__ = "instruction_labels"

    task_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # "correct" | "corrected"
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    # CorrectedInstruction serialised as JSON; NULL when verdict == "correct".
    corrected_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

（`Any`、`JSON`、`DateTime`、`ForeignKey`、`Mapped`、`mapped_column`、`String` 在该文件顶部已 import，沿用即可。）

- [ ] **Step 2: 写域对象 + Task.label 字段**

在 `backend/app/domain/task.py` 的 `Task` dataclass 之前新增 `InstructionLabel`，并给 `Task` 加 `label` 字段。先确认文件顶部已 `from typing import Any`（若无则补 `Any`）。

新增 dataclass（放在 `@dataclass class Task:` 上方）：

```python
@dataclass
class InstructionLabel:
    """人工解析质量标注。纯评测数据，不影响交易。

    verdict: "correct"（解析正确）| "corrected"（已校正）。
    corrected_payload: 仅 corrected 时有，键见 schemas.CorrectedInstruction。
    """
    verdict: str
    corrected_payload: dict[str, Any] | None
    updated_at: datetime
```

在 `Task` 里 `submit_price` 字段之后新增：

```python
    #: 人工解析标注（None = 未标注）。仅由 repo 从 instruction_labels 表填充；
    #: 内存中新建的 Task（如 WS 广播路径）恒为 None。
    label: InstructionLabel | None = None
```

- [ ] **Step 3: 写表存在性测试**

创建 `backend/tests/storage/test_instruction_labels.py`：

```python
from __future__ import annotations

from app.storage.schema import InstructionLabelRow


def test_instruction_labels_table_registered() -> None:
    assert InstructionLabelRow.__tablename__ == "instruction_labels"
    cols = set(InstructionLabelRow.__table__.columns.keys())
    assert cols == {"task_id", "verdict", "corrected_payload", "updated_at"}
```

- [ ] **Step 4: 跑测试**

Run: `cd backend && uv run pytest tests/storage/test_instruction_labels.py -v`
Expected: PASS（2 列断言通过）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/schema.py backend/app/domain/task.py backend/tests/storage/test_instruction_labels.py
git commit -m "feat(storage): add instruction_labels table + InstructionLabel domain"
```

---

## Task 2: 后端 — repo 读写标注 + 填充 Task.label

**Files:**
- Modify: `backend/app/storage/repo.py`
- Test: `backend/tests/storage/test_instruction_labels.py`（追加）

- [ ] **Step 1: 写失败测试（set/get/clear + load_task 填充）**

在 `backend/tests/storage/test_instruction_labels.py` 追加（顶部补 import）：

```python
from datetime import UTC, datetime

from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.storage import repo
from app.storage.db import session_scope


def _make_task(task_id: str = "t-label-1") -> Task:
    now = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    msg = Message(
        id=task_id, content="buy AAPL", raw_content="buy AAPL",
        author="trader", posted_at=now, received_at=now,
        source="stock", quoted=None,
    )
    return Task(
        id=task_id, type="stock", status=Status.PARSE_ERROR,
        message=msg, instruction=None, created_at=now, updated_at=now,
    )


async def test_set_and_load_label_correct(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task())
        await repo.set_label(s, "t-label-1", "correct", None)

    async with session_scope(session_factory) as s:
        task = await repo.load_task(s, "t-label-1")
    assert task is not None
    assert task.label is not None
    assert task.label.verdict == "correct"
    assert task.label.corrected_payload is None


async def test_set_label_corrected_then_overwrite(session_factory) -> None:
    payload = {"type": "stock", "action": "BUY", "ticker": "AAPL",
               "price": 188.0, "quantity": 50}
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task())
        await repo.set_label(s, "t-label-1", "corrected", payload)
        await repo.set_label(s, "t-label-1", "correct", None)  # overwrite

    async with session_scope(session_factory) as s:
        task = await repo.load_task(s, "t-label-1")
    assert task.label.verdict == "correct"
    assert task.label.corrected_payload is None


async def test_clear_label(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task())
        await repo.set_label(s, "t-label-1", "correct", None)
        await repo.clear_label(s, "t-label-1")

    async with session_scope(session_factory) as s:
        task = await repo.load_task(s, "t-label-1")
    assert task.label is None


async def test_list_tasks_populates_labels(session_factory) -> None:
    async with session_scope(session_factory) as s:
        await repo.save_task(s, _make_task("t-a"))
        await repo.save_task(s, _make_task("t-b"))
        await repo.set_label(s, "t-a", "correct", None)

    async with session_scope(session_factory) as s:
        tasks = await repo.list_tasks(s, limit=10)
    by_id = {t.id: t for t in tasks}
    assert by_id["t-a"].label is not None and by_id["t-a"].label.verdict == "correct"
    assert by_id["t-b"].label is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/storage/test_instruction_labels.py -v`
Expected: FAIL（`AttributeError: module 'app.storage.repo' has no attribute 'set_label'`）。

- [ ] **Step 3: 实现 repo 方法 + 填充**

在 `backend/app/storage/repo.py`：

(a) 顶部 import 区把 `InstructionLabelRow` 加进现有的 schema import（与 `InstructionRow` 同处）：

```python
from app.storage.schema import (
    InstructionLabelRow,
    InstructionRow,
    MessageRow,
    PushEventRow,
    TaskRow,
)
```
（按文件现有 import 形式合并，勿重复导入；并确保 `from app.domain.task import InstructionLabel, Task` 中包含 `InstructionLabel`。）

(b) 在 `_rows_to_task` 之后新增转换器与读写函数：

```python
def _row_to_label(row: InstructionLabelRow) -> InstructionLabel:
    return InstructionLabel(
        verdict=row.verdict,
        corrected_payload=dict(row.corrected_payload) if row.corrected_payload else None,
        updated_at=_ensure_utc(row.updated_at),
    )


async def set_label(
    session: AsyncSession,
    task_id: str,
    verdict: str,
    corrected_payload: dict[str, Any] | None,
) -> InstructionLabel:
    """Upsert the human parse-quality label for a task."""
    now = datetime.now(UTC)
    row = await session.get(InstructionLabelRow, task_id)
    if row is None:
        session.add(InstructionLabelRow(
            task_id=task_id, verdict=verdict,
            corrected_payload=corrected_payload, updated_at=now,
        ))
    else:
        row.verdict = verdict
        row.corrected_payload = corrected_payload
        row.updated_at = now
    await session.flush()
    return InstructionLabel(verdict=verdict, corrected_payload=corrected_payload, updated_at=now)


async def clear_label(session: AsyncSession, task_id: str) -> None:
    """Remove a task's label row (back to unlabeled)."""
    await session.execute(
        sa_delete(InstructionLabelRow).where(InstructionLabelRow.task_id == task_id)
    )


async def labels_for_tasks(
    session: AsyncSession, task_ids: list[str]
) -> dict[str, InstructionLabel]:
    """Batched ``{task_id: InstructionLabel}`` for the given ids."""
    if not task_ids:
        return {}
    result = await session.execute(
        select(InstructionLabelRow).where(InstructionLabelRow.task_id.in_(task_ids))
    )
    return {r.task_id: _row_to_label(r) for r in result.scalars().all()}
```
（`sa_delete`、`select`、`datetime`、`UTC`、`Any`、`AsyncSession` 该文件已 import；`sa_delete` 在 `delete_tasks_by_url` 已用到，确认存在。）

(c) 在 `load_task` 的 `return _rows_to_task(...)` 之前，填充 label：

```python
    task = _rows_to_task(task_row, msg_row, inst_row, push_rows)
    label_row = await session.get(InstructionLabelRow, task_id)
    if label_row is not None:
        task.label = _row_to_label(label_row)
    return task
```
（把原来的 `return _rows_to_task(task_row, msg_row, inst_row, push_rows)` 改成上面四行。）

(d) 在 `list_tasks` 末尾、`return tasks` 之前，批量填充：

```python
    if tasks:
        labels = await labels_for_tasks(session, [t.id for t in tasks])
        for t in tasks:
            t.label = labels.get(t.id)

    return tasks
```
（紧跟在现有的 `latest_push_per_task` 填充块之后。）

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/storage/test_instruction_labels.py -v`
Expected: PASS（全部 5 个用例）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage/repo.py backend/tests/storage/test_instruction_labels.py
git commit -m "feat(storage): repo set/clear/batch-load instruction labels"
```

---

## Task 3: 后端 — Pydantic schema + TaskOut/TaskSummaryOut 转发 label

**Files:**
- Modify: `backend/app/api/schemas.py`
- Modify: `backend/tests/api/test_endpoint_field_forwarding.py`

- [ ] **Step 1: 改字段转发测试（先让它因缺字段失败）**

在 `backend/tests/api/test_endpoint_field_forwarding.py`，给 `test_task_to_out_forwards_every_field` 和 `test_task_to_summary_forwards_every_field` 两处的 `optional_fields` 集合都加上 `"label"`：

```python
    optional_fields = {
        "reject_reason", "last_submitted_price", "last_submitted_qty",
        "label",
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_endpoint_field_forwarding.py -v`
Expected: FAIL —— `TaskOut has new fields not classified by this test: {'label'}` 还不会出现（因为字段还没加到模型）；此步会因 `optional_fields` 里多了 `label` 但模型无该字段而 **不报错**。先跳到 Step 3 加模型字段，再回来此测试就能锁住转发。

> 说明：本测试的断言只检查「模型字段是否都被分类」。先加 `label` 到 `optional_fields`，再在 Step 3 给模型加 `label` 字段，二者匹配即通过；若漏改其一会失败。

- [ ] **Step 3: 写 schema + 转换器**

在 `backend/app/api/schemas.py`：

(a) 确认顶部 import 有 `Literal`（`from typing import Any, Literal` —— 若缺则补 `Literal`），以及 `from app.domain.task import InstructionLabel`（在转换器区按需补；该文件已 import Task 相关，沿用其 import 块）。

(b) 在 `InstructionOut` 类之后新增三个模型：

```python
class CorrectedInstruction(BaseModel):
    """人工校正后的指令字段集合（纯标注，不参与交易）。"""
    type: Literal["stock", "option"]
    action: Literal["BUY", "SELL", "CLOSE", "MODIFY"]
    ticker: str | None = None
    price: float | None = None
    quantity: int | None = None
    strike: float | None = None
    expiry: str | None = None
    option_type: Literal["CALL", "PUT"] | None = None


class InstructionLabelOut(BaseModel):
    verdict: str  # "correct" | "corrected"
    corrected_payload: CorrectedInstruction | None = None
    updated_at: datetime


class InstructionLabelIn(BaseModel):
    verdict: Literal["correct", "corrected"]
    corrected_payload: CorrectedInstruction | None = None
```

(c) 给 `TaskOut` 末尾（`last_submitted_qty` 之后）加：

```python
    label: InstructionLabelOut | None = None
```

(d) 给 `TaskSummaryOut` 末尾（`last_submitted_qty` 之后、`push_events` 注释之前）加同一行：

```python
    label: InstructionLabelOut | None = None
```

(e) 在转换器区（`instruction_to_out` 附近）新增：

```python
def label_to_out(label: InstructionLabel) -> InstructionLabelOut:
    return InstructionLabelOut(
        verdict=label.verdict,
        corrected_payload=(
            CorrectedInstruction(**label.corrected_payload)
            if label.corrected_payload is not None
            else None
        ),
        updated_at=label.updated_at,
    )
```

(f) 在 `task_to_out` 的 `TaskOut(...)` 里，`**_last_push_summary(task.push_events)` 之后加一行：

```python
        label=label_to_out(task.label) if task.label is not None else None,
```

(g) 在 `task_to_summary` 的 `TaskSummaryOut(...)` 里，`**_last_push_summary(task.push_events)` 之后加同一行。

- [ ] **Step 4: 跑字段转发测试 + schema 测试**

Run: `cd backend && uv run pytest tests/api/test_endpoint_field_forwarding.py -v`
Expected: PASS（`label` 已在模型且已分类为 optional）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/schemas.py backend/tests/api/test_endpoint_field_forwarding.py
git commit -m "feat(api): forward instruction label on TaskOut/TaskSummaryOut"
```

---

## Task 4: 后端 — PUT/DELETE label 端点

**Files:**
- Modify: `backend/app/api/http.py`
- Test: `backend/tests/api/test_task_label_endpoints.py`

- [ ] **Step 1: 写端点测试（参照 test_http.py 的 client 搭建）**

创建 `backend/tests/api/test_task_label_endpoints.py`。先打开 `backend/tests/api/test_http.py` 顶部，复制其 `client` / app 构建 fixture 的写法（`build_http_router` + `FastAPI` + `TestClient` + `session_factory` + 写入一条 task 的 helper）。本测试至少覆盖：

```python
# 复用 test_http.py 同款 fixture 构建 client 与写入一条 PARSE_ERROR task（id="t1"）。
# 下面只列断言主体，fixture/任务写入按 test_http.py 现有模式补齐。

def test_put_label_correct(client) -> None:
    r = client.put("/api/tasks/t1/label", json={"verdict": "correct"})
    assert r.status_code == 200
    assert r.json()["label"]["verdict"] == "correct"
    assert r.json()["label"]["corrected_payload"] is None


def test_put_label_corrected(client) -> None:
    body = {
        "verdict": "corrected",
        "corrected_payload": {
            "type": "stock", "action": "BUY",
            "ticker": "AAPL", "price": 188.0, "quantity": 50,
        },
    }
    r = client.put("/api/tasks/t1/label", json=body)
    assert r.status_code == 200
    cp = r.json()["label"]["corrected_payload"]
    assert cp["ticker"] == "AAPL" and cp["action"] == "BUY" and cp["quantity"] == 50


def test_put_label_corrected_without_payload_400(client) -> None:
    r = client.put("/api/tasks/t1/label", json={"verdict": "corrected"})
    assert r.status_code == 400


def test_put_label_unknown_task_404(client) -> None:
    r = client.put("/api/tasks/nope/label", json={"verdict": "correct"})
    assert r.status_code == 404


def test_delete_label_clears(client) -> None:
    client.put("/api/tasks/t1/label", json={"verdict": "correct"})
    r = client.delete("/api/tasks/t1/label")
    assert r.status_code == 200
    assert r.json()["label"] is None


def test_label_appears_in_task_list(client) -> None:
    client.put("/api/tasks/t1/label", json={"verdict": "correct"})
    r = client.get("/api/tasks")
    t1 = next(t for t in r.json()["tasks"] if t["id"] == "t1")
    assert t1["label"]["verdict"] == "correct"
```

> 注：`client` fixture 与 `t1` 任务写入请严格照搬 `test_http.py` 里既有写法（同目录、同 `_TOKEN` 查询参数附加方式）。token 通过 query param `?token=` 传递——参照 test_http.py 里请求是怎么带 token 的，给上面每个 `client.put/get/delete` 的 URL 补上 token 参数或用其 fixture 封装。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_task_label_endpoints.py -v`
Expected: FAIL（404/405：端点尚不存在）。

- [ ] **Step 3: 实现端点**

在 `backend/app/api/http.py`：

(a) 把 `InstructionLabelIn` 加进从 `app.api.schemas` 的 import（与 `task_to_out`、`TaskOut` 等同处）。

(b) 在 `skip_task_endpoint`（约 1556 行）之后新增：

```python
    @router.put("/api/tasks/{task_id}/label", response_model=TaskOut)
    async def set_task_label_endpoint(task_id: str, body: InstructionLabelIn) -> TaskOut:
        """Upsert 人工解析标注（correct / corrected）。纯评测数据。"""
        if body.verdict == "corrected" and body.corrected_payload is None:
            raise HTTPException(400, detail="corrected verdict requires corrected_payload")
        payload = (
            body.corrected_payload.model_dump()
            if body.verdict == "corrected" and body.corrected_payload is not None
            else None
        )
        async with session_scope(session_factory) as session:
            task = await repo.load_task(session, task_id)
            if task is None:
                raise HTTPException(404, detail="task not found")
            await repo.set_label(session, task_id, body.verdict, payload)
            refreshed = await repo.load_task(session, task_id)
        if refreshed is None:
            raise HTTPException(500, detail="task missing after label set")
        return task_to_out(refreshed)

    @router.delete("/api/tasks/{task_id}/label", response_model=TaskOut)
    async def clear_task_label_endpoint(task_id: str) -> TaskOut:
        """清除任务标注（回到未标注）。"""
        async with session_scope(session_factory) as session:
            task = await repo.load_task(session, task_id)
            if task is None:
                raise HTTPException(404, detail="task not found")
            await repo.clear_label(session, task_id)
            refreshed = await repo.load_task(session, task_id)
        if refreshed is None:
            raise HTTPException(500, detail="task missing after label clear")
        return task_to_out(refreshed)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_task_label_endpoints.py -v`
Expected: PASS（全部用例）。

- [ ] **Step 5: 跑后端全量确认无回归**

Run: `cd backend && uv run pytest -q`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_task_label_endpoints.py
git commit -m "feat(api): PUT/DELETE /api/tasks/{id}/label endpoints"
```

---

## Task 5: 前端 — 重新生成类型 + domain-types + api 方法

**Files:**
- Modify: `frontend/src/api/types.ts`（生成物）
- Modify: `frontend/src/api/domain-types.ts`
- Modify: `frontend/src/api/http.ts`
- Test: `frontend/src/api/http.test.ts`

- [ ] **Step 1: 重新生成 OpenAPI 类型**

Run: `cd frontend && npm run gen:types`
Expected: `src/api/types.ts` 更新，包含 `InstructionLabelOut`、`CorrectedInstruction`、`InstructionLabelIn`，且 `TaskOut`/`TaskSummaryOut` 多出 `label`。

校验：`grep -n "InstructionLabelOut\|CorrectedInstruction" frontend/src/api/types.ts` 应有输出。

- [ ] **Step 2: 加 domain-types 别名**

在 `frontend/src/api/domain-types.ts`（紧跟 `Instruction` 别名附近）加：

```typescript
export type InstructionLabel = components["schemas"]["InstructionLabelOut"];
export type CorrectedInstruction = components["schemas"]["CorrectedInstruction"];
```

- [ ] **Step 3: 写 api 方法测试（先失败）**

在 `frontend/src/api/http.test.ts` 的 `describe("http", ...)` 内追加：

```typescript
  it("uses PUT method + body for setTaskLabel", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ id: "msg-1", label: { verdict: "correct", corrected_payload: null } }),
    });
    await api.setTaskLabel("msg-1", { verdict: "correct" });
    const [url, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/tasks/msg-1/label");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({ verdict: "correct" });
  });

  it("uses DELETE method for clearTaskLabel", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({ id: "msg-1", label: null }),
    });
    await api.clearTaskLabel("msg-1");
    const [url, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toContain("/api/tasks/msg-1/label");
    expect(init.method).toBe("DELETE");
  });
```

- [ ] **Step 4: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/api/http.test.ts`
Expected: FAIL（`api.setTaskLabel is not a function`）。

- [ ] **Step 5: 实现 api 方法**

在 `frontend/src/api/http.ts` 的 `api` 对象里、`skipTask` 之后加：

```typescript
  async setTaskLabel(
    id: string,
    body:
      | { verdict: "correct" }
      | { verdict: "corrected"; corrected_payload: CorrectedInstruction },
  ): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}/label`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
  },

  async clearTaskLabel(id: string): Promise<Task> {
    return request<Task>(`/api/tasks/${encodeURIComponent(id)}/label`, { method: "DELETE" });
  },
```

并确保文件顶部从 `domain-types` import 了 `CorrectedInstruction`（与 `Task` 等同处）。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/api/http.test.ts`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/domain-types.ts frontend/src/api/http.ts frontend/src/api/http.test.ts
git commit -m "feat(api): setTaskLabel/clearTaskLabel client methods + regen types"
```

---

## Task 6: 前端 — tasks store 的 `labelsByTask`

**Files:**
- Modify: `frontend/src/stores/tasks.ts`
- Test: `frontend/src/stores/tasks.test.ts`

**行为规范（务必照此实现，避免 WS 清掉标注）：**
- `setInitialTasks(tasks)`：**重建** `labelsByTask`（只收 `task.label != null` 的条目）。
- `upsertTask(task)`：**仅当** `task.label != null` 时写入 `labelsByTask[id]`；**绝不**因 `label` 为 null 而删除。（WS 推送的 task.label 恒为 null，不能清掉已有标注。）
- `setLabel(taskId, label)`：显式 setter——`label` 为 null 则删 key，否则写入。标注接口成功后调用它。

- [ ] **Step 1: 写 store 测试（先失败）**

在 `frontend/src/stores/tasks.test.ts` 追加（顶部按现有方式 import 所需类型；`_mkTask` 已存在于该文件，复用并允许传 label）：

```typescript
import { useLabelOf } from "../stores/tasks"; // 若不导出 selector 可改为直接读 state

function _mkLabeled(id: string, verdict: "correct" | "corrected") {
  return { ...(_mkTask(id, "2026-04-25T10:00:00Z")), label: { verdict, corrected_payload: null } };
}

describe("labelsByTask", () => {
  beforeEach(() => {
    useTasksStore.setState({ tasks: [], pushEventsByTask: {}, labelsByTask: {} });
  });

  it("setInitialTasks seeds labelsByTask from task.label", () => {
    useTasksStore.getState().setInitialTasks([_mkLabeled("t1", "correct")]);
    expect(useTasksStore.getState().labelsByTask["t1"].verdict).toBe("correct");
  });

  it("setInitialTasks rebuilds (drops stale labels)", () => {
    useTasksStore.setState({ labelsByTask: { told: { verdict: "correct", corrected_payload: null } } });
    useTasksStore.getState().setInitialTasks([_mkTask("t1", "2026-04-25T10:00:00Z")]);
    expect(useTasksStore.getState().labelsByTask).toEqual({});
  });

  it("upsertTask with null label does NOT clobber existing label", () => {
    useTasksStore.getState().setLabel("t1", { verdict: "correct", corrected_payload: null });
    useTasksStore.getState().upsertTask(_mkTask("t1", "2026-04-25T10:00:00Z")); // label undefined/null
    expect(useTasksStore.getState().labelsByTask["t1"].verdict).toBe("correct");
  });

  it("setLabel(null) clears", () => {
    useTasksStore.getState().setLabel("t1", { verdict: "correct", corrected_payload: null });
    useTasksStore.getState().setLabel("t1", null);
    expect(useTasksStore.getState().labelsByTask["t1"]).toBeUndefined();
  });
});
```

> 若 `_mkTask` 不在测试文件作用域，按该文件现有 `_mkTask` 定义复制一份；它返回的 TaskSummary 需补 `label: null` 以满足类型（见 Task 9 的 fixtures 处理）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/stores/tasks.test.ts`
Expected: FAIL（`labelsByTask`/`setLabel` 不存在）。

- [ ] **Step 3: 实现 store 改动**

在 `frontend/src/stores/tasks.ts`：

(a) import 加 `InstructionLabel`：

```typescript
import type { TaskSummary, PushEvent, InstructionLabel } from "../api/domain-types";
```

(b) `interface TaskState` 加：

```typescript
  labelsByTask: Record<string, InstructionLabel>;
  setLabel(taskId: string, label: InstructionLabel | null): void;
```

(c) store 初始 state 加 `labelsByTask: {},`（在 `pushEventsByTask: {}` 旁）。

(d) 改 `setInitialTasks`：

```typescript
  setInitialTasks(tasks) {
    const labelsByTask: Record<string, InstructionLabel> = {};
    for (const t of tasks) {
      if (t.label != null) labelsByTask[t.id] = t.label;
    }
    set({ tasks, labelsByTask });
  },
```

(e) 在 `upsertTask` 的 `set((state) => { ... })` 内，返回前加 label 合并（仅非空写入，不删除）：

```typescript
      const filtered = state.tasks.filter((t) => t.id !== task.id);
      const newList = [...filtered, incoming].sort(
        (a, b) => b.created_at.localeCompare(a.created_at),
      );
      const labelsByTask = task.label != null
        ? { ...state.labelsByTask, [task.id]: task.label }
        : state.labelsByTask;
      return { tasks: newList, labelsByTask };
```

(f) 新增 action（放在 `appendPushEvent` 旁）：

```typescript
  setLabel(taskId, label) {
    set((state) => {
      const next = { ...state.labelsByTask };
      if (label == null) delete next[taskId];
      else next[taskId] = label;
      return { labelsByTask: next };
    });
  },
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/stores/tasks.test.ts`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/tasks.ts frontend/src/stores/tasks.test.ts
git commit -m "feat(store): labelsByTask map decoupled from WS task replacement"
```

---

## Task 7: 前端 — `LabelCorrectionDialog` 校正弹窗

**Files:**
- Create: `frontend/src/components/Card/LabelCorrectionDialog.tsx`
- Create: `frontend/src/components/Card/LabelActions.css`
- Test: `frontend/src/components/Card/LabelCorrectionDialog.test.tsx`

- [ ] **Step 1: 写组件测试（先失败）**

创建 `frontend/src/components/Card/LabelCorrectionDialog.test.tsx`：

```typescript
import { render, fireEvent, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { LabelCorrectionDialog } from "./LabelCorrectionDialog";
import type { InstructionOut } from "../../api/domain-types";

const stockInst = {
  type: "stock", instruction_type: "BUY", ticker: "AAPL",
  price: 188, quantity: 50, price_range: null, position_size: null,
  stop_loss_price: null, take_profit_price: null, context_source: null,
  parser_notes: [], symbol: "AAPL.US",
} as unknown as InstructionOut;

describe("LabelCorrectionDialog", () => {
  it("prefills from instruction", () => {
    render(
      <LabelCorrectionDialog
        variant="stock" instruction={stockInst} existing={null}
        onSubmit={() => {}} onClose={() => {}}
      />,
    );
    expect((screen.getByLabelText("ticker") as HTMLInputElement).value).toBe("AAPL");
    expect((screen.getByLabelText("action") as HTMLSelectElement).value).toBe("BUY");
  });

  it("shows option fields only when type=option", () => {
    render(
      <LabelCorrectionDialog
        variant="option" instruction={null} existing={null}
        onSubmit={() => {}} onClose={() => {}}
      />,
    );
    expect(screen.queryByLabelText("strike")).not.toBeNull();
  });

  it("hides option fields for stock", () => {
    render(
      <LabelCorrectionDialog
        variant="stock" instruction={null} existing={null}
        onSubmit={() => {}} onClose={() => {}}
      />,
    );
    expect(screen.queryByLabelText("strike")).toBeNull();
  });

  it("submits a corrected_payload", () => {
    const onSubmit = vi.fn();
    render(
      <LabelCorrectionDialog
        variant="stock" instruction={stockInst} existing={null}
        onSubmit={onSubmit} onClose={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("保存"));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ type: "stock", action: "BUY", ticker: "AAPL", quantity: 50 }),
    );
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/Card/LabelCorrectionDialog.test.tsx`
Expected: FAIL（找不到模块）。

- [ ] **Step 3: 实现组件**

创建 `frontend/src/components/Card/LabelCorrectionDialog.tsx`：

```typescript
import { useState } from "react";
import type { InstructionOut, CorrectedInstruction } from "../../api/domain-types";
import "./LabelActions.css";

type Action = "BUY" | "SELL" | "CLOSE" | "MODIFY";
type CType = "stock" | "option";
type OptType = "CALL" | "PUT";

interface Props {
  variant: "stock" | "option";
  instruction: InstructionOut | null;
  existing: CorrectedInstruction | null;
  onSubmit(payload: CorrectedInstruction): void;
  onClose(): void;
}

const ACTIONS: Action[] = ["BUY", "SELL", "CLOSE", "MODIFY"];

function str(v: number | null | undefined): string {
  return v == null ? "" : String(v);
}
function numOrNull(s: string): number | null {
  const t = s.trim();
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

export function LabelCorrectionDialog({ variant, instruction, existing, onSubmit, onClose }: Props) {
  const seedType: CType = (existing?.type ?? (variant === "option" ? "option" : "stock"));
  const [type, setType] = useState<CType>(seedType);
  const [ticker, setTicker] = useState(existing?.ticker ?? instruction?.ticker ?? "");
  const [price, setPrice] = useState(str(existing?.price ?? instruction?.price));
  const [quantity, setQuantity] = useState(str(existing?.quantity ?? instruction?.quantity));
  const [action, setAction] = useState<Action>(
    (existing?.action ?? (instruction?.instruction_type as Action) ?? "BUY"),
  );
  const [strike, setStrike] = useState(str(existing?.strike ?? instruction?.strike));
  const [expiry, setExpiry] = useState(existing?.expiry ?? instruction?.expiry ?? "");
  const [optionType, setOptionType] = useState<OptType>(
    (existing?.option_type
      ?? ((instruction?.option_type as string)?.toUpperCase() as OptType)
      ?? "CALL"),
  );

  const submit = () => {
    const payload: CorrectedInstruction = {
      type, action,
      ticker: ticker.trim() || null,
      price: numOrNull(price),
      quantity: numOrNull(quantity),
      strike: type === "option" ? numOrNull(strike) : null,
      expiry: type === "option" ? (expiry.trim() || null) : null,
      option_type: type === "option" ? optionType : null,
    };
    onSubmit(payload);
  };

  const stop = (e: React.SyntheticEvent) => e.stopPropagation();

  return (
    <div className="label-dialog-backdrop" onClick={onClose}>
      <div className="label-dialog" role="dialog" aria-label="校正解析结果"
           onClick={stop} onKeyDown={stop}>
        <div className="label-dialog-title">校正解析结果</div>

        <label className="label-field">
          <span>type</span>
          <select aria-label="type" value={type}
                  onChange={(e) => setType(e.target.value as CType)}>
            <option value="stock">stock</option>
            <option value="option">option</option>
          </select>
        </label>

        <label className="label-field">
          <span>ticker</span>
          <input aria-label="ticker" value={ticker}
                 onChange={(e) => setTicker(e.target.value)} />
        </label>

        <label className="label-field">
          <span>action</span>
          <select aria-label="action" value={action}
                  onChange={(e) => setAction(e.target.value as Action)}>
            {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
          </select>
        </label>

        <label className="label-field">
          <span>price</span>
          <input aria-label="price" inputMode="decimal" value={price}
                 onChange={(e) => setPrice(e.target.value)} />
        </label>

        <label className="label-field">
          <span>quantity</span>
          <input aria-label="quantity" inputMode="numeric" value={quantity}
                 onChange={(e) => setQuantity(e.target.value)} />
        </label>

        {type === "option" && (
          <>
            <label className="label-field">
              <span>strike</span>
              <input aria-label="strike" inputMode="decimal" value={strike}
                     onChange={(e) => setStrike(e.target.value)} />
            </label>
            <label className="label-field">
              <span>expiry</span>
              <input aria-label="expiry" placeholder="YYYY-MM-DD" value={expiry}
                     onChange={(e) => setExpiry(e.target.value)} />
            </label>
            <label className="label-field">
              <span>option_type</span>
              <select aria-label="option_type" value={optionType}
                      onChange={(e) => setOptionType(e.target.value as OptType)}>
                <option value="CALL">CALL</option>
                <option value="PUT">PUT</option>
              </select>
            </label>
          </>
        )}

        <div className="label-dialog-actions">
          <button type="button" className="label-btn-ghost" onClick={onClose}>取消</button>
          <button type="button" className="label-btn-primary" onClick={submit}>保存</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 写最小 CSS**

创建 `frontend/src/components/Card/LabelActions.css`：

```css
.label-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #21262d;
}
.label-action-btn {
  background: transparent;
  border: 1px solid #444c56;
  color: #8b949e;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}
.label-action-btn.active-correct { border-color: #2ea043; background: #2ea043; color: #fff; }
.label-action-btn.active-corrected { border-color: #1f6feb; color: #58a6ff; }
.label-err { color: #f85149; font-size: 12px; align-self: center; }

.label-dialog-backdrop {
  position: fixed; inset: 0; background: rgba(0,0,0,0.5);
  display: flex; align-items: center; justify-content: center; z-index: 1000;
}
.label-dialog {
  background: #161b22; border: 1px solid #2a3441; border-radius: 10px;
  padding: 16px; min-width: 300px; color: #e6edf3;
}
.label-dialog-title { font-weight: 600; margin-bottom: 12px; }
.label-field { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; font-size: 13px; }
.label-field > span { width: 80px; color: #8b949e; }
.label-field input, .label-field select {
  flex: 1; background: #0d1117; border: 1px solid #30363d; color: #e6edf3;
  border-radius: 4px; padding: 4px 6px;
}
.label-dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.label-btn-ghost { background: transparent; border: 1px solid #444c56; color: #8b949e; padding: 4px 12px; border-radius: 6px; cursor: pointer; }
.label-btn-primary { background: #1f6feb; border: 1px solid #1f6feb; color: #fff; padding: 4px 12px; border-radius: 6px; cursor: pointer; }
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/Card/LabelCorrectionDialog.test.tsx`
Expected: PASS。

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Card/LabelCorrectionDialog.tsx frontend/src/components/Card/LabelActions.css frontend/src/components/Card/LabelCorrectionDialog.test.tsx
git commit -m "feat(card): LabelCorrectionDialog form with stock/option fields"
```

---

## Task 8: 前端 — `LabelActions` 按钮排

**Files:**
- Create: `frontend/src/components/Card/LabelActions.tsx`
- Test: `frontend/src/components/Card/LabelActions.test.tsx`

- [ ] **Step 1: 写组件测试（先失败）**

创建 `frontend/src/components/Card/LabelActions.test.tsx`：

```typescript
import { render, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LabelActions } from "./LabelActions";
import { useTasksStore } from "../../stores/tasks";
import { api } from "../../api/http";

beforeEach(() => {
  useTasksStore.setState({ tasks: [], pushEventsByTask: {}, labelsByTask: {} });
});
afterEach(() => vi.restoreAllMocks());

describe("LabelActions", () => {
  it("clicking 解析正确 calls setTaskLabel(correct) and updates store", async () => {
    vi.spyOn(api, "setTaskLabel").mockResolvedValue({
      id: "t1", label: { verdict: "correct", corrected_payload: null },
    } as never);
    render(<LabelActions taskId="t1" instruction={null} variant="stock" />);
    fireEvent.click(screen.getByText("解析正确"));
    await waitFor(() => {
      expect(api.setTaskLabel).toHaveBeenCalledWith("t1", { verdict: "correct" });
      expect(useTasksStore.getState().labelsByTask["t1"].verdict).toBe("correct");
    });
  });

  it("clicking 解析正确 while already correct clears it", async () => {
    useTasksStore.getState().setLabel("t1", { verdict: "correct", corrected_payload: null });
    vi.spyOn(api, "clearTaskLabel").mockResolvedValue({ id: "t1", label: null } as never);
    render(<LabelActions taskId="t1" instruction={null} variant="stock" />);
    fireEvent.click(screen.getByText("已确认正确"));
    await waitFor(() => {
      expect(api.clearTaskLabel).toHaveBeenCalledWith("t1");
      expect(useTasksStore.getState().labelsByTask["t1"]).toBeUndefined();
    });
  });

  it("校正 opens dialog; saving calls setTaskLabel(corrected)", async () => {
    vi.spyOn(api, "setTaskLabel").mockResolvedValue({
      id: "t1",
      label: { verdict: "corrected", corrected_payload: { type: "stock", action: "BUY" } },
    } as never);
    render(<LabelActions taskId="t1" instruction={null} variant="stock" />);
    fireEvent.click(screen.getByText("校正"));
    expect(screen.getByRole("dialog")).not.toBeNull();
    fireEvent.click(screen.getByText("保存"));
    await waitFor(() => {
      expect(api.setTaskLabel).toHaveBeenCalledWith(
        "t1",
        expect.objectContaining({ verdict: "corrected" }),
      );
    });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/Card/LabelActions.test.tsx`
Expected: FAIL（找不到模块）。

- [ ] **Step 3: 实现组件**

创建 `frontend/src/components/Card/LabelActions.tsx`：

```typescript
import { useState } from "react";
import type { SyntheticEvent } from "react";
import type { InstructionOut, CorrectedInstruction } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { useTasksStore } from "../../stores/tasks";
import { LabelCorrectionDialog } from "./LabelCorrectionDialog";
import "./LabelActions.css";

interface Props {
  taskId: string;
  instruction: InstructionOut | null;
  variant: "stock" | "option";
}

export function LabelActions({ taskId, instruction, variant }: Props) {
  const label = useTasksStore((s) => s.labelsByTask[taskId]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const verdict = label?.verdict;

  const errMsg = (e: unknown) =>
    e instanceof HttpError
      ? (typeof e.body === "object" && e.body && "detail" in e.body
          ? String((e.body as { detail: unknown }).detail)
          : e.message)
      : (e instanceof Error ? e.message : String(e));

  const toggleCorrect = async () => {
    setBusy(true);
    setError(null);
    try {
      if (verdict === "correct") {
        const updated = await api.clearTaskLabel(taskId);
        useTasksStore.getState().setLabel(taskId, updated.label ?? null);
      } else {
        const updated = await api.setTaskLabel(taskId, { verdict: "correct" });
        useTasksStore.getState().setLabel(taskId, updated.label ?? null);
      }
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const saveCorrection = async (payload: CorrectedInstruction) => {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.setTaskLabel(taskId, {
        verdict: "corrected",
        corrected_payload: payload,
      });
      useTasksStore.getState().setLabel(taskId, updated.label ?? null);
      setDialogOpen(false);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  };

  const stop = (e: SyntheticEvent) => e.stopPropagation();

  return (
    <div className="label-actions" onClick={stop} onKeyDown={stop}>
      {error && <span className="label-err" title={error}>!</span>}
      <button
        type="button"
        className={`label-action-btn${verdict === "correct" ? " active-correct" : ""}`}
        disabled={busy}
        onClick={toggleCorrect}
      >
        {verdict === "correct" ? "已确认正确" : "解析正确"}
      </button>
      <button
        type="button"
        className={`label-action-btn${verdict === "corrected" ? " active-corrected" : ""}`}
        disabled={busy}
        onClick={() => setDialogOpen(true)}
      >
        校正
      </button>
      {dialogOpen && (
        <LabelCorrectionDialog
          variant={variant}
          instruction={instruction}
          existing={label?.corrected_payload ?? null}
          onSubmit={saveCorrection}
          onClose={() => setDialogOpen(false)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/components/Card/LabelActions.test.tsx`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Card/LabelActions.tsx frontend/src/components/Card/LabelActions.test.tsx
git commit -m "feat(card): LabelActions button row (correct toggle + correction)"
```

---

## Task 9: 前端 — 接入 SignalBubble + fixtures + 快照

**Files:**
- Modify: `frontend/src/components/Chat/SignalBubble.tsx`
- Modify: `frontend/src/test/fixtures.ts`
- Modify: `frontend/src/components/Chat/SignalBubble.test.tsx`
- Modify: `frontend/src/components/Chat/__snapshots__/SignalBubble.test.tsx.snap`（由 -u 重生）

- [ ] **Step 1: fixtures 补 label 字段**

`npm run gen:types` 后，`TaskSummary` 多了 `label`。在 `frontend/src/test/fixtures.ts` 的 `makeStockTask` / `makeOptionTask` / `makeFailedParseTask` 三个返回对象里各加 `label: null,`（放在 `instruction` 字段旁），使类型完整。

- [ ] **Step 2: 写接入测试（先失败）**

在 `frontend/src/components/Chat/SignalBubble.test.tsx` 追加：

```typescript
  it("renders LabelActions only when expanded (stock)", () => {
    const folded = render(
      <SignalBubble task={makeStockTask()} pushEvents={[]} expanded={false}
        onToggle={() => {}} autoTrade={true} variant="stock" />,
    );
    expect(folded.container.querySelector(".label-actions")).toBeNull();

    const expanded = render(
      <SignalBubble task={makeStockTask()} pushEvents={[]} expanded={true}
        onToggle={() => {}} autoTrade={true} variant="stock" />,
    );
    expect(expanded.container.querySelector(".label-actions")).not.toBeNull();
  });

  it("renders LabelActions for parse-error when expanded", () => {
    const { container } = render(
      <SignalBubble task={makeFailedParseTask()} pushEvents={[]} expanded={true}
        onToggle={() => {}} autoTrade={true} variant="stock" />,
    );
    expect(container.querySelector(".label-actions")).not.toBeNull();
  });

  it("does NOT render LabelActions on image bubbles", () => {
    const base = makeStockTask();
    const task = { ...base, status: "SKIPPED" as const,
      message: { ...base.message, content: "", image_url: "/api/messages/x/image" } };
    const { container } = render(
      <SignalBubble task={task} pushEvents={[]} expanded={true}
        onToggle={() => {}} autoTrade={true} variant="stock" />,
    );
    expect(container.querySelector(".label-actions")).toBeNull();
  });
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/components/Chat/SignalBubble.test.tsx -t "LabelActions"`
Expected: FAIL（`.label-actions` 不存在）。

- [ ] **Step 4: 接入 SignalBubble**

在 `frontend/src/components/Chat/SignalBubble.tsx`：

(a) 顶部加 import：

```typescript
import { LabelActions } from "../Card/LabelActions";
```

(b) 在 `signal-detail` 块内、ORD 推送链 `</div>` 之后、`signal-detail` 的闭合 `</div>` 之前，加：

```tsx
              <LabelActions
                taskId={task.id}
                instruction={task.instruction}
                variant={variant}
              />
```

具体位置：紧接现有的 ORD 块（`{(pushEvents.length > 0 || task.order_id) && ( ... )}`）之后，仍在 `{expanded && (<div className="signal-detail"> ... </div>)}` 内部。LabelActions 因此只在 `expanded` 时渲染；image 分支不含 `signal-detail`，天然不显示。

- [ ] **Step 5: 跑接入测试确认通过**

Run: `cd frontend && npx vitest run src/components/Chat/SignalBubble.test.tsx -t "LabelActions"`
Expected: PASS（3 个用例）。

- [ ] **Step 6: 更新快照**

现有快照（stock-expanded / option-expanded 等）因新增按钮排而变化，确认 diff 只多了 `.label-actions` 后更新：

Run: `cd frontend && npx vitest run src/components/Chat/SignalBubble.test.tsx -u`
Expected: 快照更新，全部 PASS。

- [ ] **Step 7: 前端全量 + typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: 测试全 PASS，无类型错误。

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Chat/SignalBubble.tsx frontend/src/test/fixtures.ts frontend/src/components/Chat/SignalBubble.test.tsx frontend/src/components/Chat/__snapshots__/SignalBubble.test.tsx.snap
git commit -m "feat(chat): wire LabelActions into expanded SignalBubble detail"
```

---

## Task 10: 端到端手动验证

**Files:** 无（仅运行 + 浏览器验证）

- [ ] **Step 1: 起后端**

按项目惯例启动后端（见项目 run skill / README）。确认 `/api/tasks` 返回的 task 含 `label` 字段（初始为 null）。

- [ ] **Step 2: 起前端，浏览器验证黄金路径**

打开前端，展开一条正股信号卡：
- 底部出现「解析正确 / 校正」按钮排。
- 点「解析正确」→ 变「已确认正确」实心；刷新页面后仍保持（持久化生效）。
- 再点 → 取消回未标注。
- 点「校正」→ 弹窗预填解析值；改 quantity 后保存 → 「校正」按钮高亮；刷新后仍在。

- [ ] **Step 3: 验证期权卡 + 解析失败卡**

- 期权卡：校正弹窗含 strike/expiry/option_type。
- PARSE_ERROR 卡：展开后也有按钮排；校正弹窗 type 默认 stock，可切 option。
- 图片卡：展开无按钮排。

- [ ] **Step 4: 验证 WS 不清标注（关键回归点）**

对一条 **非终态**（如 PENDING/INSTRUCTION_READY）任务标「解析正确」，触发一次会产生 WS task 更新的操作（如成交推送），确认卡片上的标注**不被清掉**。

- [ ] **Step 5: 跑全量测试做最终把关**

Run: `cd backend && uv run pytest -q && cd ../frontend && npx vitest run && npx tsc --noEmit`
Expected: 全 PASS。

---

## Self-Review（plan 作者已核对）

- **Spec 覆盖**：三态标注（correct/corrected/未标注）→ Task 2/6/8；新表覆盖 PARSE_ERROR → Task 1 + Task 9 接入；校正字段集合（stock 4 + option 3）→ Task 7；嵌进 TaskSummaryOut → Task 3；PUT/DELETE 端点 → Task 4；展开才显示 → Task 9；纯评测数据不影响交易 → 无任何交易路径改动。导出/批量查看明确不在范围。
- **Spec 偏差（需告知用户）**：前端 label 显示状态改放 store 的 `labelsByTask` map（而非直接读 task.label），原因是 WS 整条替换 task 会清掉 label。行为对用户不变，是更稳的实现。
- **类型一致性**：`verdict` 全程 `"correct"|"corrected"`；`CorrectedInstruction` 键集后端 schema 与前端表单/payload 一致；`setLabel`/`labelsByTask`/`setTaskLabel`/`clearTaskLabel` 命名跨任务统一。
- **占位符**：无 TBD；唯一「照搬现有 fixture」的指示在 Task 4 端点测试的 client 搭建处，已明确指向 `test_http.py` 既有模式（该文件 client/token 写法是事实来源，无法在不读取时逐字复制）。
