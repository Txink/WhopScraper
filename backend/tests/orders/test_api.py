"""HTTP contract for /api/orders/* — happy + 422 + 502 + 503 paths."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.http import build_http_router
from app.broker.noop_client import NoopBrokerClient
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus

_TOKEN = "test-token-orders"


class _FakeBroker:
    """Minimal broker double for orders API tests."""

    is_paper = True
    dry_run = False
    account_id = "acct-test"

    def __init__(self) -> None:
        self._order_counter = 0

    def submit_stock_order(self, **kwargs) -> str:  # type: ignore[no-untyped-def]
        self._order_counter += 1
        return f"ord-{self._order_counter}"

    def replace_order(
        self, order_id: str, *, quantity: int | None = None, price: float | None = None
    ) -> None:
        pass

    def cancel_order(self, order_id: str) -> None:
        pass

    def today_orders(self, *, ticker: str | None = None) -> list[dict]:  # type: ignore[type-arg]
        return []

    # Additional methods required by BrokerClient protocol (stubs)
    def submit_option_order(self, **kwargs) -> str:  # type: ignore[no-untyped-def]
        return "noop"

    def get_quote(self, symbols: list[str]) -> dict:  # type: ignore[type-arg]
        return {}

    def subscribe_order_push(self, handler) -> None:  # type: ignore[no-untyped-def]
        pass

    def set_on_quote(self, handler) -> None:  # type: ignore[no-untyped-def]
        pass

    def subscribe_quotes(self, symbols: list[str]) -> None:
        pass

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        pass

    def today_executions(self) -> list[dict]:  # type: ignore[type-arg]
        return []

    def history_executions(self, **kwargs) -> list[dict]:  # type: ignore[no-untyped-def, type-arg]
        return []

    def fetch_trading_sessions(self) -> dict:  # type: ignore[type-arg]
        return {}

    def fetch_trading_days(self, **kwargs) -> dict:  # type: ignore[no-untyped-def, type-arg]
        return {}

    def stock_positions(self) -> list[dict]:  # type: ignore[type-arg]
        return []

    def close(self) -> None:
        pass


def _make_app(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    broker: object | None = None,
) -> FastAPI:
    _broker = broker or _FakeBroker()
    settings = Settings(app_token=_TOKEN)
    bus = EventBus()
    runtime_store = LongPortRuntimeStore(settings_file=tmp_path / "longport_settings.json")

    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=_broker,  # type: ignore[arg-type]
            settings=settings,
            bus=bus,
            longport_runtime=runtime_store,
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
def client(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> TestClient:
    app = _make_app(session_factory, tmp_path)
    return TestClient(
        app, raise_server_exceptions=True, headers={"Authorization": f"Bearer {_TOKEN}"}
    )


@pytest.fixture
def noop_client(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> TestClient:
    app = _make_app(session_factory, tmp_path / "noop", broker=NoopBrokerClient())
    return TestClient(
        app, raise_server_exceptions=False, headers={"Authorization": f"Bearer {_TOKEN}"}
    )


def test_submit_order_happy_path(client: TestClient) -> None:
    r = client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["source"] == "manual"
    assert data["order_id"]


def test_submit_order_validation_fails_without_price_for_limit(client: TestClient) -> None:
    r = client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200, "order_type": "LIMIT",
    })
    assert r.status_code == 422


def test_replace_order_requires_field(client: TestClient) -> None:
    client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    r = client.patch("/api/orders/ord-1", json={})
    assert r.status_code == 422


def test_get_orders_returns_list(client: TestClient) -> None:
    r = client.get("/api/orders?ticker=AAPL")
    assert r.status_code == 200
    assert "orders" in r.json()


def test_submit_503_when_noop_broker(noop_client: TestClient) -> None:
    r = noop_client.post("/api/orders", json={
        "symbol": "AAPL.US", "side": "BUY", "qty": 200,
        "order_type": "LIMIT", "price": 199.0,
    })
    assert r.status_code == 503


def test_replace_503_when_noop_broker(noop_client: TestClient) -> None:
    r = noop_client.patch("/api/orders/ord-1", json={"price": 199.5})
    assert r.status_code == 503


def test_cancel_503_when_noop_broker(noop_client: TestClient) -> None:
    r = noop_client.delete("/api/orders/ord-1")
    assert r.status_code == 503
