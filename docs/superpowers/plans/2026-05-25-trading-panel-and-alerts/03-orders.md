# Task 3: Orders Service + REST API + WS `order.changed`

**Files:**
- Create: `backend/app/orders/__init__.py`, `service.py`, `schemas.py`
- Modify: `backend/app/core/events.py` — add `ORDER_CHANGED`
- Modify: `backend/app/api/http.py` — mount `/api/orders/*` routes
- Modify: `backend/app/api/ws.py` — relay `order.changed` topic
- Test: `backend/tests/orders/test_service.py`, `test_api.py`

## Steps

- [ ] **Step 1: Define schemas**

Create `backend/app/orders/schemas.py`:

```python
"""Pydantic schemas for the /api/orders/* endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

OrderType = Literal["LIMIT", "MARKET"]
OrderSide = Literal["BUY", "SELL"]


class SubmitOrderRequest(BaseModel):
    symbol: str = Field(min_length=1)
    side: OrderSide
    qty: int = Field(gt=0)
    order_type: OrderType
    price: float | None = None
    time_in_force: Literal["Day"] = "Day"
    note: str | None = None


class ReplaceOrderRequest(BaseModel):
    price: float | None = None
    qty: int | None = Field(default=None, gt=0)


class OrderOut(BaseModel):
    order_id: str
    task_id: str | None
    ticker: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: float | None
    qty: int
    filled_qty: int
    status: str
    source: Literal["signal", "manual", "external"]
    submitted_at: datetime | None
    last_replaced_at: datetime | None


class OrderListOut(BaseModel):
    orders: list[OrderOut]
```

- [ ] **Step 2: Add event topic**

Modify `backend/app/core/events.py`:

```python
    ORDER_CHANGED = "order.changed"
```

(Insert after `TASK_STATUS_CHANGED`.)

- [ ] **Step 3: Write failing service tests**

Create `backend/tests/orders/test_service.py`:

```python
"""OrdersService — submit, replace, cancel, list paths against a fake broker."""
from __future__ import annotations

import pytest

from app.core.event_bus import EventBus
from app.core.events import Topic
from app.orders.schemas import ReplaceOrderRequest, SubmitOrderRequest
from app.orders.service import OrdersService


class FakeBroker:
    def __init__(self) -> None:
        self.submitted: list[dict] = []
        self.replaced: list[dict] = []
        self.cancelled: list[str] = []
        self.next_order_id = "ord-1"
        self.is_paper = True
        self.dry_run = False
        self.account_id = "acct-1"

    def submit_stock_order(self, **kwargs):
        self.submitted.append(kwargs)
        return self.next_order_id

    def replace_order(self, order_id, *, quantity=None, price=None):
        self.replaced.append({"order_id": order_id, "qty": quantity, "price": price})

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)

    def today_orders(self, *, ticker=None):
        return [{
            "order_id": "ord-1", "symbol": "AAPL.US", "ticker": "AAPL",
            "side": "Buy", "order_type": "LO", "price": 199.0, "quantity": 200,
            "executed_quantity": 0, "status": "NewStatus", "submitted_at": None,
        }]


@pytest.mark.asyncio
async def test_submit_creates_task_and_emits_event(db_session, monkeypatch):
    bus = EventBus()
    received: list = []
    bus.subscribe(Topic.ORDER_CHANGED, lambda payload: received.append(payload))
    svc = OrdersService(broker=FakeBroker(), event_bus=bus, session_factory=db_session)
    req = SubmitOrderRequest(
        symbol="AAPL.US", side="BUY", qty=200, order_type="LIMIT", price=199.0,
    )
    out = await svc.submit(req)
    assert out.order_id == "ord-1"
    assert out.source == "manual"
    await bus.wait_idle()
    assert any(p["action"] == "created" for p in received)


@pytest.mark.asyncio
async def test_replace_calls_broker_and_updates_task(db_session):
    bus = EventBus()
    broker = FakeBroker()
    svc = OrdersService(broker=broker, event_bus=bus, session_factory=db_session)
    # Prime a manual task
    await svc.submit(SubmitOrderRequest(
        symbol="AAPL.US", side="BUY", qty=200, order_type="LIMIT", price=199.0,
    ))
    await svc.replace("ord-1", ReplaceOrderRequest(price=199.5))
    assert broker.replaced == [{"order_id": "ord-1", "qty": None, "price": 199.5}]


@pytest.mark.asyncio
async def test_replace_requires_at_least_one_field(db_session):
    svc = OrdersService(broker=FakeBroker(), event_bus=EventBus(), session_factory=db_session)
    with pytest.raises(ValueError, match="price or qty"):
        await svc.replace("ord-1", ReplaceOrderRequest())


@pytest.mark.asyncio
async def test_cancel_calls_broker(db_session):
    broker = FakeBroker()
    svc = OrdersService(broker=broker, event_bus=EventBus(), session_factory=db_session)
    await svc.cancel("ord-1")
    assert broker.cancelled == ["ord-1"]


@pytest.mark.asyncio
async def test_list_today_merges_broker_orders_with_manual_tasks(db_session):
    broker = FakeBroker()
    svc = OrdersService(broker=broker, event_bus=EventBus(), session_factory=db_session)
    await svc.submit(SubmitOrderRequest(
        symbol="AAPL.US", side="BUY", qty=200, order_type="LIMIT", price=199.0,
    ))
    rows = await svc.list_today("AAPL")
    assert len(rows) == 1
    # Same order_id from manual submit AND broker today_orders → single merged row,
    # source=manual takes precedence.
    assert rows[0].source == "manual"
```

