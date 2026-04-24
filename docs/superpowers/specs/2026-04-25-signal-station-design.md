# Signal Station · 项目重构设计 (v2)

> **Status:** Draft — awaiting user review
> **Date:** 2026-04-25
> **Scope:** 重构现 Whop 信号抓取 + 长桥自动交易项目为独立模块化架构，前后端分离的 Web 单页应用。
> **Rewrite strategy:** 在 git worktree 上创建 `refactor-v2` 分支全量重写；老代码在 `main` 分支保留作为参考 / fallback。

---

## 1. 动机

现项目 `main.py::SignalScraper` 将浏览器管理、消息提取、指令解析、下单执行、状态打印全部编排在一处；`RecordManager` 被传进 `MessageContextResolver` 形成紧耦合；UI 是终端 `RichLogger` 的 `TradeLogFlow`，**单进程、单会话、无持久历史、无远程查看**。

目标：

1. 把六个职责拆成独立模块，依赖方向明确、可单元测试
2. 把 UI 升级为 Web 监控看板，可在本机浏览器打开，也可分享 URL 给少量朋友远程看
3. 把数据落盘到 SQLite，跨重启保留历史，支持按 symbol / 日期 / 状态查询
4. 把"交易流"可视化为 Card 组件，覆盖完整生命周期（原始消息 → 解析 → 下单 → broker 推送 → 终态）

---

## 2. 决策汇总

| 维度 | 决策 |
|------|------|
| 项目代号 | **Signal Station** · 目录 `signal-station` |
| 受众 | 个人主用 + 少量朋友通过 URL + token 共享（单机） |
| 部署 | 本地 Mac（单进程 Python，前端静态资源由 FastAPI 服务） |
| 后端语言 | Python ≥ 3.11 |
| 后端框架 | FastAPI |
| 前端框架 | React 18 + TypeScript 5 + Vite |
| 前端状态管理 | Zustand |
| 通信 | WebSocket（server → client 事件推送） + REST（client → server 查询/动作） |
| 数据库 | SQLite（单文件 `data/signals.db`）+ SQLAlchemy 2.x + Alembic 迁移 |
| 浏览器自动化 | Playwright（Python，与现有一致） |
| 券商 SDK | LongPort Python SDK（与现有一致） |
| UI 主题 | Dark only，桌面优先 |
| UI 风格锚定 | 监控看板（Datadog / Grafana 邻域，但非抄袭配色） |
| 设计系统来源 | 见第 9 节；mockup 定稿在 `.superpowers/brainstorm/.../v0-app-mockup-v5.html` |
| 重构方式 | git worktree · 新分支 `refactor-v2` · 全量重写 |
| 兼容性要求 | 无。老 `main.py` 保留在 `main` 分支继续可跑，直到 v2 稳定后再决定归档 |

---

## 3. 模块拓扑

### 3.1 依赖方向

```
               ┌─────────────┐
               │  domain/    │  纯数据模型 (Message / Instruction / Task / Status)
               └──────┬──────┘  被所有人依赖，不依赖任何人
                      ▲
            ┌─────────┼─────────┬─────────┐
            │         │         │         │
       ┌────┴───┐ ┌───┴───┐ ┌──┴────┐ ┌──┴─────┐
       │ whop/  │ │parser/│ │broker/│ │storage/│  独立模块
       └────┬───┘ └───┬───┘ └──┬────┘ └──┬─────┘  只依赖 domain + core
            │         │        │         │
            └─────────┴────────┴─────────┘
                         ▲
                         │ 发布事件 / 订阅事件
                         ▼
                  ┌──────────────┐
                  │  event_bus   │  进程内 pub/sub，核心解耦机制
                  └──────┬───────┘
                         ▲
                         │ 订阅
                   ┌─────┴─────┐
                   │   api/    │  FastAPI + WebSocket，对外暴露
                   └───────────┘
```

**核心原则**：四个业务模块（whop / parser / broker / storage）互不直接调用，全走 `event_bus`。好处是：

- 新增消费者（比如未来要加 Telegram 通知、Discord webhook）只需 `event_bus.subscribe("task.push_event", handler)`，零侵入
- 单元测试容易：mock event bus，注入假消息观察输出事件

### 3.2 目录结构

