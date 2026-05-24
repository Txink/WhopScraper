# Trading Panel + Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual trading panel (submit / modify / cancel orders, LongPort `replace_order` preserves queue priority) and a backend-driven alerts subsystem (price / pct-change / volume) under a swipeable 3-tab container in the stock detail page.

**Architecture:** Reuse `tasks` table for manual orders (new `source` + `last_replaced_at` columns); new `alerts/` package owns engine + repo + service subscribing to LongPort quote pushes; frontend gets a swipe-tab container replacing the current TradeList slot. WebSocket gets 3 new event topics. NoopBroker stays the no-LongPort fallback.

**Tech Stack:** FastAPI, SQLAlchemy 2.x async, Alembic, LongPort Python SDK, React 18, Zustand, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-05-24-trading-panel-and-alerts-design.md`
**Mockup:** `.design/trading-panel-and-alerts.html`

---

## File Plan

### Backend — created

- `backend/alembic/versions/<rev>_alerts_and_manual_orders.py` — single migration
- `backend/app/orders/__init__.py`
- `backend/app/orders/service.py` — submit / replace / cancel / list_today
- `backend/app/orders/schemas.py` — request/response Pydantic
- `backend/app/alerts/__init__.py`
- `backend/app/alerts/repo.py` — alerts + alert_events CRUD
- `backend/app/alerts/engine.py` — quote subscriber + evaluator
- `backend/app/alerts/service.py` — CRUD wrapper + engine notification
- `backend/app/alerts/schemas.py`
- `backend/app/alerts/conditions.py` — pure evaluation functions
- `backend/tests/orders/test_service.py`
- `backend/tests/orders/test_api.py`
- `backend/tests/alerts/test_repo.py`
- `backend/tests/alerts/test_conditions.py`
- `backend/tests/alerts/test_engine.py`
- `backend/tests/alerts/test_service.py`
- `backend/tests/alerts/test_api.py`
- `backend/tests/integration/test_acceptance_manual_order.py`
- `backend/tests/integration/test_acceptance_alerts.py`

### Backend — modified

- `backend/app/storage/schema.py` — add `tasks.source`, `tasks.last_replaced_at`; add `AlertRow`, `AlertEventRow`
- `backend/app/broker/broker_client.py` — add `replace_order`, `today_orders` to Protocol
- `backend/app/broker/longport_client.py` — implement both
- `backend/app/broker/noop_client.py` — stub both
- `backend/app/core/events.py` — add `ORDER_CHANGED`, `ALERT_TRIGGERED`, `ALERT_CHANGED`
- `backend/app/api/http.py` — mount `/api/orders/*` + `/api/alerts/*` routers
- `backend/app/api/schemas.py` — add Out schemas
- `backend/app/api/ws.py` — forward new topics; include in ring buffer
- `backend/app/main.py` — lifespan starts AlertEngine

### Frontend — created

- `frontend/src/api/orders.ts` (typed client helpers)
- `frontend/src/api/alerts.ts`
- `frontend/src/stores/orders.ts`
- `frontend/src/stores/alerts.ts`
- `frontend/src/stores/alertNotifications.ts`
- `frontend/src/components/Positions/DetailTabSwipe.tsx` + `.css`
- `frontend/src/components/Positions/DetailTabFooter.tsx`
- `frontend/src/components/Positions/TradingPanel/TradingPanel.tsx` + `.css`
- `frontend/src/components/Positions/TradingPanel/ActiveOrdersTable.tsx`
- `frontend/src/components/Positions/TradingPanel/QuickOrderRow.tsx`
- `frontend/src/components/Positions/TradingPanel/FullOrderModal.tsx`
- `frontend/src/components/Positions/TradingPanel/ReplaceOrderPopover.tsx`
- `frontend/src/components/Positions/AlertsPanel/AlertsPanel.tsx` + `.css`
- `frontend/src/components/Positions/AlertsPanel/AlertModal.tsx`
- `frontend/src/components/AlertNotifications/AlertBell.tsx` + `.css`
- `frontend/src/components/AlertNotifications/AlertToastStack.tsx`
- Vitest sibling files for each above

### Frontend — modified

- `frontend/src/components/Positions/DetailPane.tsx` — swap TradeList for DetailTabSwipe with 3 tab children
- `frontend/src/components/TopBar.tsx` — mount `<AlertBell />`
- `frontend/src/App.tsx` — mount `<AlertToastStack />`
- `frontend/src/api/ws.ts` — dispatch 3 new topics into stores
- `frontend/src/stores/detailView.ts` — add `tabIndex` field
- `frontend/openapi.json` + `frontend/src/api/types.ts` — regenerated after backend schema changes

---

## Task Index

1. Schema + migration (tasks columns, alerts, alert_events)
2. `replace_order` + `today_orders` on BrokerClient / LongPort / Noop
3. Orders service + API + WS `order.changed`
4. Alerts: condition pure evaluators
5. Alerts: repo
6. Alerts: engine
7. Alerts: service + API + WS topics + lifespan wiring
8. Frontend stores + WS dispatch
9. DetailTabSwipe + footer + integrate with DetailPane
10. TradingPanel + ActiveOrdersTable + QuickOrderRow + Replace popover + FullOrder modal
11. AlertsPanel + AlertModal
12. AlertBell + AlertToastStack
13. Acceptance e2e

Each task is implemented TDD-style with frequent commits. Detailed step-by-step instructions for each task follow in companion task files to keep this index readable:

- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/01-schema.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/02-broker.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/03-orders.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/04-alert-conditions.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/05-alert-repo.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/06-alert-engine.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/07-alert-service-api.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/08-frontend-stores.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/09-tab-swipe.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/10-trading-panel.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/11-alerts-panel.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/12-bell-toast.md`
- `docs/superpowers/plans/2026-05-25-trading-panel-and-alerts/13-acceptance.md`

Each task file is self-contained: file paths, exact test code, exact implementation code, commands, expected output, and a final commit message. Reading the index then the per-task file gives full context.

---

## Cross-task Invariants

These rules apply to every task; do not relax without spec amendment:

1. **TDD only**: red → green → commit. No "I'll add tests later".
2. **One commit per Step 5** in each task; conventional commit prefix matching repo style (`feat(...)`, `refactor(...)`, `test(...)`, etc.).
3. **No new `mypy --strict` or `ruff` errors** beyond the existing baseline (37 mypy / 218 ruff pre-existing on main as of 2026-05-25). Each task adds zero new violations in the files it touches.
4. **`tsc --noEmit` and `vitest` must stay green** after every frontend commit.
5. **No new dependencies** without explicit user approval. Reuse existing libraries (SQLAlchemy 2.x, Pydantic v2, Zustand, Chart.js).
6. **Manual orders never write rows to `messages` or `instructions`** — only `tasks`. Frontend gates instruction-only UI off `tasks.source != 'manual'`.
7. **Alert engine never blocks the event loop**: SDK callbacks marshal into asyncio via `loop.call_soon_threadsafe`. DB writes go through async session.
8. **NoopBroker is the only "no LongPort" runtime**: every new broker method ships a Noop implementation; alert engine starts but skips quote subscription when `is_noop`.
9. **No `alert` confirm UI bypasses confirm**: destructive actions (cancel order, delete alert, disable alert) require explicit two-step confirmation in the UI.
10. **`task.id` for manual orders**: prefix `man_` + uuid4 hex (24 chars). Distinct from whop domIDs which never start with `man_`.

---

## Pre-flight Checklist (run once before Task 1)

- [ ] On a clean branch (or inside the worktree just created via `superpowers:using-git-worktrees`)
- [ ] `cd backend && uv run pytest -q` is green (baseline)
- [ ] `cd frontend && npm test -- --run` is green (baseline)
- [ ] `make typecheck` is green
- [ ] Read the spec: `docs/superpowers/specs/2026-05-24-trading-panel-and-alerts-design.md`
- [ ] Open the mockup in a browser: `open .design/trading-panel-and-alerts.html`

---

## Self-Review

After each task: re-read the spec sections relevant to that task; verify the implementation matches the contract (endpoints, fields, status codes, WS topics). Discrepancies are fixed before commit, not deferred.
