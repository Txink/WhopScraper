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
from app.domain.status import TERMINAL, Status
from app.orders.schemas import OrderOut, ReplaceOrderRequest, SubmitOrderRequest
from app.storage.schema import TaskRow

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]

# LongPort `replace_order` does NOT amend in place — it marks the old
# order_id as "Replaced" (terminal, superseded) and mints a NEW order_id
# with status "ReplacedNotReported". To preserve a single-row UX, we:
#   1. After replace, scan today_orders to find the new id and rebind
#      the TaskRow.order_id to it (see _find_replacement_order_id).
#   2. Filter the SUPERSEDED status out of list_today.
# Anything else containing "Replaced" (ReplacedNotReported, etc.) is the
# new live order and stays visible.
_SUPERSEDED_STATUSES = frozenset(("OrderStatus.Replaced", "Replaced"))


class OrderImmutable(RuntimeError):
    """Raised when an order cannot be replaced/cancelled because it is
    already in a terminal state."""


def _start_of_today_utc() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


class OrdersService:
    def __init__(
        self,
        broker: BrokerClient,
        event_bus: EventBus,
        session_factory: SessionFactory,
        push_listener_getter: Callable[[], Any] | None = None,
    ) -> None:
        self._broker = broker
        self._bus = event_bus
        self._sessions = session_factory
        # Resolved lazily on each replace so we pick up post-broker-reload
        # PushListener instances. None means "no listener" (tests, early
        # startup) — replace still rebinds the TaskRow, just doesn't try
        # to drain the buffer.
        self._push_listener_getter = push_listener_getter

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
        # Reject modify on terminal orders (CANCELLED / FILLED / REJECTED / ...).
        # Skip when no TaskRow exists — the order was placed outside our DB
        # (e.g. directly via the broker app); let the SDK be the source of truth.
        async with self._sessions() as session:
            existing = (await session.execute(
                select(TaskRow).where(TaskRow.order_id == order_id)
            )).scalar_one_or_none()
            if existing is not None and Status(existing.status) in TERMINAL:
                raise ValueError(
                    f"order is {existing.status}; cannot modify"
                )
        self._broker.replace_order(order_id, quantity=req.qty, price=req.price)
        now = datetime.now(UTC)
        new_order_id: str | None = None
        async with self._sessions() as session:
            stmt = select(TaskRow).where(TaskRow.order_id == order_id)
            task = (await session.execute(stmt)).scalar_one_or_none()
            if task is not None:
                # Compute the expected post-replace values for the broker scan.
                post_price = req.price if req.price is not None else task.submit_price
                post_qty = req.qty if req.qty is not None else task.quantity
                new_order_id = self._find_replacement_order_id(
                    ticker=task.ticker or "",
                    symbol=task.symbol or "",
                    side=task.side or "",
                    price=post_price,
                    qty=post_qty,
                    old_id=order_id,
                )
                if new_order_id:
                    task.order_id = new_order_id
                if req.price is not None:
                    task.submit_price = req.price
                    task.price = req.price
                if req.qty is not None:
                    task.quantity = req.qty
                task.last_replaced_at = now
                task.updated_at = now
                await session.commit()
        # Drain any buffered pushes that arrived for the new id between
        # broker.replace_order returning and us committing the rebind.
        if new_order_id and self._push_listener_getter is not None:
            listener = self._push_listener_getter()
            if listener is not None:
                try:
                    await listener.replay_for_order(new_order_id)
                except Exception:
                    logger.exception(
                        "replace: replay_for_order(%s) failed", new_order_id
                    )
        await self._bus.publish(
            Event(
                Topics.ORDER_CHANGED,
                {"action": "updated",
                 "order_id": new_order_id or order_id,
                 "old_order_id": order_id if new_order_id else None,
                 "price": req.price, "qty": req.qty,
                 "last_replaced_at": now.isoformat()},
            )
        )

    def _find_replacement_order_id(
        self,
        *,
        ticker: str,
        symbol: str,
        side: str,
        price: float | None,
        qty: int | None,
        old_id: str,
    ) -> str | None:
        """Scan broker today_orders for the new order_id minted by replace_order.

        LongPort doesn't return the new id from replace_order — it shows up
        in today_orders with a status containing ``Replaced`` but not the
        literal terminal ``OrderStatus.Replaced`` (which is the OLD id's
        post-replace state). We match by ticker/side and the post-replace
        price/qty, then pick the newest. Returns None if no plausible match
        is found (e.g. broker hasn't yet propagated the new order, or this
        wasn't really a LongPort-style replace).
        """
        try:
            rows = self._broker.today_orders(ticker=ticker)
        except Exception:
            logger.exception("replace: today_orders scan failed")
            return None
        side_token = "Buy" if side == "BUY" else "Sell"
        candidates: list[dict[str, Any]] = []
        for r in rows:
            if r["order_id"] == old_id:
                continue
            if symbol and r["symbol"] != symbol:
                continue
            if side_token not in r["side"]:
                continue
            status = r["status"]
            if "Replaced" not in status or status in _SUPERSEDED_STATUSES:
                continue
            if price is not None and abs(r["price"] - price) > 1e-4:
                continue
            if qty is not None and r["quantity"] != qty:
                continue
            candidates.append(r)
        if not candidates:
            return None
        candidates.sort(key=lambda r: str(r.get("submitted_at") or ""), reverse=True)
        return str(candidates[0]["order_id"])

    async def cancel(self, order_id: str) -> None:
        # Mirror the replace() gate: refuse to cancel an order that is
        # already terminal (cancelled / filled / rejected / ...). The
        # broker SDK would reject it too, but a clean 422 reads better
        # than the broker's stack-traced 502.
        async with self._sessions() as session:
            existing = (await session.execute(
                select(TaskRow).where(TaskRow.order_id == order_id)
            )).scalar_one_or_none()
            if existing is not None and Status(existing.status) in TERMINAL:
                raise ValueError(
                    f"order is {existing.status}; cannot cancel"
                )
        self._broker.cancel_order(order_id)
        await self._bus.publish(
            Event(Topics.ORDER_CHANGED, {"action": "cancelled", "order_id": order_id})
        )

    async def list_today(self, ticker: str) -> list[OrderOut]:
        broker_rows = self._broker.today_orders(ticker=ticker)
        # Drop the superseded "OrderStatus.Replaced" rows — they're the
        # OLD ids of replace_order events and aren't actionable. Mirrors
        # the LongPort app, which only shows the live successor.
        broker_rows = [r for r in broker_rows if r.get("status") not in _SUPERSEDED_STATUSES]
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
