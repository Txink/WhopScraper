"""GET /api/whop/pages/{page_id}/chat-message-counts — Beijing-day counts."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http import build_http_router
from app.broker.noop_client import NoopBrokerClient
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.storage import repo
from app.storage.db import Base, create_engine, make_session_factory
from app.storage.schema import ChatMessageRow
from app.whop.registry import WhopRegistry

_TOKEN = "test-chat-messages-token"

# Fixtures mirror tests/api/test_chat_messages_endpoint.py (see test_chat_images.py for the same pattern).


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
def app_with_db(
    patch_browser: None,
    settings_test: Settings,
    tmp_path: Path,
):
    """Build app + registry + a real session_factory bound to a file-backed SQLite."""
    bus = EventBus()
    pages_file = tmp_path / "pages.json"

    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(db_url)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:

        async def _create_schema() -> None:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        loop.run_until_complete(_create_schema())
        factory = make_session_factory(engine)

        registry = WhopRegistry(
            bus=bus,
            settings=settings_test,
            session_factory=factory,
            pages_file=pages_file,
        )
        loop.run_until_complete(registry.load_entries())

        app = FastAPI()
        app.include_router(
            build_http_router(
                session_factory=factory,
                broker=NoopBrokerClient(),
                settings=settings_test,
                bus=bus,
                whop_registry=registry,
            )
        )
        app.dependency_overrides[get_settings] = lambda: settings_test

        client = TestClient(app, raise_server_exceptions=True)
        yield client, factory, registry, loop
    finally:
        with contextlib.suppress(Exception):
            loop.run_until_complete(registry.shutdown_all())
        with contextlib.suppress(Exception):
            loop.run_until_complete(engine.dispose())
        loop.close()
        asyncio.set_event_loop(None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_page(client: TestClient, url: str = "https://whop.example/chat-t14") -> str:
    """Create a chat-source page via the API and return its id."""
    resp = client.post(
        "/api/whop/pages",
        json={"url": url, "source": "chat"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _seed(loop, factory, page_id: str, msgs: list[tuple[str, datetime]]) -> None:
    async def _do() -> None:
        async with factory() as s:
            for mid, ts in msgs:
                await repo.upsert_chat_message(
                    s,
                    ChatMessageRow(
                        id=mid,
                        page_id=page_id,
                        author="alice",
                        content="x",
                        raw_content="x",
                        posted_at=ts,
                        received_at=ts,
                        url="https://whop.example/counts",
                        quoted_message_id=None,
                        quoted_author=None,
                        quoted_content=None,
                        quoted_posted_at=None,
                    ),
                )
            await s.commit()

    loop.run_until_complete(_do())


def test_chat_message_counts_returns_shape(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-shape")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"month": "2026-05", "counts": {}}


def test_chat_message_counts_omits_zero_days(app_with_db) -> None:  # noqa: ANN001
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-zero")

    # 5-19 一条；5-20 两条；5-21 没消息
    _seed(loop, factory, page_id, [
        ("a", datetime(2026, 5, 19, 3, 0, tzinfo=UTC)),
        ("b", datetime(2026, 5, 20, 1, 0, tzinfo=UTC)),
        ("c", datetime(2026, 5, 20, 15, 0, tzinfo=UTC)),
    ])

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "month": "2026-05",
        "counts": {"2026-05-19": 1, "2026-05-20": 2},
    }


def test_chat_message_counts_month_boundary(app_with_db) -> None:  # noqa: ANN001
    """A message at UTC 2026-04-30 15:00 == Beijing 2026-04-30 23:00; should
    appear under month=2026-04 only, not 2026-05."""
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-bound")

    _seed(loop, factory, page_id, [
        ("apr-end", datetime(2026, 4, 30, 15, 0, tzinfo=UTC)),   # 北京 4-30 23:00
        ("may-start", datetime(2026, 5, 1, 1, 0, tzinfo=UTC)),   # 北京 5-1 09:00
    ])

    resp_apr = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-04", "token": _TOKEN},
    )
    assert resp_apr.json()["counts"] == {"2026-04-30": 1}

    resp_may = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp_may.json()["counts"] == {"2026-05-01": 1}


def test_chat_message_counts_requires_month(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-req")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"token": _TOKEN},
    )
    assert resp.status_code == 422


def test_chat_message_counts_rejects_invalid_month(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/counts-bad")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-message-counts",
        params={"month": "abc", "token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "invalid month" in resp.text


def test_chat_message_counts_unknown_page_404(app_with_db) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_with_db
    resp = client.get(
        "/api/whop/pages/no-such-page/chat-message-counts",
        params={"month": "2026-05", "token": _TOKEN},
    )
    assert resp.status_code == 404