```
signal-station/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── event_bus.py          # 进程内 asyncio pub/sub
│   │   │   ├── config.py             # pydantic-settings 读取 .env
│   │   │   └── logger.py             # 结构化 JSON 日志
│   │   ├── domain/                   # 模型定义（纯数据，零副作用）
│   │   │   ├── message.py            # Message
│   │   │   ├── instruction.py        # Instruction 抽象 + StockInstruction + OptionInstruction
│   │   │   ├── task.py               # Task（聚合根）
│   │   │   ├── status.py             # Status 枚举 + 状态机转换规则
│   │   │   └── push_event.py         # PushEvent (订单推送事件)
│   │   ├── whop/                     # 模块 2：whop 消息监听
│   │   │   ├── login.py              # cookie 持久化 + 登录流程
│   │   │   ├── browser.py            # Playwright 封装
│   │   │   ├── extractor.py          # DOM → Message
│   │   │   └── listener.py           # 轮询 + 去重 + 发 message.received
│   │   ├── parser/                   # 模块 3：消息 → 指令
│   │   │   ├── stock_parser.py
│   │   │   ├── option_parser.py
│   │   │   └── context_resolver.py   # 结合历史上下文补齐 ticker
│   │   ├── broker/                   # 模块 4：长桥下单
│   │   │   ├── longport_client.py    # SDK 薄封装
│   │   │   ├── trader.py             # Instruction → 下单动作
│   │   │   ├── push_listener.py      # 订阅 broker push，发 task.push_event
│   │   │   └── status_updater.py     # PushEvent → Task.status 转换
│   │   ├── storage/                  # 持久化
│   │   │   ├── db.py                 # SQLAlchemy engine + async session
│   │   │   ├── schema.py             # ORM 表
│   │   │   ├── repo.py               # 业务查询封装
│   │   │   └── listeners.py          # 订阅全部事件 → 落盘
│   │   ├── api/
│   │   │   ├── http.py               # REST 端点
│   │   │   ├── ws.py                 # WebSocket hub
│   │   │   ├── schemas.py            # Pydantic 出参/入参
│   │   │   └── auth.py               # APP_TOKEN 中间件
│   │   └── main.py                   # FastAPI + 模块装配
│   ├── alembic/
│   ├── tests/
│   │   ├── domain/
│   │   ├── parser/
│   │   ├── broker/
│   │   └── integration/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx                   # 模块 6：App 主体
│   │   ├── components/
│   │   │   ├── Card/                 # 模块 5：Card 组件
│   │   │   │   ├── Card.tsx          # 外壳，切换 compact / expanded
│   │   │   │   ├── CardCompact.tsx
│   │   │   │   ├── CardExpanded.tsx
│   │   │   │   ├── PushChain.tsx     # 单行节点链
│   │   │   │   ├── PushDetail.tsx    # 垂直详情列表
│   │   │   │   └── OrderSubmit.tsx   # 提交订单阶段的强调展示
│   │   │   ├── TopBar.tsx
│   │   │   ├── RightRail.tsx
│   │   │   └── common/
│   │   │       ├── StatusPill.tsx
│   │   │       └── TypeBadge.tsx
│   │   ├── stores/                   # Zustand
│   │   │   ├── tasks.ts              # Task 列表 + 新增 push event 增量更新
│   │   │   ├── positions.ts
│   │   │   ├── stats.ts
│   │   │   └── conn.ts               # WebSocket 连接状态
│   │   ├── api/
│   │   │   ├── ws.ts                 # 客户端 + 自动重连 + 心跳
│   │   │   ├── http.ts               # fetch 封装
│   │   │   └── types.ts              # 从 OpenAPI 自动生成
│   │   ├── styles/
│   │   │   ├── tokens.css            # design system CSS 变量
│   │   │   └── fonts.css             # IBM Plex 引入
│   │   ├── hooks/
│   │   │   └── useStickyTop.ts       # 右栏粘顶行为
│   │   └── main.tsx
│   ├── public/
│   ├── index.html
│   ├── tsconfig.json
│   ├── vite.config.ts
│   └── package.json
├── data/
│   └── signals.db                    # SQLite（gitignored）
├── .auth/
│   └── whop_cookie.json              # Whop 登录态（gitignored）
├── docs/
│   └── architecture.md               # 基于本文档演化的长期文档
├── scripts/                          # 一次性运维脚本（从 main 分支按需迁入）
├── .env.example
├── .gitignore
├── README.md
└── Makefile                          # 常用命令集合（dev / build / db migrate）
```

