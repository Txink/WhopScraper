# 监控看板二级 tab + per-page 监听设置 设计文档

| 字段 | 值 |
|------|-----|
| 日期 | 2026-04-25 |
| 状态 | Draft（待用户审阅） |
| 影响范围 | 全栈：DB schema、parser、broker/trader、registry、REST、WS、前端 dashboard |
| 是否破坏性 | **是**：`config/watched_stocks.json` 废弃；`Trader` 价格偏差语义从"拒单 gate"改为"order_type 决策" |

---

## 1. 背景

当前监控看板（dashboard tab）把所有 task 混在一个流里，按日期分组倒序展示。无法按"来源监听页"分流；监听页的"设置"（避免重复解析、可下单 ticker 列表 + 数量、价格偏差阈值）目前散落在 `.env` 全局 settings 和 `config/watched_stocks.json` 全局文件，无法在 UI 内编辑。

本设计在监控看板内增加二级 tab（每个 Whop 监听页一个 tab），加入 per-page 设置，并把价格偏差从"超阈拒单"改成"超阈降级到限价单"。

---

## 2. 决策摘要（用户确认）

| # | 决策 | 选择 |
|---|------|------|
| Q1 | 二级 tab 粒度 | 每个监听页一个 tab |
| Q2 | 设置作用域 | per-page（不共享） |
| Q3 | 价格偏差行为 | 之内 MARKET、之外 LIMIT@signal_price，永不拒单 |
| Q4 | 与 `watched_stocks.json` 关系 | 完全废弃，per-page ticker 重新实现 |
| Q5a | 去重数据源 | 复用 SQLite，listener 启动从 DB 灌 `_seen` |
| Q5b | 触发时机 | 启动 + restart 都灌；开关关闭走旧行为 |
| Q6a | 信息行内容 | name + source 标签 + URL hover + running + last_poll + messages_published + last_error |
| Q6b | 设置入口形态 | 弹窗 modal |
| Q6c | 全展开/收缩作用域 | 当前 tab 内所有 Card；状态 per-tab；不持久化（刷新回 smart） |
| Q7 | 移除 page 后的历史 task | 孤儿 tab（灰色徽章，可浏览不可重启/改设置） |
| Q8a | 默认进入哪个 tab | 上次浏览（localStorage），fallback 第一个 |
| Q8b | 无监听页空态 | 显示 EmptyState 提示去 Whop 管理添加 |
| Q9a | ticker key 大小写 | 全大写存储 |
| Q9b | watched_stocks migration | 不做自动 migration，用户手动迁移 |
| Q9c | 老 task `url=None` | 走孤儿 tab |
| Q10 | 数量取整粒度 | 向下取整到 1（`int(qty)`） |
| 期权白名单 | 期权是否需要 ticker 白名单 | 否 |
| 设置生效时机 | dedupe 切换是否立即生效 | 否，下次重启才生效 |

---

## 3. UI 设计

### 3.1 监控看板内部结构

```
┌── Dashboard ──────────────────────────────────────┐
│ <PageTabs>                                         │  ← per-page 二级 tab
│   [正股A] [期权A] [正股B] [已停用]                 │
├────────────────────────────────────────────────────┤
│ <PageInfoBar>                                      │  ← 信息行
│   [正股] 正股A · 运行中 · 最后轮询 5s前            │
│   已发消息 234   ⓘ url (hover)                     │
├────────────────────────────────────────────────────┤
│ <PageActionBar>                                    │  ← 操作行
│   [↻ 重启] [⚙ 设置] [⤓ 全展开] [⤒ 全收缩]         │
├────────────────────────────────────────────────────┤
│ <TaskStream>                                       │  ← 任务流（filter by url）
│   今天 04-25 · 12                                  │
│   Card · Card · Card ...                          │
└────────────────────────────────────────────────────┘

  ⚙ 设置点击 → <PageSettingsModal>（覆盖在上面）
```

### 3.2 组件拆分

```
components/Dashboard/
  ├── PageTabs.tsx           // 二级 tab + 孤儿
  ├── PageInfoBar.tsx        // 信息行
  ├── PageActionBar.tsx      // 重启 / 设置 / 全展开 / 全收缩
  ├── PageSettingsModal.tsx  // 设置弹窗
  │     ├── DedupeToggle.tsx
  │     ├── DeviationInput.tsx
  │     └── TickerListEditor.tsx  (stock only)
  ├── TaskStream.tsx         // 接收 filtered tasks，复用现有 DateGroups + Card
  └── EmptyState.tsx
```

