# 股票详情交易面板 + 告警子系统 — 设计

**日期**：2026-05-24
**作者**：txink + Claude (brainstorming)
**Mockup**：`.design/trading-panel-and-alerts.html`（含 Tweaks 切换 5 视图）

---

## 1. 背景与目标

当前股票详情页（`DetailPane`）布局为：摘要卡 → 图表卡 → `TradeList`。本设计在底部 `TradeList` 占据的位置引入**三 tab 容器**，新增两块能力：

1. **交易面板**：手动提交 / 修改 / 撤销订单，展示该 ticker 当日所有订单状态（含信号自动单 + 长桥 app 端下单）
2. **告警子系统**：per-ticker 列表管理 + 后端常驻评估 + 触发后顶栏铃铛红点 + 右上角 toast

「交易记录」（现有 `TradeList`）成为三 tab 的第一个 tab。

## 2. 用户故事

- **手动下单**：用户在看 AAPL 详情图表时，决定按当前盘口加仓 200 股 LIMIT $199.50，从下方"交易面板" tab 快速下单行一行操作完成
- **改价**：用户提交后行情上涨，希望抬价至 $199.80 保住队列优先级 —— 点活跃订单行的`[改]`弹小 popover，改价后调 LongPort `replace_order`
- **撤单**：用户决定不再追价，点`[撤]`二次确认撤单
- **跨来源订单可见**：用户在长桥 app 上下了一笔单，在 Signal Station 的"活跃订单"列表里**仍能看到并管理**这笔单
- **告警**：用户在 AAPL 详情设了"价格 ≥ $200 one-shot"告警；浏览器关掉后晚上股价穿过 $200，第二天打开看到铃铛 3 个未读 + 历史记录里的触发
- **触发实时感**：用户白天看 NVDA 详情时，AAPL 触发告警，右上角弹 toast 5 秒后自动消失；点 toast 跳到 AAPL 详情的告警 tab

## 3. 设计决定汇总（brainstorm 已对齐）

| # | 决定 |
|---|---|
| 1 | 底部三 tab：交易记录 / 交易面板 / 告警 |
| 2 | 左右滑切换 + 底部 footer 中间悬浮指示器；左下 ⚙ + tab 名 |
| 3 | 下单：LIMIT + MARKET；改单走 LongPort `replace_order` 保留队列位置 |
| 4 | 数量：手输 + 三档预设（复用 per-page 白名单的 常规/半/三分之一仓） |
| 5 | 活跃订单列表：该 ticker 当天全部订单（不论来源） |
| 6 | 告警条件：价格阈值 / 涨跌幅 / 分钟成交量异动 |
| 7 | 触发模式：用户创建时选 one-shot 或 recurring |
| 8 | 触发表现：顶栏红点徽章 + toast 弹窗 |
| 9 | 告警作用域：per-ticker（详情页 tab 内管理） |
| 10 | 存储：SQLite |
| 11 | one-shot 触发 → 自动禁用（保留历史，不删除） |
| 12 | 评估：后端常驻，订阅 LongPort 行情推送，WS 推 `alert.triggered` |
| 13 | 实现路径：A — 最小落地（alerts 独立 package，orders 复用 broker） |
| 14 | TradingPanel 主体是活跃订单列表；下面是快速下单行；复杂订单走 modal |

## 4. 架构

