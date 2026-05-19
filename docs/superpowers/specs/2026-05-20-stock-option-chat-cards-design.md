# 正股 / 期权交易信号卡嵌入聊天列表 · 设计

## 背景

目前 `WhopPage.source ∈ {stock, option, chat}` 三类各占独立 tab：

- `stock` / `option` 走 `ParserService → Trader` 链路，产物是 `tasks` 流，渲染成 `TaskStream` 里的 `Card`（compact / expanded）；
- `chat` 不解析，落 `chat_messages` 表，渲染 `ChatBoardPanel`（按 sender 过滤 + 卡片分组 + 周分页）。

业务诉求：把正股 / 期权监听 "嵌入" 到 chat 页的消息流里 —— 一个 chat 频道既能看到群友的对话，又能看到由群友某句话触发的交易信号卡片，sender 与人发消息并列在 `ChatSenderBar` 里。

## 设计原则

- **零侵入复用现有管线**：子 stock/option 监听仍然是 `WhopPage` + `WhopListener` + `ParserService` + `Trader` 标准链路；只在 chat 父 -> 子的归属关系上加一列。
- **范围最小**：不引入"通用 entity attach"机制；不动 ticker 白名单 / 期权 qty 配置的语义，仅迁移它们的编辑入口。
- **现有独立 stock/option 页保留现状**：本期只面向"从 chat 页内新建子监听"这条路径，不做老页面的迁移 UI。
- **视觉与 ChatCard 同构**：信号卡走 `chat-card` 同构外壳 + 内部一个 `signal-bubble`，与人发消息天然在同一个时间序里共存。

## 视觉参考

落库前已用 web-design-engineer 出了两份高保真稿，仅作设计 / 验收参考，不参与构建：

- `.design/signal-cards-in-chat.html` — chat 板嵌入信号卡的完整效果（含 filter / highlight 双模式、各状态降级、单 accordion 展开）。
- `.design/chat-settings-monitors.html` — chat 页 `PageSettingsModal` 加入"挂载监听"区块的形态。

## 数据模型

### 后端持久层

Whop 页面元数据是 JSON 文件 `data/whop_pages.json`（不是 DB 表）；`WhopRegistry` 在内存维持 `WhopPageEntry` dataclass + 文件读写。`tasks / chat_messages` 等才是 DB 表，**不动**。

新加字段：

```python
# backend/app/whop/registry.py
@dataclass
class WhopPageEntry:
    id: str
    url: str
    source: str           # "stock" | "option" | "chat"
    name: str
    added_at: datetime
    settings: PageSettings
    parent_chat_id: str | None = None       # NEW · default None
```

`to_dict` / `from_dict` 都加 `parent_chat_id`；`from_dict` 对 legacy 条目（无该 key）回落到 None，无需 migration 脚本。

- `parent_chat_id is None` → 独立顶层页（=现状）。
- `parent_chat_id is not None` → 子监听，挂在指定 chat 父页下。
- 删父 chat 时，registry 在内存里把所有 children `parent_chat_id = None` 写回 JSON，子页自动"降级"为独立顶层页，listener 不停。

不允许 sub-of-sub：子页 source 必须 ∈ {stock, option}，父页 source 必须 = chat。在 `WhopRegistry.add_page` 显式校验：

```python
if create.parent_chat_id is not None:
    parent = registry.get(create.parent_chat_id)
    if parent is None:                    raise HTTPException(404)
    if parent.source != "chat":           raise HTTPException(400, "parent must be chat")
    if parent.parent_chat_id is not None: raise HTTPException(400, "no nested sub-monitors")
    if create.source == "chat":           raise HTTPException(400, "chat cannot be sub")
```

### 与 Listener / Parser / Trader 的关系

后端**完全不感知**父子关系。子页跟独立 stock/option 页对 listener / parser / trader / event bus / DB / WS 全栈等价：

- `WhopListener` 按 `page.url` 起 Playwright，scrape → 发 `message.received`。
- `ParserService` 按 `page.source` 路由 → stock_parser / option_parser → 发 `task.instruction_ready`。
- `Trader` 订阅 instruction → 提交订单 → push 事件。
- 所有 task 落 `tasks` 表，WS 广播 `task.*`。

父子关系仅在 **REST query** 和 **前端渲染** 时使用。

