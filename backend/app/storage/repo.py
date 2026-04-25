"""Business-level CRUD for Tasks / Messages / Instructions / PushEvents.

Public surface
--------------
    save_task(session, task)               — upsert Task + linked rows
    append_push_event(session, event)      — insert PushEventRow
    load_task(session, task_id)            — load fully-hydrated Task | None
    list_tasks(session, *, ...)            — paginated, filtered Task list

Design notes
------------
- Domain classes NEVER import from app.storage.*; this module is the boundary.
- Instruction serialization is handled by private helpers _instruction_to_json /
  _instruction_from_json.
- save_task uses SQLite UPSERT (INSERT … ON CONFLICT DO UPDATE) so concurrent
  handlers for the same Task.id never race to INSERT the same row.
- list_tasks returns Tasks without push_events (empty list) for performance.
  Use load_task to get push_events for a specific Task.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.instruction import (
    Instruction,
    InstructionType,
    OptionInstruction,
    StockInstruction,
)
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import Status
from app.domain.task import Task
from app.storage.schema import InstructionRow, MessageRow, PositionRow, PushEventRow, TaskRow

# ---------------------------------------------------------------------------
# Instruction serialization helpers
# ---------------------------------------------------------------------------


def _instruction_to_json(inst: Instruction) -> dict[str, Any]:
    """Serialize an Instruction subtype to a JSON-serializable dict."""
    payload: dict[str, Any] = {
        "instruction_type": inst.instruction_type.value,
        "price": inst.price,
        "price_range": list(inst.price_range) if inst.price_range is not None else None,
        "quantity": inst.quantity,
        "position_size": inst.position_size,
        "stop_loss_price": inst.stop_loss_price,
        "take_profit_price": inst.take_profit_price,
        "context_source": inst.context_source,
        "parser_notes": list(inst.parser_notes),
    }

    if isinstance(inst, StockInstruction):
        payload["_type"] = "stock"
        payload["ticker"] = inst.ticker
        payload["symbol"] = inst.symbol
        payload["sell_quantity"] = inst.sell_quantity
    elif isinstance(inst, OptionInstruction):
        payload["_type"] = "option"
        payload["ticker"] = inst.ticker
        payload["symbol"] = inst.symbol
        payload["option_type"] = inst.option_type
        payload["strike"] = inst.strike
        payload["expiry"] = inst.expiry.isoformat()  # ISO date string
    else:
        # Fallback for plain Instruction (should not normally appear)
        payload["_type"] = "base"

    return payload


def _instruction_from_json(data: dict[str, Any]) -> Instruction:
    """Deserialize an Instruction subtype from a JSON dict."""
    type_ = data["_type"]
    instruction_type = InstructionType(data["instruction_type"])

    # price_range: list → tuple
    price_range_raw = data.get("price_range")
    price_range: tuple[float, float] | None = (
        (float(price_range_raw[0]), float(price_range_raw[1]))
        if price_range_raw is not None
        else None
    )

    common: dict[str, Any] = {
        "instruction_type": instruction_type,
        "price": data.get("price"),
        "price_range": price_range,
        "quantity": data.get("quantity"),
        "position_size": data.get("position_size"),
        "stop_loss_price": data.get("stop_loss_price"),
        "take_profit_price": data.get("take_profit_price"),
        "context_source": data.get("context_source"),
        "parser_notes": data.get("parser_notes", []),
    }

    if type_ == "stock":
        return StockInstruction(
            **common,
            ticker=data["ticker"],
            symbol=data.get("symbol", ""),
            sell_quantity=data.get("sell_quantity"),
        )
    elif type_ == "option":
        return OptionInstruction(
            **common,
            ticker=data["ticker"],
            symbol=data.get("symbol", ""),
            option_type=data["option_type"],
            strike=float(data["strike"]),
            expiry=date.fromisoformat(data["expiry"]),
        )
    else:
        raise ValueError(f"Unknown instruction _type: {type_!r}")


# ---------------------------------------------------------------------------
# Row ↔ Domain conversion helpers
# ---------------------------------------------------------------------------


def _task_to_row(task: Task) -> TaskRow:
    """Convert a Task domain object to a TaskRow for persistence."""
    inst = task.instruction
    ticker: str | None = None
    symbol: str | None = None
    side: str | None = None
    price: float | None = None
    quantity: int | None = None

    if isinstance(inst, (StockInstruction, OptionInstruction)):
        ticker = inst.ticker
        symbol = inst.symbol
        side = inst.instruction_type.value
        price = inst.price
        quantity = inst.quantity

    return TaskRow(
        id=task.id,
        type=task.type,
        status=task.status.value,
        order_id=task.order_id,
        ticker=ticker,
        symbol=symbol,
        side=side,
        price=price,
        quantity=quantity,
        reject_reason=task.reject_reason,
        stage_timings_json=dict(task.stage_timings) if task.stage_timings else None,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _message_to_row(msg: Message) -> MessageRow:
    """Convert a Message domain object to a MessageRow."""
    return MessageRow(
        id=msg.id,
        content=msg.content,
        raw_content=msg.raw_content,
        author=msg.author,
        source=msg.source,
        posted_at=msg.posted_at,
        received_at=msg.received_at,
        quoted_message_id=msg.quoted.id if msg.quoted is not None else None,
    )


def _push_event_to_row(evt: PushEvent) -> PushEventRow:
    """Convert a PushEvent domain object to a PushEventRow."""
    return PushEventRow(
        id=evt.id,
        task_id=evt.task_id,
        order_id=evt.order_id,
        state=evt.state.value,
        received_at=evt.received_at,
        delta_qty=evt.delta_qty,
        delta_price=evt.delta_price,
        cumulative_qty=evt.cumulative_qty,
        cumulative_avg_price=evt.cumulative_avg_price,
        note=evt.note,
        payload_json=dict(evt.payload),
    )


def _row_to_message(row: MessageRow) -> Message:
    """Hydrate a Message from a MessageRow.

    quoted is always None on load (no recursive resolution).
    history_hint is always [] on load (recomputed on demand).
    """
    return Message(
        id=row.id,
        content=row.content,
        raw_content=row.raw_content,
        author=row.author,
        posted_at=_ensure_utc(row.posted_at),
        received_at=_ensure_utc(row.received_at),
        source=row.source,  # type: ignore[arg-type]
        quoted=None,
        history_hint=[],
    )


def _row_to_push_event(row: PushEventRow) -> PushEvent:
    """Hydrate a PushEvent from a PushEventRow."""
    return PushEvent(
        id=row.id,
        task_id=row.task_id,
        order_id=row.order_id,
        state=PushState(row.state),
        received_at=_ensure_utc(row.received_at),
        payload=dict(row.payload_json),
        delta_qty=row.delta_qty,
        delta_price=row.delta_price,
        cumulative_qty=row.cumulative_qty,
        cumulative_avg_price=row.cumulative_avg_price,
        note=row.note,
    )


def _rows_to_task(
    task_row: TaskRow,
    msg_row: MessageRow,
    inst_row: InstructionRow | None,
    push_rows: list[PushEventRow],
) -> Task:
    """Assemble a fully-hydrated Task from ORM rows."""
    message = _row_to_message(msg_row)

    instruction: Instruction | None = None
    if inst_row is not None:
        instruction = _instruction_from_json(dict(inst_row.payload_json))

    push_events = [_row_to_push_event(r) for r in push_rows]

    return Task(
        id=task_row.id,
        type=task_row.type,  # type: ignore[arg-type]
        status=Status(task_row.status),
        message=message,
        instruction=instruction,
        order_id=task_row.order_id,
        push_events=push_events,
        stage_timings=dict(task_row.stage_timings_json) if task_row.stage_timings_json else {},
        created_at=_ensure_utc(task_row.created_at),
        updated_at=_ensure_utc(task_row.updated_at),
        reject_reason=task_row.reject_reason,
    )


def _ensure_utc(dt: datetime) -> datetime:
    """Attach UTC tzinfo if the datetime is naive (SQLite returns naive datetimes)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


