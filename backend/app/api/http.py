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

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.auth import require_app_token
from app.api.schemas import (
    CancelOk,
    HealthOut,
    PositionOut,
    PositionsOut,
    StatsTodayOut,
    TaskListOut,
    TaskOut,
    TickerConfigOut,
    WhopCookieStatusOut,
    WhopPageCreate,
    WhopPageOut,
    WhopPageSettingsOut,
    WhopPageSettingsPatch,
    WhopPagesOut,
    task_to_out,
    task_to_summary,
    whop_page_to_out,
)
from app.broker.broker_client import BrokerClient
from app.core.config import Settings
from app.domain.status import Status
from app.storage import repo
from app.storage.db import session_scope

if TYPE_CHECKING:
    from app.whop.registry import WhopRegistry


def build_http_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    broker: BrokerClient,
    settings: Settings,
    whop_registry: WhopRegistry | None = None,
) -> APIRouter:
    """Factory — injects session_factory, broker, and settings at app assembly.

    All routes share ``dependencies=[Depends(require_app_token)]`` applied at
    the router level, so auth is enforced uniformly without per-route boilerplate.
    """
    router = APIRouter(dependencies=[Depends(require_app_token)])

    # ------------------------------------------------------------------ #
    # GET /api/tasks                                                        #
    # ------------------------------------------------------------------ #

    @router.get("/api/tasks", response_model=TaskListOut)
    async def list_tasks_endpoint(
        limit: int = Query(50, ge=1, le=200),
        cursor: datetime | None = None,
        status: str | None = None,
        type: Annotated[str | None, Query(alias="type")] = None,
        symbol: str | None = None,
    ) -> TaskListOut:
        """Return a paginated, optionally-filtered list of tasks.

        Pagination is cursor-based: pass ``cursor=<ISO-datetime>`` from
        ``next_cursor`` in the previous page to advance.  ``next_cursor`` is
        ``null`` when no further pages exist.
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
            )
        summaries = [task_to_summary(t) for t in tasks]
        next_cur: datetime | None = tasks[-1].created_at if len(tasks) == limit else None
        return TaskListOut(tasks=summaries, next_cursor=next_cur)

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
            broker.cancel_order(task.order_id)
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

        Sourced from the ``positions`` table (populated by a future broker-sync
        job — returns empty lists until that sync runs).
        """
        async with session_scope(session_factory) as session:
            rows = await repo.list_positions(session)

        stocks: list[PositionOut] = []
        options: list[PositionOut] = []
        for row in rows:
            pos = PositionOut(
                symbol=row.symbol,
                type=row.type,
                ticker=row.ticker,
                quantity=row.quantity,
                avg_cost=row.avg_cost,
                option_strike=row.option_strike,
                option_expiry=row.option_expiry,
                option_type=row.option_type,
            )
            if row.type == "option":
                options.append(pos)
            else:
                stocks.append(pos)

        return PositionsOut(stocks=stocks, options=options)

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
        return HealthOut(
            whop="down",
            longport="up",
            mode="paper" if broker.is_paper else "real",
            dry_run=broker.dry_run,
        )

    # Satisfy Settings reference so mypy knows it's consumed.
    _ = settings

    # ------------------------------------------------------------------ #
    # Whop monitoring management (only when registry provided)             #
    # ------------------------------------------------------------------ #

    if whop_registry is not None:

        @router.get("/api/whop/pages", response_model=WhopPagesOut)
        async def list_whop_pages() -> WhopPagesOut:
            pages = whop_registry.list_pages()
            return WhopPagesOut(pages=[whop_page_to_out(e, ll) for e, ll in pages])

        @router.post("/api/whop/pages", response_model=WhopPageOut, status_code=201)
        async def create_whop_page(body: WhopPageCreate) -> WhopPageOut:
            try:
                entry = await whop_registry.add_page(
                    url=body.url, source=body.source, name=body.name
                )
            except ValueError as exc:
                raise HTTPException(400, detail=str(exc)) from exc
            # Re-read to include listener status
            for e, ll in whop_registry.list_pages():
                if e.id == entry.id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="added but lost track")

        @router.delete("/api/whop/pages/{page_id}", status_code=204)
        async def delete_whop_page(page_id: str) -> None:
            ok = await whop_registry.remove_page(page_id)
            if not ok:
                raise HTTPException(404, detail="page not found")

        @router.post("/api/whop/pages/{page_id}/restart", response_model=WhopPageOut)
        async def restart_whop_page(page_id: str) -> WhopPageOut:
            ok = await whop_registry.restart_page(page_id)
            if not ok:
                raise HTTPException(404, detail="page not found or restart failed")
            for e, ll in whop_registry.list_pages():
                if e.id == page_id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="restart succeeded but lost track")

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
            if body.tickers is not None:
                patch_dict["tickers"] = {
                    k: {"trade_quantity": v.trade_quantity} for k, v in body.tickers.items()
                }
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
            for e, ll in whop_registry.list_pages():
                if e.id == entry.id:
                    return whop_page_to_out(e, ll)
            raise HTTPException(500, detail="updated but lost track")

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

    return router
