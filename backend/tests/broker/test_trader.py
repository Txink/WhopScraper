"""Tests for app.broker.trader — Task lifecycle + order submission."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from app.broker.config import LongPortConfig
from app.broker.trader import register_trader
from app.core.event_bus import Event, EventBus
from app.core.events import TaskPayload, Topics
from app.domain.instruction import InstructionType, OptionInstruction, StockInstruction
from app.domain.message import Message
from app.domain.status import Status
from app.domain.task import Task
from app.whop.page_settings import PageSettings, TickerConfig
from tests.broker._fakes import FakeBrokerClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(*, source: str = "stock") -> Message:
    return Message(
        id="msg-test-001",
        content="test message",
        raw_content="test message",
        author="test-user",
        posted_at=datetime(2026, 4, 24, 10, 0, 0, tzinfo=UTC),
        received_at=datetime(2026, 4, 24, 10, 0, 0, 1000, tzinfo=UTC),
        source=source,  # type: ignore[arg-type]
    )


def _stock_task(
    symbol: str = "TSLA.US",
    instruction_type: InstructionType = InstructionType.BUY,
) -> Task:
    task = Task.new_from_message(_msg(source="stock"))
    task.mark_parsing()
    inst = StockInstruction(
        instruction_type=instruction_type,
        price=25.0,
        price_range=None,
        quantity=100,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source="group",
        parser_notes=[],
        ticker="TSLA",
        symbol=symbol,
        sell_quantity=None,
    )
    task.attach_instruction(inst)
    return task


def _option_task(
    symbol: str = "AAPL260117C150000.US",
    quantity: int = 1,
    price: float = 3.0,
    instruction_type: InstructionType = InstructionType.BUY,
) -> Task:
    task = Task.new_from_message(_msg(source="option"))
    task.mark_parsing()
    inst = OptionInstruction(
        instruction_type=instruction_type,
        price=price,
        price_range=None,
        quantity=quantity,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source="group",
        parser_notes=[],
        ticker="AAPL",
        option_type="CALL",
        strike=150.0,
        expiry=date(2026, 1, 17),
        symbol=symbol,
    )
    task.attach_instruction(inst)
    return task


def _config(**overrides: object) -> LongPortConfig:
    defaults: dict = dict(
        mode="paper",
        app_key="k",
        app_secret="s",
        access_token="t",
        auto_trade=True,
        dry_run=False,
        max_option_total_price=500.0,
        max_option_quantity=3,
    )
    defaults.update(overrides)
    return LongPortConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stock_buy_happy_path() -> None:
    """Stock BUY task → broker receives stock order, TASK_ORDER_SUBMITTED emitted."""
    bus = EventBus()
    fake = FakeBrokerClient(next_order_id="ORDER-STK-001")
    # last_done 20 < signal 25 → LIMIT @ last_done (20)
    fake.quote_by_symbol["TSLA.US"] = 20.0
    register_trader(bus, fake, _config())

    received_events: list[Event] = []

    async def capture(event: Event) -> None:
        received_events.append(event)

    bus.subscribe(Topics.TASK_ORDER_SUBMITTED, capture)

    task = _stock_task()
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(fake.submitted_orders) == 1
    order = fake.submitted_orders[0]
    assert order["kind"] == "stock"
    assert order["side"] == "BUY"
    assert order["symbol"] == "TSLA.US"
    assert order["price"] == pytest.approx(20.0)
    assert order["order_type"] == "LIMIT"

    assert len(received_events) == 1
    submitted_task: Task = received_events[0].payload.task
    assert submitted_task.status == Status.PENDING
    assert submitted_task.submit_order_type == "LIMIT"
    assert submitted_task.submit_order_context is not None
    assert "限价" in (submitted_task.submit_order_context or "")
    assert submitted_task.submit_quote_last_done == pytest.approx(20.0)
    assert submitted_task.order_id == "ORDER-STK-001"
    assert "submit" in submitted_task.stage_timings


@pytest.mark.asyncio
async def test_option_buy_happy_path() -> None:
    """Option BUY task → broker receives option order, TASK_ORDER_SUBMITTED emitted."""
    bus = EventBus()
    fake = FakeBrokerClient(next_order_id="ORDER-OPT-001")
    # last_done 2.0 < signal 3.0 → LIMIT @ last_done (2.0)
    fake.quote_by_symbol["AAPL260117C150000.US"] = 2.0
    register_trader(bus, fake, _config())

    received_events: list[Event] = []

    async def capture(event: Event) -> None:
        received_events.append(event)

    bus.subscribe(Topics.TASK_ORDER_SUBMITTED, capture)

    task = _option_task(quantity=1, price=3.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(fake.submitted_orders) == 1
    order = fake.submitted_orders[0]
    assert order["kind"] == "option"
    assert order["side"] == "BUY"
    assert order["symbol"] == "AAPL260117C150000.US"
    assert order["price"] == pytest.approx(2.0)
    assert order["order_type"] == "LIMIT"

    assert len(received_events) == 1
    submitted_task: Task = received_events[0].payload.task
    assert submitted_task.status == Status.PENDING
    assert submitted_task.submit_order_type == "LIMIT"
    assert submitted_task.submit_quote_last_done == pytest.approx(2.0)
    assert submitted_task.order_id == "ORDER-OPT-001"


@pytest.mark.asyncio
async def test_auto_trade_disabled_marks_waiting_manual_confirm() -> None:
    """auto_trade=False keeps task INSTRUCTION_READY and emits a status update."""
    bus = EventBus()
    fake = FakeBrokerClient()
    register_trader(bus, fake, _config(auto_trade=False))

    status_events: list[Event] = []
    submitted_events: list[Event] = []

    async def capture_status(event: Event) -> None:
        status_events.append(event)

    async def capture_submitted(event: Event) -> None:
        submitted_events.append(event)

    bus.subscribe(Topics.TASK_STATUS_CHANGED, capture_status)
    bus.subscribe(Topics.TASK_ORDER_SUBMITTED, capture_submitted)

    task = _stock_task()
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(fake.submitted_orders) == 0
    assert len(submitted_events) == 0
    assert len(status_events) == 1
    blocked_task: Task = status_events[0].payload.task
    assert blocked_task.status == Status.INSTRUCTION_READY
    assert blocked_task.reject_reason is not None
    assert "manual" in blocked_task.reject_reason.lower()


@pytest.mark.asyncio
async def test_option_global_env_limits_no_longer_block() -> None:
    """Option submission should no longer be blocked by global max_option_* config."""
    bus = EventBus()
    fake = FakeBrokerClient(next_order_id="ORDER-OPT-002")
    # Intentionally tiny global limits; trader should ignore them.
    register_trader(bus, fake, _config(max_option_total_price=1.0, max_option_quantity=1))

    submitted_events: list[Event] = []

    async def capture_submitted(event: Event) -> None:
        submitted_events.append(event)

    bus.subscribe(Topics.TASK_ORDER_SUBMITTED, capture_submitted)

    task = _option_task(quantity=10, price=5.0)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(fake.submitted_orders) == 1
    order = fake.submitted_orders[0]
    assert order["kind"] == "option"
    assert order["quantity"] == 10
    assert len(submitted_events) == 1


@pytest.mark.asyncio
async def test_broker_exception_marks_submit_failed() -> None:
    """Broker raises RuntimeError → TASK_SUBMIT_FAILED, task.reject_reason has error text."""
    bus = EventBus()
    fake = FakeBrokerClient(raise_on_submit=RuntimeError("connection timeout"))
    register_trader(bus, fake, _config())

    failed_events: list[Event] = []

    async def capture_failed(event: Event) -> None:
        failed_events.append(event)

    bus.subscribe(Topics.TASK_SUBMIT_FAILED, capture_failed)

    task = _stock_task()
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(failed_events) == 1
    failed_task: Task = failed_events[0].payload.task
    assert failed_task.status == Status.SUBMIT_FAILED
    assert "connection timeout" in (failed_task.reject_reason or "")
    assert failed_task.submit_order_type is None
    assert failed_task.submit_order_context is None


@pytest.mark.asyncio
async def test_openapi_exception_reject_reason_drops_envelope() -> None:
    """OpenApiException-shaped errors are reduced to "broker [code] message"
    so the UI shows the server message rather than the SDK's repr envelope
    (kind=..., trace_id=...)."""

    class _OpenApiExceptionLike(Exception):
        """Duck-typed stand-in for longport.openapi.OpenApiException — same
        structural fields (kind/code/trace_id/message) the helper looks for."""

        def __init__(self, *, kind: str, code: int, trace_id: str, message: str) -> None:
            super().__init__(message)
            self.kind = kind
            self.code = code
            self.trace_id = trace_id
            self.message = message

    exc = _OpenApiExceptionLike(
        kind="ErrorKind.OpenApi",
        code=603301,
        trace_id="bbbb8a494db6cb14b34f618c5c905feb",
        message="The symbol currently does not support short selling.",
    )

    bus = EventBus()
    fake = FakeBrokerClient(raise_on_submit=exc)
    register_trader(bus, fake, _config())

    failed_events: list[Event] = []

    async def capture_failed(event: Event) -> None:
        failed_events.append(event)

    bus.subscribe(Topics.TASK_SUBMIT_FAILED, capture_failed)

    task = _stock_task()
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(failed_events) == 1
    failed_task: Task = failed_events[0].payload.task
    assert failed_task.status == Status.SUBMIT_FAILED
    assert failed_task.reject_reason == (
        "broker [603301] The symbol currently does not support short selling."
    )
    assert failed_task.submit_order_type is None


@pytest.mark.asyncio
async def test_missing_symbol_skips() -> None:
    """Instruction with empty symbol → SKIPPED, no broker call."""
    bus = EventBus()
    fake = FakeBrokerClient()
    register_trader(bus, fake, _config())

    status_events: list[Event] = []

    async def capture_status(event: Event) -> None:
        status_events.append(event)

    bus.subscribe(Topics.TASK_STATUS_CHANGED, capture_status)

    # Build a stock task with empty symbol
    task = _stock_task(symbol="")
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert len(fake.submitted_orders) == 0
    assert len(status_events) == 1
    skipped_task: Task = status_events[0].payload.task
    assert skipped_task.status == Status.SKIPPED
    assert "symbol" in (skipped_task.reject_reason or "")


# ---------------------------------------------------------------------------
# Pre-submission validation gate — Task 2 (revised design)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trader_skips_when_instruction_invalid_side() -> None:
    """A task whose instruction has CLOSE side fails the validation gate
    before the auto_trade check, regardless of auto_trade."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(bus, fake_broker, _config(auto_trade=True))

    task = _stock_task(instruction_type=InstructionType.CLOSE)
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert task.status == Status.SKIPPED
    assert task.reject_reason is not None
    assert "参数不齐" in task.reject_reason
    assert "BUY" in task.reject_reason and "SELL" in task.reject_reason