```
后端进程：
  ┌──────────────────────────────────────────────────────────────┐
  │ LongPortClient (existing)                                    │
  │   ├─ submit_stock_order / submit_option_order  (existing)    │
  │   ├─ cancel_order                              (existing)    │
  │   ├─ replace_order                             (NEW)         │
  │   ├─ today_orders(ticker)                      (NEW)         │
  │   └─ set_on_quote → push events                (existing)    │
  └──────────────────────────────────────────────────────────────┘
                       │                          │
                       ▼ orders                   ▼ quotes
            ┌──────────────────────┐    ┌──────────────────────┐
            │ orders_service (NEW) │    │ alerts/engine.py     │
            │  - submit/replace/    │    │  - subscribe symbols │
            │    cancel via broker  │    │  - evaluate on tick  │
            │  - persist as tasks   │    │  - cooldown / oneshot│
            │    (source=manual)    │    │  - emit alert.fired  │
            └──────────────────────┘    └──────────────────────┘
                       │                          │
                       ▼ EventBus events          ▼
                  ┌────────────────────────────────────┐
                  │ WebSocketHub (existing)            │
                  │   + order.changed       (NEW)      │
                  │   + alert.triggered     (NEW)      │
                  │   + alert.changed       (NEW)      │
                  └────────────────────────────────────┘

前端：
  DetailPane
    └── DetailTabSwipe (NEW)
        ├── tab[0] TradeList (existing, unchanged)
        ├── tab[1] TradingPanel (NEW)
        │     ├── ActiveOrdersTable
        │     ├── QuickOrderRow
        │     ├── FullOrderModal (advanced)
        │     └── ReplaceOrderPopover
        └── tab[2] AlertsPanel (NEW)
              ├── AlertList
              └── AlertModal (create/edit)
        + DetailTabFooter (settings ⚙ + 3-dot indicator)

  App.tsx
    └── AlertToastStack (NEW, position: fixed)
  TopBar
    └── AlertBell (NEW, badge + popover)

  Stores:
    + stores/orders.ts        (NEW; today orders by ticker)
    + stores/alerts.ts        (NEW; alerts by ticker)
    + stores/alertNotifications.ts (NEW; unread count + toast queue + history)
```

## 5. 数据模型

### 5.1 复用 `tasks` 表 — 手动订单标记

不新建 `manual_orders` 表。在 `tasks.source` 字段标 `"manual"`（现状是 `"whop"` / `null`）；可与自动信号订单共用列表查询。

新增列（migration）：
- `tasks.order_kind`: `"signal"` | `"manual"` —— 区分来源；前端展示用
- `tasks.last_replaced_at`: datetime —— 改单时间，方便排序与审计

### 5.2 新表 `alerts`

```python
class Alert(Base):
    __tablename__ = "alerts"
    id: int                                # auto-increment PK
    ticker: str
    symbol: str                            # 行情订阅 key
    condition_type: str                    # "price" | "pct_change" | "volume"
    operator: str                          # ">=" | "<="
    threshold: float
    pct_change_baseline: str | None        # "today_open" | "prev_close" — pct_change only
    volume_window: str | None              # "1min" | "5min" — volume only
    repeat_mode: str                       # "one_shot" | "recurring"
    cooldown_seconds: int                  # default 300; recurring 节流
    enabled: bool                          # one-shot 触发后置 false
    note: str | None
    created_at: datetime
    last_triggered_at: datetime | None
    trigger_count: int                     # 累计触发次数
```

### 5.3 新表 `alert_events`

```python
class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: int
    alert_id: int                          # FK → alerts.id
    triggered_at: datetime
    ticker: str
    symbol: str
    snapshot_price: float
    snapshot_pct: float | None
    snapshot_volume: float | None
    message: str                           # 渲染好的中文 "AAPL 触发 价格 ≥ $200.00"
```

### 5.4 Alembic migration

单文件 migration：建 `alerts` + `alert_events` + 给 `tasks` 加两列。`make db-reset` 路径正常。

## 6. 后端模块

### 6.1 `broker/longport_client.py` — `replace_order`（NEW）

```python
def replace_order(
    self,
    order_id: str,
    *,
    quantity: int | None = None,
    price: float | None = None,
) -> None:
    """
    Replace an order via LongPort SDK's trade_ctx.replace_order, preserving
    queue priority. At least one of quantity/price must be provided; the
    other is read from current order state and re-submitted unchanged.

    Raises:
      OrderNotFound: order_id 不存在或非本账户
      OrderImmutable: 订单已成 / 已撤；调用方应返回 409
    """
```

- 实现：调用 `trade_ctx.replace_order(order_id, quantity, price)`（LongPort Python SDK 原生支持）
- `dry_run = True` 时 log 后直接返回
- `NoopBrokerClient.replace_order` 同样 log + 返回

