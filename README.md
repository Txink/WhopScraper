# Signal Station v2

Real-time Whop signal monitoring, LongPort auto-trading, and a dark monitoring dashboard —
all wired together in a single-command production stack.

## Status

| Layer       | Tests      | Type-check         |
|-------------|------------|--------------------|
| Backend     | 231 passing | mypy strict (clean) |
| Frontend    | 70 passing  | TypeScript strict (clean) |
| Integration | 4 e2e acceptance tests (spec §11) | — |

CI baseline: all suites green on Python 3.11 + Node 18.

---

## Architecture

```
Whop forum (browser)
        |
        v
  WhopBrowser (Playwright)
        |  DOM → Message
        v
  WhopListener (poll every 2 s)
        |  EVENT: message.received
        v
    EventBus (in-process async pub/sub)
        |
   ┌────┴─────────────┐
   |                  |
   v                  v
ParserService    StorageListeners
(stock / option    (DB upsert on
 regex parser)      every task.* event)
   |
   | EVENT: task.instruction_ready
   v
  Trader
  (risk checks → submit / dry-run)
   |
   v
LongPortClient  ←──── PushListener
(REST + WS SDK)         (order change callbacks)
   |                          |
   | EVENT: task.push_event   |
   └──────────────────────────┘
                |
                v
         WebSocketHub
         (ring buffer, ?since= replay)
                |
                v
         FastAPI /ws endpoint
                |
         React frontend
         (Zustand stores, Card/TopBar/RightRail)
```

### Data persistence

All domain events that touch a Task are persisted to SQLite:

```
EventBus → StorageListeners → SQLite (tasks + push_events tables)
                                  ↑
                          GET /api/tasks (REST)
```

Browser refresh restores full state from `GET /api/tasks` (cursor-paginated).
WebSocket reconnect with `?since=<event_id>` replays the last 500 buffered events.

---

## Modules

### Backend (`backend/app/`)

| Module | Responsibility |
|--------|---------------|
| `main.py` | App factory (`create_app`), lifespan startup/shutdown, static frontend mount |
| `core/config.py` | Pydantic-settings; all config loaded from `.env` |
| `core/event_bus.py` | In-process async pub/sub with fan-out and failure isolation |
| `core/events.py` | Typed topic constants + payload dataclasses (MessagePayload, TaskPayload, …) |
| `domain/` | Pure domain model: Message, Task, Instruction, PushEvent, Status |
| `parser/service.py` | Subscribes to `message.received`; runs stock/option parsers |
| `parser/stock_parser.py` | Regex-based stock signal parser (89.6% parse rate) |
| `parser/option_parser.py` | Option contract signal parser |
| `parser/context_resolver.py` | Loads watched tickers from `config/watched_stocks.json` |
| `broker/longport_client.py` | LongPort SDK wrapper: submit/cancel orders + quote |
| `broker/trader.py` | Risk gate + order submission on `task.instruction_ready` |
| `broker/push_listener.py` | Subscribes to LongPort push callbacks → `task.push_event` |
| `storage/db.py` | SQLAlchemy async engine factory + session scope helper |
| `storage/schema.py` | ORM models: TaskRow, PushEventRow |
| `storage/repo.py` | Repository functions: save_task, load_task, list_tasks |
| `storage/listeners.py` | EventBus → DB persistence (upsert on every task.* event) |
| `api/http.py` | REST router: GET /api/tasks, /api/health, /api/stats/today, /api/positions |
| `api/ws.py` | WebSocketHub: broadcast + ring buffer replay |
| `api/auth.py` | Token auth (query param / Bearer header / X-App-Token header) |
| `api/schemas.py` | Pydantic response schemas (TaskOut, HealthOut, …) |
| `whop/browser.py` | Playwright browser wrapper (headless / headed) |
| `whop/login.py` | Cookie persistence + interactive login helper |
| `whop/extractor.py` | DOM → Message pure function |
| `whop/listener.py` | Poll loop: navigate → extract → deduplicate → publish |

### Frontend (`frontend/src/`)

