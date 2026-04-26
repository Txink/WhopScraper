"""Tests for app/broker/push_listener.py — SDK push callback → TASK_PUSH_EVENT bridge.

Five test cases:
1. test_push_new_status_emits_task_push_event
2. test_push_filled_emits_with_cumulative_deltas
3. test_push_for_unknown_order_id_logs_and_skips
4. test_push_unknown_status_maps_to_failed
5. test_multiple_subscribers_on_same_event

Note on test approach
---------------------
In production the SDK fires callbacks on its own thread; ``start()`` bridges
these to the async loop via ``asyncio.run_coroutine_threadsafe``.

In tests ``FakeBrokerClient.emit_push`` calls handlers *synchronously* from
within the event loop thread.  ``run_coroutine_threadsafe`` schedules
``_handle_raw_push`` as a coroutine on the loop, but the coroutine includes
multiple ``await`` points for DB I/O.  Since SQLAlchemy aiosqlite sessions
require many I/O round-trips to complete, the coroutine cannot be reliably
flushed to completion with a fixed number of ``asyncio.sleep(0)`` yields
before the test function returns and the fixture teardown disposes the engine.

Solution: tests call ``await listener._handle_raw_push(raw)`` directly.  This
is the appropriate pattern — we test the *business logic* of the async handler,
not the threading bridge (which is tested implicitly by test 5 via
``emit_push`` + a simple sync subscriber, without DB I/O).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.broker.push_listener import (
    PushListener,
    _build_push_event,
    _to_payload_dict,
    register_push_listener,
)
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPushPayload, Topics
from app.domain.message import Message
from app.domain.push_event import PushState
from app.domain.status import Status
from app.domain.task import Task
from app.storage.listeners import register_storage_listeners
from app.storage.repo import save_task
from tests.broker._fakes import FakeBrokerClient

# ---------------------------------------------------------------------------
# Fake SDK event (mimics LongPort push event shape via attribute access)
# ---------------------------------------------------------------------------


@dataclass
class FakePushEvent:
    """Minimal stand-in for the LongPort order-changed push event object."""

    order_id: str
    status: str  # plain string — _map_sdk_status handles both enum and string
    executed_quantity: int | None = None
    executed_price: float | None = None


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_message(id_: str) -> Message:
    return Message(
        id=id_,
        content="BUY 100",
        raw_content="BUY 100",
        author="trader",
        posted_at=datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 4, 24, 10, 0, 1, tzinfo=UTC),
        source="stock",
    )


def _make_pending_task(task_id: str, order_id: str) -> Task:
    """Return a Task in PENDING status with the given order_id set."""
    return Task(
        id=task_id,
        type="stock",
        status=Status.PENDING,
        message=_make_message(task_id),
        order_id=order_id,
        created_at=datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC),
        updated_at=datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC),
    )


async def _save(session_factory: async_sessionmaker[AsyncSession], task: Task) -> None:
    async with session_factory() as session:
        await save_task(session, task)


def _make_listener(
    bus: EventBus,
    client: FakeBrokerClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> PushListener:
    """Construct and start a PushListener. Requires a running loop — fine in async tests."""
    return register_push_listener(bus=bus, client=client, session_factory=session_factory)


# ---------------------------------------------------------------------------
# 1. NEW push → TASK_PUSH_EVENT emitted with PushState.NEW
# ---------------------------------------------------------------------------


async def test_push_new_status_emits_task_push_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    client = FakeBrokerClient()
    task = _make_pending_task("task-push-001", "ord-1")
    await _save(session_factory, task)

    received_events: list[Event] = []

    async def _capture(evt: Event) -> None:
        received_events.append(evt)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _capture)

    listener = _make_listener(bus, client, session_factory)

    # Call the async handler directly (bypasses threading bridge — tests business logic)
    await listener._handle_raw_push(FakePushEvent(order_id="ord-1", status="NEW"))
    await bus.wait_idle(timeout=2.0)

    assert len(received_events) == 1
    payload: TaskPushPayload = received_events[0].payload
    assert payload.push_event.state == PushState.NEW
    assert payload.push_event.order_id == "ord-1"
    assert payload.task.id == "task-push-001"
    assert received_events[0].topic == Topics.TASK_PUSH_EVENT


# ---------------------------------------------------------------------------
# 2. Cumulative delta sequence: NEW → PARTIAL(100) → FILLED(500)
# ---------------------------------------------------------------------------


async def test_push_filled_emits_with_cumulative_deltas(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sequence NEW → PARTIAL(100) → FILLED(500) produces correct deltas.

    Delta computation requires prior push events to be present on the loaded
    Task.  We register the storage listener so that each TASK_PUSH_EVENT
    triggers ``append_push_event`` to DB.  That way, when the next push loads
    the Task from DB, it includes previously persisted events.
    """
    bus = EventBus()
    client = FakeBrokerClient()
    task = _make_pending_task("task-push-002", "ord-2")
    await _save(session_factory, task)

    # Storage listener persists push events so subsequent loads include them
    register_storage_listeners(bus, session_factory)

    captured: list[TaskPushPayload] = []

    async def _capture(evt: Event) -> None:
        captured.append(evt.payload)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _capture)

    listener = _make_listener(bus, client, session_factory)

    # Step 1: NEW (no fill yet)
    await listener._handle_raw_push(FakePushEvent(order_id="ord-2", status="NEW"))
    await bus.wait_idle(timeout=2.0)

    # Step 2: PARTIAL 100 shares
    await listener._handle_raw_push(
        FakePushEvent(order_id="ord-2", status="PARTIAL", executed_quantity=100)
    )
    await bus.wait_idle(timeout=2.0)

    # Step 3: FILLED 500 shares total
    await listener._handle_raw_push(
        FakePushEvent(order_id="ord-2", status="FILLED", executed_quantity=500)
    )
    await bus.wait_idle(timeout=2.0)

    # Three events should have been emitted
    assert len(captured) == 3

    # NEW event — no fill qty
    new_evt = captured[0].push_event
    assert new_evt.state == PushState.NEW
    assert new_evt.cumulative_qty is None
    assert new_evt.delta_qty is None

    # PARTIAL event — first fill batch
    partial_evt = captured[1].push_event
    assert partial_evt.state == PushState.PARTIAL
    assert partial_evt.cumulative_qty == 100
    assert partial_evt.delta_qty == 100  # 100 - 0 prior

    # FILLED event — second fill batch
    filled_evt = captured[2].push_event
    assert filled_evt.state == PushState.FILLED
    assert filled_evt.cumulative_qty == 500
    assert filled_evt.delta_qty == 400  # 500 - 100 prior