### 6.2 `broker/longport_client.py` — `today_orders`（NEW）

```python
def today_orders(self, *, ticker: str | None = None) -> list[dict[str, Any]]:
    """
    Pull today's orders (all states: pending / partial / filled / cancelled
    / rejected) from LongPort. Optional ticker filter applied client-side.

    Returns list of dicts compatible with the OrderOut schema below.
    """
```

- 实现：`trade_ctx.today_orders()` SDK 原生；映射 LongPort `Order` 到统一 dict
- `NoopBrokerClient.today_orders` 返回 `[]`

### 6.3 `app/orders/service.py`（NEW）

```python
class OrdersService:
    """Wraps broker + persistence + EventBus for manual orders.

    submit / replace / cancel each:
      1. validate input
      2. call broker
      3. upsert Task row with source=manual
      4. emit task.* event (reusing existing topic so WS, push_listener,
         and storage_listeners pick it up uniformly)
    """

    async def submit(self, req: SubmitOrderRequest) -> Task: ...
    async def replace(self, order_id: str, req: ReplaceOrderRequest) -> None: ...
    async def cancel(self, order_id: str) -> None: ...
    async def list_today(self, ticker: str) -> list[OrderOut]: ...
```

- 复用现有 `task.order_submitted` / `task.status_changed` / `task.push_event` 事件，前端 orders store 监听这些，加上新增的 `order.changed` 用于"手动单刚创建但未触达 LongPort"过渡态

### 6.4 `app/alerts/` 新 package

#### `alerts/repo.py`

`SQLAlchemy async` CRUD：
- `create(alert: AlertCreate) -> Alert`
- `update(alert_id, fields) -> Alert`
- `delete(alert_id) -> None`
- `list_by_ticker(ticker, include_disabled=True) -> list[Alert]`
- `list_enabled() -> list[Alert]` — 启动时给 engine 用
- `record_trigger(alert_id, snapshot) -> AlertEvent` —— 单事务：写 event + 更新 alert (last_triggered_at, trigger_count, enabled=false if one_shot)
- `list_events(ticker?, limit) -> list[AlertEvent]`

#### `alerts/engine.py`

```python
class AlertEngine:
    """
    Continuously evaluates enabled alerts against LongPort quote pushes.

    Lifecycle:
      - start() during lifespan startup if broker is authorized
      - on_alert_changed(action, alert) called by service.py after CRUD
      - quote push → _evaluate_quote(symbol, quote) for all enabled alerts on symbol

    Thread safety: SDK push runs on a background thread; engine uses an
    asyncio queue to marshal back into the event loop where DB/EventBus
    operations are async-safe.
    """

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def on_alert_changed(self, action: str, alert: Alert) -> None: ...
    def _evaluate_quote(self, symbol: str, quote: dict[str, Any]) -> None: ...
    async def _fire(self, alert: Alert, snapshot: dict[str, Any]) -> None: ...
```

**订阅集合管理**：维护 `dict[symbol, set[alert_id]]`。新增 alert → 若 symbol 不在集合，调 `broker.subscribe_quotes([symbol])`；删除最后一个使用该 symbol 的 alert → `unsubscribe_quotes([symbol])`。

**condition 评估**：
- `price`：`quote.last_done {op} threshold`
- `pct_change`：baseline 从 quote payload 拿（LongPort quote 包含 today_open / prev_close）
- `volume`：LongPort `PushQuote.volume` 是当日**累计**成交量；engine 每 symbol 维护 `deque[(ts, cumulative_volume)]`，窗口成交量 = 最新累计 − 窗口起点累计。`volume_window` 决定窗口长度（1min / 5min）

**cooldown 节流**：触发前检查 `alert.last_triggered_at + cooldown_seconds > now()`，是则跳过。

**broker 未授权时**：engine 仍启动但 `start()` 跳过 quote 订阅，等 `broker reload` 后调 `engine.restart()`。

#### `alerts/service.py`

CRUD 包装层：DB 写 + `engine.on_alert_changed()` 通知 + 返回 schema 对象。负责"创建告警时预检 symbol 有效性"（调 `broker.get_quote([symbol])` 验失败拒绝创建）。

