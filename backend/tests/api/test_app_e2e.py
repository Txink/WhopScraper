"""End-to-end: full FastAPI app assembled via create_app() factory.

Tests verify that:
1. All routers are correctly mounted via lifespan.
2. REST endpoints (health, tasks, auth) work through the real app assembly.
3. WebSocket hub receives bus events and broadcasts to connected clients.
4. Storage listeners persist tasks so GET /api/tasks returns them.

TestClient runs the ASGI app in a background thread via anyio.  We use
``client.portal.call(coro)`` to schedule async bus.publish() calls on the
server's event loop, then ``bus.wait_idle(timeout=...)`` to drain handlers
before checking HTTP responses or WebSocket messages.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.core.event_bus import Event
from app.core.events import TaskPayload, Topics
from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.main import create_app
from tests.broker._fakes import FakeBrokerClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 4, 25, 10, 42, tzinfo=UTC)


def _make_message(msg_id: str = "msg-e2e-1") -> Message:
    return Message(
        id=msg_id,
        content="TSLL 26.5 加一半",
        raw_content="TSLL 26.5 加一半",
        author="e2e",
        posted_at=_NOW,
        received_at=_NOW,
        source="stock",
    )


def _make_stock_task(msg_id: str = "msg-e2e-1") -> Task:
    """Construct a Task that is already past the INSTRUCTION_READY stage.

    Publishing TASK_INSTRUCTION_READY with this task lets the storage listener
    persist it so GET /api/tasks can return it.
    """
    msg = _make_message(msg_id)
    task = Task.new_from_message(msg)
    task.mark_parsing()
    task.attach_instruction(
        StockInstruction(
            instruction_type=InstructionType.BUY,
            price=26.5,
            price_range=None,
            quantity=500,
            position_size=None,
            stop_loss_price=None,
            take_profit_price=None,
            context_source="group",
            parser_notes=[],
            ticker="TSLL",
            symbol="TSLL.US",
            sell_quantity=None,
        )
    )
    return task


def _make_settings(token: str = "e2e-token") -> Settings:
    """Return a Settings instance using in-memory SQLite for test isolation."""
    return Settings(
        app_token=token,
        database_url="sqlite+aiosqlite:///:memory:",
    )


# ---------------------------------------------------------------------------
# 1. Health + empty task list + populated task list
# ---------------------------------------------------------------------------


def test_e2e_rest_tasks_empty_then_populated() -> None:
    """Full round-trip: app starts, /api/health 200, tasks empty, publish event, tasks 1."""
    settings = _make_settings()
    broker = FakeBrokerClient()
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    # Override settings dependency so require_app_token uses our token.
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        # Health check
        r = client.get("/api/health", params={"token": "e2e-token"})
        assert r.status_code == 200
        data = r.json()
        assert data["longport"] == "up"
        assert data["mode"] == "paper"  # FakeBrokerClient.is_paper = True

        # Empty task list at startup
        r = client.get("/api/tasks", params={"token": "e2e-token"})
        assert r.status_code == 200
        assert r.json() == {"tasks": [], "next_cursor": None}

        # Publish TASK_INSTRUCTION_READY → storage listener persists the task
        task = _make_stock_task()
        state = app.state.app_state

        async def _pub() -> None:
            await state.bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
            await state.bus.wait_idle(timeout=3.0)

        assert client.portal is not None
        client.portal.call(_pub)

        # Task should now appear in GET /api/tasks
        r = client.get("/api/tasks", params={"token": "e2e-token"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["id"] == task.id


# ---------------------------------------------------------------------------
# 2. WebSocket receives event broadcast from bus
# ---------------------------------------------------------------------------


def test_e2e_ws_receives_event_from_bus() -> None:
    """WS client connected before bus.publish() receives the event payload."""
    settings = _make_settings("ws-token")
    broker = FakeBrokerClient()
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client, client.websocket_connect("/ws?token=ws-token") as ws:
        task = _make_stock_task("msg-e2e-ws")
        state = app.state.app_state

        async def _pub() -> None:
            await state.bus.publish(Event(Topics.TASK_CREATED, TaskPayload(task)))
            await state.bus.wait_idle(timeout=3.0)

        assert client.portal is not None
        client.portal.call(_pub)

        msg = json.loads(ws.receive_text())
        assert msg["type"] == Topics.TASK_CREATED
        assert msg["payload"]["task"]["id"] == task.id


# ---------------------------------------------------------------------------
# 3. Auth: missing token → 403
# ---------------------------------------------------------------------------


def test_e2e_auth_denied_without_token() -> None:
    """All REST endpoints return 403 when no token is presented."""
    settings = _make_settings()
    broker = FakeBrokerClient()
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        r = client.get("/api/tasks")
        assert r.status_code == 403

        r = client.get("/api/health")
        assert r.status_code == 403

        r = client.get("/api/stats/today")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 4. Multiple tasks published → paginated list
# ---------------------------------------------------------------------------


def test_e2e_multiple_tasks_listed() -> None:
    """Publish three tasks via bus; GET /api/tasks returns all three."""
    settings = _make_settings("multi-token")
    broker = FakeBrokerClient()
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    task_ids = ["msg-e2e-a", "msg-e2e-b", "msg-e2e-c"]
    tasks = [_make_stock_task(tid) for tid in task_ids]

    with TestClient(app) as client:
        state = app.state.app_state

        async def _pub_all() -> None:
            for t in tasks:
                await state.bus.publish(
                    Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(t))
                )
            await state.bus.wait_idle(timeout=5.0)

        assert client.portal is not None
        client.portal.call(_pub_all)

        r = client.get("/api/tasks", params={"token": "multi-token"})
        assert r.status_code == 200
        data = r.json()
        returned_ids = {t["id"] for t in data["tasks"]}
        assert returned_ids == set(task_ids)


# ---------------------------------------------------------------------------
# 5. GET /api/tasks/{task_id} returns full task
# ---------------------------------------------------------------------------


def test_e2e_get_single_task() -> None:
    """After persisting via bus, GET /api/tasks/{id} returns the full task."""
    settings = _make_settings("single-token")
    broker = FakeBrokerClient()
    app = create_app(settings=settings, broker_override=broker, skip_whop=True)
    app.dependency_overrides[get_settings] = lambda: settings

    task = _make_stock_task("msg-e2e-single")

    with TestClient(app) as client:
        state = app.state.app_state

        async def _pub() -> None:
            await state.bus.publish(
                Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task))
            )
            await state.bus.wait_idle(timeout=3.0)

        assert client.portal is not None
        client.portal.call(_pub)

        r = client.get(f"/api/tasks/{task.id}", params={"token": "single-token"})
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == task.id
        assert data["type"] == "stock"
        # The trader listener fires on TASK_INSTRUCTION_READY and submits an
        # order, so the status advances past INSTRUCTION_READY to PENDING.
        assert data["status"] in (
            Status.INSTRUCTION_READY.value,
            Status.SUBMITTING.value,
            Status.PENDING.value,
        )

        # Unknown task → 404
        r = client.get("/api/tasks/no-such-id", params={"token": "single-token"})
        assert r.status_code == 404
