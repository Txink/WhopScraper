"""Manual orders service — submit, replace, cancel via broker; persist
manual orders to `tasks` with source='manual'; emit ORDER_CHANGED events.

Manual orders bypass the parser / Trader signal pipeline. They never
create Message or Instruction rows — the task is created directly here
with a `man_` prefixed id.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, time, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.broker.broker_client import BrokerClient
from app.core.event_bus import Event, EventBus
from app.core.events import Topics
from app.orders.schemas import OrderOut, ReplaceOrderRequest, SubmitOrderRequest
from app.storage.schema import TaskRow

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


def _start_of_today_utc() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


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
        )
        task_id = f"man_{uuid.uuid4().hex[:24]}"
        ticker = req.symbol.split(".")[0]
        now = datetime.now(UTC)
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
            Event(Topics.ORDER_CHANGED, {"action": "created", "order": out.model_dump(mode="json")})
        )
        return out

    async def replace(self, order_id: str, req: ReplaceOrderRequest) -> None:
        if req.price is None and req.qty is None:
            raise ValueError("replace requires price or qty")
        self._broker.replace_order(order_id, quantity=req.qty, price=req.price)
        now = datetime.now(UTC)
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
            Event(
                Topics.ORDER_CHANGED,
                {"action": "updated", "order_id": order_id,
                 "price": req.price, "qty": req.qty,
                 "last_replaced_at": now.isoformat()},
            )
        )

    async def cancel(self, order_id: str) -> None:
        self._broker.cancel_order(order_id)
        await self._bus.publish(
            Event(Topics.ORDER_CHANGED, {"action": "cancelled", "order_id": order_id})
        )

    async def list_today(self, ticker: str) -> list[OrderOut]:
        broker_rows = self._broker.today_orders(ticker=ticker)
        broker_by_id: dict[str, Any] = {r["order_id"]: r for r in broker_rows}

        async with self._sessions() as session:
            stmt = select(TaskRow).where(
                TaskRow.ticker == ticker,
                TaskRow.source == "manual",
                TaskRow.created_at >= _start_of_today_utc(),
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
