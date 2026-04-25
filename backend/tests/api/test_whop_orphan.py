"""REST endpoint tests for /api/whop/orphan/cleanup — Task Q.5."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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

_TOKEN = "test-token-orphan"


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


@pytest.fixture
def patch_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.whop.listener.WhopBrowser", _FakeBrowser)


@pytest.fixture
def settings_test() -> Settings:
    return Settings(
        app_token=_TOKEN,
        database_url="sqlite+aiosqlite:///:memory:",
        whop_poll_interval=0.05,
        whop_headless=True,
    )


@pytest.fixture
def app_and_factory(
    patch_browser: None,
    settings_test: Settings,
    tmp_path: Path,
):
    """Build app + registry + persistent in-process engine (single loop pattern).

    Drives async setup/teardown on a single dedicated event loop so listeners
    are stopped cleanly (avoids "Task was destroyed but it is pending!" warnings).
    """
    import asyncio
    import contextlib

    from sqlalchemy import event

    bus = EventBus()
    pages_file = tmp_path / "pages.json"

    # Use a single shared in-memory engine via a file-backed URL so every
    # session sees the same data. tmp_path provides isolation between tests.
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(db_url)

    # Enable FK enforcement so cascade tests work.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _record):  # noqa: ANN001 ANN202
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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


def _make_orphan_task(id_: str, url: str | None) -> Task:
    msg = Message(
        id=id_,
        content="x",
        raw_content="x",
        author=None,
        posted_at=datetime.now(UTC),
        received_at=datetime.now(UTC),
        source="stock",
        url=url,
    )
    return Task.new_from_message(msg)


def test_cleanup_deletes_matching_tasks(app_and_factory) -> None:  # noqa: ANN001
    client, factory, _registry, loop = app_and_factory
    orphan_url = "https://whop.com/orphan/app/"

    async def _seed() -> None:
        async with factory() as session:
            for i in range(3):
                await repo.save_task(session, _make_orphan_task(f"orph-{i}", orphan_url))

    loop.run_until_complete(_seed())

    resp = client.post(
        "/api/whop/orphan/cleanup",
        json={"url": orphan_url},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 3}

    async def _verify() -> set[str]:
        async with factory() as session:
            return await repo.load_seen_ids_for_url(session, orphan_url)

    ids = loop.run_until_complete(_verify())
    assert ids == set()


def test_cleanup_unknown_url_returns_zero(app_and_factory) -> None:  # noqa: ANN001
    client, _factory, _registry, _loop = app_and_factory
    resp = client.post(
        "/api/whop/orphan/cleanup",
        json={"url": "https://whop.com/never/"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 0}


def test_cleanup_rejects_active_page_url(app_and_factory) -> None:  # noqa: ANN001
    client, _factory, registry, loop = app_and_factory
    entry = loop.run_until_complete(
        registry.add_page(
            url="https://whop.com/active/app/", source="stock", name="active"
        )
    )

    resp = client.post(
        "/api/whop/orphan/cleanup",
        json={"url": entry.url},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "active page" in resp.json()["detail"]


def test_cleanup_null_url_deletes_legacy(app_and_factory) -> None:  # noqa: ANN001
    """url=null in request body should delete legacy rows where messages.url IS NULL."""
    client, factory, _registry, loop = app_and_factory

    async def _seed() -> None:
        async with factory() as session:
            for i in range(3):
                await repo.save_task(session, _make_orphan_task(f"legacy-{i}", None))

    loop.run_until_complete(_seed())

    resp = client.post(
        "/api/whop/orphan/cleanup",
        json={"url": None},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"deleted_count": 3}
