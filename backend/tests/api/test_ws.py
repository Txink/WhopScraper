"""Tests for app.api.ws — WebSocketHub + /ws endpoint.

Testing strategy
----------------
TestClient runs the ASGI app in a background thread via anyio and exposes a
``portal`` attribute (``anyio.from_thread.BlockingPortal``) when used as a
context manager.  We use ``client.portal.call(coro_fn)`` to schedule async
bus.publish() calls on the server's event loop, then ``bus.wait_idle()`` to
drain them before reading the WebSocket message.

For tests that don't need the bus integration (ping/pong, auth, replay) we
call ``hub._on_bus_event`` directly via the portal — this is simpler and still
exercises the full Hub code path for those specific behaviours.

For the buffer-overflow test (test #7) we monkey-patch ``BUFFER_SIZE`` on the
module and create a fresh hub with a small buffer so the test completes in
milliseconds.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.ws import WebSocketHub, build_ws_router
from app.core.config import Settings
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
_TOKEN = "test-token-WS"


def _make_message(msg_id: str = "msg-1") -> Message:
    return Message(
        id=msg_id,
        content="buy AAPL 100 shares",
        raw_content="buy AAPL 100 shares",
        author="trader_alice",
        posted_at=_NOW,
        received_at=_NOW,
        source="stock",
    )


def _make_task(task_id: str = "msg-1") -> Task:
    return Task(
        id=task_id,
        type="stock",
        status=Status.INSTRUCTION_READY,
        message=_make_message(task_id),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_task_event(task_id: str = "msg-1", topic: str = Topics.TASK_CREATED) -> Event:
    return Event(topic=topic, payload=TaskPayload(task=_make_task(task_id)))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def ws_app() -> tuple[FastAPI, EventBus, WebSocketHub, Settings]:
    """Return (app, bus, hub, settings) with startup hook registered."""
    bus = EventBus()
    settings = Settings(app_token=_TOKEN)
    hub = WebSocketHub(bus)

    app = FastAPI()
    app.include_router(build_ws_router(hub, settings))

    @app.on_event("startup")
    async def _startup() -> None:
        await hub.register_listeners()

    return app, bus, hub, settings


# ---------------------------------------------------------------------------
# 1. Auth: missing token → 1008 close
# ---------------------------------------------------------------------------


def test_ws_rejects_missing_token(ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings]) -> None:
    app, _bus, _hub, _settings = ws_app
    client = TestClient(app, raise_server_exceptions=False)
    # server closes before accept(); testclient raises WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws"):
        pass


# ---------------------------------------------------------------------------
# 2. Auth: wrong token → 1008 close
# ---------------------------------------------------------------------------


def test_ws_rejects_wrong_token(ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings]) -> None:
    app, _bus, _hub, _settings = ws_app
    client = TestClient(app, raise_server_exceptions=False)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws?token=wrong-token"):
        pass


# ---------------------------------------------------------------------------
# 3. Auth: correct token → connected
# ---------------------------------------------------------------------------


def test_ws_accepts_correct_token(ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings]) -> None:
    app, _bus, _hub, _settings = ws_app
    client = TestClient(app)
    with client.websocket_connect(f"/ws?token={_TOKEN}") as ws:
        # Verify bi-directional communication
        ws.send_text(json.dumps({"type": "ping"}))
        msg = json.loads(ws.receive_text())
        assert msg == {"type": "pong"}


# ---------------------------------------------------------------------------
# 4. Receives broadcast event when bus publishes
# ---------------------------------------------------------------------------


def test_ws_receives_broadcast_event(
    ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings],
) -> None:
    app, bus, _hub, _settings = ws_app
    client = TestClient(app)

    with client, client.websocket_connect(f"/ws?token={_TOKEN}") as ws:

        async def _pub() -> None:
            await bus.publish(_make_task_event())
            await bus.wait_idle(timeout=2.0)

        assert client.portal is not None
        client.portal.call(_pub)

        msg = json.loads(ws.receive_text())
        assert msg["event_id"] == 1
        assert msg["type"] == Topics.TASK_CREATED
        assert "task" in msg["payload"]


# ---------------------------------------------------------------------------
# 5. Event IDs increment monotonically
# ---------------------------------------------------------------------------


def test_ws_event_id_increments(ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings]) -> None:
    app, bus, _hub, _settings = ws_app
    client = TestClient(app)

    with client, client.websocket_connect(f"/ws?token={_TOKEN}") as ws:

        async def _pub_three() -> None:
            for i in range(3):
                await bus.publish(_make_task_event(f"msg-{i}"))
            await bus.wait_idle(timeout=2.0)

        assert client.portal is not None
        client.portal.call(_pub_three)

        received_ids = []
        for _ in range(3):
            msg = json.loads(ws.receive_text())
            received_ids.append(msg["event_id"])

        assert received_ids == [1, 2, 3]


# ---------------------------------------------------------------------------
# 6. Replay ?since=<event_id> returns only later events
# ---------------------------------------------------------------------------


def test_ws_replay_from_since(ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings]) -> None:
    app, bus, _hub, _settings = ws_app
    client = TestClient(app)

    # First: publish 5 events (no ws connected — events go to buffer only)
    with client:

        async def _pub_five() -> None:
            for i in range(5):
                await bus.publish(_make_task_event(f"msg-{i}"))
            await bus.wait_idle(timeout=2.0)

        assert client.portal is not None
        client.portal.call(_pub_five)

        # Now connect with since=2 — should only get events 3, 4, 5
        with client.websocket_connect(f"/ws?token={_TOKEN}&since=2") as ws:
            replayed = []
            for _ in range(3):
                msg = json.loads(ws.receive_text())
                replayed.append(msg["event_id"])

            assert replayed == [3, 4, 5]


# ---------------------------------------------------------------------------
# 7. Buffer overflow: only last BUFFER_SIZE events are replayed
# ---------------------------------------------------------------------------


def test_ws_replay_respects_buffer_overflow(
    ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish 50 events into a hub with maxlen=30; replay from 0 → 30 events."""
    import app.api.ws as ws_module

    _app, _bus, _hub_orig, settings = ws_app

    # Create a fresh hub with a tiny buffer (30)
    small_buffer_size = 30
    monkeypatch.setattr(ws_module, "BUFFER_SIZE", small_buffer_size)

    bus2 = EventBus()
    hub2 = WebSocketHub.__new__(WebSocketHub)
    hub2._bus = bus2
    hub2._connections = set()
    hub2._buffer = deque(maxlen=small_buffer_size)
    hub2._next_event_id = 0
    hub2._unsubs = []
    hub2._lock = asyncio.Lock()

    app2 = FastAPI()
    app2.include_router(build_ws_router(hub2, settings))

    @app2.on_event("startup")
    async def _startup2() -> None:
        await hub2.register_listeners()

    total_events = 50
    client2 = TestClient(app2)

    with client2:

        async def _pub_many() -> None:
            for i in range(total_events):
                await bus2.publish(_make_task_event(f"msg-{i}"))
            await bus2.wait_idle(timeout=5.0)

        assert client2.portal is not None
        client2.portal.call(_pub_many)

        # Connect with since=0 — should receive exactly small_buffer_size events
        # (the last 30: event IDs 21–50)
        with client2.websocket_connect(f"/ws?token={_TOKEN}&since=0") as ws:
            replayed = []
            for _ in range(small_buffer_size):
                msg = json.loads(ws.receive_text())
                replayed.append(msg["event_id"])

            assert len(replayed) == small_buffer_size
            # First replayed event_id should be total_events - small_buffer_size + 1
            assert replayed[0] == total_events - small_buffer_size + 1
            assert replayed[-1] == total_events