# ---------------------------------------------------------------------------
# 3. Unknown order_id → no crash, no event emitted
# ---------------------------------------------------------------------------


async def test_push_for_unknown_order_id_logs_and_skips(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    client = FakeBrokerClient()

    received_events: list[Event] = []

    async def _capture(evt: Event) -> None:
        received_events.append(evt)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _capture)

    listener = _make_listener(bus, client, session_factory)

    # Call handler directly — order_id has no matching Task
    await listener._handle_raw_push(FakePushEvent(order_id="does-not-exist", status="NEW"))
    await bus.wait_idle(timeout=2.0)

    assert len(received_events) == 0


# ---------------------------------------------------------------------------
# 4. Unknown status → PushState.FAILED, note contains "unknown status"
# ---------------------------------------------------------------------------


async def test_push_unknown_status_maps_to_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    bus = EventBus()
    client = FakeBrokerClient()
    task = _make_pending_task("task-push-004", "ord-4")
    await _save(session_factory, task)

    captured: list[TaskPushPayload] = []

    async def _capture(evt: Event) -> None:
        captured.append(evt.payload)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _capture)

    listener = _make_listener(bus, client, session_factory)

    await listener._handle_raw_push(FakePushEvent(order_id="ord-4", status="WEIRD_UNKNOWN"))
    await bus.wait_idle(timeout=2.0)

    assert len(captured) == 1
    push_evt = captured[0].push_event
    assert push_evt.state == PushState.FAILED
    assert push_evt.note is not None
    assert "WEIRD_UNKNOWN" in push_evt.note


