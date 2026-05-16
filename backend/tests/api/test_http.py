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
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task
from app.storage import repo
from app.storage.listeners import register_storage_listeners
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
def make_app(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> tuple[FastAPI, FakeBrokerClient]:
    """Return a (FastAPI app, FakeBrokerClient) pair.

    Builds an isolated LongPortRuntimeStore backed by a tmp file so any
    PATCH /api/longport/settings calls in tests do NOT clobber the real
    data/longport_settings.json — that file holds the user's real
    credentials and was being silently overwritten by every test run.
    """
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
    # Override the settings dependency so require_app_token uses the same token.
    app.dependency_overrides[get_settings] = lambda: settings

    # Register storage listeners so events are persisted to DB
    register_storage_listeners(bus, session_factory)

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
    # account_label is empty when no account is active yet (test fixture
    # has no accounts registered) — present as a string field regardless.
    assert isinstance(data["account_label"], str)
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


def test_positions_returns_broker_holdings(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """Live broker.stock_positions() drives the response — no DB cache."""
    client, broker = client_and_broker
    broker.stock_positions_list = [  # type: ignore[attr-defined]
        {"symbol": "TSLL.US", "ticker": "TSLL", "name": "Direxion TSLA Bull 2X",
         "quantity": 800, "avg_cost": 11.889, "currency": "USD"},
        {"symbol": "IREN.US", "ticker": "IREN", "name": "IREN",
         "quantity": 55, "avg_cost": 44.935, "currency": "USD"},
    ]
    resp = client.get("/api/positions", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert [p["ticker"] for p in data["stocks"]] == ["TSLL", "IREN"]
    assert data["stocks"][0]["quantity"] == 800
    assert data["stocks"][0]["avg_cost"] == pytest.approx(11.889)


def test_positions_broker_error_falls_back_to_empty(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """If the broker raises (e.g. SDK transient failure), we return [] rather
    than 502 — the dashboard treats absence as 'no positions'."""
    client, broker = client_and_broker

    def boom() -> list:
        raise RuntimeError("simulated broker outage")
    broker.stock_positions = boom  # type: ignore[assignment]

    resp = client.get("/api/positions", params={"token": _TOKEN})
    assert resp.status_code == 200
    assert resp.json()["stocks"] == []


# ---------------------------------------------------------------------------
# 14. No token → 403
# ---------------------------------------------------------------------------


def test_missing_token_403(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/health")
    assert resp.status_code == 403


def test_get_longport_settings(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    client, _ = client_and_broker
    resp = client.get("/api/longport/settings", params={"token": _TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    # Multi-account shape: list of accounts + active pointer + flags.
    assert "active_account_id" in body
    assert isinstance(body["accounts"], list)
    assert "auto_trade" in body and "dry_run" in body and "region" in body


def test_patch_longport_settings(client_and_broker: tuple[TestClient, FakeBrokerClient]) -> None:
    """PATCH only accepts auto_trade / region / dry_run.

    Account list + active selection mutate exclusively through
    /api/longport/oauth/* endpoints. Anything else in the body is
    silently dropped (Pydantic ignores unknown fields).
    """
    client, _ = client_and_broker
    resp = client.patch(
        "/api/longport/settings",
        params={"token": _TOKEN},
        json={
            "auto_trade": False,
            "dry_run": False,
            "region": "hk",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auto_trade"] is False
    assert body["dry_run"] is False
    assert body["region"] == "hk"
    # Account list shape unchanged by a flag-only PATCH.
    assert isinstance(body["accounts"], list)
    assert "active_account_id" in body


def test_patch_longport_settings_rejects_legacy_credential_fields(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """Legacy `mode` / `paper` / `real` payloads must be ignored by the
    multi-account schema. Pydantic drops unknown fields; the persisted
    shape stays clean.
    """
    client, _ = client_and_broker
    resp = client.patch(
        "/api/longport/settings",
        params={"token": _TOKEN},
        json={
            "mode": "real",
            "paper": {"app_key": "x", "app_secret": "y", "access_token": "z"},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    # No mode or per-mode slot keys leak into the response.
    assert "mode" not in body
    assert "paper" not in body
    assert "real" not in body


@pytest_asyncio.fixture
async def instruction_ready_task(session_factory: async_sessionmaker[AsyncSession]) -> Task:
    task = _task("confirm-1", Status.RECEIVED, offset_secs=0)
    task.mark_parsing()
    task.attach_instruction(_stock_instruction())
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


def test_confirm_task_endpoint_ok(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    instruction_ready_task: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/confirm-1/confirm", params={"token": _TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "confirm-1"
    assert body["status"] == "INSTRUCTION_READY"


def test_confirm_task_endpoint_rejects_non_instruction_ready(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    received_task_no_order: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/cxl2/confirm", params={"token": _TOKEN})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Skip endpoint — POST /api/tasks/{id}/skip
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def ready_task_for_skip(
    session_factory: async_sessionmaker[AsyncSession],
) -> Task:
    task = _task("skp1", Status.INSTRUCTION_READY, offset_secs=0)
    task.instruction = _stock_instruction()
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


def test_skip_marks_task_skipped(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    ready_task_for_skip: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/skp1/skip", params={"token": _TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "SKIPPED"
    assert data["reject_reason"] == "用户手动取消"


def test_skip_404_when_task_missing(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/no-such-id/skip", params={"token": _TOKEN})
    assert resp.status_code == 404


@pytest_asyncio.fixture
async def pending_task_no_skip(
    session_factory: async_sessionmaker[AsyncSession],
) -> Task:
    task = _task("skp2", Status.PENDING, order_id="ORD-PSKP", offset_secs=0)
    async with session_factory() as session:
        await repo.save_task(session, task)
    return task


def test_skip_400_when_status_not_instruction_ready(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    pending_task_no_skip: Task,
) -> None:
    client, _ = client_and_broker
    resp = client.post("/api/tasks/skp2/skip", params={"token": _TOKEN})
    assert resp.status_code == 400
    assert "INSTRUCTION_READY" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Broker status + reload endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_broker_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[FastAPI, dict, FakeBrokerClient]:
    """Variant of make_app that also wires broker_status_fn + broker_reload_fn.

    The state dict stays mutable so tests can assert reload swapped the
    broker / mutated last_init_error.
    """
    broker = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)
    state = {
        "broker": broker,
        "is_real": True,  # FakeBroker stands in for a "real" client in tests
        "last_init_error": None,
        "reload_count": 0,
    }

    def _status() -> dict:
        return {
            "is_real": state["is_real"],
            "mode": "paper" if state["broker"].is_paper else "real",
            "dry_run": state["broker"].dry_run,
            "last_init_error": state["last_init_error"],
        }

    async def _reload() -> dict:
        # Simulate a real reload: optionally toggle to "noop" / set an error.
        state["reload_count"] += 1
        return _status()

    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
            bus=EventBus(),
            broker_status_fn=_status,
            broker_reload_fn=_reload,
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app, state, broker


def test_broker_status_returns_current_state(
    app_with_broker_lifecycle: tuple[FastAPI, dict, FakeBrokerClient],
) -> None:
    app, state, _ = app_with_broker_lifecycle
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/longport/broker/status", params={"token": _TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_real"] is True
    # account_label replaces the prior paper/real mode field.
    assert isinstance(body["account_label"], str)
    assert body["dry_run"] is False
    assert body["last_init_error"] is None


def test_broker_status_surfaces_init_error(
    app_with_broker_lifecycle: tuple[FastAPI, dict, FakeBrokerClient],
) -> None:
    app, state, _ = app_with_broker_lifecycle
    state["is_real"] = False
    state["last_init_error"] = "OpenApiException: token empty"
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.get("/api/longport/broker/status", params={"token": _TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_real"] is False
    assert body["last_init_error"] == "OpenApiException: token empty"


def test_broker_reload_invokes_reload_fn(
    app_with_broker_lifecycle: tuple[FastAPI, dict, FakeBrokerClient],
) -> None:
    app, state, _ = app_with_broker_lifecycle
    client = TestClient(app, raise_server_exceptions=True)
    resp = client.post("/api/longport/broker/reload", params={"token": _TOKEN})
    assert resp.status_code == 200
    assert state["reload_count"] == 1
    body = resp.json()
    assert body["is_real"] is True
    # And status reflects post-reload state
    resp2 = client.post("/api/longport/broker/reload", params={"token": _TOKEN})
    assert resp2.status_code == 200
    assert state["reload_count"] == 2


def test_broker_status_endpoint_omitted_when_status_fn_not_provided(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """When the lifespan does not pass status/reload functions (e.g. minimal
    test setups), the corresponding endpoints are 404 — not registered."""
    broker = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)
    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
            bus=EventBus(),
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app, raise_server_exceptions=True)

    resp = client.get("/api/longport/broker/status", params={"token": _TOKEN})
    assert resp.status_code == 404
    resp = client.post("/api/longport/broker/reload", params={"token": _TOKEN})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# OAuth endpoints — register / start / status / logout
# ---------------------------------------------------------------------------


def test_oauth_start_registers_fresh_account(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each /oauth/start registers a NEW OAuth client; the resulting
    account_id is returned to the caller for polling."""
    from app.broker import oauth as oauth_mod

    client, _ = client_and_broker
    registered: list[str] = []

    async def fake_register(client_name: str = "Signal Station", **_: object) -> str:
        registered.append(client_name)
        return "fresh-acct-1"

    monkeypatch.setattr(oauth_mod, "register_client", fake_register)

    async def fake_start(self, client_id: str, **_: object):
        from app.broker.oauth import OAuthSession

        sess = OAuthSession(session_id="sid-1", client_id=client_id)
        sess.auth_url = f"https://example.test/auth?cid={client_id}"
        sess.state = "ready"
        self._sessions[sess.session_id] = sess
        return sess

    monkeypatch.setattr(oauth_mod.OAuthCoordinator, "start", fake_start)

    resp = client.post(
        "/api/longport/oauth/start",
        params={"token": _TOKEN},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["account_id"] == "fresh-acct-1"
    assert body["session_id"] == "sid-1"
    assert "fresh-acct-1" in body["auth_url"]
    assert registered == ["Signal Station"]


def test_oauth_status_adds_account_on_success(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When /oauth/status flips to success, the new account_id is appended
    to the accounts list and becomes active (it's the first one)."""
    from app.broker import oauth as oauth_mod
    from app.broker.oauth import OAuthSession

    client, _ = client_and_broker

    async def fake_register(**_: object) -> str:
        return "acct-success"

    monkeypatch.setattr(oauth_mod, "register_client", fake_register)

    captured: dict[str, OAuthSession] = {}

    async def fake_start(self, client_id: str, **_: object):
        sess = OAuthSession(session_id="sid-success", client_id=client_id)
        sess.auth_url = "https://example.test/auth"
        sess.state = "ready"
        self._sessions[sess.session_id] = sess
        captured["session"] = sess
        return sess

    monkeypatch.setattr(oauth_mod.OAuthCoordinator, "start", fake_start)

    client.post(
        "/api/longport/oauth/start",
        params={"token": _TOKEN},
    )
    captured["session"].state = "success"

    resp = client.get(
        "/api/longport/oauth/status",
        params={"token": _TOKEN, "session_id": "sid-success"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "success"
    assert body["account_id"] == "acct-success"

    settings = client.get("/api/longport/settings", params={"token": _TOKEN}).json()
    # The first account added is auto-promoted to active.
    assert settings["active_account_id"] == "acct-success"
    account_ids = [a["account_id"] for a in settings["accounts"]]
    assert "acct-success" in account_ids


def test_oauth_status_unknown_session_returns_404(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    client, _ = client_and_broker
    resp = client.get(
        "/api/longport/oauth/status",
        params={"token": _TOKEN, "session_id": "no-such-session"},
    )
    assert resp.status_code == 404


def test_oauth_logout_removes_account(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /oauth/logout scrubs the token cache and drops the slot."""
    from app.broker import oauth as oauth_mod
    from app.broker.oauth import OAuthSession

    client, _ = client_and_broker

    async def fake_register(**_: object) -> str:
        return "acct-to-logout"

    monkeypatch.setattr(oauth_mod, "register_client", fake_register)

    captured: dict[str, OAuthSession] = {}

    async def fake_start(self, client_id: str, **_: object):
        sess = OAuthSession(session_id="sid-x", client_id=client_id)
        sess.auth_url = "https://example.test/auth"
        sess.state = "ready"
        self._sessions[sess.session_id] = sess
        captured["session"] = sess
        return sess

    monkeypatch.setattr(oauth_mod.OAuthCoordinator, "start", fake_start)

    revoked: list[str] = []

    def fake_revoke(cid: str | None) -> bool:
        if cid:
            revoked.append(cid)
        return True

    monkeypatch.setattr(oauth_mod, "revoke_local_token", fake_revoke)

    # First add the account (start + flip to success + poll status).
    client.post("/api/longport/oauth/start", params={"token": _TOKEN})
    captured["session"].state = "success"
    client.get(
        "/api/longport/oauth/status",
        params={"token": _TOKEN, "session_id": "sid-x"},
    )

    resp = client.post(
        "/api/longport/oauth/logout",
        params={"token": _TOKEN},
        json={"account_id": "acct-to-logout"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Account removed from list; active pointer reset to None (no fallback).
    assert all(a["account_id"] != "acct-to-logout" for a in body["accounts"])
    assert body["active_account_id"] is None
    assert revoked == ["acct-to-logout"]


def test_oauth_activate_and_rename(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activate + rename endpoints mutate the runtime store correctly."""
    from app.broker import oauth as oauth_mod
    from app.broker.oauth import OAuthSession

    client, _ = client_and_broker

    counter = {"n": 0}

    async def fake_register(**_: object) -> str:
        counter["n"] += 1
        return f"acct-{counter['n']}"

    monkeypatch.setattr(oauth_mod, "register_client", fake_register)

    sessions: dict[str, OAuthSession] = {}

    async def fake_start(self, client_id: str, **_: object):
        sid = f"sid-{client_id}"
        sess = OAuthSession(session_id=sid, client_id=client_id)
        sess.auth_url = "https://example.test/auth"
        sess.state = "ready"
        self._sessions[sid] = sess
        sessions[client_id] = sess
        return sess

    monkeypatch.setattr(oauth_mod.OAuthCoordinator, "start", fake_start)

    # Add two accounts.
    for _ in range(2):
        r = client.post("/api/longport/oauth/start", params={"token": _TOKEN}).json()
        sessions[r["account_id"]].state = "success"
        client.get(
            "/api/longport/oauth/status",
            params={"token": _TOKEN, "session_id": r["session_id"]},
        )

    # First account is active by default.
    settings = client.get("/api/longport/settings", params={"token": _TOKEN}).json()
    assert settings["active_account_id"] == "acct-1"

    # Activate the second account.
    resp = client.post(
        "/api/longport/oauth/activate",
        params={"token": _TOKEN},
        json={"account_id": "acct-2"},
    )
    assert resp.status_code == 200
    assert resp.json()["active_account_id"] == "acct-2"

    # Rename the second account.
    resp = client.patch(
        "/api/longport/oauth/account",
        params={"token": _TOKEN},
        json={"account_id": "acct-2", "label": "副账户"},
    )
    assert resp.status_code == 200
    labels = {a["account_id"]: a["label"] for a in resp.json()["accounts"]}
    assert labels["acct-2"] == "副账户"


def test_today_executions_endpoint_aggregates_partial_fills(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """today_executions now aggregates per-fill rows by order_id (qty sum,
    weighted-avg price, latest ts). Endpoint syncs to DB then reads back
    one row per order. Side-less rows get filtered at response time."""
    from datetime import datetime, timezone

    client, broker = client_and_broker
    broker.history_executions_list = [  # type: ignore[attr-defined]
        # Two partial fills on the same order — should aggregate.
        {
            "order_id": "o-1",
            "trade_id": "t-1a",
            "symbol": "HOOD260618P100000.US",
            "ticker": "HOOD",
            "side": "SELL",
            "qty": 30,
            "price": 1.7,
            "ts": datetime(2026, 5, 15, 16, 0, 0, tzinfo=timezone.utc),
        },
        {
            "order_id": "o-1",
            "trade_id": "t-1b",
            "symbol": "HOOD260618P100000.US",
            "ticker": "HOOD",
            "side": "SELL",
            "qty": 10,
            "price": 1.7,
            "ts": datetime(2026, 5, 15, 16, 1, 0, tzinfo=timezone.utc),
        },
        # Separate order with empty side — kept in DB but filtered at
        # response (side not BUY/SELL).
        {
            "order_id": "o-2",
            "symbol": "HOOD260618P100000.US",
            "ticker": "HOOD",
            "side": "",
            "qty": 20,
            "price": 1.5,
            "ts": datetime(2026, 5, 15, 16, 30, 0, tzinfo=timezone.utc),
        },
    ]
    resp = client.get("/api/broker/today_executions", params={"token": _TOKEN})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # o-1 aggregates to qty=40, o-2 drops due to empty side.
    assert len(body["executions"]) == 1
    exec0 = body["executions"][0]
    assert exec0["order_id"] == "o-1"
    assert exec0["side"] == "SELL"
    assert exec0["qty"] == 40
    assert exec0["price"] == 1.7  # weighted avg of identical prices
    # task_id is null because no signal-station task points at this order_id.
    assert exec0["task_id"] is None


def test_history_executions_endpoint_paginates(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """``/api/broker/executions?offset=&limit=`` slices the result newest-first
    and reports total_count + has_more so the UI can drive "加载更多" without
    losing cross-page做T binding state."""
    from datetime import datetime, timedelta, timezone

    client, broker = client_and_broker
    base = datetime(2026, 5, 14, 16, 0, 0, tzinfo=timezone.utc)
    # 5 distinct fills, monotonically-increasing ts so order is unambiguous.
    broker.history_executions_list = [  # type: ignore[attr-defined]
        {
            "order_id": f"o-{i}",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "BUY" if i % 2 == 0 else "SELL",
            "qty": 10 + i,
            "price": 200.0 + i,
            "ts": base + timedelta(minutes=i),
        }
        for i in range(5)
    ]

    # Page 1: newest 2.
    r1 = client.get(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA", "offset": 0, "limit": 2},
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["total_count"] == 5
    assert b1["has_more"] is True
    assert [e["order_id"] for e in b1["executions"]] == ["o-4", "o-3"]

    # Page 2: next 2.
    r2 = client.get(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA", "offset": 2, "limit": 2},
    )
    b2 = r2.json()
    assert b2["total_count"] == 5
    assert b2["has_more"] is True
    assert [e["order_id"] for e in b2["executions"]] == ["o-2", "o-1"]

    # Page 3: tail row, has_more flips off.
    r3 = client.get(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA", "offset": 4, "limit": 2},
    )
    b3 = r3.json()
    assert b3["total_count"] == 5
    assert b3["has_more"] is False
    assert [e["order_id"] for e in b3["executions"]] == ["o-0"]


def test_history_executions_endpoint_backfills_across_windows(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """First-time sync iterates 90-day chunks backwards up to ``days`` total
    so rows older than 90d still land in the DB. Asserts that a row at
    ``now-150d`` is persisted alongside one at ``now-15d`` (i.e. multiple
    windows were issued)."""
    from datetime import datetime, timedelta, timezone

    client, broker = client_and_broker
    now = datetime.now(timezone.utc)
    broker.history_executions_list = [  # type: ignore[attr-defined]
        # Window 1 (now-90d → now): recent fill
        {
            "order_id": "recent",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "BUY",
            "qty": 10,
            "price": 200.0,
            "ts": now - timedelta(days=15),
        },
        # Window 2 (now-180d → now-90d): old fill, only reachable if
        # the sync issued a second backfill chunk.
        {
            "order_id": "old",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "SELL",
            "qty": 5,
            "price": 220.0,
            "ts": now - timedelta(days=150),
        },
    ]

    r = client.get(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA", "days": 365, "limit": 50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_count"] == 2
    ids = sorted(e["order_id"] for e in body["executions"])
    assert ids == ["old", "recent"]


def test_history_executions_endpoint_incremental_gap_over_90d_chunks(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Once ``history_synced=True``, gap-from-MAX(ts) sync walks 90-day
    chunks when the gap exceeds the broker's per-call cap.

    Pre-condition: a positions row exists with ``history_synced=True``
    (i.e. we've previously full-backfilled this ticker). Seeds the DB
    with a 200-day-old fill so MAX(ts) is 200 days ago. The sync must
    walk the 200-day gap in 90-day chunks; a single wide call would be
    rejected by FakeBroker mirroring the broker's cap.
    """
    import asyncio
    from datetime import UTC, datetime, timedelta

    client, broker = client_and_broker
    broker.account_id_value = "test-acct"  # type: ignore[attr-defined]
    now = datetime.now(UTC)

    async def _seed() -> None:
        async with session_factory() as session:
            await repo.upsert_positions(
                session,
                account_id="test-acct",
                rows=[{
                    "symbol": "TSLA.US",
                    "ticker": "TSLA",
                    "quantity": 100,
                    "avg_cost": 100.0,
                }],
            )
            await repo.mark_position_history_synced(
                session, account_id="test-acct", ticker="TSLA"
            )
            await repo.upsert_broker_executions(
                session,
                account_id="test-acct",
                rows=[{
                    "order_id": "seed-old",
                    "symbol": "TSLA.US",
                    "ticker": "TSLA",
                    "side": "BUY",
                    "qty": 10,
                    "price": 100.0,
                    "ts": now - timedelta(days=200),
                }],
            )

    asyncio.get_event_loop().run_until_complete(_seed())

    # New broker-side fill arrived 10 days ago — must be reachable via
    # the chunked gap sync (first chunk: now → now-90d covers it).
    broker.history_executions_list = [  # type: ignore[attr-defined]
        {
            "order_id": "new-fill",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "SELL",
            "qty": 5,
            "price": 120.0,
            "ts": now - timedelta(days=10),
        },
    ]

    r = client.get(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA", "limit": 50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = sorted(e["order_id"] for e in body["executions"])
    assert ids == ["new-fill", "seed-old"]
    assert body["total_count"] == 2


def test_history_executions_endpoint_full_backfill_even_with_narrow_sync_residue(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Regression: a residual row from the 2-day ``today_executions`` sync
    must NOT prevent the detail-pane open from doing the full backfill.

    Setup mirrors what we observed on the user's machine:
    - ``positions`` has a TSLA row with ``history_synced=False`` (just
      created by the dashboard's /api/positions fetch).
    - ``broker_executions`` has 1 recent TSLA fill written by the 2-day
      ``today_executions`` sync.
    - The broker has many more TSLA fills going back 200 days.

    Expected: opening the detail page triggers the FULL backfill (not the
    1-day gap from MAX(ts)) and ``history_synced`` flips to True.
    """
    import asyncio
    from datetime import UTC, datetime, timedelta

    client, broker = client_and_broker
    broker.account_id_value = "test-acct"  # type: ignore[attr-defined]
    now = datetime.now(UTC)

    async def _seed() -> None:
        async with session_factory() as session:
            await repo.upsert_positions(
                session,
                account_id="test-acct",
                rows=[{
                    "symbol": "TSLA.US",
                    "ticker": "TSLA",
                    "quantity": 100,
                    "avg_cost": 100.0,
                }],
            )
            # today_executions 2-day sync seeded a single recent fill.
            await repo.upsert_broker_executions(
                session,
                account_id="test-acct",
                rows=[{
                    "order_id": "narrow-recent",
                    "symbol": "TSLA.US",
                    "ticker": "TSLA",
                    "side": "BUY",
                    "qty": 100,
                    "price": 110.0,
                    "ts": now - timedelta(days=1),
                }],
            )

    asyncio.get_event_loop().run_until_complete(_seed())

    # Broker has the recent fill PLUS a much older one (200 days ago)
    # that the 2-day sync never touched.
    broker.history_executions_list = [  # type: ignore[attr-defined]
        {
            "order_id": "narrow-recent",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "BUY",
            "qty": 100,
            "price": 110.0,
            "ts": now - timedelta(days=1),
        },
        {
            "order_id": "ancient",
            "symbol": "TSLA.US",
            "ticker": "TSLA",
            "side": "BUY",
            "qty": 50,
            "price": 90.0,
            "ts": now - timedelta(days=200),
        },
    ]

    r = client.get(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA", "days": 730, "limit": 50},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ids = sorted(e["order_id"] for e in body["executions"])
    assert ids == ["ancient", "narrow-recent"], (
        "full backfill must reach the 200-day-old fill, not stop at MAX(ts)"
    )

    # And history_synced must now be True so subsequent opens take the
    # cheap path.
    async def _check_flag() -> bool:
        async with session_factory() as session:
            return await repo.is_position_history_synced(
                session, account_id="test-acct", ticker="TSLA"
            )

    flagged = asyncio.get_event_loop().run_until_complete(_check_flag())
    assert flagged is True


def test_delete_broker_executions_clears_rows_and_history_synced(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``DELETE /api/broker/executions?ticker=X`` wipes that ticker's
    rows from ``broker_executions`` AND flips the corresponding
    positions.history_synced back to False, so a follow-up GET re-
    triggers the full chunked backfill from scratch. Other tickers
    untouched."""
    import asyncio
    from datetime import UTC, datetime, timedelta

    client, broker = client_and_broker
    broker.account_id_value = "test-acct"  # type: ignore[attr-defined]
    now = datetime.now(UTC)

    async def _seed() -> None:
        async with session_factory() as session:
            await repo.upsert_positions(
                session,
                account_id="test-acct",
                rows=[
                    {"symbol": "TSLA.US", "ticker": "TSLA", "quantity": 50,
                     "avg_cost": 100.0},
                    {"symbol": "NVDA.US", "ticker": "NVDA", "quantity": 20,
                     "avg_cost": 200.0},
                ],
            )
            await repo.mark_position_history_synced(
                session, account_id="test-acct", ticker="TSLA"
            )
            await repo.mark_position_history_synced(
                session, account_id="test-acct", ticker="NVDA"
            )
            await repo.upsert_broker_executions(
                session,
                account_id="test-acct",
                rows=[
                    {"order_id": "tx-1", "symbol": "TSLA.US", "ticker": "TSLA",
                     "side": "BUY", "qty": 10, "price": 100.0,
                     "ts": now - timedelta(days=5)},
                    {"order_id": "nx-1", "symbol": "NVDA.US", "ticker": "NVDA",
                     "side": "BUY", "qty": 5, "price": 200.0,
                     "ts": now - timedelta(days=5)},
                ],
            )

    asyncio.get_event_loop().run_until_complete(_seed())

    resp = client.delete(
        "/api/broker/executions",
        params={"token": _TOKEN, "ticker": "TSLA"},
    )
    assert resp.status_code == 204, resp.text

    async def _verify() -> tuple[list[str], bool, bool]:
        async with session_factory() as session:
            from sqlalchemy import select
            from app.storage.schema import BrokerExecutionRow

            result = await session.execute(
                select(BrokerExecutionRow.order_id, BrokerExecutionRow.ticker)
                .where(BrokerExecutionRow.account_id == "test-acct")
            )
            rows = [r.ticker for r in result.all()]
            tsla_synced = await repo.is_position_history_synced(
                session, account_id="test-acct", ticker="TSLA"
            )
            nvda_synced = await repo.is_position_history_synced(
                session, account_id="test-acct", ticker="NVDA"
            )
            return rows, tsla_synced, nvda_synced

    tickers, tsla_synced, nvda_synced = asyncio.get_event_loop().run_until_complete(
        _verify()
    )
    assert tickers == ["NVDA"]
    assert tsla_synced is False, "TSLA history_synced must reset so next GET re-backfills"
    assert nvda_synced is True, "NVDA flag must survive — other tickers untouched"


def test_delete_broker_executions_requires_ticker(
    client_and_broker: tuple[TestClient, FakeBrokerClient],
) -> None:
    """Bulk delete must specify ``ticker`` — there's no shortcut to
    wipe across all tickers in a single account."""
    client, _ = client_and_broker
    resp = client.delete("/api/broker/executions", params={"token": _TOKEN})
    assert resp.status_code in (400, 422), resp.text


def test_quotes_watch_endpoint_diffs_subscriptions(
    tmp_path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """POST /api/quotes/watch replaces the symbol watch list — backend
    diffs the new set against the prior one and subscribes/unsubscribes
    on the broker accordingly. Empty list clears everything."""
    from app.api.http import build_http_router
    from app.broker.subscription_manager import SubscriptionManager
    from app.core.config import Settings
    from app.core.event_bus import EventBus
    import asyncio

    broker = FakeBrokerClient()
    settings = Settings(app_token=_TOKEN)
    bus = EventBus()

    # Lazily-bound manager — created on first endpoint hit so the router
    # can be built before there's an event loop.
    mgr_ref: dict[str, SubscriptionManager | None] = {"mgr": None}

    def _get_mgr() -> SubscriptionManager:
        if mgr_ref["mgr"] is None:
            mgr_ref["mgr"] = SubscriptionManager(broker, asyncio.get_event_loop())
            mgr_ref["mgr"].attach()
        return mgr_ref["mgr"]

    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=broker,
            settings=settings,
            bus=bus,
            subscription_manager_getter=_get_mgr,
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)

    # First watch — pure additions.
    r1 = client.post(
        "/api/quotes/watch",
        params={"token": _TOKEN},
        json={"symbols": ["TSLA.US", "AAPL.US"]},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json() == {"added": 2, "removed": 0, "total": 2}

    # Swap one, keep one.
    r2 = client.post(
        "/api/quotes/watch",
        params={"token": _TOKEN},
        json={"symbols": ["TSLA.US", "NVDA.US"]},
    )
    assert r2.json() == {"added": 1, "removed": 1, "total": 2}

    # Empty list clears.
    r3 = client.post(
        "/api/quotes/watch",
        params={"token": _TOKEN},
        json={"symbols": []},
    )
    assert r3.json() == {"added": 0, "removed": 2, "total": 0}


def test_quotes_watch_endpoint_503_when_hub_unavailable(
    tmp_path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No subscription_manager_getter passed → endpoint returns 503 so
    the frontend can retry after broker init / auth completes."""
    from app.api.http import build_http_router
    from app.core.config import Settings
    from app.core.event_bus import EventBus

    settings = Settings(app_token=_TOKEN)
    app = FastAPI()
    app.include_router(
        build_http_router(
            session_factory=session_factory,
            broker=FakeBrokerClient(),
            settings=settings,
            bus=EventBus(),
        )
    )
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)

    r = client.post(
        "/api/quotes/watch",
        params={"token": _TOKEN},
        json={"symbols": ["TSLA.US"]},
    )
    assert r.status_code == 503
