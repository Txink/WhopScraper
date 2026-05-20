"""Tests for /api/tasks ?urls=&week_start=&week_end= filters (Task 7)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.http import build_http_router
from app.broker.runtime_settings import LongPortRuntimeStore
from app.core.config import Settings, get_settings
from app.core.event_bus import EventBus
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.storage import repo
from tests.broker._fakes import FakeBrokerClient

_TOKEN = "test-token-tasks-filter"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(year: int, month: int, day: int, hour: int = 9) -> datetime:
    """Return a timezone-aware UTC datetime."""
    return datetime(year, month, day, hour, 0, 0, tzinfo=UTC)


def _msg(id_: str, *, url: str, ts: datetime) -> Message:
    return Message(
        id=id_,
        content="TSLL 26.5 buy",
        raw_content="TSLL 26.5 buy",
        author="trader",
        source="stock",  # type: ignore[arg-type]
        url=url,
        posted_at=ts,
        received_at=ts,
    )


def _task(id_: str, *, url: str, ts: datetime) -> Task:
    return Task(
        id=id_,
        type="stock",
        status=Status.FILLED,
        message=_msg(id_, url=url, ts=ts),
        created_at=ts,
        updated_at=ts,
    )


# ---------------------------------------------------------------------------
# App / client fixture  (mirrors make_app + client_and_broker pattern)
# ---------------------------------------------------------------------------


@pytest.fixture
def make_filter_app(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> tuple[FastAPI, FakeBrokerClient]:
    broker: FakeBrokerClient = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)
    bus = EventBus()
    runtime_store = LongPortRuntimeStore(settings_file=tmp_path / "longport_settings.json")

    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
            bus=bus,
            longport_runtime=runtime_store,
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app, broker


@pytest.fixture
def client(
    make_filter_app: tuple[FastAPI, FakeBrokerClient],
) -> TestClient:
    app, _ = make_filter_app
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Seed fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_tasks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Seed four tasks covering two URLs and two time windows."""
    seeds = [
        _task("task-a", url="https://a.example", ts=_ts(2026, 5, 20, 9)),
        _task("task-b", url="https://b.example", ts=_ts(2026, 5, 20, 10)),
        _task("task-c", url="https://c.example", ts=_ts(2026, 5, 20, 11)),
        _task("task-old", url="https://a.example", ts=_ts(2026, 5, 10, 9)),
    ]
    for t in seeds:
        async with session_factory() as session:
            await repo.save_task(session, t)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_tasks_multi_url_query(
    client: TestClient,
    seeded_tasks: None,
) -> None:
    """Pass multiple ?urls= values; result is the union of those two URLs."""
    r = client.get(
        "/api/tasks",
        params=[
            ("urls", "https://a.example"),
            ("urls", "https://c.example"),
            ("token", _TOKEN),
        ],
    )
    assert r.status_code == 200, r.text
    ids = {t["id"] for t in r.json()["tasks"]}
    # task-a and task-old both have url https://a.example
    assert "task-a" in ids
    assert "task-old" in ids
    assert "task-c" in ids
    assert "task-b" not in ids


def test_tasks_week_window(
    client: TestClient,
    seeded_tasks: None,
) -> None:
    """week_start / week_end filters on message.posted_at."""
    r = client.get(
        "/api/tasks",
        params={
            "week_start": "2026-05-18T00:00:00",
            "week_end": "2026-05-25T00:00:00",
            "token": _TOKEN,
        },
    )
    assert r.status_code == 200, r.text
    ids = {t["id"] for t in r.json()["tasks"]}
    assert "task-a" in ids
    assert "task-b" in ids
    assert "task-c" in ids
    assert "task-old" not in ids


def test_tasks_window_plus_urls(
    client: TestClient,
    seeded_tasks: None,
) -> None:
    """Combining week window and URL filter returns intersection."""
    r = client.get(
        "/api/tasks",
        params=[
            ("urls", "https://a.example"),
            ("urls", "https://b.example"),
            ("week_start", "2026-05-18T00:00:00"),
            ("week_end", "2026-05-25T00:00:00"),
            ("token", _TOKEN),
        ],
    )
    assert r.status_code == 200, r.text
    ids = {t["id"] for t in r.json()["tasks"]}
    # task-old is excluded by the week window; task-c excluded by URL filter
    assert ids == {"task-a", "task-b"}


def test_tasks_no_filter(
    client: TestClient,
    seeded_tasks: None,
) -> None:
    """Without any URL or window filter all seeded tasks are returned."""
    r = client.get("/api/tasks", params={"token": _TOKEN})
    assert r.status_code == 200, r.text
    ids = {t["id"] for t in r.json()["tasks"]}
    assert ids == {"task-a", "task-b", "task-c", "task-old"}


def test_tasks_empty_urls_returns_nothing(
    client: TestClient,
    seeded_tasks: None,
) -> None:
    """Passing urls= with no value should short-circuit to empty list."""
    # FastAPI will parse a missing-value list param as None (no filter),
    # so we call with an explicit non-existent URL instead.
    r = client.get(
        "/api/tasks",
        params=[("urls", "https://nonexistent.example"), ("token", _TOKEN)],
    )
    assert r.status_code == 200, r.text
    assert r.json()["tasks"] == []