# ---------------------------------------------------------------------------
# 5. Multiple subscribers — no interference between them
# ---------------------------------------------------------------------------


async def test_multiple_subscribers_on_same_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Two independent push subscribers both receive the same raw SDK event.

    Verifies:
    - ``FakeBrokerClient`` correctly fans out to all registered handlers via
      ``subscribe_order_push`` — the second handler fires for the same event.
    - Registering two handlers does not break either handler (no interference).
    - The PushListener correctly processes a push and emits a TASK_PUSH_EVENT.
    """
    bus = EventBus()
    client = FakeBrokerClient()
    task = _make_pending_task("task-push-005", "ord-5")
    await _save(session_factory, task)

    # Register a second independent sync subscriber BEFORE PushListener
    second_received: list[Any] = []

    def _second_handler(raw: Any) -> None:
        second_received.append(raw)

    client.subscribe_order_push(_second_handler)

    # Register our PushListener (appends its own sync callback)
    listener = _make_listener(bus, client, session_factory)

    # Capture bus events
    bus_events: list[Event] = []

    async def _bus_capture(evt: Event) -> None:
        bus_events.append(evt)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _bus_capture)

    raw_event = FakePushEvent(order_id="ord-5", status="FILLED", executed_quantity=200)

    # emit_push fires both _second_handler (sync) and PushListener._sync_callback (sync).
    client.emit_push(raw_event)

    # Second handler received the raw event synchronously — no async needed
    assert len(second_received) == 1
    assert second_received[0].order_id == "ord-5"

    # Call PushListener's async handler directly to verify its output without
    # racing against the threadsafe-scheduled coroutine from emit_push.
    # The scheduled coroutine will also run eventually (verified by no crash),
    # but we use the direct call to assert deterministic bus output.
    await listener._handle_raw_push(raw_event)
    await bus.wait_idle(timeout=2.0)

    # At least one TASK_PUSH_EVENT was published with the right state.
    # (There may be 2 if the run_coroutine_threadsafe coroutine also completed.)
    assert len(bus_events) >= 1
    assert bus_events[0].payload.push_event.state == PushState.FILLED


# ---------------------------------------------------------------------------
# 6. Realistic C-extension SDK shape: vars()/__dict__ does not return a dict
# ---------------------------------------------------------------------------
#
# Production bug (commit ed1b108): LongPort SDK's PushOrderChanged is a
# Rust-backed C-extension whose ``__dict__`` is a builtin method, not a
# Python dict. The old ``_to_payload_dict`` did
#     pairs = vars(raw).items()
# expecting either a dict (returned items()) or a TypeError (caught and
# fell through). It got NEITHER — vars() silently returned a non-dict
# (the bound method itself), and ``.items()`` raised AttributeError. This
# crashed ``_handle_raw_push`` for every real push, so push_events stayed
# empty in production despite valid pushes arriving.
#
# Old test doubles (FakePushEvent above) are plain Python ``@dataclass``
# instances with a normal ``__dict__``, so they always hit the happy
# fast path and never exercised the C-extension branch.
#
# The doubles below reproduce the exact production conditions:
#  - ``__dict__`` resolves to a non-dict, non-raising value
#  - attribute reads via ``getattr`` work (matching real SDK)
#  - ``dir()`` enumerates the public attribute names
#  - enum-shaped fields ``repr()`` as ``"OrderStatus.NotReported"`` etc.,
#    so ``_serialise_value`` must split on ``.`` to reach ``"NotReported"``


class _SDKEnumLike:
    """Mimics LongPort SDK enum value reprs (e.g. ``"OrderStatus.NotReported"``).

    The real SDK enums are PyO3-bound Rust enums whose ``repr`` is
    ``"<TypeName>.<VariantName>"``. ``_serialise_value`` relies on this format
    to extract the variant name when no Python ``Enum`` subclass match.
    """

    def __init__(self, type_name: str, variant: str) -> None:
        self._type = type_name
        self._variant = variant

    def __repr__(self) -> str:
        return f"{self._type}.{self._variant}"


class _CExtensionPushOrderChanged:
    """Test double for LongPort's C-extension ``PushOrderChanged``.

    Reproduces the runtime shape that broke production:
      * ``vars(raw)`` returns a non-dict (a builtin method) instead of a
        Python ``dict``, and crucially does NOT raise ``TypeError``.
      * Attribute reads via ``getattr(raw, name)`` work (Rust property
        descriptors) — this is how the real SDK exposes fields.
      * ``dir(raw)`` enumerates the public attribute names — the
        ``_to_payload_dict`` dir-fallback walks these.

    Implementation note: ``__slots__`` removes the auto-generated instance
    ``__dict__``; the override in ``__getattribute__`` reroutes ``__dict__``
    to a plain builtin function so ``isinstance(vars(self), dict)`` is False.
    """

    __slots__ = ("_attrs",)

    def __init__(self, **fields: Any) -> None:
        object.__setattr__(self, "_attrs", fields)

    def __getattribute__(self, name: str) -> Any:
        if name == "__dict__":
            # The real SDK exposes __dict__ as a Rust property/method —
            # vars() returns it as-is without raising. dict.fromkeys is a
            # convenient stand-in: a builtin_function_or_method, not a dict.
            return dict.fromkeys
        if name == "_attrs":
            return object.__getattribute__(self, "_attrs")
        # User-data attributes live in _attrs (mimicking SDK property descriptors)
        attrs = object.__getattribute__(self, "_attrs")
        if name in attrs:
            return attrs[name]
        return object.__getattribute__(self, name)

    def __dir__(self) -> list[str]:
        return list(object.__getattribute__(self, "_attrs").keys())


def _realistic_sdk_push(
    *,
    order_id: str = "1232925773216645120",
    status_variant: str = "NotReported",
    side_variant: str = "Buy",
) -> _CExtensionPushOrderChanged:
    """Build a double with field shapes captured from a live SDK push.

    Field set + types match a real ``PushOrderChanged`` observed in a paper
    diag run. Values are realistic enough to exercise every branch of
    ``_serialise_value`` (Decimal, SDK enums, datetime ISO strings, plain
    primitives, Optional/None).
    """
    return _CExtensionPushOrderChanged(
        side=_SDKEnumLike("OrderSide", side_variant),
        stock_name="苹果",
        submitted_quantity=Decimal("1"),
        symbol="AAPL.US",
        order_type=_SDKEnumLike("OrderType", "LO"),
        submitted_price=Decimal("1.00"),
        executed_quantity=Decimal("0"),
        executed_price=None,
        order_id=order_id,
        currency="USD",
        status=_SDKEnumLike("OrderStatus", status_variant),
        submitted_at="2026-04-26T05:15:54Z",
        updated_at="2026-04-26T05:15:54Z",
        trigger_price=None,
        msg="",
        tag=_SDKEnumLike("OrderTag", "Normal"),
        trigger_status=_SDKEnumLike("TriggerStatus", "Unknown"),
        trigger_at=None,
        trailing_amount=None,
        trailing_percent=None,
        limit_offset=None,
        account_no="LBPT10030472",
        last_share=None,
        last_price=None,
        remark="diag test",
    )


def test_to_payload_dict_handles_c_extension_with_non_dict_dunder_dict() -> None:
    """Regression for production crash: ``vars(SDK_obj)`` returns a non-dict.

    Without the dir()-based fallback, ``vars(raw).items()`` raises
    AttributeError and kills the entire push pipeline (push_events table
    stays empty despite valid SDK pushes arriving).
    """
    raw = _realistic_sdk_push()

    # Sanity: simulator reproduces the bug condition. If this assertion
    # ever flips, the test is no longer probing the production failure mode.
    assert not isinstance(vars(raw), dict), (
        "simulator must reproduce the C-extension behavior where vars() "
        "returns a non-dict; otherwise this test isn't catching the bug"
    )

    # Must not crash, must produce a usable payload.
    payload = _to_payload_dict(raw)

    assert isinstance(payload, dict)
    # Field presence
    assert payload["order_id"] == "1232925773216645120"
    assert payload["symbol"] == "AAPL.US"
    assert payload["currency"] == "USD"
    assert payload["account_no"] == "LBPT10030472"
    assert payload["msg"] == ""
    assert payload["remark"] == "diag test"
    # SDK enum-likes are reduced to their variant name by _serialise_value
    assert payload["status"] == "NotReported"
    assert payload["side"] == "Buy"
    assert payload["order_type"] == "LO"
    assert payload["tag"] == "Normal"
    # None values pass through
    assert payload["executed_price"] is None
    assert payload["trigger_at"] is None


def test_build_push_event_with_realistic_c_extension_raw() -> None:
    """End-to-end: ``_build_push_event`` accepts a realistic SDK-shaped raw.

    Verifies the entire payload-building path works against the C-extension
    double, not just the dict conversion. Status mapping, payload
    serialisation, and PushEvent construction all need to cope with the
    SDK's runtime shape.
    """
    raw = _realistic_sdk_push(status_variant="Filled")
    task = _make_pending_task("task-cext-1", "1232925773216645120")

    evt = _build_push_event(raw, task)

    assert evt.task_id == "task-cext-1"
    assert evt.order_id == "1232925773216645120"
    assert evt.state == PushState.FILLED  # OrderStatus.Filled → PushState.FILLED
    # Payload was extracted via the dir() fallback and contains the SDK fields.
    assert isinstance(evt.payload, dict)
    assert evt.payload["symbol"] == "AAPL.US"
    assert evt.payload["status"] == "Filled"


async def test_handle_raw_push_publishes_when_raw_is_c_extension_shaped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """End-to-end through ``_handle_raw_push``: C-extension raw lookups the
    Task by order_id, builds the PushEvent, and publishes
    TASK_PUSH_EVENT — exactly the path that crashed in production.
    """
    bus = EventBus()
    client = FakeBrokerClient()
    task = _make_pending_task("task-cext-2", "1232925773216645120")
    await _save(session_factory, task)

    listener = _make_listener(bus, client, session_factory)

    captured: list[Event] = []

    async def _capture(evt: Event) -> None:
        captured.append(evt)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _capture)

    raw = _realistic_sdk_push(status_variant="PartialFilled")
    await listener._handle_raw_push(raw)
    await bus.wait_idle(timeout=2.0)

    assert len(captured) == 1
    payload: TaskPushPayload = captured[0].payload  # type: ignore[assignment]
    assert payload.push_event.state == PushState.PARTIAL
    assert payload.push_event.order_id == "1232925773216645120"
    # The serialised payload reached storage shape via the dir() fallback.
    assert payload.push_event.payload["symbol"] == "AAPL.US"
    assert payload.push_event.payload["status"] == "PartialFilled"


# ---------------------------------------------------------------------------
# 7. Broker-supplied rejection msg surfaces on PushEvent.note + Task.reject_reason
# ---------------------------------------------------------------------------


async def test_rejected_push_surfaces_broker_msg_as_note_and_reject_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """When LongPort rejects an order, ``PushOrderChanged.msg`` carries the
    human-readable reason (e.g. ``"订单金额超出最大购买力"``). We must:

    1. Put it on ``PushEvent.note`` so the expanded card's push detail
       row can render it next to the REJECTED node.
    2. Copy it onto ``Task.reject_reason`` so the card header / status
       pill can show ``"REJECTED · <reason>"`` without having to dig
       through push events.
    """
    bus = EventBus()
    client = FakeBrokerClient()
    task = _make_pending_task("task-reject-msg", "ord-rej")
    await _save(session_factory, task)

    listener = _make_listener(bus, client, session_factory)

    captured: list[Event] = []

    async def _capture(evt: Event) -> None:
        captured.append(evt)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _capture)

    raw = _CExtensionPushOrderChanged(
        order_id="ord-rej",
        status=_SDKEnumLike("OrderStatus", "Rejected"),
        side=_SDKEnumLike("OrderSide", "Buy"),
        symbol="AAPL.US",
        executed_quantity=Decimal("0"),
        executed_price=None,
        msg="订单金额超出最大购买力",
    )
    await listener._handle_raw_push(raw)
    await bus.wait_idle(timeout=2.0)

    assert len(captured) == 1
    payload: TaskPushPayload = captured[0].payload  # type: ignore[assignment]
    assert payload.push_event.state == PushState.REJECTED
    # Broker msg lands on the PushEvent note (not the unknown-status fallback).
    assert payload.push_event.note == "订单金额超出最大购买力"
    # And it bubbles to the Task itself for header-level display.
    assert payload.task.reject_reason == "订单金额超出最大购买力"


def test_build_push_event_prefers_broker_msg_over_unknown_status_note() -> None:
    """If the SDK sends an unrecognised status AND a non-empty msg, the msg
    is the more useful note; the unknown-status warning is a fallback only."""
    raw = _CExtensionPushOrderChanged(
        order_id="ord-x",
        status=_SDKEnumLike("OrderStatus", "TotallyMadeUpStatus"),
        side=_SDKEnumLike("OrderSide", "Buy"),
        symbol="AAPL.US",
        executed_quantity=Decimal("0"),
        executed_price=None,
        msg="账户冻结",
    )
    task = _make_pending_task("task-msg-priority", "ord-x")

    evt = _build_push_event(raw, task)

    assert evt.state == PushState.FAILED  # unknown status → FAILED
    # Note prefers the broker msg, not "unknown status: ..."
    assert evt.note == "账户冻结"


def test_build_push_event_falls_back_to_unknown_status_note_when_msg_empty() -> None:
    """When msg is empty/missing, the unknown-status warning is preserved
    so we don't lose diagnostic info on truly unrecognised SDK statuses."""
    raw = _CExtensionPushOrderChanged(
        order_id="ord-y",
        status=_SDKEnumLike("OrderStatus", "MadeUp"),
        side=_SDKEnumLike("OrderSide", "Buy"),
        symbol="AAPL.US",
        executed_quantity=Decimal("0"),
        executed_price=None,
        msg="",
    )
    task = _make_pending_task("task-msg-empty", "ord-y")

    evt = _build_push_event(raw, task)

    assert evt.state == PushState.FAILED
    assert evt.note is not None
    assert "unknown status" in evt.note
    assert "MadeUp" in evt.note


