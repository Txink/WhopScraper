"""BrokerClient Protocol — minimum interface broker consumers rely on.

Higher-level layers (Trader, PushListener) depend on this interface only,
never on ``LongPortClient`` directly, enabling easy test-time substitution.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime  # noqa: F401  (used in protocol docstring forward refs)
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

    def stock_positions(self) -> list[dict[str, Any]]:
        """Fetch current stock holdings from the broker.

        Returns ``[{"symbol", "ticker", "quantity", "avg_cost",
        "currency"}]`` — one entry per held position. ``ticker`` is the
        user-facing short code (e.g. ``"TSLL"``) derived by stripping the
        market suffix from ``symbol``. Returns ``[]`` when the account is
        flat or the broker call fails (callers should treat absence as
        "no positions" rather than "error").
        """

    def today_executions(self) -> list[dict[str, Any]]:
        """Fetch today's fills directly from the broker — includes orders
        placed in any channel (signal-station, LongBridge app, web).

        Each entry: ``{"order_id", "symbol", "ticker", "side", "qty",
        "price", "ts"}``. ``side`` is resolved via a join with
        ``today_orders``. ``ts`` is an ISO 8601 timestamp.

        This is the canonical data source for "what happened today" — DB
        trades only cover orders the trader pipeline submitted. Returns
        ``[]`` on broker error.
        """

    def history_executions(
        self,
        *,
        ticker: str | None = None,
        days: int = 30,
        start_at: "datetime | None" = None,
        end_at: "datetime | None" = None,
    ) -> list[dict[str, Any]]:
        """Fetch broker fills, optionally filtered to one underlying ticker.

        Window selection:
          - When both ``start_at`` and ``end_at`` are provided, query that
            exact UTC range. Used by the first-time-sync backfill which
            iterates 90-day chunks backwards to cover ~2 years of history
            without hitting the broker's per-call row cap.
          - Otherwise fall back to the rolling ``days`` window ending now.

        Same shape as ``today_executions``; this is the source of truth
        for the detail pane's historical trade list (includes manual
        fills placed via the LongBridge app / web).

        ``ticker`` matches against the OPTION-leg ticker for option fills
        (e.g. ``"HOOD"`` returns all HOOD option contract fills + HOOD
        stock fills). Pass ``None`` to fetch every fill in the window.
        """

    def get_candlesticks(
        self,
        symbol: str,
        *,
        period: str,
        count: int,
        sessions: str = "regular",
        before: "datetime | None" = None,
    ) -> list[dict[str, Any]]:
        """Fetch historical candlesticks for a symbol.

        ``period`` accepts granular SDK-style names (``min_1`` / ``min_2``
        / ``min_3`` / ``min_5`` / ``min_15`` / … / ``day``).

        ``sessions``:
          - ``"regular"`` (default): regular trading hours only
            (9:30-16:00 ET for US equities).
          - ``"all"``: include pre-market + after-hours bars.

        ``before`` (optional): when provided, fetch ``count`` bars strictly
        OLDER than this UTC instant — used by the detail-pane's pan-back
        flow to extend the loaded history when the user scrolls past the
        leftmost loaded bar. When ``None`` (default), behaves as before
        and returns the latest ``count`` bars.

        ``count`` caps the number of bars returned; the SDK may return
        fewer if the symbol has less history. Bars are chronological
        (oldest first).
        """

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        """Register a callback for broker order-change push events.

        ``handler`` receives the raw broker event object.  Multiple
        subscribers may be registered; all are called in registration order.
        """

    def set_on_quote(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        """Install the single callback for streaming quote pushes.

        ``handler`` receives ``(symbol, quote_dict)`` where ``quote_dict``
        carries the same shape as ``get_quote``'s value (last_done, open,
        high, low, volume, turnover, trade_session). One handler per broker;
        QuoteHub owns it. Called on the SDK's own thread — bridge to asyncio
        via ``loop.call_soon_threadsafe`` if needed.
        """

    def subscribe_quotes(self, symbols: list[str]) -> None:
        """Subscribe streaming Quote push for ``symbols`` via SDK
        ``QuoteContext.subscribe([SubType.Quote])``. Idempotent — symbols
        already subscribed are skipped at the broker layer."""

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        """Unsubscribe Quote push for ``symbols``. Idempotent. Called on
        watch-list shrinkage and broker teardown (account switch)."""

    def fetch_trading_sessions(self) -> dict[str, list[tuple[Any, Any, str]]]:
        """Return today's trading-session windows per market (SDK
        ``trading_session()``). Output shape: ``{market_code: [(begin,
        end, session_state)]}``. ``session_state`` ∈ {"regular", "pre",
        "post", "overnight"}. Holidays return an empty window list for
        that market. Used by :class:`MarketSchedule` so it doesn't reach
        into the broker's SDK directly."""

    def fetch_trading_days(
        self,
        *,
        days_back: int = 3,
    ) -> dict[str, list[Any]]:
        """Return the most recent ``days_back`` trading days per market
        (calendar-aware — skips weekends + holidays). Output: ``{market:
        [date, ...]}`` newest-first. Used to resolve "yesterday's close
        of record" when the calendar has a holiday."""

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order by broker-assigned order_id.

        On ``dry_run=True`` implementations should log + no-op rather than
        making a network call.  Raises on failure.
        """

    def replace_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
    ) -> None:
        """Modify an existing live order; preserves queue priority.

        At least one of quantity or price must be supplied. Raises
        ValueError if neither is given; lets SDK exceptions propagate
        for caller-side translation to HTTP 409/502.
        """
        ...

    def today_orders(
        self, *, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        """Return today's orders across all states (pending, partial,
        filled, cancelled, rejected). Optional client-side ticker filter.
        Schema: ``{order_id, symbol, ticker, side, order_type, price,
        quantity, executed_quantity, status, submitted_at}``.
        """
        ...

    def close(self) -> None:
        """Release SDK resources.  Safe to call multiple times."""