`Dashboard.tsx`（现有）改成 orchestrator，不再直接渲染 task 流。

### 3.3 孤儿 tab 显示规则

- 计算：`orphanTasks = tasks.filter(t => t.url == null || !pageUrls.has(t.url))`
- 渲染：仅当 `orphanTasks.length > 0` 时才显示「已停用」tab
- tab 内：禁用「重启」「设置」按钮（无对应 page），其余 UI 一致；按 `task.url` 二级分组显示

### 3.4 空态（无任何监听页）

PageTabs / InfoBar / ActionBar / TaskStream 全部隐藏，渲染 `<EmptyState>`：

```
还没有任何监听页。
点这里 → [跳转到 Whop 管理] 添加你的第一个监听。
```

### 3.5 全展开 / 全收缩

- store 字段：`expandModeByTab: Record<string, "smart" | "all-open" | "all-closed">`，默认 `"smart"`
- Card 渲染时：
  ```
  effectiveExpanded =
    expandMode === "smart" ? isActiveExpanded(task) :
    expandMode === "all-open"
  ```
- 状态范围：当前 tab 内所有 Card 一致；切 tab 不影响其他 tab 的状态
- 持久化：**不持久化**，刷新页面所有 tab 回 `"smart"`
- `expandModeByTab[tabId]` 在 store 中未设置时按 `"smart"` 处理（默认值，不需要预填）

---

## 4. 数据模型

### 4.1 `WhopPageEntry` 增加 `settings` 字段

`data/whop_pages.json` 每条 entry：

```json
{
  "id": "3ed65f045344",
  "url": "https://whop.com/joined/.../app/",
  "source": "stock",
  "name": "监听正股",
  "added_at": "2026-04-25T06:26:31+00:00",
  "settings": {
    "dedupe_processed_messages": true,
    "price_deviation_tolerance": 1.0,
    "tickers": {
      "TSLL": { "trade_quantity": 2000 },
      "NVDA": { "trade_quantity": 500 }
    }
  }
}
```

期权 page 的 `settings` 没有 `tickers` 字段：

```json
{
  "settings": {
    "dedupe_processed_messages": true,
    "price_deviation_tolerance": 5.0
  }
}
```

### 4.2 默认 settings 模板

| 字段 | stock 默认 | option 默认 |
|------|----------|----------|
| `dedupe_processed_messages` | `true` | `true` |
| `price_deviation_tolerance` | `1.0` | `5.0` |
| `tickers` | `{}` | （不存在） |

新建 page 时如果调用方未传 `settings`，后端按 source 填默认。

### 4.3 `messages` 表 schema 变更

- alembic migration：`ALTER TABLE messages ADD COLUMN url TEXT NULL`
- index：`CREATE INDEX idx_messages_url ON messages(url)`
- domain `Message` 加 `url: str | None`
- `MessagePayload` dataclass 加 `url: str | None`（实际通过 message 字段间接传递即可，看实现选择）
- `WhopListener._scan_once` 发布消息时把 `self._url` 注入 `Message.url`

### 4.4 `Task.url` 暴露

- DB 不在 `tasks` 表加列；`Task.url` 通过 `Task.message.url` 间接取
- API serializer：`TaskSummary.url: str | None` 由 `task.message.url` 提供
- 老 task（migration 前）`url=None` → 孤儿 tab

### 4.5 `watched_stocks.json` 退役

需要修改的引用点：

| 文件 | 当前用途 | 改为 |
|------|---------|------|
| `parser/stock_parser.py` (root) | fallback 匹配 ticker | 接收 `tickers: list[str]` 参数；调用方按 page 注入 |
| `backend/app/parser/context_resolver.py` | 同上 | 同上 |
| `parser/stock_context_resolver.py` | resolve position size | 直接从 page settings 取 |
| `broker/position_manager.py` (root) | bucket / position 计算 | 全部从 page settings 反查 |

`config/watched_stocks.json` 和 `utils/watched_stocks.py`（如果存在）被删除。`Settings.stock_price_deviation_tolerance` / `Settings.price_deviation_tolerance` 字段保留作为孤儿 task 的 fallback 阈值（trader 反查不到 page 时用），其他场合不再读。

