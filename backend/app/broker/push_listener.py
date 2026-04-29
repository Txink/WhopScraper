"""PushListener —— Bridge broker SDK push callbacks → TASK_PUSH_EVENT bus events.

Design
------
Broker SDK fires order-change push events on its own thread via a registered
callback.  ``PushListener.start()`` captures the running asyncio event-loop and
schedules ``_handle_raw_push`` on it using ``asyncio.run_coroutine_threadsafe``,
keeping all domain logic safely in async context.

Push routing
------------
On each push, look up the Task by ``order_id`` in the DB. If found, build the
PushEvent and publish it. If NOT found, the task hasn't been registered yet
(the trader is still in the middle of its submit → save_task path, or the
push belongs to a foreign order). Buffer the raw push under ``order_id`` and
expect the trader to call :meth:`replay_for_order` once it commits the
order_id to the DB.

Buffered pushes that age past :attr:`BUFFER_TTL_S` are dropped on the next
GC sweep with a WARN log — protects against unbounded growth from foreign
orders (mobile app, other processes) that the trader will never claim.

State mapping
-------------
LongPort ``OrderStatus`` is a C-extension enum whose instances have no ``.name``
or ``.value`` attributes.  We extract the status label via
``repr(status).split(".")[-1]`` (e.g. ``"OrderStatus.PartialFilled"`` → ``"PartialFilled"``).
When the raw event carries a plain string (test doubles) we use that directly.
Unknown statuses default to ``PushState.FAILED`` with a note.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.broker_client import BrokerClient
from app.broker.order_id_norm import normalize_broker_order_id
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPushPayload, Topics
from app.domain.push_event import PushEvent, PushState
from app.domain.task import Task
from app.storage.repo import load_task_by_order_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SDK status → PushState mapping
# ---------------------------------------------------------------------------
# LongPort ``OrderStatus`` label → our PushState
_SDK_STATUS_MAP: dict[str, PushState] = {
    # Active / in-flight
    "New": PushState.NEW,
    "WaitToNew": PushState.NEW,
    "NotReported": PushState.SUBMITTED,
    "WaitToReplace": PushState.SUBMITTED,
    "PendingReplace": PushState.SUBMITTED,
    "ReplacedNotReported": PushState.SUBMITTED,
    "ProtectedNotReported": PushState.SUBMITTED,
    "VarietiesNotReported": PushState.SUBMITTED,
    "Replaced": PushState.MODIFIED,
    "PendingCancel": PushState.MODIFIED,
    "WaitToCancel": PushState.MODIFIED,
    "PartialFilled": PushState.PARTIAL,
    "PartialWithdrawal": PushState.PARTIAL,
    "Filled": PushState.FILLED,
    "Canceled": PushState.CANCELLED,
    "Expired": PushState.CANCELLED,
    "Rejected": PushState.REJECTED,
    "Unknown": PushState.FAILED,
}

# Also support upper-case string variants from test doubles
_SDK_STATUS_MAP_UPPER: dict[str, PushState] = {k.upper(): v for k, v in _SDK_STATUS_MAP.items()}

# Extra plain-string aliases that test doubles may use
_PLAIN_STRING_MAP: dict[str, PushState] = {
    "NEW": PushState.NEW,
    "SUBMITTED": PushState.SUBMITTED,
    "MODIFIED": PushState.MODIFIED,
    "PARTIAL": PushState.PARTIAL,
    "FILLED": PushState.FILLED,
    "CANCELLED": PushState.CANCELLED,
    "REJECTED": PushState.REJECTED,
    "FAILED": PushState.FAILED,
}


def _extract_status_label(status: Any) -> str:
    """Return the bare label string from a broker status value.

    Handles:
    - LongPort ``OrderStatus`` instances  → ``repr`` is ``"OrderStatus.Filled"``
    - Python ``enum.Enum`` sub-classes    → use ``.name``
    - Plain strings                       → returned as-is (uppercased)
    """
    if status is None:
        return ""
    if isinstance(status, Enum):
        return status.name
    raw_repr = repr(status)
    if "." in raw_repr:
        # e.g. "OrderStatus.Filled" → "Filled"
        return raw_repr.split(".")[-1]
    return str(status).strip()


def _map_sdk_status(status: Any) -> tuple[PushState, str | None]:
    """Map SDK status to ``(PushState, note_or_None)``.

    Returns ``(PushState.FAILED, note)`` for unrecognised statuses.
    """
    label = _extract_status_label(status)

    # 1. Try original-case SDK labels
    if label in _SDK_STATUS_MAP:
        return _SDK_STATUS_MAP[label], None

    # 2. Try upper-case SDK labels
    if label.upper() in _SDK_STATUS_MAP_UPPER:
        return _SDK_STATUS_MAP_UPPER[label.upper()], None

    # 3. Try plain-string PushState names (test doubles)
    if label.upper() in _PLAIN_STRING_MAP:
        return _PLAIN_STRING_MAP[label.upper()], None

    # Unknown
    note = f"unknown status: {label}"
    logger.warning("PushListener: %s", note)
    return PushState.FAILED, note


# ---------------------------------------------------------------------------
# Payload serialisation helpers
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> int | None:
    """Coerce value to int, returning None on failure."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    """Coerce value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _serialise_value(v: Any) -> Any:
    """Convert a single value to a JSON-safe primitive."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, datetime):
        return v.isoformat()
    # LongPort uses custom types (Decimal-like, enums without .value via repr)
    raw = repr(v)
    if "." in raw:
        # e.g. "OrderStatus.Filled" → "Filled"
        return raw.split(".")[-1]
    return str(v)


def _to_payload_dict(raw: Any) -> dict[str, Any]:
    """Convert a SDK push event object to a JSON-serialisable dict.

    Strategy:
      1. ``vars()`` for plain Python objects (test doubles, dataclasses).
         Note: on a C-extension object ``vars(obj)`` may NOT raise — it can
         return a non-dict (the ``__dict__`` *property* itself), so the
         result must be type-checked before iterating.
      2. ``dir()`` introspection for C-extension objects (e.g. LongPort
         ``PushOrderChanged``) which expose attributes as Rust-backed
         properties rather than a Python ``__dict__``.
      3. ``repr`` as the final fallback.
    """
    # 1. Plain-Python fast path
    try:
        candidate = vars(raw)
        if isinstance(candidate, dict):
            pairs = list(candidate.items())
            result: dict[str, Any] = {}
            for k, v in pairs:
                if k.startswith("_"):
                    continue
                result[str(k)] = _serialise_value(v)
            return result
    except TypeError:
        pass

    # 2. C-extension fallback via dir()
    pairs2: list[tuple[str, Any]] = []
    for name in dir(raw):
        if name.startswith("_"):
            continue
        try:
            val = getattr(raw, name)
        except Exception:  # noqa: BLE001
            continue
        if callable(val):
            continue
        pairs2.append((name, val))
    if pairs2:
        return {k: _serialise_value(v) for k, v in pairs2}

    # 3. Last-resort repr
    return {"_raw": repr(raw)}


# ---------------------------------------------------------------------------
# PushEvent construction
# ---------------------------------------------------------------------------


def _extract_broker_msg(raw: Any) -> str | None:
    """Pull the broker-supplied message off the raw push event, if any.

    LongPort's ``PushOrderChanged.msg`` carries the human-readable rejection
    reason (e.g. ``"订单金额超出最大购买力"``) on Rejected events. Other
    states usually have an empty msg.
    """
    msg = getattr(raw, "msg", None)
    if not isinstance(msg, str):
        return None
    msg = msg.strip()
    return msg or None


def _build_push_event(raw: Any, task: Task) -> PushEvent:
    """Build a ``PushEvent`` from a raw SDK event and the associated ``Task``.

    Delta logic:
    - ``delta_qty``: current cumulative qty minus highest prior cumulative qty
      from already-recorded push events.  Only set when positive.
    - ``delta_price``: None — SDK's ``executed_price`` is a weighted average,
      not the fill price of this specific batch.

    ``note`` priority:
    1. Broker-supplied ``raw.msg`` if non-empty (rejection reason etc).
    2. Otherwise the unknown-status warning emitted by ``_map_sdk_status``.
    """
    state, status_note = _map_sdk_status(getattr(raw, "status", None))

    cum_qty = _to_int(getattr(raw, "executed_quantity", None))
    cum_avg = _to_float(getattr(raw, "executed_price", None))

    # Highest prior cumulative from earlier push events on this task
    prior_cum = 0
    for prior in task.push_events:
        if prior.cumulative_qty is not None and prior.cumulative_qty > prior_cum:
            prior_cum = prior.cumulative_qty

    delta_qty: int | None = None
    if cum_qty is not None and cum_qty > prior_cum:
        delta_qty = cum_qty - prior_cum

    # Prefer broker-supplied message — that's where the rejection reason lives.
    note = _extract_broker_msg(raw) or status_note

    return PushEvent(
        id=uuid.uuid4().hex,
        task_id=task.id,
        order_id=task.order_id or "",
        state=state,
        received_at=datetime.now(UTC),
        payload=_to_payload_dict(raw),
        delta_qty=delta_qty,
        delta_price=None,
        cumulative_qty=cum_qty,
        cumulative_avg_price=cum_avg,
        note=note,
    )


# ---------------------------------------------------------------------------
# PushListener
# ---------------------------------------------------------------------------


class PushListener:
    """Bridge broker push callbacks → TASK_PUSH_EVENT bus events.

    Thread-safety
    -------------
    ``start()`` must be called from an async context (i.e. inside a running
    event loop).  It captures the loop reference at that time.  The SDK then
    fires callbacks on its own thread; ``_sync_callback`` uses
    ``asyncio.run_coroutine_threadsafe`` to hop back onto the captured loop.

    Buffering contract
    ------------------
    Pushes whose ``order_id`` is not yet bound to a Task in the DB are held
    in :attr:`_buffer` (a per-order_id list of raw pushes). The trader is
    expected to call :meth:`replay_for_order` once it has committed the
    binding, draining the buffer in arrival order. Entries older than
    :attr:`BUFFER_TTL_S` are GC'd on the next push arrival to bound memory.
    """

    #: Maximum age (seconds) for a buffered push before it is dropped with
    #: a WARN log. Tuned so a normal trader submit (~120ms broker call +
    #: save_task) finishes well within this window, while genuinely foreign
    #: pushes (mobile-app orders, other processes) don't pile up forever.
    BUFFER_TTL_S = 60.0

    def __init__(
        self,
        bus: EventBus,
        client: BrokerClient,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._bus = bus
        self._client = client
        self._session_factory = session_factory
        self._loop: asyncio.AbstractEventLoop | None = None
        # order_id -> [(monotonic_ts, raw_push), ...] in arrival order.
        self._buffer: dict[str, list[tuple[float, Any]]] = {}
        # Indirected for test injection. Keep monotonic so manual clock
        # changes (e.g. NTP) cannot resurrect or expire entries unexpectedly.
        self._clock: Callable[[], float] = time.monotonic

    def start(self) -> None:
        """Subscribe to broker push.  Must be called from a running event loop."""
        loop = asyncio.get_running_loop()
        self._loop = loop

        def _sync_callback(raw: Any) -> None:
            # Runs on SDK thread — marshal to async loop.
            asyncio.run_coroutine_threadsafe(self._handle_raw_push(raw), loop)

        self._client.subscribe_order_push(_sync_callback)
        logger.info("PushListener started — subscribed to broker order push")

    # ------------------------------------------------------------------ #
    # Buffer introspection (test-only)                                    #
    # ------------------------------------------------------------------ #

    def buffered_count(self, order_id: str) -> int:
        """Return the number of buffered pushes for ``order_id`` (0 if none)."""
        oid = normalize_broker_order_id(order_id)
        if not oid:
            return 0
        return len(self._buffer.get(oid, []))

    # ------------------------------------------------------------------ #
    # Core handlers                                                       #
    # ------------------------------------------------------------------ #

    async def _handle_raw_push(self, raw: Any) -> None:
        """Async handler.  DB hit → publish; miss → buffer for later replay."""
        order_id: str = normalize_broker_order_id(getattr(raw, "order_id", None))
        sdk_status = getattr(raw, "status", None)
        if not order_id:
            logger.warning(
                "PushListener: received push with no order_id — skipping; raw=%r",
                repr(raw)[:200],
            )
            return

        logger.info(
            "PushListener: handling push order_id=%s sdk_status=%r",
            order_id,
            sdk_status,
        )

        async with self._session_factory() as session:
            task = await load_task_by_order_id(session, order_id)

        if task is not None:
            await self._publish_push(raw, task)
            return

        # No task yet — trader may still be mid-submit, or this is a foreign
        # order. Buffer it and let the trader call replay_for_order once it
        # commits the binding. Stale entries are dropped here too so a flood
        # of foreign pushes can't grow the buffer indefinitely.
        self._gc_buffer()
        self._buffer.setdefault(order_id, []).append((self._clock(), raw))
        logger.info(
            "PushListener: no Task in DB for order_id=%s — buffered (size=%d) "
            "awaiting replay_for_order; sdk_status=%r",
            order_id,
            len(self._buffer[order_id]),
            sdk_status,
        )

    async def replay_for_order(self, order_id: str) -> int:
        """Drain buffered pushes for ``order_id``; publish each as TASK_PUSH_EVENT.

        Called by the trader after ``save_task`` commits the order_id↔task_id
        binding to the DB. Returns the number of pushes drained.
        """
        oid = normalize_broker_order_id(order_id)
        if not oid:
            return 0

        # Sweep first so any expired entries are dropped before we drain
        # (keeps "buffered then forgotten" pushes from being silently
        # processed minutes after they arrived).
        self._gc_buffer()
        entries = self._buffer.pop(oid, [])
        if not entries:
            return 0

        logger.info(
            "PushListener: replaying %d buffered push(es) for order_id=%s",
            len(entries),
            oid,
        )
        published = 0
        for _ts, raw in entries:
            async with self._session_factory() as session:
                task = await load_task_by_order_id(session, oid)
            if task is None:
                # Trader claimed this order but the DB row is gone (e.g. the
                # task was deleted between commit and replay). Nothing useful
                # to do but warn — the push event has nowhere to attach.
                logger.warning(
                    "PushListener: replay_for_order=%s drained 1 buffered push "
                    "but DB has no matching task — dropping; sdk_status=%r",
                    oid,
                    getattr(raw, "status", None),
                )
                continue
            await self._publish_push(raw, task)
            published += 1
        return published

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #

    async def _publish_push(self, raw: Any, task: Task) -> None:
        """Build and publish a TASK_PUSH_EVENT for the given raw + task."""
        logger.info(
            "PushListener: task loaded id=%s prior_status=%s prior_push_count=%d",
            task.id,
            task.status.value,
            len(task.push_events),
        )

        evt = _build_push_event(raw, task)
        task.append_push_event(evt)

        # Surface broker-side rejection / failure reason on the Task itself
        # so the UI can show "REJECTED · 订单金额超出最大购买力" directly,
        # and not just on the individual push event.
        if evt.state in (PushState.REJECTED, PushState.FAILED) and evt.note:
            task.reject_reason = evt.note

        await self._bus.publish(
            Event(
                topic=Topics.TASK_PUSH_EVENT,
                payload=TaskPushPayload(task=task, push_event=evt),
            )
        )
        logger.info(
            "PushListener: published TASK_PUSH_EVENT task_id=%s new_state=%s "
            "reject_reason=%r delta_qty=%s cum_qty=%s",
            task.id,
            evt.state.name,
            task.reject_reason,
            evt.delta_qty,
            evt.cumulative_qty,
        )

    def _gc_buffer(self) -> None:
        """Drop buffered entries older than :attr:`BUFFER_TTL_S` with a WARN."""
        cutoff = self._clock() - self.BUFFER_TTL_S
        for order_id in list(self._buffer.keys()):
            entries = self._buffer[order_id]
            kept = [(ts, raw) for ts, raw in entries if ts >= cutoff]
            dropped = len(entries) - len(kept)
            if dropped > 0:
                logger.warning(
                    "PushListener: dropping %d expired push(es) for order_id=%s "
                    "(buffered > %.0fs without trader claim — likely foreign order)",
                    dropped,
                    order_id,
                    self.BUFFER_TTL_S,
                )
            if kept:
                self._buffer[order_id] = kept
            else:
                del self._buffer[order_id]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def register_push_listener(
    bus: EventBus,
    client: BrokerClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> PushListener:
    """Construct and start a ``PushListener``.  Returns the instance for lifecycle control.

    Must be called from a running event loop (i.e. inside an ``async def``).
    """
    listener = PushListener(bus=bus, client=client, session_factory=session_factory)
    listener.start()
    return listener
