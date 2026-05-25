"""REST API router factory for Signal Station (§7).

Provides six endpoints:
  GET  /api/tasks                — paginated, filterable task list
  GET  /api/tasks/{task_id}      — single task with push_events
  POST /api/tasks/{task_id}/cancel — cancel a brokerage order
  GET  /api/stats/today          — today's counts grouped by status
  GET  /api/positions            — positions from DB (positions table)
  GET  /api/health               — broker + mode liveness status

Whop monitoring endpoints (when whop_registry is provided):
  GET    /api/whop/pages                       — list monitored pages
  POST   /api/whop/pages                       — add a page
  DELETE /api/whop/pages/{page_id}             — remove a page
  POST   /api/whop/pages/{page_id}/restart     — restart listener
  POST   /api/whop/pages/{page_id}/start       — start listener (was OFF → ON)
  POST   /api/whop/pages/{page_id}/stop        — stop listener (entry retained)
  PATCH  /api/whop/pages/{page_id}/settings    — partially update settings
  GET    /api/whop/pages/defaults              — default settings template
  GET    /api/whop/cookie                      — cookie file status

All routes are gated by ``require_app_token`` applied at the router level.

Usage::

    router = build_http_router(
        session_factory=_factory,
        broker=_broker,
        settings=_settings,
        whop_registry=registry,   # optional
    )
    app.include_router(router)
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

from app.api.auth import require_app_token
from app.api.schemas import (
    BrokerStatusOut,
    CancelOk,
    CandlestickOut,
    CandlesticksOut,
    ChatAuthorOut,
    ChatDayWindowOut,
    ChatMessageCountsOut,
    ChatMessageOut,
    ChatMessagesOut,
    ExecutionOut,
    ExecutionsOut,
    ExecutionsSyncOut,
    QuotedRefOut,
    QuoteWatchIn,
    QuoteWatchOut,
    TradeOut,
    TradesOut,
    HealthOut,
    LongPortAccountActivateIn,
    LongPortAccountLogoutIn,
    LongPortAccountOut,
    LongPortAccountRenameIn,
    LongPortOAuthStartOut,
    LongPortOAuthStatusOut,
    LongPortSettingsOut,
    LongPortSettingsPatch,
    OrphanCleanupRequest,
    OrphanCleanupResponse,
    PairAggregateOut,
    PendingExecutionsOut,
    PendingTradeOut,
    PositionOut,
    PositionsOut,
    QuoteOut,
    QuotesOut,
    StatsTodayOut,
    TaskCountOut,
    TaskListOut,
    TaskOut,
    TickerConfigOut,
    TPairCreate,
    TPairExtendIn,
    TPairOut,
    TPairsOut,
    WhopCookieStatusOut,
    WhopPageCreate,
    WhopPageOut,
    WhopPageSettingsOut,
    WhopPageSettingsPatch,
    WhopPagesOut,
    task_to_out,
    task_to_summary,
    tpair_row_to_out,
    whop_page_to_out,
)
from app.broker.broker_client import BrokerClient
from app.broker.noop_client import NoopBrokerClient
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings
from app.core.event_bus import Event
from app.core.events import TaskPayload, Topics
from app.domain.status import Status
from app.alerts.schemas import (
    AlertCreate,
    AlertEventListOut,
    AlertListOut,
    AlertOut,
    AlertUpdate,
)
from app.alerts.service import AlertsService, SymbolUnknown
from app.orders.schemas import OrderListOut, OrderOut, ReplaceOrderRequest, SubmitOrderRequest
from app.orders.service import OrdersService
from app.storage import repo
from app.storage.db import Base, session_scope
from app.storage.schema import ChatMessageRow, TPairRow

if TYPE_CHECKING:
    from app.core.event_bus import EventBus
    from app.whop.registry import WhopRegistry


# ---------------------------------------------------------------------------
# Chat monitor helpers (T14)
# ---------------------------------------------------------------------------


def _beijing_day_bounds(day: str) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` in UTC for a Beijing calendar day like
    ``"2026-05-23"``. The window is ``[day 00:00 +08:00, next 00:00 +08:00)``
    expressed as UTC datetimes — suitable for ``posted_at >= start AND < end``.
    """
    try:
        y, m, d = day.split("-")
        year, month, dom = int(y), int(m), int(d)
    except ValueError as e:
        raise HTTPException(400, detail=f"invalid day: {day}") from e
    # Beijing 00:00 of `day` == UTC `day-1 16:00`
    start_utc = datetime(year, month, dom, tzinfo=UTC) - timedelta(hours=8)
    end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc


def _beijing_month_bounds(month: str) -> tuple[datetime, datetime]:
    """Return ``[start, end)`` in UTC for a Beijing calendar month like
    ``"2026-05"``. End is the first instant of the next month, Beijing-local.
    """
    try:
        y, m = month.split("-")
        year, mon = int(y), int(m)
    except ValueError as e:
        raise HTTPException(400, detail=f"invalid month: {month}") from e
    # Beijing month-start 00:00 == UTC (day-1) 16:00  (same +08:00 offset as _beijing_day_bounds)
    start_utc = datetime(year, mon, 1, tzinfo=UTC) - timedelta(hours=8)
    if mon == 12:
        next_year, next_mon = year + 1, 1
    else:
        next_year, next_mon = year, mon + 1
    end_utc = datetime(next_year, next_mon, 1, tzinfo=UTC) - timedelta(hours=8)
    return start_utc, end_utc


def _row_to_chat_out(row: ChatMessageRow) -> ChatMessageOut:
    """Convert a ChatMessageRow into ChatMessageOut.

    The denormalized ``quoted_*`` columns collapse into a nested
    ``QuotedRefOut`` when ``quoted_author`` is non-null, or ``None`` when
    the row has no quote. ``quoted_content`` may be empty string when the
    parent message had no body (image-only / sticker-only quote).

    Re-attach ``tzinfo=UTC`` on naive datetimes coming back from SQLite —
    ``DateTime(timezone=True)`` is honored at write time (we always insert
    aware UTC) but SQLite stores the value as a plain string and SQLAlchemy
    returns it naive on read. Without this, Pydantic emits ISO without a
    ``+00:00`` suffix and the frontend's ``new Date(...)`` parses it as the
    browser's local timezone, mis-binning messages by up to 8 hours.
    """
    posted_at = row.posted_at
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)
    quoted: QuotedRefOut | None = None
    if row.quoted_author is not None:
        q_posted = row.quoted_posted_at
        if q_posted is not None and q_posted.tzinfo is None:
            q_posted = q_posted.replace(tzinfo=UTC)
        quoted = QuotedRefOut(
            message_id=row.quoted_message_id,
            author=row.quoted_author,
            content=row.quoted_content or "",
            posted_at=q_posted,
        )
    return ChatMessageOut(
        id=row.id,
        page_id=row.page_id,
        author=row.author,
        content=row.content,
        posted_at=posted_at,
        quoted=quoted,
        image_url=f"/api/chat-images/{row.id}" if row.image_filename else None,
    )


_IMAGE_MEDIA_TYPES = {
    ".avif": "image/avif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bin": "application/octet-stream",
}