@pytest.mark.asyncio
async def test_trader_holds_for_manual_when_valid_and_auto_trade_off() -> None:
    """Valid instruction + auto_trade=false: validation gate passes, then
    the auto_trade gate keeps the task at INSTRUCTION_READY with reject_reason
    set, ready for manual confirmation."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(bus, fake_broker, _config(auto_trade=False))

    task = _stock_task()  # BUY, complete instruction
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert task.status == Status.INSTRUCTION_READY  # held for manual
    assert task.reject_reason is not None
    assert "auto_trade" in task.reject_reason


@pytest.mark.asyncio
async def test_trader_proceeds_when_valid_and_auto_trade_on() -> None:
    """Valid instruction + auto_trade=true: both gates pass, broker called."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(bus, fake_broker, _config(auto_trade=True))

    task = _stock_task()  # BUY, complete instruction
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    # Status advanced past INSTRUCTION_READY (PENDING means broker submitted)
    assert task.status in (Status.PENDING, Status.SUBMITTING, Status.FILLED)


# ---------------------------------------------------------------------------
# Helpers for ordering tests
# ---------------------------------------------------------------------------


def _fake_registry(tickers: set[str], block_historical: bool = False) -> MagicMock:
    registry = MagicMock()
    registry.get_settings_for_url.return_value = PageSettings(
        dedupe_processed_messages=True,
        price_deviation_tolerance=1.0,
        tickers={t: TickerConfig(trade_quantity=100) for t in tickers},
        block_historical_messages=block_historical,
    )
    return registry