**注入方式**：parser 是纯函数。`ParserService` 订阅 `message.received` 时拿到 `message.url`，从 `WhopRegistry.get_settings_for_url(url)` 取 page settings，把 `tickers: list[str]`（仅 stock）作为函数参数传入 `stock_parser.parse(...)`。`WhopRegistry` 通过 DI 注入 `ParserService`。孤儿 message（`url=None` 或反查不到）→ 传入空 ticker 列表，parser 走"无 fallback 列表"分支（识别率会下降，但仍能跑显式信号）。

### 4.6 新增 Task 状态：`SKIPPED`

- 用于 trader 白名单 gate：ticker 不在 page.settings.tickers 时跳过下单
- Status enum 加 `SKIPPED`
- 前端 Card 显示灰色徽章 + reason hover
- 不算错误（与 `submit_failed` 区分）

---

## 5. 后端逻辑变更

### 5.1 `WhopListener` 去重逻辑

```python
class WhopListener:
    def __init__(self, *, ..., dedupe_processed_messages: bool = True):
        self._dedupe = dedupe_processed_messages

    async def start(self):
        # ... browser setup ...
        if self._dedupe:
            self._seen = await load_seen_ids_for_url(self._url)
            # 历史 ID 已经在 _seen，无需 prime DOM
        else:
            self._seen = set()
            if self._skip_initial:
                # 旧行为：DOM 现状当起点
                html = await self._browser.scrape_html()
                initial = extract_messages(html, source=self._source)
                self._seen.update(m.id for m in initial)
        # ... rest ...
```

`load_seen_ids_for_url` 在 `storage/repo.py` 新增：

```python
async def load_seen_ids_for_url(url: str) -> set[str]:
    """SELECT id FROM messages WHERE url=?"""
```

### 5.2 行为矩阵

| 场景 | dedupe=on | dedupe=off |
|------|-----------|-----------|
| 启动 | 灌 DB → 不漏不重 | `skip_initial=True`（旧行为）|
| 手动重启 | 灌 DB → 不重发已处理消息 | `skip_initial=False`（旧行为）|

### 5.3 设置变更生效策略

- `PATCH /api/whop/pages/{id}/settings` 不立即重启 listener
- `dedupe_processed_messages`：下次手动 / 自动重启时才生效
- `price_deviation_tolerance` / `tickers`：trader 在每次决策时反查 registry，**立即生效**

前端 modal 在改 dedupe 字段时弹 hint：「下次重启监听才生效」

### 5.4 `Trader` 改造

伪代码示意（字段名 `symbol_root` / `position_fraction` 是占位 — 实施时按现有 `Instruction` domain 实际命名调整；如果当前 model 没有"仓位比例"概念，则在 instruction 解析阶段补这个字段）：

```python
async def on_instruction_ready(self, payload):
    task = payload.task
    page_settings = self._registry.get_settings_for_url(task.message.url)

    # 4.4 ticker 白名单（仅 stock + 非孤儿）
    if task.source == "stock" and page_settings is not None:
        ticker = task.instruction.symbol_root.upper()
        if ticker not in page_settings.tickers:
            await self._publish_skipped(task, reason="ticker not in trade whitelist")
            return
        # 4.5 数量计算：page 配置的 trade_quantity × 仓位比例，向下取整、最小 1
        base_qty = page_settings.tickers[ticker].trade_quantity
        qty = max(int(base_qty * task.instruction.position_fraction), 1)
    elif task.source == "stock" and page_settings is None:
        # 孤儿 stock task：跳过白名单检查；qty 用 instruction 自带值或 fallback
        qty = task.instruction.quantity or 0
        if qty == 0:
            await self._publish_skipped(task, reason="orphan task with no qty")
            return
    else:
        # 期权
        qty = task.instruction.quantity

    # 4.2 偏差决策（page settings 优先，孤儿 task fallback 全局）
    market_price = await self._broker.quote(task.instruction.symbol)
    signal_price = task.instruction.price
    tolerance = (page_settings.price_deviation_tolerance
                 if page_settings is not None
                 else self._fallback_tolerance(task.source))
    deviation = abs(market_price - signal_price) / signal_price

    if deviation <= tolerance / 100.0:    # tolerance 字段单位是百分比
        order_type, limit_price = "MARKET", None
    else:
        order_type, limit_price = "LIMIT", signal_price

    await self._broker.submit(qty=qty, order_type=order_type, limit_price=limit_price, ...)
```

**孤儿 task 行为总结**：
- stock 孤儿：跳过白名单；qty 用 instruction 自带值（若无 → SKIPPED）；偏差用全局 fallback
- option 孤儿：qty 用 instruction（期权 instruction 必有 qty）；偏差用全局 fallback