### 6.5 REST endpoints — `app/api/http.py`（新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/orders` | 手动下单。body: `{symbol, side, qty, order_type, price?, time_in_force, note?}` |
| PATCH | `/api/orders/{order_id}` | 改单。body: `{price?, qty?}` —— 至少一个 |
| DELETE | `/api/orders/{order_id}` | 撤单 |
| GET | `/api/orders?ticker=&active_only=false` | 当日订单列表 |
| GET | `/api/alerts?ticker=` | 该 ticker 全部告警（含禁用） |
| POST | `/api/alerts` | 创建告警 |
| PATCH | `/api/alerts/{id}` | 修改（含 enable/disable） |
| DELETE | `/api/alerts/{id}` | 删除 |
| GET | `/api/alerts/events?ticker=&limit=` | 触发历史 |

错误码契约：
- 409: 订单已结束（不能改/撤）；告警状态冲突
- 422: 字段校验
- 502: broker SDK 异常透传
- 503: NoopBrokerClient 模式下尝试下单 / 创建告警

### 6.6 WebSocket 事件（新增 topic，进 `core/events.py`）

| topic | payload |
|-------|---------|
| `order.changed` | `{order: OrderOut, action: "created" \| "updated" \| "filled" \| "cancelled"}` |
| `alert.triggered` | `{event: AlertEventOut, alert: AlertOut}` |
| `alert.changed` | `{alert: AlertOut, action: "created" \| "updated" \| "deleted" \| "toggled"}` |

进 ring buffer，`?since=` 续传走现有机制。

## 7. 前端模块

### 7.1 `DetailTabSwipe.tsx`（NEW）

容器组件，包住三个 tab 内容，处理：
- 水平 `translateX(-tabIndex * 100%)` + `transition: 220ms cubic-bezier(.4,0,.2,1)`
- 触摸 `touchstart/move/end`（位移 > 50px 或速度 > 0.4px/ms 切换）
- 鼠标拖拽（阈值 8px；target 是 input/select/button/contenteditable 时不启动）
- 键盘 `←/→` 切换（容器 focus 时）
- 边界橡皮筋（最左/最右拉伸 40% 回弹）
- `DetailTabFooter` 子组件：左下 ⚙ + tab 名 + 中间 3 圆点指示器（当前 tab 圆点拉长为胶囊）

状态：tab index 存在 `useDetailViewStore`（已存在）；ticker 切换不重置，离开详情页清回 0。

### 7.2 `TradingPanel.tsx`（NEW）

布局：
1. **活跃订单表**：占主体高度，列 = 时间 / 方向 / 类型 / 价格 / 数量 / 已成 / 状态 / 来源 / 操作
   - 行的 `[改]` 打开 `ReplaceOrderPopover`（inline，价/量两字段）
   - 行的 `[撤]` 走二次确认（沿用 `Positions/ConfirmModal`）
   - 已结束的订单灰显，`[改][撤]` disabled
   - "仅活跃" 过滤（默认关）
2. **单行快速下单**（底部，sticky）：
   - `[BUY|SELL]` toggle
   - `[LIMIT|MKT]` toggle
   - 价 input（默认 last_done；MARKET 时 disabled）
   - 数 input + ▾ 弹三档预设（常规 / 半 / 1-3 仓，从该 ticker page settings 读）
   - `[提交]` 按钮（BUY 青绿 / SELL 红）
   - `[更多 ▾]` 打开 `FullOrderModal`
3. 数据源：mount 时 `GET /api/orders?ticker=`，订阅 `order.changed` WS 增量

### 7.3 `FullOrderModal.tsx`（NEW）

走复杂订单路径：方向 / 类型 / 价格 / 数量 / TIF（Day / GTC，v1 仅 Day）/ 二次确认开关 / 大额警告 / 备注。

### 7.4 `ReplaceOrderPopover.tsx`（NEW）

**行锚定** popover（不是 viewport modal），anchor 到点击的 `[改]` 按钮，向上展开。两字段：价 + 量（至少改一项才能提交）。提交即 `PATCH /api/orders/{id}`；成功后 popover 关闭，列表通过 WS `order.changed` 自动刷新该行。

