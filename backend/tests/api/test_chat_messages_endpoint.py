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


# ---------------------------------------------------------------------------
# T14: GET /api/whop/pages/{page_id}/chat-messages
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


def test_get_chat_messages_returns_shape(app_with_db) -> None:
    """Endpoint returns messages, authors, day — all top-level keys present."""
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client)

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-23", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "messages" in body
    assert "authors" in body
    assert "day" in body
    assert "week" not in body
    assert isinstance(body["messages"], list)
    assert isinstance(body["authors"], list)
    assert "start" in body["day"]
    assert "end" in body["day"]


def test_get_chat_messages_requires_day(app_with_db) -> None:
    """``day`` is required; missing → 422."""
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client)

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"token": _TOKEN},
    )
    assert resp.status_code == 422


def test_get_chat_messages_rejects_invalid_day(app_with_db) -> None:
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client)

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "not-a-date", "token": _TOKEN},
    )
    assert resp.status_code == 400
    assert "invalid day" in resp.text


def test_get_chat_messages_filters_by_sender(app_with_db) -> None:  # noqa: ANN001
    """senders=alice returns only alice's messages."""
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/chat-t14-filter")

    async def _seed() -> None:
        async with factory() as s:
            for i, author in enumerate(["alice", "bob", "alice"]):
                await repo.upsert_chat_message(
                    s,
                    ChatMessageRow(
                        id=f"m{i}",
                        page_id=page_id,
                        author=author,
                        content="x",
                        raw_content="x",
                        posted_at=datetime(2026, 5, 20, 9, i, tzinfo=UTC),
                        received_at=datetime(2026, 5, 20, 9, i, tzinfo=UTC),
                        url="https://whop.example/chat-t14-filter",
                        quoted_message_id=None,
                        quoted_author=None,
                        quoted_content=None,
                        quoted_posted_at=None,
                    ),
                )
            await s.commit()

    loop.run_until_complete(_seed())

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-20", "senders": "alice", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert all(m["author"] == "alice" for m in body["messages"])
    assert len(body["messages"]) == 2


def test_get_chat_messages_posted_at_carries_utc_offset(app_with_db) -> None:  # noqa: ANN001
    """``posted_at`` (and ``quoted.posted_at``) must serialize with a UTC
    offset suffix even though SQLite drops ``tzinfo`` on roundtrip.

    Without the offset, the frontend's ``new Date(iso)`` parses the value
    as the browser's local timezone — a Beijing browser then mis-bins UTC
    23:18 as local 23:18, shifting the day boundary by 8 hours.
    """
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/chat-t14-tz")

    async def _seed() -> None:
        async with factory() as s:
            await repo.upsert_chat_message(
                s,
                ChatMessageRow(
                    id="m-tz",
                    page_id=page_id,
                    author="alice",
                    content="x",
                    raw_content="x",
                    posted_at=datetime(2026, 5, 20, 23, 18, tzinfo=UTC),
                    received_at=datetime(2026, 5, 22, 12, 30, tzinfo=UTC),
                    url="https://whop.example/chat-t14-tz",
                    quoted_message_id="parent-id",
                    quoted_author="bob",
                    quoted_content="parent",
                    quoted_posted_at=datetime(2026, 5, 20, 22, 0, tzinfo=UTC),
                ),
            )
            await s.commit()

    loop.run_until_complete(_seed())

    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-21", "token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    msg = next(m for m in body["messages"] if m["id"] == "m-tz")
    # Must end with Z or ±HH:MM offset — never bare "YYYY-MM-DDTHH:MM:SS".
    assert msg["posted_at"].endswith(("Z", "+00:00")), msg["posted_at"]
    assert msg["quoted"]["posted_at"].endswith(("Z", "+00:00")), msg["quoted"]["posted_at"]


def test_get_chat_messages_unknown_page_404(app_with_db) -> None:  # noqa: ANN001
    """Unknown page_id returns 404."""
    client, _factory, _registry, _loop = app_with_db
    resp = client.get(
        "/api/whop/pages/no-such-page/chat-messages",
        params={"day": "2026-05-23", "token": _TOKEN},
    )
    assert resp.status_code == 404, resp.text


def test_get_chat_messages_beijing_day_boundary(app_with_db) -> None:  # noqa: ANN001
    """A message at UTC 16:30 on day D belongs to Beijing day D+1, not D."""
    client, factory, _registry, loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/chat-bj-edge")

    # UTC 2026-05-23 16:30 == Beijing 2026-05-24 00:30
    async def _seed() -> None:
        async with factory() as s:
            await repo.upsert_chat_message(
                s,
                ChatMessageRow(
                    id="m-edge",
                    page_id=page_id,
                    author="alice",
                    content="x",
                    raw_content="x",
                    posted_at=datetime(2026, 5, 23, 16, 30, tzinfo=UTC),
                    received_at=datetime(2026, 5, 23, 16, 30, tzinfo=UTC),
                    url="https://whop.example/chat-bj-edge",
                    quoted_message_id=None,
                    quoted_author=None,
                    quoted_content=None,
                    quoted_posted_at=None,
                ),
            )
            await s.commit()

    loop.run_until_complete(_seed())

    # day=2026-05-23 (Beijing) -> message NOT in window
    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-23", "token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["messages"] == []

    # day=2026-05-24 (Beijing) -> message IS in window
    resp = client.get(
        f"/api/whop/pages/{page_id}/chat-messages",
        params={"day": "2026-05-24", "token": _TOKEN},
    )
    assert resp.status_code == 200
    assert [m["id"] for m in resp.json()["messages"]] == ["m-edge"]


# ---------------------------------------------------------------------------
# PATCH settings round-trip for watched_senders / chat_card_max_msgs
# ---------------------------------------------------------------------------


def test_patch_settings_persists_watched_senders(app_with_db) -> None:  # noqa: ANN001
    """PATCH watched_senders survives GET /api/whop/pages."""
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/chat-watched-senders")

    resp = client.patch(
        f"/api/whop/pages/{page_id}/settings",
        json={"watched_senders": ["alice", "bob"]},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text

    pages = client.get("/api/whop/pages", params={"token": _TOKEN}).json()["pages"]
    page = next(p for p in pages if p["id"] == page_id)
    assert page["settings"]["watched_senders"] == ["alice", "bob"]


def test_patch_settings_persists_chat_card_max_msgs(app_with_db) -> None:  # noqa: ANN001
    """PATCH chat_card_max_msgs survives GET /api/whop/pages."""
    client, _factory, _registry, _loop = app_with_db
    page_id = _make_chat_page(client, url="https://whop.example/chat-card-max-msgs")

    resp = client.patch(
        f"/api/whop/pages/{page_id}/settings",
        json={"chat_card_max_msgs": 8},
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text

    pages = client.get("/api/whop/pages", params={"token": _TOKEN}).json()["pages"]
    page = next(p for p in pages if p["id"] == page_id)
    assert page["settings"]["chat_card_max_msgs"] == 8