# ---------------------------------------------------------------------------
# Public repo functions
# ---------------------------------------------------------------------------


_TASK_UPDATE_COLS = (
    "type",
    "status",
    "order_id",
    "ticker",
    "symbol",
    "side",
    "price",
    "quantity",
    "reject_reason",
    "stage_timings_json",
    "updated_at",
)

_INSTRUCTION_UPDATE_COLS = (
    "instruction_type",
    "context_source",
    "payload_json",
)


async def save_task(session: AsyncSession, task: Task) -> None:
    """Upsert a Task and its linked Message / Instruction rows.

    Uses SQLite's ``INSERT … ON CONFLICT DO UPDATE`` (UPSERT) for all three
    tables so concurrent callers with the same ``Task.id`` never race to INSERT
    the same primary key.

    tasks:        ON CONFLICT → overwrite all mutable columns (last-writer-wins)
    messages:     ON CONFLICT → DO NOTHING  (messages are immutable after first write)
    instructions: ON CONFLICT → overwrite all columns (re-parse may change the instruction)
    """
    inst = task.instruction
    ticker: str | None = None
    symbol: str | None = None
    side: str | None = None
    price: float | None = None
    quantity: int | None = None

    if isinstance(inst, (StockInstruction, OptionInstruction)):
        ticker = inst.ticker
        symbol = inst.symbol
        side = inst.instruction_type.value
        price = inst.price
        quantity = inst.quantity

    task_values: dict[str, Any] = {
        "id": task.id,
        "type": task.type,
        "status": task.status.value,
        "order_id": task.order_id,
        "ticker": ticker,
        "symbol": symbol,
        "side": side,
        "price": price,
        "quantity": quantity,
        "reject_reason": task.reject_reason,
        "stage_timings_json": dict(task.stage_timings) if task.stage_timings else None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }

    # --- tasks UPSERT ---
    task_stmt = sqlite_insert(TaskRow).values(**task_values)
    task_stmt = task_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={col: task_stmt.excluded[col] for col in _TASK_UPDATE_COLS},
    )
    await session.execute(task_stmt)
    await session.flush()

    # --- messages UPSERT (DO NOTHING on conflict — messages are immutable) ---
    msg = task.message
    msg_values: dict[str, Any] = {
        "id": msg.id,
        "content": msg.content,
        "raw_content": msg.raw_content,
        "author": msg.author,
        "source": msg.source,
        "posted_at": msg.posted_at,
        "received_at": msg.received_at,
        "quoted_message_id": msg.quoted.id if msg.quoted is not None else None,
    }
    msg_stmt = sqlite_insert(MessageRow).values(**msg_values)
    msg_stmt = msg_stmt.on_conflict_do_nothing(index_elements=["id"])
    await session.execute(msg_stmt)

    # --- instructions UPSERT (overwrite on conflict — re-parse changes content) ---
    if task.instruction is not None:
        inst_values: dict[str, Any] = {
            "task_id": task.id,
            "instruction_type": task.instruction.instruction_type.value,
            "context_source": task.instruction.context_source,
            "payload_json": _instruction_to_json(task.instruction),
        }
        inst_stmt = sqlite_insert(InstructionRow).values(**inst_values)
        inst_stmt = inst_stmt.on_conflict_do_update(
            index_elements=["task_id"],
            set_={col: inst_stmt.excluded[col] for col in _INSTRUCTION_UPDATE_COLS},
        )
        await session.execute(inst_stmt)

    await session.flush()
    await session.commit()


