"""REST endpoint tests for /api/whop/pages/{id}/start and /stop (explicit on/off)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http import build_http_router
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.whop.registry import WhopPageEntry, WhopRegistry

_TOKEN = "test-whop-lifecycle-token"


# ---------------------------------------------------------------------------
# Fake browser
# ---------------------------------------------------------------------------


class _FakeBrowser:
    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002 ANN003
        self.closed = False

    async def start(self) -> None:
        return None

    async def navigate(self, url: str) -> bool:  # noqa: ARG002
        return True

    async def scrape_html(self) -> str:
        return "<html></html>"

    async def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_test() -> Settings:
    return Settings(
        app_token=_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        whop_poll_interval=0.05,
        whop_headless=True,
    )


@pytest.fixture
def patch_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.whop.listener.WhopBrowser", _FakeBrowser)


@pytest.fixture
def registry_and_client(
    patch_browser: None,
    settings_test: Settings,
    tmp_path: Path,
):
    """Build app + registry pre-populated with one stock + one option page (both OFF)."""
    import asyncio

    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    registry = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(registry.load_entries())
        stock_entry = loop.run_until_complete(
            registry.add_page(url="https://whop.com/stk/app/", source="stock", name="Stock1")
        )
        opt_entry = loop.run_until_complete(
            registry.add_page(url="https://whop.com/opt/app/", source="option", name="Opt1")
        )

        app = FastAPI()
        app.include_router(
            build_http_router(
                session_factory=None,  # type: ignore[arg-type]
                broker=None,  # type: ignore[arg-type]
                settings=settings_test,
                whop_registry=registry,
            )
        )
        app.dependency_overrides[get_settings] = lambda: settings_test

        client = TestClient(app, raise_server_exceptions=True)
        yield registry, client, stock_entry, opt_entry
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            loop.run_until_complete(registry.shutdown_all())
        loop.close()
        asyncio.set_event_loop(None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pages_start_off_after_add(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Newly added pages have running=False (no auto-start anymore)."""
    _, client, stock, _ = registry_and_client
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    target = next(p for p in pages if p["id"] == stock.id)
    assert target["running"] is False


def test_start_endpoint(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """POST /start flips a page from OFF to ON."""
    _, client, stock, _ = registry_and_client
    resp = client.post(f"/api/whop/pages/{stock.id}/start", params={"token": _TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == stock.id
    assert body["running"] is True


def test_stop_endpoint(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """POST /stop after /start flips ON → OFF."""
    _, client, stock, _ = registry_and_client
    client.post(f"/api/whop/pages/{stock.id}/start", params={"token": _TOKEN})
    resp = client.post(f"/api/whop/pages/{stock.id}/stop", params={"token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json()["running"] is False


def test_stop_on_already_stopped_returns_200(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """stop_page is idempotent: stopping an already-stopped page is success."""
    _, client, stock, _ = registry_and_client
    resp = client.post(f"/api/whop/pages/{stock.id}/stop", params={"token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json()["running"] is False


def test_start_unknown_page_404(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    _, client, _, _ = registry_and_client
    resp = client.post("/api/whop/pages/nope/start", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_stop_unknown_page_404(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    _, client, _, _ = registry_and_client
    resp = client.post("/api/whop/pages/nope/stop", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_start_endpoint_requires_auth(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    _, client, stock, _ = registry_and_client
    resp = client.post(f"/api/whop/pages/{stock.id}/start")
    assert resp.status_code == 403


def test_stop_endpoint_requires_auth(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    _, client, stock, _ = registry_and_client
    resp = client.post(f"/api/whop/pages/{stock.id}/stop")
    assert resp.status_code == 403
