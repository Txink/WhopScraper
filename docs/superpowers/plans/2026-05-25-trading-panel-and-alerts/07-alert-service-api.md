# Task 7: Alert Service + REST API + Lifespan wiring

**Files:**
- Create: `backend/app/alerts/service.py`
- Modify: `backend/app/api/http.py` — add `/api/alerts/*` routes
- Modify: `backend/app/main.py` — instantiate AlertEngine + AlertsService in lifespan
- Test: `backend/tests/alerts/test_service.py`, `test_api.py`

## Steps

- [ ] **Step 1: Failing service test**

`backend/tests/alerts/test_service.py`:

```python
"""AlertsService — CRUD wrapper that pre-validates symbol + notifies engine."""
from __future__ import annotations

import pytest

from app.alerts.schemas import AlertCreate, AlertUpdate
from app.alerts.service import AlertsService, SymbolUnknown


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def on_alert_changed(self, action, alert):
        self.calls.append((action, alert.id))


class GoodBroker:
    def get_quote(self, symbols): return {s: {"last_done": 100.0} for s in symbols}


class BadBroker:
    def get_quote(self, symbols): return {}


@pytest.mark.asyncio
async def test_create_validates_symbol(repo):
    svc = AlertsService(repo=repo, engine=FakeEngine(), broker=BadBroker())
    with pytest.raises(SymbolUnknown):
        await svc.create(AlertCreate(
            ticker="ZZZZ", symbol="ZZZZ.US", condition_type="price",
            operator=">=", threshold=1.0,
        ))


@pytest.mark.asyncio
async def test_create_notifies_engine(repo):
    eng = FakeEngine()
    svc = AlertsService(repo=repo, engine=eng, broker=GoodBroker())
    out = await svc.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    assert ("created", out.id) in eng.calls


@pytest.mark.asyncio
async def test_update_notifies_engine(repo):
    eng = FakeEngine()
    svc = AlertsService(repo=repo, engine=eng, broker=GoodBroker())
    a = await svc.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    await svc.update(a.id, AlertUpdate(threshold=205.0))
    assert ("updated", a.id) in eng.calls


@pytest.mark.asyncio
async def test_delete_notifies_engine(repo):
    eng = FakeEngine()
    svc = AlertsService(repo=repo, engine=eng, broker=GoodBroker())
    a = await svc.create(AlertCreate(
        ticker="AAPL", symbol="AAPL.US", condition_type="price",
        operator=">=", threshold=200.0,
    ))
    await svc.delete(a.id)
    assert ("deleted", a.id) in eng.calls
```

- [ ] **Step 2: Implement service**

`backend/app/alerts/service.py`:

```python
"""CRUD wrapper that pre-validates with the broker and notifies the
running AlertEngine after every change. Emits ALERT_CHANGED on the bus.
"""
from __future__ import annotations

from typing import Protocol

from app.alerts.repo import AlertRepo
from app.alerts.schemas import AlertCreate, AlertOut, AlertUpdate
from app.core.event_bus import EventBus
from app.core.events import Topic


class SymbolUnknown(ValueError):
    """Raised when broker.get_quote returns no entry for the symbol."""


class Engine(Protocol):
    async def on_alert_changed(self, action: str, alert: AlertOut) -> None: ...


class QuoteBroker(Protocol):
    def get_quote(self, symbols: list[str]) -> dict[str, dict]: ...


class AlertsService:
    def __init__(
        self,
        *,
        repo: AlertRepo,
        engine: Engine,
        broker: QuoteBroker,
        event_bus: EventBus | None = None,
    ) -> None:
        self._repo = repo
        self._engine = engine
        self._broker = broker
        self._bus = event_bus

    async def create(self, req: AlertCreate) -> AlertOut:
        try:
            quote = self._broker.get_quote([req.symbol])
        except Exception as e:
            raise SymbolUnknown(f"broker rejected symbol: {e}") from e
        if not quote or req.symbol not in quote:
            raise SymbolUnknown(f"unknown symbol: {req.symbol}")
        out = await self._repo.create(req)
        await self._engine.on_alert_changed("created", out)
        await self._publish("created", out)
        return out

    async def update(self, alert_id: int, req: AlertUpdate) -> AlertOut:
        before = await self._repo.get(alert_id)
        if before is None:
            raise KeyError(alert_id)
        after = await self._repo.update(alert_id, req)
        action = "toggled" if (req.enabled is not None and before.enabled != after.enabled) else "updated"
        await self._engine.on_alert_changed(action, after)
        await self._publish(action, after)
        return after

    async def delete(self, alert_id: int) -> None:
        existing = await self._repo.get(alert_id)
        if existing is None:
            return
        await self._repo.delete(alert_id)
        await self._engine.on_alert_changed("deleted", existing)
        await self._publish("deleted", existing)

    async def _publish(self, action: str, alert: AlertOut) -> None:
        if self._bus is None:
            return
        await self._bus.publish(
            Topic.ALERT_CHANGED,
            {"action": action, "alert": alert.model_dump(mode="json")},
        )
```

- [ ] **Step 3: Run + verify**

```bash
cd backend && uv run pytest tests/alerts/test_service.py -v
```

Expected: 4 pass.

- [ ] **Step 4: Add API routes**

Inside `build_http_router(...)` in `backend/app/api/http.py`, add the following block (after the orders block from Task 3):

