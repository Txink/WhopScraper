"""WebSocket hub — EventBus → WS bridge (§7.2).

WebSocketHub:
- Subscribes to all task.* topics on the EventBus
- Converts domain payloads to JSON-ready dicts via schemas converters
- Broadcasts to all connected WebSocket clients
- Maintains a ring buffer of last BUFFER_SIZE events for ?since=<event_id> replay
- Handles ping/pong heartbeat from clients
- Cleans up dead connections on send failure

build_ws_router(hub, settings):
- Factory that returns an APIRouter with a /ws endpoint
- Auth: ?token=<APP_TOKEN>, else closes with code 1008
- Query params: token, since (optional)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.auth import ws_token_valid
from app.api.schemas import push_event_to_out, task_to_out
from app.core.config import Settings
from app.core.event_bus import Event, EventBus
from app.core.events import (
    ExecutionPayload,
    QuoteSnapshotPayload,
    TaskPayload,
    TaskPushPayload,
    Topics,
    WhopPagePayload,
)

logger = logging.getLogger(__name__)

BUFFER_SIZE = 500  # ring buffer for replay


@dataclass
class BufferedEvent:
    event_id: int
    type: str
    payload: dict[str, Any]  # JSON-serialisable, built once at broadcast time


class WebSocketHub:
    """Server-side WebSocket broadcaster.

    - Subscribes to EventBus for all task.* topics
    - Converts domain payloads to JSON-ready dicts
    - Broadcasts to all connected clients
    - Maintains ring buffer of last BUFFER_SIZE events for replay via ?since=
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._connections: set[WebSocket] = set()
        self._buffer: deque[BufferedEvent] = deque(maxlen=BUFFER_SIZE)
        self._next_event_id: int = 0
        self._unsubs: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()  # guards _connections set mutations

    async def register_listeners(self) -> None:
        """Subscribe to all bridged topics. Call once at app startup."""
        topics_to_bridge = [
            Topics.TASK_CREATED,
            Topics.TASK_INSTRUCTION_READY,
            Topics.TASK_PARSE_FAILED,
            Topics.TASK_ORDER_SUBMITTED,
            Topics.TASK_SUBMIT_FAILED,
            Topics.TASK_PUSH_EVENT,
            Topics.TASK_STATUS_CHANGED,
            Topics.SYSTEM_CONNECTION_CHANGED,
            Topics.WHOP_PAGE_CHANGED,
            Topics.QUOTE_SNAPSHOT,
            Topics.EXECUTION_UPDATE,
        ]
        for t in topics_to_bridge:
            unsub = self._bus.subscribe(t, self._on_bus_event)
            self._unsubs.append(unsub)

    async def _on_bus_event(self, event: Event) -> None:
        """Convert Event → BufferedEvent, append to ring buffer, broadcast."""
        payload_dict = self._payload_to_dict(event)
        if payload_dict is None:
            return  # unsupported payload type — ignore silently

        self._next_event_id += 1
        buffered = BufferedEvent(
            event_id=self._next_event_id,
            type=event.topic,
            payload=payload_dict,
        )
        self._buffer.append(buffered)
        await self._broadcast(buffered)

    @staticmethod
    def _payload_to_dict(event: Event) -> dict[str, Any] | None:
        """Translate Event.payload → serialisable dict.

        Returns None for unsupported payload types (they are silently dropped).
        """
        p = event.payload
        if isinstance(p, TaskPushPayload):
            return {
                "task": task_to_out(p.task).model_dump(mode="json"),
                "push_event": push_event_to_out(p.push_event).model_dump(mode="json"),
            }
        if isinstance(p, TaskPayload):
            return {"task": task_to_out(p.task).model_dump(mode="json")}
        if isinstance(p, QuoteSnapshotPayload):
            # ``quote`` already carries the QuoteOut shape from the broker
            # adapter (last_done, open, high, low, volume, turnover,
            # trade_session). Frontend writes it straight into quotesStore
            # under ``symbol`` — no client-side conversion needed.
            return {"symbol": p.symbol, "quote": p.quote}
        if isinstance(p, ExecutionPayload):
            # Shape mirrors ExecutionOut so the frontend's executions store
            # can ingest push-driven rows without a converter. Drives the
            # per-card Day P/L update.
            return {
                "order_id": p.order_id,
                "symbol": p.symbol,
                "ticker": p.ticker,
                "side": p.side,
                "qty": p.qty,
                "price": p.price,
                "ts": p.ts,
            }
        if isinstance(p, WhopPagePayload):
            return {"action": p.action, "page": p.page_dict}
        # Pass-through for dict payloads (e.g. system.connection_changed)
        if isinstance(p, dict):
            return p
        return None

    async def _broadcast(self, buffered: BufferedEvent) -> None:
        """Send buffered event to all current connections; remove dead ones."""
        async with self._lock:
            conns = list(self._connections)

        message = json.dumps(
            {
                "event_id": buffered.event_id,
                "type": buffered.type,
                "payload": buffered.payload,
            }
        )
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception as exc:
                logger.warning("ws send failed: %s", exc)
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)

    async def handle_connection(self, websocket: WebSocket, since: int | None = None) -> None:
        """Per-connection handler.

        1. Add to connection set
        2. Optionally replay buffered events > since
        3. Loop to handle ping/pong (and detect disconnect)
        4. Remove from connection set on exit
        """
        async with self._lock:
            self._connections.add(websocket)
        try:
            # Replay buffered events after the requested cursor
            if since is not None:
                for b in list(self._buffer):
                    if b.event_id > since:
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event_id": b.event_id,
                                    "type": b.type,
                                    "payload": b.payload,
                                }
                            )
                        )

            # Main receive loop — keep connection alive, handle ping
            while True:
                try:
                    data = await websocket.receive_text()
                except WebSocketDisconnect:
                    break
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_text(json.dumps({"type": "pong"}))
                except json.JSONDecodeError:
                    pass  # ignore malformed input
        finally:
            async with self._lock:
                self._connections.discard(websocket)

    async def close(self) -> None:
        """Shutdown: unsubscribe all listeners and close all open connections."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

        async with self._lock:
            conns = list(self._connections)
            self._connections.clear()

        for ws in conns:
            with contextlib.suppress(Exception):
                await ws.close()


def build_ws_router(hub: WebSocketHub, settings: Settings) -> APIRouter:
    """Return an APIRouter containing the /ws endpoint."""
    router = APIRouter()

    @router.websocket("/ws")
    async def websocket_endpoint(
        websocket: WebSocket,
        token: str | None = None,
        since: int | None = None,
    ) -> None:
        # Reject unauthenticated connections before accepting
        if not await ws_token_valid(token, settings):
            await websocket.close(code=1008, reason="invalid or missing token")
            return
        await websocket.accept()
        await hub.handle_connection(websocket, since=since)

    return router
