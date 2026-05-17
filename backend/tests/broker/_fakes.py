"""Test fakes for broker tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime  # noqa: F401  (used in get_candlesticks forward ref)
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

    def stock_positions(self) -> list[dict[str, Any]]:
        """Return the test-configured holdings list (default: empty)."""
        return list(getattr(self, "stock_positions_list", []))

    @property
    def account_id(self) -> str:
        """User-configurable account id (default test-acct) for sync tests."""
        return str(getattr(self, "account_id_value", "test-acct"))

    def today_executions(self) -> list[dict[str, Any]]:
        """Return the test-configured execution list (default: empty)."""
        return list(getattr(self, "executions_list", []))

    def history_executions(
        self,
        *,
        ticker: str | None = None,
        days: int = 30,
        start_at: "datetime | None" = None,
        end_at: "datetime | None" = None,
    ) -> list[dict[str, Any]]:
        items = list(getattr(self, "history_executions_list", []))
        if ticker is not None:
            items = [e for e in items if e.get("ticker") == ticker]
        # LongBridge's history_executions / history_orders cap each call
        # at a 90-day window. Mirror that here so the test suite actually
        # catches callers that issue a single wide-range request instead
        # of iterating 90-day chunks. See knowledge/longbridge-api-limits.md.
        if start_at is not None and end_at is not None:
            from datetime import timedelta, timezone

            def _aware(t):
                return t if t.tzinfo is not None else t.replace(tzinfo=timezone.utc)
            s, e = _aware(start_at), _aware(end_at)
            if (e - s) > timedelta(days=90):
                raise ValueError(
                    f"history_executions window too wide: "
                    f"{(e - s).days}d > 90d (LongBridge cap)"
                )
            # ``start_at`` inclusive, ``end_at`` exclusive — matches
            # LongBridge's convention.
            items = [r for r in items if r.get("ts") is not None and s <= _aware(r["ts"]) < e]
        elif days > 90:
            raise ValueError(
                f"history_executions window too wide: {days}d > 90d (LongBridge cap)"
            )
        return items

    def get_candlesticks(
        self,
        symbol: str,
        *,
        period: str,
        count: int,
        sessions: str = "regular",  # noqa: ARG002 — accepted for protocol compat
        before: "datetime | None" = None,  # noqa: ARG002 — accepted for protocol compat
    ) -> list[dict[str, Any]]:
        """Deterministic stub: returns ``count`` bars seeded from symbol hash
        so tests can assert structure without a real broker connection.
        Tests can also override by monkey-patching ``candlesticks_by_symbol``."""
        override = getattr(self, "candlesticks_by_symbol", {}).get(symbol)
        if override is not None:
            return list(override[:count])
        base = (sum(ord(c) for c in symbol) % 200) + 50  # 50..250
        bars: list[dict[str, Any]] = []
        for i in range(count):
            p = float(base + (i * 0.5))
            bars.append({
                "timestamp": f"2026-01-{(i % 28) + 1:02d}T16:00:00",
                "open": p,
                "high": p + 1.0,
                "low": p - 1.0,
                "close": p + 0.3,
                "volume": 1_000_000 + i * 1000,
                "turnover": p * 1_000_000,
            })
        return bars

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        self.push_handlers.append(handler)

    def set_on_quote(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        """Quote-push handler (one per broker, owned by QuoteHub)."""
        self.quote_handler = handler

    def subscribe_quotes(self, symbols: list[str]) -> None:
        """Record symbols added to the quote-watch set."""
        if not hasattr(self, "subscribed_quote_symbols"):
            self.subscribed_quote_symbols = set()
        for s in symbols:
            self.subscribed_quote_symbols.add(s)

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        """Record symbols removed from the quote-watch set."""
        if not hasattr(self, "subscribed_quote_symbols"):
            self.subscribed_quote_symbols = set()
        for s in symbols:
            self.subscribed_quote_symbols.discard(s)

    def fetch_trading_sessions(self) -> dict[str, list[tuple[Any, Any, str]]]:
        """Test helper — defaults to the override ``trading_sessions_map``
        if set, else returns the empty dict (so MarketSchedule falls
        back to its clock heuristic)."""
        return dict(getattr(self, "trading_sessions_map", {}))

    def fetch_trading_days(self, *, days_back: int = 3) -> dict[str, list[Any]]:
        return dict(getattr(self, "trading_days_map", {}))

    def close(self) -> None:
        pass

    def emit_push(self, event_obj: Any) -> None:
        """Test helper: fire a push event to all subscribers."""
        for h in self.push_handlers:
            h(event_obj)

    def emit_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        """Test helper: fire a quote-push event to the registered handler.
        Tests use this to assert QuoteHub → bus → WS path end-to-end."""
        handler = getattr(self, "quote_handler", None)
        if handler is not None:
            handler(symbol, quote)


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