---

## 4. 领域模型（domain/）

### 4.1 Message

```python
@dataclass(frozen=True)
class Message:
    id: str                         # whop domID —— 这也是对应 Task 的唯一标识
    content: str                    # 清洗后的正文
    raw_content: str                # 原始正文（含 emoji / 引用等）
    author: str | None
    posted_at: datetime             # Whop 上的时间戳
    received_at: datetime           # 我们抓到的时刻
    source: Literal["stock", "option"]  # 源于哪个 whop 页面
    quoted: Message | None          # 引用消息（refer context）
    history_hint: list[Message]     # 同组临近消息，用于解析上下文
```

### 4.2 Instruction

```python
class InstructionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"          # 止盈/止损调整

@dataclass
class Instruction(ABC):
    instruction_type: InstructionType
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None         # "小仓位" / "一半" / "全部" 等文本
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: Literal["group", "refer", "recent", "positions"] | None
    parser_notes: list[str]           # 解析时的 debug 信息

@dataclass
class StockInstruction(Instruction):
    ticker: str                       # TSLL
    symbol: str                       # TSLL.US
    sell_quantity: str | None         # "1/2" / "全部"

@dataclass
class OptionInstruction(Instruction):
    ticker: str
    option_type: Literal["CALL", "PUT"]
    strike: float
    expiry: date                      # 标准化日期
    symbol: str                       # NVDA 250426C135.US
```

### 4.3 Task（聚合根）

Task 的唯一标识直接使用其关联 Message 的 `domID`。一条消息对应一个 Task，贯穿整个生命周期（包括 PARSE_ERROR 的消息），前后端 / 数据库 / 日志 / WebSocket 事件一律使用同一个 id 溯源。

```python
@dataclass
class Task:
    id: str                               # = Message.id = whop domID
    type: Literal["stock", "option", "unknown"]
    status: Status
    message: Message
    instruction: Instruction | None       # 解析成功后填充
    order_id: str | None                  # 提交后填充
    push_events: list[PushEvent]
    stage_timings: dict[str, float]       # {"parse": 18, "submit": 412, ...}
    created_at: datetime
    updated_at: datetime
    reject_reason: str | None
```

**唯一性说明**：

- 同一条 whop 消息在反复抓取（轮询 + 历史滚动）时拿到同一个 domID，天然去重
- 不再生成单独的 UUID（避免 id 空间双重维护、跨层对齐成本）
- 极端情况 domID 冲突：whop 自身保证同页内唯一；跨页（stock 页 vs option 页）同时出现同一 domID 的概率极低，若发生记录异常事件并以最早一条为准


### 4.4 Status（状态机）

```python
class Status(str, Enum):
    RECEIVED = "RECEIVED"                 # 消息刚到
    PARSING = "PARSING"
    PARSE_ERROR = "PARSE_ERROR"           # 无法解析，终态
    INSTRUCTION_READY = "INSTRUCTION_READY"
    SUBMITTING = "SUBMITTING"             # 调用 broker.submit 中
    SUBMIT_FAILED = "SUBMIT_FAILED"       # 终态
    PENDING = "PENDING"                   # 已提交，等 broker push
    PARTIAL = "PARTIAL"                   # 部分成交
    FILLED = "FILLED"                     # 终态
    CANCELLED = "CANCELLED"               # 终态
    REJECTED = "REJECTED"                 # 终态
    SKIPPED = "SKIPPED"                   # 风控拒下（价差超容忍度、watchlist 未命中等）终态

TERMINAL = {PARSE_ERROR, SUBMIT_FAILED, FILLED, CANCELLED, REJECTED, SKIPPED}
```

转换规则在 `status.py` 以显式 table 写清楚，禁止任意跳转。

### 4.5 PushEvent