### REST 接口变更

**新增 / 改动**：

| 端点 | 改动 |
| --- | --- |
| `GET /api/whop/pages` | 默认仅返回 `parent_chat_id IS NULL` 的页（顶层 tab 用） |
| `GET /api/whop/pages?parent_chat_id=<id>` | 仅返回该父页的子监听列表 |
| `POST /api/whop/pages` | body 接受可选 `parent_chat_id`；后端按上面规则校验 |
| `GET /api/tasks?urls=<u1>&urls=<u2>&week_start=&week_end=` | 多 url + 周时间窗过滤（multi-value query param），chat board 用 |
| `POST /api/whop/pages/<id>/start` · `/stop` · `/restart` | 沿用现有三端点；设置弹窗按状态切换 ⏸停 / ▶启 / ↻重启 |

`PATCH /api/whop/pages/<id>/settings` 沿用现接口；子页改 ticker_whitelist / option_buy_quantity 都走它。

### 前端类型

```ts
// frontend/src/api/domain-types.ts
export type WhopPage = ... & {
  parent_chat_id?: string | null;
};
```

## 卡片视觉 · `SignalCard` 组件

### 折叠态布局

```
┌─ ● avatar  Sender name · 09:32:15 · [正股|期权]
│  ┃ "buying tsla calls dip 200 — full position"        ← MSG  灰斜 1 行 clip
│  ┃ [BUY] TSLL.US  $200.00  × 100                      ← SIG  解析簇
│  ┃ ● 已成交 · 100/100 @ $199.87                 [▾]   ← ORD  状态点 + cum
└────────────────────────────────────────────────────────
   ┃ = 左 2px 条带：stock = #5fbf8b · option = #8b6fcf · degraded = --fg-3
```

三层永远存在；任一层数据缺失 → 按状态降级（见下）。点卡片任意位置切换展开 / 收起；同一 chat board 内单 accordion。

### 展开态

折叠态保留在顶部作概览，下方追加 dashed 分隔再露出：

- `MSG block`：完整 raw 文本（自动换行）+ meta（domID · posted_at 完整北京时间 · url ↗）
- `SIG block`：parsed inline（ticker / price / qty / strike / expiry / stop_loss / context_source）+ parse 耗时 ms
- `ORD block`：提交行（order_id · LO/MO · 价 × 量 · submit 耗时）+ 推送链（PushChain compact，可二次展开成 PushDetail）+ cum/avg 汇总 + 总耗时 + StatusPill

> 推送链的二级展开（`PushChain ↔ PushDetail` 当前对照）保留，"展开详情 ▾" 跟卡片自身展开互不干扰。

### Stock vs Option 字段差异（折叠态）

| 字段 | Stock | Option |
| --- | --- | --- |
| 左条带 | `--source-stock` 绿 | `--source-option` 紫 |
| chip 文字 | 正股 | 期权 |
| ticker | `TSLL.US` | `NVDA.US` |
| 合约描述 | — | `880C 12/15`（strike + expiry MMDD） |
| qty | `× 100` | `× 5 张` |
| 期权特例 ORD | — | 数量规则未配 → "未下单 · 数量规则未配置"，状态点灰 |

### 状态降级矩阵（折叠态）

| Task status | 折叠态变化 |
| --- | --- |
| `PARSE_ERROR` | SIG 行替换为红字"未解析 · 正则未匹配"；ORD 行隐藏；左条带变 `--fg-3` |
| `SKIPPED` | ORD 行显示 reject_reason；状态点橙 |
| `INSTRUCTION_READY` + auto_trade off | SIG 行尾追加 `[✓ 确认] [✗ 跳过]` 小按钮；ORD 行 "等待人工确认" |
| `SUBMITTING / PENDING / PARTIAL` | ORD 状态点黄；"等待 / 部分成交 N/M @ avg" |
| `SUBMIT_FAILED` | ORD 行 "提交失败 · <error>"；状态点红 |
| `CANCELLED / REJECTED` | ORD 行最终态文字；状态点红 |
| `FILLED` | 默认形态：cum / avg 全展示 |

### 复用 / 新增

复用：`StatusPill` · `avatarPalette.paletteColorFor` · `cardHelpers.formatTitle / fmtTime / displaySubmitPriceDollars` · `ConfirmActions` · `PushChain` / `PushDetail` · `TypeBadge`。

