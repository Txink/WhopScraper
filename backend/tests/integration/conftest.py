"""Integration test fixtures.

Provides:
- ``fake_broker`` — a FakeBrokerClient with full tracking for orders (submitted,
  replaced, cancelled) and quote-push wiring used by AlertEngine.
- ``client`` — async httpx.AsyncClient backed by a real FastAPI app with lifespan
  triggered, authenticated with the test token.
- ``noop_client`` — same but with NoopBrokerClient (so /api/orders returns 503).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.broker.noop_client import NoopBrokerClient
from app.core.config import Settings, get_settings
from app.main import create_app

_TOKEN = "integration-test-token"


# ---------------------------------------------------------------------------
# FakeBroker — order tracking + quote-push wiring
# ---------------------------------------------------------------------------


class FakeBrokerIntegration:
    """FakeBroker with full order + quote support for integration tests.

    Order methods:
        submitted    — list of dicts with all submit kwargs
        replaced     — list of dicts {order_id, price, qty}
        cancelled    — list of order_id strings
        Returns sequential ord-1, ord-2, ... IDs from submit_stock_order.

    Quote methods:
        subscribed   — set[str] of currently-subscribed symbols
        fire_quote(symbol, payload) — invoke the registered on_quote handler
        set_on_quote(cb)            — register the single on-quote callback
    """

    is_paper: bool = True
    dry_run: bool = False
    account_id: str = "fake-integration-acct"

    def __init__(self) -> None:
        self._order_counter = 0
        self.submitted: list[dict[str, Any]] = []
        self.replaced: list[dict[str, Any]] = []
        self.cancelled: list[str] = []
        self.subscribed: set[str] = set()
        self._quote_cb = None

    # ---- order methods --------------------------------------------------------

    def submit_stock_order(self, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        self._order_counter += 1
        order_id = f"ord-{self._order_counter}"
        self.submitted.append({"order_id": order_id, **kwargs})
        return order_id

    def submit_option_order(self, **kwargs: Any) -> str:  # type: ignore[no-untyped-def]
        self._order_counter += 1
        return f"ord-{self._order_counter}"

    def replace_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        price: float | None = None,
    ) -> None:
        self.replaced.append({"order_id": order_id, "price": price, "qty": quantity})

    def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)

    def today_orders(self, *, ticker: str | None = None) -> list[dict[str, Any]]:  # type: ignore[type-arg]
        return []

    # ---- quote / alert engine methods ----------------------------------------

    def set_on_quote(self, cb: Any) -> None:
        self._quote_cb = cb

    def subscribe_quotes(self, symbols: list[str]) -> None:
        self.subscribed.update(symbols)

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        self.subscribed.difference_update(symbols)

    def fire_quote(self, symbol: str, payload: dict[str, Any]) -> None:
        """Test helper: invoke the registered on-quote callback."""
        assert self._quote_cb is not None, "fire_quote called before set_on_quote"
        self._quote_cb(symbol, payload)

    def get_quote(self, symbols: list[str]) -> dict[str, Any]:
        # Return a non-empty stub so AlertsService symbol validation passes.
        return {s: {"last_done": 100.0} for s in symbols}

    # ---- misc stubs required by BrokerClient protocol ------------------------

    def is_noop(self) -> bool:
        return False

    def subscribe_order_push(self, handler: Any) -> None:
        pass

    def today_executions(self) -> list[dict[str, Any]]:
        return []

    def history_executions(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def stock_positions(self) -> list[dict[str, Any]]:
        return []

    def fetch_trading_sessions(self) -> dict[str, Any]:
        return {}

    def fetch_trading_days(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings() -> Settings:
    return Settings(
        app_token=_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
    )


@asynccontextmanager
async def _make_async_client(broker: Any) -> AsyncIterator[AsyncClient]:
    """Spin up a FastAPI app with lifespan and yield an authenticated AsyncClient."""
    settings = _make_settings()
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    # Trigger the FastAPI lifespan context so routes are registered and
    # AlertEngine / OrdersService are wired up before any request is made.
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"Authorization": f"Bearer {_TOKEN}"},
        ) as ac:
            yield ac


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_broker() -> FakeBrokerIntegration:
    return FakeBrokerIntegration()


@pytest_asyncio.fixture
async def client(fake_broker: FakeBrokerIntegration) -> AsyncIterator[AsyncClient]:
    """AsyncClient backed by a full FastAPI app (lifespan included)."""
    async with _make_async_client(fake_broker) as ac:
        yield ac


@pytest_asyncio.fixture
async def noop_client() -> AsyncIterator[AsyncClient]:
    """AsyncClient backed by an app with NoopBrokerClient."""
    noop = NoopBrokerClient()
    async with _make_async_client(noop) as ac:
        yield ac