### 7.5 `AlertsPanel.tsx`（NEW）

布局：
- 顶部 head：`告警 · {ticker} · 共 N 条 · 启用 K` + `[+ 添加告警]`
- 告警列表：每行 `✓ 勾选 | 条件文案 | 模式徽章 | 触发状态 | [编辑][×]`
- 数据源：mount 时 `GET /api/alerts?ticker=`，订阅 `alert.changed` 增量

### 7.6 `AlertModal.tsx`（NEW）

字段：
- condition-type 三 tab：价格阈值 / 涨跌幅 / 成交量
  - 价格阈值：`≥/≤` + 价格 input
  - 涨跌幅：`≥/≤` + 百分比 input + baseline 选 `今开/昨收`
  - 成交量：`≥/≤` + 阈值 input + 窗口选 `1min/5min`
- 触发模式：one-shot / recurring（recurring 时显示 cooldown 输入，默认 300s）
- 备注（可选）

### 7.7 `AlertBell.tsx`（NEW，挂 TopBar）

铃铛图标 + 红点徽章；点击展开历史 popover（最近 50 条）。点 popover 关闭 → unread 清零。

### 7.8 `AlertToastStack.tsx`（NEW，挂 App.tsx 顶层）

`position: fixed; top: 60px; right: 16px`；订阅 `alert.triggered` WS：
- one-shot 红边、recurring 黄边
- 默认 5 秒自动消失，hover 暂停计时
- 同时最多显示 3 条；超出合并显示"等 N 条触发，点开铃铛查看"
- 点 `[查看]` 跳转该 ticker 详情的告警 tab

### 7.9 stores

- `stores/orders.ts`：`Map<ticker, OrderOut[]>` + WS reducer（upsert by order_id）
- `stores/alerts.ts`：`Map<ticker, Alert[]>` + WS reducer
- `stores/alertNotifications.ts`：`{unreadCount, history[], activeToasts[]}` + WS push 入队

### 7.10 ⚙ 设置（每 tab 左下角）

- 交易记录 ⚙：复用现有 TradeList 的过滤/同步/清空菜单
- 交易面板 ⚙：仅活跃过滤 / 默认订单类型 / 默认 TIF / 二次确认开关；持久化到 localStorage
- 告警 ⚙：默认 repeat_mode / 默认 cooldown 秒数

## 8. 错误处理与边界

### 交易

| 场景 | 处理 |
|------|------|
| NoopBroker | 提交按钮 disabled + tooltip；活跃订单列表空 |
| broker submit/replace/cancel 异常 | 后端 502 + 透传 message；前端 toast 红色，表单不清空 |
| 字段校验失败 | 前端阻拦 + 按钮 disabled |
| 单笔金额超阈值 | 提交时强制弹二次确认（即使⚙关闭），文案标阈值 |
| 改/撤已结束订单 | 后端 409 + message；前端 toast + 行自动从列表移除 |
| 改单仅传一个字段 | 后端拼接：未传字段从订单当前状态读 |
| 闭市/盘前盘后下单 | 提交前 `market_state` 非 regular 弹警告确认 |
| 长桥 app 端撤的单 | push_listener → `order.changed` WS → 列表自动更新 |

### 告警

| 场景 | 处理 |
|------|------|
| 创建时 symbol 预检失败 | 后端 422 + message；告警**不**入库 |
| quote 流断 | LongPort SDK 自动重连；断流期间不触发任何告警 |
| cooldown 内多次满足 | 跳过，不发事件，不写 event |
| one_shot 触发时 DB 写失败 | 仍 emit EventBus（用户看到 toast），enabled 保持 true 等下次重试；记 error log |
| engine 启动失败（broker 未就绪） | lifespan 不阻塞；`/api/health` 暴露 engine 状态；`broker reload` 后自动重启 |
| Toast 堆叠超 3 条 | 取最新 3 条，多余合并"等 N 条触发，点开铃铛查看" |

### 滑动手势

