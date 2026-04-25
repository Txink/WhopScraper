"""Signal Station backend —— FastAPI app assembly + startup/shutdown lifecycle."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

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


def create_app(
    *,
    settings: Settings | None = None,
    broker_override: BrokerClient | None = None,
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
                logger.warning(
                    "LongPortClient init failed (%s) — startup aborted. "
                    "Set LONGPORT_* env vars or pass broker_override= for tests.",
                    exc,
                )
                raise

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

        # Include routers now that all dependencies are ready.
        # FastAPI supports include_router inside lifespan; routes work for all
        # subsequent requests.
        app.include_router(
            build_http_router(
                session_factory=state.session_factory,
                broker=state.broker,
                settings=state.settings,
            )
        )
        app.include_router(build_ws_router(state.hub, state.settings))

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
