# 数据库 Tab 多表浏览实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Dashboard "数据库记录" 面板顶部加 7 个 tab，可切换查看 7 张 DB 表。tasks tab 保留现有精选视图，其他 6 张表走通用 raw 表格。

**Architecture:** 后端在 `http.py` 加一个白名单 endpoint `GET /api/db/{table}`，通过 `Base.metadata.tables` 动态拿列名、SQLAlchemy core 拉数据；前端 `DatabaseRecordsPanel` 拆出 tab bar，分发到 `GenericDbTable` 子组件（其他 6 张表）或现有 tasks 视图。

**Tech Stack:** FastAPI + SQLAlchemy 2.x async + React + TypeScript + Vitest + pytest

**Spec:** `docs/superpowers/specs/2026-05-18-db-tab-multi-table-design.md`

---

## File Structure

**Backend：**
- Modify: `backend/app/api/http.py` — 新增一个 endpoint，放在 `/api/positions` 后面（业务无关 endpoint 区段）
- Modify: `backend/tests/api/test_http.py` — 新增 3 个测试

**Frontend：**
- Modify: `frontend/src/api/http.ts` — 新增 `api.listDbRows` 方法
- Create: `frontend/src/components/Dashboard/GenericDbTable.tsx` — 通用 raw 表格子组件
- Create: `frontend/src/components/Dashboard/GenericDbTable.test.tsx` — 子组件测试
- Modify: `frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx` — 加 tab bar + 分发
- Modify: `frontend/src/components/Dashboard/DatabaseRecordsPanel.test.tsx` — 加 tab 切换测试
- Modify: `frontend/src/components/Dashboard/Dashboard.css` — 加 `.db-tab-bar / .db-tab` 样式

---

## Task 1: 后端 endpoint - 白名单和路径校验（TDD）

**Files:**
- Modify: `backend/app/api/http.py:285+` （在 `/api/positions` endpoint 之后）
- Modify: `backend/tests/api/test_http.py` （文件末尾追加）

**白名单常量与 endpoint 雏形** — 这一任务先把"非白名单返回 404"的行为做出来，下一任务再加查询逻辑。

- [ ] **Step 1: 在测试文件末尾加白名单否决测试**

打开 `backend/tests/api/test_http.py`，跳到文件末尾，追加：

```python
# ---------------------------------------------------------------------------
# /api/db/{table} — generic table browser (whitelist)
# ---------------------------------------------------------------------------

# 6 张白名单内的表（tasks 不在白名单 — 它走 /api/tasks）
_DB_BROWSER_TABLES = [
    "messages",
    "instructions",
    "push_events",
    "positions",
    "t_pairs",
    "broker_executions",
]


def test_db_rows_unknown_table_returns_404(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/db/no_such_table", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_db_rows_tasks_table_not_in_whitelist(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """tasks 走专用 /api/tasks，generic endpoint 不开放 — 防止两条路径
    返回不一致的数据。"""
    client, _ = client_and_broker
    resp = client.get("/api/db/tasks", params={"token": _TOKEN})
    assert resp.status_code == 404
```

- [ ] **Step 2: 跑测试，确认两个用例都失败**

```bash
cd backend && pytest tests/api/test_http.py::test_db_rows_unknown_table_returns_404 tests/api/test_http.py::test_db_rows_tasks_table_not_in_whitelist -v
```

Expected: 两个测试都 FAIL（endpoint 不存在 → 404 来自 FastAPI 默认 router，但实际可能因为 token 缺失先 403；先看实际错误信息再决定）。

Note: 即使两个测试碰巧"PASS"（因为 FastAPI 对未注册路径返回 404），仍然需要写下面的 endpoint 代码——它后续 task 要扩展。

- [ ] **Step 3: 在 `http.py` 加 endpoint 骨架与白名单**

打开 `backend/app/api/http.py`，定位到 `/api/positions` endpoint 结束（约 line 366 之后，`/api/pairs` 之前），在合适位置插入：

