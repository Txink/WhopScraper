"""REST endpoint tests for /api/whop/* paths."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http import build_http_router
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.whop.registry import WhopRegistry

_TOKEN = "test-whop-token"


# ---------------------------------------------------------------------------
# Fake browser (same pattern as test_listener.py)
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
) -> tuple[WhopRegistry, TestClient]:
    """Return a (WhopRegistry, TestClient) pair backed by the real registry."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    registry = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)

    # Build app without lifespan so we control registry startup manually
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

    return registry, TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_list_pages_empty(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """GET /api/whop/pages with no pages returns {pages: []}."""
    _, client = registry_and_client
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"pages": []}


def test_create_page_success(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """POST /api/whop/pages with valid body returns 201 and page object."""
    _, client = registry_and_client
    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.com/joined/abc/app/", "source": "stock", "name": "Test"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["url"] == "https://whop.com/joined/abc/app/"
    assert data["source"] == "stock"
    assert data["name"] == "Test"
    assert "id" in data
    assert "added_at" in data
    assert isinstance(data["running"], bool)
    assert isinstance(data["messages_published"], int)


def test_create_page_default_name(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """POST without name uses URL as name."""
    _, client = registry_and_client
    url = "https://whop.com/joined/abc/app/"
    resp = client.post(
        "/api/whop/pages",
        json={"url": url, "source": "option"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == url


def test_create_page_duplicate_url_returns_400(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """POST with duplicate URL returns 400."""
    _, client = registry_and_client
    payload = {"url": "https://whop.com/joined/abc/app/", "source": "stock"}
    resp1 = client.post("/api/whop/pages", json=payload, params={"token": _TOKEN})
    assert resp1.status_code == 201

    resp2 = client.post("/api/whop/pages", json=payload, params={"token": _TOKEN})
    assert resp2.status_code == 400
    assert "already monitored" in resp2.json()["detail"]


def test_create_page_placeholder_url_returns_400(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """POST with placeholder URL returns 400."""
    _, client = registry_and_client
    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.com/joined/xxx/app/", "source": "stock"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "placeholder" in resp.json()["detail"]


def test_create_page_invalid_source_returns_422(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """POST with invalid source value returns 422 (Pydantic validation)."""
    _, client = registry_and_client
    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.com/joined/abc/app/", "source": "invalid"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 422


def test_delete_page_success(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """DELETE /api/whop/pages/{id} returns 204; subsequent GET shows it gone."""
    _, client = registry_and_client

    # Create first
    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.com/joined/abc/app/", "source": "stock"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201
    page_id = resp.json()["id"]

    # Delete
    resp = client.delete(f"/api/whop/pages/{page_id}", params={"token": _TOKEN})
    assert resp.status_code == 204

    # Verify gone
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json()["pages"] == []


def test_delete_page_unknown_returns_404(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """DELETE unknown page id returns 404."""
    _, client = registry_and_client
    resp = client.delete("/api/whop/pages/no-such-id", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_list_pages_after_create(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """GET /api/whop/pages returns created page."""
    _, client = registry_and_client

    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.com/joined/abc/app/", "source": "stock", "name": "My Page"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201
    created_id = resp.json()["id"]

    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["pages"]) == 1
    assert data["pages"][0]["id"] == created_id
    assert data["pages"][0]["name"] == "My Page"


def test_restart_page_unknown_returns_404(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """POST /api/whop/pages/{id}/restart with unknown id returns 404."""
    _, client = registry_and_client
    resp = client.post("/api/whop/pages/no-such-id/restart", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_restart_page_success(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """POST /api/whop/pages/{id}/restart returns 200 with updated page status."""
    _, client = registry_and_client

    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.com/joined/abc/app/", "source": "stock"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201
    page_id = resp.json()["id"]

    resp = client.post(f"/api/whop/pages/{page_id}/restart", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == page_id
    assert "running" in data


def test_cookie_status_missing(
    registry_and_client: tuple[WhopRegistry, TestClient],
    tmp_path: Path,
) -> None:
    """GET /api/whop/cookie returns exists=false when cookie file absent."""
    _, client = registry_and_client

    # cookie_path is imported lazily inside the endpoint from app.whop.login
    fake_cookie = tmp_path / ".auth" / "whop_cookie.json"

    import app.whop.login as login_mod
    original = login_mod.cookie_path

    def _fake_cookie_path(*args, **kwargs):  # noqa: ANN002 ANN003 ANN202
        return fake_cookie

    login_mod.cookie_path = _fake_cookie_path
    try:
        resp = client.get("/api/whop/cookie", params={"token": _TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is False
        assert "path" in data
        assert data["last_modified"] is None
        assert data["age_seconds"] is None
    finally:
        login_mod.cookie_path = original


def test_cookie_status_present(
    registry_and_client: tuple[WhopRegistry, TestClient],
    tmp_path: Path,
) -> None:
    """GET /api/whop/cookie returns exists=true with age when file present."""
    _, client = registry_and_client

    fake_cookie = tmp_path / ".auth" / "whop_cookie.json"
    fake_cookie.parent.mkdir(parents=True, exist_ok=True)
    fake_cookie.write_text(json.dumps({"cookies": []}))

    import app.whop.login as login_mod
    original = login_mod.cookie_path

    def _fake_cookie_path(*args, **kwargs):  # noqa: ANN002 ANN003 ANN202
        return fake_cookie

    login_mod.cookie_path = _fake_cookie_path
    try:
        resp = client.get("/api/whop/cookie", params={"token": _TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert data["exists"] is True
        assert data["last_modified"] is not None
        assert data["age_seconds"] is not None
        assert data["age_seconds"] >= 0
    finally:
        login_mod.cookie_path = original


def test_missing_token_returns_403(
    registry_and_client: tuple[WhopRegistry, TestClient],
) -> None:
    """Whop endpoints also require auth token."""
    _, client = registry_and_client
    resp = client.get("/api/whop/pages")
    assert resp.status_code == 403


def test_whop_endpoints_absent_when_no_registry(
    settings_test: Settings,
) -> None:
    """When build_http_router has no whop_registry, whop endpoints are not registered."""
    # We need a minimal session factory for the non-whop router
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.storage.db import Base, create_engine
    from tests.broker._fakes import FakeBrokerClient

    async def _build() -> async_sessionmaker[AsyncSession]:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return async_sessionmaker(engine, expire_on_commit=False)

    sf = asyncio.get_event_loop().run_until_complete(_build())

    broker = FakeBrokerClient()
    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=sf,
            broker=broker,
            settings=settings_test,
            # no whop_registry
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings_test

    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert resp.status_code == 404
