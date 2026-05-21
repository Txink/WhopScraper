"""Tests for ``image_url`` on ``ChatMessageOut`` + ``/api/chat-images/{id}`` route.

Uses the same ``app_with_db`` fixture pattern as ``test_chat_messages_endpoint.py``:
a real file-backed SQLite, real registry, and a TestClient. Seeds chat_messages
rows directly via the session factory, then exercises the HTTP surface.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

_TOKEN = "test-chat-images-token"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings_test(tmp_path: Path) -> Settings:
    return Settings(
        app_token=_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        whop_poll_interval=0.05,
        whop_headless=True,
        data_dir=tmp_path,
    )


@pytest.fixture
def app_with_db(
    settings_test: Settings, tmp_path: Path
) -> Iterator[tuple[TestClient, Any, asyncio.AbstractEventLoop]]:
    """Build app + a real session_factory bound to a file-backed SQLite.

    Mirrors the ``app_with_db`` fixture in test_chat_messages_endpoint.py.
    """
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
        yield client, factory, loop
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


def _seed_row(
    factory: Any,
    loop: asyncio.AbstractEventLoop,
    msg_id: str,
    *,
    page_id: str,
    content: str = "",
    image_filename: str | None = None,
) -> None:
    async def _do() -> None:
        async with factory() as session:
            await repo.upsert_chat_message(
                session,
                ChatMessageRow(
                    id=msg_id,
                    page_id=page_id,
                    author="alice",
                    content=content,
                    raw_content=content,
                    posted_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
                    received_at=datetime(2026, 5, 21, 12, 0, tzinfo=UTC),
                    url=None,
                    quoted_message_id=None,
                    quoted_author=None,
                    quoted_content=None,
                    quoted_posted_at=None,
                    image_filename=image_filename,
                ),
            )
            await session.commit()

    loop.run_until_complete(_do())


def _make_chat_page(client: TestClient) -> str:
    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.example/chat-img-page", "source": "chat"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# image_url on ChatMessageOut
# ---------------------------------------------------------------------------


def test_chat_message_out_includes_image_url(app_with_db) -> None:  # noqa: ANN001
    """When a row has ``image_filename``, the API response carries
    ``image_url`` pointing at the new chat-images endpoint."""
    client, factory, loop = app_with_db
    page_id = _make_chat_page(client)
    _seed_row(factory, loop, "m_api_1", page_id=page_id, image_filename="m_api_1.png")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"token": _TOKEN, "week": "2026-W21"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    msg = next(m for m in body["messages"] if m["id"] == "m_api_1")
    assert msg["image_url"] == "/api/chat-images/m_api_1"


def test_chat_message_out_image_url_null_when_no_image(app_with_db) -> None:  # noqa: ANN001
    """Rows without ``image_filename`` carry ``image_url=null``."""
    client, factory, loop = app_with_db
    page_id = _make_chat_page(client)
    _seed_row(factory, loop, "m_api_2", page_id=page_id, content="just text")

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"token": _TOKEN, "week": "2026-W21"},
    )
    assert resp.status_code == 200, resp.text
    msg = next(m for m in resp.json()["messages"] if m["id"] == "m_api_2")
    assert msg.get("image_url") is None


# ---------------------------------------------------------------------------
# /api/chat-images/{message_id}
# ---------------------------------------------------------------------------


def test_get_chat_image_returns_file(
    app_with_db, settings_test: Settings
) -> None:  # noqa: ANN001
    """The endpoint serves the cached image bytes with the correct media type."""
    client, factory, loop = app_with_db
    page_id = _make_chat_page(client)
    _seed_row(
        factory, loop, "m_route_1", page_id=page_id, image_filename="m_route_1.png"
    )

    # Drop the cached bytes where the route expects them — same data_dir as
    # the test's Settings instance, written by chat_writer in production.
    (settings_test.data_dir / "chat-images").mkdir(exist_ok=True)
    (settings_test.data_dir / "chat-images" / "m_route_1.png").write_bytes(b"PNGBYTES")

    resp = client.get("/api/chat-images/m_route_1", params={"token": _TOKEN})
    assert resp.status_code == 200, resp.text
    assert resp.content == b"PNGBYTES"
    assert resp.headers["content-type"].startswith("image/png")


def test_get_chat_image_404_when_no_image_filename(app_with_db) -> None:  # noqa: ANN001
    """Row exists but ``image_filename`` is None → 404."""
    client, factory, loop = app_with_db
    page_id = _make_chat_page(client)
    _seed_row(factory, loop, "m_route_2", page_id=page_id, content="text only")

    resp = client.get("/api/chat-images/m_route_2", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_get_chat_image_404_when_message_not_found(app_with_db) -> None:  # noqa: ANN001
    """Unknown message id → 404."""
    client, _factory, _loop = app_with_db

    resp = client.get("/api/chat-images/does_not_exist", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_get_chat_image_404_when_file_missing_on_disk(
    app_with_db, settings_test: Settings
) -> None:  # noqa: ANN001
    """Row has ``image_filename`` but the file isn't on disk → 404.

    Guards against a desync where the DB knows about a file the cache no
    longer has (e.g., operator cleaned ``data/chat-images/``)."""
    client, factory, loop = app_with_db
    page_id = _make_chat_page(client)
    _seed_row(
        factory, loop, "m_route_3", page_id=page_id, image_filename="m_route_3.avif"
    )
    # Note: do NOT create the file under settings_test.data_dir / chat-images.

    resp = client.get("/api/chat-images/m_route_3", params={"token": _TOKEN})
    assert resp.status_code == 404
