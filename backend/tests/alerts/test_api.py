"""HTTP contract for /api/alerts/* — CRUD + 422 + 404."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.http import build_http_router
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus

_TOKEN = "test-token-alerts"


class _FakeEngine:
    """Minimal AlertEngine double for API tests."""

    async def on_alert_changed(self, action: str, alert) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class _GoodBroker:
    """Broker that always returns a quote for any symbol."""

    is_paper = True
    dry_run = False
    account_id = "acct-test"

    def get_quote(self, symbols: list[str]) -> dict:
        return {s: {"last_done": 100.0} for s in symbols}

    # Additional stubs required by BrokerClient protocol
    def submit_stock_order(self, **kwargs) -> str:
        return "noop"

    def submit_option_order(self, **kwargs) -> str:
        return "noop"

    def cancel_order(self, order_id: str) -> None:
        pass

    def replace_order(self, order_id: str, **kwargs) -> None:
        pass

    def today_orders(self, *, ticker: str | None = None) -> list:
        return []

    def subscribe_order_push(self, handler) -> None:
        pass

    def set_on_quote(self, handler) -> None:
        pass

    def subscribe_quotes(self, symbols: list[str]) -> None:
        pass

    def unsubscribe_quotes(self, symbols: list[str]) -> None:
        pass

    def is_noop(self) -> bool:
        return False

    def today_executions(self) -> list:
        return []

    def history_executions(self, **kwargs) -> list:
        return []

    def fetch_trading_sessions(self) -> dict:
        return {}

    def fetch_trading_days(self, **kwargs) -> dict:
        return {}

    def stock_positions(self) -> list:
        return []

    def close(self) -> None:
        pass


class _BadBroker(_GoodBroker):
    """Broker that never returns quotes."""

    def get_quote(self, symbols: list[str]) -> dict:
        return {}


def _make_app(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    broker=None,
) -> FastAPI:
    _broker = broker or _GoodBroker()
    settings = Settings(app_token=_TOKEN)
    bus = EventBus()
    runtime_store = LongPortRuntimeStore(settings_file=tmp_path / "longport_settings.json")
    engine = _FakeEngine()

    app = FastAPI()
    # Stub the alerts engine so the route factory can find it
    app.state.alerts_engine = engine

    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=_broker,  # type: ignore[arg-type]
            settings=settings,
            bus=bus,
            longport_runtime=runtime_store,
            alerts_engine_getter=lambda: engine,
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
def client_bad_quote(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> TestClient:
    app = _make_app(session_factory, tmp_path / "bad_quote", broker=_BadBroker())
    return TestClient(
        app, raise_server_exceptions=True, headers={"Authorization": f"Bearer {_TOKEN}"}
    )


def test_create_alert_happy(client: TestClient) -> None:
    r = client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    assert r.status_code == 201, r.text
    assert r.json()["enabled"] is True


def test_list_alerts_filtered_by_ticker(client: TestClient) -> None:
    client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    r = client.get("/api/alerts?ticker=AAPL")
    assert r.status_code == 200
    assert len(r.json()["alerts"]) == 1


def test_patch_alert_toggle_disabled(client: TestClient) -> None:
    r1 = client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    alert_id = r1.json()["id"]
    r2 = client.patch(f"/api/alerts/{alert_id}", json={"enabled": False})
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False


def test_delete_alert(client: TestClient) -> None:
    r1 = client.post("/api/alerts", json={
        "ticker": "AAPL", "symbol": "AAPL.US",
        "condition_type": "price", "operator": ">=", "threshold": 200.0,
    })
    alert_id = r1.json()["id"]
    r2 = client.delete(f"/api/alerts/{alert_id}")
    assert r2.status_code == 204


def test_create_alert_unknown_symbol_422(client_bad_quote: TestClient) -> None:
    r = client_bad_quote.post("/api/alerts", json={
        "ticker": "ZZZZ", "symbol": "ZZZZ.US",
        "condition_type": "price", "operator": ">=", "threshold": 1.0,
    })
    assert r.status_code == 422


def test_patch_alert_404_when_not_found(client: TestClient) -> None:
    r = client.patch("/api/alerts/99999", json={"enabled": False})
    assert r.status_code == 404


def test_get_alert_events_returns_list(client: TestClient) -> None:
    r = client.get("/api/alerts/events?ticker=AAPL&limit=10")
    assert r.status_code == 200
    assert "events" in r.json()
    # Newly-created service with no triggers yet → empty list.
    assert r.json()["events"] == []