```python
class PushState(str, Enum):
    NEW = "NEW"                 # broker 确认创建
    SUBMITTED = "SUBMITTED"     # 进入市场
    MODIFIED = "MODIFIED"       # 改单
    PARTIAL = "PARTIAL"         # 部分成交
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"           # broker 内部错误

@dataclass(frozen=True)
class PushEvent:
    id: str                      # 自动生成（UUID7 或递增 ulid，仅用于去重和回放）
    task_id: str                 # = Task.id = Message.id = domID
    order_id: str
    state: PushState
    received_at: datetime
    payload: dict                # broker 原始 payload（JSON-serializable）
    # 计算/派生字段
    delta_qty: int | None        # 本次新成交数量
    delta_price: float | None
    cumulative_qty: int | None
    cumulative_avg_price: float | None
    note: str | None             # "本地 chase 优化"等人类可读
```

---

## 5. 事件模型（event_bus）

### 5.1 事件清单

| 事件名 | payload | 发布者 | 主要订阅者 |
|--------|---------|--------|-----------|
| `message.received` | `Message` | whop/listener | storage, parser |
| `task.created` | `Task` (Status=PARSING) | parser | storage, ws, broker |
| `task.instruction_ready` | `Task` | parser | storage, ws, broker |
| `task.parse_failed` | `Task` (Status=PARSE_ERROR) | parser | storage, ws |
| `task.order_submitted` | `Task` + 提交耗时 | broker/trader | storage, ws |
| `task.submit_failed` | `Task` + 原因 | broker/trader | storage, ws |
| `task.push_event` | `Task` + `PushEvent` | broker/push_listener | storage, ws, status_updater |
| `task.status_changed` | `Task` + old_status + new_status | status_updater | ws |
| `system.connection_changed` | `{target: "whop" \| "longport", status: "up" \| "down"}` | whop / broker | ws |

### 5.2 实现

- `asyncio.Queue` 为骨，一个 publisher 多个 subscriber
- 每个订阅者拿自己的 queue，消费失败不影响其他订阅者
- 关键错误落 WAL 日志，让模块能 replay

---

## 6. 数据库 Schema

```sql
-- 最新状态的 Task（查询主表）
-- id 即 Message.id 即 whop domID，三者共享同一主键空间
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,                  -- = messages.id = domID
  type TEXT NOT NULL,                   -- stock | option | unknown
  status TEXT NOT NULL,
  order_id TEXT,
  ticker TEXT,
  symbol TEXT,
  side TEXT,                            -- BUY | SELL | CLOSE | MODIFY
  price REAL,
  quantity INTEGER,
  reject_reason TEXT,
  stage_timings_json TEXT,              -- {"parse": 18, ...}
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_symbol ON tasks(symbol);

-- 原始消息（与 tasks 表 1:1 共享主键）
CREATE TABLE messages (
  id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,  -- = tasks.id = domID
  content TEXT NOT NULL,
  raw_content TEXT NOT NULL,
  author TEXT,
  source TEXT NOT NULL,                 -- stock | option
  posted_at TIMESTAMP NOT NULL,
  received_at TIMESTAMP NOT NULL,
  quoted_message_id TEXT
);

-- 解析出的指令（冗余存为 JSON，避免多表 join）
CREATE TABLE instructions (
  task_id TEXT PRIMARY KEY REFERENCES tasks(id),
  instruction_type TEXT NOT NULL,
  context_source TEXT,
  payload_json TEXT NOT NULL            -- 完整 Instruction 序列化
);

-- 订单推送事件流（追加，不改）
CREATE TABLE push_events (
  id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(id),
  order_id TEXT NOT NULL,
  state TEXT NOT NULL,
  received_at TIMESTAMP NOT NULL,
  delta_qty INTEGER,
  delta_price REAL,
  cumulative_qty INTEGER,
  cumulative_avg_price REAL,
  note TEXT,
  payload_json TEXT NOT NULL
);
CREATE INDEX idx_push_task ON push_events(task_id, received_at);

-- 持仓快照（每次 longport 同步覆盖）
CREATE TABLE positions (
  symbol TEXT PRIMARY KEY,
  type TEXT NOT NULL,                   -- stock | option
  ticker TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  avg_cost REAL,
  option_strike REAL,
  option_expiry DATE,
  option_type TEXT,
  updated_at TIMESTAMP NOT NULL
);
```

---

## 7. API 合约

### 7.1 REST