async def test_filled_push_with_msg_does_not_set_reject_reason(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """reject_reason is set only on REJECTED/FAILED states. A FILLED push with
    a msg (rare but legal — e.g. partial-fill informational note) must not
    pollute reject_reason.
    """
    bus = EventBus()
    client = FakeBrokerClient()
    task = _make_pending_task("task-filled-msg", "ord-f")
    await _save(session_factory, task)

    listener = _make_listener(bus, client, session_factory)

    captured: list[Event] = []

    async def _capture(evt: Event) -> None:
        captured.append(evt)

    bus.subscribe(Topics.TASK_PUSH_EVENT, _capture)

    raw = _CExtensionPushOrderChanged(
        order_id="ord-f",
        status=_SDKEnumLike("OrderStatus", "Filled"),
        side=_SDKEnumLike("OrderSide", "Buy"),
        symbol="AAPL.US",
        executed_quantity=Decimal("100"),
        executed_price=Decimal("25.00"),
        msg="info: full fill",
    )
    await listener._handle_raw_push(raw)
    await bus.wait_idle(timeout=2.0)

    assert len(captured) == 1
    payload: TaskPushPayload = captured[0].payload  # type: ignore[assignment]
    assert payload.push_event.state == PushState.FILLED
    # Note still carries the msg for audit visibility…
    assert payload.push_event.note == "info: full fill"
    # …but reject_reason stays clean.
    assert payload.task.reject_reason is None
