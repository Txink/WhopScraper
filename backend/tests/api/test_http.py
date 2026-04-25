"""Tests for app.api.http — 6 REST endpoints (Plan Task 33).

14 test cases covering:
 1. GET /api/health → 200, fields populated
 2. GET /api/tasks → 200, empty, null next_cursor
 3. GET /api/tasks with 3 tasks → 200, 3 results in reverse-chron order
 4. GET /api/tasks?status=FILLED → filters correctly
 5. GET /api/tasks with cursor pagination → iterates all
 6. GET /api/tasks/{id} → 200, push_events included
 7. GET /api/tasks/{id} unknown → 404
 8. POST /api/tasks/{id}/cancel → 200, broker.cancelled_orders populated
 9. POST /api/tasks/{id}/cancel unknown → 404
10. POST /api/tasks/{id}/cancel no order_id → 400
11. GET /api/stats/today empty DB → msg_count=0
12. GET /api/stats/today with 3 tasks → correct buckets
13. GET /api/positions empty DB → {stocks:[], options:[]}
14. GET /api/health without token → 403
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.http import build_http_router
from app.core.config import Settings, get_settings
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task
from app.storage import repo
from tests.broker._fakes import FakeBrokerClient

_TOKEN = "test-token-http-XYZ"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now(offset_secs: int = 0) -> datetime:
    """Return a UTC timestamp anchored to today so stats_today() picks it up."""
    base = datetime.combine(date.today(), datetime.min.time(), tzinfo=UTC)
    return base + timedelta(hours=10, seconds=offset_secs)


def _msg(id_: str, *, offset_secs: int = 0) -> Message:
    ts = _now(offset_secs)
    return Message(
        id=id_,
        content="TSLL 26.5 buy",
        raw_content="TSLL 26.5 buy",
        author="trader",
        source="stock",  # type: ignore[arg-type]
        posted_at=ts,
        received_at=ts,
    )


def _task(
    id_: str,
    status: Status = Status.RECEIVED,
    *,
    order_id: str | None = None,
    offset_secs: int = 0,
) -> Task:
    ts = _now(offset_secs)
    return Task(
        id=id_,
        type="stock",
        status=status,
        message=_msg(id_, offset_secs=offset_secs),
        order_id=order_id,
        created_at=ts,
        updated_at=ts,
    )


def _stock_instruction() -> StockInstruction:
    return StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.5,
        price_range=None,
        quantity=100,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def make_app(session_factory: async_sessionmaker[AsyncSession]) -> tuple[FastAPI, FakeBrokerClient]:
    """Return a (FastAPI app, FakeBrokerClient) pair."""
    broker: FakeBrokerClient = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)

    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
        )
    )
    # Override the settings dependency so require_app_token uses the same token.
    app.dependency_overrides[get_settings] = lambda: settings

    return app, broker


@pytest.fixture
def client_and_broker(
    make_app: tuple[FastAPI, FakeBrokerClient],
) -> tuple[TestClient, FakeBrokerClient]:
    app, broker = make_app
    return TestClient(app, raise_server_exceptions=True), broker


# ---------------------------------------------------------------------------
# 1. GET /api/health → 200, fields populated
# ---------------------------------------------------------------------------


def test_health(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/health", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["whop"] == "down"
    assert data["longport"] == "up"
    assert data["mode"] in ("paper", "real")
    assert isinstance(data["dry_run"], bool)


# ---------------------------------------------------------------------------
# 2. GET /api/tasks empty DB → 200, empty, null next_cursor
# ---------------------------------------------------------------------------


def test_tasks_list_empty(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/tasks", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["tasks"] == []
    assert data["next_cursor"] is None


# ---------------------------------------------------------------------------
# 3. GET /api/tasks with 3 tasks → reverse-chron order
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def three_tasks(session_factory: async_sessionmaker[AsyncSession]) -> list[Task]:
    tasks = [
        _task("t1", offset_secs=1),
        _task("t2", offset_secs=2),
        _task("t3", offset_secs=3),
    ]
    for t in tasks:
        async with session_factory() as session:
            await repo.save_task(session, t)
    return tasks


def test_tasks_list_with_data(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    three_tasks: list[Task],
) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/tasks", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 3
    # Reverse-chronological: newest first
    ids = [t["id"] for t in data["tasks"]]
    assert ids == ["t3", "t2", "t1"]


# ---------------------------------------------------------------------------
# 4. GET /api/tasks?status=FILLED → filtered correctly
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def mixed_status_tasks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tasks = [
        _task("mx1", Status.FILLED, offset_secs=1),
        _task("mx2", Status.PARSE_ERROR, offset_secs=2),
        _task("mx3", Status.FILLED, offset_secs=3),
    ]
    for t in tasks:
        async with session_factory() as session:
            await repo.save_task(session, t)


def test_tasks_list_filter_status(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    mixed_status_tasks: None,
) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/tasks", params={"token": _TOKEN, "status": "FILLED"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["tasks"]) == 2
    assert all(t["status"] == "FILLED" for t in data["tasks"])


# ---------------------------------------------------------------------------
# 5. GET /api/tasks pagination — save 5, iterate with limit=2
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def five_tasks(session_factory: async_sessionmaker[AsyncSession]) -> list[Task]:
    tasks = [_task(f"p{i}", offset_secs=i) for i in range(1, 6)]
    for t in tasks:
        async with session_factory() as session:
            await repo.save_task(session, t)
    return tasks


def test_tasks_list_pagination(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    five_tasks: list[Task],
) -> None:
    client, _ = client_and_broker
    collected: list[str] = []
    cursor: str | None = None

    while True:
        params: dict[str, object] = {"token": _TOKEN, "limit": 2}
        if cursor:
            params["cursor"] = cursor
        resp = client.get("/api/tasks", params=params)
        assert resp.status_code == 200
        data = resp.json()
        collected.extend(t["id"] for t in data["tasks"])
        cursor = data["next_cursor"]
        if cursor is None:
            break

    assert sorted(collected) == ["p1", "p2", "p3", "p4", "p5"]
    assert len(collected) == 5


# ---------------------------------------------------------------------------
# 6. GET /api/tasks/{id} → 200, push_events included
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def task_with_push(session_factory: async_sessionmaker[AsyncSession]) -> Task:
    task = _task("tw1", Status.PENDING, order_id="ORD-TW1", offset_secs=0)
    async with session_factory() as session:
        await repo.save_task(session, task)

    evt = PushEvent(
        id="evt-tw1",
        task_id="tw1",
        order_id="ORD-TW1",
        state=PushState.NEW,
        received_at=datetime(2026, 4, 24, 10, 1, 0, tzinfo=UTC),
        payload={"x": 1},
    )
    async with session_factory() as session:
        await repo.append_push_event(session, evt)

    return task


def test_task_detail_found(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    task_with_push: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/tasks/tw1", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "tw1"
    assert len(data["push_events"]) == 1
    assert data["push_events"][0]["id"] == "evt-tw1"


# ---------------------------------------------------------------------------
# 7. GET /api/tasks/{id} unknown → 404
# ---------------------------------------------------------------------------


def test_task_detail_404(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/tasks/no-such-id", params={"token": _TOKEN})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 8. POST /api/tasks/{id}/cancel → 200, broker.cancelled_orders populated
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def pending_task_with_order(session_factory: async_sessionmaker[AsyncSession]) -> Task:
    task = _task("cxl1", Status.PENDING, order_id="ORD-CXL1", offset_secs=0)
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


def test_cancel_calls_broker(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    pending_task_with_order: Task,
) -> None:
    client, broker = client_and_broker
    resp = client.post("/api/tasks/cxl1/cancel", params={"token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "ORD-CXL1" in broker.cancelled_orders


# ---------------------------------------------------------------------------
# 9. POST cancel unknown task → 404
# ---------------------------------------------------------------------------


def test_cancel_404_when_task_missing(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/no-such-id/cancel", params={"token": _TOKEN})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 10. POST cancel task without order_id → 400
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def received_task_no_order(session_factory: async_sessionmaker[AsyncSession]) -> Task:
    task = _task("cxl2", Status.RECEIVED, order_id=None, offset_secs=0)
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


def test_cancel_400_when_no_order_id(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    received_task_no_order: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/cxl2/cancel", params={"token": _TOKEN})
    assert resp.status_code == 400
    assert "order_id" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 11. GET /api/stats/today empty DB → msg_count=0
# ---------------------------------------------------------------------------


def test_stats_today_empty(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/stats/today", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["msg_count"] == 0
    assert data["parse_rate"] == 0.0


# ---------------------------------------------------------------------------
# 12. GET /api/stats/today with tasks → correct buckets
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def stats_tasks(session_factory: async_sessionmaker[AsyncSession]) -> None:
    tasks = [
        _task("st1", Status.FILLED, offset_secs=1),
        _task("st2", Status.PARSE_ERROR, offset_secs=2),
        _task("st3", Status.PENDING, offset_secs=3),
    ]
    for t in tasks:
        async with session_factory() as session:
            await repo.save_task(session, t)


def test_stats_today_counts_correctly(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    stats_tasks: None,
) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/stats/today", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["msg_count"] == 3
    # FILLED + PENDING = parse_ok (PARSE_ERROR is not in parse_ok set)
    assert data["parse_ok"] == 2
    assert data["filled"] == 1
    # PARSE_ERROR counts as rejected
    assert data["rejected"] == 1
    # orders: FILLED + PENDING
    assert data["orders"] == 2
    assert abs(data["parse_rate"] - (2 / 3)) < 0.001


# ---------------------------------------------------------------------------
# 13. GET /api/positions empty DB → {stocks:[], options:[]}
# ---------------------------------------------------------------------------


def test_positions_empty_returns_empty_lists(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/positions", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["stocks"] == []
    assert data["options"] == []


# ---------------------------------------------------------------------------
# 14. No token → 403
# ---------------------------------------------------------------------------


def test_missing_token_403(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/health")
    assert resp.status_code == 403