```python
    # ------------------------------------------------------------------ #
    # GET /api/db/{table}  — generic table browser (whitelist)              #
    # ------------------------------------------------------------------ #

    # tasks is deliberately excluded — it has a dedicated /api/tasks endpoint
    # with cursor pagination, business filters, and message join. Routing it
    # through the generic browser would expose two divergent code paths.
    _DB_BROWSER_TABLES: dict[str, str] = {
        # table_name → default order column (DESC)
        "messages": "posted_at",
        "instructions": "task_id",
        "push_events": "received_at",
        "positions": "updated_at",
        "t_pairs": "created_at",
        "broker_executions": "ts",
    }

    @router.get("/api/db/{table}")
    async def list_db_rows_endpoint(
        table: str,
        limit: int = Query(15, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        if table not in _DB_BROWSER_TABLES:
            raise HTTPException(404, detail=f"table not browsable: {table!r}")
        # Real query lands in next task.
        return {"table": table, "columns": [], "rows": [], "total": 0}
```

- [ ] **Step 4: 跑测试，确认两个白名单测试通过**

```bash
cd backend && pytest tests/api/test_http.py::test_db_rows_unknown_table_returns_404 tests/api/test_http.py::test_db_rows_tasks_table_not_in_whitelist -v
```

Expected: 两个测试都 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_http.py
git commit -m "$(cat <<'EOF'
feat(api): add /api/db/{table} whitelist skeleton

Generic DB-browser endpoint scaffold. Returns 404 for unknown tables
and for 'tasks' (which has its own dedicated endpoint with cursor
pagination + message join). Query logic lands next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: 后端 endpoint - 真实查询逻辑（TDD）

**Files:**
- Modify: `backend/app/api/http.py` （上一任务新增的 endpoint）
- Modify: `backend/tests/api/test_http.py` （继续追加）

- [ ] **Step 1: 在测试文件追加 "messages 表上有数据 + 分页" 用例**

```python
def test_db_rows_messages_empty(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """空表也要返回结构良好的响应——columns 必须从 schema 派生而不是
    从行里推断，否则空表前端就没列名可渲染。"""
    client, _ = client_and_broker
    resp = client.get("/api/db/messages", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["table"] == "messages"
    assert data["rows"] == []
    assert data["total"] == 0
    # 列名必须从 schema 派生（MessageRow 的 mapped_column）
    assert "id" in data["columns"]
    assert "content" in data["columns"]
    assert "posted_at" in data["columns"]


def test_db_rows_messages_pagination(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    three_tasks: list[Task],
) -> None:
    """three_tasks 创建 3 个 task 同时通过 cascade 写入 3 行 messages。
    我们用 messages 表验证分页行为。"""
    client, _ = client_and_broker

    # 第 1 页: limit=2, offset=0 → 拿到 2 行（按 posted_at DESC，是 m3, m2）
    resp = client.get("/api/db/messages", params={"token": _TOKEN, "limit": 2, "offset": 0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["rows"]) == 2
    id_idx = data["columns"].index("id")
    ids_page1 = [row[id_idx] for row in data["rows"]]
    assert ids_page1 == ["t3", "t2"]

    # 第 2 页: limit=2, offset=2 → 拿到剩下 1 行（m1）
    resp = client.get("/api/db/messages", params={"token": _TOKEN, "limit": 2, "offset": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["rows"]) == 1
    ids_page2 = [row[id_idx] for row in data["rows"]]
    assert ids_page2 == ["t1"]
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd backend && pytest tests/api/test_http.py::test_db_rows_messages_empty tests/api/test_http.py::test_db_rows_messages_pagination -v
```

Expected: 两个用例 FAIL。`test_db_rows_messages_empty` 因为 columns 是空数组；`test_db_rows_messages_pagination` 因为 rows 是空数组。

- [ ] **Step 3: 在 `http.py` 顶部加 SQLAlchemy import**

