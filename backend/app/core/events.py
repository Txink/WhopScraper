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
- ``chat.message_received`` carries a ``ChatMessagePayload``.
- ``chat.message_stored`` carries a ``ChatMessageStoredPayload``.
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
    # Streaming broker quote — one Event per PushQuote callback. Payload
    # is a ``QuoteSnapshotPayload`` containing the symbol + the same
    # ``QuoteOut``-shaped dict as ``get_quote``. WebSocketHub bridges this
    # topic so the frontend can rebuild the per-card last_done in real
    # time instead of waiting on a 15s poll.
    QUOTE_SNAPSHOT = "quote.snapshot"
    # Streaming broker execution / fill. Fired by SubscriptionManager when
    # an order transitions to a Filled / PartialFilled status. Payload is
    # an ``ExecutionPayload`` (matches ExecutionOut on the wire). Drives
    # the per-card Day P/L live without re-polling /today_executions.
    EXECUTION_UPDATE = "execution.update"
    # Chat pipeline (pages whose source == "chat"). RECEIVED is fired by
    # ``whop.listener`` instead of ``MESSAGE_RECEIVED`` and carries the
    # extracted Message + page_id; STORED is fired by ``chat_writer``
    # after the row is persisted so the WS bridge can push it to the
    # frontend ChatBoardPanel.
    CHAT_MESSAGE_RECEIVED = "chat.message_received"
    CHAT_MESSAGE_STORED = "chat.message_stored"
    ORDER_CHANGED = "order.changed"


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
class ChatMessagePayload:
    """Payload for ``chat.message_received`` events.

    Emitted by listeners for pages whose source is "chat". Carries the
    full extracted :class:`Message` (including the optional ``quoted``
    nested message) plus the ``page_id`` so the writer knows where to
    persist the row without re-resolving the page from the URL.
    """

    page_id: str
    message: Message
    is_historical: bool = False


@dataclass(frozen=True)
class ChatMessageStoredPayload:
    """Payload for ``chat.message_stored`` events.

    Emitted after a non-historical chat message is persisted. WS bridges
    this to the frontend so it can append the message to the active
    page's in-memory cache and re-run card grouping.
    """

    page_id: str
    message_id: str


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
class QuoteSnapshotPayload:
    """Payload for ``quote.snapshot`` events.

    One per PushQuote callback from the broker. ``quote`` carries the
    same shape as ``QuoteOut`` (last_done, prev_close, open, high, low,
    volume, turnover, change, change_pct, trade_session) so the frontend
    can swap it into its ``quotesStore`` directly without a converter.
    """

    symbol: str
    quote: dict[str, Any]


@dataclass(frozen=True)
class ExecutionPayload:
    """Payload for ``execution.update`` events.

    One per fill event (status ∈ {Filled, PartialFilled}). Shape matches
    ``ExecutionOut``'s wire form: order_id, symbol, ticker, side, qty,
    price, ts (ISO-8601 string). Frontend upserts into the executions
    store keyed by order_id; PositionCard reads it to recompute Day P/L
    without re-polling /today_executions.
    """

    order_id: str
    symbol: str
    ticker: str
    side: str  # "BUY" | "SELL"
    qty: int
    price: float
    ts: str | None


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