| 场景 | 处理 |
|------|------|
| 在 input 上拖动 | 阈值 8px + target 检测，不启动拖拽 |
| 滑动中切换 ticker | tab index 保留；动画立即结束 |
| 滑动到边界 | 橡皮筋拉伸 40% 回弹 |

## 9. 测试

### 后端

| 模块 | 覆盖点 |
|------|--------|
| `broker.replace_order` | SDK mock 参数映射 / dry_run / 异常透传 |
| `broker.today_orders` | SDK mock 列表映射 / ticker 过滤 |
| `alerts/repo` | CRUD / list_enabled / record_trigger 事务 |
| `alerts/engine` 评估 | 三种 condition 命中/不命中 / cooldown / one_shot 自动 disable |
| `alerts/engine` 订阅 | 引用计数 / 新建删除增减订阅 |
| `alerts/service` | 启动流程 / broker 未授权降级不崩 |
| `api/orders` | POST/PATCH/DELETE/GET 路径；409 / 422 / 502 / 503 |
| `api/alerts` | CRUD 全套 / ticker 过滤 / toggle |
| `api/ws` | `order.changed` / `alert.triggered` / `alert.changed` 进 ring buffer + 续传 |
| acceptance §11+ | 2 个新 e2e：手动下单全链路；告警 quote → 触发可观察 |

### 前端

| 组件 | 覆盖点 |
|------|--------|
| `DetailTabSwipe` | 鼠标拖拽阈值 / 键盘 / 点击指示器 / input target 不触发 |
| `TradingPanel` 快速下单 | 状态切换 / 预设填值 / 提交调 API |
| `FullOrderModal` | 打开关闭 / TIF / 大额警告 |
| `ReplaceOrderPopover` | 价/量任一修改 / 已结束 disabled |
| `ActiveOrdersTable` | WS push 实时更新 / 状态徽章 / 仅活跃过滤 |
| `AlertsPanel` | 渲染 / toggle 启用 / 删除二次确认 |
| `AlertModal` | 三 condition 切换 / 表单校验 / 提交 |
| `AlertBell` + popover | 未读累加 / 点击清零 / 历史渲染 |
| `AlertToastStack` | 堆叠 ≤3 / 5 秒消失 / hover 暂停 / 合并显示 |
| `stores/orders` | WS reducer upsert |
| `stores/alerts` + notifications | CRUD reducer / WS 累加 |

### 手动验证

- LongPort `replace_order` 真单（paper 账户）—— 改价后队列保持
- 50+ 告警跨 20 symbol，订阅集合正确
- 多浏览器 tab 同时在线：toast 都出现，铃铛各自计数
- 跨页 toast：在 Whop 管理 tab 也能看到

### CI

- backend `make test` 全绿；mypy strict / ruff 不破
- frontend `npm test` 全绿；TS strict 不破

## 10. 范围之外（YAGNI）

- 跨 ticker 告警总览页（详情 tab 内管理已够；后续若量大再加）
- 浏览器 Notification API 推送
- 声音提醒
- TIF GTC（v1 仅 Day，UI 留位）
- 期权手动下单（v1 仅 stock —— `submit_option_order` 现有，但 UI 仍走 SignalCard）
- 历史告警分析 / 命中率统计
- 多账户同时下单
- "watchers" 通用抽象（路径 C，本设计放弃）

## 11. 实施顺序建议（plan 阶段细化）

1. Migration + ORM 模型（alerts / alert_events / tasks 加列）
2. broker `replace_order` + `today_orders`
3. `orders` 服务 + REST + `order.changed` WS
4. `alerts/` package（repo → engine → service → REST → WS）
5. 前端 stores（orders / alerts / alertNotifications）
6. `DetailTabSwipe` 容器 + 把现有 TradeList 接进 tab[0]
7. `TradingPanel`（活跃订单表 + 快速下单行）
8. `FullOrderModal` + `ReplaceOrderPopover`
9. `AlertsPanel` + `AlertModal`
10. `AlertBell` + `AlertToastStack`
11. 测试补全 + 验收 §11 新增 2 个 e2e

每步独立可测可 ship。
