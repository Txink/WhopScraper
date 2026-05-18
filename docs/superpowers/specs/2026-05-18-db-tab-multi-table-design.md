# 数据库 Tab 多表浏览设计

## 背景

当前 Dashboard 的"数据库记录"面板（`frontend/src/components/Dashboard/DatabaseRecordsPanel.tsx`）只展示 `tasks` 表（join 一部分 `messages` 列），用户看不到 DB 里其他 6 张表的内容。希望像 DB Browser 一样能切换查看所有表。

DB 中现有 7 张表（`backend/app/storage/schema.py`）：

| 表 | 性质 |
|---|---|
| tasks | 业务核心，当前已展示 |
| messages | 1:1 with tasks |
| instructions | 1:1 with tasks |
| push_events | 多对一 with tasks |
| positions | 持仓快照 |
| t_pairs | 做 T 配对 |
| broker_executions | 券商成交记录 |

## 设计原则

- **范围最小**：避免引入复杂的查询/筛选/编辑能力，只做"按表分页浏览"。
- **混合策略**：tasks tab 保留现有精选业务视图（来源页着色、状态高亮），其余 6 张表统一走通用 raw 视图。
- **安全**：通用 endpoint 严格白名单，不接受任意表名/SQL。

## 后端

在 `backend/app/api/http.py` 中新增一个 endpoint（与其他业务 endpoint 同模块，符合现有代码组织）：

### 1. `GET /api/db/{table}`

- `table` 路径参数：必须命中白名单 `{"messages", "instructions", "push_events", "positions", "t_pairs", "broker_executions"}`。**不暴露 `tasks`**——tasks 走原有 `/api/tasks`。
- query 参数：`limit`（默认 15，最大 100），`offset`（默认 0）。
- 返回：

  ```json
  {
    "table": "push_events",
    "columns": ["id", "task_id", "order_id", "state", "received_at", ...],
    "rows": [
      ["evt-1", "task-9", "ord-7", "FILLED", "2026-05-18T...", ...],
      ...
    ],
    "total": 4287
  }
  ```

- 实现方式：用 SQLAlchemy `inspect(engine)` 或直接对 `Base.metadata.tables[table]` 取 `columns`，避免硬编码每张表的 schema。
- 排序：每表用预设排序键 DESC（见下表）。预设字典写在该模块内部，简单清楚。
- JSON 列：原样以 dict/list 形式编码进 `rows`（FastAPI 会序列化）。前端负责 stringify + 截断。

#### 默认排序

| 表 | 排序键 |
|---|---|
| messages | posted_at DESC |
| instructions | task_id DESC |
| push_events | received_at DESC |
| positions | updated_at DESC |
| t_pairs | created_at DESC |
| broker_executions | ts DESC |

### 2. 不新增 `/api/db/tables`

tab 列表前端硬编码，省一个网络请求和一个 endpoint。表名变动不频繁。

## 前端

### 改造 `DatabaseRecordsPanel.tsx`

1. 顶部加 tab bar，固定 7 个 tab：`tasks | messages | instructions | push_events | positions | t_pairs | broker_executions`，默认选中 `tasks`。
2. **当 active tab === `tasks`**：渲染**现有逻辑不动**（继续走 `/api/tasks`，保留 cursor 分页、`pageNameByUrl` 着色、status 高亮）。**`tasks` 不走新的 `/api/db/{table}`**。
3. **当 active tab !== `tasks`**：渲染新的 `<GenericDbTable table={tab} />` 子组件，调用 `/api/db/{table}`：
   - 调 `GET /api/db/{table}?limit=15&offset=N`
   - `<thead>` 按 `columns` 自动渲染
   - `<tbody>` 按 `rows` 自动渲染：
     - 原始类型（string/number/bool/null）：转 string 直接显示，`null` 渲染为占位 `—`
     - 对象/数组：`JSON.stringify`，截断到 ~80 字符，完整内容放进 `<td title="...">` 供 hover 查看
     - datetime ISO 字符串：保持当前 `fmtBeijingFull` 格式化（沿用 `cardHelpers`）
   - 复用现有 `db-pagination` 底栏样式，使用 offset 模式（"上一页" → `offset -= limit`，"下一页" → `offset += limit`，禁用条件由 `total` 与 `offset + limit` 判断）

### API 层（`frontend/src/api/`）

在 `api/http.ts` 加 `api.listDbRows(table: string, opts: { limit?: number; offset?: number })`，返回类型如下：

```ts
interface DbRowsResponse {
  table: string;
  columns: string[];
  rows: unknown[][];
  total: number;
}
```

### CSS

复用现有 `.db-panel / .db-table / .db-pagination` 类名。tab bar 单独加一个 `.db-tab-bar / .db-tab` 类即可，参考项目里已有的 tab 样式（如 `DetailChart` 的 day/minute tab 组）。

## 不做的事

- 不做列排序、筛选、搜索（YAGNI）
- 不做行编辑/删除（数据库 Browser 不是 admin 后台）
- 不做导出 CSV
- 不做列宽自定义
- 不做 schema-introspection UI（用户当前的需求不需要）

## 测试

- 后端：为 `/api/db/{table}` 加 1 个集成测试，覆盖：
  - 白名单外的 table 返回 404
  - 在有数据的表上 limit/offset 行为正确
  - `total` 与实际行数一致
- 前端：`DatabaseRecordsPanel.test.tsx` 加一个 case 测试切换到 `positions` tab 后调用了正确的 API path 并渲染了返回的列。

## 工作量预估

- 后端 endpoint + 测试：~80 行代码
- 前端 `GenericDbTable` 子组件 + tab bar + 测试：~150 行代码
- CSS：~30 行

整体应在一个 PR 内完成。
