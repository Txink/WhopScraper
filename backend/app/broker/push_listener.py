"""PushListener —— Bridge broker SDK push callbacks → TASK_PUSH_EVENT bus events.

Design
------
Broker SDK fires order-change push events on its own thread via a registered
callback.  ``PushListener.start()`` captures the running asyncio event-loop and
schedules ``_handle_raw_push`` on it using ``asyncio.run_coroutine_threadsafe``,
keeping all domain logic safely in async context.

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
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.broker_client import BrokerClient
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
    """

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

    def start(self) -> None:
        """Subscribe to broker push.  Must be called from a running event loop."""
        loop = asyncio.get_running_loop()
        self._loop = loop

        def _sync_callback(raw: Any) -> None:
            # Runs on SDK thread — marshal to async loop.
            asyncio.run_coroutine_threadsafe(self._handle_raw_push(raw), loop)

        self._client.subscribe_order_push(_sync_callback)
        logger.info("PushListener started — subscribed to broker order push")

    # Race-safe lookup config: in production we have observed pushes for
    # an order arrive BEFORE the trader's storage listener has committed
    # the task row carrying that order_id. submit_order returns an id at
    # T+~120ms; LongPort can push NotReported within a few ms of that;
    # the storage save runs on the same event loop and finishes shortly
    # after. A blind first lookup races with the commit. Retrying gives
    # the in-flight save a chance to finish.
    _LOOKUP_RETRY_ATTEMPTS = 4
    _LOOKUP_RETRY_DELAY_S = 0.1

    async def _load_task_with_retry(self, order_id: str) -> Task | None:
        """Look up the Task by order_id, retrying briefly to absorb the
        trader→storage commit race. Returns None only after all retries fail.
        """
        last_attempt = self._LOOKUP_RETRY_ATTEMPTS - 1
        for attempt in range(self._LOOKUP_RETRY_ATTEMPTS):
            async with self._session_factory() as session:
                task = await load_task_by_order_id(session, order_id)
            if task is not None:
                if attempt > 0:
                    logger.info(
                        "PushListener: task lookup succeeded on retry %d/%d for "
                        "order_id=%s — absorbed trader→storage commit race",
                        attempt + 1,
                        self._LOOKUP_RETRY_ATTEMPTS,
                        order_id,
                    )
                return task
            if attempt < last_attempt:
                logger.debug(
                    "PushListener: task lookup miss attempt %d/%d for order_id=%s; "
                    "retrying in %.0fms",
                    attempt + 1,
                    self._LOOKUP_RETRY_ATTEMPTS,
                    order_id,
                    self._LOOKUP_RETRY_DELAY_S * 1000,
                )
                await asyncio.sleep(self._LOOKUP_RETRY_DELAY_S)
        return None

    async def _handle_raw_push(self, raw: Any) -> None:
        """Async handler.  Looks up Task, builds PushEvent, publishes to bus."""
        order_id: str = str(getattr(raw, "order_id", "") or "")
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

        task = await self._load_task_with_retry(order_id)
        if task is None:
            # All retries failed. This is either a push for a foreign
            # order_id (we never submitted it — possibly residual broker
            # session leftovers) or our trader was so slow to commit that
            # even the retry window was not enough. Logging the raw event
            # at WARNING gives the operator something to grep for.
            logger.warning(
                "PushListener: no Task found for order_id=%s after %d attempts "
                "(total wait ≈ %dms) — DROPPING push; sdk_status=%r raw=%r",
                order_id,
                self._LOOKUP_RETRY_ATTEMPTS,
                int(self._LOOKUP_RETRY_DELAY_S * 1000 * (self._LOOKUP_RETRY_ATTEMPTS - 1)),
                sdk_status,
                repr(raw)[:200],
            )
            return

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