新增：

- `frontend/src/components/Chat/SignalCard.tsx`（folded + expanded 单组件 + state 降级映射）
- `frontend/src/components/Chat/SignalCard.css`
- `frontend/src/components/Chat/signalCardHelpers.ts`（status → layer 内容 + 颜色）

## ChatBoardPanel · 时间序合流

`ChatBoardPanel` 在 `activePage.source === "chat"` 时多做三件事：

```
mount / activePage change
  │
  ├─ 1. GET /api/whop/pages?parent_chat_id=<chatId>
  │     → useChildPagesStore.setByParent(chatId, children)
  │
  ├─ 2. useChatStore.fetch(chatId, week)          (现有)
  │
  └─ 3. GET /api/tasks?urls=<childUrls>&week_start=&week_end=&limit=500
        → useTasksStore.upsertMany(tasks)         (复用全局 store)
```

合流为统一 timeline：

```ts
type TimelineEntry =
  | { kind: "msg";    msg: ChatMessageOut }
  | { kind: "signal"; task: TaskSummary };

const entries = [
  ...messages.map(asMsg),
  ...childTasks.map(asSignal),
].sort((a, b) => posted_at(a).localeCompare(posted_at(b)));
```

### Filter 模式 · 按 sender 聚合

人 sender：复用现有 `groupIntoCards` —— 每个 watched sender 一张大卡，包含其本周所有消息（context 桥接逻辑不变）。

监听 sender：**所有 stock 子页的信号合并到一张"正股信号"聚合卡**；**所有 option 子页的信号合并到一张"期权信号"聚合卡**。卡片头部如下：

```
[∑] 正股信号  [stock]  · TSLL 监听 + AAPL 监听     4 signals · 09:32–09:42
[∑] 期权信号  [option] · NVDA 期权监听              2 signals · 09:35–09:43
```

每个 `signal-bubble` 内部加一行小 `signal-source-tag` 注明真实来源（"TSLL 监听 · 09:32:15"），方便单卡多源时识别。

**过滤粒度**：每个 `signal-bubble` 的可见性由其源监听 chip 单独控制；`正股 / 期权` 聚合卡只是容器 —— 当且仅当内部至少 1 个 bubble 可见时它才出现。这样 TSLL 监听 + AAPL 监听 都挂在同一 chat 下时，关掉 AAPL 不影响 TSLL 卡里的内容，只会让 AAPL 的 bubble 从 `正股` 卡里消失。

### Highlight 模式 · 单条扁平流

不分卡片外壳。整页一条 `stream-view`：

- 按时间序合流后，按 "连续同 sender 合并 head" 分组（与 `GroupChatView` 同构）；
- watched sender 的 group → 右贴边 + brand 蓝 tint；
- 非 watched → 左对齐 + 淡化（opacity 0.72；hover 恢复）；
- 信号 bubble 作为 group body 里的一项嵌入，外形不变（仍是带左条带的 `signal-bubble`）；
- 子页 sender 的 chip 同样能 watched，效果是该子页对应的所有信号 bubble 高亮。

两种模式共用同一份 `signal-bubble` 实现 + 同一份点击展开 / 收起逻辑（`single accordion per board`）。

### Sender chips

`ChatSenderBar` 的 chip 集合来源：

```
authors = uniq([
  ...chatStore.caches[`${chatId}|${week}`].authors,   // 人
  ...childPagesStore.byParent(chatId).map(p => p.name) // 监听
])
```

子页 chip 在常规人 chip 基础上加一个前缀 6px dot（stock = 绿 / option = 紫），区分"监听 sender" vs 人 sender，但走完全相同的 `watched_senders` 过滤 / highlight 逻辑。`watched_senders` 仍持久化到父 chat 的 `WhopPageSettings`（既有字段，无需新增）。

### Stores

```
useChildPagesStore        // 新建
  byParent: Record<chatId, WhopPage[]>
  setByParent(chatId, pages)
  upsert(page)              // WS whop.page_changed.parent_chat_id != null 时调用
  remove(pageId)

useTasksStore               // 复用，无改动
useChatStore                // 复用，无改动
usePageTabsStore            // applyPageChanged 加分支：parent_chat_id != null → 转发到 useChildPagesStore
```

