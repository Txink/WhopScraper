"""BrokerClient Protocol — minimum interface broker consumers rely on.

Higher-level layers (Trader, PushListener) depend on this interface only,
never on ``LongPortClient`` directly, enabling easy test-time substitution.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["LIMIT", "MARKET"]


class BrokerClient(Protocol):
    """Abstract broker interface.

    Concrete implementation: ``LongPortClient``.
    Test double: any class that satisfies this structural sub-type.
    """

    @property
    def is_paper(self) -> bool: ...

    @property
    def dry_run(self) -> bool: ...

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
        """Submit an option order; return broker-assigned order_id.

        Raises on failure.  If ``dry_run=True``, returns a synthetic id
        prefixed with ``DRY-`` without making any network call.
        """

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
        """Submit a stock (equity) order; return broker-assigned order_id."""

    def get_quote(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch latest quotes.

        Returns ``{symbol: {last_done, open, high, low, volume, ...}}``.
        """

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        """Register a callback for broker order-change push events.

        ``handler`` receives the raw broker event object.  Multiple
        subscribers may be registered; all are called in registration order.
        """

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order by broker-assigned order_id.

        On ``dry_run=True`` implementations should log + no-op rather than
        making a network call.  Raises on failure.
        """

    def close(self) -> None:
        """Release SDK resources.  Safe to call multiple times."""