| 方法 | 路径 | 入参 | 出参 | 说明 |
|------|------|------|------|------|
| `GET` | `/api/tasks` | `limit`, `cursor`, `status?`, `type?`, `symbol?` | `{tasks: Task[], next_cursor}` | 列表（倒序） |
| `GET` | `/api/tasks/{id}` | — | `Task`（含 push_events） | 详情 |
| `POST` | `/api/tasks/{id}/cancel` | — | `{ok: true}` | 手动撤单，broker 返回后通过 push_event 反馈 |
| `GET` | `/api/stats/today` | — | `{msg_count, parse_ok, parse_rate, orders, filled, rejected}` | 右栏 |
| `GET` | `/api/positions` | — | `{stocks: Position[], options: Position[]}` | 右栏 |
| `GET` | `/api/health` | — | `{whop: up/down, longport: up/down, mode, dry_run}` | 顶栏 |

### 7.2 WebSocket

- 路径：`/ws`
- 握手：URL query `?token=<APP_TOKEN>`，不匹配则 403 关闭
- 握手补拉：查询参数 `?since=<event_id>` 让客户端重连后从指定 id 之后回放，服务端在内存里保留最近 500 条事件（FIFO），超过则客户端需要通过 `/api/tasks` 重拉
- 消息格式（server → client，每条带递增 `event_id`）：
  ```json
  {"event_id": 10423, "type": "task.push_event", "payload": {...Task..., "push_event": {...}}}
  ```
- 心跳：客户端每 25s 发 `{"type":"ping"}`，server 回 `pong`
- 断连：客户端指数退避重连（1s → 2s → 4s → 最多 30s），重连后带上最后收到的 `event_id` 作为 `since`

### 7.3 鉴权

- `.env` 配置 `APP_TOKEN`（随机 32 字符）
- 前端在 URL `?token=xxx` 或 localStorage 保存
- FastAPI dependency 校验 REST 和 WS
- 无 token 直接返回 403。不搞多用户账号系统（YAGNI）

---

## 8. 部署与运行

### 8.1 开发（本地 Mac）

```bash
# 后端
cd signal-station
uv venv && source .venv/bin/activate
uv pip install -e backend
alembic -c backend/alembic.ini upgrade head
python -m backend.app.main                       # :8000

# 前端（另一窗）
cd frontend
npm install
npm run dev                                      # :5173 代理 /api /ws 到 :8000
```

### 8.2 生产（单命令）

```bash
cd frontend && npm run build   # 输出到 frontend/dist
cd ..
python -m backend.app.main     # 挂载 frontend/dist 为静态资源，一个端口搞定
```

浏览器打开 `http://localhost:8000/?token=<APP_TOKEN>` 即可。

### 8.3 分享给朋友

**本机 Mac 单机部署**，朋友要看就需要一个可达 URL。最朴素做法：`ngrok http 8000` 临时暴露；中长期考虑在朋友需要时跑 `cloudflared tunnel` 或 Tailscale Funnel。**本文档不定死分享方式**，留待后续按需加。

### 8.4 常用命令（Makefile）

```
make dev            # 并发启 backend + frontend
make build          # 打包前端
make db-migrate     # alembic upgrade head
make db-reset       # 重置开发 DB
make test           # 跑所有测试
make lint
```

---

## 9. 设计系统（UI）

完整 mockup 位置：`.superpowers/brainstorm/69376-*/content/v0-app-mockup-v5.html`

**tokens**（会移到 `frontend/src/styles/tokens.css`）：

- **色彩**：`bg-0 #0b0f14` · `bg-1 #121821` · `bg-2 #171f2a` · 发丝线 `rgba(255,255,255,0.06)` · 主文 `#e4e8ef` · 次 `#8a93a1` · 弱 `#566071`
- **主色**：`#3fb5c5` teal（仅身份标记、选中态）
- **状态色**：OK `#3dd68c` · ERR `#ef5b5b` · WARN `#e7a73d` · INFO `#5aa0ff`
- **类型色**：STOCK teal 系（同主色） · OPTION `#c688ff` purple 系
- **字体**：`IBM Plex Sans` 400/500/600 · `IBM Plex Mono` 400/500（mono 用于 ticker / 价格 / ts / order_id）
- **间距**：4px 基准；Card 内 padding 12px；Card 间距 8px
- **圆角**：chip 3px；Card 6px（禁用大圆角）
- **无阴影**；层级靠 bg 色阶 + 发丝线
- **动效**：150ms ease-out；PENDING / PARTIAL 的 status pill 使用 1.2s 脉冲；尊重 `prefers-reduced-motion`

