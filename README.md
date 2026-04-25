# Signal Station v2

实时 Whop 信号监控 + 长桥（LongPort）自动下单 + Dark 监控看板，前后端单端口集成。

> 中文为主，英文术语保留以匹配代码 / API。

## 状态

| 层 | 测试 | 类型检查 |
|----|------|---------|
| Backend | 262 passing + 2 skipped | mypy strict 干净 |
| Frontend | 91 passing | TypeScript strict 干净 |
| 集成 | 4 个 e2e acceptance 测试（spec §11） | — |

`ruff` / `vitest` 全绿；CI baseline：Python 3.11 + Node 18+。

---

## 目录

- [架构](#架构)
- [模块清单](#模块清单)
- [快速开始](#快速开始)
- [日常使用](#日常使用)
- [配置（.env）](#配置env)
- [Whop 监听 UI 工作流](#whop-监听-ui-工作流)
- [开发模式](#开发模式)
- [REST API 参考](#rest-api-参考)
- [WebSocket 协议](#websocket-协议)
- [运维 cheatsheet](#运维-cheatsheet)
- [故障排查](#故障排查)
- [验收标准 §11](#验收标准-11)
- [项目结构](#项目结构)
- [设计说明](#设计说明)

---

## 架构

```
Whop 频道页（chromium）
        │
        ▼
  WhopBrowser（Playwright async）
        │  DOM → Message
        ▼
  WhopListener（轮询，去重，发布）
        │  EVENT: message.received
        ▼
  EventBus（进程内 asyncio pub/sub）
        │
   ┌────┴───────────────┐
   │                    │
   ▼                    ▼
ParserService       StorageListeners
（stock/option       （SQLite upsert：
  正则解析 +           每个 task.* 事件落盘）
  context resolver）
   │
   │ EVENT: task.instruction_ready
   ▼
  Trader
  （风控 → 提交订单 / dry-run）
   │
   ▼
LongPortClient    ←──── PushListener
（REST + WS SDK）       （订单状态推送回调）
   │                          │
   │ EVENT: task.push_event   │
   └──────────────────────────┘
                │
                ▼
         WebSocketHub
         （ring buffer，?since= replay）
                │
                ▼
         FastAPI /ws
                │
                ▼
         React 前端
         （Zustand stores · Card/TopBar/RightRail/WhopPanel）
```

**关键设计**：

- 模块间**只**通过 `EventBus` 通信。新增功能（比如 Telegram 通知）订阅事件即可，零侵入
- Whop 监听是**动态注册**：`WhopRegistry` 持久化页面列表到 `data/whop_pages.json`，REST + 前端 UI 可运行时增删
- `Task.id = Message.id = whop domID`：贯穿前后端、DB、日志、WS 事件，全链路同 id 溯源
- LongPort 凭据缺失时降级到 `NoopBrokerClient`：仍然能跑解析 + UI，只是不下单

---

## 模块清单

### Backend (`backend/app/`)

| 模块 | 职责 |
|------|------|
| `main.py` | App 工厂 `create_app(...)` + lifespan startup/shutdown + 静态前端挂载 |
| `core/config.py` | pydantic-settings；从 `.env` 加载所有配置 |
| `core/event_bus.py` | 进程内 asyncio pub/sub，fan-out + 失败隔离 |
| `core/events.py` | 事件 topic 常量 + payload dataclass（MessagePayload, TaskPayload …） |
| `domain/` | 纯领域模型：Message · Instruction · Task · Status · PushEvent |
| `parser/service.py` | 订阅 `message.received` → 跑解析器 + context resolver |
| `parser/stock_parser.py` | 正股信号正则解析（snapshot 命中率 94%+） |
| `parser/option_parser.py` | 期权合约信号解析；标准化 expiry 为 date |
| `parser/context_resolver.py` | refer / watchlist / recent 三段式补齐 ticker |
| `broker/longport_client.py` | LongPort SDK 封装（提交/撤单/报价/推送订阅） |
| `broker/noop_client.py` | 凭据缺失时的兜底实现，监控-only 模式 |
| `broker/trader.py` | 风控 + 订阅 `task.instruction_ready` 提交订单 |
| `broker/push_listener.py` | LongPort 推送回调 → `task.push_event` |
| `storage/db.py` | SQLAlchemy async engine + session_scope（路径自动锚定项目根） |
| `storage/schema.py` | ORM 表（5 张：tasks / messages / instructions / push_events / positions） |
| `storage/repo.py` | save_task / load_task / list_tasks / append_push_event（含 SQLite UPSERT 防 race） |
| `storage/listeners.py` | EventBus → DB 自动落盘 |
| `api/http.py` | REST 路由（任务列表 / 任务详情 / 撤单 / 统计 / 持仓 / 健康 / **Whop 管理 5 个端点**） |
| `api/ws.py` | WebSocketHub：广播 + 500 条 ring buffer + `?since=` 续传 |
| `api/auth.py` | APP_TOKEN 校验（query / Bearer / X-App-Token 三种来源） |
| `api/schemas.py` | Pydantic 出参 schema |
| `whop/browser.py` | WhopBrowser：Playwright async 封装 |
| `whop/login.py` | Cookie 加载/保存（与 `scripts/whop_login.py` 共用路径） |
| `whop/extractor.py` | 纯函数 DOM → Message（用 `tmp/*/page_html.html` 离线测试） |
| `whop/listener.py` | 单页轮询循环，去重发事件，暴露 running/last_poll/error 状态 |
| `whop/registry.py` | **多页面运行时注册表**，持久化到 JSON，async-safe 增删 |

### Frontend (`frontend/src/`)

| 模块 | 职责 |
|------|------|
| `App.tsx` | 根组件：登录 gate · 路由（Dashboard / WhopPanel） · WS 客户端启动 |
| `api/http.ts` | 类型化 fetch wrapper（11 个方法：tasks / health / stats / positions / **whop/* 5 个**） |
| `api/ws.ts` | WebSocket 客户端 + 指数退避重连 + `?since=` 续传 |
| `api/types.ts` | 从后端 OpenAPI 自动生成 |
| `api/domain-types.ts` | 类型别名 re-export |
| `stores/conn.ts` | 连接状态 store |
| `stores/tasks.ts` | Task 列表 + push_event map |
| `stores/stats.ts` | 今日统计 |
| `stores/positions.ts` | 持仓 |
| `stores/view.ts` | **当前 tab：dashboard / whop** |
| `components/Login.tsx` | Token 登录页（首次访问） |
| `components/TopBar.tsx` | 品牌 + tab 切换 + 连接灯 + 账户 pill + 退出登录 |
| `components/RightRail.tsx` | 今日 / 正股持仓 / 期权持仓 |
| `components/Card/` | Card 全家桶（Compact · Expanded · PushChain · PushDetail · OrderSubmit） |
| `components/WhopPanel/WhopPanel.tsx` | **Whop 管理 tab：cookie 状态 · 添加 · 列表 · 重启 · 移除** |
| `hooks/useStickyTop.ts` | 右栏粘顶动态 offset |

---

## 快速开始

### 前置依赖

- Python 3.11+
- Node 18+
- [`uv`](https://github.com/astral-sh/uv) Python 包管理器：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- 长桥（LongPort）账号 + API key（可选 — 没填会进监控-only 模式）
- 你订阅的 Whop 频道 URL（可选 — 启动后从 UI 添加）

### 1. 克隆 + 安装

```bash
git clone <repo-url> signal-station
cd signal-station
make install
```

`make install` 跑：
- `backend/`：`uv venv && uv pip install -e ".[dev]"` + `playwright install chromium`
- `frontend/`：`npm install`

### 2. 配置 `.env`

```bash
cp .env.example .env
```

最小可跑配置（其他都用默认值）：

```env
# 必填：前端登录用的访问令牌（随便 32 字符随机串）
APP_TOKEN=put-your-32-char-secret-here
```

LongPort + Whop URL **都可以暂时不填** —— 系统会以监控-only 模式启动，登录后从 UI 加 Whop 监听。

填上 LongPort 凭据后才会真正下单：

```env
LONGPORT_MODE=paper
LONGPORT_PAPER_APP_KEY=...
LONGPORT_PAPER_APP_SECRET=...
LONGPORT_PAPER_ACCESS_TOKEN=...
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=true     # 安全起见先开，确认行为正确再关
```

### 3. 启动

**生产模式**（前端打包后挂载到 FastAPI 静态目录，单端口）：

```bash
make run
# 后端 + 前端 dist 都从 :8000 提供
# 浏览器: http://localhost:8000
```

**开发模式**（热重载，前后端分离）：

```bash
# 终端 1
make backend-dev   # uvicorn --reload :8000

# 终端 2
make frontend-dev  # vite dev :5173（代理 /api 和 /ws 到 :8000）

# 浏览器
open http://localhost:5173
```

### 4. 浏览器登录

第一次访问会跳到登录页（dark 主题卡片，要求输入 APP TOKEN）：

1. 输入 `.env` 里设的 `APP_TOKEN`
2. 点"进入"
3. Token 自动保存到浏览器 localStorage，之后无需重输

也可以一次性带 token 进入：`http://localhost:8000?token=<APP_TOKEN>`，之后清掉 query 也保留 localStorage 里的。

退出：顶栏角落 ⎋ 按钮。

### 5. 添加 Whop 监听

进入后默认是空看板。顶栏点 **"Whop 管理"** 切到 Whop tab。详见下面 [Whop 监听 UI 工作流](#whop-监听-ui-工作流)。

---

## 日常使用

```bash
# 启动
make backend-dev      # 终端 1
make frontend-dev     # 终端 2

# 关闭（任何模式都用这个）
make stop             # 关 :8000 + :5173
make stop-all         # 同上 + 清 Playwright 留下的孤儿 chromium

# 看后端测试
make test             # 后端 + 前端
cd backend && uv run pytest -v   # 仅后端
cd frontend && npm test          # 仅前端

# Lint / typecheck
make lint
make typecheck

# 重置 SQLite 数据库
make db-reset
```

---

## 配置（.env）

所有配置都从项目**根目录**的 `.env` 读取（不在 `backend/.env`）。

| Key | 默认 | 说明 |
|-----|------|------|
| `APP_TOKEN` | `change-me-...` | 前端登录 + REST/WS 的访问令牌。强烈建议改成强随机串 |
| `WHOP_STOCK_URL` | `""` | （可选）启动时 seed 一个正股监听。**留空时只能从 UI 添加** |
| `WHOP_OPTION_URL` | `""` | （可选）启动时 seed 一个期权监听 |
| `WHOP_POLL_INTERVAL` | `2.0` | DOM 轮询间隔（秒） |
| `WHOP_HEADLESS` | `false` | `true` = 无头模式；调试时设 `false` 能看到浏览器 |
| `LONGPORT_MODE` | `paper` | `paper` 或 `real` —— 选用哪一组凭据 |
| `LONGPORT_PAPER_APP_KEY` | `""` | 模拟账户 |
| `LONGPORT_PAPER_APP_SECRET` | `""` | |
| `LONGPORT_PAPER_ACCESS_TOKEN` | `""` | |
| `LONGPORT_REAL_*` | `""` | 真实账户（仅 `MODE=real` 时使用） |
| `LONGPORT_REGION` | `cn` | `cn` / `us` |
| `LONGPORT_AUTO_TRADE` | `true` | `false` = 仅解析不下单 |
| `LONGPORT_DRY_RUN` | `true` | `true` = 计算订单但不真正提交，仅日志 |
| `MAX_OPTION_TOTAL_PRICE` | `500.0` | 单笔期权总名义额上限（USD） |
| `MAX_OPTION_QUANTITY` | `3` | 单笔期权合约数上限 |
| `PRICE_DEVIATION_TOLERANCE` | `5.0` | 期权：市价偏离信号价超过 N% 拒下 |
| `STOCK_PRICE_DEVIATION_TOLERANCE` | `1.0` | 正股偏差容忍度 |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/signals.db` | 相对路径会**自动锚定到项目根**，不会因 CWD 变化失效 |
| `HTTP_HOST` | `127.0.0.1` | 后端绑定 host |
| `HTTP_PORT` | `8000` | 后端端口 |
| `LOG_LEVEL` | `INFO` | Python logging 级别 |

### 关注股配置

`config/watched_stocks.json` 给解析器优先匹配的 ticker 列表 + 别名（中文昵称）。改完不需要重启，启动时加载。

---

## Whop 监听 UI 工作流

进入 **Whop 管理** tab 后，看到三块卡：

### Cookie 状态卡

| 状态 | 含义 |
|------|------|
| ✅ 有效（绿） | `.auth/whop_cookie.json` 存在且 < 14 天 |
| ⚠️ 过期可能（黄） | 文件存在但 > 14 天，建议刷新 |
| ❌ 缺失（红） | 文件不存在，必须先登录 |

按钮：
- **刷新**：重新拉一遍状态
- **复制登录命令**：把 `uv run --project backend python scripts/whop_login.py` 拷到剪贴板

#### 第一次登录抓 cookie

1. 点"复制登录命令" → 粘贴到终端运行
2. 自动弹 chromium 窗口，打开 `https://whop.com/login/`
3. **你在浏览器里手动**输邮箱 / 密码 / 2FA → 跳转主页确认登录成功
4. **回到终端按回车**
5. 脚本调用 `context.storage_state(path=...)` 把 cookie + localStorage 一起 dump 到 `.auth/whop_cookie.json`
6. 浏览器关闭；回到前端 Whop 页面点"刷新" → 状态变 ✅ 有效

> 💡 后端启动时会自动加载这个 cookie，cookie 失效后正常情况下不会自动续期。重新跑登录脚本即可覆盖。

### 添加监听卡

填三项 → 点"添加监听"：
- **URL**：完整频道 URL，例如 `https://whop.com/joined/stock-and-option/<channel-id>/app/`
- **来源类型**：正股 / 期权（决定走哪个 parser）
- **显示名**（可选）：UI 列表里看到的标签，留空就用 URL

后端立即起 Playwright 监听该页面，列表出现新行。**重复 URL** / **占位符 URL（含 xxx/yyy）** 会被前端报错拒绝。

### 监听列表卡

| 列 | 含义 |
|---|---|
| 类型 | 正股青绿 / 期权紫色 徽章 |
| 名称 | 添加时填的显示名 |
| URL | 完整 URL（鼠标悬停看全） |
| 状态 | 运行中 / 错误（hover 看错误信息） / 未运行 |
| 最后轮询 | "5s 前" / "2m 前" / "1.3h 前" |
| 已发消息 | 累计推送到 event_bus 的新消息数 |
| 操作 | **重启** / **移除** |

数据持久化：列表存在 `data/whop_pages.json`，重启后端自动恢复并起 listener。

---

## 开发模式

### 前后端分离开发

```bash
make backend-dev      # uvicorn --reload :8000
make frontend-dev     # vite :5173 → 自动代理 /api 和 /ws
```

Vite 改前端代码秒热重载，uvicorn `--reload` 改后端代码自动重启。

### Backend 测试

```bash
cd backend
uv run pytest                    # 全部 262 + 2 skip
uv run pytest -v -x              # 第一个失败就停
uv run pytest tests/integration/test_acceptance.py  # 仅 acceptance
uv run pytest tests/whop/        # 仅 whop 模块
```

### Frontend 测试

```bash
cd frontend
npm test                         # vitest 全部 91
npm test -- --reporter verbose
```

### 类型检查

```bash
cd backend && uv run mypy app                  # mypy strict
cd frontend && npm run typecheck               # tsc --noEmit
```

### Lint

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
```

### 前端打包

```bash
make build           # frontend/dist/ 用于 make run 单端口部署
```

### 数据库

```bash
make db-migrate      # alembic upgrade head
make db-reset        # 删 DB 重建
```

### OpenAPI 类型同步

每次后端 schema 变了，前端要重新生成类型：

```bash
# 生成 frontend/openapi.json + 重写 frontend/src/api/types.ts
cd frontend && npm run gen:types
```

---

## REST API 参考

所有端点要 token，通过以下任一方式：

- Query：`?token=<APP_TOKEN>`
- Header：`Authorization: Bearer <APP_TOKEN>`
- Header：`X-App-Token: <APP_TOKEN>`

### 监控 / 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 连接状态 + 模式 + dry_run |
| GET | `/api/tasks?limit=50&cursor=&status=&type=&symbol=` | 任务列表分页（倒序） |
| GET | `/api/tasks/{id}` | 单 Task 详情（含 push_events） |
| POST | `/api/tasks/{id}/cancel` | 撤单（broker.cancel_order） |
| GET | `/api/stats/today` | 今日统计 |
| GET | `/api/positions` | 持仓快照 |

### Whop 监听管理（**新**）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/whop/pages` | 列出当前监听 + 状态 |
| POST | `/api/whop/pages` | 添加监听，body `{url, source, name?}` |
| DELETE | `/api/whop/pages/{id}` | 移除监听（停 listener + 删 entry） |
| POST | `/api/whop/pages/{id}/restart` | 重启某条监听 |
| GET | `/api/whop/cookie` | Cookie 文件状态（exists / age_seconds / mtime） |

### WebSocket

| 路径 | 说明 |
|------|------|
| `/ws?token=&since=<event_id>` | 全事件推送 + ring buffer 续传 |

详见下一节。

---

## WebSocket 协议

```
ws://localhost:8000/ws?token=<APP_TOKEN>
```

每条消息：

```json
{
  "event_id": 42,
  "type": "task.created",
  "payload": { "task": {...} }
}
```

### 事件类型

镜像 EventBus topic：

- `task.created`
- `task.instruction_ready`
- `task.parse_failed`
- `task.order_submitted`
- `task.submit_failed`
- `task.push_event`（payload 含 push_event 详情）
- `task.status_changed`
- `system.connection_changed`

### 重连续传

断线重连时带上 `?since=<last_event_id>`，hub 从 ring buffer 把之后的事件按序回放。Buffer 容量 500；超出时前端需要重新拉 `/api/tasks` 全量同步。

### Heartbeat

客户端每 25 秒发 `{"type":"ping"}`，服务端回 `{"type":"pong"}`。

---

## 运维 cheatsheet

```bash
# 启停
make backend-dev   # 后端
make frontend-dev  # 前端
make run           # 单端口生产模式
make stop          # 一键停 :8000 + :5173（带进程信息输出）
make stop-all      # 同上 + 清 Playwright chromium 残留

# 测试 / lint / typecheck
make test
make lint
make typecheck

# 数据库
make db-migrate
make db-reset

# 清理
make clean         # __pycache__ + dist/

# Whop cookie
uv run --project backend python scripts/whop_login.py           # 首次登录
uv run --project backend python scripts/whop_login.py --test    # 测试 cookie 有效性
```

---

## 故障排查

### 后端启动失败：`unable to open database file`

**已修**。如果还遇到，是因为 SQLite URL 指向了不存在的目录。`db.py::_resolve_sqlite_url` 会把相对路径锚到项目根并 `mkdir -p` 父目录。检查 `.env` 的 `DATABASE_URL` 是不是指向了什么诡异的路径。

### 后端启动报 `LONGPORT_PAPER_APP_KEY is empty but mode='paper'`

**这不是错误，是降级**。日志里会接着说：

```
Falling back to monitoring-only mode (NoopBrokerClient).
No orders will be submitted. Set LONGPORT_* env vars in .env to enable real trading.
```

系统进监控-only 模式：消息能被解析、Task 状态能被持续推到前端，但**不会真下单**。要启用下单，把 `LONGPORT_PAPER_*` 凭据填上。

### 后端启动卡 30 秒无响应

旧 bug。如果 `.env` 里 `WHOP_*_URL` 是 `https://whop.com/joined/stock-and-option/xxx/app/` 这种**占位符**，listener 会试着 navigate 这个假 URL → Playwright timeout 挂住。**已修**：`_is_placeholder_url()` 自动跳过 `xxx`/`yyy`/`example.com`/`your-page-here`。如果还卡，确认 `.env.example` 是最新版，把 `WHOP_*_URL` 留空。

### 所有 API 端点返回 422 `_kwargs missing`

**已修**。如果还遇到，是 `get_settings()` 函数签名带了 `**_kwargs`，FastAPI 在 `Depends(get_settings)` 时会把 `_kwargs` 当成 query 参。把签名改回 `def get_settings() -> Settings`。

### Whop 登录后立即跳回 `/login`

Cookie 失效或被 Whop 主动登出。重跑：

```bash
uv run --project backend python scripts/whop_login.py
```

### 浏览器打开 `localhost:8000` 是 404

后端未跑或前端没 build：

```bash
make build && make run
```

或开发模式直接打开 `http://localhost:5173`。

### 浏览器登录页输 token 后还是跳回登录页

Token 不匹配。打开 DevTools Console：

```js
localStorage.getItem("APP_TOKEN")  // 看保存了什么
localStorage.removeItem("APP_TOKEN")  // 清掉重输
```

或带 query 强制重置：`http://localhost:8000?token=<对的-token>`

### 高内存 / Playwright chromium 占用

正常 1 个 chromium 进程约 150-250 MB。如果你看到多个 chromium 在跑：

```bash
make stop-all   # 包含 Playwright 孤儿清理
```

如果不停加，是 listener 重启逻辑漏了，开 issue 给我（或检查 `WhopListener.stop()` 是否调到了）。

### SQLite "database is locked"

SQLite 单写。不要同时跑两个 uvicorn 占同一个 DB。`make stop` 先确认所有进程退干净。

### 测试 import `app.main` 失败

`app/main.py` 末尾有 `app = create_app()`，模块导入时执行；如果你在 test 里 `from app.main import app`，会在导入时失败（凭据缺）。**测试请用 `from app.main import create_app; app = create_app(broker_override=FakeBrokerClient(), skip_whop=True)`**。

---

## 验收标准 §11

`backend/tests/integration/test_acceptance.py` 4 个测试全过：

| # | 标准 | 测试名 |
|---|------|--------|
| §11.1 | Whop 消息 → SQLite 全链路可跑 | `test_acceptance_e2e_full_cycle` |
| §11.3 | WS 断线 buffered + cursor replay | `test_acceptance_websocket_broadcast_and_replay` |
| §11.4 | 浏览器刷新首屏从 /api/tasks 恢复 | `test_acceptance_browser_refresh_recovers_via_initial_list` |
| §11.6 | 单命令启动 + mode 可观察 | `test_acceptance_health_endpoint_exposes_mode` |

§11.2（所有 Status 在 Card 上可观察）、§11.5（单测覆盖）、§11.7（< 300 MB）由全套测试集 + 手动确认。

---

## 项目结构

```
signal-station/
├── .env                          # 凭据 / token（git-ignored）
├── Makefile                      # install / dev / build / run / stop / test / ...
├── README.md
├── config/
│   ├── watched_stocks.json       # 关注股 + 中文别名
│   └── ticker_aliases.json
├── data/
│   ├── signals.db                # SQLite（git-ignored）
│   └── whop_pages.json           # Whop 监听列表（持久化）
├── docs/
│   └── superpowers/
│       ├── specs/2026-04-25-signal-station-design.md
│       └── plans/2026-04-25-signal-station-implementation.md
├── scripts/
│   ├── whop_login.py             # Whop 交互式登录抓 cookie
│   ├── stop.sh                   # 一键关闭脚本
│   └── dump_openapi.py           # 生成 frontend/openapi.json 给 ts 类型用
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                  # DB migrations
│   ├── app/
│   │   ├── main.py               # FastAPI 工厂 + lifespan + 静态挂载
│   │   ├── api/                  # REST + WS routers + auth + schemas
│   │   ├── broker/               # LongPort + Trader + PushListener + NoopBroker
│   │   ├── core/                 # config + EventBus + events
│   │   ├── domain/               # Task / Message / Instruction / PushEvent / Status
│   │   ├── parser/               # 正股 + 期权 + context resolver + service
│   │   ├── storage/              # SQLAlchemy + repo + listeners
│   │   └── whop/                 # browser + extractor + listener + registry + login
│   └── tests/
│       ├── api/                  # HTTP + WS + e2e + Whop 端点
│       ├── broker/
│       ├── core/
│       ├── domain/
│       ├── integration/          # acceptance §11
│       ├── parser/               # 含 snapshot 回归
│       ├── storage/
│       └── whop/                 # registry + listener + extractor
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── dist/                     # 生产打包产物（git-ignored）
    └── src/
        ├── App.tsx
        ├── api/                  # http + ws + types + domain-types
        ├── components/
        │   ├── Card/             # Card · CardCompact · CardExpanded · PushChain · PushDetail · OrderSubmit
        │   ├── WhopPanel/        # Whop 监听管理 tab
        │   ├── Login.tsx + .css  # token 登录页
        │   ├── TopBar.tsx + .css # 顶栏 + tab 切换 + logout
        │   └── RightRail.tsx + .css
        ├── hooks/useStickyTop.ts
        ├── stores/               # conn / tasks / stats / positions / view
        └── styles/               # tokens.css + fonts.css
```

---

## 设计说明

### 为什么不用消息队列？

每个 channel 一份信号流，2 channel 上限，每天几十条 message。进程内 asyncio EventBus 完全够用，零依赖，`wait_idle()` 让测试可断言"事件已 flush"。Redis/RabbitMQ 是过度设计。

### 为什么 SQLite？

写入是只追加（每个 task event 不可变），数据量低（每天几十信号），单进程访问。SQLite + SQLAlchemy async 在这个量级是生产级的，零运维。多用户后再迁 Postgres，schema 已经兼容。

### 为什么 Task.id = Message.id = whop domID？

避免维护两个 id 空间。Whop 自己保证同一个 channel 内 domID 唯一，重复抓取（轮询 + 历史滚动）天然去重。前端、后端、DB、日志、WS 事件全部用 domID 串起来，溯源直接 grep。

### Cookie 风险

`.auth/whop_cookie.json` 包含你的 Whop session。**不要**分享给朋友。朋友远程查看用的是你的 `APP_TOKEN`（前端登录 token），他们用各自的浏览器 + 你给的 APP_TOKEN 就能看到你抓的数据，但拿不到你的 Whop session。

### 凭据缺失降级策略

设计上不强求全套凭据齐全才能启动 —— 监控、UI、解析、入库这些核心能力都不依赖 broker。LongPort 凭据缺失 → `NoopBrokerClient`，会日志记录"假装下单了一笔"但实际不发请求。这也意味着 dry-run 流程里你能看见全套 Card 状态流转，只是订单永远停在 SUBMITTING（因为 NoopBroker 不发 push 事件）。

### Whop URL 占位符防呆

`.env.example` 模板里如果留 `xxx/yyy` 之类占位符，listener 会去 navigate 一个假 URL 然后 Playwright timeout，体验很糟。`_is_placeholder_url()` 主动检测并跳过：包含 `/xxx/`、`/yyy/`、`example.com`、`your-page-here` 的 URL 都会被识别为占位符，启动时 log info 跳过，不阻塞主流程。

### Token 前端策略

`APP_TOKEN` 是后端和操作者浏览器之间的共享秘密。**不嵌入打包产物** —— 前端首次访问时从 URL query 取，存到 localStorage，之后从本地读。这样既支持 "URL 一次性分享给朋友"，也避免在 JS bundle 里暴露 token。

---

## License / Notes

内部工具，不公开发行。LongPort SDK + Whop 凭据由用户自备。

完整设计文档：`docs/superpowers/specs/2026-04-25-signal-station-design.md`
完整实施计划：`docs/superpowers/plans/2026-04-25-signal-station-implementation.md`
