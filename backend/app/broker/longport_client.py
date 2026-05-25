"""LongPortClient — concrete BrokerClient backed by longport SDK.

Wraps sync ``TradeContext`` / ``QuoteContext``.  Push callbacks fan out to
subscribers on the SDK's own thread — callers needing asyncio should bridge
via ``loop.call_soon_threadsafe`` in their handler.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from datetime import date, datetime, time  # noqa: F401  (datetime used in get_candlesticks forward ref)
from decimal import Decimal
from typing import Any

from longbridge.openapi import (
    Config as LPConfig,
)
from longbridge.openapi import (
    OAuthBuilder,
)
from longbridge.openapi import (
    OrderSide as LPOrderSide,
)
from longbridge.openapi import (
    OrderType as LPOrderType,
)
from longbridge.openapi import (
    AdjustType,
    Period,
    PushQuote,
    QuoteContext,
    SubType,
    TimeInForceType,
    TopicType,
    TradeContext,
    TradeSessions,
)


# LongBridge ``TradeSession`` enum → our wire state. The SDK returns one
# Intraday window for regular sessions, plus optionally Pre/Post/Overnight
# windows for US markets. Anything outside all listed windows is "closed".
_TRADE_SESSION_TO_STATE: dict[str, str] = {
    "Intraday": "regular",
    "Pre": "pre",
    "Post": "post",
    "Overnight": "overnight",
}

# Trading-session schedule + day calendar live in ``MarketSchedule``
# now (app.broker.market_schedule). LongPortClient just delegates state
# lookups to whichever instance ``bind_market_schedule`` injects.

from app.broker.broker_client import OrderSide, OrderType
from app.broker.config import LongPortConfig
from app.broker.oauth import is_authorized
from app.broker.order_id_norm import normalize_broker_order_id

logger = logging.getLogger(__name__)


def _quote_to_dict(q: Any, state: str | None = None) -> dict[str, Any]:
    """Normalize an SDK SecurityQuote / OptionQuote into our wire shape.

    Session-aware change% reference (the bit users care about):

      - **盘前 / 盘中** → reference = yesterday's RTH close
        (``SecurityQuote.prev_close``). Change = today's price vs yesterday.
      - **盘后 / 夜盘** → reference = TODAY's RTH close
        (``SecurityQuote.last_done`` — frozen at the 16:00 ET close once
        post-market starts). Change = post/overnight tick vs today's close.

    These two "closes" are intentionally different values: during Wed
    post-market, "yesterday's close" is Tuesday's; "today's close" is
    Wed's (just frozen). The user wants the post-market chip to show
    the move since 16:00 today, NOT cumulative since yesterday.

    ``today_close`` is surfaced as its own field (``None`` outside
    post/overnight) so the frontend can decide how to display it and so
    the push-handler cache can pick it up via a per-symbol seed.

    Tier selection for displayed ``last_done`` is unchanged:
      - ``"pre"``       → ``pre_market_quote`` (US)
      - ``"post"``      → ``post_market_quote`` (US)
      - ``"overnight"`` → ``overnight_quote`` (US)
      - else → regular SecurityQuote
    """
    if state is None:
        from app.broker.market_hours import market_state_for
        symbol = str(getattr(q, "symbol", ""))
        state = market_state_for(symbol)

    tier = {
        "pre": getattr(q, "pre_market_quote", None),
        "post": getattr(q, "post_market_quote", None),
        "overnight": getattr(q, "overnight_quote", None),
    }.get(state)
    # On closed state (weekend / holiday), the broker's main last_done
    # is the most recent RTH close — but the user-visible "现价" should
    # be the freshest reported tick, which is whichever extended-hours
    # tier reported last. Prefer overnight > post > rth so the chart's
    # current price + Day P/L reflect Friday's full session including
    # the post-market drift (e.g. 14.760 not 15.060 if TSLL drifted
    # down after the bell).
    if state == "closed" and tier is None:
        over = getattr(q, "overnight_quote", None)
        post = getattr(q, "post_market_quote", None)
        if over is not None and float(getattr(over, "last_done", 0) or 0) > 0:
            tier = over
        elif post is not None and float(getattr(post, "last_done", 0) or 0) > 0:
            tier = post
    if tier is None or float(getattr(tier, "last_done", 0) or 0) <= 0:
        chosen = q
    else:
        chosen = tier

    last_done = float(getattr(chosen, "last_done", 0) or 0)
    prev_close = float(getattr(q, "prev_close", 0) or 0)
    # today_close: only meaningful once today's RTH session has ended.
    # During post / overnight, SecurityQuote.last_done is frozen at the
    # 16:00 ET close — that IS today's close. Outside those sessions
    # there's no "today's close" yet (or it would equal prev_close).
    if state in ("post", "overnight"):
        today_close = float(getattr(q, "last_done", 0) or 0) or None
    else:
        today_close = None

    reference = today_close if (state in ("post", "overnight") and today_close) else prev_close
    if reference > 0:
        change = last_done - reference
        change_pct = (change / reference) * 100.0
    else:
        change = 0.0
        change_pct = 0.0

    return {
        "last_done": last_done,
        "prev_close": prev_close,
        "today_close": today_close,
        "open": float(getattr(q, "open", 0) or 0),
        "high": float(getattr(chosen, "high", 0) or 0),
        "low": float(getattr(chosen, "low", 0) or 0),
        "volume": int(getattr(chosen, "volume", 0) or 0),
        "turnover": float(getattr(chosen, "turnover", 0) or 0),
        "change": change,
        "change_pct": change_pct,
        "trade_session": state,
    }


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
        # Quote push: single handler (owned by QuoteHub), populated via
        # set_on_quote. Symbols this client has SDK-subscribed are tracked
        # so subscribe/unsubscribe is idempotent.
        self._quote_handler: Callable[[str, dict[str, Any]], None] | None = None
        self._subscribed_quote_symbols: set[str] = set()
        # Per-symbol reference-price cache used by the push handler. SDK
        # ``PushQuote`` events carry only the live last_done — they omit
        # ``prev_close`` and the pre/post/overnight tier sub-quotes. We
        # seed this cache on ``subscribe_quotes`` with a one-shot
        # ``get_quote`` so the push handler can compute change% against
        # the correct reference (yesterday's RTH close or today's RTH
        # close, depending on session). Entries are refreshed on
        # session transition so today_close picks up when RTH ends.
        # Shape: ``symbol → {prev_close, today_close, last_session}``.
        self._ref_price_cache: dict[str, dict[str, Any]] = {}
        # Trading-day-prev close cache for closed-state quote override.
        # On a closed view (weekend / holiday), the SDK's ``prev_close``
        # points at the most recent trading day's close (Friday's close
        # on Saturday), which would give a post-market-only change. Day
        # P/L and 涨跌幅 should reflect the full last-session move, so
        # we override with the close of the trading day BEFORE the most
        # recent one (Thursday's close on Saturday). Lazily filled by
        # ``_prev_session_close``; dropped per-symbol when the session
        # transitions out of closed.
        self._prev_session_close_cache: dict[str, float] = {}
        self._closed = False

        # OAuth construction: the SDK persists tokens on disk per
        # account_id (= the OAuth client_id we registered for this
        # account). build() reuses the cached token when one exists; we
        # guard with ``is_authorized`` so this path is only entered when a
        # token cache exists — the caller (broker init) catches the
        # ValueError below and falls back to NoopBrokerClient with a
        # "未授权" status.
        if not is_authorized(config.account_id):
            raise ValueError(
                f"OAuth token cache missing for account_id={config.account_id!r}; "
                "complete the LongBridge login flow in the UI first."
            )
        oauth = OAuthBuilder(config.account_id).build(lambda url: None)
        # enable_overnight=True is required to receive US overnight bars
        # and quote pushes. Per LongBridge FAQ Q6 / Q7, overnight data is
        # opt-in: even with the "LV1 Real-time (OpenAPI)" market-data card
        # purchased, the SDK auth must signal need_over_night_quote=true
        # for the broker to emit it. Without this flag, sessions=All
        # candlestick calls silently exclude the overnight window.
        # (HK doesn't have overnight; the flag is harmless there.)
        lp_config = LPConfig.from_oauth(oauth, enable_overnight=True)

        # QuoteContext first (mirrors old broker — avoids connection-count
        # leak if TradeContext creation fails).
        self._quote_ctx: QuoteContext | None = QuoteContext(lp_config)
        self._trade_ctx: TradeContext | None = TradeContext(lp_config)
        # Bound by ``bind_market_schedule`` once the global
        # ``MarketSchedule`` instance is created at lifespan startup.
        # Until then, ``_market_state_for`` falls back to the static
        # clock heuristic in ``market_hours``.
        self._market_schedule: Any | None = None

        # Wire push callback — fans out to all registered handlers.
        self._trade_ctx.set_on_order_changed(self._on_order_changed)
        # Subscribe to the Private topic so the SDK actually delivers
        # order-changed pushes. set_on_order_changed alone only registers
        # the callback; without subscribe([TopicType.Private]) the SDK never
        # pushes anything and submitted orders sit at PENDING forever.
        self._trade_ctx.subscribe([TopicType.Private])

        # Quote push trampoline: SDK fires set_on_quote callback for any
        # symbol we've subscribed via QuoteContext.subscribe([SubType.Quote]).
        # ``_on_quote`` normalizes PushQuote → dict then delegates to the
        # handler installed by QuoteHub. Registering up-front keeps the
        # dispatch path in place before the first subscribe.
        self._quote_ctx.set_on_quote(self._on_quote)

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def account_id(self) -> str:
        """OAuth client_id of the active account; used for DB tagging so
        trades / pairs / tasks etc. can be filtered by account."""
        return self._config.account_id

    @property
    def account_label(self) -> str:
        """User-chosen display label for the active account."""
        return self._config.label

    @property
    def is_paper(self) -> bool:
        """LongBridge OpenAPI has no paper-trading mode — every authorized
        account hits the live endpoint. Kept on the Protocol for backward
        compat (and so the noop/sim brokers can claim ``is_paper=True``),
        but always False for the real SDK-backed client. """
        return False

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

    def replace_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
    ) -> None:
        if quantity is None and price is None:
            raise ValueError("replace_order requires quantity or price")
        # The dry_run property reads self._dry_run_getter (set in __init__).
        # Test helpers that bypass __init__ via LongPortClient.__new__ never
        # set _dry_run_getter, so the property raises AttributeError.  Until
        # the test factory is updated to fully initialise the instance, the
        # try/except is the least-invasive guard.  The fallback reads
        # _dry_run, which those same helpers set directly.
        try:
            dry = self.dry_run
        except AttributeError:
            dry = bool(getattr(self, "_dry_run", False))
        if dry:
            logger.info(
                "[DRY RUN] replace_order order_id=%s qty=%s price=%s — skipped",
                order_id, quantity, price,
            )
            return
        if self._trade_ctx is None:
            raise RuntimeError("LongPortClient has been closed")
        # LongPort SDK's TradeContext.replace_order requires BOTH quantity
        # and price on every call. When the caller only supplied one (e.g.
        # the user is modifying price only), fall back to the order's
        # current value for the other field.
        if quantity is None or price is None:
            existing = next(
                (o for o in self.today_orders() if o["order_id"] == order_id),
                None,
            )
            if existing is None:
                raise ValueError(f"order not found: {order_id}")
            if quantity is None:
                quantity = existing["quantity"]
            if price is None:
                price = existing["price"]
        self._trade_ctx.replace_order(
            order_id=order_id, quantity=quantity, price=price,
        )

    def today_orders(
        self, *, ticker: str | None = None
    ) -> list[dict[str, Any]]:
        if self._trade_ctx is None:
            raise RuntimeError("LongPortClient has been closed")
        raw = self._trade_ctx.today_orders() or []
        out: list[dict[str, Any]] = []
        for o in raw:
            symbol = getattr(o, "symbol", None) or ""
            tkr = symbol.split(".")[0] if symbol else ""
            if ticker is not None and tkr != ticker:
                continue
            out.append({
                "order_id": getattr(o, "order_id", ""),
                "symbol": symbol,
                "ticker": tkr,
                "side": str(getattr(o, "side", "")),
                "order_type": str(getattr(o, "order_type", "")),
                "price": float(getattr(o, "price", 0.0) or 0.0),
                "quantity": int(getattr(o, "quantity", 0) or 0),
                "executed_quantity": int(getattr(o, "executed_quantity", 0) or 0),
                "status": str(getattr(o, "status", "")),
                "submitted_at": getattr(o, "submitted_at", None),
            })
        return out

    # ------------------------------------------------------------------ #
    # Quotes                                                               #
    # ------------------------------------------------------------------ #

    def _market_state_for(self, symbol: str) -> str:
        """Resolve current trading state for ``symbol``'s market.

        Delegates to the project-wide ``MarketSchedule`` singleton when
        one has been bound via :meth:`bind_market_schedule` (main.py wires
        this during lifespan). If no schedule is bound (early startup or
        unit-test paths), falls back to the static clock heuristic — same
        windows as the SDK schedule for normal trading days, ignores
        holidays.
        """
        market = symbol.rsplit(".", 1)[-1].upper() if "." in symbol else ""
        if market not in {"US", "HK", "SH", "SZ"}:
            return "regular"

        if self._market_schedule is not None:
            return self._market_schedule.state_for(market)

        from app.broker.market_hours import market_state_for
        return market_state_for(symbol)

    def bind_market_schedule(self, schedule: Any) -> None:
        """Inject the global :class:`MarketSchedule` so quote/state
        lookups delegate to it. Called by main.py after the schedule
        is constructed for this broker."""
        self._market_schedule = schedule

    def fetch_trading_sessions(self) -> dict[str, list[tuple[time, time, str]]]:
        """BrokerClient implementation — pulls one ``trading_session()``
        and normalises the SDK ``MarketTradingSession`` list into the
        protocol-defined ``{market: [(begin, end, state)]}`` shape."""
        if self._quote_ctx is None:
            return {}
        resp = self._quote_ctx.trading_session()
        out: dict[str, list[tuple[time, time, str]]] = {}
        for mkt in resp or []:
            market_str = str(getattr(mkt, "market", "")).rsplit(".", 1)[-1].upper()
            if not market_str:
                continue
            windows: list[tuple[time, time, str]] = []
            for w in getattr(mkt, "trade_sessions", []) or []:
                begin = getattr(w, "begin_time", None)
                end = getattr(w, "end_time", None)
                session = str(getattr(w, "trade_session", "")).rsplit(".", 1)[-1]
                state = _TRADE_SESSION_TO_STATE.get(session, "regular")
                windows.append((begin, end, state))
            out[market_str] = windows
        return out

    def fetch_trading_days(self, *, days_back: int = 3) -> dict[str, list[date]]:
        """BrokerClient implementation — pulls ``trading_days`` per
        market for a look-back window and returns the newest-first list.

        The SDK requires explicit ``Market`` enums; we iterate the three
        markets we actually surface (US / HK / CN) so callers don't have
        to enumerate them. Failure for one market leaves it out of the
        result; other markets still load.
        """
        if self._quote_ctx is None:
            return {}
        from longbridge.openapi import Market as LPMarket

        end = date.today()
        # Pull a wider calendar window than ``days_back`` to absorb
        # weekends and holidays — 14 days back gives us at least 3 trading
        # days in every reasonable holiday pattern.
        begin = end - __import__("datetime").timedelta(days=14)
        markets = (("US", LPMarket.US), ("HK", LPMarket.HK), ("CN", LPMarket.CN))
        out: dict[str, list[date]] = {}
        for code, market_enum in markets:
            try:
                resp = self._quote_ctx.trading_days(market_enum, begin, end)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "trading_days fetch for %s failed: %s — skipping", code, exc,
                )
                continue
            trading: list[date] = list(getattr(resp, "trading_days", []) or [])
            # Newest-first, capped to ``days_back``. half_trading_days
            # (HK 半日) are also trading days for our purposes — include them.
            trading.extend(getattr(resp, "half_trading_days", []) or [])
            trading.sort(reverse=True)
            out[code] = trading[:days_back]
        return out

    def get_quote(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch latest quotes; returns ``{symbol: {last_done, open, ...}}``.

        Option symbols (OCC format like ``TSLA250117C300000.US``) need the
        dedicated ``option_quote`` SDK call — the regular ``quote`` API only
        covers equities/ETFs/indices. We classify each symbol and call the
        appropriate endpoint, then merge.
        """
        if self._quote_ctx is None:
            raise RuntimeError("LongPortClient has been closed")
        from app.broker.symbol_classify import parse_option_symbol

        stock_syms: list[str] = []
        option_syms: list[str] = []
        for s in symbols:
            (option_syms if parse_option_symbol(s) is not None else stock_syms).append(s)

        result: dict[str, dict[str, Any]] = {}
        if stock_syms:
            for q in self._quote_ctx.quote(stock_syms):
                state = self._market_state_for(q.symbol)
                row = _quote_to_dict(q, state)
                self._apply_closed_state_baseline(q.symbol, state, row)
                result[q.symbol] = row
        if option_syms:
            # ``option_quote`` returns OptionQuote with the same last_done /
            # prev_close / open / high / low / volume / turnover fields, so
            # the same converter handles both.
            for q in self._quote_ctx.option_quote(option_syms):
                result[q.symbol] = _quote_to_dict(q, self._market_state_for(q.symbol))
        return result

    def _prev_session_close(self, symbol: str) -> float | None:
        """Return the close of the trading day BEFORE the most recent one.

        Used to anchor change% / Day P/L on closed-state views (weekend
        / holiday). The SDK's regular ``prev_close`` points at the most
        recent close (= Friday's close on Saturday) — that's only one
        session away from ``last_done``, so the implied change is tiny.
        The user wants "Friday's full session move", which requires the
        close BEFORE Friday's session = Thursday's close.

        Fetches the last 2 daily candles (RTH only) and returns the
        older one's close. Cached per-symbol; dropped when the session
        transitions out of closed (see ``_update_ref_cache``).
        """
        if self._quote_ctx is None:
            return None
        cached = self._prev_session_close_cache.get(symbol)
        if cached is not None:
            return cached
        try:
            bars = self._quote_ctx.candlesticks(
                symbol,
                Period.Day,
                2,
                AdjustType.NoAdjust,
                trade_sessions=TradeSessions.Intraday,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LongPortClient: prev-session-close fetch failed for %s: %s",
                symbol, exc,
            )
            return None
        if not bars or len(bars) < 2:
            return None
        # candlesticks() returns oldest-first; the second-from-last is the
        # one we want (the close BEFORE the most recent trading day).
        prev = float(getattr(bars[-2], "close", 0) or 0)
        if prev <= 0:
            return None
        self._prev_session_close_cache[symbol] = prev
        return prev

    def _apply_closed_state_baseline(
        self, symbol: str, state: str, row: dict[str, Any],
    ) -> None:
        """Mutate ``row`` in place so closed-state change/change_pct are
        anchored at the previous trading day's close. No-op for other
        states. Used by both ``get_quote`` (HTTP) and the push handler
        path (via ``_update_ref_cache``)."""
        if state != "closed":
            return
        prev = self._prev_session_close(symbol)
        if prev is None or prev <= 0:
            return
        last = float(row.get("last_done") or 0)
        row["prev_close"] = prev
        row["change"] = last - prev
        row["change_pct"] = (row["change"] / prev) * 100.0 if prev > 0 else 0.0

    @staticmethod
    def _sdk_order_side(order: Any) -> str:
        side_attr = getattr(order, "side", None)
        if side_attr is None:
            return ""
        return str(side_attr).split(".")[-1].upper()

    @staticmethod
    def _ingest_orders(side_by_order: dict[str, str], orders: Any) -> None:
        for o in orders or []:
            order_id = str(getattr(o, "order_id", ""))
            if order_id:
                side_by_order[order_id] = LongPortClient._sdk_order_side(o)

    @staticmethod
    def _execution_dedupe_key(execution: Any) -> tuple[str, ...]:
        trade_id = str(getattr(execution, "trade_id", "") or "")
        if trade_id:
            return ("trade_id", trade_id)
        return (
            "fallback",
            str(getattr(execution, "order_id", "")),
            str(getattr(execution, "trade_done_at", "")),
            str(getattr(execution, "quantity", "")),
        )

    @staticmethod
    def _window_includes_today_slice(end: "datetime") -> bool:
        """Only merge SDK ``today_*`` when the window ends near now.

        Historical 90-day backfill chunks end in the past; calling
        ``today_executions()`` there would inject current-day fills into
        the wrong chunk.
        """
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        end_utc = end if end.tzinfo is not None else end.replace(tzinfo=timezone.utc)
        return (now - end_utc) <= timedelta(days=1)

    def _fetch_executions_window(
        self,
        *,
        ticker: str | None,
        start: "datetime",
        end: "datetime",
    ) -> list[dict[str, Any]]:
        """Common path for ``today_executions`` / ``history_executions``.

        LongBridge splits **today** vs **history** into separate SDK
        endpoints. Unsettled intraday fills live under ``today_executions``
        / ``today_orders``; settled fills appear in ``history_*``. We union
        both (dedupe fills by ``trade_id``) and merge order sides from both
        order endpoints so executions are not dropped when a fill's
        ``order_id`` only exists in ``today_orders``.

        The optional ``ticker`` filter is applied AFTER fetching because
        the SDK's ``symbol`` filter accepts only one symbol at a time — for
        option positions on a ticker we want all contracts.

        Caller contract: ``end - start`` MUST be ≤ 90 days. LongBridge
        rejects wider single calls to both ``history_orders`` and
        ``history_executions``; the chunking happens in
        ``executions_sync._sync_chunked``. See
        ``knowledge/longbridge-api-limits.md``.
        """
        from datetime import datetime, timedelta, timezone
        from app.broker.symbol_classify import parse_option_symbol

        if self._trade_ctx is None:
            raise RuntimeError("LongPortClient has been closed")

        now = end
        include_today = self._window_includes_today_slice(now)

        side_by_order: dict[str, str] = {}
        try:
            history_orders = self._trade_ctx.history_orders(
                start_at=start, end_at=now,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("history_orders fetch failed: %s", exc)
            history_orders = []
        self._ingest_orders(side_by_order, history_orders)

        if include_today:
            try:
                today_orders = self._trade_ctx.today_orders()
            except Exception as exc:  # noqa: BLE001
                logger.warning("today_orders fetch failed: %s", exc)
                today_orders = []
            self._ingest_orders(side_by_order, today_orders)

        execs_merged: list[Any] = []
        seen_keys: set[tuple[str, ...]] = set()
        n_today_execs = 0
        n_hist_execs = 0

        def _append_execs(batch: Any) -> None:
            for e in batch or []:
                key = self._execution_dedupe_key(e)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                execs_merged.append(e)

        if include_today:
            try:
                today_execs = self._trade_ctx.today_executions()
                n_today_execs = len(today_execs or [])
                _append_execs(today_execs)
            except Exception as exc:  # noqa: BLE001
                logger.warning("today_executions fetch failed: %s", exc)

        try:
            history_execs = self._trade_ctx.history_executions(
                start_at=start, end_at=now,
            )
            n_hist_execs = len(history_execs or [])
            _append_execs(history_execs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("history_executions fetch failed: %s", exc)

        out: list[dict[str, Any]] = []
        dropped_side = 0
        for e in execs_merged:
            order_id = str(getattr(e, "order_id", ""))
            side = side_by_order.get(order_id, "")
            if side not in ("BUY", "SELL"):
                dropped_side += 1
                continue
            symbol = str(getattr(e, "symbol", ""))
            leg = parse_option_symbol(symbol)
            if leg is not None:
                row_ticker = leg.ticker
            else:
                row_ticker = symbol.split(".")[0] if "." in symbol else symbol
            if ticker is not None and row_ticker != ticker:
                continue
            qty_raw = getattr(e, "quantity", 0)
            price_raw = getattr(e, "price", 0)
            try:
                qty = int(qty_raw)
            except (TypeError, ValueError):
                qty = 0
            try:
                price = float(price_raw)
            except (TypeError, ValueError):
                price = 0.0
            ts = getattr(e, "trade_done_at", None)
            if ts is None:
                continue
            # LongBridge returns trade_done_at as a naive datetime in HK
            # local time. Pin to UTC+8 before serializing.
            if isinstance(ts, datetime) and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone(timedelta(hours=8)))
            out.append({
                "order_id": order_id,
                "trade_id": str(getattr(e, "trade_id", "")),
                "symbol": symbol,
                "ticker": row_ticker,
                "side": side,
                "qty": qty,
                "price": price,
                "ts": ts,
            })

        logger.debug(
            "executions_window [%s..%s] include_today=%s: "
            "orders=%d execs_merged=%d (today=%d history=%d) out=%d dropped_side=%d",
            start,
            now,
            include_today,
            len(side_by_order),
            len(execs_merged),
            n_today_execs,
            n_hist_execs,
            len(out),
            dropped_side,
        )
        return out

    def today_executions(self) -> list[dict[str, Any]]:
        """Fetch broker-side fills for the current trading window.

        Unions SDK ``today_executions`` with a 30-hour
        ``history_executions`` slice (HK/BJ vs ET calendar quirks — see
        ``knowledge/longbridge-api-limits.md`` §2). Frontend filters to the
        current ET session where needed.
        """
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        return self._fetch_executions_window(
            ticker=None, start=now - timedelta(hours=30), end=now,
        )

    def history_executions(
        self,
        *,
        ticker: str | None = None,
        days: int = 30,
        start_at: "datetime | None" = None,
        end_at: "datetime | None" = None,
    ) -> list[dict[str, Any]]:
        """Historical fills, either over an explicit UTC range
        (``start_at`` / ``end_at``) or the rolling ``days`` window.

        Either form MUST resolve to a window ≤ 90 days — LongBridge's
        ``history_executions`` rejects anything wider. Chunking lives
        in ``executions_sync._sync_chunked``; this method delegates
        one chunk per call.
        """
        from datetime import datetime, timedelta, timezone

        if start_at is not None and end_at is not None:
            return self._fetch_executions_window(
                ticker=ticker, start=start_at, end=end_at,
            )
        now = datetime.now(timezone.utc)
        return self._fetch_executions_window(
            ticker=ticker, start=now - timedelta(days=days), end=now,
        )

    def stock_positions(self) -> list[dict[str, Any]]:
        """Fetch current stock holdings (and option contracts — Longbridge
        ships both under the same channel; option symbols carry OCC suffix).

        Zero-quantity rows are filtered out: switching trading mode brings
        in a different account whose positions are entirely different, and
        the broker can echo back stale "previously held" rows with qty=0
        that would otherwise clutter the dashboard.
        """
        if self._trade_ctx is None:
            raise RuntimeError("LongPortClient has been closed")
        resp = self._trade_ctx.stock_positions()
        out: list[dict[str, Any]] = []
        for channel in getattr(resp, "channels", []) or []:
            for p in getattr(channel, "positions", []) or []:
                symbol = str(getattr(p, "symbol", ""))
                qty = int(getattr(p, "quantity", 0) or 0)
                if qty == 0:
                    continue
                # Derive a user-facing ticker by removing the market suffix.
                # Symbols are always "<TICKER>.<MARKET>"; if not, use as-is.
                ticker = symbol.split(".")[0] if "." in symbol else symbol
                out.append({
                    "symbol": symbol,
                    "ticker": ticker,
                    "name": str(getattr(p, "symbol_name", "")) or None,
                    "quantity": qty,
                    "avg_cost": float(getattr(p, "cost_price", 0) or 0) or None,
                    "currency": str(getattr(p, "currency", "")) or None,
                })
        return out

    # SDK period name → enum, in the values supported by /api/candlesticks.
    _SDK_PERIODS = {
        "min_1": Period.Min_1,
        "min_2": Period.Min_2,
        "min_3": Period.Min_3,
        "min_5": Period.Min_5,
        "min_15": Period.Min_15,
        "min_30": Period.Min_30,
        "min_60": Period.Min_60,
        "day": Period.Day,
        "week": Period.Week,
        "month": Period.Month,
        "year": Period.Year,
        # Legacy alias retained so older callers that pass "intraday" keep
        # working without a code change.
        "intraday": Period.Min_5,
    }

    _SDK_SESSIONS = {
        "regular": TradeSessions.Intraday,
        "all": TradeSessions.All,
    }

    def get_candlesticks(
        self,
        symbol: str,
        *,
        period: str,
        count: int,
        sessions: str = "regular",
        before: "datetime | None" = None,
    ) -> list[dict[str, Any]]:
        """Fetch historical candlesticks at the requested granularity.

        ``period`` accepts the granular SDK-style names ``min_1`` / ``min_5``
        / ``min_15`` / ``min_30`` / ``min_60`` / ``day`` — the HTTP layer
        translates user-facing period strings (``today`` / ``5`` / … /
        ``90``) into a (granularity, count) pair before calling here.

        When ``before`` is provided we use the SDK's
        ``history_candlesticks_by_offset`` with ``forward=False`` so the
        N bars strictly older than that instant come back; otherwise we
        use the latest-N ``candlesticks`` call.
        """
        if self._quote_ctx is None:
            raise RuntimeError("LongPortClient has been closed")

        sdk_period = self._SDK_PERIODS.get(period)
        if sdk_period is None:
            raise ValueError(
                f"unknown period {period!r}; expected one of "
                f"{sorted(self._SDK_PERIODS)}"
            )
        sdk_sessions = self._SDK_SESSIONS.get(sessions)
        if sdk_sessions is None:
            raise ValueError(
                f"unknown sessions {sessions!r}; expected 'regular' or 'all'"
            )

        if before is not None:
            bars = self._quote_ctx.history_candlesticks_by_offset(
                symbol,
                sdk_period,
                AdjustType.NoAdjust,
                False,  # forward=False → bars older than `time`
                count,
                time=before,
                trade_sessions=sdk_sessions,
            )
        else:
            bars = self._quote_ctx.candlesticks(
                symbol,
                sdk_period,
                count,
                AdjustType.NoAdjust,
                trade_sessions=sdk_sessions,
            )
        result: list[dict[str, Any]] = []
        for c in bars:
            # SDK returns timestamp as datetime in exchange tz; ISO-format for
            # JSON serialization downstream.
            result.append({
                "timestamp": c.timestamp.isoformat() if c.timestamp else None,
                "open": float(c.open) if c.open else 0.0,
                "high": float(c.high) if c.high else 0.0,
                "low": float(c.low) if c.low else 0.0,
                "close": float(c.close) if c.close else 0.0,
                "volume": int(c.volume) if c.volume else 0,
                "turnover": float(c.turnover) if c.turnover else 0.0,
            })
        return result

    # ------------------------------------------------------------------ #
    # Push                                                                 #
    # ------------------------------------------------------------------ #

    def subscribe_order_push(self, handler: Callable[[Any], None]) -> None:
        """Register a callback for order-change push events."""
        self._push_handlers.append(handler)

    def set_on_quote(
        self, handler: Callable[[str, dict[str, Any]], None]
    ) -> None:
        """Install QuoteHub's adapter as the (single) quote-push handler."""
        self._quote_handler = handler

    def subscribe_quotes(self, symbols: list[str]) -> None:
        """SDK-subscribe Quote sub-type for ``symbols``. Dedups against
        the local ``_subscribed_quote_symbols`` set so repeated watch
        updates with overlapping lists don't blast the SDK.

        Also seeds the per-symbol reference-price cache with one SDK
        ``get_quote`` so the first push for each symbol already has the
        right change% reference. Seeding failure is logged but doesn't
        block the subscribe.
        """
        if self._quote_ctx is None:
            return
        new_syms = [s for s in symbols if s not in self._subscribed_quote_symbols]
        if not new_syms:
            return
        try:
            self._quote_ctx.subscribe(new_syms, [SubType.Quote])
            self._subscribed_quote_symbols.update(new_syms)
            logger.info(
                "LongPortClient: subscribed %d quote symbol(s): %s",
                len(new_syms), new_syms,
            )
        except Exception:
            logger.exception("LongPortClient: subscribe_quotes failed for %s", new_syms)
        self._seed_ref_price_cache(new_syms)

    def _seed_ref_price_cache(self, symbols: list[str]) -> None:
        """Populate ``_ref_price_cache`` from one ``get_quote`` per batch.

        Splits options vs stocks because the SDK uses different endpoints
        — options also lack the pre/post tier fields, but their cache
        entry still records ``prev_close`` so option-card change% works.
        """
        if not symbols or self._quote_ctx is None:
            return
        from app.broker.symbol_classify import parse_option_symbol

        stock_syms = [s for s in symbols if parse_option_symbol(s) is None]
        option_syms = [s for s in symbols if parse_option_symbol(s) is not None]
        try:
            if stock_syms:
                for q in self._quote_ctx.quote(stock_syms):
                    self._update_ref_cache(q.symbol, q)
            if option_syms:
                for q in self._quote_ctx.option_quote(option_syms):
                    self._update_ref_cache(q.symbol, q)
        except Exception:
            logger.exception("LongPortClient: ref-price cache seed failed for %s", symbols)

    def _update_ref_cache(self, symbol: str, q: Any) -> None:
        """Refresh one cache entry from a fresh SecurityQuote / OptionQuote."""
        state = self._market_state_for(symbol)
        prev = float(getattr(q, "prev_close", 0) or 0)
        # today_close: only valid during post/overnight (SDK has frozen
        # last_done at the RTH close). During pre/regular, leave it None
        # so the push handler falls back to prev_close.
        if state in ("post", "overnight"):
            today = float(getattr(q, "last_done", 0) or 0) or None
        else:
            today = None
        # Closed state: override prev_close with the close of the trading
        # day BEFORE the most recent one (Thursday's close on Saturday)
        # so the push handler's change% / Day P/L reflects the full last-
        # session move. Drop the override when state transitions out of
        # closed so a future re-seed picks up fresh broker semantics.
        if state == "closed":
            override = self._prev_session_close(symbol)
            if override is not None and override > 0:
                prev = override
        else:
            self._prev_session_close_cache.pop(symbol, None)
        self._ref_price_cache[symbol] = {
            "prev_close": prev,
            "today_close": today,
            "last_session": state,
        }

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        """SDK-unsubscribe Quote sub-type. Gates via the local set so the
        SDK only sees symbols we actually subscribed (cleaner logs)."""
        if self._quote_ctx is None:
            return
        old_syms = [s for s in symbols if s in self._subscribed_quote_symbols]
        if not old_syms:
            return
        try:
            self._quote_ctx.unsubscribe(old_syms, [SubType.Quote])
            self._subscribed_quote_symbols.difference_update(old_syms)
            logger.info(
                "LongPortClient: unsubscribed %d quote symbol(s): %s",
                len(old_syms), old_syms,
            )
        except Exception:
            logger.exception("LongPortClient: unsubscribe_quotes failed for %s", old_syms)

    def _on_quote(self, symbol: str, event: PushQuote) -> None:
        """SDK quote-push trampoline → normalized dict → user handler.

        Computes change% session-aware: 盘前/盘中 vs yesterday's RTH
        close (prev_close), 盘后/夜盘 vs today's RTH close (today_close).
        Both reference prices live in ``_ref_price_cache`` — seeded by
        ``subscribe_quotes`` and refreshed lazily on session transition
        (e.g. regular → post crossing the 16:00 ET boundary), so the
        push handler doesn't need to call back into the SDK on every tick.

        Runs on the SDK's own thread. The downstream handler (the
        SubscriptionManager fan-out) marshals onto asyncio via
        ``loop.call_soon_threadsafe`` for bus publish.
        """
        handler = self._quote_handler
        if handler is None:
            return
        try:
            state = self._market_state_for(symbol)
            cache = self._ref_price_cache.get(symbol)
            # Session transition (e.g. regular → post at 16:00 ET) →
            # re-seed so today_close picks up the just-frozen RTH close.
            # Skipped if cache is missing entirely (next branch handles it).
            if cache is not None and cache.get("last_session") != state:
                self._seed_ref_price_cache([symbol])
                cache = self._ref_price_cache.get(symbol)
            elif cache is None:
                self._seed_ref_price_cache([symbol])
                cache = self._ref_price_cache.get(symbol)

            prev_close = float((cache or {}).get("prev_close") or 0)
            today_close = (cache or {}).get("today_close")
            reference = (
                float(today_close)
                if (state in ("post", "overnight") and today_close)
                else prev_close
            )
            last_done = float(getattr(event, "last_done", 0) or 0)
            if reference > 0:
                change = last_done - reference
                change_pct = (change / reference) * 100.0
            else:
                change = 0.0
                change_pct = 0.0

            quote_dict: dict[str, Any] = {
                "last_done": last_done,
                "prev_close": prev_close,
                "today_close": float(today_close) if today_close else None,
                "open": float(getattr(event, "open", 0) or 0),
                "high": float(getattr(event, "high", 0) or 0),
                "low": float(getattr(event, "low", 0) or 0),
                "volume": int(getattr(event, "volume", 0) or 0),
                "turnover": float(getattr(event, "turnover", 0) or 0),
                "change": change,
                "change_pct": change_pct,
                "trade_session": state,
            }
            handler(symbol, quote_dict)
        except Exception:
            logger.exception("LongPortClient: quote-push handler raised")

    def _on_order_changed(self, event: Any) -> None:
        """SDK callback — fans out to all registered subscribers.

        Logged at INFO so we can correlate "broker submit at Tx" with
        "SDK push at Ty" when chasing missing-push reports — without it
        the only signal of "did the SDK actually deliver?" was the
        downstream PushListener log line, which doesn't fire if the
        push was dropped before reaching the listener.
        """
        order_id = getattr(event, "order_id", None)
        status = getattr(event, "status", None)
        logger.info(
            "LongPortClient: SDK push received order_id=%s status=%r handlers=%d",
            order_id,
            status,
            len(self._push_handlers),
        )
        for handler in list(self._push_handlers):
            try:
                handler(event)
            except Exception:
                logger.exception("Order push handler raised an exception; continuing")

    def is_noop(self) -> bool:
        return False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        """Release SDK resources.  Idempotent."""
        if self._closed:
            return
        self._closed = True
        for attr_name, ctx in (
            ("_quote_ctx", self._quote_ctx),
            ("_trade_ctx", self._trade_ctx),
        ):
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

        raw_id = getattr(resp, "order_id", None) or getattr(resp, "id", None) or str(resp)
        return normalize_broker_order_id(raw_id)
