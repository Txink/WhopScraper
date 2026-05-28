"""Tests for GET /api/messages/{id}/image (stock/option image serve)."""

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
from app.domain.message import Message
from app.domain.task import Task
from app.storage import repo
from app.storage.db import Base, create_engine, make_session_factory
from app.whop.registry import WhopRegistry

_TOKEN = "test-messages-image-token"
_NOW = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)


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
            bus=bus, settings=settings_test, session_factory=factory,
            pages_file=pages_file,
        )
        loop.run_until_complete(registry.load_entries())
        app = FastAPI()
        app.include_router(
            build_http_router(
                session_factory=factory, broker=NoopBrokerClient(),
                settings=settings_test, bus=bus, whop_registry=registry,
            )
        )
        app.dependency_overrides[get_settings] = lambda: settings_test
        yield TestClient(app, raise_server_exceptions=True), factory, loop
    finally:
        with contextlib.suppress(Exception):
            loop.run_until_complete(registry.shutdown_all())
        with contextlib.suppress(Exception):
            loop.run_until_complete(engine.dispose())
        loop.close()
        asyncio.set_event_loop(None)


def _seed_message(
    factory: Any, loop: asyncio.AbstractEventLoop,
    msg_id: str, image_filename: str | None,
) -> None:
    async def _do() -> None:
        msg = Message(
            id=msg_id, content="", raw_content="", author="t",
            posted_at=_NOW, received_at=_NOW, source="stock",
            image_filename=image_filename,
        )
        task = Task.new_from_message(msg)
        task.mark_parsing()
        task.mark_skipped("图片消息")
        async with factory() as session:
            await repo.save_task(session, task)
    loop.run_until_complete(_do())


def test_serves_image_bytes(app_with_db, settings_test: Settings) -> None:  # noqa: ANN001
    client, factory, loop = app_with_db
    _seed_message(factory, loop, "mi_1", "mi_1.png")
    (settings_test.data_dir / "chat-images").mkdir(exist_ok=True)
    (settings_test.data_dir / "chat-images" / "mi_1.png").write_bytes(b"PNGBYTES")

    resp = client.get("/api/messages/mi_1/image", params={"token": _TOKEN})
    assert resp.status_code == 200, resp.text
    assert resp.content == b"PNGBYTES"
    assert resp.headers["content-type"].startswith("image/png")


def test_404_when_no_filename(app_with_db) -> None:  # noqa: ANN001
    client, factory, loop = app_with_db
    _seed_message(factory, loop, "mi_2", None)
    resp = client.get("/api/messages/mi_2/image", params={"token": _TOKEN})
    assert resp.status_code == 404


def test_404_when_file_missing(app_with_db) -> None:  # noqa: ANN001
    client, factory, loop = app_with_db
    _seed_message(factory, loop, "mi_3", "ghost.png")
    resp = client.get("/api/messages/mi_3/image", params={"token": _TOKEN})
    assert resp.status_code == 404
