"""Event-bus → persistence bridge.

``register_storage_listeners`` subscribes to all task lifecycle topics and
auto-persists the corresponding domain objects via ``repo.save_task`` /
``repo.append_push_event``.  No module outside ``app.storage`` needs to call
those repo functions directly.

Design note
-----------
``save_task`` and ``append_push_event`` commit internally, so each handler
opens its own session via ``session_scope``.  This is intentional for now;
a future refactor may move commit responsibility up to the listeners.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, TaskPushPayload, Topics
from app.storage.db import session_scope
from app.storage.repo import append_push_event, save_task

logger = logging.getLogger(__name__)

# Alias matching EventBus.Handler
_Handler = Callable[[Event], Awaitable[None]]


# ---------------------------------------------------------------------------
# Internal handler factories
# ---------------------------------------------------------------------------


def _persist_task_handler(
    factory: async_sessionmaker[AsyncSession],
) -> _Handler:
    """Return an async handler that persists ``payload.task`` to DB.

    Used by all ``task.*`` topics **except** ``task.push_event``.
    """

    async def _handler(event: Event) -> None:
        payload: TaskPayload = event.payload  # pyright: ignore[reportAssignmentType]
        async with session_scope(factory) as session:
            await save_task(session, payload.task)

    _handler.__name__ = f"_persist_task_handler[{factory!r}]"
    return _handler


def _persist_push_event_handler(
    factory: async_sessionmaker[AsyncSession],
) -> _Handler:
    """Return an async handler that persists both the task and the push event."""

    async def _handler(event: Event) -> None:
        payload: TaskPushPayload = event.payload  # pyright: ignore[reportAssignmentType]
        # Two separate sessions / commits to match repo's internal-commit design.
        async with session_scope(factory) as session:
            await save_task(session, payload.task)
        async with session_scope(factory) as session:
            await append_push_event(session, payload.push_event)

    _handler.__name__ = f"_persist_push_event_handler[{factory!r}]"
    return _handler


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_storage_listeners(
    bus: EventBus,
    session_factory: async_sessionmaker[AsyncSession],
) -> list[Callable[[], None]]:
    """Subscribe storage handlers to *bus*.

    Returns a list of unsubscribe callables; call each to detach the handler.
    """
    task_handler = _persist_task_handler(session_factory)
    push_handler = _persist_push_event_handler(session_factory)

    unsubs: list[Callable[[], None]] = [
        bus.subscribe(Topics.TASK_CREATED, task_handler),
        bus.subscribe(Topics.TASK_INSTRUCTION_READY, task_handler),
        bus.subscribe(Topics.TASK_PARSE_FAILED, task_handler),
        bus.subscribe(Topics.TASK_ORDER_SUBMITTED, task_handler),
        bus.subscribe(Topics.TASK_SUBMIT_FAILED, task_handler),
        bus.subscribe(Topics.TASK_STATUS_CHANGED, task_handler),
        bus.subscribe(Topics.TASK_PUSH_EVENT, push_handler),
    ]
    return unsubs
