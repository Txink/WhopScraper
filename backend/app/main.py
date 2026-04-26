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
    """
    if settings is None:
        settings = get_settings()

    state = AppState()
    state.settings = settings
    state.unsubs = []
    state.trader_unsub = None
    state.push_listener = None
    state.last_init_error = None

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
                return LongPortClient(cfg), None
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

        # Trader + push_listener are broker-dependent. Wrap in a closure so
        # _broker_reload() below can tear them down and rebuild against the
        # new broker without restarting the process.

        def _make_trader_cfg() -> LongPortConfig:
            runtime = state.longport_runtime.get()
            try:
                return load_longport_config_from_runtime(runtime, settings=settings)
            except ValueError:
                # No creds yet; trader still uses runtime auto_trade gate.
                return LongPortConfig(
                    mode=runtime.mode,
                    app_key="",
                    app_secret="",
                    access_token="",
                    region=runtime.region,
                    auto_trade=runtime.auto_trade,
                    dry_run=runtime.dry_run,
                    max_option_total_price=settings.max_option_total_price,
                    max_option_quantity=settings.max_option_quantity,
                    price_deviation_tolerance=settings.price_deviation_tolerance,
                    stock_price_deviation_tolerance=settings.stock_price_deviation_tolerance,
                )

        def _register_trader_and_push() -> None:
            state.trader_unsub = register_trader(
                bus,
                state.broker,
                _make_trader_cfg(),
                registry=state.whop_registry,
                auto_trade_getter=lambda: state.longport_runtime.get().auto_trade,
            )
            state.push_listener = register_push_listener(
                bus, state.broker, session_factory
            )

        _register_trader_and_push()

        # Broker status / reload — surfaced via /api/longport/broker/* so the
        # UI can show "real / noop / error" and let the user retry init after
        # filling in credentials, without restarting the backend process.
        _reload_lock = asyncio.Lock()

        def _broker_status() -> dict[str, Any]:
            from app.broker.longport_client import LongPortClient

            return {
                "is_real": isinstance(state.broker, LongPortClient),
                "mode": "paper" if state.broker.is_paper else "real",
                "dry_run": state.broker.dry_run,
                "last_init_error": state.last_init_error,
            }

        async def _broker_reload() -> dict[str, Any]:
            async with _reload_lock:
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

                # 3. Close the old broker (releases SDK resources / WebSocket).
                try:
                    state.broker.close()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("broker close during reload failed: %s", exc)

                # 4. Build fresh broker from current runtime settings.
                state.broker, state.last_init_error = _build_broker()

                # 5. Re-register trader + push_listener against the new broker.
                _register_trader_and_push()

                logger.info(
                    "broker reloaded — is_real=%s, error=%s",
                    isinstance(state.broker, type(state.broker)) and state.last_init_error is None,
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
            )
        )
        app.include_router(build_ws_router(state.hub, state.settings))

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