async def append_push_event(session: AsyncSession, event: PushEvent) -> None:
    """Insert a single PushEventRow.  Caller is responsible for FK validity."""
    row = _push_event_to_row(event)
    session.add(row)
    await session.commit()


async def load_task(session: AsyncSession, task_id: str) -> Task | None:
    """Load a fully-hydrated Task by id, including push_events.

    Returns None if the task_id doesn't exist.
    Two queries:
      1. tasks + messages + instructions (via separate gets)
      2. push_events ordered by received_at ASC
    """
    task_row = await session.get(TaskRow, task_id)
    if task_row is None:
        return None

    msg_row = await session.get(MessageRow, task_id)
    if msg_row is None:
        # Data integrity issue — messages row missing for existing task
        return None

    inst_row = await session.get(InstructionRow, task_id)

    # Fetch push events ordered by received_at ASC
    result = await session.execute(
        select(PushEventRow)
        .where(PushEventRow.task_id == task_id)
        .order_by(PushEventRow.received_at.asc())
    )
    push_rows = list(result.scalars().all())

    return _rows_to_task(task_row, msg_row, inst_row, push_rows)


async def load_task_by_order_id(session: AsyncSession, order_id: str) -> Task | None:
    """Load Task by order_id (denormalized column on tasks table).

    Returns None if no Task with the given order_id exists.
    """
    result = await session.execute(
        select(TaskRow).where(TaskRow.order_id == order_id)
    )
    task_row = result.scalar_one_or_none()
    if task_row is None:
        return None
    return await load_task(session, task_row.id)


