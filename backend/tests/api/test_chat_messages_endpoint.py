"""Regression tests for chat-monitor-panel HTTP guards (T7) + DELETE cleanup (T11).

T7 asserts that ``PATCH /api/whop/pages/{page_id}/settings`` cannot mutate a
page's ``source`` field. ``WhopPageSettingsPatch`` does not declare a
``source`` field, so pydantic's default ``extra='ignore'`` silently drops
the bogus key — the PATCH succeeds (or 400-empty if it was the only key),
but the page's ``source`` stays as it was.

T11 asserts that ``DELETE /api/whop/pages/{page_id}`` for a chat-source page
also removes all ``chat_messages`` rows for that page (no FK cascade is
possible because ``WhopPageEntry`` lives in ``data/whop_pages.json``).

If a future change adds ``source: ... = None`` to ``WhopPageSettingsPatch``
(or flips the schema to ``extra='allow'``), the T7 tests will fail loudly.
"""

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
from app.storage import repo
from app.storage.db import Base, create_engine, make_session_factory
from app.storage.schema import ChatMessageRow
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


# ---------------------------------------------------------------------------
# T11: DELETE chat page → chat_messages rows are removed
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_db(
    patch_browser: None,
    settings_test: Settings,
    tmp_path: Path,
):
    """Build app + registry + a real session_factory bound to a file-backed SQLite.

    The T7 fixture above passes ``session_factory=None`` because those tests
    don't touch the DB. T11 exercises ``repo.delete_chat_messages_by_page``
    inside the DELETE handler, so we need a live factory + ``chat_messages``
    table. Mirrors the pattern in ``test_whop_orphan.py``.
    """
    import asyncio
    import contextlib

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


def test_delete_chat_page_removes_chat_messages(app_with_db) -> None:  # noqa: ANN001
    """Deleting a chat-source page also deletes all its chat_messages rows.

    Verifies T11: ``WhopPageEntry`` lives in ``data/whop_pages.json`` so there
    is no FK cascade — the DELETE handler must call
    ``repo.delete_chat_messages_by_page`` explicitly for chat-typed pages.
    """
    client, factory, _registry, loop = app_with_db

    # Create a chat page via the API.
    resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.example/chat-page-1", "source": "chat"},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 201, resp.text
    page_id = resp.json()["id"]

    week_start = datetime(2026, 5, 11, tzinfo=UTC)
    week_end = datetime(2026, 5, 25, tzinfo=UTC)

    async def _seed() -> None:
        async with factory() as session:
            for i in range(3):
                await repo.upsert_chat_message(
                    session,
                    ChatMessageRow(
                        id=f"seed-m{i}",
                        page_id=page_id,
                        author="alice",
                        content="x",
                        raw_content="x",
                        posted_at=datetime(2026, 5, 18, 9, i, tzinfo=UTC),
                        received_at=datetime(2026, 5, 18, 9, i, tzinfo=UTC),
                        url="https://whop.example/chat-page-1",
                        quoted_message_id=None,
                        quoted_author=None,
                        quoted_content=None,
                        quoted_posted_at=None,
                    ),
                )
            await session.commit()

    async def _count() -> int:
        async with factory() as session:
            rows = await repo.list_chat_messages(
                session, page_id, week_start, week_end, None
            )
            return len(rows)

    loop.run_until_complete(_seed())
    assert loop.run_until_complete(_count()) == 3  # confirm seeded

    # Delete the page.
    resp = client.delete(f"/api/whop/pages/{page_id}", params={"token": _TOKEN})
    assert resp.status_code == 204, resp.text

    # chat_messages rows are gone.
    assert loop.run_until_complete(_count()) == 0


def test_delete_stock_page_leaves_chat_messages_untouched(app_with_db) -> None:  # noqa: ANN001
    """Deleting a stock page must NOT delete chat_messages for some other chat page.

    Belt-and-suspenders guard: ensures the source check actually scopes the
    cleanup to chat pages. Seeds chat rows for a chat page, deletes a separate
    stock page, asserts the chat rows are still there.
    """
    client, factory, _registry, loop = app_with_db

    chat_resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.example/chat-page-2", "source": "chat"},
        params={"token": _TOKEN},
    )
    assert chat_resp.status_code == 201, chat_resp.text
    chat_page_id = chat_resp.json()["id"]

    stock_resp = client.post(
        "/api/whop/pages",
        json={"url": "https://whop.com/stk-page/app/", "source": "stock"},
        params={"token": _TOKEN},
    )
    assert stock_resp.status_code == 201, stock_resp.text
    stock_page_id = stock_resp.json()["id"]

    week_start = datetime(2026, 5, 11, tzinfo=UTC)
    week_end = datetime(2026, 5, 25, tzinfo=UTC)

    async def _seed() -> None:
        async with factory() as session:
            await repo.upsert_chat_message(
                session,
                ChatMessageRow(
                    id="keep-1",
                    page_id=chat_page_id,
                    author="bob",
                    content="y",
                    raw_content="y",
                    posted_at=datetime(2026, 5, 18, 12, tzinfo=UTC),
                    received_at=datetime(2026, 5, 18, 12, tzinfo=UTC),
                    url="https://whop.example/chat-page-2",
                    quoted_message_id=None,
                    quoted_author=None,
                    quoted_content=None,
                    quoted_posted_at=None,
                ),
            )
            await session.commit()

    async def _count() -> int:
        async with factory() as session:
            rows = await repo.list_chat_messages(
                session, chat_page_id, week_start, week_end, None
            )
            return len(rows)

    loop.run_until_complete(_seed())
    assert loop.run_until_complete(_count()) == 1

    resp = client.delete(
        f"/api/whop/pages/{stock_page_id}", params={"token": _TOKEN}
    )
    assert resp.status_code == 204, resp.text

    # Chat rows for the OTHER page are still there.
    assert loop.run_until_complete(_count()) == 1