定位到 `http.py` 的 sqlalchemy import 行（约 line 43）：

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
```

在其下一行加：

```python
from sqlalchemy import desc, func, select
```

并确认顶部已经有 `from app.storage.db import Base` 这行 import；如果没有，添加：

```python
from app.storage.db import Base
```

（通过 grep 检查：`grep -n "from app.storage" backend/app/api/http.py`，确认 `Base` 是否已导入；没有就加。）

- [ ] **Step 4: 实现真实查询**

把上一任务 Step 3 的 `list_db_rows_endpoint` 函数体替换为：

```python
    @router.get("/api/db/{table}")
    async def list_db_rows_endpoint(
        table: str,
        limit: int = Query(15, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        if table not in _DB_BROWSER_TABLES:
            raise HTTPException(404, detail=f"table not browsable: {table!r}")

        sa_table = Base.metadata.tables[table]
        order_col = sa_table.c[_DB_BROWSER_TABLES[table]]
        columns = [c.name for c in sa_table.columns]

        async with session_scope(session_factory) as session:
            total_result = await session.execute(
                select(func.count()).select_from(sa_table)
            )
            total = total_result.scalar_one()

            rows_result = await session.execute(
                select(sa_table)
                .order_by(desc(order_col))
                .limit(limit)
                .offset(offset)
            )
            rows = [list(r) for r in rows_result.all()]

        return {"table": table, "columns": columns, "rows": rows, "total": total}
```

- [ ] **Step 5: 跑两个新测试**

```bash
cd backend && pytest tests/api/test_http.py::test_db_rows_messages_empty tests/api/test_http.py::test_db_rows_messages_pagination -v
```

Expected: 两个 PASS。

- [ ] **Step 6: 跑整个 test_http.py 确保没把已有测试搞坏**

```bash
cd backend && pytest tests/api/test_http.py -v
```

Expected: 全部 PASS。

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/http.py backend/tests/api/test_http.py
git commit -m "$(cat <<'EOF'
feat(api): /api/db/{table} returns paginated rows + columns

Columns derived from SQLAlchemy Base.metadata so empty tables still
expose their schema to the frontend. Per-table default ordering
(DESC on a sensible timestamp / PK column) baked into the whitelist.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: 前端 API 客户端方法

**Files:**
- Modify: `frontend/src/api/http.ts`

- [ ] **Step 1: 加 `DbRowsResponse` 类型与 `api.listDbRows` 方法**

在 `frontend/src/api/http.ts` 中：

1. 在 `export const api = {` 上方（约 line 73 附近，紧贴 `HttpError` 之后或 `request()` 之后）加类型定义：

```typescript
export interface DbRowsResponse {
  table: string;
  columns: string[];
  rows: unknown[][];
  total: number;
}
```

2. 在 `api` 对象内的 `countTasks` 方法之后（约 line 103 之后）加：

```typescript
  async listDbRows(
    table: string,
    params: { limit?: number; offset?: number } = {},
  ): Promise<DbRowsResponse> {
    const qs = new URLSearchParams();
    if (params.limit !== undefined) qs.set("limit", String(params.limit));
    if (params.offset !== undefined) qs.set("offset", String(params.offset));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<DbRowsResponse>(`/api/db/${encodeURIComponent(table)}${suffix}`);
  },
```

- [ ] **Step 2: 编译检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/http.ts
git commit -m "$(cat <<'EOF'
feat(api-client): add listDbRows for generic table browser

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: 前端 `<GenericDbTable>` 组件（TDD）

**Files:**
- Create: `frontend/src/components/Dashboard/GenericDbTable.test.tsx`
- Create: `frontend/src/components/Dashboard/GenericDbTable.tsx`

- [ ] **Step 1: 先写测试**

创建 `frontend/src/components/Dashboard/GenericDbTable.test.tsx`：

```typescript
import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import * as httpModule from "../../api/http";
import { GenericDbTable } from "./GenericDbTable";

describe("<GenericDbTable>", () => {
  it("renders columns and rows from API", async () => {
    vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "messages",
      columns: ["id", "content", "posted_at"],
      rows: [
        ["m1", "AAPL buy", "2026-04-25T00:00:00Z"],
        ["m2", "TSLA sell", "2026-04-24T00:00:00Z"],
      ],
      total: 2,
    });

    render(<GenericDbTable table="messages" />);
    await waitFor(() => expect(screen.getByText("AAPL buy")).toBeInTheDocument());

    expect(screen.getByText("id")).toBeInTheDocument();
    expect(screen.getByText("posted_at")).toBeInTheDocument();
    expect(screen.getByText("m1")).toBeInTheDocument();
    expect(screen.getByText("第 1 页 / 共 1 页")).toBeInTheDocument();
  });

  it("stringifies JSON cells with title attribute for hover", async () => {
    const payload = { foo: "bar", n: 42 };
    vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "push_events",
      columns: ["id", "payload_json"],
      rows: [["evt1", payload]],
      total: 1,
    });

    render(<GenericDbTable table="push_events" />);
    await waitFor(() => expect(screen.getByText("evt1")).toBeInTheDocument());

    const cell = screen.getByTitle(JSON.stringify(payload));
    expect(cell).toBeInTheDocument();
    expect(cell.textContent).toContain('"foo"');
  });

  it("renders null cells as em-dash", async () => {
    vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "messages",
      columns: ["id", "author"],
      rows: [["m1", null]],
      total: 1,
    });

    render(<GenericDbTable table="messages" />);
    await waitFor(() => expect(screen.getByText("m1")).toBeInTheDocument());

    // 找到 "author" 列对应的 cell — 用 row 内的 cell index
    const row = screen.getByText("m1").closest("tr")!;
    const cells = row.querySelectorAll("td");
    expect(cells[1].textContent).toBe("—");
  });

  it("paginates via offset on next/prev", async () => {
    const spy = vi
      .spyOn(httpModule.api, "listDbRows")
      .mockResolvedValueOnce({
        table: "messages",
        columns: ["id"],
        rows: [["a"]],
        total: 25,
      })
      .mockResolvedValueOnce({
        table: "messages",
        columns: ["id"],
        rows: [["b"]],
        total: 25,
      });

    render(<GenericDbTable table="messages" />);
    await waitFor(() => expect(screen.getByText("a")).toBeInTheDocument());
    expect(spy).toHaveBeenNthCalledWith(1, "messages", { limit: 15, offset: 0 });

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await waitFor(() => expect(screen.getByText("b")).toBeInTheDocument());
    expect(spy).toHaveBeenNthCalledWith(2, "messages", { limit: 15, offset: 15 });
  });
});
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd frontend && npx vitest run src/components/Dashboard/GenericDbTable.test.tsx
```

Expected: 全部 FAIL（GenericDbTable 文件不存在）。

- [ ] **Step 3: 实现组件**

创建 `frontend/src/components/Dashboard/GenericDbTable.tsx`：

```typescript
import { useEffect, useState } from "react";
import { api, HttpError, type DbRowsResponse } from "../../api/http";

