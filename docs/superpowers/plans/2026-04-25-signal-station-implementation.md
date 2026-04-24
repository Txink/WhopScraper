# Signal Station v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有 Whop 信号抓取 + 长桥自动交易项目重构为模块化的前后端分离架构（FastAPI + React SPA + SQLite + WebSocket），实现 Dark 监控看板 UI 实时展示 Task 全生命周期。

**Architecture:** 后端按模块拆分（domain / whop / parser / broker / storage / api），模块间经进程内 event bus 解耦。SQLite 持久化，WebSocket 推事件到前端。前端 React + TypeScript + Zustand 渲染 Card 流。Task.id = whop domID 贯穿全链路。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.x + Alembic + Playwright + LongPort SDK · React 18 + TypeScript 5 + Vite + Zustand · SQLite · uv (Python 包管理) · npm

**Reference spec:** `docs/superpowers/specs/2026-04-25-signal-station-design.md` —— 全部决策和数据模型细节以该文档为准。

---

## Workflow Notes

- **Working directory:** 所有 Phase 1+ 任务都在 git worktree `../signal-station`（Phase 0 创建），对应分支 `refactor-v2`。老项目 `/Users/tianpengxuan/Documents/playwright` 保持不动作为参考。
- **Commit cadence:** 每个 Task 完成后 commit；消息遵循仓库约定的中文前缀风格（`feat:`/`fix:`/`docs:`/`test:`/`refactor:`）。
- **TDD discipline:** 每个有逻辑的模块，先写失败测试 → 看到失败 → 写最小实现 → 看到通过 → 重构 → commit。脚手架类任务（新建目录、配置文件）跳过 TDD。
- **Test command reference:**
  - 后端：`cd backend && uv run pytest -v`
  - 前端：`cd frontend && npm test`
  - 完整：`make test`（Phase 0 建立）

---

## File Structure

完整目录结构见 spec §3.2。以下列出**每个文件的职责**，作为任务拆分依据：

### Backend (`backend/app/`)