### 5.5 取整规则

数量计算 `qty = int(base_qty * fraction)`（向下取整到 1）。最小值 1（`max(int(qty), 1)`）防止"1/3 仓 × 1 股 = 0"。

### 5.6 `WhopRegistry` 新增 API

```python
async def update_settings(page_id: str, settings_patch: dict) -> WhopPageEntry:
    """局部更新 entry.settings，持久化，触发 whop.page_changed 事件。"""

def get_settings_for_url(url: str | None) -> PageSettings | None:
    """O(1) lookup by URL（内部维护 url → entry 反查表）。返回 None 表示孤儿。"""
```

`PageSettings` 是 dataclass：`dedupe_processed_messages: bool`、`price_deviation_tolerance: float`、`tickers: dict[str, TickerConfig]`（option 无此字段）。

### 5.7 settings PATCH validation

| 字段 | 规则 |
|------|------|
| `tickers` 的 key | 自动 `.upper()` |
| `tickers[T].trade_quantity` | int > 0 |
| `price_deviation_tolerance` | float ≥ 0 |
| option page 传 `tickers` | 422 error |
| stock page 传 `tickers` 但 ticker 名格式非法（含特殊字符） | 422 error |

---

## 6. API + WS 协议

### 6.1 REST 端点变更

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/whop/pages` | 改返回：每条 entry 多 `settings` 字段 |
| POST | `/api/whop/pages` | 改入参：可选 `settings`；不传走 source 默认 |
| **PATCH** | `/api/whop/pages/{id}/settings` | **新**：局部更新 settings |
| **GET** | `/api/whop/pages/{id}/settings/defaults?source=stock` | **新**：返回 source 默认模板（前端"重置"用） |
| GET | `/api/tasks?...` | 返回的 `TaskSummary` 加 `url: str \| null` |
| GET | `/api/tasks/{id}` | 同上 |

### 6.2 新增 WS 事件

| topic | payload | 触发 |
|-------|---------|------|
| `whop.page_changed` | `{action: "added"\|"removed"\|"restarted"\|"settings_updated", page: WhopPage}` | registry 任何变更后 |

`task.status_changed` 已存在；新增 `SKIPPED` 状态值，前端 switch 处理。

### 6.3 OpenAPI / 类型同步

- 后端改 schema 后，跑 `cd frontend && npm run gen:types` 重新生成 `frontend/openapi.json` + `frontend/src/api/types.ts`

### 6.4 兼容性

- 旧前端连新后端：会收到 `whop.page_changed` 不识别 → switch 默认分支忽略，无害
- 旧 WS clients 续传 `?since=` 仍工作

---

## 7. 前端 store 设计

### 7.1 新增 `stores/pageTabs.ts`

```typescript
interface PageTabsState {
  pages: WhopPage[];                                      // 实时同步 from WS
  activeTabId: string | "orphan" | null;                  // null = 无 page 空态
  expandModeByTab: Record<string, "smart" | "all-open" | "all-closed">;

