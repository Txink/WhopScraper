"""NoopBrokerClient —— a BrokerClient that does nothing.

Used when LongPort credentials are missing. The system runs in
monitoring-only mode: messages parse to instructions, but no orders
get submitted to a real broker.

Submitting an order returns a synthetic id like `NOOP-<uuid>` and logs
a warning. Cancel / push subscribe / quote return empty/no-op.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from app.broker.broker_client import OrderSide, OrderType

logger = logging.getLogger(__name__)


class NoopBrokerClient:
    """No-op broker for monitoring mode (no LongPort creds).

    Satisfies BrokerClient Protocol structurally (duck-typed); orders
    are logged but not submitted. ``is_paper=True`` and ``dry_run=True``
    so downstream display layers know nothing real happened.
    """

    @property
    def is_paper(self) -> bool:
        return True

    @property
    def dry_run(self) -> bool:
        return True

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
        oid = f"NOOP-{uuid.uuid4().hex[:8]}"
        logger.warning(
            "noop broker would submit option order: "
            "%s %s %s × %s @ %s (id=%s) — no real submission",
            side, order_type, symbol, quantity, price, oid,
        )
        return oid

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
        oid = f"NOOP-{uuid.uuid4().hex[:8]}"
        logger.warning(
            "noop broker would submit stock order: "
            "%s %s %s × %s @ %s (id=%s) — no real submission",
            side, order_type, symbol, quantity, price, oid,
        )
        return oid

    def cancel_order(self, order_id: str) -> None:
        logger.warning("noop broker would cancel %s — no real cancel", order_id)

    def get_quote(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return {s: {"last_done": 0.0} for s in symbols}

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        # No real push stream — handler will never be invoked
        pass

    def close(self) -> None:
        pass