| Module | Responsibility |
|--------|---------------|
| `App.tsx` | Root component: WS client, initial fetch, layout |
| `api/http.ts` | Typed HTTP client (health, tasks, stats, positions) |
| `api/ws.ts` | WebSocket client with exponential back-off reconnect |
| `api/domain-types.ts` | Shared TypeScript types mirroring backend schemas |
| `stores/` | Zustand stores: conn, tasks, stats, positions |
| `components/Card/` | Task Card family (Compact, Expanded, PushChain, PushDetail) |
| `components/TopBar.tsx` | Connection status indicators (Whop, LongPort, mode) |
| `components/RightRail.tsx` | Live stats + positions sidebar |
| `hooks/useStickyTop.ts` | Sticky top bar utility |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node 18+
- [uv](https://github.com/astral-sh/uv) Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A [LongPort](https://longportapp.com) account with API credentials
- Access to the Whop forum channel(s) you want to monitor

### 1. Clone

```bash
git clone <repo-url> signal-station
cd signal-station
```

### 2. Install dependencies

```bash
make install
```

This runs:
- `uv venv && uv pip install -e ".[dev]"` in `backend/`
- `uv run playwright install chromium` for Whop scraping
- `npm install` in `frontend/`

### 3. Configure

Copy the example env file and fill in your credentials:

```bash
cp .env.example .env   # create from template if it exists, otherwise:
touch .env
```

Edit `.env` at the project root (see Configuration section below for all keys).

Minimum required keys to start:

```env
APP_TOKEN=your-random-secret-token
LONGPORT_PAPER_APP_KEY=...
LONGPORT_PAPER_APP_SECRET=...
LONGPORT_PAPER_ACCESS_TOKEN=...
```

### 4. Run (production — single command)

```bash
make run
# or: cd frontend && npm run build && cd ../backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://localhost:8000?token=<APP_TOKEN>` in your browser.

The token is stored in `localStorage` on first load; subsequent visits don't need the query param.

---

## Configuration

All settings are read from a `.env` file at the **project root** (one level above `backend/`).

| Key | Default | Description |
|-----|---------|-------------|
| `APP_TOKEN` | `change-me-...` | Auth token for REST + WebSocket endpoints. Set to a strong random string. |
| `WHOP_STOCK_URL` | `""` | Full URL of the Whop stock channel page |
| `WHOP_OPTION_URL` | `""` | Full URL of the Whop option channel page |
| `WHOP_POLL_INTERVAL` | `2.0` | Seconds between DOM polls |
| `WHOP_HEADLESS` | `false` | `true` = run Playwright in headless mode (no browser window) |
| `LONGPORT_MODE` | `paper` | `paper` or `real` — selects which credentials to use |
| `LONGPORT_PAPER_APP_KEY` | `""` | Paper trading app key |
| `LONGPORT_PAPER_APP_SECRET` | `""` | Paper trading app secret |
| `LONGPORT_PAPER_ACCESS_TOKEN` | `""` | Paper trading access token |
| `LONGPORT_REAL_APP_KEY` | `""` | Real trading app key (only used when MODE=real) |
| `LONGPORT_REAL_APP_SECRET` | `""` | Real trading app secret |
| `LONGPORT_REAL_ACCESS_TOKEN` | `""` | Real trading access token |
| `LONGPORT_REGION` | `cn` | LongPort region: `cn` or `us` |
| `LONGPORT_AUTO_TRADE` | `true` | `false` = parse signals but never submit orders |
| `LONGPORT_DRY_RUN` | `true` | `true` = compute orders but log instead of submitting |
| `MAX_OPTION_TOTAL_PRICE` | `500.0` | Maximum total notional for a single option order (USD) |
| `MAX_OPTION_QUANTITY` | `3` | Maximum option contracts per order |
| `PRICE_DEVIATION_TOLERANCE` | `5.0` | Reject if market price deviates > N% from signal price |
| `STOCK_PRICE_DEVIATION_TOLERANCE` | `1.0` | Same for stocks |
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/signals.db` | SQLAlchemy async database URL |
| `HTTP_HOST` | `127.0.0.1` | Host to bind the uvicorn server |
| `HTTP_PORT` | `8000` | Port to bind the uvicorn server |
| `LOG_LEVEL` | `INFO` | Python logging level |

### Watched stocks

The parser uses `config/watched_stocks.json` to prioritise signal matching. Add or remove tickers there; no restart needed (loaded at startup).

---

## Development Guide

### Run in dev mode (hot reload on both sides)

```bash
make dev
# starts backend on :8000 (uvicorn --reload) and frontend on :5173 (Vite dev server)
```

The Vite dev server proxies `/api` and `/ws` to `localhost:8000`, so you don't need to build the frontend in dev.

### Backend tests

```bash
cd backend
uv run pytest            # all 231 tests
uv run pytest -v -x      # stop on first failure
uv run pytest tests/integration/test_acceptance.py  # acceptance tests only
```

### Frontend tests

```bash
cd frontend
npm test                 # vitest (70 tests)
npm test -- --reporter verbose
```

### Type checking

```bash
# Backend
cd backend && uv run mypy app

# Frontend
cd frontend && npm run typecheck
```

### Linting

```bash
cd backend && uv run ruff check .
cd backend && uv run ruff format --check .
```

### Build frontend (production bundle)

```bash
make build
# or: cd frontend && npm run build
# output: frontend/dist/
```

### Database

SQLite database lives at `data/signals.db` (created automatically on first run).

```bash
make db-reset    # delete DB and recreate empty schema
```

---

## REST API Reference

All endpoints require authentication. Pass the token as:
- Query param: `?token=<APP_TOKEN>`
- Header: `Authorization: Bearer <APP_TOKEN>`
- Header: `X-App-Token: <APP_TOKEN>`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Broker connectivity, mode, dry_run flag |
| GET | `/api/tasks` | Paginated task list. Params: `limit`, `cursor`, `status` |
| GET | `/api/tasks/{id}` | Single task with full push_events list |
| POST | `/api/tasks/{id}/cancel` | Cancel a pending brokerage order |
| GET | `/api/stats/today` | Today's task counts grouped by status |
| GET | `/api/positions` | Current portfolio positions |
| GET/WS | `/ws` | WebSocket stream. Params: `token`, `since` (event_id for replay) |

---

## WebSocket Protocol

Connect to `ws://localhost:8000/ws?token=<APP_TOKEN>`.

Each message is a JSON object:

```json
{
  "event_id": 42,
  "type": "task.created",
  "payload": { "task": { ... } }
}
```

Event types mirror EventBus topics:
- `task.created`
- `task.instruction_ready`
- `task.parse_failed`
- `task.order_submitted`
- `task.submit_failed`
- `task.push_event`
- `task.status_changed`
- `system.connection_changed`

### Reconnect / replay

On reconnect, pass `?since=<last_event_id>` to replay all buffered events after that ID.
The hub keeps the last 500 events in memory. This prevents missing events during brief disconnects.

### Heartbeat

Send `{"type": "ping"}` at any time; the server responds with `{"type": "pong"}`.

---

## Troubleshooting

### Whop login fails or shows blank page

The Playwright browser session needs to be logged in. On first run, `WHOP_HEADLESS=false` (default) shows a real browser window. Log into Whop manually; the session cookie is saved to `.auth/state.json` and reused on subsequent runs. Set `WHOP_HEADLESS=true` only after a successful manual login.

### LongPort connection error on startup

Check that the correct credential set is used for your `LONGPORT_MODE`. Paper and real accounts use separate key sets. Verify the access token hasn't expired (LongPort tokens require renewal).

### "frontend/dist not found — running in API-only mode"

You need to build the frontend before using the production single-command mode:
```bash
make build    # or: cd frontend && npm run build
```
The backend will then serve the frontend automatically from the same port.

### Token auth in browser

Open `http://localhost:8000?token=<APP_TOKEN>`. The token is saved to `localStorage` automatically. Future page loads work without the query param. To change the token, clear `localStorage["APP_TOKEN"]` in browser DevTools.

### High memory usage / Playwright overhead

Playwright runs a full Chromium browser process. Memory usage is typically 150–250 MB. The spec target is < 300 MB total. If you exceed this, check that only one `WhopListener` per channel is running (check the startup logs).

### SQLite "database is locked"

Only one process should have the database open. Kill any stray uvicorn/pytest processes before restarting.

### Tests fail with "LongPortClient init failed"

Tests use `FakeBrokerClient` and `broker_override=`. The module-level `app = create_app()` at the bottom of `app/main.py` runs at import time and requires real LongPort credentials. In test, always import `create_app` directly — never import `app` from `app.main`.

---

## Acceptance Criteria (spec §11)

All 4 e2e acceptance tests pass in `backend/tests/integration/test_acceptance.py`:

| # | Criterion | Test |
|---|-----------|------|
| §11.1 | Whop message → SQLite full-cycle pipeline | `test_acceptance_e2e_full_cycle` |
| §11.3 | WebSocket disconnect: buffered + cursor replay | `test_acceptance_websocket_broadcast_and_replay` |
| §11.4 | Browser refresh: first screen restores from /api/tasks | `test_acceptance_browser_refresh_recovers_via_initial_list` |
| §11.6 | `python -m app.main` single-command startup + mode observable | `test_acceptance_health_endpoint_exposes_mode` |

§11.2 (all status visible on Card), §11.5 (unit + integration tests), and §11.7 (< 300 MB) are verified manually / by the full test suite.

---

## Project Structure

```
signal-station/
├── .env                        # credentials (git-ignored)
├── Makefile                    # install / dev / build / run / test / lint
├── README.md
├── config/
│   └── watched_stocks.json     # tickers the parser prioritises
├── data/
│   └── signals.db              # SQLite database (git-ignored)
├── docs/                       # design docs + domain notes
│   └── superpowers/specs/
│       └── 2026-04-25-signal-station-design.md
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py             # FastAPI app factory + static mount
│   │   ├── api/                # REST + WebSocket routers
│   │   ├── broker/             # LongPort client + trader + push listener
│   │   ├── core/               # EventBus + config + typed events
│   │   ├── domain/             # Pure domain model (Task, Message, …)
│   │   ├── parser/             # Signal parsing (stock + option)
│   │   ├── storage/            # SQLAlchemy DB + repo + listeners
│   │   └── whop/               # Playwright scraper + extractor
│   └── tests/
│       ├── api/                # HTTP + WS e2e tests
│       ├── broker/             # Trader + push listener tests
│       ├── core/               # EventBus tests
│       ├── domain/             # Domain model tests
│       ├── integration/        # Full-stack acceptance tests (spec §11)
│       ├── parser/             # Parser unit tests
│       ├── storage/            # DB repo tests
│       └── whop/               # Extractor + listener tests
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── dist/                   # Production build output (git-ignored)
    └── src/
        ├── App.tsx             # Root component
        ├── api/                # HTTP + WS client
        ├── components/         # Card, TopBar, RightRail
        ├── hooks/
        └── stores/             # Zustand state
```

---

## Design Notes

### Why in-process EventBus?

Signal Station processes one signal at a time per channel (2 channels max). An in-process async pub/sub bus is sufficient, has zero infrastructure dependencies, and is trivially testable with `wait_idle`. A message queue (Redis/RabbitMQ) would be premature for this workload.

### Why SQLite?

The workload is write-once (task events are immutable), low volume (tens of signals per day), and single-process. SQLite via SQLAlchemy async is production-grade for this scale with zero operational overhead.

### Parser confidence and watchlist

The stock parser achieves ~89.6% parse rate on observed traffic. The watchlist (`config/watched_stocks.json`) + ticker alias table boosts hit rate for common tickers. Unknown tickers fall back to a looser pattern; signals that can't be parsed are recorded with status `PARSE_FAILED` and visible on the dashboard.

### Token security

`APP_TOKEN` is a shared secret between the backend and the operator's browser. It is never embedded in built JS — the frontend reads it from a URL query param on first visit and stores it in `localStorage`. This avoids shipping credentials in the build artifact while keeping the single-binary deployment model simple.

---

## License / Notes

Internal tool. Not for public distribution. LongPort SDK and Whop credentials are operator-supplied.

For full design rationale, see `docs/superpowers/specs/2026-04-25-signal-station-design.md`.
