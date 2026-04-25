"""Tests for app.api.schemas — Pydantic models and domain converters."""
from __future__ import annotations

from datetime import UTC, date, datetime

from app.api.schemas import (
    TaskSummaryOut,
    instruction_to_out,
    message_to_out,
    push_event_to_out,
    task_to_out,
    task_to_summary,
)
from app.domain.instruction import InstructionType, OptionInstruction, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _make_message(
    msg_id: str = "msg-1",
    quoted: Message | None = None,
    source: str = "stock",
) -> Message:
    return Message(
        id=msg_id,
        content="buy AAPL 200 shares at 195",
        raw_content="buy AAPL 200 shares at 195",
        author="trader_alice",
        posted_at=_NOW,
        received_at=_NOW,
        source=source,  # type: ignore[arg-type]
        quoted=quoted,
    )


def _make_stock_instruction(**kwargs: object) -> StockInstruction:
    defaults: dict[str, object] = dict(
        instruction_type=InstructionType.BUY,
        price=195.0,
        price_range=None,
        quantity=200,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="AAPL",
        symbol="AAPL.US",
        sell_quantity=None,
    )
    defaults.update(kwargs)
    return StockInstruction(**defaults)  # type: ignore[arg-type]


def _make_option_instruction(**kwargs: object) -> OptionInstruction:
    defaults: dict[str, object] = dict(
        instruction_type=InstructionType.BUY,
        price=3.5,
        price_range=None,
        quantity=2,
        position_size=None,
        stop_loss_price=None,
        take_profit_price=None,
        context_source=None,
        parser_notes=[],
        ticker="TSLA",
        option_type="CALL",
        strike=250.0,
        expiry=date(2025, 12, 19),
        symbol="TSLA250119C00250000",
    )
    defaults.update(kwargs)
    return OptionInstruction(**defaults)  # type: ignore[arg-type]


def _make_push_event(evt_id: str = "evt-1", task_id: str = "msg-1") -> PushEvent:
    return PushEvent(
        id=evt_id,
        task_id=task_id,
        order_id="ord-99",
        state=PushState.FILLED,
        received_at=_NOW,
        payload={},
        delta_qty=100,
        delta_price=195.5,
        cumulative_qty=100,
        cumulative_avg_price=195.5,
        note="filled",
    )


def _make_task(msg: Message, instruction: object = None) -> Task:
    task = Task(
        id=msg.id,
        type="stock",
        status=Status.INSTRUCTION_READY,
        message=msg,
        created_at=_NOW,
        updated_at=_NOW,
    )
    return task


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_message_to_out_round_trip() -> None:
    msg = _make_message()
    out = message_to_out(msg)
    assert out.id == "msg-1"
    assert out.content == "buy AAPL 200 shares at 195"
    assert out.author == "trader_alice"
    assert out.source == "stock"
    assert out.quoted_message_id is None


def test_message_to_out_with_quoted_message() -> None:
    parent = _make_message(msg_id="parent-msg")
    child = _make_message(msg_id="child-msg", quoted=parent)
    out = message_to_out(child)
    assert out.quoted_message_id == "parent-msg"


def test_stock_instruction_to_out() -> None:
    inst = _make_stock_instruction()
    out = instruction_to_out(inst)
    assert out.type == "stock"
    assert out.ticker == "AAPL"
    assert out.symbol == "AAPL.US"
    assert out.price == 195.0
    # Option-specific fields must be None
    assert out.option_type is None
    assert out.strike is None
    assert out.expiry is None


def test_option_instruction_to_out() -> None:
    inst = _make_option_instruction()
    out = instruction_to_out(inst)
    assert out.type == "option"
    assert out.ticker == "TSLA"
    assert out.option_type == "CALL"
    assert out.strike == 250.0
    assert out.expiry == date(2025, 12, 19)
    # Serialize to JSON-mode — expiry should be an ISO date string
    data = out.model_dump(mode="json")
    assert data["expiry"] == "2025-12-19"


def test_task_to_out_with_push_events() -> None:
    msg = _make_message()
    inst = _make_stock_instruction()
    task = Task(
        id=msg.id,
        type="stock",
        status=Status.FILLED,
        message=msg,
        instruction=inst,
        order_id="ord-99",
        push_events=[
            _make_push_event("evt-1"),
            _make_push_event("evt-2"),
        ],
        created_at=_NOW,
        updated_at=_NOW,
    )
    out = task_to_out(task)
    assert out.id == "msg-1"
    assert out.status == "FILLED"
    assert out.order_id == "ord-99"
    assert len(out.push_events) == 2
    assert out.push_events[0].id == "evt-1"
    assert out.push_events[1].id == "evt-2"
    assert out.instruction is not None
    assert out.instruction.type == "stock"


def test_task_to_summary_omits_push_events() -> None:
    """TaskSummaryOut must not have a push_events field at all."""
    msg = _make_message()
    task = Task(
        id=msg.id,
        type="stock",
        status=Status.INSTRUCTION_READY,
        message=msg,
        push_events=[_make_push_event("evt-1")],
        created_at=_NOW,
        updated_at=_NOW,
    )
    out = task_to_summary(task)
    assert isinstance(out, TaskSummaryOut)
    assert not hasattr(out, "push_events"), "TaskSummaryOut must NOT have push_events"
    data = out.model_dump(mode="json")
    assert "push_events" not in data


def test_instruction_out_price_range_serializes_as_tuple() -> None:
    """price_range=(26, 27) in domain → [26.0, 27.0] in JSON-mode output."""
    inst = _make_stock_instruction(price=None, price_range=(26.0, 27.0))
    out = instruction_to_out(inst)
    assert out.price_range == (26.0, 27.0)
    data = out.model_dump(mode="json")
    assert data["price_range"] == [26.0, 27.0]


def test_push_event_to_out_fields() -> None:
    evt = _make_push_event()
    out = push_event_to_out(evt)
    assert out.id == "evt-1"
    assert out.state == "FILLED"
    assert out.delta_qty == 100
    assert out.cumulative_avg_price == 195.5
    assert out.note == "filled"