**Card 两态**：
- **Compact** · 单行 grid 8 列：`[type] [symbol] [side] [details] [ts] [elapsed] [status] [caret]`
- **Expanded** · 分三块：原始消息 + chips → 本地 stages（原始消息/解析指令/提交订单）→ 订单推送（内部再两态：紧凑 node chain / 垂直详情 list，独立 toggle）

**App 骨架**：
- 顶栏 48px（品牌 · filters · 连接灯 · 账户 pill）
- 主区两列：左 card stream（自动智能模式 = 活跃展开 + 历史紧凑）| 右 rail 320px（今日统计 + 正股持仓 + 期权持仓；粘顶行为随 scroll 动态调整）

---

## 10. 非目标 / Out of scope（本次不做）

- 多用户账号系统 / OAuth 登录
- 云端部署 / Docker（留作可选，不纳入 v2 主交付）
- 前端路由 / 多页面（只有单个 dashboard 页）
- 图表库 / K 线 / 盘口（右栏留 placeholder，后续接入）
- 移动端适配（桌面优先）
- 国际化（中英文混排，暂不做 i18n）
- 消息解析能力升级（沿用现解析器逻辑，解析改进单独另立 spec）
- 老 `main.py` 的归档决策（等 v2 稳定跑一段再定）

---

## 11. 验收标准

v2 重构视为完成的条件：

1. Whop 消息 → SQLite 记录全链路可跑；与 `main` 分支现跑行为在样例数据下解析一致
2. 所有状态（RECEIVED / PARSING / PARSE_ERROR / INSTRUCTION_READY / SUBMITTING / SUBMIT_FAILED / PENDING / PARTIAL / FILLED / CANCELLED / REJECTED / SKIPPED）在浏览器 Card 上可观察到
3. WebSocket 断线可自动重连，消息不丢（通过服务端缓冲 + 客户端按 cursor 补拉）
4. 浏览器刷新后：首屏拉 `/api/tasks?limit=100` 能恢复今日视图；点任一 Card `展开 → 收起` 行为与 v5 mockup 一致
5. 至少覆盖 domain / parser / broker 核心路径的单测；一个端到端集成测（假 whop + 假 longport）
6. `python -m backend.app.main` 单命令启动，浏览器访问 `:8000/?token=xxx` 能用
7. 跑在本地 Mac 上，空闲内存占用 < 300MB

---

## 12. 风险与未决

| 风险 | 缓解 |
|------|------|
| WebSocket 在 macOS 系统休眠后断连 | 客户端指数退避重连；服务端保留最近 N 个事件供按 cursor 补拉 |
| SQLite 并发写（whop 监听 + broker push 同时写） | 用 SQLAlchemy async session + WAL 模式；单写线程序列化也可接受 |
| Longport push_listener 连接数限制 | 延续现有 `_create_broker_with_retry` 逻辑 |
| 新老解析器逻辑偏差 | 第 0 步做 snapshot 测试：用 `data/stock_parsed_message.json` 喂新 parser，对比输出差异 |
| `refactor-v2` 分支存续期间老 bug 修复 | 只修 main；v2 分支 rebase 而非 merge 吸收 |

---

## 13. 下一步

本 spec 定稿后转入 `superpowers:writing-plans` 生成分阶段实施计划，建议划阶段：

- **阶段 0**：创建 worktree + 脚手架（pyproject、vite、alembic 初始化、CI lint）
- **阶段 1**：`domain/` 数据模型 + 状态机 + 测试
- **阶段 2**：`storage/` + Alembic 首版迁移
- **阶段 3**：`parser/`（含解析器 snapshot 测试与老行为对齐）
- **阶段 4**：`broker/`（含 mock SDK 的 push 回放）
- **阶段 5**：`whop/`（含离线 HTML 的 extractor 测试）
- **阶段 6**：`api/` + WebSocket hub + auth
- **阶段 7**：前端脚手架 + design tokens + Card 组件
- **阶段 8**：前端 App 骨架 + WS 客户端 + 状态 store
- **阶段 9**：端到端联调 + 生产打包 + README

（具体 task 划分由 writing-plans 环节完成，本文档不展开）