# ---------------------------------------------------------------------------
# Ordering tests (gate ① a → ① b → ① c ordering)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trader_whitelist_check_runs_before_validation() -> None:
    """A stock task whose ticker is NOT in the page whitelist AND has an
    invalid side (CLOSE) should SKIP with the WHITELIST reason — not the
    validation reason — proving whitelist check runs first."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(bus, fake_broker, _config(auto_trade=True), registry=_fake_registry({"AAPL"}))

    task = _stock_task(instruction_type=InstructionType.CLOSE)  # ticker is TSLA, not in whitelist
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert task.status == Status.SKIPPED
    assert task.reject_reason is not None
    assert "不在白名单" in task.reject_reason
    assert "参数不齐" not in task.reject_reason


@pytest.mark.asyncio
async def test_trader_historical_runs_before_validation() -> None:
    """Whitelisted ticker with is_historical=True AND invalid side: the
    historical reason should win, proving the historical check runs before the
    completeness check."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(
        bus, fake_broker, _config(auto_trade=True),
        registry=_fake_registry({"TSLA"}, block_historical=True),
    )

    # Build a task with an invalid side (CLOSE) and mark it as historical.
    task = _stock_task(instruction_type=InstructionType.CLOSE)
    task.is_historical = True

    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert task.status == Status.SKIPPED
    assert task.reject_reason is not None
    assert "历史消息" in task.reject_reason


