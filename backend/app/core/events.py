"""Shared event topic constants and typed payload dataclasses.

Topics
------
Centralises all ``EventBus`` topic strings so the rest of the codebase can
import a single ``Topics`` class instead of scattering string literals.

Payload types
-------------
``MessagePayload``, ``TaskPayload`` and ``TaskPushPayload`` are frozen
dataclasses (in-process only; no serialisation boundary, so Pydantic is not
needed).

Convention:
- ``message.received`` carries a ``MessagePayload``.
- every ``task.*`` event except ``task.push_event`` carries a ``TaskPayload``.
- ``task.push_event`` carries a ``TaskPushPayload``.
- ``whop.page_changed`` carries a ``WhopPagePayload``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.message import Message
from app.domain.push_event import PushEvent
from app.domain.task import Task


class Topics:
    MESSAGE_RECEIVED = "message.received"
    TASK_CREATED = "task.created"
    TASK_INSTRUCTION_READY = "task.instruction_ready"
    TASK_PARSE_FAILED = "task.parse_failed"
    TASK_ORDER_SUBMITTED = "task.order_submitted"
    TASK_SUBMIT_FAILED = "task.submit_failed"
    TASK_PUSH_EVENT = "task.push_event"
    TASK_STATUS_CHANGED = "task.status_changed"
    SYSTEM_CONNECTION_CHANGED = "system.connection_changed"
    WHOP_PAGE_CHANGED = "whop.page_changed"


@dataclass(frozen=True)
class MessagePayload:
    """Payload for ``message.received`` events.

    ``is_historical`` is set by the listener when ``message.posted_at <
    listener.started_at`` (i.e., the message existed in the channel
    before this listener session began). The trader uses it together
    with the per-page ``block_historical_messages`` setting to decide
    whether to SKIP ordering.
    """

    message: Message
    is_historical: bool = False


@dataclass(frozen=True)
class TaskPayload:
    """Payload for all ``task.*`` events except ``task.push_event``."""

    task: Task


@dataclass(frozen=True)
class TaskPushPayload:
    """Payload for ``task.push_event`` events."""

    task: Task
    push_event: PushEvent


@dataclass(frozen=True)
class WhopPagePayload:
    """Payload for ``whop.page_changed`` events.

    Emitted whenever the WhopRegistry mutates an entry (add/remove/restart/
    start/stop/settings update). ``page_dict`` is the JSON-ready dict produced by
    ``schemas.whop_page_to_out(...).model_dump(mode="json")`` at publish time
    so the downstream WS bridge can forward it verbatim.
    """

    action: str  # "added" | "removed" | "restarted" | "started" | "stopped" | "settings_updated"
    page_dict: dict[str, Any]