const PAGE_SIZE = 15;
const JSON_TRUNCATE = 80;

interface Props {
  table: string;
}

function renderCell(value: unknown): { text: string; title?: string } {
  if (value === null || value === undefined) {
    return { text: "—" };
  }
  if (typeof value === "object") {
    const full = JSON.stringify(value);
    const text = full.length > JSON_TRUNCATE ? full.slice(0, JSON_TRUNCATE) + "…" : full;
    return { text, title: full };
  }
  return { text: String(value) };
}

export function GenericDbTable({ table }: Props) {
  const [data, setData] = useState<DbRowsResponse | null>(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setOffset(0);
  }, [table]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .listDbRows(table, { limit: PAGE_SIZE, offset })
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof HttpError) setError(e.message);
        else setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [table, offset]);

  const total = data?.total ?? 0;
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  return (
    <>
      {error && <div className="db-error">{error}</div>}

      {!loading && data && data.rows.length === 0 ? (
        <div className="empty-state">
          <p>表 <code>{table}</code> 暂无数据。</p>
        </div>
      ) : (
        <div className="db-table-wrap">
          <table className="db-table">
            <thead>
              <tr>
                {data?.columns.map((col) => (
                  <th key={col}>{col}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => {
                    const rendered = renderCell(cell);
                    return (
                      <td key={j} title={rendered.title}>
                        {rendered.text}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <footer className="db-pagination">
        <button
          className="db-page-btn"
          onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          disabled={loading || !hasPrev}
        >
          上一页
        </button>
        <span className="db-page-indicator">
          第 {currentPage} 页 / 共 {totalPages} 页
        </span>
        <button
          className="db-page-btn"
          onClick={() => setOffset((o) => o + PAGE_SIZE)}
          disabled={loading || !hasNext}
        >
          下一页
        </button>
      </footer>
    </>
  );
}
```

Note: 该组件不暴露刷新按钮——刷新逻辑只保留在 tasks tab（由 panel 拥有），其他 tab 想刷新就来回切一次 tab 即可。

- [ ] **Step 4: 跑测试**

```bash
cd frontend && npx vitest run src/components/Dashboard/GenericDbTable.test.tsx
```

Expected: 全部 PASS。

- [ ] **Step 5: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Dashboard/GenericDbTable.tsx frontend/src/components/Dashboard/GenericDbTable.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): GenericDbTable for raw DB-table browsing

Renders rows from /api/db/{table}, JSON cells truncate with full
content in title attribute, null shows as em-dash, offset pagination.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 在 `DatabaseRecordsPanel` 加 tab bar 并分发

**Files:**
- Modify: `frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx`
- Modify: `frontend/src/components/Dashboard/DatabaseRecordsPanel.test.tsx`

- [ ] **Step 1: 在 `DatabaseRecordsPanel.test.tsx` 加切换 tab 的测试**

打开 `frontend/src/components/Dashboard/DatabaseRecordsPanel.test.tsx`，在最后一个 `it(...)` 之后追加：

```typescript
  it("switches to a non-tasks tab and calls listDbRows", async () => {
    vi.spyOn(httpModule.api, "listTasks").mockResolvedValue({
      tasks: [],
      next_cursor: null,
    });
    vi.spyOn(httpModule.api, "countTasks").mockResolvedValue({ total_count: 0 });
    const dbSpy = vi.spyOn(httpModule.api, "listDbRows").mockResolvedValue({
      table: "messages",
      columns: ["id", "content"],
      rows: [["m1", "hello"]],
      total: 1,
    });

    render(<DatabaseRecordsPanel pageNameByUrl={new Map()} />);
    // 默认是 tasks tab，等它加载完
    await waitFor(() => expect(httpModule.api.listTasks).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("tab", { name: "messages" }));
    await waitFor(() => expect(screen.getByText("hello")).toBeInTheDocument());

    expect(dbSpy).toHaveBeenCalledWith("messages", { limit: 15, offset: 0 });
  });
```

- [ ] **Step 2: 跑测试，确认失败**

```bash
cd frontend && npx vitest run src/components/Dashboard/DatabaseRecordsPanel.test.tsx
```

Expected: 新增的 case FAIL（没有名为 "messages" 的 button）。已有两个测试应当继续 PASS（因为还没改 panel）。

- [ ] **Step 3: 改造 `DatabaseRecordsPanel.tsx`**

打开 `frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx`，把整个文件替换为：

```typescript
import { useEffect, useMemo, useState } from "react";
import type { TaskSummary } from "../../api/domain-types";
import { api, HttpError } from "../../api/http";
import { fmtBeijingFull } from "../Card/cardHelpers";
import { GenericDbTable } from "./GenericDbTable";

const PAGE_SIZE = 15;

const TABLE_TABS = [
  "tasks",
  "messages",
  "instructions",
  "push_events",
  "positions",
  "t_pairs",
  "broker_executions",
] as const;

type TableTab = (typeof TABLE_TABS)[number];

function fmtTime(ts: string): string {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return fmtBeijingFull(ts);
}

function getMessageTime(task: TaskSummary): string {
  return task.message.posted_at || task.message.received_at || task.created_at;
}

interface Props {
  pageNameByUrl: Map<string, string>;
}

export function DatabaseRecordsPanel({ pageNameByUrl }: Props) {
  const [activeTab, setActiveTab] = useState<TableTab>("tasks");

  return (
    <section className="db-panel" aria-label="数据库记录">
      <header className="db-panel-head">
        <div className="db-panel-title-wrap">
          <h3>数据库记录</h3>
          <p>按表分页查看持久化记录</p>
        </div>
      </header>

      <nav className="db-tab-bar" role="tablist">
        {TABLE_TABS.map((t) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={activeTab === t}
            className={`db-tab${activeTab === t ? " active" : ""}`}
            onClick={() => setActiveTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>

      {activeTab === "tasks" ? (
        <TasksTabContent pageNameByUrl={pageNameByUrl} />
      ) : (
        <GenericDbTable table={activeTab} />
      )}
    </section>
  );
}

// ---- tasks tab (preserved curated view) ----

function TasksTabContent({ pageNameByUrl }: Props) {
  const [currentPage, setCurrentPage] = useState(1);
  const [pageRows, setPageRows] = useState<Record<number, TaskSummary[]>>({});
  const [pageCursor, setPageCursor] = useState<Record<number, string | null>>({ 1: null });
  const [pageNextCursor, setPageNextCursor] = useState<Record<number, string | null>>({});
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadPage = async (page: number, force = false) => {
    if (!force && pageRows[page]) return;
    const cursor = pageCursor[page];
    if (cursor === undefined) return;

    setLoading(true);
    setError(null);
    try {
      const [r, c] = await Promise.all([
        api.listTasks(cursor ? { limit: PAGE_SIZE, cursor } : { limit: PAGE_SIZE }),
        api.countTasks(),
      ]);
      const nextCursor = r.next_cursor ?? null;
      setPageRows((prev) => ({ ...prev, [page]: r.tasks }));
      setPageNextCursor((prev) => ({ ...prev, [page]: nextCursor }));
      setTotalCount(c.total_count);
      if (nextCursor !== null) {
        setPageCursor((prev) => (prev[page + 1] !== undefined ? prev : { ...prev, [page + 1]: nextCursor }));
      }
    } catch (e) {
      if (e instanceof HttpError) {
        setError(e.message);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadPage(currentPage);
  }, [currentPage]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = async () => {
    await loadPage(currentPage, true);
  };

  const records = pageRows[currentPage] ?? [];
  const hasPrev = currentPage > 1;
  const hasNext = pageNextCursor[currentPage] != null;
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));

  const rows = useMemo(
    () =>
      records.map((task) => {
        const sourceUrl = task.message.url;
        const pageName = sourceUrl ? pageNameByUrl.get(sourceUrl) : null;
        const sourceState = sourceUrl == null ? "missing" : pageName ? "active" : "orphan";
        const sourceLabel =
          sourceState === "active"
            ? pageName!
            : sourceState === "orphan"
              ? "已移除页面"
              : "无来源";
        return { task, sourceState, sourceLabel };
      }),
    [records, pageNameByUrl],
  );

  return (
    <>
      <div className="db-tasks-toolbar">
        <button className="db-refresh-btn" onClick={refresh} disabled={loading}>
          {loading ? "刷新中…" : "刷新"}
        </button>
      </div>

      {error && <div className="db-error">{error}</div>}

      {!loading && rows.length === 0 ? (
        <div className="empty-state">
          <p>数据库中暂无记录。</p>
        </div>
      ) : (
        <div className="db-table-wrap">
          <table className="db-table">
            <thead>
              <tr>
                <th>消息时间</th>
                <th>来源页</th>
                <th>状态</th>
                <th>作者</th>
                <th>摘要</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ task, sourceState, sourceLabel }) => (
                <tr key={task.id}>
                  <td>{fmtTime(getMessageTime(task))}</td>
                  <td>
                    <span className={`db-source ${sourceState}`}>{sourceLabel}</span>
                  </td>
                  <td className={`db-status ${task.status.toLowerCase()}`}>{task.status}</td>
                  <td>{task.message.author ?? "—"}</td>
                  <td className="db-content">{task.message.content}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <footer className="db-pagination">
        <button
          className="db-page-btn"
          onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
          disabled={loading || !hasPrev}
        >
          上一页
        </button>
        <span className="db-page-indicator">
          第 {currentPage} 页 / 共 {totalPages} 页
        </span>
        <button
          className="db-page-btn"
          onClick={() => setCurrentPage((p) => p + 1)}
          disabled={loading || !hasNext}
        >
          下一页
        </button>
      </footer>
    </>
  );
}
```

- [ ] **Step 4: 跑 panel 测试**

```bash
cd frontend && npx vitest run src/components/Dashboard/DatabaseRecordsPanel.test.tsx
```

Expected: 全部 3 个 case PASS。

注意：已有两个测试用了 `expect(screen.getByText("数据库记录")).toBeInTheDocument()` 和 `expect(screen.getByText("第 1 页 / 共 1 页"))`——这些应仍然 PASS，因为 tasks tab 默认激活且保留了原文案。

- [ ] **Step 5: 类型检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 0 errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx frontend/src/components/Dashboard/DatabaseRecordsPanel.test.tsx
git commit -m "$(cat <<'EOF'
feat(dashboard): tab bar in DatabaseRecordsPanel for all 7 tables

tasks tab keeps the curated view with source-page coloring + status
highlight; other 6 tabs render via GenericDbTable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: CSS - tab bar 样式

**Files:**
- Modify: `frontend/src/components/Dashboard/Dashboard.css`

- [ ] **Step 1: 在 `.db-panel-head` 之后插入 tab bar 样式**

打开 `frontend/src/components/Dashboard/Dashboard.css`，找到 `.db-panel-title-wrap p { ... }` 结束的位置（约 line 415）。在它之后、`.db-refresh-btn` 之前，插入：

```css
.db-tab-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 12px 8px;
  border-bottom: 1px solid var(--line);
  background: var(--bg-2);
}
.db-tab {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--fg-3);
  padding: 4px 10px;
  border-radius: var(--radius-chip);
  font: inherit;
  font-size: 11px;
  font-family: var(--font-mono);
  cursor: pointer;
}
.db-tab:hover {
  color: var(--fg-1);
  border-color: var(--fg-3);
}
.db-tab.active {
  color: var(--fg-1);
  border-color: var(--fg-1);
  background: rgba(255, 255, 255, 0.04);
}
.db-tasks-toolbar {
  display: flex;
  justify-content: flex-end;
  padding: 8px 12px 0;
}
```

- [ ] **Step 2: 起前端 dev server，浏览器验证**

```bash
cd frontend && npm run dev
```

打开浏览器到 dev server URL（通常 `http://localhost:5173`），登录后进 Dashboard，验证：

1. "数据库记录" 面板顶部出现 7 个 tab（小 chip 样式，monospace 字体），`tasks` 默认高亮选中
2. 点击 `messages` tab → 切换到 raw 表格，列名是 `id / content / raw_content / author / source / posted_at / received_at / url / quoted_message_id`，分页"上一页/下一页"工作
3. 点击 `push_events` tab → `payload_json` 列截断显示，hover 看到完整 JSON
4. 点击其他 tab（`instructions / positions / t_pairs / broker_executions`）→ 都有数据展示，无报错
5. 切回 `tasks` tab → 原有"来源页着色 / 状态高亮"仍然在

如果某些表没数据，预期看到 "表 `xxx` 暂无数据。" 占位（这是正常的，不算 bug）。

- [ ] **Step 3: 类型检查 + 全量前端测试**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```

Expected: 0 type errors，所有测试 PASS。

- [ ] **Step 4: 全量后端测试**

```bash
cd backend && pytest
```

Expected: 全部 PASS。

- [ ] **Step 5: Commit CSS**

```bash
git add frontend/src/components/Dashboard/Dashboard.css
git commit -m "$(cat <<'EOF'
style(dashboard): tab bar styling for DB table browser

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage check：** 
  - 后端 `/api/db/{table}` whitelist + limit/offset + 默认排序 → Task 1, 2 ✓
  - 不暴露 `/api/db/tables` endpoint，前端硬编码 7 个 tab → Task 5 ✓
  - tasks tab 走旧 `/api/tasks`，保留着色 → Task 5 `TasksTabContent` ✓
  - 其他 6 表走 `<GenericDbTable>` → Task 4 + Task 5 ✓
  - JSON 列截断 + hover 看全文 → Task 4 `renderCell` ✓
  - 后端 + 前端测试 → Task 1, 2, 4, 5 ✓
- **Placeholder scan：** 无 TBD / TODO / "similar to" 字样。
- **Type consistency：** `DbRowsResponse.rows: unknown[][]`、`api.listDbRows(table, opts)` 签名前后一致；`TableTab` 类型在 panel 内部定义，传入 `GenericDbTable` 的 `table: string` props 兼容。