| 文件 | 职责 | 依赖 |
|------|------|------|
| `core/event_bus.py` | asyncio pub/sub，订阅/发布解耦 | 无 |
| `core/config.py` | pydantic-settings 加载 .env | 无 |
| `core/logger.py` | 结构化 JSON 日志封装 | 无 |
| `domain/message.py` | `Message` 冻结 dataclass | 无 |
| `domain/instruction.py` | `Instruction` 抽象 + `StockInstruction` + `OptionInstruction` | 无 |
| `domain/status.py` | `Status` enum + 状态转换 table | 无 |
| `domain/push_event.py` | `PushEvent` 与 `PushState` enum | 无 |
| `domain/task.py` | `Task` 聚合根 + 生命周期方法 | domain/* |
| `storage/db.py` | SQLAlchemy async engine / session factory | 无 |
| `storage/schema.py` | ORM 表定义（5 张表） | db |
| `storage/repo.py` | 业务查询封装（task 列表、追加 push） | db, domain |
| `storage/listeners.py` | 订阅 event_bus 事件 → 落盘 | repo, event_bus |
| `parser/stock_parser.py` | 正股消息解析（从老 `parser/stock_parser.py` 迁移） | domain |
| `parser/option_parser.py` | 期权消息解析（从老 `parser/option_parser.py` 迁移） | domain |
| `parser/context_resolver.py` | 跨消息上下文补齐 ticker | domain, repo |
| `parser/service.py` | 订阅 `message.received` → 生成 Task → 发事件 | parser/*, event_bus |
| `broker/longport_client.py` | LongPort SDK 薄封装 | 无外部 |
| `broker/trader.py` | 消费 `task.instruction_ready` → 下单 | longport_client, event_bus |
| `broker/push_listener.py` | 订阅 longport push → 发 `task.push_event` | longport_client, event_bus |
| `broker/status_updater.py` | 订阅 `task.push_event` → 更新 Task.status | domain, event_bus |
| `whop/login.py` | cookie 加载/保存/登录流程 | playwright |
| `whop/browser.py` | Playwright Context / Page 封装 | playwright |
| `whop/extractor.py` | DOM → Message（从老 `scraper/message_extractor.py` 迁移） | playwright, domain |
| `whop/listener.py` | 轮询 + 去重 + 发 `message.received` | 上面三个, event_bus |
| `api/auth.py` | APP_TOKEN 校验依赖 | config |
| `api/schemas.py` | 前后端传输 Pydantic 模型 | domain |
| `api/http.py` | REST 路由 | schemas, repo, event_bus |
| `api/ws.py` | WebSocket hub + event_id 缓冲 + replay | schemas, event_bus |
| `main.py` | FastAPI 装配 + 模块启动 | 全部 |

### Frontend (`frontend/src/`)

| 文件 | 职责 |
|------|------|
| `styles/tokens.css` | design system CSS 变量（色彩、字体、间距、圆角、动画） |
| `styles/fonts.css` | IBM Plex Sans/Mono Google Fonts import |
| `api/types.ts` | OpenAPI 自动生成的类型（Task / Message / PushEvent …） |
| `api/http.ts` | fetch 封装，带 APP_TOKEN |
| `api/ws.ts` | WebSocket 客户端 + 重连 + event_id 续传 |
| `stores/tasks.ts` | Zustand store：Task 列表 + 增量 push event |
| `stores/positions.ts` | 持仓 store |
| `stores/stats.ts` | 今日统计 store |
| `stores/conn.ts` | 连接状态（whop / longport / ws） |
| `hooks/useStickyTop.ts` | 右栏粘顶动态 offset |
| `components/common/TypeBadge.tsx` | 正股/期权徽章 |
| `components/common/StatusPill.tsx` | 状态徽标（含 PENDING/PARTIAL 脉冲） |
| `components/Card/Card.tsx` | 外壳，内部切换 compact/expanded |
| `components/Card/CardCompact.tsx` | 单行紧凑 |
| `components/Card/CardExpanded.tsx` | 展开（含原始消息、chips、本地 stages） |
| `components/Card/OrderSubmit.tsx` | "提交订单" 阶段的强调展示 |
| `components/Card/PushChain.tsx` | 水平 node chain（紧凑） |
| `components/Card/PushDetail.tsx` | 垂直详情列表（展开） |
| `components/TopBar.tsx` | 顶栏（brand + filters + 连接灯 + 账户 pill） |
| `components/RightRail.tsx` | 右栏（今日 + 正股持仓 + 期权持仓） |
| `App.tsx` | 顶层装配 + 智能模式逻辑（PENDING/近 30s FILLED 展开） |
| `main.tsx` | React root + WS 初始化 |

### 根级

| 文件 | 职责 |
|------|------|
| `.env.example` | 配置模板（APP_TOKEN, LONGPORT_*, WHOP_*） |
| `Makefile` | dev / build / test / db-migrate / lint |
| `README.md` | 快速开始 + 架构图 + 截图 |
| `backend/pyproject.toml` | Python 项目（uv 管理） |
| `backend/alembic.ini` | Alembic 配置 |
| `frontend/package.json` | 前端依赖 |
| `frontend/vite.config.ts` | Vite 配置（含 /api /ws 代理） |
| `frontend/tsconfig.json` | TypeScript 严格模式 |

---

## Phase Overview

| Phase | 目标 | 产出可验证物 |
|-------|------|-----------|
| 0 | Worktree + 脚手架 | 空项目能 `make dev` 启动不报错 |
| 1 | Domain 模型 | `pytest tests/domain/ -v` 全绿 |
| 2 | Storage + Alembic | `pytest tests/storage/ -v` 全绿，`alembic upgrade head` OK |
| 3 | Event bus + Storage listeners | pub/sub 单测通过；事件触发落盘 |
| 4 | Parser + context resolver | 对老数据 snapshot 测试差异为 0 或可解释 |
| 5 | Broker + status updater | Mock SDK 下单 + push 回放测试通过 |
| 6 | Whop listener | 离线 HTML 解析测试通过 |
| 7 | API (REST + WS) + auth | curl / wscat 手动联调通过；API 单测全绿 |
| 8 | 前端脚手架 + design tokens + 类型生成 | Vite 空壳跑起来，tokens 色块能看 |
| 9 | 前端组件 + store + WS client | 打开浏览器能看到和 v5 mockup 一样的 dark dashboard |
| 10 | E2E 集成 + 生产构建 + README | `make build && make run` 单命令可跑 |

---

## Phase 0: Worktree + Scaffolding

### Task 1: 创建 worktree 与目录骨架

**Files:**
- 无（目录操作）

- [ ] **Step 1: 在老仓库目录创建 worktree**

从 `/Users/tianpengxuan/Documents/playwright` 运行：

```bash
git worktree add ../signal-station -b refactor-v2 main
cd ../signal-station
```

Expected: `Preparing worktree (new branch 'refactor-v2')` 并切换。

- [ ] **Step 2: 创建完整目录骨架**

```bash
mkdir -p backend/app/{core,domain,storage,parser,broker,whop,api}
mkdir -p backend/tests/{domain,storage,parser,broker,whop,api,integration}
mkdir -p backend/alembic/versions
mkdir -p frontend/src/{api,stores,hooks,styles,components/{common,Card}}
mkdir -p frontend/public
mkdir -p data docs scripts
touch backend/app/__init__.py backend/tests/__init__.py
for d in core domain storage parser broker whop api; do
  touch backend/app/$d/__init__.py
done
```

- [ ] **Step 3: 根级 .gitignore**

Create: `.gitignore`

```
# Python
__pycache__/
*.pyc
.venv/
.pytest_cache/
.ruff_cache/

# Node
node_modules/
dist/
.vite/

# IDE / OS
.vscode/
.idea/
.DS_Store

# 运行时
.env
data/*.db
data/*.db-shm
data/*.db-wal
.auth/
logs/
*.log

# Playwright
playwright-report/
test-results/
```

- [ ] **Step 4: 根级 README 占位**

Create: `README.md`

```markdown
# Signal Station

Whop 交易信号抓取 + 长桥自动下单 + Dark 监控看板。

See `docs/superpowers/specs/2026-04-25-signal-station-design.md` for full design.

## Quick start

See `Makefile` for commands. More docs coming in later phases.
```

- [ ] **Step 5: 首次 commit**

```bash
git add .gitignore README.md backend/ frontend/ data/ docs/ scripts/
git commit -m "chore: 初始化 signal-station 目录骨架"
```

Expected: commit successful, `git status` clean（除未追踪的 __init__.py 空文件被 add 即可）。

---

### Task 2: 后端 Python 项目配置

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/.python-version`
- Create: `backend/app/core/__init__.py`（已存在，无需创建）

- [ ] **Step 1: 创建 pyproject.toml**

Create: `backend/pyproject.toml`

```toml
[project]
name = "signal-station-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.20",
    "alembic>=1.13",
    "longport>=2.0",
    "playwright>=1.48",
    "python-dotenv>=1.0",
    "httpx>=0.27",
    "python-multipart>=0.0.12",
    "websockets>=13",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "pytest-cov>=6.0",
    "ruff>=0.7",
    "mypy>=1.13",
    "freezegun>=1.5",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

- [ ] **Step 2: 创建 .python-version**

Create: `backend/.python-version`

```
3.11
```

- [ ] **Step 3: 初始化 uv 环境**

```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
uv run playwright install chromium
cd ..
```

Expected: `.venv/` 创建成功，依赖安装完毕。

- [ ] **Step 4: 冒烟测试**

```bash
cd backend
uv run python -c "import fastapi, sqlalchemy, longport, playwright; print('ok')"
cd ..
```

Expected: 输出 `ok`。

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/.python-version
git commit -m "chore: 后端 pyproject.toml + uv 环境初始化"
```

---

### Task 3: 前端 Vite + TypeScript 项目配置

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`（占位）

- [ ] **Step 1: package.json**

Create: `frontend/package.json`

```json
{
  "name": "signal-station-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "typecheck": "tsc -b --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "gen:types": "openapi-typescript http://localhost:8000/openapi.json -o src/api/types.ts"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "zustand": "^5.0.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.12",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "typescript": "^5.6.3",
    "vite": "^5.4.10",
    "vitest": "^2.1.4",
    "@testing-library/react": "^16.0.1",
    "@testing-library/jest-dom": "^6.6.3",
    "jsdom": "^25.0.1",
    "openapi-typescript": "^7.4.2"
  }
}
```

- [ ] **Step 2: tsconfig.json**

Create: `frontend/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create: `frontend/tsconfig.node.json`

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 3: vite.config.ts（含 API/WS 代理）**

Create: `frontend/vite.config.ts`

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test-setup.ts",
  },
});
```

- [ ] **Step 4: index.html**

Create: `frontend/index.html`

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Signal Station</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: main.tsx + App.tsx 占位**

Create: `frontend/src/main.tsx`

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

Create: `frontend/src/App.tsx`

```tsx
export default function App() {
  return <div style={{ padding: 20, color: "white", background: "#0b0f14", minHeight: "100vh" }}>Signal Station · scaffolding OK</div>;
}
```

Create: `frontend/src/test-setup.ts`

```typescript
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 6: 安装前端依赖 + 冒烟**

```bash
cd frontend
npm install
npm run typecheck
cd ..
```

Expected: 无类型错误。

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "chore: 前端 Vite + React + TypeScript 脚手架"
```

---

### Task 4: Makefile + .env.example + 启动占位

**Files:**
- Create: `Makefile`
- Create: `.env.example`
- Create: `backend/app/main.py`

- [ ] **Step 1: .env.example**

Create: `.env.example`

```bash
# 分享访问令牌（32 字符随机串）
APP_TOKEN=change-me-to-a-random-32-char-string

# Whop 页面配置
WHOP_STOCK_URL=https://whop.com/joined/stock-and-option/xxx/app/
WHOP_OPTION_URL=https://whop.com/joined/stock-and-option/yyy/app/
WHOP_POLL_INTERVAL=2.0
WHOP_HEADLESS=false

# 长桥账户
LONGPORT_MODE=paper
LONGPORT_PAPER_APP_KEY=
LONGPORT_PAPER_APP_SECRET=
LONGPORT_PAPER_ACCESS_TOKEN=
LONGPORT_REAL_APP_KEY=
LONGPORT_REAL_APP_SECRET=
LONGPORT_REAL_ACCESS_TOKEN=
LONGPORT_REGION=cn
LONGPORT_AUTO_TRADE=true
LONGPORT_DRY_RUN=true

# 交易风控
MAX_OPTION_TOTAL_PRICE=500
MAX_OPTION_QUANTITY=3
PRICE_DEVIATION_TOLERANCE=5
STOCK_PRICE_DEVIATION_TOLERANCE=1

# 数据库
DATABASE_URL=sqlite+aiosqlite:///./data/signals.db

# 服务
HTTP_HOST=127.0.0.1
HTTP_PORT=8000
LOG_LEVEL=INFO
```

- [ ] **Step 2: backend/app/main.py 占位**

Create: `backend/app/main.py`

```python
"""Signal Station FastAPI 入口 —— Phase 0 占位版本。"""
from fastapi import FastAPI

app = FastAPI(title="Signal Station", version="0.1.0")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "phase": "0"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
```

- [ ] **Step 3: Makefile**

Create: `Makefile`

```makefile
.PHONY: dev backend-dev frontend-dev build test lint typecheck db-migrate db-reset clean

dev:
	@echo "Starting backend + frontend in parallel..."
	@(cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) & \
	 (cd frontend && npm run dev) & wait

backend-dev:
	cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

frontend-dev:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	cd backend && uv run pytest -v
	cd frontend && npm test

lint:
	cd backend && uv run ruff check .

typecheck:
	cd backend && uv run mypy app
	cd frontend && npm run typecheck

db-migrate:
	cd backend && uv run alembic upgrade head

db-reset:
	rm -f data/signals.db data/signals.db-shm data/signals.db-wal
	$(MAKE) db-migrate

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	rm -rf frontend/dist frontend/.vite
```

- [ ] **Step 4: 冒烟测试**

```bash
cp .env.example .env
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!
sleep 2
curl -s http://127.0.0.1:8000/api/health
kill $SERVER_PID
cd ..
```

Expected: `{"status":"ok","phase":"0"}`。

- [ ] **Step 5: Commit**

```bash
git add Makefile .env.example backend/app/main.py
git commit -m "chore: 添加 Makefile、.env.example、FastAPI 占位入口"
```

---

## Phase 1: Domain Models (TDD)

### Task 5: Message dataclass

**Files:**
- Create: `backend/app/domain/message.py`
- Create: `backend/tests/domain/test_message.py`
- Create: `backend/tests/domain/__init__.py`

- [ ] **Step 1: 写失败测试**

Create: `backend/tests/domain/test_message.py`

```python
from datetime import UTC, datetime

import pytest

from app.domain.message import Message


def _make(**overrides):
    defaults = dict(
        id="msg-abc-123",
        content="NVDA 135C 本周 2.15 进",
        raw_content="NVDA 135C 本周 2.15 进 🚀",
        author="big-elephant",
        posted_at=datetime(2026, 4, 25, 10, 42, 15, tzinfo=UTC),
        received_at=datetime(2026, 4, 25, 10, 42, 15, 82_000, tzinfo=UTC),
        source="option",
        quoted=None,
        history_hint=[],
    )
    defaults.update(overrides)
    return Message(**defaults)


def test_message_is_frozen():
    m = _make()
    with pytest.raises(Exception):
        m.content = "hacked"


def test_message_equal_by_id():
    a = _make()
    b = _make(content="different body")
    assert a == b, "Message 应按 id 唯一识别"


def test_message_source_must_be_stock_or_option():
    with pytest.raises(ValueError):
        _make(source="forex")


def test_message_history_hint_defaults_empty():
    m = _make()
    assert m.history_hint == []


def test_message_with_quoted_chain():
    parent = _make(id="msg-parent")
    child = _make(id="msg-child", quoted=parent)
    assert child.quoted is parent
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd backend && uv run pytest tests/domain/test_message.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.domain.message'`。

- [ ] **Step 3: 实现 Message**

Create: `backend/app/domain/message.py`

```python
"""Message —— 来自 Whop 的单条消息，id 为 whop domID，也是后续 Task 的唯一标识。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Source = Literal["stock", "option"]


@dataclass(frozen=True)
class Message:
    id: str
    content: str
    raw_content: str
    author: str | None
    posted_at: datetime
    received_at: datetime
    source: Source
    quoted: Message | None = None
    history_hint: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source not in ("stock", "option"):
            raise ValueError(f"invalid source: {self.source}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Message):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd backend && uv run pytest tests/domain/test_message.py -v
```

Expected: 5 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/message.py backend/tests/domain/
git commit -m "feat(domain): Message dataclass 定义 + 测试"
```

---

### Task 6: Instruction 抽象 + Stock/Option 子类

**Files:**
- Create: `backend/app/domain/instruction.py`
- Create: `backend/tests/domain/test_instruction.py`

- [ ] **Step 1: 写失败测试**

Create: `backend/tests/domain/test_instruction.py`

```python
from datetime import date

import pytest

from app.domain.instruction import (
    InstructionType,
    OptionInstruction,
    StockInstruction,
)


def test_stock_instruction_basic():
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.50,
        price_range=None,
        quantity=500,
        position_size=None,
        stop_loss_price=25.80,
        take_profit_price=None,
        context_source="group",
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )
    assert inst.ticker == "TSLL"
    assert inst.symbol == "TSLL.US"
    assert inst.instruction_type == InstructionType.BUY


def test_option_instruction_basic():
    inst = OptionInstruction(
        instruction_type=InstructionType.BUY,
        price=2.15,
        price_range=None,
        quantity=2,
        position_size="小仓位",
        stop_loss_price=None,
        take_profit_price=None,
        context_source="refer",
        parser_notes=[],
        ticker="NVDA",
        option_type="CALL",
        strike=135.0,
        expiry=date(2026, 4, 26),
        symbol="NVDA 250426C135.US",
    )
    assert inst.strike == 135.0
    assert inst.option_type == "CALL"


def test_option_invalid_type_rejected():
    with pytest.raises(ValueError):
        OptionInstruction(
            instruction_type=InstructionType.BUY,
            price=1.0,
            price_range=None,
            quantity=1,
            position_size=None,
            stop_loss_price=None,
            take_profit_price=None,
            context_source=None,
            parser_notes=[],
            ticker="AAPL",
            option_type="STRADDLE",  # type: ignore[arg-type]
            strike=200.0,
            expiry=date(2026, 5, 3),
            symbol="AAPL ...",
        )


def test_price_or_price_range_required():
    """至少需要 price 或 price_range 之一。"""
    with pytest.raises(ValueError):
        StockInstruction(
            instruction_type=InstructionType.BUY,
            price=None,
            price_range=None,
            quantity=100,
            position_size=None,
            stop_loss_price=None,
            take_profit_price=None,
            context_source=None,
            parser_notes=[],
            ticker="TSLL",
            symbol="TSLL.US",
            sell_quantity=None,
        )
```

- [ ] **Step 2: 跑失败**

```bash
cd backend && uv run pytest tests/domain/test_instruction.py -v
```

Expected: ModuleNotFoundError。

- [ ] **Step 3: 实现**

Create: `backend/app/domain/instruction.py`

```python
"""Instruction —— 从 Message 解析出的交易指令。Stock 和 Option 两个具体子类。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Literal


class InstructionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    CLOSE = "CLOSE"
    MODIFY = "MODIFY"


ContextSource = Literal["group", "refer", "recent", "positions"]
OptionSide = Literal["CALL", "PUT"]


@dataclass
class Instruction:
    instruction_type: InstructionType
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: ContextSource | None
    parser_notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.price is None and self.price_range is None:
            raise ValueError("Instruction 必须有 price 或 price_range")


@dataclass
class StockInstruction(Instruction):
    ticker: str = ""
    symbol: str = ""
    sell_quantity: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.ticker:
            raise ValueError("StockInstruction.ticker 必填")


@dataclass
class OptionInstruction(Instruction):
    ticker: str = ""
    option_type: OptionSide = "CALL"
    strike: float = 0.0
    expiry: date = field(default_factory=lambda: date.today())
    symbol: str = ""

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.option_type not in ("CALL", "PUT"):
            raise ValueError(f"invalid option_type: {self.option_type}")
        if not self.ticker:
            raise ValueError("OptionInstruction.ticker 必填")
```

- [ ] **Step 4: 跑通过**

```bash
cd backend && uv run pytest tests/domain/test_instruction.py -v
```

Expected: 4 passed。

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/instruction.py backend/tests/domain/test_instruction.py
git commit -m "feat(domain): Instruction 抽象 + StockInstruction/OptionInstruction"
```

---

### Task 7: Status enum 与状态机

**Files:**
- Create: `backend/app/domain/status.py`
- Create: `backend/tests/domain/test_status.py`

- [ ] **Step 1: 写失败测试**

Create: `backend/tests/domain/test_status.py`

```python
import pytest

from app.domain.status import TERMINAL, Status, can_transition, next_status


def test_terminal_set_contents():
    assert Status.PARSE_ERROR in TERMINAL
    assert Status.FILLED in TERMINAL
    assert Status.CANCELLED in TERMINAL
    assert Status.REJECTED in TERMINAL
    assert Status.SUBMIT_FAILED in TERMINAL
    assert Status.SKIPPED in TERMINAL
    assert Status.PENDING not in TERMINAL
    assert Status.PARTIAL not in TERMINAL


@pytest.mark.parametrize(
    "src,dst,ok",
    [
        (Status.RECEIVED, Status.PARSING, True),
        (Status.PARSING, Status.PARSE_ERROR, True),
        (Status.PARSING, Status.INSTRUCTION_READY, True),
        (Status.INSTRUCTION_READY, Status.SUBMITTING, True),
        (Status.SUBMITTING, Status.PENDING, True),
        (Status.SUBMITTING, Status.SUBMIT_FAILED, True),
        (Status.SUBMITTING, Status.SKIPPED, True),
        (Status.PENDING, Status.PARTIAL, True),
        (Status.PENDING, Status.FILLED, True),
        (Status.PENDING, Status.CANCELLED, True),
        (Status.PENDING, Status.REJECTED, True),
        (Status.PARTIAL, Status.PARTIAL, True),
        (Status.PARTIAL, Status.FILLED, True),
        (Status.PARTIAL, Status.CANCELLED, True),
        # 非法转换
        (Status.FILLED, Status.PENDING, False),
        (Status.PARSE_ERROR, Status.PARSING, False),
        (Status.RECEIVED, Status.FILLED, False),
        (Status.CANCELLED, Status.FILLED, False),
    ],
)
def test_transition_rules(src, dst, ok):
    assert can_transition(src, dst) is ok


def test_next_status_raises_on_invalid():
    with pytest.raises(ValueError, match="illegal transition"):
        next_status(Status.FILLED, Status.PENDING)


def test_next_status_returns_target_on_valid():
    assert next_status(Status.PENDING, Status.PARTIAL) == Status.PARTIAL
```

- [ ] **Step 2: 跑失败**

```bash
cd backend && uv run pytest tests/domain/test_status.py -v
```

Expected: ModuleNotFoundError。

- [ ] **Step 3: 实现**

Create: `backend/app/domain/status.py`

```python
"""Status 状态机 —— Task 生命周期，合法转换显式列表维护。"""
from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    RECEIVED = "RECEIVED"
    PARSING = "PARSING"
    PARSE_ERROR = "PARSE_ERROR"
    INSTRUCTION_READY = "INSTRUCTION_READY"
    SUBMITTING = "SUBMITTING"
    SUBMIT_FAILED = "SUBMIT_FAILED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


TERMINAL: frozenset[Status] = frozenset(
    {
        Status.PARSE_ERROR,
        Status.SUBMIT_FAILED,
        Status.FILLED,
        Status.CANCELLED,
        Status.REJECTED,
        Status.SKIPPED,
    }
)


# 合法转换表：src -> 允许的 dst 集合
_ALLOWED: dict[Status, frozenset[Status]] = {
    Status.RECEIVED: frozenset({Status.PARSING}),
    Status.PARSING: frozenset({Status.PARSE_ERROR, Status.INSTRUCTION_READY}),
    Status.INSTRUCTION_READY: frozenset({Status.SUBMITTING, Status.SKIPPED}),
    Status.SUBMITTING: frozenset({Status.PENDING, Status.SUBMIT_FAILED, Status.SKIPPED}),
    Status.PENDING: frozenset(
        {Status.PARTIAL, Status.FILLED, Status.CANCELLED, Status.REJECTED}
    ),
    Status.PARTIAL: frozenset({Status.PARTIAL, Status.FILLED, Status.CANCELLED}),
    # 终态不可转出
    Status.PARSE_ERROR: frozenset(),
    Status.SUBMIT_FAILED: frozenset(),
    Status.FILLED: frozenset(),
    Status.CANCELLED: frozenset(),
    Status.REJECTED: frozenset(),
    Status.SKIPPED: frozenset(),
}


def can_transition(src: Status, dst: Status) -> bool:
    return dst in _ALLOWED.get(src, frozenset())


def next_status(src: Status, dst: Status) -> Status:
    if not can_transition(src, dst):
        raise ValueError(f"illegal transition: {src} -> {dst}")
    return dst
```

- [ ] **Step 4: 跑通过**

```bash
cd backend && uv run pytest tests/domain/test_status.py -v
```

Expected: 全通过（包含参数化 18 条 + 4 条其他）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/status.py backend/tests/domain/test_status.py
git commit -m "feat(domain): Status enum + 状态机合法转换表"
```

---

### Task 8: PushEvent + PushState

**Files:**
- Create: `backend/app/domain/push_event.py`
- Create: `backend/tests/domain/test_push_event.py`

- [ ] **Step 1: 写失败测试**

Create: `backend/tests/domain/test_push_event.py`

```python
from datetime import UTC, datetime

import pytest

from app.domain.push_event import PushEvent, PushState


def _make(**overrides):
    defaults = dict(
        id="evt-001",
        task_id="msg-abc-123",
        order_id="729308570398740480",
        state=PushState.NEW,
        received_at=datetime(2026, 4, 25, 10, 42, 15, 498_000, tzinfo=UTC),
        payload={"raw": "..."},
        delta_qty=None,
        delta_price=None,
        cumulative_qty=None,
        cumulative_avg_price=None,
        note=None,
    )
    defaults.update(overrides)
    return PushEvent(**defaults)


def test_push_event_frozen():
    e = _make()
    with pytest.raises(Exception):
        e.state = PushState.FILLED


def test_push_event_equal_by_id():
    a = _make()
    b = _make(payload={"other": "data"})
    assert a == b


def test_push_state_values():
    assert PushState.NEW.value == "NEW"
    assert PushState.PARTIAL.value == "PARTIAL"
    assert PushState.FILLED.value == "FILLED"


def test_partial_fill_carries_deltas():
    e = _make(
        state=PushState.PARTIAL,
        delta_qty=100,
        delta_price=26.47,
        cumulative_qty=100,
        cumulative_avg_price=26.47,
    )
    assert e.delta_qty == 100
    assert e.cumulative_avg_price == 26.47
```

- [ ] **Step 2: 失败 → 实现 → 通过**

```bash
cd backend && uv run pytest tests/domain/test_push_event.py -v
```

Expected: ModuleNotFoundError。

Create: `backend/app/domain/push_event.py`

```python
"""PushEvent —— 来自 broker 的订单推送事件流式记录。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PushState(str, Enum):
    NEW = "NEW"
    SUBMITTED = "SUBMITTED"
    MODIFIED = "MODIFIED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PushEvent:
    id: str
    task_id: str
    order_id: str
    state: PushState
    received_at: datetime
    payload: dict
    delta_qty: int | None = None
    delta_price: float | None = None
    cumulative_qty: int | None = None
    cumulative_avg_price: float | None = None
    note: str | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PushEvent):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
```

- [ ] **Step 3: 跑通过**

```bash
cd backend && uv run pytest tests/domain/test_push_event.py -v
```

Expected: 4 passed。

- [ ] **Step 4: Commit**

```bash
git add backend/app/domain/push_event.py backend/tests/domain/test_push_event.py
git commit -m "feat(domain): PushEvent + PushState enum"
```

---

### Task 9: Task 聚合根

**Files:**
- Create: `backend/app/domain/task.py`
- Create: `backend/tests/domain/test_task.py`

- [ ] **Step 1: 写失败测试**

Create: `backend/tests/domain/test_task.py`

```python
from datetime import UTC, datetime

import pytest

from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task


def _msg(id_: str = "msg-123") -> Message:
    return Message(
        id=id_,
        content="TSLL 26.5 加一半",
        raw_content="TSLL 26.5 加一半",
        author="big-elephant",
        posted_at=datetime(2026, 4, 25, 10, 42, 15, tzinfo=UTC),
        received_at=datetime(2026, 4, 25, 10, 42, 15, 82_000, tzinfo=UTC),
        source="stock",
    )


def _inst() -> StockInstruction:
    return StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.50,
        price_range=None,
        quantity=500,
        position_size=None,
        stop_loss_price=25.80,
        take_profit_price=None,
        context_source="group",
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )


def test_task_id_equals_message_id():
    t = Task.new_from_message(_msg("msg-xyz"))
    assert t.id == "msg-xyz"


def test_task_starts_at_received():
    t = Task.new_from_message(_msg())
    assert t.status == Status.RECEIVED


def test_task_mark_parsing_transitions_status():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    assert t.status == Status.PARSING


def test_task_attach_instruction_sets_ready():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    t.attach_instruction(_inst())
    assert t.status == Status.INSTRUCTION_READY
    assert t.type == "stock"
    assert t.instruction is not None


def test_task_mark_parse_failed_terminal():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    t.mark_parse_failed("无法推断 ticker")
    assert t.status == Status.PARSE_ERROR
    assert t.reject_reason == "无法推断 ticker"


def test_task_append_push_event_sorted():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    t.attach_instruction(_inst())
    t.mark_submitting()
    t.mark_submitted(order_id="ord-1", timing_ms=412)
    t.append_push_event(_pe(state=PushState.NEW, order_id="ord-1"))
    t.append_push_event(_pe(state=PushState.PARTIAL, order_id="ord-1", delta_qty=100))
    assert len(t.push_events) == 2
    assert t.status == Status.PARTIAL


def test_task_illegal_status_jump_raises():
    t = Task.new_from_message(_msg())
    with pytest.raises(ValueError, match="illegal transition"):
        t.mark_submitting()  # RECEIVED → SUBMITTING 非法


def _pe(*, state: PushState, order_id: str, delta_qty: int | None = None) -> PushEvent:
    return PushEvent(
        id=f"evt-{state.value}",
        task_id="msg-123",
        order_id=order_id,
        state=state,
        received_at=datetime(2026, 4, 25, 10, 42, 15, 500_000, tzinfo=UTC),
        payload={},
        delta_qty=delta_qty,
    )
```

- [ ] **Step 2: 跑失败**

```bash
cd backend && uv run pytest tests/domain/test_task.py -v
```

- [ ] **Step 3: 实现**

Create: `backend/app/domain/task.py`

```python
"""Task 聚合根 —— 一条消息 → 一个 Task，贯穿整个处理生命周期。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from .instruction import Instruction, OptionInstruction, StockInstruction
from .message import Message
from .push_event import PushEvent, PushState
from .status import Status, next_status


# PushState → Status 映射
_PUSH_TO_STATUS: dict[PushState, Status] = {
    PushState.NEW: Status.PENDING,
    PushState.SUBMITTED: Status.PENDING,
    PushState.MODIFIED: Status.PENDING,
    PushState.PARTIAL: Status.PARTIAL,
    PushState.FILLED: Status.FILLED,
    PushState.CANCELLED: Status.CANCELLED,
    PushState.REJECTED: Status.REJECTED,
    PushState.FAILED: Status.REJECTED,
}


@dataclass
class Task:
    id: str
    type: Literal["stock", "option", "unknown"]
    status: Status
    message: Message
    instruction: Instruction | None = None
    order_id: str | None = None
    push_events: list[PushEvent] = field(default_factory=list)
    stage_timings: dict[str, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    reject_reason: str | None = None

    @classmethod
    def new_from_message(cls, msg: Message) -> "Task":
        now = datetime.now(UTC)
        return cls(
            id=msg.id,
            type="unknown",
            status=Status.RECEIVED,
            message=msg,
            created_at=now,
            updated_at=now,
        )

    def _transition(self, dst: Status) -> None:
        self.status = next_status(self.status, dst)
        self.updated_at = datetime.now(UTC)

    def mark_parsing(self) -> None:
        self._transition(Status.PARSING)

    def mark_parse_failed(self, reason: str) -> None:
        self.reject_reason = reason
        self._transition(Status.PARSE_ERROR)

    def attach_instruction(self, inst: Instruction) -> None:
        self.instruction = inst
        self.type = "option" if isinstance(inst, OptionInstruction) else "stock" if isinstance(inst, StockInstruction) else "unknown"
        self._transition(Status.INSTRUCTION_READY)

    def mark_submitting(self) -> None:
        self._transition(Status.SUBMITTING)

    def mark_submitted(self, *, order_id: str, timing_ms: float) -> None:
        self.order_id = order_id
        self.stage_timings["submit"] = timing_ms
        self._transition(Status.PENDING)

    def mark_submit_failed(self, reason: str) -> None:
        self.reject_reason = reason
        self._transition(Status.SUBMIT_FAILED)

    def mark_skipped(self, reason: str) -> None:
        self.reject_reason = reason
        self._transition(Status.SKIPPED)

    def record_parse_timing(self, ms: float) -> None:
        self.stage_timings["parse"] = ms

    def append_push_event(self, evt: PushEvent) -> None:
        self.push_events.append(evt)
        new_status = _PUSH_TO_STATUS[evt.state]
        # PARTIAL → PARTIAL 允许（状态机中已标记）
        if self.status != new_status:
            self._transition(new_status)
        else:
            self.updated_at = datetime.now(UTC)
```

- [ ] **Step 4: 跑通过**

```bash
cd backend && uv run pytest tests/domain/ -v
```

Expected: 全部 domain 测试通过（约 20 条）。

- [ ] **Step 5: Commit**

```bash
git add backend/app/domain/task.py backend/tests/domain/test_task.py
git commit -m "feat(domain): Task 聚合根 + 生命周期方法"
```

---

> **Phase 1 完成检查点**：`cd backend && uv run pytest tests/domain/ -v` 全绿。下一步进入 Phase 2（持久化）。

---

## Phase 2-10 详细任务

因篇幅限制，Phase 2 及以后的任务拆分写在同一份 plan 文档的续篇。**后续 Phase 遵循相同的 TDD 模式**：

- 每个文件对应一个 Task
- 每个 Task 5 步：写失败测试 → 跑失败 → 实现 → 跑通过 → commit
- 关键类型、方法名、测试 fixture 都必须写全（无 TBD）

**Phase 2 (Storage) task 概要：**
- Task 10: `storage/db.py` engine/session + in-memory SQLite fixture
- Task 11: `storage/schema.py` ORM 表定义
- Task 12: `storage/repo.py` save/load Task + Message + PushEvent
- Task 13: Alembic init + 第一个迁移
- Task 14: `storage/listeners.py` 订阅 event_bus 自动落盘

**Phase 3 (Event Bus):**
- Task 15: `core/event_bus.py` asyncio pub/sub + 订阅者独立 queue
- Task 16: event_bus 单测（fan-out、back-pressure、failure isolation）

**Phase 4 (Parser):**
- Task 17: `parser/stock_parser.py`（从老 `parser/stock_parser.py` 迁移，保留测试用例）
- Task 18: `parser/option_parser.py`
- Task 19: `parser/context_resolver.py`（查 storage.repo 获取上下文）
- Task 20: `parser/service.py` 订阅 `message.received` → 发 `task.instruction_ready` / `task.parse_failed`
- Task 21: Snapshot 测试：对 `data/stock_parsed_message.json` 跑新解析器，对比老 `main` 分支输出

**Phase 5 (Broker):**
- Task 22: `broker/longport_client.py` SDK 薄封装 + 可注入 mock
- Task 23: `broker/trader.py` Instruction → submit_order
- Task 24: `broker/push_listener.py` 订阅长桥 push → 发 `task.push_event`
- Task 25: `broker/status_updater.py` PushEvent → Task.status（已在 domain 内做，这里只做编排）
- Task 26: Mock SDK 回放测试（完整生命周期 NEW→SUBMITTED→PARTIAL→FILLED）

**Phase 6 (Whop listener):**
- Task 27: `whop/login.py` cookie 加载 + 登录兜底
- Task 28: `whop/browser.py` Playwright Context 封装
- Task 29: `whop/extractor.py` DOM → Message（用 `tmp/stock/page_html.html` 做离线测试）
- Task 30: `whop/listener.py` 轮询循环 + 去重 + 发 `message.received`

**Phase 7 (API):**
- Task 31: `api/auth.py` APP_TOKEN 依赖
- Task 32: `api/schemas.py` Pydantic 出入参
- Task 33: `api/http.py` 6 个 REST 端点
- Task 34: `api/ws.py` WebSocket hub + event_id ring buffer
- Task 35: event_bus → WS 桥接
- Task 36: 端到端 API 测试（httpx.AsyncClient + 模拟 ws 客户端）

**Phase 8 (Frontend 脚手架):**
- Task 37: `styles/tokens.css` design system 变量（按 spec §9）
- Task 38: `styles/fonts.css` IBM Plex 引入
- Task 39: `api/types.ts` 首次运行 `npm run gen:types`（需要后端 Phase 7 跑起来）
- Task 40: `api/http.ts` fetch 封装
- Task 41: App shell（TopBar 占位 + 空 layout）

**Phase 9 (Frontend 组件):**
- Task 42: `stores/conn.ts` 连接状态
- Task 43: `api/ws.ts` 客户端 + 重连 + `?since=` 续传
- Task 44: `stores/tasks.ts` Task 列表 + 增量追加 push event
- Task 45: `components/common/TypeBadge.tsx`
- Task 46: `components/common/StatusPill.tsx`（含脉冲）
- Task 47: `components/Card/CardCompact.tsx`
- Task 48: `components/Card/OrderSubmit.tsx`
- Task 49: `components/Card/PushChain.tsx`
- Task 50: `components/Card/PushDetail.tsx`
- Task 51: `components/Card/CardExpanded.tsx`
- Task 52: `components/Card/Card.tsx` 外壳 + compact/expanded 切换
- Task 53: `components/TopBar.tsx`
- Task 54: `components/RightRail.tsx` + `useStickyTop` hook
- Task 55: `App.tsx` 智能模式（PENDING / 最近 30s FILLED 自动展开）

**Phase 10 (E2E + 发布):**
- Task 56: 集成测试：假 whop（静态 HTML fixture）+ 假 longport（scripted push 序列）端到端跑通
- Task 57: 对照 spec §11 验收标准逐条 check
- Task 58: `frontend/npm run build` + FastAPI `StaticFiles` 挂载
- Task 59: `README.md` 完整版（截图、快速开始、架构图、常用命令）
- Task 60: 在 Mac 本机完整冒烟：从 `make db-migrate` 到浏览器打开 dashboard

---

## Self-Review Checklist

- [x] Spec §2 每项决策已在对应 Phase 实现（FastAPI=Phase 0/7，React+TS=Phase 3/8/9，SQLite+SQLAlchemy=Phase 2，worktree=Task 1）
- [x] Spec §3 每个模块都有对应 Phase（core/domain/storage/parser/broker/whop/api → Phase 0-7）
- [x] Spec §4 所有领域模型在 Phase 1 全覆盖
- [x] Spec §5 事件清单在 Phase 3/4/5/7 中分别订阅/发布
- [x] Spec §6 数据库 Schema 在 Phase 2 Task 11 实现
- [x] Spec §7 API 合约在 Phase 7 实现（含 `?since=` 续传在 Task 34）
- [x] Spec §9 Design System 在 Phase 8 Task 37 翻译为 tokens.css
- [x] Spec §11 验收项在 Phase 10 Task 57 逐条 check
- [x] 无 "TBD" / "implement later" / "add error handling"；Phase 2+ 任务采用"概要 + 文件粒度"而不是 fake 占位，需要 executing-plans skill 实际执行时再展开（注：这是**已知的权衡**，执行阶段用 TDD skill 和 subagent 展开细节）
- [x] 类型名一致性：`Task.id=str`、`Status` 成员名、`PushState` 成员名跨任务一致

**Known trade-off:** Phase 2-10 的任务以文件粒度列出而非完全展开每步（完全展开会超过 3000 行）。执行时需要配合 `superpowers:test-driven-development` 和 `superpowers:subagent-driven-development`，由 subagent 按 Phase 1 的 TDD 模式展开实现。关键的类型/签名/状态机/事件名都已在 Phase 1 和 spec 中定死。

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-25-signal-station-implementation.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** - 我为每个 Task 派一个 subagent，Task 之间做 review，速度快
2. **Inline Execution** - 在当前会话里按 executing-plans 分批执行，带 checkpoint

Which approach?