async def list_tasks(
    session: AsyncSession,
    *,
    limit: int = 50,
    cursor_created_at: datetime | None = None,
    status: Status | None = None,
    type_: str | None = None,
    symbol: str | None = None,
) -> list[Task]:
    """Return a paginated, filtered list of Tasks.

    Performance note: push_events is NOT loaded for list results.
    Use load_task(id) to access push_events for a specific Task.

    Pagination: cursor_created_at is a "less-than" cursor.
    First call: cursor_created_at=None (no filter, returns newest N).
    Next pages: pass the last item's created_at as cursor_created_at.
    """
    stmt = select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit)

    if cursor_created_at is not None:
        # Strip timezone for comparison with SQLite's naive stored datetimes
        cursor_naive = cursor_created_at.replace(tzinfo=None)
        stmt = stmt.where(TaskRow.created_at < cursor_naive)

    if status is not None:
        stmt = stmt.where(TaskRow.status == status.value)

    if type_ is not None:
        stmt = stmt.where(TaskRow.type == type_)

    if symbol is not None:
        stmt = stmt.where(TaskRow.symbol == symbol)

    result = await session.execute(stmt)
    task_rows = list(result.scalars().all())

    tasks: list[Task] = []
    for task_row in task_rows:
        msg_row = await session.get(MessageRow, task_row.id)
        if msg_row is None:
            continue  # skip corrupt rows
        inst_row = await session.get(InstructionRow, task_row.id)
        tasks.append(_rows_to_task(task_row, msg_row, inst_row, []))

    return tasks


async def stats_today(session: AsyncSession) -> dict[str, int]:
    """Return task counts grouped by status for the current UTC calendar day.

    Keys in the returned dict:
      - ``msg_count``  — total tasks created today
      - ``parse_ok``   — tasks that advanced past parsing (any post-parse status)
      - ``orders``     — tasks that produced a brokerage order (PENDING and beyond)
      - ``filled``     — tasks with status FILLED
      - ``rejected``   — tasks that failed broadly (PARSE_ERROR | SUBMIT_FAILED | REJECTED)
    """
    today_start = datetime.combine(date.today(), time.min, tzinfo=UTC)
    # Strip timezone so the comparison works against SQLite's naive UTC datetimes.
    today_start_naive = today_start.replace(tzinfo=None)

    result = await session.execute(
        select(TaskRow.status, func.count(TaskRow.id))
        .where(TaskRow.created_at >= today_start_naive)
        .group_by(TaskRow.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in result.all()}

    _parse_ok_statuses: frozenset[str] = frozenset({
        Status.INSTRUCTION_READY.value,
        Status.SUBMITTING.value,
        Status.PENDING.value,
        Status.PARTIAL.value,
        Status.FILLED.value,
        Status.CANCELLED.value,
        Status.REJECTED.value,
        Status.SUBMIT_FAILED.value,
        Status.SKIPPED.value,
    })
    _orders_statuses: frozenset[str] = frozenset({
        Status.PENDING.value,
        Status.PARTIAL.value,
        Status.FILLED.value,
        Status.CANCELLED.value,
        Status.REJECTED.value,
    })
    _rejected_statuses: frozenset[str] = frozenset({
        Status.PARSE_ERROR.value,
        Status.SUBMIT_FAILED.value,
        Status.REJECTED.value,
    })

    total = sum(counts.values())
    return {
        "msg_count": total,
        "parse_ok": sum(v for k, v in counts.items() if k in _parse_ok_statuses),
        "orders": sum(v for k, v in counts.items() if k in _orders_statuses),
        "filled": counts.get(Status.FILLED.value, 0),
        "rejected": sum(v for k, v in counts.items() if k in _rejected_statuses),
    }


async def list_positions(session: AsyncSession) -> list[PositionRow]:
    """Return all PositionRows ordered by symbol."""
    result = await session.execute(select(PositionRow).order_by(PositionRow.symbol))
    return list(result.scalars())
