"""Tests for parent_chat_id round-trip through REST."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http import build_http_router
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.whop.registry import WhopRegistry

_TOKEN = "test-parent-token"


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
def client(
    patch_browser: None,
    settings_test: Settings,
    tmp_path: Path,
) -> TestClient:
    """Return a TestClient backed by a fresh WhopRegistry."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"
    registry = WhopRegistry(bus=bus, settings=settings_test, pages_file=pages_file)

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

    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_with_parent_chat_id(client: TestClient) -> None:
    """POST with parent_chat_id round-trips the field in the response."""
    parent = client.post(
        "/api/whop/pages",
        json={
            "url": "https://whop.com/c/chat-test-1",
            "source": "chat",
            "name": "alpha-room",
        },
        params={"token": _TOKEN},
    ).json()

    child = client.post(
        "/api/whop/pages",
        json={
            "url": "https://whop.com/c/stock-test-a",
            "source": "stock",
            "name": "TSLL 监听",
            "parent_chat_id": parent["id"],
        },
        params={"token": _TOKEN},
    ).json()

    assert child["parent_chat_id"] == parent["id"]


def test_list_default_excludes_sub_monitors(client: TestClient) -> None:
    """Default GET /api/whop/pages returns only top-level entries."""
    parent = client.post(
        "/api/whop/pages",
        json={
            "url": "https://whop.com/c/chat-test-2",
            "source": "chat",
            "name": "c",
        },
        params={"token": _TOKEN},
    ).json()

    client.post(
        "/api/whop/pages",
        json={
            "url": "https://whop.com/c/stock-test-b",
            "source": "stock",
            "name": "A",
            "parent_chat_id": parent["id"],
        },
        params={"token": _TOKEN},
    )

    r = client.get("/api/whop/pages", params={"token": _TOKEN})
    assert r.status_code == 200
    pages = r.json()["pages"]
    ids = {p["id"] for p in pages}
    assert parent["id"] in ids
    # All returned entries are top-level
    assert all(p["parent_chat_id"] is None for p in pages)


def test_list_filter_by_parent(client: TestClient) -> None:
    """GET /api/whop/pages?parent_chat_id=<id> returns only children."""
    parent = client.post(
        "/api/whop/pages",
        json={
            "url": "https://whop.com/c/chat-test-3",
            "source": "chat",
            "name": "c",
        },
        params={"token": _TOKEN},
    ).json()

    child_resp = client.post(
        "/api/whop/pages",
        json={
            "url": "https://whop.com/c/stock-test-c",
            "source": "stock",
            "name": "A",
            "parent_chat_id": parent["id"],
        },
        params={"token": _TOKEN},
    )
    assert child_resp.status_code == 201
    child = child_resp.json()

    r = client.get(
        "/api/whop/pages",
        params={"token": _TOKEN, "parent_chat_id": parent["id"]},
    )
    assert r.status_code == 200
    pages = r.json()["pages"]
    assert len(pages) == 1
    assert pages[0]["id"] == child["id"]


def test_create_rejects_invalid_parent(client: TestClient) -> None:
    """POST with a nonexistent parent_chat_id returns 400."""
    r = client.post(
        "/api/whop/pages",
        json={
            "url": "https://whop.com/c/stock-test-d",
            "source": "stock",
            "name": "A",
            "parent_chat_id": "nonexistent",
        },
        params={"token": _TOKEN},
    )
    assert r.status_code == 400
    assert "not found" in r.json()["detail"].lower()