`db_session` fixture (add to `backend/tests/conftest.py` if missing): an async sessionmaker bound to an in-memory engine with all tables created.

- [ ] **Step 4: Implement service**

Create `backend/app/orders/service.py`:

```python
"""Manual orders service — submit, replace, cancel via broker; persist
manual orders to `tasks` with source='manual'; emit ORDER_CHANGED events.

Manual orders bypass the parser / Trader signal pipeline. They never
create Message or Instruction rows — the task is created directly here
with a `man_` prefixed id.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.broker_client import BrokerClient
from app.core.event_bus import EventBus
from app.core.events import Topic
from app.orders.schemas import (
    OrderListOut, OrderOut, ReplaceOrderRequest, SubmitOrderRequest,
)
from app.storage.schema import TaskRow

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


class OrderImmutable(RuntimeError):
    """Raised when an order cannot be replaced/cancelled because it is
    already in a terminal state."""


class OrdersService:
    def __init__(
        self,
        broker: BrokerClient,
        event_bus: EventBus,
        session_factory: SessionFactory,
    ) -> None:
        self._broker = broker
        self._bus = event_bus
        self._sessions = session_factory

    async def submit(self, req: SubmitOrderRequest) -> OrderOut:
        if req.order_type == "LIMIT" and req.price is None:
            raise ValueError("LIMIT order requires price")
        order_id = self._broker.submit_stock_order(
            symbol=req.symbol,
            side=req.side,
            quantity=req.qty,
            order_type=req.order_type,
            price=req.price,
            time_in_force=req.time_in_force,
        )
        task_id = f"man_{uuid.uuid4().hex[:24]}"
        ticker = req.symbol.split(".")[0]
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            row = TaskRow(
                id=task_id,
                type="STOCK",
                status="SUBMITTING",
                order_id=order_id,
                ticker=ticker,
                symbol=req.symbol,
                side=req.side,
                price=req.price,
                quantity=req.qty,
                submit_order_type=req.order_type,
                submit_price=req.price,
                created_at=now,
                updated_at=now,
                source="manual",
                account_id=getattr(self._broker, "account_id", None),
            )
            session.add(row)
            await session.commit()
        out = OrderOut(
            order_id=order_id, task_id=task_id, ticker=ticker, symbol=req.symbol,
            side=req.side, order_type=req.order_type, price=req.price,
            qty=req.qty, filled_qty=0, status="SUBMITTING", source="manual",
            submitted_at=now, last_replaced_at=None,
        )
        await self._bus.publish(
            Topic.ORDER_CHANGED, {"action": "created", "order": out.model_dump(mode="json")}
        )
        return out

    async def replace(self, order_id: str, req: ReplaceOrderRequest) -> None:
        if req.price is None and req.qty is None:
            raise ValueError("replace requires price or qty")
        self._broker.replace_order(order_id, quantity=req.qty, price=req.price)
        now = datetime.now(timezone.utc)
        async with self._sessions() as session:
            stmt = select(TaskRow).where(TaskRow.order_id == order_id)
            task = (await session.execute(stmt)).scalar_one_or_none()
            if task is not None:
                if req.price is not None:
                    task.submit_price = req.price
                    task.price = req.price
                if req.qty is not None:
                    task.quantity = req.qty
                task.last_replaced_at = now
                task.updated_at = now
                await session.commit()
        await self._bus.publish(
            Topic.ORDER_CHANGED,
            {"action": "updated", "order_id": order_id,
             "price": req.price, "qty": req.qty,
             "last_replaced_at": now.isoformat()},
        )

    async def cancel(self, order_id: str) -> None:
        self._broker.cancel_order(order_id)
        await self._bus.publish(
            Topic.ORDER_CHANGED, {"action": "cancelled", "order_id": order_id}
        )

    async def list_today(self, ticker: str) -> list[OrderOut]:
        broker_rows = self._broker.today_orders(ticker=ticker)
        broker_by_id = {r["order_id"]: r for r in broker_rows}

        # Manual tasks created today for this ticker — superset; their
        # source field takes precedence over the broker's "external" tag.
        async with self._sessions() as session:
            stmt = select(TaskRow).where(
                TaskRow.ticker == ticker,
                TaskRow.source == "manual",
            )
            manual_tasks = list((await session.execute(stmt)).scalars())

        merged: dict[str, OrderOut] = {}
        for r in broker_rows:
            merged[r["order_id"]] = OrderOut(
                order_id=r["order_id"], task_id=None,
                ticker=r["ticker"], symbol=r["symbol"],
                side="BUY" if "Buy" in r["side"] else "SELL",
                order_type="LIMIT" if r["order_type"] in ("LO", "ELO") else "MARKET",
                price=r["price"], qty=r["quantity"],
                filled_qty=r["executed_quantity"],
                status=r["status"],
                source="external",
                submitted_at=r.get("submitted_at"),
                last_replaced_at=None,
            )
        for t in manual_tasks:
            if t.order_id is None:
                continue
            br = broker_by_id.get(t.order_id, {})
            merged[t.order_id] = OrderOut(
                order_id=t.order_id, task_id=t.id,
                ticker=t.ticker or ticker, symbol=t.symbol or "",
                side=t.side or "BUY",  # type: ignore[arg-type]
                order_type=t.submit_order_type or "LIMIT",  # type: ignore[arg-type]
                price=t.submit_price if t.submit_price is not None else t.price,
                qty=t.quantity or 0,
                filled_qty=int(br.get("executed_quantity", 0)),
                status=br.get("status") or t.status,
                source="manual",
                submitted_at=t.created_at,
                last_replaced_at=t.last_replaced_at,
            )
        return list(merged.values())
```

