"""Unified broker-push subscription manager.

Owns the broker's single ``set_on_quote`` slot AND piggybacks on
``subscribe_order_push`` for execution events. Provides a listener-bind
interface — clients register callbacks via :meth:`add_quote_listener` /
:meth:`add_execution_listener` and get back an unsubscribe handle.

This is the *single* abstraction over broker push streams in the project.
Bus integration is just one client (registered in ``main.py``); other
direct consumers (storage upserts, in-process trader hooks, debugging
hooks) can register their own listeners without touching the bus topic
graph.

Lifecycle: one manager per broker instance.

    mgr = SubscriptionManager(broker, loop)
    mgr.attach()
    unsub_q = mgr.add_quote_listener(on_quote)
    unsub_e = mgr.add_execution_listener(on_exec)
    await mgr.watch_quotes(["TSLA.US"])
    ...
    mgr.detach()  # called by main.py during _broker_reload before close()
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timezone
from typing import Any

from app.broker.broker_client import BrokerClient
from app.broker.symbol_classify import parse_option_symbol

logger = logging.getLogger(__name__)

QuoteListener = Callable[[str, dict[str, Any]], None]
ExecutionListener = Callable[[dict[str, Any]], None]
Unsubscribe = Callable[[], None]


# Order statuses we treat as "this is a fill event worth surfacing to
# the UI". LongBridge's ``PushOrderChanged`` fires for every state change
# (NotReported → New → Filled etc.); we only forward the fill states so
# downstream listeners can keep Day P/L math simple.
_FILL_STATUSES = {"Filled", "PartialFilled"}


def _normalize_execution(raw: Any) -> dict[str, Any] | None:
    """Convert an SDK ``PushOrderChanged`` event into the wire shape used
    by ``ExecutionOut`` / ``ExecutionPayload``. Returns ``None`` for
    non-fill events so listeners only see actual executions.

    Symbol parsing handles option contracts (OCC-format ``...US`` symbols)
    so ticker matches the user-facing underlying — same logic used by the
    polled ``today_executions`` path so push-driven and poll-driven rows
    are byte-identical.
    """
    status_str = str(getattr(raw, "status", "")).rsplit(".", 1)[-1]
    if status_str not in _FILL_STATUSES:
        return None
    order_id = str(getattr(raw, "order_id", "") or "")
    if not order_id:
        return None
    symbol = str(getattr(raw, "symbol", "") or "")
    leg = parse_option_symbol(symbol)
    if leg is not None:
        ticker = leg.ticker
    else:
        ticker = symbol.split(".", 1)[0] if "." in symbol else symbol
    side_str = str(getattr(raw, "side", "")).rsplit(".", 1)[-1].upper()
    if side_str not in ("BUY", "SELL"):
        return None
    qty_raw = getattr(raw, "executed_quantity", 0) or 0
    price_raw = getattr(raw, "executed_price", 0) or 0
    qty = int(qty_raw)
    if qty <= 0:
        return None
    ts = getattr(raw, "updated_at", None)
    ts_iso = (
        ts.isoformat() if hasattr(ts, "isoformat") else None
    )
    return {
        "order_id": order_id,
        "symbol": symbol,
        "ticker": ticker,
        "side": side_str,
        "qty": qty,
        "price": float(price_raw),
        "ts": ts_iso,
    }


class SubscriptionManager:
    """Coordinates broker push subscriptions + listener fan-out.

    Thread model: SDK callbacks fire on the SDK's own thread. Listeners
    receive the normalized dict on the SAME thread — listeners that need
    asyncio must marshal themselves (e.g. ``loop.call_soon_threadsafe``).
    Keeping the manager thread-naive means tests can call ``_dispatch_*``
    directly without spinning a loop.
    """

    def __init__(self, broker: BrokerClient, loop: asyncio.AbstractEventLoop) -> None:
        self._broker = broker
        self._loop = loop
        self._quote_listeners: list[QuoteListener] = []
        self._execution_listeners: list[ExecutionListener] = []
        self._watched_symbols: set[str] = set()
        self._attached = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def attach(self) -> None:
        """Install dispatchers on the broker's push slots. Idempotent."""
        if self._attached:
            return
        self._broker.set_on_quote(self._dispatch_quote)
        self._broker.subscribe_order_push(self._dispatch_execution)
        self._attached = True
        logger.info("SubscriptionManager: attached to broker push slots")

    def detach(self) -> None:
        """Unsubscribe everything currently watched. Called by the lifespan
        reload path before broker.close(); the next manager (on the new
        broker) starts with an empty watch list — clients re-issue
        watch_quotes after they fetch fresh positions.

        Listener lists are NOT cleared here — main.py re-registers its
        bus-publishing listeners against the freshly-built manager
        instance, so the prior list will be discarded when the manager
        itself is replaced. Tests can override by calling
        ``clear_listeners()``.
        """
        if not self._attached:
            return
        if self._watched_symbols:
            try:
                self._broker.unsubscribe_quotes(sorted(self._watched_symbols))
            except Exception:
                logger.exception("SubscriptionManager: unsubscribe_quotes failed")
            self._watched_symbols.clear()
        self._attached = False
        logger.info("SubscriptionManager: detached")

    def clear_listeners(self) -> None:
        """Drop all registered listeners. Test-only."""
        self._quote_listeners.clear()
        self._execution_listeners.clear()

    # ------------------------------------------------------------------ #
    # Listener binding                                                     #
    # ------------------------------------------------------------------ #

    def add_quote_listener(self, fn: QuoteListener) -> Unsubscribe:
        """Register ``fn`` to receive every dispatched quote push.
        Returns an idempotent unsubscribe handle."""
        self._quote_listeners.append(fn)

        def _unsub() -> None:
            try:
                self._quote_listeners.remove(fn)
            except ValueError:
                pass
        return _unsub

    def add_execution_listener(self, fn: ExecutionListener) -> Unsubscribe:
        """Register ``fn`` to receive every fill event (normalized to the
        wire shape — see :func:`_normalize_execution`)."""
        self._execution_listeners.append(fn)

        def _unsub() -> None:
            try:
                self._execution_listeners.remove(fn)
            except ValueError:
                pass
        return _unsub

    # ------------------------------------------------------------------ #
    # Quote watch set                                                      #
    # ------------------------------------------------------------------ #

    async def watch_quotes(self, symbols: list[str]) -> dict[str, int]:
        """Replace the watch list with ``symbols``. Backend diffs and
        emits subscribe/unsubscribe to the broker; returns counters for
        observability."""
        wanted = {s for s in symbols if s}
        to_add = sorted(wanted - self._watched_symbols)
        to_remove = sorted(self._watched_symbols - wanted)
        if to_remove:
            try:
                self._broker.unsubscribe_quotes(to_remove)
            except Exception:
                logger.exception("SubscriptionManager: unsubscribe failed %s", to_remove)
        if to_add:
            try:
                self._broker.subscribe_quotes(to_add)
            except Exception:
                logger.exception("SubscriptionManager: subscribe failed %s", to_add)
        self._watched_symbols = wanted
        return {
            "added": len(to_add),
            "removed": len(to_remove),
            "total": len(self._watched_symbols),
        }

    @property
    def watched_symbols(self) -> set[str]:
        """Snapshot of currently-watched symbols (immutable copy)."""
        return set(self._watched_symbols)

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """Event loop captured at construction. Listeners that need to
        publish to the bus marshal via ``loop.call_soon_threadsafe``."""
        return self._loop

    # ------------------------------------------------------------------ #
    # Dispatchers (called on SDK thread)                                   #
    # ------------------------------------------------------------------ #

    def _dispatch_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        """Drop pushes for symbols the manager no longer watches (in-flight
        ticks after a shrinkage). Fan out to all registered listeners."""
        if symbol not in self._watched_symbols:
            return
        for fn in list(self._quote_listeners):
            try:
                fn(symbol, quote)
            except Exception:
                logger.exception("SubscriptionManager: quote listener raised")

    def _dispatch_execution(self, raw: Any) -> None:
        """Normalize then fan out. Non-fill events are silently dropped
        so listeners don't have to re-filter."""
        exec_dict = _normalize_execution(raw)
        if exec_dict is None:
            return
        for fn in list(self._execution_listeners):
            try:
                fn(exec_dict)
            except Exception:
                logger.exception("SubscriptionManager: execution listener raised")