  setPages(pages: WhopPage[]): void;                      // dashboard 进入时灌入 / WS 同步
  setActiveTab(id: string | "orphan"): void;              // 写 localStorage
  setExpandMode(tabId: string, mode: ExpandMode): void;
  applyPageChanged(evt: WsEvent): void;                   // dispatch from ws.ts
}
```

`activeTabId` 持久化：写 `localStorage["DASHBOARD_LAST_TAB"]`。pages load 后 select；找不到 fallback 到第一个 page 的 id。

### 7.2 `stores/tasks.ts` 新增 selector

```typescript
function tasksByUrl(state: TaskState, url: string | null): TaskSummary[] {
  if (url === null) {
    // 孤儿模式：返回 url=null 或 url 不属于任何 active page 的 task
    const activeUrls = useTabsStore.getState().pages.map(p => p.url);
    return state.tasks.filter(t => t.url == null || !activeUrls.includes(t.url));
  }
  return state.tasks.filter(t => t.url === url);
}
```

### 7.3 切 tab 视觉

切 tab 时直接硬切（不加 fade）。理由：简单、稳；用户已经习惯 tab 即时切换。

---

## 8. 测试覆盖

| 层 | 新增测试 |
|----|---------|
| Backend `tests/whop/test_registry.py` | settings 持久化、PATCH、defaults、source-specific validation、`get_settings_for_url` lookup |
| Backend `tests/whop/test_listener_dedupe.py` | dedupe=on 时 `_seen` 从 DB 灌入；off 时旧行为；切换不立即重启 |
| Backend `tests/broker/test_trader_deviation.py` | 偏差之内 → MARKET、之外 → LIMIT@signal_price；ticker 不在白名单 → SKIPPED；qty 取整 |
| Backend `tests/api/test_whop_pages.py` | PATCH、defaults GET、url 字段传播、option page 拒收 tickers |
| Backend `tests/integration/test_acceptance.py` | 加 e2e：add page → settings PATCH → 消息进来 → trader 按新 deviation 决策 order_type |
| Frontend `tests/Dashboard/PageTabs.test.tsx` | tab 切换、孤儿 tab 出现条件、空态 |
| Frontend `tests/Dashboard/PageSettingsModal.test.tsx` | toUpperCase、validation、source 差异、dedupe hint 显示 |
| Frontend `tests/Dashboard/PageActionBar.test.tsx` | 全展开/收缩切换、重启 confirm |

---

## 9. 风险 + 缓解

| 风险 | 缓解 |
|------|------|
| `watched_stocks.json` 退役后 stock parser fallback 命中率立刻掉 | 强制 stock page 启动时如果 settings.tickers 空，listener 启动正常但前端 PageInfoBar 给红字提示「未配置 ticker，无法触发下单」；用户必须主动迁移 |
| `task.url=None`（migration 前老数据） | 孤儿 tab + trader fallback 到全局 `Settings.*_price_deviation_tolerance` |
| dedupe=on 时 listener 启动慢（要拉 DB） | `idx_messages_url` 索引；预期单页 task < 5000，查询 < 100ms |
| `whop.page_changed` WS 占 ring buffer | 现有 buffer 500 条，page 变动稀疏（每天个位数），无忧 |
| settings PATCH 并发 | `WhopRegistry._lock` 串行化 |
| 切 tab 时 task 流"突变" | 硬切，不加动画 |
| 移除 page 时 listener 正在拉消息 | 现有 `remove_page` 已经 `await listener.stop()` |
| trader 白名单 gate 误伤已建仓的旧 ticker | `task.instruction_ready` 时白名单不含 ticker → SKIPPED 是预期行为；用户在 settings 加回 ticker 即可 |
| `Instruction` domain 没有"仓位比例"字段（`position_fraction`） | 实施 step 6 之前先确认现有字段；缺失则在 instruction 解析（step 2）阶段补，否则 trader 数量逻辑无法实现 |
| `messages` 表 `url` 是 NULLABLE，新写入也可能是 None（listener 漏注入）| `WhopListener._scan_once` 强制注入 `self._url`；test_listener_dedupe 加断言 |

---

## 10. 实施顺序建议

供后续 plan 文档参考；每步独立可测试：

1. **DB schema**：`messages.url` 列 + index + alembic migration
2. **Domain / Payload 改造**：`Message.url`、`MessagePayload`、`Task.url` API serializer
3. **WhopListener 重构**：`dedupe_processed_messages` 参数、`load_seen_ids_for_url`、`_scan_once` 注入 url
4. **WhopRegistry 设置存储**：`PageSettings` dataclass、`update_settings`、`get_settings_for_url`、JSON schema 升级
5. **`watched_stocks.json` 退役**：parser/broker 引用全部切到 page settings；删 `utils/watched_stocks.py` 和 `config/watched_stocks.json`
6. **Trader 改造**：白名单 gate、SKIPPED 状态、偏差→order_type 切换
7. **REST 端点**：PATCH settings、GET defaults、修改 GET pages 出参
8. **WS 事件**：`whop.page_changed` 发布逻辑
9. **OpenAPI 同步**：后端跑 `dump_openapi`，前端 `npm run gen:types`
10. **前端 stores**：`pageTabs.ts`、`tasks.ts` selector
11. **前端 Dashboard 组件拆分**：PageTabs / InfoBar / ActionBar / TaskStream / EmptyState
12. **前端 PageSettingsModal**：DedupeToggle、DeviationInput、TickerListEditor
13. **测试**：backend + frontend + acceptance e2e

---

## 11. 文档更新

实施完成后需更新：

- `README.md`：架构图加 PageTabs，REST 表加 PATCH/defaults，配置表移除 `STOCK_PRICE_DEVIATION_TOLERANCE` 等说明，Whop UI 工作流补 settings modal 截图
- `CHANGELOG.md`：标记 breaking changes（watched_stocks.json 退役、price_deviation 行为变更、SKIPPED 状态新增）