`backend/app/orders/__init__.py`:

```python
"""Manual orders module."""
```

- [ ] **Step 5: Add API routes**

In `backend/app/api/http.py` find `build_http_router(...)` and inside the function, add after the `/api/pairs` block:

```python
    from app.orders.schemas import (
        OrderListOut, OrderOut, ReplaceOrderRequest, SubmitOrderRequest,
    )
    from app.orders.service import OrdersService

    orders_svc = OrdersService(broker=broker, event_bus=event_bus, session_factory=session_factory)

    @router.post("/api/orders", response_model=OrderOut, status_code=201)
    async def post_order(req: SubmitOrderRequest) -> OrderOut:
        if isinstance(broker, NoopBrokerClient):
            raise HTTPException(503, "No authorized broker; cannot submit order")
        try:
            return await orders_svc.submit(req)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except Exception as e:  # broker SDK errors
            raise HTTPException(502, f"broker error: {e}") from e

    @router.patch("/api/orders/{order_id}", status_code=204)
    async def patch_order(order_id: str, req: ReplaceOrderRequest) -> Response:
        try:
            await orders_svc.replace(order_id, req)
            return Response(status_code=204)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except Exception as e:
            raise HTTPException(502, f"broker error: {e}") from e

    @router.delete("/api/orders/{order_id}", status_code=204)
    async def delete_order(order_id: str) -> Response:
        try:
            await orders_svc.cancel(order_id)
            return Response(status_code=204)
        except Exception as e:
            raise HTTPException(502, f"broker error: {e}") from e

    @router.get("/api/orders", response_model=OrderListOut)
    async def get_orders(ticker: str) -> OrderListOut:
        return OrderListOut(orders=await orders_svc.list_today(ticker))
```

