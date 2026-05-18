"""Regression tests for chat-monitor-panel HTTP guards (T7).

Asserts that ``PATCH /api/whop/pages/{page_id}/settings`` cannot mutate a
page's ``source`` field. ``WhopPageSettingsPatch`` does not declare a
``source`` field, so pydantic's default ``extra='ignore'`` silently drops
the bogus key — the PATCH succeeds (or 400-empty if it was the only key),
but the page's ``source`` stays as it was.

If a future change adds ``source: ... = None`` to ``WhopPageSettingsPatch``
(or flips the schema to ``extra='allow'``), this test will fail loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http import build_http_router
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.whop.registry import WhopPageEntry, WhopRegistry

_TOKEN = "test-chat-messages-token"


# ---------------------------------------------------------------------------
# Fake browser (same pattern as test_whop_settings.py / test_http_whop.py)
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
    """Build app + registry pre-populated with one stock page.

    Mirrors the registry_and_client fixture used by ``test_whop_settings.py``:
    drives async setup/teardown on a single dedicated event loop so listeners
    are stopped cleanly.
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
        yield registry, client, stock_entry
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            loop.run_until_complete(registry.shutdown_all())
        loop.close()
        asyncio.set_event_loop(None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_patch_settings_rejects_source_field(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry],
) -> None:
    """An attempt to flip ``source`` via PATCH settings must not stick.

    ``WhopPageSettingsPatch`` doesn't declare ``source``, so pydantic's
    default ``extra='ignore'`` silently drops the field. Because nothing
    else was patched, the endpoint returns 400 (empty patch). Either way,
    the page's ``source`` must remain ``"stock"``.
    """
    _, client, stock = registry_and_client

    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={"source": "chat"},  # not in the patch schema → ignored or 422
        params={"token": _TOKEN},
    )
    # pydantic strict-mode would 422 on unknown fields; default ignores → endpoint
    # then sees empty patch_dict and returns 400. Either is fine — the contract
    # is just "source did not change".
    assert resp.status_code in (200, 400, 422), resp.text

    # Confirm the page's source is still "stock" via the list endpoint.
    page_resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert page_resp.status_code == 200
    pages = page_resp.json()["pages"]
    page = next(p for p in pages if p["id"] == stock.id)
    assert page["source"] == "stock"


def test_patch_settings_source_alongside_valid_field_does_not_change_source(
    registry_and_client: tuple[WhopRegistry, TestClient, WhopPageEntry],
) -> None:
    """Even when bundled with a valid field, ``source`` stays untouched.

    Sends ``{"source": "chat", "price_deviation_tolerance": 2.5}``. The valid
    field is applied; the bogus ``source`` key is dropped by pydantic's default
    extras handling. ``source`` must remain ``"stock"``.
    """
    _, client, stock = registry_and_client

    resp = client.patch(
        f"/api/whop/pages/{stock.id}/settings",
        json={"source": "chat", "price_deviation_tolerance": 2.5},
        params={"token": _TOKEN},
    )
    # If schema flips to extra='forbid', this becomes 422 — also acceptable
    # since the regression goal is just "source did not change".
    assert resp.status_code in (200, 422), resp.text

    page_resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert page_resp.status_code == 200
    pages = page_resp.json()["pages"]
    page = next(p for p in pages if p["id"] == stock.id)
    assert page["source"] == "stock"
