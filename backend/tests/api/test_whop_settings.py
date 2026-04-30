"""REST endpoint tests for /api/whop/pages/.../settings + /defaults (Task H)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http import build_http_router
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.whop.registry import WhopPageEntry, WhopRegistry

_TOKEN = "test-whop-settings-token"


# ---------------------------------------------------------------------------
# Fake browser (same pattern as test_http_whop.py)
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
    """Build app + registry pre-populated with one stock + one option page.

    Uses the same pattern as test_http_whop.py: pass None for session_factory
    and broker since /api/whop/* endpoints don't touch them. Drives async
    setup/teardown on a single dedicated event loop so listeners are stopped
    cleanly (avoids "Task was destroyed but it is pending!" warnings).
    """
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
                bus=bus,
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
# Tests — GET /api/whop/pages now includes typed `settings`
# ---------------------------------------------------------------------------


def test_get_pages_includes_settings(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """List pages: each entry has a `settings` object with the typed shape."""
    _, client, stock, _ = registry_and_client
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    s = next(p["settings"] for p in pages if p["id"] == stock.id)
    assert s["dedupe_processed_messages"] is True
    assert s["price_deviation_tolerance"] == 1.0
    assert s["block_historical_messages"] is False
    assert s["launch_headless"] is False
    assert s["tickers"] == {}


def test_get_pages_option_settings_tickers_none(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Option page emits tickers=None."""
    _, client, _, opt = registry_and_client
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    s = next(p["settings"] for p in pages if p["id"] == opt.id)
    assert s["tickers"] is None
    assert s["price_deviation_tolerance"] == 5.0


# ---------------------------------------------------------------------------
# Tests — PATCH /api/whop/pages/{id}/settings
# ---------------------------------------------------------------------------


def test_patch_settings_partial(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """PATCH with subset of fields preserves omitted fields."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={
            "price_deviation_tolerance": 0.5,
            "tickers": {"NVDA": {"trade_quantity": 100}},
        },
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200
    out = resp.json()
    assert out["settings"]["price_deviation_tolerance"] == 0.5
    assert out["settings"]["tickers"] == {"NVDA": {"trade_quantity": 100}}
    # dedupe was not in patch — preserved
    assert out["settings"]["dedupe_processed_messages"] is True


def test_patch_settings_uppercases_ticker_keys(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Lowercase ticker keys get normalized to uppercase by from_dict tolerance."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={"tickers": {"tsll": {"trade_quantity": 100}}},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["tickers"] == {"TSLL": {"trade_quantity": 100}}


def test_patch_settings_option_rejects_tickers(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Option pages must not accept a `tickers` patch."""
    _, client, _, opt = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{opt.id}/settings",
        json={"tickers": {"AAPL": {"trade_quantity": 1}}},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "tickers" in resp.json()["detail"]


def test_patch_settings_unknown_id_returns_404(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """PATCH unknown page id returns 404."""
    _, client, _, _ = registry_and_client
    resp = client.patch(
        "/api/whop/pages/nope/settings",
        json={"price_deviation_tolerance": 1.0},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 404


def test_patch_settings_dedupe_only(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Single-field patch flips only that field."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={"dedupe_processed_messages": False},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200
    s = resp.json()["settings"]
    assert s["dedupe_processed_messages"] is False
    # Untouched
    assert s["price_deviation_tolerance"] == 1.0
    assert s["tickers"] == {}


def test_patch_settings_negative_tolerance_returns_422(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Pydantic ge=0 rejects negative tolerance."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={"price_deviation_tolerance": -0.1},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 422


def test_patch_settings_empty_body_returns_400(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Empty PATCH body returns 400 — avoids spurious WS event + no-op write."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Tests — GET /api/whop/pages/defaults
# ---------------------------------------------------------------------------


def test_get_settings_defaults_stock(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """defaults?source=stock returns the stock template."""
    _, client, _, _ = registry_and_client
    resp = client.get("/api/whop/pages/defaults", params={"source": "stock", "token": _TOKEN})
    assert resp.status_code == 200
    s = resp.json()
    assert s["dedupe_processed_messages"] is True
    assert s["price_deviation_tolerance"] == 1.0
    assert s["block_historical_messages"] is False
    assert s["tickers"] == {}
    assert s["option_buy_quantity_enabled"] is False
    assert s["option_buy_quantity"] is None
    assert s["option_total_price_limit_enabled"] is False
    assert s["option_total_price_limit"] is None


def test_get_settings_defaults_option(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """defaults?source=option returns the option template (tickers None)."""
    _, client, _, _ = registry_and_client
    resp = client.get("/api/whop/pages/defaults", params={"source": "option", "token": _TOKEN})
    assert resp.status_code == 200
    s = resp.json()
    assert s["dedupe_processed_messages"] is True
    assert s["price_deviation_tolerance"] == 5.0
    assert s["block_historical_messages"] is False
    assert s["launch_headless"] is False
    assert s["tickers"] is None
    assert s["option_buy_quantity_enabled"] is False
    assert s["option_buy_quantity"] is None
    assert s["option_total_price_limit_enabled"] is False
    assert s["option_total_price_limit"] is None


def test_patch_settings_option_rules(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Option page patch accepts local option quantity/total rules."""
    _, client, _, opt = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{opt.id}/settings",
        json={
            "option_buy_quantity_enabled": True,
            "option_buy_quantity": 4,
            "option_total_price_limit_enabled": True,
            "option_total_price_limit": 1200.0,
        },
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200
    s = resp.json()["settings"]
    assert s["option_buy_quantity_enabled"] is True
    assert s["option_buy_quantity"] == 4
    assert s["option_total_price_limit_enabled"] is True
    assert s["option_total_price_limit"] == 1200.0


def test_get_settings_defaults_invalid_source(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Unknown source returns 400."""
    _, client, _, _ = registry_and_client
    resp = client.get("/api/whop/pages/defaults", params={"source": "weird", "token": _TOKEN})
    assert resp.status_code == 400


def test_get_settings_defaults_requires_auth(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """defaults endpoint also gated by token."""
    _, client, _, _ = registry_and_client
    resp = client.get("/api/whop/pages/defaults", params={"source": "stock"})
    assert resp.status_code == 403


def test_patch_then_get_block_historical_messages(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """PATCH the new block_historical_messages field; GET reflects it."""
    _, client, stock, _ = registry_and_client

    # PATCH to enable block_historical_messages
    r = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={"block_historical_messages": True},
        params={"token": _TOKEN},
    )
    assert r.status_code == 200
    assert r.json()["settings"]["block_historical_messages"] is True

    # GET the full page list and confirm the field persisted
    g = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert g.status_code == 200
    pages = g.json()["pages"]
    s = next(p["settings"] for p in pages if p["id"] == stock.id)
    assert s["block_historical_messages"] is True


# ---------------------------------------------------------------------------
# Tests — parser_version per-page toggle
# ---------------------------------------------------------------------------


def test_get_pages_includes_parser_version_default_v1(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """A freshly-added stock page reports parser_version='v1'."""
    _, client, stock, _ = registry_and_client
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    pages = resp.json()["pages"]
    s = next(p["settings"] for p in pages if p["id"] == stock.id)
    assert s["parser_version"] == "v1"


def test_defaults_endpoint_includes_parser_version_v1(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """GET /api/whop/pages/defaults?source=stock includes parser_version='v1'."""
    _, client, _, _ = registry_and_client
    resp = client.get(
        "/api/whop/pages/defaults",
        params={"token": _TOKEN, "source": "stock"},
    )
    assert resp.status_code == 200
    assert resp.json()["parser_version"] == "v1"


def test_patch_parser_version_v2_persists(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """PATCH parser_version='v2' is reflected in the response and on the next GET."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v2"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"]["parser_version"] == "v2"

    # Re-read via list endpoint to confirm registry was updated
    resp2 = client.get("/api/whop/pages", params={"token": _TOKEN})
    s = next(p["settings"] for p in resp2.json()["pages"] if p["id"] == stock.id)
    assert s["parser_version"] == "v2"


def test_patch_parser_version_v1_reverts(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """PATCH v2 then v1 reverts cleanly."""
    _, client, stock, _ = registry_and_client
    first = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v2"},
    )
    assert first.status_code == 200
    assert first.json()["settings"]["parser_version"] == "v2"

    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v1"},
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["parser_version"] == "v1"


def test_patch_parser_version_invalid_value_rejected(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry, WhopPageEntry],
) -> None:
    """Pydantic Literal validation rejects non-{v1,v2} values at the boundary."""
    _, client, stock, _ = registry_and_client
    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        params={"token": _TOKEN},
        json={"parser_version": "v3"},
    )
    assert resp.status_code == 422