Import `NoopBrokerClient` and `Response` at top of file if not already present.

- [ ] **Step 6: Relay topic in WS**

In `backend/app/api/ws.py` ensure `Topic.ORDER_CHANGED` is included in the topics list the hub subscribes to (it's auto-included if the hub iterates `Topic` enum — confirm).

- [ ] **Step 7: API tests**

Create `backend/tests/orders/test_api.py`:

```python
"""HTTP contract for /api/orders/* — happy + 422 + 502 + 503 paths."""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_submit_order_happy_path(client: AsyncClient) -> None:
    r = await client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["source"] == "manual"
    assert data["order_id"]


@pytest.mark.asyncio
async def test_submit_order_validation_fails_without_price_for_limit(client: AsyncClient) -> None:
    r = await client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200, "order_type": "LIMIT",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_replace_order_requires_field(client: AsyncClient) -> None:
    # submit first
    await client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    r = await client.patch("/api/orders/ord-1", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_get_orders_returns_list(client: AsyncClient) -> None:
    r = await client.get("/api/orders?ticker=AAPL")
    assert r.status_code == 200
    assert "orders" in r.json()


@pytest.mark.asyncio
async def test_submit_503_when_noop_broker(noop_client: AsyncClient) -> None:
    r = await noop_client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    assert r.status_code == 503
```

Fixtures `client` and `noop_client` should exist or be added to `backend/tests/api/conftest.py`. `noop_client` mounts an app with `broker_override=NoopBrokerClient()`.

- [ ] **Step 8: Run + verify**

```bash
cd backend
uv run pytest tests/orders tests/api/test_orders_api.py -v
uv run mypy app
uv run ruff check .
```

Expected: all pass.

- [ ] **Step 9: Regenerate OpenAPI types for frontend**

```bash
cd frontend && npm run gen:types
```

Verify diff includes new schemas.

- [ ] **Step 10: Commit**

```bash
git add backend/app/orders/ backend/app/core/events.py backend/app/api/http.py \
        backend/app/api/ws.py backend/tests/orders/ backend/tests/api/test_orders_api.py \
        frontend/openapi.json frontend/src/api/types.ts
git commit -m "$(cat <<'EOF'
feat(orders): manual order service + /api/orders/* routes + WS event

OrdersService wraps BrokerClient submit/replace/cancel and persists
manual orders to tasks (source=manual, man_ prefixed id). REST gates
behind NoopBroker → 503. WS broadcasts order.changed for the frontend.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