WS 路由：

| Event | 处理 |
| --- | --- |
| `task.*` | `useTasksStore.applyWsEvent`（不变） |
| `chat.message_stored` | `useChatStore.fetch` 重拉受影响 cache（不变） |
| `whop.page_changed` | payload.page.parent_chat_id 为空 → `usePageTabsStore.applyPageChanged`；否则 → `useChildPagesStore.upsert` |

### Sticky-bottom scroll

`wasAtBottomRef` 触发条件扩展为 `messages.length + visibleSignalTasksCount`。view-shape 转换也包含 `childPages` 列表的增删（sender chip 集合变化会改重排）。

### 边界 / 容错

- 父被删 → `WhopRegistry.remove_page` 在持久化前把所有 children `parent_chat_id = None` 重写到 JSON，自动归位为独立顶层页（每个子页会触发一次 `whop.page_changed`，前端把它从 `childPagesStore` 移到 `pageTabsStore`）。
- 子页 listener 报错 → tasks 不来 → chat board 不挂；只在设置弹窗状态点变红 + tooltip 显示 `last_error`。
- 父子 url 相同（理论不可能因为 source 不同）→ 后端 add_page 已有 url 唯一约束，会 409。
- 历史周回看：每切换到一个未拉过的周，触发一次 `listTasks` 带 `urls` + `week_start / end`。

## 设置弹窗 · "挂载监听" 区块

仅 `activePage.source === "chat"` 时显示。

结构（自上而下）：

1. 通用配置（现有 5 项）—— 不动。
2. **挂载监听** —— 新增区块。
3. 危险操作（清空历史）—— 不动。

### 子监听列表

每行是一个 `mon-row`：

```
[● src-dot] [type-chip] [双击编辑名称] [url 灰色 truncate]
                                              [状态点 + 文字] [⏸/▶] [↻] [✕] [▾]
```

行折叠态只显示这一行；点 head 任意非按钮位置 → 行内展开，露出 `mon-body`：

- 子页 source = `stock` → `TickerWhitelistEditor`（从现有 `PageWhitelistBar` 抽出复用），编辑 `settings.tickers` 字典（chip 列表 + "+ 添加"）。
- 子页 source = `option` → `OptionQuantityEditor`（从现 `PageSettingsModal` 的期权块抽出），两组 toggle + input。
- 若状态为 error → `mon-body` 顶部加红 banner 显示 `last_error`。

按钮语义：

| 按钮 | 端点 |
| --- | --- |
| `⏸ 停 / ▶ 启` | `POST /api/whop/pages/<id>/stop` 或 `/start` |
| `↻ 重启` | `POST /api/whop/pages/<id>/restart`（沿用） |
| `✕ 移除` | `DELETE /api/whop/pages/<id>`（沿用），confirm 二次确认 |
| 双击名称 | inline edit → `PATCH /api/whop/pages/<id>` |

### "添加新监听"子表单

跟在子页列表下方：

- url 输入框
- 类型 select：默认 `stock`；`chat` option 灰掉并注释"子监听不可"
- 名称输入框
- `+ 添加监听` primary 按钮

提交：`POST /api/whop/pages`，body 自动带 `parent_chat_id = currentPage.id`。成功后行立即出现，listener 立即起。

### 抽组件

- `frontend/src/components/Chat/TickerWhitelistEditor.tsx` —— 从 `Dashboard/PageWhitelistBar.tsx` 抽接受 (`tickers`, `onChange`) 的纯 UI。
- `frontend/src/components/Chat/OptionQuantityEditor.tsx` —— 从 `Dashboard/PageSettingsModal.tsx` 的期权块抽。
- `frontend/src/components/Chat/AttachedMonitorsSection.tsx` —— 列表 + 行折叠 / 行内编辑 + 添加表单。
- `Dashboard/PageSettingsModal.tsx` —— 在 `source === "chat"` 分支插入 `<AttachedMonitorsSection page={...} />`。独立 stock / option 顶层页的 modal 走原代码路径，**不动**（它们自己仍直接显示 ticker 白名单 / 期权数量配置；只是把内部 UI 抽组件后，三处共用同一份编辑器实现）。

## 范围 / YAGNI

**显式不做**：

