"""Signal Station backend —— FastAPI app assembly + startup/shutdown lifecycle."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.http import build_http_router
from app.api.ws import WebSocketHub, build_ws_router
from app.broker.broker_client import BrokerClient
from app.broker.config import LongPortConfig, load_longport_config_from_runtime
from app.broker.runtime_settings import LongPortRuntimeStore
from app.broker.push_listener import PushListener, register_push_listener
from app.broker.trader import register_trader
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.parser.service import register_parser_service
from app.storage.db import Base, create_engine, make_session_factory
from app.storage.listeners import register_storage_listeners
from app.whop.chat_writer import register_chat_writer
from app.whop.registry import WhopRegistry

logger = logging.getLogger(__name__)


class AppState:
    """Container for cross-request state. Accessible via request.app.state.app_state."""

    settings: Settings
    engine: Any
    session_factory: Any
    bus: EventBus
    broker: BrokerClient
    hub: WebSocketHub
    unsubs: list[Callable[[], None]]
    trader_unsub: Callable[[], None] | None
    push_listener: PushListener | None
    whop_registry: WhopRegistry
    longport_runtime: LongPortRuntimeStore
    last_init_error: str | None


def create_app(
    *,
    settings: Settings | None = None,
    broker_override: BrokerClient | None = None,
    longport_runtime_override: LongPortRuntimeStore | None = None,
    skip_whop: bool = False,
) -> FastAPI:
    """App factory.

    Parameters
    ----------
    settings:
        Override the default ``get_settings()`` singleton.  Useful in tests.
    broker_override:
        Inject a ``FakeBrokerClient`` (or any BrokerClient) instead of
        instantiating a real ``LongPortClient``.  Useful in tests.
    longport_runtime_override:
        Inject a ``LongPortRuntimeStore`` (typically built from
        ``from_settings_defaults`` so it stays in-memory) so tests don't
        accidentally read or write the real ``data/longport_settings.json``.
    """
    if settings is None:
        settings = get_settings()

    # Configure the root logger so ``logger.info`` calls in app.* modules
    # (e.g. PushListener) actually surface. ``setLevel`` alone is NOT enough:
    # uvicorn installs handlers for ``uvicorn``/``uvicorn.access`` but never
    # touches the root logger, so app records propagate up to a handler-less
    # root and fall back to Python's WARNING-only ``lastResort`` handler.
    # ``basicConfig(force=True)`` installs a StreamHandler on root and sets
    # its level — required for INFO-level push listener logs to print.
    # Use uvicorn's DefaultFormatter so app.* lines get level colorization
    # matching uvicorn's own output (INFO green, WARNING yellow, ERROR red).
    from uvicorn.logging import DefaultFormatter

    _root_handler = logging.StreamHandler()
    _root_handler.setFormatter(
        DefaultFormatter("%(levelprefix)s %(name)s: %(message)s", use_colors=True)
    )
    logging.basicConfig(
        level=settings.log_level.upper(),
        handlers=[_root_handler],
        force=True,
    )

    state = AppState()
    state.settings = settings
    state.unsubs = []
    state.trader_unsub = None
    state.push_listener = None
    state.last_init_error = None
    state.subscription_manager = None
    state.market_schedule = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # ------------------------------------------------------------------ #
        # Startup                                                              #
        # ------------------------------------------------------------------ #
        engine = create_engine(settings.database_url)
        state.engine = engine
        session_factory = make_session_factory(engine)
        state.session_factory = session_factory

        # Always call create_all — idempotent on existing tables; works for
        # both in-memory test DBs and persistent SQLite files.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        bus = EventBus()
        state.bus = bus
        # When a test passes broker_override OR an explicit runtime override,
        # do NOT read/write the real settings file. Use the override (or an
        # in-memory store derived from Settings) so test runs stay hermetic.
        if longport_runtime_override is not None:
            state.longport_runtime = longport_runtime_override
        elif broker_override is not None:
            state.longport_runtime = LongPortRuntimeStore.from_settings_defaults(settings)
        else:
            state.longport_runtime = LongPortRuntimeStore()

        # Broker -----------------------------------------------------------
        # Building the broker is encapsulated in a closure so we can re-run it
        # at runtime (POST /api/longport/broker/reload) — the user updates
        # creds via the UI and triggers a rebuild without restarting backend.

        def _build_broker() -> tuple[BrokerClient, str | None]:
            """Construct LongPortClient with current runtime creds, or fall
            back to NoopBrokerClient. Returns (broker, init_error_or_None).
            ``broker_override`` short-circuits both paths (used by tests).
            """
            if broker_override is not None:
                return broker_override, None
            from app.broker.longport_client import LongPortClient
            from app.broker.noop_client import NoopBrokerClient

            try:
                cfg = load_longport_config_from_runtime(
                    state.longport_runtime.get(),
                    settings=settings,
                )
                # dry_run_getter lets the UI's dry_run toggle take effect on
                # the next submit without rebuilding the broker — same pattern
                # as the trader's auto_trade_getter.
                return (
                    LongPortClient(
                        cfg,
                        dry_run_getter=lambda: state.longport_runtime.get().dry_run,
                    ),
                    None,
                )
            except Exception as exc:  # noqa: BLE001 — widened from (ValueError, ImportError)
                # Network / SDK errors can also surface during Quote/TradeContext
                # init or subscribe(). Falling back to Noop is the right behavior
                # for those too — the UI can show the error and let the user
                # retry via the refresh button.
                logger.warning(
                    "LongPortClient init failed (%s). Falling back to "
                    "NoopBrokerClient. Configure LongPort credentials in the UI "
                    "settings and click refresh to retry.",
                    exc,
                )
                return NoopBrokerClient(), f"{type(exc).__name__}: {exc}"

        state.broker, state.last_init_error = _build_broker()

        # Whop registry — constructed early (without starting listeners) so the
        # ParserService can hold a reference and look up per-page tickers by url.
        # WhopRegistry.__init__ is side-effect-free; load_entries() at the end of
        # this lifespan reads data/whop_pages.json. Listeners stay OFF until the
        # user explicitly toggles them on from the dashboard.
        state.whop_registry = WhopRegistry(
            bus=bus,
            settings=settings,
            session_factory=state.session_factory,
        )

        # Wire up event-bus listeners --------------------------------------

        # 1. Parser service: MESSAGE_RECEIVED → task pipeline
        state.unsubs.append(
            register_parser_service(bus, session_factory, registry=state.whop_registry)
        )

        # Storage listeners (broker-independent) — register once.
        state.unsubs.extend(register_storage_listeners(bus, session_factory))

        # Chat writer: CHAT_MESSAGE_RECEIVED → persist + publish CHAT_MESSAGE_STORED.
        state.unsubs.extend(register_chat_writer(bus, session_factory, settings.data_dir))

        # Trader + push_listener are broker-dependent. Wrap in a closure so
        # _broker_reload() below can tear them down and rebuild against the
        # new broker without restarting the process.

        def _make_trader_cfg() -> LongPortConfig:
            runtime = state.longport_runtime.get()
            try:
                return load_longport_config_from_runtime(runtime, settings=settings)
            except ValueError:
                # No active account / not yet authorized; trader still
                # uses runtime auto_trade + dry_run gates so confirmations
                # and risk math keep working even before the user logs in.
                return LongPortConfig(
                    account_id="",
                    label="",
                    region=runtime.region,
                    auto_trade=runtime.auto_trade,
                    dry_run=runtime.dry_run,
                    max_option_total_price=settings.max_option_total_price,
                    max_option_quantity=settings.max_option_quantity,
                    price_deviation_tolerance=settings.price_deviation_tolerance,
                    stock_price_deviation_tolerance=settings.stock_price_deviation_tolerance,
                )

        def _register_trader_and_push() -> None:
            from app.storage.repo import SqlTaskQueryRepo

            # Order matters: build the push_listener first so the trader can
            # call ``replay_for_order`` on it after each successful submit.
            # The buffer in push_listener is what catches pushes that arrive
            # while the trader's synchronous _submit is blocking the loop.
            state.push_listener = register_push_listener(
                bus, state.broker, session_factory
            )
            state.trader_unsub = register_trader(
                bus,
                state.broker,
                _make_trader_cfg(),
                registry=state.whop_registry,
                auto_trade_getter=lambda: state.longport_runtime.get().auto_trade,
                task_query_repo=SqlTaskQueryRepo(session_factory),
                session_factory=session_factory,
                push_listener=state.push_listener,
            )

        def _build_subscription_manager() -> None:
            """Wire SubscriptionManager + MarketSchedule to the current
            broker and bind bus-publishing listeners. Called once at
            startup and again after each ``_broker_reload``.

            Two bus listeners are registered:
              - Quote push → ``Topics.QUOTE_SNAPSHOT`` (per-symbol live price)
              - Execution push → ``Topics.EXECUTION_UPDATE`` (per-fill row)

            The MarketSchedule cache is also bound here — its initial
            refresh runs as a "default task" alongside the subscription
            attach. Subsequent calls reuse the cache (6h fatigue) so
            the SDK isn't hit on every quote.
            """
            from app.broker.market_schedule import MarketSchedule
            from app.broker.subscription_manager import SubscriptionManager
            from app.core.event_bus import Event
            from app.core.events import (
                ExecutionPayload,
                QuoteSnapshotPayload,
                Topics,
            )

            loop = asyncio.get_running_loop()
            mgr = SubscriptionManager(state.broker, loop)

            schedule = MarketSchedule(state.broker)
            state.market_schedule = schedule
            # Inject the schedule into the broker so internal state
            # lookups (``_market_state_for``) hit the cached service
            # instead of issuing per-quote SDK calls.
            if hasattr(state.broker, "bind_market_schedule"):
                state.broker.bind_market_schedule(schedule)
            # Default task: kick off the initial refresh in the
            # background so the cache is warm by the time the first
            # push arrives. Failure is logged but not fatal — the
            # state_for fallback uses the static clock heuristic.
            asyncio.ensure_future(schedule.maybe_refresh())

            def _publish_quote(symbol: str, quote: dict[str, Any]) -> None:
                # SDK thread → marshal onto loop. Closure captures ``bus``
                # via the outer scope, so the lambda body stays small.
                payload = QuoteSnapshotPayload(symbol=symbol, quote=quote)
                event = Event(Topics.QUOTE_SNAPSHOT, payload)
                try:
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(bus.publish(event))
                    )
                except RuntimeError:
                    logger.debug("quote dispatch: loop closed")

            def _publish_execution(exec_dict: dict[str, Any]) -> None:
                payload = ExecutionPayload(
                    order_id=exec_dict["order_id"],
                    symbol=exec_dict["symbol"],
                    ticker=exec_dict["ticker"],
                    side=exec_dict["side"],
                    qty=exec_dict["qty"],
                    price=exec_dict["price"],
                    ts=exec_dict.get("ts"),
                )
                event = Event(Topics.EXECUTION_UPDATE, payload)
                try:
                    loop.call_soon_threadsafe(
                        lambda: asyncio.ensure_future(bus.publish(event))
                    )
                except RuntimeError:
                    logger.debug("execution dispatch: loop closed")

            mgr.add_quote_listener(_publish_quote)
            mgr.add_execution_listener(_publish_execution)
            mgr.attach()
            state.subscription_manager = mgr

        _register_trader_and_push()
        _build_subscription_manager()

        # AlertEngine — evaluates enabled alerts against live quote pushes.
        from app.alerts.engine import AlertEngine
        from app.alerts.repo import AlertRepo as _AlertRepo

        _alerts_repo = _AlertRepo(session_factory)
        alerts_engine = AlertEngine(repo=_alerts_repo, broker=state.broker, event_bus=bus)
        await alerts_engine.start()
        app.state.alerts_engine = alerts_engine

        # Broker status / reload — surfaced via /api/longport/broker/* so the
        # UI can show "real / noop / error" and let the user retry init after
        # filling in credentials, without restarting the backend process.
        _reload_lock = asyncio.Lock()

        def _broker_status() -> dict[str, Any]:
            from app.broker.longport_client import LongPortClient

            # ``account_label`` replaces the prior paper/real ``mode``
            # field in the BrokerStatusOut payload. Real SDK broker has
            # ``account_label`` from its current LongPortConfig; Noop has
            # an empty string.
            return {
                "is_real": isinstance(state.broker, LongPortClient),
                "account_label": getattr(state.broker, "account_label", ""),
                "dry_run": state.broker.dry_run,
                "last_init_error": state.last_init_error,
            }

        async def _broker_reload() -> dict[str, Any]:
            async with _reload_lock:
                logger.info("broker reload: starting (current is_real=%s, last_init_error=%s)",
                            type(state.broker).__name__ != "NoopBrokerClient",
                            state.last_init_error)
                # 0. Drain any in-flight TASK_INSTRUCTION_READY (or other
                #    bus traffic) so we don't unsubscribe the trader handler
                #    out from under a half-processed event. Without this, a
                #    parser publish that lands in the unsub→re-subscribe
                #    window has no listener and the task is silently
                #    abandoned at INSTRUCTION_READY.
                try:
                    await bus.wait_idle(timeout=2.0)
                except TimeoutError:
                    logger.warning(
                        "broker reload: bus did not idle within 2s; "
                        "proceeding anyway. In-flight events may be lost."
                    )

                # 1. Tear down trader subscription (so it stops receiving events
                #    on the old broker reference).
                if state.trader_unsub is not None:
                    try:
                        state.trader_unsub()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("trader unsub during reload failed: %s", exc)
                    state.trader_unsub = None

                # 2. Drop push_listener reference. There is no formal teardown —
                #    closing the broker below releases its push handler list,
                #    which makes the old _sync_callback unreachable.
                state.push_listener = None

                # 2a. Detach SubscriptionManager from the OLD broker —
                #     unsubscribes all watched symbols at the SDK level so
                #     the next broker doesn't inherit stale subs. Listener
                #     callbacks (bus publishers) are tied to the manager
                #     instance; rebuilding the manager on the new broker
                #     wires fresh callbacks. Front-end re-issues
                #     /api/quotes/watch with the new account's positions.
                if state.subscription_manager is not None:
                    try:
                        state.subscription_manager.detach()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "subscription_manager detach during reload failed: %s", exc,
                        )
                    state.subscription_manager = None

                # 2b. Drop MarketSchedule — it'll be rebuilt against
                # the new broker by ``_build_subscription_manager``.
                # Account-switch typically also changes which markets
                # the user has access to; starting cold is safe.
                state.market_schedule = None

                # 3. Close the old broker (releases SDK resources / WebSocket).
                try:
                    state.broker.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("broker close during reload failed: %s", exc)

                # 4. Build fresh broker from current runtime settings.
                state.broker, state.last_init_error = _build_broker()

                # 5. Re-register trader + push_listener + QuoteHub against
                #    the new broker.
                _register_trader_and_push()
                _build_subscription_manager()

                from app.broker.longport_client import LongPortClient
                is_real = isinstance(state.broker, LongPortClient)
                logger.info(
                    "broker reload: complete — is_real=%s, last_init_error=%s",
                    is_real,
                    state.last_init_error,
                )
                return _broker_status()

        # 5. WebSocket hub: task.* topics → WS broadcast
        state.hub = WebSocketHub(bus)
        await state.hub.register_listeners()

        # 6. Load Whop entries from disk (does NOT start any listeners — user
        #    explicitly toggles each page on via the dashboard).
        if not skip_whop:
            try:
                await state.whop_registry.load_entries()
            except Exception as exc:  # noqa: BLE001
                logger.warning("whop registry load failed: %s", exc)

            # Register the simulator's virtual page so trader gates (whitelist,
            # qty resolution) work end-to-end for sim:// tasks. Ephemeral —
            # never persisted; re-registered on every restart.
            from app.sim.virtual_page import register_sim_page
            register_sim_page(state.whop_registry)

            # Seed default monitoring pages on first run (when pages file empty).
            # User can later remove or modify them via the Whop management UI.
            # Note: WHOP_STOCK_URL / WHOP_OPTION_URL env vars are no longer
            # consulted here — the seed is hardcoded to the canonical pair.
            if len(state.whop_registry._entries) == 0:
                _DEFAULT_PAGES = [
                    (
                        "https://whop.com/joined/stock-and-option/-GiWyN1ZTuUjwlG/app/",
                        "stock",
                        "正股发布",
                    ),
                    (
                        "https://whop.com/joined/stock-and-option/-gZyq1MzOZAWO98/app/",
                        "option",
                        "期权发布",
                    ),
                ]
                for _url, _source, _name in _DEFAULT_PAGES:
                    try:
                        await state.whop_registry.add_page(
                            url=_url, source=_source, name=_name
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("default seed %s failed: %s", _name, exc)

        # Include routers now that all dependencies are ready.
        # FastAPI supports include_router inside lifespan; routes work for all
        # subsequent requests.
        app.include_router(
            build_http_router(
                session_factory=state.session_factory,
                broker=state.broker,
                settings=state.settings,
                bus=state.bus,
                longport_runtime=state.longport_runtime,
                whop_registry=state.whop_registry,
                broker_getter=lambda: state.broker,
                broker_status_fn=_broker_status,
                broker_reload_fn=_broker_reload,
                subscription_manager_getter=lambda: state.subscription_manager,
                alerts_engine_getter=lambda: app.state.alerts_engine,
                push_listener_getter=lambda: state.push_listener,
            )
        )
        app.include_router(build_ws_router(state.hub, state.settings))

        # Simulator router — exercises the real bus → parser → DB → WS pipeline
        # with prebuilt scenarios so the operator can preview UI behaviour
        # without making real broker calls.
        from app.api.sim import build_sim_router
        app.include_router(
            build_sim_router(
                bus=state.bus,
                session_factory=state.session_factory,
                push_listener_getter=lambda: state.push_listener,
            )
        )

        # ── Static frontend mount (after API/WS routers) ──────────────────
        _DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
        if _DIST_DIR.is_dir():
            # Mount /assets as StaticFiles for hashed JS/CSS bundles
            _assets_dir = _DIST_DIR / "assets"
            if _assets_dir.is_dir():
                app.mount(
                    "/assets",
                    StaticFiles(directory=_assets_dir),
                    name="assets",
                )

            # SPA catch-all: any path not matched by /api or /ws serves index.html.
            # Real static files (favicon, etc.) are served directly if they exist.
            @app.get("/{full_path:path}", include_in_schema=False)
            async def _spa_fallback(full_path: str) -> FileResponse:  # noqa: RUF029
                target = _DIST_DIR / full_path
                if target.is_file():
                    return FileResponse(target)
                return FileResponse(_DIST_DIR / "index.html")

            logger.info("Static frontend mounted from %s", _DIST_DIR)
        else:
            logger.warning(
                "frontend/dist not found — running in API-only mode "
                "(build with `cd frontend && npm run build` to enable static UI)",
            )

        logger.info(
            "signal-station backend started (mode=%s, dry_run=%s)",
            "paper" if state.broker.is_paper else "real",
            state.broker.dry_run,
        )

        yield

        # ------------------------------------------------------------------ #
        # Shutdown                                                             #
        # ------------------------------------------------------------------ #
        logger.info("shutting down signal-station backend...")

        if hasattr(app.state, "alerts_engine"):
            try:
                await app.state.alerts_engine.stop()
            except Exception as exc:  # noqa: BLE001
                logger.warning("alerts_engine stop error: %s", exc)

        if hasattr(state, "whop_registry"):
            try:
                await state.whop_registry.shutdown_all()
            except Exception as exc:  # noqa: BLE001
                logger.warning("whop registry shutdown error: %s", exc)

        await state.hub.close()

        if state.trader_unsub is not None:
            try:
                state.trader_unsub()
            except Exception as exc:  # noqa: BLE001
                logger.warning("trader unsub failed: %s", exc)
            state.trader_unsub = None

        for unsub in state.unsubs:
            try:
                unsub()
            except Exception as exc:  # noqa: BLE001
                logger.warning("unsub failed: %s", exc)
        state.unsubs.clear()

        await bus.aclose()

        try:
            state.broker.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("broker close failed: %s", exc)

        await engine.dispose()

    app = FastAPI(
        title="Signal Station",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.app_state = state

    return app


# ---------------------------------------------------------------------------
# Module-level app for `uvicorn app.main:app`
# ---------------------------------------------------------------------------
# This will raise at import time if LONGPORT_* credentials are absent and no
# broker_override is provided — which is intentional (fail-fast for prod).
# For tests, import `create_app` directly and pass `broker_override=`.
app = create_app()


if __name__ == "__main__":
    import uvicorn

    _settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=_settings.http_host,
        port=_settings.http_port,
        reload=True,
    )