# ---------------------------------------------------------------------------
# 8. Ping / pong heartbeat
# ---------------------------------------------------------------------------


def test_ws_ping_pong(ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings]) -> None:
    app, _bus, _hub, _settings = ws_app
    client = TestClient(app)
    with client.websocket_connect(f"/ws?token={_TOKEN}") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        msg = json.loads(ws.receive_text())
        assert msg == {"type": "pong"}


# ---------------------------------------------------------------------------
# 9. Broadcast reaches all connected clients
# ---------------------------------------------------------------------------


def test_ws_broadcast_to_multiple_clients(
    ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings],
) -> None:
    app, bus, _hub, _settings = ws_app
    client = TestClient(app)

    with client:
        ws1_ctx = client.websocket_connect(f"/ws?token={_TOKEN}")
        ws2_ctx = client.websocket_connect(f"/ws?token={_TOKEN}")
        ws1 = ws1_ctx.__enter__()
        ws2 = ws2_ctx.__enter__()
        try:

            async def _pub() -> None:
                await bus.publish(_make_task_event())
                await bus.wait_idle(timeout=2.0)

            assert client.portal is not None
            client.portal.call(_pub)

            msg1 = json.loads(ws1.receive_text())
            msg2 = json.loads(ws2.receive_text())

            assert msg1["event_id"] == 1
            assert msg2["event_id"] == 1
            assert msg1["type"] == Topics.TASK_CREATED
            assert msg2["type"] == Topics.TASK_CREATED
        finally:
            ws2_ctx.__exit__(None, None, None)
            ws1_ctx.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# 10. hub.close() disconnects all clients
