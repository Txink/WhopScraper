"""Pydantic request/response schemas for Signal Station REST API (§7).

All *Out models are serializable via .model_dump(mode="json").
Converter functions translate app.domain.* dataclasses → Pydantic models.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from app.domain.instruction import Instruction
    from app.domain.message import Message
    from app.domain.push_event import PushEvent
    from app.domain.task import Task
    from app.whop.listener import WhopListener
    from app.whop.registry import WhopPageEntry


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------


class MessageOut(BaseModel):
    id: str
    content: str
    raw_content: str
    author: str | None
    source: str
    posted_at: datetime
    received_at: datetime
    quoted_message_id: str | None


# ---------------------------------------------------------------------------
# Instruction (stock + option unified)
# ---------------------------------------------------------------------------


class InstructionOut(BaseModel):
    """Union serializer for Stock/Option — carries a discriminator field."""

    type: str = Field(..., description="stock | option")
    instruction_type: str
    price: float | None
    price_range: tuple[float, float] | None
    quantity: int | None
    position_size: str | None
    stop_loss_price: float | None
    take_profit_price: float | None
    context_source: str | None
    parser_notes: list[str]
    # Stock-only
    ticker: str | None = None
    symbol: str | None = None
    sell_quantity: str | None = None
    # Option-only
    option_type: str | None = None  # CALL | PUT
    strike: float | None = None
    expiry: date | None = None


# ---------------------------------------------------------------------------
# PushEvent
# ---------------------------------------------------------------------------


class PushEventOut(BaseModel):
    id: str
    task_id: str
    order_id: str
    state: str
    received_at: datetime
    delta_qty: int | None
    delta_price: float | None
    cumulative_qty: int | None
    cumulative_avg_price: float | None
    note: str | None


# ---------------------------------------------------------------------------
# Task (full detail)
# ---------------------------------------------------------------------------


class TaskOut(BaseModel):
    id: str
    type: str
    status: str
    order_id: str | None
    stage_timings: dict[str, float]
    created_at: datetime
    updated_at: datetime
    reject_reason: str | None
    message: MessageOut
    instruction: InstructionOut | None
    push_events: list[PushEventOut]


# ---------------------------------------------------------------------------
# Task list (push_events intentionally omitted for performance)
# ---------------------------------------------------------------------------


class TaskSummaryOut(BaseModel):
    id: str
    type: str
    status: str
    order_id: str | None
    stage_timings: dict[str, float]
    created_at: datetime
    updated_at: datetime
    reject_reason: str | None
    message: MessageOut
    instruction: InstructionOut | None
    # push_events intentionally NOT included — call /api/tasks/{id} for full detail


class TaskListOut(BaseModel):
    tasks: list[TaskSummaryOut]
    next_cursor: datetime | None = None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class StatsTodayOut(BaseModel):
    msg_count: int
    parse_ok: int
    parse_rate: float
    orders: int
    filled: int
    rejected: int


# ---------------------------------------------------------------------------
# Positions
# ---------------------------------------------------------------------------


class PositionOut(BaseModel):
    symbol: str
    type: str  # stock | option
    ticker: str
    quantity: int
    avg_cost: float | None
    option_strike: float | None = None
    option_expiry: date | None = None
    option_type: str | None = None


class PositionsOut(BaseModel):
    stocks: list[PositionOut]
    options: list[PositionOut]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthOut(BaseModel):
    whop: str  # up | down
    longport: str  # up | down
    mode: str  # paper | real
    dry_run: bool


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class CancelOk(BaseModel):
    ok: bool = True


# ---------------------------------------------------------------------------
# Whop monitoring management
# ---------------------------------------------------------------------------


class WhopPageOut(BaseModel):
    id: str
    url: str
    source: str
    name: str
    added_at: datetime
    # Live status (None when listener absent)
    running: bool
    started_at: datetime | None
    last_poll_at: datetime | None
    messages_published: int
    last_error: str | None
    # Per-page listener settings (Task D stub: dict; Task H replaces with WhopPageSettingsOut).
    settings: dict[str, Any] | None = None


class WhopPagesOut(BaseModel):
    pages: list[WhopPageOut]


class WhopPageCreate(BaseModel):
    url: str
    source: Literal["stock", "option"]
    name: str | None = None


class WhopCookieStatusOut(BaseModel):
    exists: bool
    path: str
    last_modified: datetime | None = None
    age_seconds: float | None = None


# ---------------------------------------------------------------------------
# Converters: domain dataclasses → Pydantic Out models
# ---------------------------------------------------------------------------


def message_to_out(msg: Message) -> MessageOut:
    """Convert a domain Message to MessageOut (quoted → quoted_message_id only)."""
    return MessageOut(
        id=msg.id,
        content=msg.content,
        raw_content=msg.raw_content,
        author=msg.author,
        source=msg.source,
        posted_at=msg.posted_at,
        received_at=msg.received_at,
        quoted_message_id=msg.quoted.id if msg.quoted is not None else None,
    )


def push_event_to_out(evt: PushEvent) -> PushEventOut:
    """Convert a domain PushEvent to PushEventOut."""
    return PushEventOut(
        id=evt.id,
        task_id=evt.task_id,
        order_id=evt.order_id,
        state=str(evt.state),
        received_at=evt.received_at,
        delta_qty=evt.delta_qty,
        delta_price=evt.delta_price,
        cumulative_qty=evt.cumulative_qty,
        cumulative_avg_price=evt.cumulative_avg_price,
        note=evt.note,
    )


def instruction_to_out(inst: Instruction) -> InstructionOut:
    """Convert a StockInstruction or OptionInstruction to InstructionOut.

    Imports deferred to avoid circular imports at module load time.
    """
    from app.domain.instruction import OptionInstruction, StockInstruction

    if isinstance(inst, OptionInstruction):
        return InstructionOut(
            type="option",
            instruction_type=str(inst.instruction_type),
            price=inst.price,
            price_range=inst.price_range,
            quantity=inst.quantity,
            position_size=inst.position_size,
            stop_loss_price=inst.stop_loss_price,
            take_profit_price=inst.take_profit_price,
            context_source=inst.context_source,
            parser_notes=list(inst.parser_notes),
            ticker=inst.ticker,
            symbol=inst.symbol,
            sell_quantity=None,
            option_type=str(inst.option_type),
            strike=inst.strike,
            expiry=inst.expiry,
        )
    elif isinstance(inst, StockInstruction):
        return InstructionOut(
            type="stock",
            instruction_type=str(inst.instruction_type),
            price=inst.price,
            price_range=inst.price_range,
            quantity=inst.quantity,
            position_size=inst.position_size,
            stop_loss_price=inst.stop_loss_price,
            take_profit_price=inst.take_profit_price,
            context_source=inst.context_source,
            parser_notes=list(inst.parser_notes),
            ticker=inst.ticker,
            symbol=inst.symbol,
            sell_quantity=inst.sell_quantity,
            option_type=None,
            strike=None,
            expiry=None,
        )
    else:
        # Fallback for plain Instruction base (should rarely be used directly)
        return InstructionOut(
            type="unknown",
            instruction_type=str(inst.instruction_type),
            price=inst.price,
            price_range=inst.price_range,
            quantity=inst.quantity,
            position_size=inst.position_size,
            stop_loss_price=inst.stop_loss_price,
            take_profit_price=inst.take_profit_price,
            context_source=inst.context_source,
            parser_notes=list(inst.parser_notes),
        )


def task_to_out(task: Task) -> TaskOut:
    """Convert a domain Task (with push events) to TaskOut."""
    return TaskOut(
        id=task.id,
        type=task.type,
        status=str(task.status),
        order_id=task.order_id,
        stage_timings=dict(task.stage_timings),
        created_at=task.created_at,
        updated_at=task.updated_at,
        reject_reason=task.reject_reason,
        message=message_to_out(task.message),
        instruction=instruction_to_out(task.instruction) if task.instruction is not None else None,
        push_events=[push_event_to_out(e) for e in task.push_events],
    )


def task_to_summary(task: Task) -> TaskSummaryOut:
    """Convert a domain Task to TaskSummaryOut (push_events excluded)."""
    return TaskSummaryOut(
        id=task.id,
        type=task.type,
        status=str(task.status),
        order_id=task.order_id,
        stage_timings=dict(task.stage_timings),
        created_at=task.created_at,
        updated_at=task.updated_at,
        reject_reason=task.reject_reason,
        message=message_to_out(task.message),
        instruction=instruction_to_out(task.instruction) if task.instruction is not None else None,
    )


def whop_page_to_out(
    entry: WhopPageEntry,
    listener: WhopListener | None,
) -> WhopPageOut:
    """Build WhopPageOut from a (entry, listener) pair from registry.list_pages()."""
    from app.whop.page_settings import page_settings_to_dict

    settings_dict = page_settings_to_dict(entry.settings)
    if listener is not None:
        return WhopPageOut(
            id=entry.id,
            url=entry.url,
            source=entry.source,
            name=entry.name,
            added_at=entry.added_at,
            running=listener.running,
            started_at=listener.started_at,
            last_poll_at=listener.last_poll_at,
            messages_published=listener.messages_published,
            last_error=listener.last_error,
            settings=settings_dict,
        )
    return WhopPageOut(
        id=entry.id,
        url=entry.url,
        source=entry.source,
        name=entry.name,
        added_at=entry.added_at,
        running=False,
        started_at=None,
        last_poll_at=None,
        messages_published=0,
        last_error=None,
        settings=settings_dict,
    )
