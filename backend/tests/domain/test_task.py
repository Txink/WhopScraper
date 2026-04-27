from datetime import UTC, datetime

import pytest

from app.domain.instruction import InstructionType, StockInstruction
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task


def _msg(id_: str = "msg-123") -> Message:
    return Message(
        id=id_,
        content="TSLL 26.5 加一半",
        raw_content="TSLL 26.5 加一半",
        author="big-elephant",
        posted_at=datetime(2026, 4, 25, 10, 42, 15, tzinfo=UTC),
        received_at=datetime(2026, 4, 25, 10, 42, 15, 82_000, tzinfo=UTC),
        source="stock",
    )


def _inst() -> StockInstruction:
    return StockInstruction(
        instruction_type=InstructionType.BUY,
        price=26.50,
        price_range=None,
        quantity=500,
        position_size=None,
        stop_loss_price=25.80,
        take_profit_price=None,
        context_source="group",
        parser_notes=[],
        ticker="TSLL",
        symbol="TSLL.US",
        sell_quantity=None,
    )


def test_task_id_equals_message_id():
    t = Task.new_from_message(_msg("msg-xyz"))
    assert t.id == "msg-xyz"


def test_task_starts_at_received():
    t = Task.new_from_message(_msg())
    assert t.status == Status.RECEIVED


def test_task_mark_parsing_transitions_status():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    assert t.status == Status.PARSING


def test_task_attach_instruction_sets_ready():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    t.attach_instruction(_inst())
    assert t.status == Status.INSTRUCTION_READY
    assert t.type == "stock"
    assert t.instruction is not None


def test_task_mark_parse_failed_terminal():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    t.mark_parse_failed("无法推断 ticker")
    assert t.status == Status.PARSE_ERROR
    assert t.reject_reason == "无法推断 ticker"


def test_task_append_push_event_sorted():
    t = Task.new_from_message(_msg())
    t.mark_parsing()
    t.attach_instruction(_inst())
    t.mark_submitting()
    t.mark_submitted(order_id="ord-1", timing_ms=412)
    t.append_push_event(_pe(state=PushState.NEW, order_id="ord-1"))
    t.append_push_event(_pe(state=PushState.PARTIAL, order_id="ord-1", delta_qty=100))
    assert len(t.push_events) == 2
    assert t.status == Status.PARTIAL


def test_task_illegal_status_jump_raises():
    t = Task.new_from_message(_msg())
    with pytest.raises(ValueError, match="illegal transition"):
        t.mark_submitting()  # RECEIVED → SUBMITTING 非法


def _pe(*, state: PushState, order_id: str, delta_qty: int | None = None) -> PushEvent:
    return PushEvent(
        id=f"evt-{state.value}",
        task_id="msg-123",
        order_id=order_id,
        state=state,
        received_at=datetime(2026, 4, 25, 10, 42, 15, 500_000, tzinfo=UTC),
        payload={},
        delta_qty=delta_qty,
    )


def test_task_default_is_historical_false():
    """is_historical defaults to False in new_from_message."""
    t = Task.new_from_message(_msg())
    assert t.is_historical is False


def test_task_new_from_message_accepts_is_historical_true():
    """is_historical can be set to True via new_from_message."""
    t = Task.new_from_message(_msg(), is_historical=True)
    assert t.is_historical is True
