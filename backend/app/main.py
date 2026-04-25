"""Signal Station backend —— FastAPI app assembly + startup/shutdown lifecycle."""
from __future__ import annotations

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
from app.broker.config import LongPortConfig, load_longport_config
from app.broker.push_listener import PushListener, register_push_listener
from app.broker.trader import register_trader
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.parser.context_resolver import load_watched_tickers
from app.parser.service import register_parser_service
from app.storage.db import Base, create_engine, make_session_factory
from app.storage.listeners import register_storage_listeners
from app.whop.listener import _is_placeholder_url
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
    push_listener: PushListener | None
    whop_registry: WhopRegistry


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
    state.push_listener = None

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

        # Broker -----------------------------------------------------------
        if broker_override is not None:
            state.broker = broker_override
        else:
            try:
                broker_cfg = load_longport_config()
                from app.broker.longport_client import LongPortClient

                state.broker = LongPortClient(broker_cfg)
            except (ValueError, ImportError) as exc:
                from app.broker.noop_client import NoopBrokerClient

                logger.warning(
                    "LongPortClient init failed (%s). Falling back to monitoring-only "
                    "mode (NoopBrokerClient). No orders will be submitted. "
                    "Set LONGPORT_* env vars in .env to enable real trading.",
                    exc,
                )
                state.broker = NoopBrokerClient()

        # Parser watchlist -------------------------------------------------
        try:
            watchlist = load_watched_tickers()
        except (FileNotFoundError, Exception):
            watchlist = set()

        # Wire up event-bus listeners --------------------------------------

        # 1. Parser service: MESSAGE_RECEIVED → task pipeline
        state.unsubs.append(
            register_parser_service(bus, session_factory, watched_tickers=watchlist)
        )

        # 2. Trader: TASK_INSTRUCTION_READY → broker order submission
        try:
            trader_cfg = load_longport_config()
        except ValueError:
            # No LongPort creds (test or paper monitoring mode) — build a
            # minimal config from Settings so the trader can still apply
            # auto_trade / dry_run / risk-limit logic.
            trader_cfg = LongPortConfig(
                mode="paper",
                app_key="",
                app_secret="",
                access_token="",
                auto_trade=settings.longport_auto_trade,
                dry_run=settings.longport_dry_run,
                max_option_total_price=settings.max_option_total_price,
                max_option_quantity=settings.max_option_quantity,
                price_deviation_tolerance=settings.price_deviation_tolerance,
                stock_price_deviation_tolerance=settings.stock_price_deviation_tolerance,
            )
        state.unsubs.append(register_trader(bus, state.broker, trader_cfg))

        # 3. Storage listeners: all task.* topics → DB persistence
        state.unsubs.extend(register_storage_listeners(bus, session_factory))

        # 4. Push listener: broker order-change callbacks → TASK_PUSH_EVENT
        state.push_listener = register_push_listener(bus, state.broker, session_factory)

        # 5. WebSocket hub: task.* topics → WS broadcast
        state.hub = WebSocketHub(bus)
        await state.hub.register_listeners()

        # 6. Whop registry (manages all Whop page listeners)
        state.whop_registry = WhopRegistry(
            bus=bus,
            settings=settings,
            session_factory=state.session_factory,
        )
        if not skip_whop:
            try:
                await state.whop_registry.load_and_start_all()
            except Exception as exc:  # noqa: BLE001
                logger.warning("whop registry startup failed: %s", exc)

            # Seed from .env on first run if pages file empty AND env URLs present
            if len(state.whop_registry._entries) == 0:
                if settings.whop_stock_url and not _is_placeholder_url(settings.whop_stock_url):
                    try:
                        await state.whop_registry.add_page(
                            url=settings.whop_stock_url,
                            source="stock",
                            name="Stock (from .env)",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("seed stock from .env failed: %s", exc)
                if settings.whop_option_url and not _is_placeholder_url(
                    settings.whop_option_url
                ):
                    try:
                        await state.whop_registry.add_page(
                            url=settings.whop_option_url,
                            source="option",
                            name="Option (from .env)",
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("seed option from .env failed: %s", exc)

        # Include routers now that all dependencies are ready.
        # FastAPI supports include_router inside lifespan; routes work for all
        # subsequent requests.
        app.include_router(
            build_http_router(
                session_factory=state.session_factory,
                broker=state.broker,
                settings=state.settings,
                whop_registry=state.whop_registry,
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
