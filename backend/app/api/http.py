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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

from app.api.auth import require_app_token
from app.api.schemas import (
    BrokerStatusOut,
    CancelOk,
    HealthOut,
    LongPortCredentialSet,
    LongPortSettingsOut,
    LongPortSettingsPatch,
    OrphanCleanupRequest,
    OrphanCleanupResponse,
    PositionOut,
    PositionsOut,
    StatsTodayOut,
    TaskCountOut,
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
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings
from app.domain.status import Status
from app.core.event_bus import Event
from app.core.events import TaskPayload, Topics
from app.storage import repo
from app.storage.db import session_scope

if TYPE_CHECKING:
    from app.core.event_bus import EventBus
    from app.whop.registry import WhopRegistry


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
            mode=runtime.mode,
            paper=LongPortCredentialSet(
                app_key=runtime.paper.app_key,
                app_secret=runtime.paper.app_secret,
                access_token=runtime.paper.access_token,
            ),
            real=LongPortCredentialSet(
                app_key=runtime.real.app_key,
                app_secret=runtime.real.app_secret,
                access_token=runtime.real.access_token,
            ),
            auto_trade=runtime.auto_trade,
            region=runtime.region,
            dry_run=runtime.dry_run,
        )

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
            mode=_longport_settings_out().mode,
            dry_run=_longport_settings_out().dry_run,
        )

    @router.get("/api/longport/settings", response_model=LongPortSettingsOut)
    async def get_longport_settings() -> LongPortSettingsOut:
        return _longport_settings_out()

    @router.patch("/api/longport/settings", response_model=LongPortSettingsOut)
    async def patch_longport_settings(body: LongPortSettingsPatch) -> LongPortSettingsOut:
        patch: dict[str, object] = {}
        if body.mode is not None:
            patch["mode"] = body.mode
        # Credentials: per-field merge. An empty string means "keep existing"
        # — this prevents a UI form glitch (e.g. one of the long-string fields
        # accidentally cleared during paste / selection) from wiping real
        # credentials. To explicitly clear a credential the user can edit the
        # runtime JSON file directly; the UI never has a legitimate reason to
        # set a field to "".
        current = runtime_store.get()
        if body.paper is not None:
            patch["paper"] = {
                "app_key": body.paper.app_key or current.paper.app_key,
                "app_secret": body.paper.app_secret or current.paper.app_secret,
                "access_token": body.paper.access_token or current.paper.access_token,
            }
        if body.real is not None:
            patch["real"] = {
                "app_key": body.real.app_key or current.real.app_key,
                "app_secret": body.real.app_secret or current.real.app_secret,
                "access_token": body.real.access_token or current.real.access_token,
            }
        if body.auto_trade is not None:
            patch["auto_trade"] = body.auto_trade
        if body.region is not None:
            patch["region"] = body.region
        if body.dry_run is not None:
            patch["dry_run"] = body.dry_run
        runtime_store.update(patch)
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
                mode=str(snap.get("mode", "paper")),
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
                mode=str(snap.get("mode", "paper")),
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
            for e, ll in whop_registry.list_pages():
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
            for e, ll in whop_registry.list_pages():
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

        @router.post("/api/whop/orphan/cleanup", response_model=OrphanCleanupResponse)
        async def cleanup_orphan_tasks(body: OrphanCleanupRequest) -> OrphanCleanupResponse:
            """Delete all tasks (and linked rows) for a given url.

            Defensive: rejects (400) if the url is currently registered to an
            active page — unless `force=true`. The orphan-cleanup UI never
            sets force; the per-page settings modal "清空本页历史" sets
            force=true since it's an explicit user choice.
            """
            if not body.force:
                active_urls = {entry.url for entry, _ in whop_registry.list_pages()}
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

    return router
