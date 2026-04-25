"""REST API router factory for Signal Station (§7).

Provides six endpoints:
  GET  /api/tasks                — paginated, filterable task list
  GET  /api/tasks/{task_id}      — single task with push_events
  POST /api/tasks/{task_id}/cancel — cancel a brokerage order
  GET  /api/stats/today          — today's counts grouped by status
  GET  /api/positions            — positions from DB (positions table)
  GET  /api/health               — broker + mode liveness status

All routes are gated by ``require_app_token`` applied at the router level.

Usage::

    router = build_http_router(
        session_factory=_factory,
        broker=_broker,
        settings=_settings,
    )
    app.include_router(router)
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated

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
    task_to_out,
    task_to_summary,
)
from app.broker.broker_client import BrokerClient
from app.core.config import Settings
from app.domain.status import Status
from app.storage import repo
from app.storage.db import session_scope


def build_http_router(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    broker: BrokerClient,
    settings: Settings,
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

    return router
