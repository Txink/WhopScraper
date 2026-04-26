"""LongPortClient — concrete BrokerClient backed by longport SDK.

Wraps sync ``TradeContext`` / ``QuoteContext``.  Push callbacks fan out to
subscribers on the SDK's own thread — callers needing asyncio should bridge
via ``loop.call_soon_threadsafe`` in their handler.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from longport.openapi import (
    Config as LPConfig,
)
from longport.openapi import (
    OrderSide as LPOrderSide,
)
from longport.openapi import (
    OrderType as LPOrderType,
)
from longport.openapi import (
    QuoteContext,
    TimeInForceType,
    TopicType,
    TradeContext,
)

from app.broker.broker_client import OrderSide, OrderType
from app.broker.config import LongPortConfig

logger = logging.getLogger(__name__)


class LongPortClient:
    """BrokerClient implementation using the ``longport.openapi`` SDK.

    Pass ``config.dry_run=True`` to exercise order-submission code paths
    without ever making a network call — useful in unit tests and staging.
    For interactive dry_run toggling at runtime (e.g. from the UI) pass
    ``dry_run_getter`` so the flag is read on every submit instead of being
    captured at construction.
    """

    def __init__(
        self,
        config: LongPortConfig,
        *,
        dry_run_getter: Callable[[], bool] | None = None,
    ) -> None:
        self._config = config
        self._dry_run_getter = dry_run_getter
        self._push_handlers: list[Callable[[Any], None]] = []
        self._closed = False

        lp_config = LPConfig(
            app_key=config.app_key,
            app_secret=config.app_secret,
            access_token=config.access_token,
        )

        # QuoteContext first (mirrors old broker — avoids connection-count
        # leak if TradeContext creation fails).
        self._quote_ctx: QuoteContext | None = QuoteContext(lp_config)
        self._trade_ctx: TradeContext | None = TradeContext(lp_config)

        # Wire push callback — fans out to all registered handlers.
        self._trade_ctx.set_on_order_changed(self._on_order_changed)
        # Subscribe to the Private topic so the SDK actually delivers
        # order-changed pushes. set_on_order_changed alone only registers
        # the callback; without subscribe([TopicType.Private]) the SDK never
        # pushes anything and submitted orders sit at PENDING forever.
        self._trade_ctx.subscribe([TopicType.Private])

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_paper(self) -> bool:
        return self._config.mode == "paper"

    @property
    def dry_run(self) -> bool:
        # Prefer the runtime getter when wired — lets the UI's dry_run
        # toggle take effect on the next submit without rebuilding the
        # broker. Falls back to the config snapshot for tests / direct use.
        if self._dry_run_getter is not None:
            return bool(self._dry_run_getter())
        return self._config.dry_run

    # ------------------------------------------------------------------ #
    # Orders                                                               #
    # ------------------------------------------------------------------ #

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
        """Submit an option order; return broker-assigned order_id."""
        if self.dry_run:
            dry_id = f"DRY-{uuid.uuid4()}"
            logger.info(
                "[DRY RUN] submit_option_order symbol=%s side=%s qty=%d price=%s → %s",
                symbol,
                side,
                quantity,
                price,
                dry_id,
            )
            return dry_id

        return self._submit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            remark=remark,
        )

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
        """Submit a stock order; return broker-assigned order_id."""
        if self.dry_run:
            dry_id = f"DRY-{uuid.uuid4()}"
            logger.info(
                "[DRY RUN] submit_stock_order symbol=%s side=%s qty=%d price=%s → %s",
                symbol,
                side,
                quantity,
                price,
                dry_id,
            )
            return dry_id

        return self._submit_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            order_type=order_type,
            remark=remark,
        )

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order.

        On dry_run: log and no-op without a network call.
        """
        if self.dry_run:
            logger.info("[DRY RUN] cancel_order order_id=%s — skipped", order_id)
            return
        if self._trade_ctx is None:
            raise RuntimeError("LongPortClient has been closed")
        self._trade_ctx.cancel_order(order_id)

    # ------------------------------------------------------------------ #
    # Quotes                                                               #
    # ------------------------------------------------------------------ #

    def get_quote(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch latest quotes; returns ``{symbol: {last_done, open, ...}}``."""
        if self._quote_ctx is None:
            raise RuntimeError("LongPortClient has been closed")

        resp = self._quote_ctx.quote(symbols)
        result: dict[str, dict[str, Any]] = {}
        for q in resp:
            result[q.symbol] = {
                "last_done": float(q.last_done) if q.last_done else 0.0,
                "prev_close": float(q.prev_close) if q.prev_close else 0.0,
                "open": float(q.open) if q.open else 0.0,
                "high": float(q.high) if q.high else 0.0,
                "low": float(q.low) if q.low else 0.0,
                "volume": int(q.volume) if q.volume else 0,
                "turnover": float(q.turnover) if q.turnover else 0.0,
            }
        return result

    # ------------------------------------------------------------------ #
    # Push                                                                 #
    # ------------------------------------------------------------------ #

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        """Register a callback for order-change push events."""
        self._push_handlers.append(handler)

    def _on_order_changed(self, event: Any) -> None:
        """SDK callback — fans out to all registered subscribers."""
        for handler in list(self._push_handlers):
            try:
                handler(event)
            except Exception:
                logger.exception("Order push handler raised an exception; continuing")

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Release SDK resources.  Idempotent."""
        if self._closed:
            return
        self._closed = True
        for attr_name, ctx in (("_quote_ctx", self._quote_ctx), ("_trade_ctx", self._trade_ctx)):
            if ctx is None:
                continue
            try:
                close_fn = getattr(ctx, "close", None)
                if callable(close_fn):
                    close_fn()
            except Exception as exc:
                logger.debug("Error closing %s (ignored): %s", attr_name, exc)
            setattr(self, attr_name, None)
        logger.debug("LongPortClient closed")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _submit_order(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: int,
        price: float | None,
        order_type: OrderType,
        remark: str,
    ) -> str:
        """Build and submit an order via the SDK TradeContext."""
        if self._trade_ctx is None:
            raise RuntimeError("LongPortClient has been closed")

        lp_side = LPOrderSide.Buy if side == "BUY" else LPOrderSide.Sell

        submitted_price: Decimal | None
        lp_order_type: type[LPOrderType]
        if order_type == "MARKET":
            lp_order_type = LPOrderType.MO
            submitted_price = None
        else:
            lp_order_type = LPOrderType.LO
            if price is None:
                raise ValueError(f"price is required for LIMIT order (symbol={symbol})")
            submitted_price = Decimal(str(price))

        resp = self._trade_ctx.submit_order(
            side=lp_side,
            symbol=symbol,
            order_type=lp_order_type,
            submitted_price=submitted_price,
            submitted_quantity=Decimal(quantity),
            time_in_force=TimeInForceType.Day,
            remark=remark,
        )

        order_id: str = getattr(resp, "order_id", None) or getattr(resp, "id", None) or str(resp)
        return order_id