def build_http_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    broker: BrokerClient,
    settings: Settings,
    bus: EventBus,
    longport_runtime: LongPortRuntimeStore | None = None,
    whop_registry: WhopRegistry | None = None,
    broker_getter: Callable[[], BrokerClient] | None = None,
    broker_status_fn: Callable[[], dict[str, Any]] | None = None,
    broker_reload_fn: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    subscription_manager_getter: Callable[[], Any] | None = None,
    alerts_engine_getter: Callable[[], Any] | None = None,
    push_listener_getter: Callable[[], Any] | None = None,
) -> APIRouter:
    """Factory — injects session_factory, broker, and settings at app assembly.

    Parameters
    ----------
    broker:
        Initial broker reference. Endpoints that need the broker LATER
        (e.g. ``cancel_task_endpoint``) should go through ``broker_getter``
        instead so they pick up post-reload swaps.
    broker_getter:
        Callable returning the *current* broker. Defaults to a closure over
        the initial ``broker`` for callers that don't support live reload.
    broker_status_fn / broker_reload_fn:
        Optional integration with the lifespan-managed broker rebuild flow.
        When omitted (e.g. in tests), the corresponding endpoints are not
        registered.

    All routes share ``dependencies=[Depends(require_app_token)]`` applied at
    the router level, so auth is enforced uniformly without per-route boilerplate.
    """
    router = APIRouter(dependencies=[Depends(require_app_token)])
    runtime_store = longport_runtime or LongPortRuntimeStore.from_settings_defaults(settings)
    _get_broker: Callable[[], BrokerClient] = broker_getter or (lambda: broker)

    def _longport_settings_out() -> LongPortSettingsOut:
        runtime = runtime_store.get()
        return LongPortSettingsOut(
            active_account_id=runtime.active_account_id,
            accounts=[
                LongPortAccountOut(
                    account_id=a.account_id,
                    label=a.label,
                    authorized=a.authorized,
                )
                for a in runtime.accounts
            ],
            auto_trade=runtime.auto_trade,
            region=runtime.region,
            dry_run=runtime.dry_run,
        )

    # ------------------------------------------------------------------ #
    # GET /api/tasks                                                        #
    # ------------------------------------------------------------------ #

    @router.get("/api/tasks", response_model=TaskListOut)
    async def list_tasks_endpoint(
        limit: int = Query(50, ge=1, le=500),
        cursor: datetime | None = None,
        status: str | None = None,
        type: Annotated[str | None, Query(alias="type")] = None,
        symbol: str | None = None,
        urls: Annotated[list[str] | None, Query()] = None,
        week_start: datetime | None = None,
        week_end: datetime | None = None,
    ) -> TaskListOut:
        """Return a paginated, optionally-filtered list of tasks.

        Pagination is cursor-based: pass ``cursor=<ISO-datetime>`` from
        ``next_cursor`` in the previous page to advance.  ``next_cursor`` is
        ``null`` when no further pages exist.

        Multi-value URL filter: pass ``?urls=u1&urls=u2``. Time window:
        ``week_start`` / ``week_end`` apply a half-open [start, end) filter on
        ``message.posted_at``.
        """
        status_enum: Status | None = None
        if status is not None:
            try:
                status_enum = Status(status)
            except ValueError as exc:
                raise HTTPException(400, detail=f"unknown status: {status!r}") from exc

        async with session_scope(session_factory) as session:
            tasks = await repo.list_tasks(
                session,
                limit=limit,
                cursor_created_at=cursor,
                status=status_enum,
                type_=type,
                symbol=symbol,
                urls=urls,
                posted_at_start=week_start,
                posted_at_end=week_end,
            )
        summaries = [task_to_summary(t) for t in tasks]
        next_cur: datetime | None = tasks[-1].created_at if len(tasks) == limit else None
        return TaskListOut(tasks=summaries, next_cursor=next_cur)

    @router.get("/api/tasks/count", response_model=TaskCountOut)
    async def count_tasks_endpoint(
        status: str | None = None,
        type: Annotated[str | None, Query(alias="type")] = None,
        symbol: str | None = None,
    ) -> TaskCountOut:
        """Return total task count (supports the same filters as /api/tasks)."""
        status_enum: Status | None = None
        if status is not None:
            try:
                status_enum = Status(status)
            except ValueError as exc:
                raise HTTPException(400, detail=f"unknown status: {status!r}") from exc

        async with session_scope(session_factory) as session:
            total = await repo.count_tasks(
                session,
                status=status_enum,
                type_=type,
                symbol=symbol,
            )
        return TaskCountOut(total_count=total)

    # ------------------------------------------------------------------ #
    # GET /api/tasks/{task_id}                                             #
    # ------------------------------------------------------------------ #

    @router.get("/api/tasks/{task_id}", response_model=TaskOut)
    async def get_task_endpoint(task_id: str) -> TaskOut:
        """Return the fully-hydrated Task including all push_events."""
        async with session_scope(session_factory) as session:
            task = await repo.load_task(session, task_id)
        if task is None:
            raise HTTPException(404, detail="task not found")
        return task_to_out(task)

    # ------------------------------------------------------------------ #
    # POST /api/tasks/{task_id}/cancel                                     #
    # ------------------------------------------------------------------ #

    @router.post("/api/tasks/{task_id}/cancel", response_model=CancelOk)
    async def cancel_task_endpoint(task_id: str) -> CancelOk:
        """Cancel the brokerage order associated with a task.

        Returns 404 if the task doesn't exist, 400 if it has no ``order_id``
        (not yet submitted), or 502 if the broker call fails.
        """
        async with session_scope(session_factory) as session:
            task = await repo.load_task(session, task_id)
        if task is None:
            raise HTTPException(404, detail="task not found")
        if not task.order_id:
            raise HTTPException(400, detail="task has no order_id (not yet submitted)")
        try:
            _get_broker().cancel_order(task.order_id)
        except Exception as exc:
            raise HTTPException(502, detail=f"broker cancel failed: {exc}") from exc
        return CancelOk()

    # ------------------------------------------------------------------ #
    # GET /api/stats/today                                                 #
    # ------------------------------------------------------------------ #

    @router.get("/api/stats/today", response_model=StatsTodayOut)
    async def stats_today_endpoint() -> StatsTodayOut:
        """Return today's task counts grouped into summary buckets."""
        async with session_scope(session_factory) as session:
            s = await repo.stats_today(session)
        msg = s["msg_count"]
        return StatsTodayOut(
            msg_count=msg,
            parse_ok=s["parse_ok"],
            parse_rate=(s["parse_ok"] / msg) if msg else 0.0,
            orders=s["orders"],
            filled=s["filled"],
            rejected=s["rejected"],
        )

    # ------------------------------------------------------------------ #
    # GET /api/positions                                                   #
    # ------------------------------------------------------------------ #

    @router.get("/api/positions", response_model=PositionsOut)
    async def list_positions_endpoint() -> PositionsOut:
        """Return current positions split into stocks and options.

        Pulls live from the broker on every call so the dashboard cards
        reflect the latest holdings without a periodic sync job, and
        upserts the result into the ``positions`` table (account-scoped)
        as a side-effect. The DB row is the anchor for
        ``history_synced`` — the per-(account, ticker) "broker_executions
        is fully backfilled" flag the detail-pane sync path consults.

        Symbols no longer reported by the broker are zeroed out
        (``quantity = 0``) rather than deleted so ``history_synced``
        survives close/re-open cycles. The dashboard read filters qty>0.

        Longbridge's ``stock_positions`` endpoint actually returns BOTH
        stocks and option contracts the user holds (the option contracts
        carry an OCC-format symbol). We classify each row via
        ``parse_option_symbol`` and route to the appropriate bucket.
        """
        from app.broker.symbol_classify import parse_option_symbol

        broker = _get_broker()
        account_id = getattr(broker, "account_id", "") or None
        stocks: list[PositionOut] = []
        options: list[PositionOut] = []
        try:
            raw = broker.stock_positions()
        except Exception as exc:  # pragma: no cover — broker SDK errors
            logger.warning("stock_positions fetch failed: %s", exc)
            raw = []

        # Persist as a side-effect so the detail-pane sync path has an
        # anchor for history_synced. Noop broker (account_id="") skips
        # silently — nothing to scope by.
        if account_id:
            try:
                async with session_scope(session_factory) as session:
                    await repo.upsert_positions(
                        session, account_id=account_id, rows=raw
                    )
            except Exception as exc:  # noqa: BLE001 — DB hiccup shouldn't 502
                logger.warning("upsert_positions failed: %s", exc)

        for p in raw:
            symbol = str(p.get("symbol", ""))
            option_leg = parse_option_symbol(symbol)
            qty = int(p.get("quantity", 0) or 0)
            avg = p.get("avg_cost")
            name = p.get("name")
            if option_leg is not None:
                options.append(
                    PositionOut(
                        symbol=symbol,
                        type="option",
                        ticker=option_leg.ticker,
                        quantity=qty,
                        avg_cost=avg,
                        name=name,
                        option_strike=option_leg.strike,
                        option_expiry=option_leg.expiry,
                        option_type=option_leg.cp,
                    )
                )
            else:
                stocks.append(
                    PositionOut(
                        symbol=symbol,
                        type="stock",
                        ticker=str(p.get("ticker", "")),
                        quantity=qty,
                        avg_cost=avg,
                        name=name,
                        option_strike=None,
                        option_expiry=None,
                        option_type=None,
                    )
                )
        return PositionsOut(stocks=stocks, options=options)

    # ------------------------------------------------------------------ #
    # GET /api/db/{table}  — generic table browser (whitelist)              #
    # ------------------------------------------------------------------ #

    # tasks is deliberately excluded — it has a dedicated /api/tasks endpoint
    # with cursor pagination, business filters, and message join. Routing it
    # through the generic browser would expose two divergent code paths.
    _DB_BROWSER_TABLES: dict[str, str] = {
        # table_name → default order column (DESC)
        "messages": "posted_at",
        "instructions": "task_id",
        "push_events": "received_at",
        "positions": "updated_at",
        "t_pairs": "created_at",
        "broker_executions": "ts",
    }

    @router.get("/api/db/{table}")
    async def list_db_rows_endpoint(
        table: str,
        limit: int = Query(15, ge=1, le=100),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        if table not in _DB_BROWSER_TABLES:
            raise HTTPException(404, detail=f"table not browsable: {table!r}")

        sa_table = Base.metadata.tables[table]
        order_col = sa_table.c[_DB_BROWSER_TABLES[table]]
        columns = [c.name for c in sa_table.columns]

        async with session_scope(session_factory) as session:
            total_result = await session.execute(
                select(func.count()).select_from(sa_table)
            )
            total = total_result.scalar_one()

            rows_result = await session.execute(
                select(sa_table)
                .order_by(desc(order_col))
                .limit(limit)
                .offset(offset)
            )
            rows = [list(r) for r in rows_result.all()]

        return {"table": table, "columns": columns, "rows": rows, "total": total}

    # ------------------------------------------------------------------ #
    # /api/pairs — 做T 配对 CRUD                                           #
    # ------------------------------------------------------------------ #

    @router.get("/api/pairs", response_model=TPairsOut)
    async def list_pairs_endpoint(
        ticker: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=500),
    ) -> TPairsOut:
        """List做T pairs for the active account, optionally filtered by
        ticker. Cross-account isolation is enforced via the broker's
        ``account_id``; pairs created under a different account stay
        hidden after switching.

        Paginated: ``offset`` / ``limit`` slice the result. The response
        carries ``total_count`` and ``has_more`` so the UI can render a
        "已加载 M / N · 加载更多" affordance without a separate count call.
        """
        account_id = getattr(_get_broker(), "account_id", "") or None
        async with session_scope(session_factory) as session:
            rows = await repo.list_pairs(
                session,
                ticker=ticker,
                account_id=account_id,
                offset=offset,
                limit=limit,
            )
            total = await repo.count_pairs(
                session, ticker=ticker, account_id=account_id
            )
        return TPairsOut(
            pairs=[tpair_row_to_out(r) for r in rows],
            total_count=total,
            has_more=(offset + len(rows)) < total,
        )

    @router.post("/api/pairs", response_model=TPairOut, status_code=201)
    async def create_pair_endpoint(body: TPairCreate) -> TPairOut:
        """Create a做T pair binding broker fills (one row per order_id).
        Server auto-balances qty using FIFO; leftover qty stays on the
        originating fills for future bindings. The pair id is assigned by
        SQLite (autoincrement integer)."""
        if not body.buy_trade_ids and not body.sell_trade_ids:
            raise HTTPException(400, detail="must select at least one trade")

        all_ids = list({*body.buy_trade_ids, *body.sell_trade_ids})

        account_id = getattr(_get_broker(), "account_id", "") or None
        if account_id is None:
            raise HTTPException(503, detail="broker account not initialised")
        async with session_scope(session_factory) as session:
            # Qty lookup reads broker_executions (one row per order_id,
            # partial fills aggregated).
            trade_qty = await repo.get_broker_executions_qty_map(session, all_ids)
            row = await repo.create_pair(
                session,
                ticker=body.ticker,
                symbol=body.symbol,
                buy_trade_ids=body.buy_trade_ids,
                sell_trade_ids=body.sell_trade_ids,
                trade_qty=trade_qty,
                account_id=account_id,
            )
        if row is None:
            raise HTTPException(
                400,
                detail="no available qty to allocate — selected trades may be "
                       "unfilled or already fully bound to other pairs",
            )
        return tpair_row_to_out(row)

    @router.post("/api/pairs/{pair_id}/extend", response_model=TPairOut)
    async def extend_pair_endpoint(
        pair_id: int,
        body: TPairExtendIn,
    ) -> TPairOut:
        """Add trades to an existing做T pair."""
        if not body.buy_trade_ids and not body.sell_trade_ids:
            raise HTTPException(400, detail="must select at least one trade")
        all_ids = list({*body.buy_trade_ids, *body.sell_trade_ids})

        account_id = getattr(_get_broker(), "account_id", "") or None
        async with session_scope(session_factory) as session:
            trade_qty = await repo.get_broker_executions_qty_map(session, all_ids)
            row = await repo.extend_pair(
                session,
                pair_id=pair_id,
                buy_trade_ids=body.buy_trade_ids,
                sell_trade_ids=body.sell_trade_ids,
                trade_qty=trade_qty,
                account_id=account_id,
            )
        if row is None:
            raise HTTPException(404, detail=f"pair {pair_id} not found")
        return tpair_row_to_out(row)

    @router.delete("/api/pairs/{pair_id}", status_code=204)
    async def delete_pair_endpoint(pair_id: int) -> None:
        """Unbind a做T pair. The underlying trades become available again."""
        async with session_scope(session_factory) as session:
            ok = await repo.delete_pair(session, pair_id)
        if not ok:
            raise HTTPException(404, detail=f"pair {pair_id} not found")

    @router.delete("/api/pairs", status_code=204)
    async def delete_pairs_by_ticker_endpoint(
        ticker: Annotated[str, Query(min_length=1)],
    ) -> None:
        """Bulk-delete every做T pair on the active account for ``ticker``.
        Each affected trade's ``broker_executions.t_pair_tags`` is
        rewritten so the做T chip column reflects the change immediately.
        ``ticker`` is REQUIRED — there's no "wipe across all tickers"
        shortcut, because that would be too easy to fat-finger.
        """
        account_id = getattr(_get_broker(), "account_id", "") or ""
        if not account_id:
            raise HTTPException(400, detail="no active broker account")
        async with session_scope(session_factory) as session:
            await repo.delete_pairs_for_ticker(
                session, account_id=account_id, ticker=ticker
            )

    @router.get("/api/pairs/aggregate", response_model=PairAggregateOut)
    async def pair_aggregate_endpoint(
        ticker: Annotated[str | None, Query()] = None,
    ) -> PairAggregateOut:
        """Account+ticker scoped做T aggregates via SQL SUM/COUNT.

        Used by PairKPIs so the frontend never has to fetch every pair
        just to display totals. ``ticker`` is optional; omit for an
        account-wide aggregate.
        """
        account_id = getattr(_get_broker(), "account_id", "") or None
        async with session_scope(session_factory) as session:
            if account_id is None:
                return PairAggregateOut(profit_total=0.0, count=0, win_count=0)
            from sqlalchemy import case, func, select as _select

            stmt = _select(
                func.coalesce(func.sum(TPairRow.profit), 0.0),
                func.count(),
                func.coalesce(
                    func.sum(case((TPairRow.profit > 0, 1), else_=0)), 0
                ),
            ).where(TPairRow.account_id == account_id)
            if ticker is not None:
                stmt = stmt.where(TPairRow.ticker == ticker)
            row = (await session.execute(stmt)).one()
        return PairAggregateOut(
            profit_total=float(row[0]),
            count=int(row[1]),
            win_count=int(row[2]),
        )

    @router.get(
        "/api/broker/executions/pending", response_model=PendingExecutionsOut
    )
    async def pending_executions_endpoint(
        ticker: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> PendingExecutionsOut:
        """List broker fills whose qty exceeds the qty already allocated
        to any做T pair, plus aggregate pending qty by side.

        ``allocated_qty`` is derived from ``t_pair_tags`` via
        ``json_each``; the WHERE filter drops fully-allocated fills so the
        UI can scan the result for what's still open. ``limit`` caps the
        listing but the aggregate row totals everything regardless.
        """
        account_id = getattr(_get_broker(), "account_id", "") or None
        if account_id is None:
            return PendingExecutionsOut(
                pending_buy_qty=0, pending_sell_qty=0, trades=[]
            )
        from sqlalchemy import text as _text

        async with session_scope(session_factory) as session:
            # SQLite JSON inline:
            # allocated_qty = SUM(json_extract(t.value, '$[1]')) over
            # json_each(broker_executions.t_pair_tags).
            allocated_sql = (
                "COALESCE(("
                " SELECT SUM(CAST(json_extract(t.value, '$[1]') AS INTEGER))"
                " FROM json_each(broker_executions.t_pair_tags) AS t"
                "), 0)"
            )
            params: dict[str, Any] = {"account_id": account_id, "limit": limit}
            where = ["account_id = :account_id", f"qty > {allocated_sql}"]
            if ticker is not None:
                where.append("ticker = :ticker")
                params["ticker"] = ticker

            agg_sql = (
                f"SELECT side, SUM(qty - {allocated_sql}) "
                f"FROM broker_executions WHERE {' AND '.join(where)} "
                f"GROUP BY side"
            )
            buy_qty = sell_qty = 0
            for side, pending in (await session.execute(_text(agg_sql), params)).all():
                if side == "BUY":
                    buy_qty = int(pending or 0)
                elif side == "SELL":
                    sell_qty = int(pending or 0)

            list_sql = (
                f"SELECT order_id, ticker, symbol, side, qty, "
                f"{allocated_sql} AS allocated_qty, "
                f"(qty - {allocated_sql}) AS pending_qty, "
                f"price, ts "
                f"FROM broker_executions "
                f"WHERE {' AND '.join(where)} "
                f"ORDER BY ts DESC LIMIT :limit"
            )
            from datetime import timezone as _tz

            trades: list[PendingTradeOut] = []
            for row in (await session.execute(_text(list_sql), params)).all():
                ts = row.ts
                if isinstance(ts, datetime) and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_tz.utc)
                trades.append(
                    PendingTradeOut(
                        order_id=row.order_id,
                        ticker=row.ticker,
                        symbol=row.symbol,
                        side=row.side,
                        qty=int(row.qty),
                        allocated_qty=int(row.allocated_qty),
                        pending_qty=int(row.pending_qty),
                        price=float(row.price),
                        ts=ts,
                    )
                )
        return PendingExecutionsOut(
            pending_buy_qty=buy_qty, pending_sell_qty=sell_qty, trades=trades,
        )

    # ------------------------------------------------------------------ #
    # GET /api/quote — snapshot quotes for one or more symbols              #
    # ------------------------------------------------------------------ #

    @router.get("/api/quote", response_model=QuotesOut)
    async def quote_endpoint(
        symbols: Annotated[str, Query(description="comma-separated symbols")],
    ) -> QuotesOut:
        """Fetch snapshot quotes for the comma-separated symbol list.

        Symbols missing from the broker's response are silently dropped from
        the result — callers should expect a possibly-smaller result set.
        """
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbol_list:
            raise HTTPException(400, detail="symbols query param is empty")

        try:
            raw = _get_broker().get_quote(symbol_list)
        except Exception as exc:  # pragma: no cover — broker SDK errors
            raise HTTPException(502, detail=f"broker quote failed: {exc}") from exc

        quotes: list[QuoteOut] = []
        for sym in symbol_list:
            q = raw.get(sym)
            if q is None:
                continue
            # ``broker.get_quote`` returns dicts pre-shaped by
            # ``_quote_to_dict`` — session-aware change% + today_close
            # already computed. Fallback (last - prev_close) kept for
            # alternate broker implementations that don't pre-compute.
            last = float(q.get("last_done", 0.0))
            prev = float(q.get("prev_close", 0.0))
            today_close_val = q.get("today_close")
            today_close = float(today_close_val) if today_close_val is not None else None
            if "change" in q and "change_pct" in q:
                change = float(q.get("change", 0.0))
                change_pct = float(q.get("change_pct", 0.0))
            else:
                change = last - prev
                change_pct = (change / prev * 100.0) if prev > 0 else 0.0
            session = str(q.get("trade_session") or "regular")
            if session not in ("regular", "pre", "post", "overnight", "closed"):
                session = "regular"
            quotes.append(
                QuoteOut(
                    symbol=sym,
                    last_done=last,
                    prev_close=prev,
                    today_close=today_close,
                    open=float(q.get("open", 0.0)),
                    high=float(q.get("high", 0.0)),
                    low=float(q.get("low", 0.0)),
                    volume=int(q.get("volume", 0)),
                    turnover=float(q.get("turnover", 0.0)),
                    change=change,
                    change_pct=change_pct,
                    trade_session=session,  # type: ignore[arg-type]
                )
            )
        return QuotesOut(quotes=quotes)

    # ------------------------------------------------------------------ #
    # POST /api/quotes/watch — replace the streaming quote watch set     #
    # ------------------------------------------------------------------ #

    @router.post("/api/quotes/watch", response_model=QuoteWatchOut)
    async def watch_quotes_endpoint(body: QuoteWatchIn) -> QuoteWatchOut:
        """Set the symbols whose quote push-stream the backend forwards
        to WS clients. Replaces the previous set — backend diffs and
        issues subscribe/unsubscribe to the broker.

        Frontend calls this once after positions resolve, and again on
        every account switch (after /broker/reload). Empty list clears
        all subscriptions (used on dashboard unmount / logout).

        Returns 503 when no SubscriptionManager is bound yet (early
        startup window before broker init completes, or right after an
        account-switch reload tore the old manager down) — frontend
        retries on the next positions tick.
        """
        if subscription_manager_getter is None:
            raise HTTPException(503, detail="subscription manager not available")
        mgr = subscription_manager_getter()
        if mgr is None:
            raise HTTPException(503, detail="subscription manager not available")
        result = await mgr.watch_quotes(body.symbols)
        return QuoteWatchOut(**result)

    # ------------------------------------------------------------------ #
    # GET /api/candlesticks — intraday or daily K bars for one symbol      #
    # ------------------------------------------------------------------ #

    # Regular US session ~6.5h. ``all`` aims for the full 24h trading
    # day (pre + regular + post + overnight = 5.5 + 6.5 + 4 + 8 = 24h),
    # but LongBridge caps the candlesticks API at 1000 bars per call —
    # any larger ``count`` returns 502 from the SDK. We cap at 1000 for
    # min_1, which covers pre+regular+post (16h = 960 bars) cleanly and
    # picks up the first ~40 minutes of overnight at most. Beyond that
    # the overnight region stays empty until we wire a separate fetch.
    # Both 分时 and 1min map to SDK Min_1; 分时 differs only in front-end
    # rendering (pads to fill the session window).
    _BARS_PER_DAY_REGULAR = {
        "min_1": 390, "min_2": 195, "min_3": 130, "min_5": 78,
    }
    _BARS_PER_DAY_ALL = {
        "min_1": 1000, "min_2": 720, "min_3": 480, "min_5": 288,
    }

    # Longer-horizon (non-today) periods use a fixed granularity; granularity/
    # sessions query params are ignored for these.
    #
    #   5/7  → multi-day intraday line (5-min bars stitched across days).
    #          Used by the "多日" view; the chart renders a folded line.
    #   day  → 1-year batch of daily candles. The "日K" candlestick view
    #          loads this once and lets the user pinch/pan within it.
    #   week → 4-year batch of weekly candles.
    #   month → 10-year batch of monthly candles.
    #   year  → 30-year batch of yearly candles.
    _PERIOD_GRANULARITY_NON_TODAY: dict[str, tuple[str, int]] = {
        "5":     ("min_5", 5 * 78),
        "7":     ("min_5", 7 * 78),
        # "30" is retained as a legacy period for the OptionCard miniline
        # which renders 30 daily candles. NOT exposed in the new chart tabs.
        "30":    ("day", 30),
        "day":   ("day", 250),
        "week":  ("week", 200),
        "month": ("month", 120),
        "year":  ("year", 30),
    }

    # User-facing granularity name → SDK period.
    # ``分时`` is a 1-min line chart with session-padded x-axis;
    # ``1min`` is the same SDK data but rendered as a regular K-line view
    # (no slot padding, identical to 2/3/5min behavior).
    _GRANULARITY_FOR_TODAY = {
        "分时": "min_1",
        "1min": "min_1",
        "2min": "min_2",
        "3min": "min_3",
        "5min": "min_5",
    }
    _SESSION_NAMES = {"regular", "pre", "post", "overnight", "all"}

    @router.get("/api/candlesticks", response_model=CandlesticksOut)
    async def candlesticks_endpoint(
        symbol: str,
        period: Annotated[
            str,
            Query(description="today | 5 | 7 | 30 | day | week | month | year"),
        ] = "today",
        granularity: Annotated[
            str,
            Query(description="(today only) 2min | 3min | 5min"),
        ] = "5min",
        sessions: Annotated[
            str,
            Query(description="(today only) regular | all (include pre/post-market)"),
        ] = "regular",
        before: Annotated[
            datetime | None,
            Query(description=(
                "Optional UTC instant — when set, return bars strictly older "
                "than this (used by the detail-pane pan-back flow). Only "
                "supported for day/week/month/year periods."
            )),
        ] = None,
    ) -> CandlesticksOut:
        """Return candlestick bars for a single symbol.

        For `today`, granularity (2/3/5 min) and sessions (regular vs
        pre+post) are user-selectable so the user can choose between a
        clean regular-hours curve and a wider view that includes pre-market
        and after-hours. For other periods these query params are ignored
        (fixed mapping):
          5/7 → 5-min stitched across days (多日 line view);
          day/week/month/year → 1/4/10/30-year batch of candles for the
                                日K/周K/月K/年K candlestick views.
        """
        if period == "today":
            sdk_period = _GRANULARITY_FOR_TODAY.get(granularity)
            if sdk_period is None:
                raise HTTPException(
                    400,
                    detail=f"unknown granularity {granularity!r}; "
                           f"expected {list(_GRANULARITY_FOR_TODAY)}",
                )
            if sessions not in _SESSION_NAMES:
                raise HTTPException(
                    400,
                    detail=f"unknown sessions {sessions!r}; "
                           f"expected {sorted(_SESSION_NAMES)}",
                )
            # The SDK only exposes two modes: Intraday (regular) or All.
            # For 盘前/盘后/夜盘 specifically, fetch All and let the client
            # filter by ET time-of-day. We send sdk_sessions accordingly.
            sdk_sessions_for_query = "regular" if sessions == "regular" else "all"
            bars_per_day = (
                _BARS_PER_DAY_ALL if sdk_sessions_for_query == "all"
                else _BARS_PER_DAY_REGULAR
            )
            count = bars_per_day[sdk_period]
            sessions = sdk_sessions_for_query  # what we actually pass to broker
        else:
            cfg = _PERIOD_GRANULARITY_NON_TODAY.get(period)
            if cfg is None:
                raise HTTPException(
                    400,
                    detail=f"unknown period {period!r}; expected one of "
                           f"today, {sorted(_PERIOD_GRANULARITY_NON_TODAY)}",
                )
            sdk_period, count = cfg
            # Non-today periods always use regular session.
            sessions = "regular"

        # ``before`` semantics:
        #   - K-line periods: pan-back history extension.
        #   - today period: fetch the intraday window ending at ``before``
        #     (count = bars_per_day from above). Used by the "多日重叠"
        #     overlay view to grab a specific historical trading day's
        #     full-session line via history_candlesticks_by_offset; the
        #     client server-side filters down to its target date.

        try:
            bars = _get_broker().get_candlesticks(
                symbol,
                period=sdk_period,
                count=count,
                sessions=sessions,
                before=before,
            )
        except Exception as exc:  # pragma: no cover — broker SDK errors
            raise HTTPException(502, detail=f"broker candlesticks failed: {exc}") from exc

        return CandlesticksOut(
            symbol=symbol,
            period=period,
            bars=[CandlestickOut(**b) for b in bars],
        )

    # ------------------------------------------------------------------ #
    # GET /api/trades — per-ticker flat fill history for做T binding        #
    # ------------------------------------------------------------------ #

    @router.get("/api/broker/executions", response_model=ExecutionsOut)
    async def history_executions_endpoint(
        ticker: Annotated[str | None, Query()] = None,
        days: Annotated[int, Query(ge=1, le=3650)] = 730,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> ExecutionsOut:
        """Broker-side fill history for the detail pane's trade list.

        Sync semantics (both modes iterate 90-day chunks — LongBridge
        rejects wider single calls; see knowledge/longbridge-api-limits.md):
          - Incremental: starts from ``MAX(ts)`` already in DB for this
            account (+ optional ticker), walks 90-day chunks back to
            cover the gap.
          - First-ever sync: walks 90-day chunks backwards up to
            ``days`` total (default 730 = 2 years) so the user's complete
            history materializes on initial detail-pane open. Stops
            early on any empty window — saves wasted calls when the
            account opened mid-horizon.

        Read comes from DB filtered by account_id (cross-account bleed
        is impossible) and is NOT truncated by ``days``: once history is
        synced, every page returns it. ``days`` only governs the
        first-time backfill horizon.

        Paginated: ``offset`` / ``limit`` slice the result newest-first.
        Sync runs on every call (idempotent upsert) so a page-flip also
        picks up new fills that arrived since the previous open.
        """
        from app.broker.executions_sync import (
            sync_broker_executions_incremental,
            latest_synced_at,
        )

        broker = _get_broker()
        account_id = getattr(broker, "account_id", "")
        async with session_scope(session_factory) as session:
            last_synced: datetime | None = None
            total = 0
            if account_id:
                await sync_broker_executions_incremental(
                    session, broker, ticker=ticker, fallback_days=days
                )
                rows = await repo.list_broker_executions(
                    session,
                    account_id=account_id,
                    ticker=ticker,
                    offset=offset,
                    limit=limit,
                )
                total = await repo.count_broker_executions(
                    session,
                    account_id=account_id,
                    ticker=ticker,
                )
                last_synced = await latest_synced_at(
                    session, account_id=account_id, ticker=ticker
                )
            else:
                rows = []
        from datetime import timezone as _tz
        executions: list[ExecutionOut] = []
        for r in rows:
            if r.side not in ("BUY", "SELL"):
                continue
            ts = r.ts
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz.utc)
            executions.append(
                ExecutionOut(
                    order_id=r.order_id,
                    task_id=r.task_id,
                    symbol=r.symbol,
                    ticker=r.ticker,
                    side=r.side,  # type: ignore[arg-type]
                    qty=r.qty,
                    price=r.price,
                    ts=ts,
                    t_pair_tags=[
                        (int(pid), int(qty)) for pid, qty in (r.t_pair_tags or [])
                    ],
                )
            )
        if last_synced is not None and last_synced.tzinfo is None:
            last_synced = last_synced.replace(tzinfo=_tz.utc)
        return ExecutionsOut(
            executions=executions,
            last_synced_at=last_synced,
            total_count=total,
            has_more=(offset + len(executions)) < total,
        )

    @router.delete("/api/broker/executions", status_code=204)
    async def delete_broker_executions_endpoint(
        ticker: Annotated[str, Query(min_length=1)],
    ) -> None:
        """Wipe ``broker_executions`` rows for the active account scoped
        to ``ticker`` AND reset ``positions.history_synced`` to False.
        After this, a follow-up GET ``/api/broker/executions?ticker=X``
        re-triggers the full chunked 2-year backfill from scratch.

        ``ticker`` is REQUIRED — keeps the bulk wipe scope explicit.
        """
        account_id = getattr(_get_broker(), "account_id", "") or ""
        if not account_id:
            raise HTTPException(400, detail="no active broker account")
        async with session_scope(session_factory) as session:
            await repo.delete_broker_executions_for_ticker(
                session, account_id=account_id, ticker=ticker
            )

    @router.post(
        "/api/broker/executions/sync", response_model=ExecutionsSyncOut
    )
    async def sync_executions_endpoint(
        ticker: Annotated[str, Query(min_length=1)],
        days: Annotated[int, Query(ge=1, le=90)] = 7,
    ) -> ExecutionsSyncOut:
        """Force-pull the last ``days`` of broker fills for ``ticker`` and
        upsert into ``broker_executions``. Distinct from the GET path's
        incremental sync (which anchors on ``MAX(ts)``) — this
        unconditionally walks back ``days`` so mid-window gaps in the
        local cache are filled. Idempotent: PK is order_id.

        ``days`` capped at 90 because LongBridge's history_executions
        rejects wider single calls (see knowledge/longbridge-api-limits.md).
        """
        from app.broker.executions_sync import sync_broker_executions

        broker = _get_broker()
        if not getattr(broker, "account_id", ""):
            return ExecutionsSyncOut(persisted=0)
        async with session_scope(session_factory) as session:
            persisted = await sync_broker_executions(
                session, broker, ticker=ticker, days=days
            )
        return ExecutionsSyncOut(persisted=persisted)

    @router.get("/api/broker/today_executions", response_model=ExecutionsOut)
    async def today_executions_endpoint() -> ExecutionsOut:
        """Today's (ET trading day) order-level executions for the active
        account. Same DB-backed path as /api/broker/executions but with a
        narrow window — used by Day P/L on position cards.

        Sync pulls today_executions from the broker (which already covers
        ~30h via history_executions internally) and upserts as one row
        per order. Frontend re-filters by ET trading day client-side.
        """
        from datetime import datetime, timedelta, timezone as _tz
        from app.broker.executions_sync import sync_broker_executions

        broker = _get_broker()
        account_id = getattr(broker, "account_id", "")
        async with session_scope(session_factory) as session:
            if account_id:
                # 7-day window: comfortably spans the worst-case
                # Thanksgiving (Thu close + Fri half-day + Sat + Sun)
                # or Memorial Day (Fri + Sat + Sun + Mon holiday) so
                # the most recent trading day's fills are always in
                # the DB read. Frontend filters precisely by
                # ``quote.trading_day``; backend just needs to not
                # drop fills before they reach the client. DB upsert
                # in sync_broker_executions dedupes by order_id so
                # the widened sync is idempotent.
                await sync_broker_executions(session, broker, days=7)
                since = datetime.now(_tz.utc) - timedelta(days=7)
                rows = await repo.list_broker_executions(
                    session,
                    account_id=account_id,
                    since=since,
                )
            else:
                rows = []
        executions: list[ExecutionOut] = []
        for r in rows:
            if r.side not in ("BUY", "SELL"):
                continue
            ts = r.ts
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz.utc)
            executions.append(
                ExecutionOut(
                    order_id=r.order_id,
                    task_id=r.task_id,
                    symbol=r.symbol,
                    ticker=r.ticker,
                    side=r.side,  # type: ignore[arg-type]
                    qty=r.qty,
                    price=r.price,
                    ts=ts,
                    t_pair_tags=[
                        (int(pid), int(qty)) for pid, qty in (r.t_pair_tags or [])
                    ],
                )
            )
        return ExecutionsOut(executions=executions)

    @router.get("/api/trades", response_model=TradesOut)
    async def trades_endpoint(
        ticker: Annotated[str, Query(description="user-facing ticker, e.g. TSLA")],
        limit: int = Query(200, ge=1, le=500),
    ) -> TradesOut:
        """Return chronologically-ordered FILLED / PARTIAL trades for a ticker.

        Each entry corresponds to one task (its id is the trade_id used in
        做T pair allocations). Unfilled tasks (no cumulative_qty) are
        filtered out — they have no position to bind.
        """
        async with session_scope(session_factory) as session:
            tasks = await repo.list_tasks(
                session,
                ticker=ticker,
                statuses=[Status.FILLED, Status.PARTIAL],
                limit=limit,
            )

        trades: list[TradeOut] = []
        for t in tasks:
            evt = t.push_events[0] if t.push_events else None
            qty = evt.cumulative_qty if evt and evt.cumulative_qty else None
            price = (
                evt.cumulative_avg_price
                if evt and evt.cumulative_avg_price is not None
                else None
            )
            if qty is None or qty <= 0 or price is None:
                continue  # no position to do T on

            inst = t.instruction
            if inst is None:
                continue
            side = "BUY" if "BUY" in inst.instruction_type.value.upper() else "SELL"

            trades.append(
                TradeOut(
                    id=t.id,
                    ticker=t.instruction.ticker if hasattr(t.instruction, "ticker") else ticker,
                    symbol=getattr(t.instruction, "symbol", None) or None,
                    side=side,
                    qty=int(qty),
                    price=float(price),
                    ts=evt.received_at if evt else t.updated_at,
                    source=t.message.author or t.message.source,
                    tag=None,
                )
            )

        # Chronological ascending so做T builder can FIFO-allocate by order.
        trades.sort(key=lambda x: x.ts)
        return TradesOut(ticker=ticker, trades=trades)

    # ------------------------------------------------------------------ #
    # GET /api/health                                                      #
    # ------------------------------------------------------------------ #

    @router.get("/api/health", response_model=HealthOut)
    async def health_endpoint() -> HealthOut:
        """Return service liveness + mode status.

        ``whop`` is always ``"down"`` until the Phase 6 Whop scraper is wired
        into the health probe.  ``longport`` is assumed ``"up"`` because the
        broker is injected at startup (real health-check is future work).
        """
        settings_out = _longport_settings_out()
        # Look up the active account's label so /health can surface a
        # user-friendly hint of which account is in use right now.
        active = next(
            (a for a in settings_out.accounts if a.account_id == settings_out.active_account_id),
            None,
        )
        return HealthOut(
            whop="down",
            longport="up",
            account_label=active.label if active else "",
            dry_run=settings_out.dry_run,
        )

    @router.get("/api/longport/settings", response_model=LongPortSettingsOut)
    async def get_longport_settings() -> LongPortSettingsOut:
        return _longport_settings_out()

    @router.patch("/api/longport/settings", response_model=LongPortSettingsOut)
    async def patch_longport_settings(body: LongPortSettingsPatch) -> LongPortSettingsOut:
        # Only flags / region are patchable here. The account list and
        # active account mutate exclusively through the OAuth / account
        # endpoints below.
        patch: dict[str, object] = {}
        if body.auto_trade is not None:
            patch["auto_trade"] = body.auto_trade
        if body.region is not None:
            patch["region"] = body.region
        if body.dry_run is not None:
            patch["dry_run"] = body.dry_run
        runtime_store.update(patch)
        return _longport_settings_out()

    # ------------------------------------------------------------------ #
    # OAuth login flow                                                    #
    #                                                                     #
    # /start: register a client_id if missing, then kick off the SDK's    #
    #         local-callback OAuth dance and return the auth URL for the  #
    #         UI to window.open().                                        #
    # /status: poll for completion (the SDK's callback server fires when  #
    #         the user finishes authorizing in their browser).            #
    # /logout: delete the SDK's local token cache for the chosen mode so  #
    #         the next login flow starts from scratch.                    #
    # ------------------------------------------------------------------ #
    # Reference the module (not its members) so tests can monkeypatch
    # ``register_client`` / ``revoke_local_token`` on the module and the
    # routes pick up the patched version on next call.
    from app.broker import oauth as oauth_mod

    # One coordinator instance per router build — its sessions are in-memory
    # and tied to this app process. Hoisting it outside the router would
    # leak state across test fixtures.
    oauth_coordinator = oauth_mod.OAuthCoordinator()

    @router.post(
        "/api/longport/oauth/start",
        response_model=LongPortOAuthStartOut,
    )
    async def post_longport_oauth_start() -> LongPortOAuthStartOut:
        """Start a fresh OAuth flow to add a new LongBridge account slot.

        Always registers a brand-new OAuth client_id — there is no concept
        of "re-using" a previously-authorized account here, because each
        invocation expresses the user's intent to add an account.
        """
        try:
            account_id = await oauth_mod.register_client(
                client_name="Signal Station",
            )
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"OAuth client registration failed: {e}",
            ) from e

        session = await oauth_coordinator.start(account_id)
        # Port-bind recovery is now handled inside the coordinator (it
        # cancels the prior task + waits for the OS to release the socket
        # before rebinding the same port). If it still fails here, the
        # port is held by an outside process and re-registration won't
        # help — surface the error.
        if session.state == "error" or session.auth_url is None:
            raise HTTPException(
                status_code=502,
                detail=session.error or "OAuth flow failed to start",
            )
        return LongPortOAuthStartOut(
            session_id=session.session_id,
            auth_url=session.auth_url,
            account_id=account_id,
        )

    @router.get(
        "/api/longport/oauth/status",
        response_model=LongPortOAuthStatusOut,
    )
    async def get_longport_oauth_status(session_id: str) -> LongPortOAuthStatusOut:
        session = oauth_coordinator.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="OAuth session not found")
        # On success, materialize the account into the settings list. We
        # only do this once — add_account is idempotent on account_id.
        if session.state == "success":
            runtime_store.add_account(session.client_id)
        return LongPortOAuthStatusOut(
            state=session.state,
            error=session.error,
            account_id=session.client_id if session.state == "success" else None,
        )

    @router.post(
        "/api/longport/oauth/activate",
        response_model=LongPortSettingsOut,
    )
    async def post_longport_oauth_activate(
        body: LongPortAccountActivateIn,
    ) -> LongPortSettingsOut:
        """Set ``account_id`` as the active account. Caller is expected to
        invoke /broker/reload separately to actually swap the broker."""
        try:
            runtime_store.set_active(body.account_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        return _longport_settings_out()

    @router.post(
        "/api/longport/oauth/logout",
        response_model=LongPortSettingsOut,
    )
    async def post_longport_oauth_logout(
        body: LongPortAccountLogoutIn,
    ) -> LongPortSettingsOut:
        """Remove an account: scrub the SDK token cache, drop from the
        settings list. If it was the active account, fall back to whatever
        account remains."""
        oauth_mod.revoke_local_token(body.account_id)
        runtime_store.remove_account(body.account_id)
        return _longport_settings_out()

    @router.patch(
        "/api/longport/oauth/account",
        response_model=LongPortSettingsOut,
    )
    async def patch_longport_oauth_account(
        body: LongPortAccountRenameIn,
    ) -> LongPortSettingsOut:
        """Rename an account's display label."""
        runtime_store.rename_account(body.account_id, body.label)
        return _longport_settings_out()

    # ------------------------------------------------------------------ #
    # Broker status + reload — surfaces LongPort init state to the UI    #
    # so the user can see if the broker fell back to Noop and trigger a  #
    # rebuild after fixing credentials.                                   #
    # ------------------------------------------------------------------ #
    if broker_status_fn is not None:

        @router.get("/api/longport/broker/status", response_model=BrokerStatusOut)
        async def get_broker_status() -> BrokerStatusOut:  # noqa: RUF029
            snap = broker_status_fn()
            return BrokerStatusOut(
                is_real=bool(snap.get("is_real")),
                account_label=str(snap.get("account_label", "")),
                dry_run=bool(snap.get("dry_run")),
                last_init_error=snap.get("last_init_error"),
            )

    if broker_reload_fn is not None:

        @router.post("/api/longport/broker/reload", response_model=BrokerStatusOut)
        async def post_broker_reload() -> BrokerStatusOut:
            """Tear down the current broker + push subscription, build a
            new one from the latest credentials in runtime store, and
            return the resulting status. Used by the UI's refresh button.
            """
            snap = await broker_reload_fn()
            return BrokerStatusOut(
                is_real=bool(snap.get("is_real")),
                account_label=str(snap.get("account_label", "")),
                dry_run=bool(snap.get("dry_run")),
                last_init_error=snap.get("last_init_error"),
            )

    @router.post("/api/tasks/{task_id}/confirm", response_model=TaskOut)
    async def confirm_task_endpoint(task_id: str) -> TaskOut:
        async with session_scope(session_factory) as session:
            task = await repo.load_task(session, task_id)
        if task is None:
            raise HTTPException(404, detail="task not found")
        if task.instruction is None:
            raise HTTPException(400, detail="task has no parsed instruction")
        if task.status != Status.INSTRUCTION_READY:
            raise HTTPException(
                400,
                detail=f"task status must be INSTRUCTION_READY for confirm, got: {task.status}",
            )

        prev_runtime = runtime_store.get()
        runtime_store.update({"auto_trade": True})
        try:
            await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
        finally:
            runtime_store.update({"auto_trade": prev_runtime.auto_trade})
        # 8s gives time for: validation gate → broker submit (typical
        # ~120ms but can be much slower under load / slow network) →
        # initial NotReported push event → bus storage save. The previous
        # 3s window often returned with status still at INSTRUCTION_READY
        # because the broker submit hadn't completed when the response was
        # serialized, leaving the user wondering if confirm did anything.
        try:
            await bus.wait_idle(timeout=8.0)
        except TimeoutError:
            logger.warning(
                "confirm_task_endpoint: bus did not idle within 8s for task %s; "
                "returning current DB state",
                task_id,
            )

        async with session_scope(session_factory) as session:
            refreshed = await repo.load_task(session, task_id)
        if refreshed is None:
            raise HTTPException(500, detail="task missing after confirm")
        return task_to_out(refreshed)

    @router.post("/api/tasks/{task_id}/skip", response_model=TaskOut)
    async def skip_task_endpoint(task_id: str) -> TaskOut:
        """Mark an INSTRUCTION_READY task as SKIPPED on user request."""
        async with session_scope(session_factory) as session:
            task = await repo.load_task(session, task_id)
        if task is None:
            raise HTTPException(404, detail="task not found")
        if task.status != Status.INSTRUCTION_READY:
            raise HTTPException(
                400,
                detail=f"task status must be INSTRUCTION_READY for skip, got: {task.status}",
            )
        task.mark_skipped("用户手动取消")
        await bus.publish(Event(Topics.TASK_STATUS_CHANGED, TaskPayload(task)))
        await bus.wait_idle(timeout=3.0)
        async with session_scope(session_factory) as session:
            refreshed = await repo.load_task(session, task_id)
        if refreshed is None:
            raise HTTPException(500, detail="task missing after skip")
        return task_to_out(refreshed)

    # ------------------------------------------------------------------ #
    # Whop monitoring management (only when registry provided)             #
    # ------------------------------------------------------------------ #

    if whop_registry is not None:

        @router.get("/api/whop/pages", response_model=WhopPagesOut)
        async def list_whop_pages(
            parent_chat_id: str | None = None,
        ) -> WhopPagesOut:
            """List monitored pages.

            Default (no query param): only top-level pages (parent_chat_id IS NULL).
            With ``?parent_chat_id=<id>``: only that parent's sub-monitors.
            """
            if parent_chat_id is None:
                pages = whop_registry.list_pages()
            else:
                pages = whop_registry.list_pages(parent_chat_id=parent_chat_id)
            return WhopPagesOut(pages=[whop_page_to_out(e, ll) for e, ll in pages])

        @router.post("/api/whop/pages", response_model=WhopPageOut, status_code=201)
        async def create_whop_page(body: WhopPageCreate) -> WhopPageOut:
            try:
                entry = await whop_registry.add_page(
                    url=body.url,
                    source=body.source,
                    name=body.name,
                    parent_chat_id=body.parent_chat_id,
                )
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            # Re-read to include listener status. Use parent_chat_id=None so we can
            # find subs (they aren't in the default top-level listing).
            for e, ll in whop_registry.list_pages(parent_chat_id=None):
                if e.id == entry.id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="added but lost track")

        @router.delete("/api/whop/pages/{page_id}", status_code=204)
        async def delete_whop_page(page_id: str) -> None:
            # Capture the source BEFORE removing the entry so we know whether
            # this is a chat page (chat pages need their chat_messages rows
            # cleaned up — there's no FK cascade since WhopPageEntry lives in
            # data/whop_pages.json, not the DB). The registry exposes entries
            # via list_pages(); the page may not exist (concurrent delete,
            # bad id) in which case remove_page below 404s.
            source: str | None = None
            for entry, _ll in whop_registry.list_pages(parent_chat_id=None):
                if entry.id == page_id:
                    source = entry.source
                    break

            ok = await whop_registry.remove_page(page_id)
            if not ok:
                raise HTTPException(404, detail="page not found")

            # Spec: 仅对 source == "chat" 的页面执行清理 (no-op for stock/option;
            # explicit guard avoids an unnecessary DELETE statement).
            if source == "chat":
                async with session_scope(session_factory) as session:
                    await repo.delete_chat_messages_by_page(session, page_id)

        @router.get(
            "/api/whop/pages/{page_id}/chat-messages",
            response_model=ChatMessagesOut,
        )
        async def get_chat_messages(
            page_id: str,
            day: str,
            senders: str | None = None,
        ) -> ChatMessagesOut:
            """Return one Beijing-calendar-day's worth of chat messages
            for *page_id*.

            ``day=YYYY-MM-DD`` is required; the window is ``[day 00:00 +08:00,
            next 00:00 +08:00)`` expressed in UTC. ``senders`` is a
            comma-separated allow-list of authors; empty / absent → no filter.
            ``authors`` is the (author, count) breakdown for the *unfiltered*
            day — the chip bar should show every author seen in the window
            regardless of the active filter selection.
            """
            page = None
            for entry, _ll in whop_registry.list_pages(parent_chat_id=None):
                if entry.id == page_id:
                    page = entry
                    break
            if page is None:
                raise HTTPException(404, detail="page not found")

            day_start, day_end = _beijing_day_bounds(day)
            sender_list = (
                [s.strip() for s in senders.split(",") if s.strip()]
                if senders
                else None
            )

            async with session_scope(session_factory) as session:
                rows = await repo.list_chat_messages(
                    session, page_id, day_start, day_end, sender_list
                )
                authors = await repo.list_chat_authors(
                    session, page_id, day_start, day_end
                )

            return ChatMessagesOut(
                messages=[_row_to_chat_out(r) for r in rows],
                authors=[ChatAuthorOut(name=a, count=c) for a, c in authors],
                day=ChatDayWindowOut(start=day_start, end=day_end),
            )

        @router.get(
            "/api/whop/pages/{page_id}/chat-message-counts",
            response_model=ChatMessageCountsOut,
        )
        async def get_chat_message_counts(
            page_id: str,
            month: str,
        ) -> ChatMessageCountsOut:
            """Return per-Beijing-day message counts for the given month.

            Days with zero messages are omitted from ``counts``. The window
            is ``[month-01 00:00 +08:00, (month+1)-01 00:00 +08:00)``
            expressed in UTC.
            """
            page = None
            for entry, _ll in whop_registry.list_pages(parent_chat_id=None):
                if entry.id == page_id:
                    page = entry
                    break
            if page is None:
                raise HTTPException(404, detail="page not found")

            start, end = _beijing_month_bounds(month)
            async with session_scope(session_factory) as session:
                pairs = await repo.count_chat_messages_per_day(
                    session, page_id, start, end
                )

            return ChatMessageCountsOut(
                month=month,
                counts={day: count for day, count in pairs},
            )

        @router.get("/api/chat-images/{message_id}")
        async def get_chat_image(message_id: str) -> FileResponse:
            """Serve a cached chat image from ``<data_dir>/chat-images/``.

            The chat_writer downloads images at scrape time (see
            ``app.whop.chat_writer._download_image``). This endpoint returns
            the bytes with a media type inferred from the file extension.
            404 if the row is missing, the row has no image, or the file is
            missing on disk.
            """
            async with session_scope(session_factory) as session:
                row = await session.get(ChatMessageRow, message_id)
            if row is None or not row.image_filename:
                raise HTTPException(404, detail="image not found")
            # Defense-in-depth: chat_writer.py sanitizes filenames at write
            # time via Path(msg_id).name, so legitimate rows always have a
            # safe basename. Re-confirming the resolved path lives under
            # the chat-images dir guards against any future code path (or
            # manual DB edit) that stores an un-sanitized filename.
            images_root = (settings.data_dir / "chat-images").resolve()
            path = (images_root / row.image_filename).resolve()
            if not path.is_relative_to(images_root):
                raise HTTPException(404, detail="image not found")
            if not path.exists():
                raise HTTPException(404, detail="image file missing")
            media_type = _IMAGE_MEDIA_TYPES.get(
                path.suffix.lower(), "application/octet-stream"
            )
            return FileResponse(path, media_type=media_type)

        @router.post("/api/whop/pages/{page_id}/restart", response_model=WhopPageOut)
        async def restart_whop_page(page_id: str) -> WhopPageOut:
            ok = await whop_registry.restart_page(page_id)
            if not ok:
                raise HTTPException(404, detail="page not found or restart failed")
            for e, ll in whop_registry.list_pages(parent_chat_id=None):
                if e.id == page_id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="restart succeeded but lost track")

        @router.post("/api/whop/pages/{page_id}/start", response_model=WhopPageOut)
        async def start_whop_page_endpoint(page_id: str) -> WhopPageOut:
            """Start the Playwright listener for a page.

            Idempotent w.r.t. the entry: if a listener is already running it
            is stopped and re-started (same semantics as restart). Returns 404
            if the page id is unknown OR if Playwright launch fails.
            """
            ok = await whop_registry.start_page(page_id)
            if not ok:
                raise HTTPException(404, detail="page not found or start failed")
            for e, ll in whop_registry.list_pages(parent_chat_id=None):
                if e.id == page_id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="started but lost track")

        @router.post("/api/whop/pages/{page_id}/stop", response_model=WhopPageOut)
        async def stop_whop_page_endpoint(page_id: str) -> WhopPageOut:
            """Stop the Playwright listener for a page (entry stays).

            Idempotent: returns 200 even if no listener was running. Returns
            404 only when the entry id is unknown.
            """
            ok = await whop_registry.stop_page(page_id)
            if not ok:
                raise HTTPException(404, detail="page not found")
            for e, ll in whop_registry.list_pages(parent_chat_id=None):
                if e.id == page_id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="stopped but lost track")

        @router.get("/api/whop/pages/defaults", response_model=WhopPageSettingsOut)
        async def whop_settings_defaults(source: str) -> WhopPageSettingsOut:
            from app.whop.page_settings import default_settings_for

            try:
                s = default_settings_for(source)  # type: ignore[arg-type]
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            return WhopPageSettingsOut(
                dedupe_processed_messages=s.dedupe_processed_messages,
                price_deviation_tolerance=s.price_deviation_tolerance,
                block_historical_messages=s.block_historical_messages,
                launch_headless=s.launch_headless,
                parser_version=s.parser_version,
                option_buy_quantity_enabled=s.option_buy_quantity_enabled,
                option_buy_quantity=s.option_buy_quantity,
                option_total_price_limit_enabled=s.option_total_price_limit_enabled,
                option_total_price_limit=s.option_total_price_limit,
                tickers=(
                    {
                        k: TickerConfigOut(trade_quantity=v.trade_quantity)
                        for k, v in s.tickers.items()
                    }
                    if s.tickers is not None
                    else None
                ),
            )

        @router.patch("/api/whop/pages/{page_id}/settings", response_model=WhopPageOut)
        async def patch_whop_page_settings(
            page_id: str, body: WhopPageSettingsPatch
        ) -> WhopPageOut:
            patch_dict: dict[str, object] = {}
            if body.dedupe_processed_messages is not None:
                patch_dict["dedupe_processed_messages"] = body.dedupe_processed_messages
            if body.price_deviation_tolerance is not None:
                patch_dict["price_deviation_tolerance"] = body.price_deviation_tolerance
            if body.block_historical_messages is not None:
                patch_dict["block_historical_messages"] = body.block_historical_messages
            if body.launch_headless is not None:
                patch_dict["launch_headless"] = body.launch_headless
            if body.parser_version is not None:
                patch_dict["parser_version"] = body.parser_version
            if body.tickers is not None:
                patch_dict["tickers"] = {
                    k: {"trade_quantity": v.trade_quantity} for k, v in body.tickers.items()
                }
            if body.option_buy_quantity_enabled is not None:
                patch_dict["option_buy_quantity_enabled"] = body.option_buy_quantity_enabled
            if body.option_buy_quantity is not None:
                patch_dict["option_buy_quantity"] = body.option_buy_quantity
            if body.option_total_price_limit_enabled is not None:
                patch_dict["option_total_price_limit_enabled"] = body.option_total_price_limit_enabled
            if body.option_total_price_limit is not None:
                patch_dict["option_total_price_limit"] = body.option_total_price_limit
            if body.watched_senders is not None:
                patch_dict["watched_senders"] = body.watched_senders
            if body.chat_card_max_msgs is not None:
                patch_dict["chat_card_max_msgs"] = body.chat_card_max_msgs
            if not patch_dict:
                raise HTTPException(
                    400,
                    detail="patch body is empty — provide at least one settings field",
                )
            try:
                entry = await whop_registry.update_settings(page_id, patch_dict)
            except KeyError as exc:
                raise HTTPException(404, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            for e, ll in whop_registry.list_pages(parent_chat_id=None):
                if e.id == entry.id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="updated but lost track")

        @router.post("/api/whop/orphan/cleanup", response_model=OrphanCleanupResponse)
        async def cleanup_orphan_tasks(body: OrphanCleanupRequest) -> OrphanCleanupResponse:
            """Delete all tasks (and linked rows) for a given url.

            Defensive: rejects (400) if the url is currently registered to an
            active page — unless `force=true`. The orphan-cleanup UI never
            sets force; the per-page settings modal "清空本页历史" sets
            force=true since it's an explicit user choice.
            """
            if not body.force:
                active_urls = {entry.url for entry, _ in whop_registry.list_pages(parent_chat_id=None)}
                if body.url is not None and body.url in active_urls:
                    raise HTTPException(
                        400,
                        detail="url is currently registered to an active page; remove the page first or pass force=true",
                    )
            async with session_scope(session_factory) as session:
                count = await repo.delete_tasks_by_url(session, body.url)
            # Keep runtime dedupe cache in sync with DB cleanup.
            await whop_registry.clear_seen_for_url(body.url)
            return OrphanCleanupResponse(deleted_count=count)

        @router.get("/api/whop/cookie", response_model=WhopCookieStatusOut)
        async def whop_cookie_status() -> WhopCookieStatusOut:
            from app.whop.login import cookie_path

            p = cookie_path()
            if not p.is_file():
                return WhopCookieStatusOut(exists=False, path=str(p))
            stat = p.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            now = datetime.now(UTC)
            age = (now - mtime).total_seconds()
            return WhopCookieStatusOut(
                exists=True,
                path=str(p),
                last_modified=mtime,
                age_seconds=age,
            )

    # ------------------------------------------------------------------ #
    # /api/orders — manual order submission (trading panel)               #
    # ------------------------------------------------------------------ #

    orders_svc = OrdersService(
        broker=broker,
        event_bus=bus,
        session_factory=session_factory,
        push_listener_getter=push_listener_getter,
    )

    @router.post("/api/orders", response_model=OrderOut, status_code=201)
    async def post_order(req: SubmitOrderRequest) -> OrderOut:
        if isinstance(broker, NoopBrokerClient):
            raise HTTPException(503, "No authorized broker; cannot submit order")
        try:
            return await orders_svc.submit(req)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except Exception as e:
            logger.exception("submit_order failed: %s %s %s @ %s", req.side, req.qty, req.symbol, req.price)
            raise HTTPException(502, f"broker error: {type(e).__name__}: {e}") from e

    @router.patch("/api/orders/{order_id}", status_code=204)
    async def patch_order(order_id: str, req: ReplaceOrderRequest) -> Response:
        if isinstance(broker, NoopBrokerClient):
            raise HTTPException(503, "No authorized broker; cannot replace order")
        try:
            await orders_svc.replace(order_id, req)
            return Response(status_code=204)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except Exception as e:
            logger.exception("replace_order failed: order_id=%s", order_id)
            raise HTTPException(502, f"broker error: {type(e).__name__}: {e}") from e

    @router.delete("/api/orders/{order_id}", status_code=204)
    async def delete_order(order_id: str) -> Response:
        if isinstance(broker, NoopBrokerClient):
            raise HTTPException(503, "No authorized broker; cannot cancel order")
        try:
            await orders_svc.cancel(order_id)
            return Response(status_code=204)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        except Exception as e:
            logger.exception("cancel_order failed: order_id=%s", order_id)
            raise HTTPException(502, f"broker error: {type(e).__name__}: {e}") from e

    @router.get("/api/orders", response_model=OrderListOut)
    async def get_orders(ticker: str) -> OrderListOut:
        return OrderListOut(orders=await orders_svc.list_today(ticker))

    # ------------------------------------------------------------------ #
    # /api/alerts — price / volume / pct-change alert CRUD               #
    # ------------------------------------------------------------------ #

    from app.alerts.repo import AlertRepo

    alerts_repo = AlertRepo(session_factory)

    def _alerts_service() -> AlertsService:
        engine = alerts_engine_getter() if alerts_engine_getter is not None else None
        if engine is None:
            raise HTTPException(503, "AlertEngine not available")
        return AlertsService(
            repo=alerts_repo, engine=engine, broker=broker, event_bus=bus
        )

    @router.get("/api/alerts", response_model=AlertListOut)
    async def get_alerts(ticker: str) -> AlertListOut:
        return AlertListOut(alerts=await alerts_repo.list_by_ticker(ticker))

    @router.post("/api/alerts", response_model=AlertOut, status_code=201)
    async def post_alert(req: AlertCreate) -> AlertOut:
        try:
            return await _alerts_service().create(req)
        except SymbolUnknown as e:
            raise HTTPException(422, str(e)) from e

    @router.patch("/api/alerts/{alert_id}", response_model=AlertOut)
    async def patch_alert(alert_id: int, req: AlertUpdate) -> AlertOut:
        try:
            return await _alerts_service().update(alert_id, req)
        except KeyError:
            raise HTTPException(404, f"alert {alert_id} not found") from None

    @router.delete("/api/alerts/{alert_id}", status_code=204)
    async def delete_alert(alert_id: int) -> Response:
        await _alerts_service().delete(alert_id)
        return Response(status_code=204)

    @router.get("/api/alerts/events", response_model=AlertEventListOut)
    async def get_alert_events(
        ticker: str | None = None, limit: int = 50,
    ) -> AlertEventListOut:
        return AlertEventListOut(events=await alerts_repo.list_events(ticker=ticker, limit=limit))

    return router
