"""Test fakes for broker tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.broker.broker_client import OrderSide, OrderType


@dataclass
class FakeBrokerClient:
    """Programmable BrokerClient for tests."""

    is_paper: bool = True
    dry_run: bool = False
    submitted_orders: list[dict[str, Any]] = field(default_factory=list)
    cancelled_orders: list[str] = field(default_factory=list)
    #: ``last_done`` per symbol for ``get_quote`` (0 = missing quote → trader uses LIMIT).
    quote_by_symbol: dict[str, float] = field(default_factory=dict)
    next_order_id: str = ""
    raise_on_submit: Exception | None = None
    raise_on_cancel: Exception | None = None
    push_handlers: list[Callable[[Any], None]] = field(default_factory=list)

    def submit_option_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float | None,
        order_type: OrderType,
        remark: str = "",
    ) -> str:
        if self.raise_on_submit:
            raise self.raise_on_submit
        self.submitted_orders.append(
            {
                "kind": "option",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
                "remark": remark,
            }
        )
        return self.next_order_id or f"fake-{uuid.uuid4().hex[:8]}"

    def submit_stock_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float | None,
        order_type: OrderType,
        remark: str = "",
    ) -> str:
        if self.raise_on_submit:
            raise self.raise_on_submit
        self.submitted_orders.append(
            {
                "kind": "stock",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                "order_type": order_type,
                "remark": remark,
            }
        )
        return self.next_order_id or f"fake-{uuid.uuid4().hex[:8]}"

    def cancel_order(self, order_id: str) -> None:
        if self.raise_on_cancel:
            raise self.raise_on_cancel
        self.cancelled_orders.append(order_id)

    def get_quote(self, symbols: list[str]) -> dict[str, Any]:
        return {s: {"last_done": float(self.quote_by_symbol.get(s, 0.0))} for s in symbols}

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        self.push_handlers.append(handler)

    def close(self) -> None:
        pass

    def emit_push(self, event_obj: Any) -> None:
        """Test helper: fire a push event to all subscribers."""
        for h in self.push_handlers:
            h(event_obj)


@dataclass
class FakeTaskQueryRepo:
    """Test fake for TaskQueryRepo. Stores qty by (ticker, side_value, price)."""

    matches: dict[tuple[str, str, float], int] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def find_recent_task_by_ref(
        self,
        *,
        ticker: str,
        side: Any,  # InstructionType — kept Any to avoid circular imports here
        price: float,
        before: Any,
        window_hours: int = 24 * 7,
    ) -> int | None:
        self.calls.append({
            "ticker": ticker, "side": side, "price": price,
            "before": before, "window_hours": window_hours,
        })
        side_value = side.value if hasattr(side, "value") else side
        return self.matches.get((ticker, side_value, price))