```python
    from app.alerts.repo import AlertRepo
    from app.alerts.schemas import (
        AlertCreate, AlertEventListOut, AlertListOut, AlertOut, AlertUpdate,
    )
    from app.alerts.service import AlertsService, SymbolUnknown

    alerts_repo = AlertRepo(session_factory)
    # alerts_engine is created in main.py lifespan and stored on app.state;
    # FastAPI sees it via Depends if needed. Here we pull it lazily.
    def _alerts_service() -> AlertsService:
        engine = app.state.alerts_engine  # set in main.py
        return AlertsService(
            repo=alerts_repo, engine=engine, broker=broker, event_bus=event_bus
        )

    @router.get("/api/alerts", response_model=AlertListOut)
    async def get_alerts(ticker: str) -> AlertListOut:
        return AlertListOut(alerts=await alerts_repo.list_by_ticker(ticker))

    @router.post("/api/alerts", response_model=AlertOut, status_code=201)
    async def post_alert(req: AlertCreate) -> AlertOut:
        try:
            return await _alerts_service().create(req)
        except SymbolUnknown as e:
            raise HTTPException(422, str(e)) from e

    @router.patch("/api/alerts/{alert_id}", response_model=AlertOut)
    async def patch_alert(alert_id: int, req: AlertUpdate) -> AlertOut:
        try:
            return await _alerts_service().update(alert_id, req)
        except KeyError:
            raise HTTPException(404, f"alert {alert_id} not found")

    @router.delete("/api/alerts/{alert_id}", status_code=204)
    async def delete_alert(alert_id: int) -> Response:
        await _alerts_service().delete(alert_id)
        return Response(status_code=204)

    @router.get("/api/alerts/events", response_model=AlertEventListOut)
    async def get_alert_events(
        ticker: str | None = None, limit: int = 50,
    ) -> AlertEventListOut:
        return AlertEventListOut(events=await alerts_repo.list_events(ticker=ticker, limit=limit))
```

- [ ] **Step 5: Lifespan wiring**

In `backend/app/main.py` lifespan startup, after the broker is constructed and EventBus initialized, add:

```python
    from app.alerts.engine import AlertEngine
    from app.alerts.repo import AlertRepo
    alerts_repo = AlertRepo(session_factory)
    alerts_engine = AlertEngine(repo=alerts_repo, broker=broker, event_bus=event_bus)
    await alerts_engine.start()
    app.state.alerts_engine = alerts_engine
```

In shutdown:

```python
    if hasattr(app.state, "alerts_engine"):
        await app.state.alerts_engine.stop()
```

- [ ] **Step 6: Add WS broadcast for new topics**

Ensure `Topic.ALERT_TRIGGERED` and `Topic.ALERT_CHANGED` are forwarded to the WebSocketHub. The existing hub typically auto-forwards every `Topic` enum value via `event_bus.subscribe`. Verify by inspecting `backend/app/api/ws.py` `register_ws_listeners` (or equivalent); add subscriptions if absent.

- [ ] **Step 7: API test**

`backend/tests/alerts/test_api.py`:

```python
"""HTTP contract for /api/alerts/* — CRUD + 422 + 404."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_alert_happy(client: AsyncClient) -> None:
    r = await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    assert r.status_code == 201
    assert r.json()["enabled"] is True


@pytest.mark.asyncio
async def test_list_alerts_filtered_by_ticker(client: AsyncClient) -> None:
    await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    r = await client.get("/api/alerts?ticker=AAPL")
    assert r.status_code == 200
    assert len(r.json()["alerts"]) == 1


@pytest.mark.asyncio
async def test_patch_alert_toggle_disabled(client: AsyncClient) -> None:
    r1 = await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    alert_id = r1.json()["id"]
    r2 = await client.patch(f"/api/alerts/{alert_id}", json={"enabled": False})
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False


@pytest.mark.asyncio
async def test_delete_alert(client: AsyncClient) -> None:
    r1 = await client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    alert_id = r1.json()["id"]
    r2 = await client.delete(f"/api/alerts/{alert_id}")
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_create_alert_unknown_symbol_422(client_bad_quote: AsyncClient) -> None:
    r = await client_bad_quote.post("/api/alerts", json={
        "ticker": "ZZZZ", "symbol": "ZZZZ.US",
        "condition_type": "price", "operator": ">=", "threshold": 1.0,
    })
    assert r.status_code == 422
```

`client_bad_quote` is a fixture mounting the app with a broker whose `get_quote` returns `{}`.

- [ ] **Step 8: Run + verify all**

```bash
cd backend
uv run pytest tests/alerts -v
uv run mypy app
uv run ruff check .
```

Expected: all green.

- [ ] **Step 9: Regenerate OpenAPI types**

```bash
cd frontend && npm run gen:types
```

- [ ] **Step 10: Commit**

```bash
git add backend/app/alerts/service.py backend/app/api/http.py backend/app/main.py \
        backend/app/api/ws.py backend/tests/alerts/ \
        frontend/openapi.json frontend/src/api/types.ts
git commit -m "$(cat <<'EOF'
feat(alerts): service + /api/alerts/* + lifespan engine wiring

AlertsService validates symbols via broker.get_quote, propagates CRUD
to AlertEngine, broadcasts ALERT_CHANGED. main.py starts/stops the
engine in lifespan.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