- 现有独立 stock / option 页向 chat 挂载的迁移 UI（按既定决策：仅面向未来）。
- 一对多挂载（一个 stock 子页同时喂多个 chat） —— 当前不需要；需要时再加 junction 表。
- 子页对父 chat 的通用配置（dedupe / launch_headless / parser_version）override 编辑器 —— 暂全部继承 / 沿用子页自身 settings 默认。
- 三层（MSG / SIG / ORD）独立展开 —— 仅整卡单展开。
- chatExport 输出信号卡 —— 现有 export 只装 chat msgs，不动。
- 信号卡的实时报价 / Day P&L 叠加 —— 与 PositionCard 解耦。
- 设置弹窗里 drag&drop 排序子页、"分离为独立 tab"按钮 —— 不开放（要分离即删除重建独立页）。

## 测试

### 后端 (pytest)

- `WhopPageEntry.from_dict / to_dict` 对 legacy JSON（无 parent_chat_id 字段）正确回落到 None；带字段的新 JSON 正确解析。
- `add_page` 拒绝：parent_chat_id 指向不存在 / 非 chat / 自身；子页 source = chat；嵌套（在子页上再挂子页）。
- `remove_page(chat)` 后 children `parent_chat_id = None` 写回磁盘；原 listener 不停；children 出现在顶层 `list_pages()` 默认输出里；每个 child 触发 `whop.page_changed`。
- `list_pages(parent_chat_id=X)` 与 `list_pages()` 互不污染。
- `list_tasks(urls=[u1, u2], week_start, week_end)` 多 url 过滤 + 时间窗（注意：`tasks.message_url` 列需有索引，若没有则 plan 阶段加一条 alembic migration）。

### 前端 (vitest)

- `SignalCard`：8 种 status × {stock, option} × {folded, expanded} 关键组合的快照；状态降级矩阵单元测试。
- `signalCardHelpers.statusToLayers(...)` 单元测试。
- `ChatBoardPanel`：
  - timeline 合流：3 chat + 1 signal + 2 chat 的输入 → 渲染顺序与卡数（filter 模式聚合 / highlight 模式扁平）正确。
  - filter / highlight 模式切换：sender chip 子集变化时聚合卡可见性正确。
  - 子页删除后 ChatBoardPanel 不再显示其对应信号（自然从 `childUrls` 中消失）。
- `ChatSenderBar`：子页 name 作为 chip 出现（带 prefix dot）；选中后流里只剩对应 signal + 同 author chat 卡。
- `PageSettingsModal`：
  - source = chat → 渲染"挂载监听"区块；source = stock/option → 不渲染。
  - 添加子监听后行立即出现，调用 url 正确。
  - 行内 ticker / option 编辑提交走 `PATCH /pages/<id>/settings`。
- WS：`whop.page_changed` payload 带 `parent_chat_id` 时只更新 `childPagesStore`，不污染 `pageTabsStore`。

### 集成（acceptance, spec §11 风格）

- e2e：建一个 chat 父页 → 设置弹窗里添加一个 stock 子监听（url 指向 mock whop）→ 模拟 whop 推一条 stock 消息 → `ChatBoardPanel` 在 filter 模式下出现一张正股信号聚合卡 + 一张人卡（如果 watched）→ 切到 highlight 模式确认信号 bubble 嵌入到时间流 → 点 sender chip 过滤正常 → 点信号 bubble 展开看推送链。

## 实施顺序建议（写入 plan 时细化）

1. 后端 `WhopPageEntry.parent_chat_id` + `to_dict / from_dict` + `WhopRegistry.add_page / remove_page` 校验与级联 + REST query 过滤参数 → 现有测试不破。
2. 后端 task list 多 url + 时间窗过滤端点；如 `tasks.message_url` 无索引则补一条 alembic migration。
3. 前端 `useChildPagesStore` + WS 分支 + WhopPage 类型扩。
4. `SignalCard.tsx` + `signalCardHelpers.ts` + CSS（含 8 种状态）。
5. `ChatBoardPanel` 合流 + filter 聚合 + highlight 扁平流双模式。
6. `TickerWhitelistEditor` / `OptionQuantityEditor` 抽组件 + `AttachedMonitorsSection` + `PageSettingsModal` 接入。
7. acceptance e2e。

每步小 commit、跑 mypy strict + ruff + vitest 后再下一步。