# ---------------------------------------------------------------------------


def test_ws_hub_close_removes_all_connections(
    ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings],
) -> None:
    """After hub.close(), the connection set is empty."""
    app, _bus, hub, _settings = ws_app
    client = TestClient(app)

    with client:
        ws1_ctx = client.websocket_connect(f"/ws?token={_TOKEN}")
        ws2_ctx = client.websocket_connect(f"/ws?token={_TOKEN}")
        ws1_ctx.__enter__()
        ws2_ctx.__enter__()
        try:
            # Verify both connected
            assert len(hub._connections) == 2

            async def _close() -> None:
                await hub.close()

            assert client.portal is not None
            client.portal.call(_close)

            # After close, connection set cleared
            assert len(hub._connections) == 0
        finally:
            ws2_ctx.__exit__(None, None, None)
            ws1_ctx.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# 11. Bridges whop.page_changed bus events to WS clients
# ---------------------------------------------------------------------------


def test_whop_page_changed_broadcast(
    ws_app: tuple[FastAPI, EventBus, WebSocketHub, Settings],
) -> None:
    """Bus publish WHOP_PAGE_CHANGED → WS clients receive event."""
    from app.core.events import WhopPagePayload

    app, bus, _hub, _settings = ws_app
    client = TestClient(app)

    with client, client.websocket_connect(f"/ws?token={_TOKEN}") as ws:
        page_dict = {
            "id": "p1",
            "url": "u",
            "source": "stock",
            "name": "n",
            "added_at": "2026-04-25T00:00:00+00:00",
            "settings": {
                "dedupe_processed_messages": True,
                "price_deviation_tolerance": 1.0,
                "tickers": {},
            },
            "running": True,
            "started_at": None,
            "last_poll_at": None,
            "messages_published": 0,
            "last_error": None,
        }

        async def _pub() -> None:
            await bus.publish(
                Event(
                    topic=Topics.WHOP_PAGE_CHANGED,
                    payload=WhopPagePayload(action="settings_updated", page_dict=page_dict),
                )
            )
            await bus.wait_idle(timeout=2.0)

        assert client.portal is not None
        client.portal.call(_pub)

        msg = json.loads(ws.receive_text())
        assert msg["type"] == "whop.page_changed"
        assert msg["payload"]["action"] == "settings_updated"
        assert msg["payload"]["page"]["id"] == "p1"