@pytest.mark.asyncio
async def test_trader_accepts_whitelisted_stock_without_qty_or_position_size() -> None:
    """The bug being fixed: a whitelisted stock signal that parsed only
    ticker+side+price (no qty, no position_size) should NOT be SKIPPED
    by the validation gate. trader.py should resolve qty from
    page_settings.trade_quantity."""
    bus = EventBus()
    fake_broker = FakeBrokerClient()
    register_trader(
        bus, fake_broker, _config(auto_trade=True),
        registry=_fake_registry({"TSLA"}),
    )

    # Build a stock task with quantity=None and position_size=None
    task = Task.new_from_message(_msg(source="stock"))
    task.mark_parsing()
    inst = StockInstruction(
        instruction_type=InstructionType.BUY,
        price=25.0, price_range=None,
        quantity=None, position_size=None,  # ← the bug case
        stop_loss_price=None, take_profit_price=None,
        context_source="group", parser_notes=[],
        ticker="TSLA", symbol="TSLA.US", sell_quantity=None,
    )
    task.attach_instruction(inst)

    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    # Should advance past INSTRUCTION_READY (broker submitted)
    assert task.status in (Status.PENDING, Status.SUBMITTING, Status.FILLED), (
        f"expected submission, got {task.status} with reason={task.reject_reason}"
    )


# ---------------------------------------------------------------------------
# Push-buffer replay integration: trader must drain the listener's buffer
# after committing the order_id, so pushes that arrived during _submit are
# not lost.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trader_calls_replay_for_order_after_save_task() -> None:
    """If a ``push_listener`` is wired in, the trader must call
    ``listener.replay_for_order(order_id)`` after the broker submit succeeds
    so any pushes that arrived while ``_submit`` was blocking get processed.
    """
    bus = EventBus()
    fake = FakeBrokerClient(next_order_id="ORDER-REPLAY-1")
    fake.quote_by_symbol["TSLA.US"] = 20.0

    replay_calls: list[str] = []

    class _StubListener:
        async def replay_for_order(self, order_id: str) -> int:
            replay_calls.append(order_id)
            return 0

    register_trader(bus, fake, _config(), push_listener=_StubListener())

    task = _stock_task()
    await bus.publish(Event(Topics.TASK_INSTRUCTION_READY, TaskPayload(task)))
    await bus.wait_idle(timeout=2.0)

    assert replay_calls == ["ORDER-REPLAY-1"]
    assert task.order_id == "ORDER-REPLAY-1"
