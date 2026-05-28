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

from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.instruction import (
    Instruction,
    InstructionType,
    OptionInstruction,
    StockInstruction,
)
from app.broker.order_id_norm import normalize_broker_order_id
from app.domain.message import Message
from app.domain.push_event import PushEvent, PushState
from app.domain.status import TERMINAL, Status
from app.domain.task import Task
from app.storage.schema import (
    BrokerExecutionRow,
    ChatMessageRow,
    InstructionRow,
    MessageRow,
    PositionRow,
    PushEventRow,
    TaskRow,
    TPairRow,
)

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
        "referenced_lot_price": inst.referenced_lot_price,  # ← new
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
        "referenced_lot_price": data.get("referenced_lot_price"),  # ← new
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
        is_historical=task.is_historical,
        submit_order_type=task.submit_order_type,
        submit_order_context=task.submit_order_context,
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
        url=msg.url,
        quoted_message_id=msg.quoted.id if msg.quoted is not None else None,
        image_filename=msg.image_filename,
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
        submitted_price=evt.submitted_price,
        submitted_quantity=evt.submitted_quantity,
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
        url=row.url,
        image_filename=row.image_filename,
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
        submitted_price=row.submitted_price,
        submitted_quantity=row.submitted_quantity,
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
        is_historical=task_row.is_historical,
        submit_order_type=task_row.submit_order_type,
        submit_order_context=task_row.submit_order_context,
        submit_quote_last_done=task_row.submit_quote_last_done,
        submit_price=task_row.submit_price,
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
    "is_historical",
    "stage_timings_json",
    "updated_at",
    "submit_order_type",
    "submit_order_context",
    "submit_quote_last_done",
    "submit_price",
)

_INSTRUCTION_UPDATE_COLS = (
    "instruction_type",
    "context_source",
    "payload_json",
)

# String values of the terminal statuses, for SQL WHERE clauses that
# prevent a terminal row from being overwritten by a stale non-terminal
# update (race protection — see save_task).
_TERMINAL_STATUS_VALUES = frozenset(s.value for s in TERMINAL)


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
        "is_historical": task.is_historical,
        "stage_timings_json": dict(task.stage_timings) if task.stage_timings else None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "submit_order_type": task.submit_order_type,
        "submit_order_context": task.submit_order_context,
        "submit_quote_last_done": task.submit_quote_last_done,
        "submit_price": task.submit_price,
    }

    # --- tasks UPSERT ---
    # Race protection: refuse the UPDATE branch when the existing row is
    # already at a terminal status. This prevents a slow / out-of-order push
    # handler from overwriting (e.g.) REJECTED with PENDING when two SDK
    # pushes for the same order_id arrive within milliseconds and their
    # _handle_raw_push coroutines race. INSERT (new row) is always allowed.
    task_stmt = sqlite_insert(TaskRow).values(**task_values)
    task_stmt = task_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={col: task_stmt.excluded[col] for col in _TASK_UPDATE_COLS},
        where=TaskRow.status.notin_(_TERMINAL_STATUS_VALUES),
    )
    await session.execute(task_stmt)
    await session.flush()

    # --- messages UPSERT ---
    msg = task.message
    msg_values: dict[str, Any] = {
        "id": msg.id,
        "content": msg.content,
        "raw_content": msg.raw_content,
        "author": msg.author,
        "source": msg.source,
        "posted_at": msg.posted_at,
        "received_at": msg.received_at,
        "url": msg.url,
        "quoted_message_id": msg.quoted.id if msg.quoted is not None else None,
        "image_filename": msg.image_filename,
    }
    # Messages are immutable except for `url`, which we backfill when the existing
    # row had no url. This handles the case where messages were persisted before the
    # `messages.url` column was wired up by the listener — when the listener
    # republishes the same domID with a proper url, we want that url to land.
    msg_stmt = sqlite_insert(MessageRow).values(**msg_values)
    msg_stmt = msg_stmt.on_conflict_do_update(
        index_elements=["id"],
        set_={"url": msg_stmt.excluded.url},
        where=MessageRow.url.is_(None),
    )
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
    oid = normalize_broker_order_id(order_id)
    if not oid:
        return None
    result = await session.execute(select(TaskRow).where(TaskRow.order_id == oid))
    task_row = result.scalar_one_or_none()
    if task_row is None:
        return None
    return await load_task(session, task_row.id)


async def find_recent_task_by_ref(
    session: AsyncSession,
    *,
    ticker: str,
    side: InstructionType,
    price: float,
    before: datetime,
    window_hours: int = 24 * 7,
) -> int | None:
    """Find the most recent submitted task whose ticker/side/price match.

    Used by the trader to resolve "lot @<price>" references in messages like
    "12.87 减一半 12.42 的 tsll" — looks up the prior reverse-side task and
    returns its planned quantity.

    Filters:
    - ticker exact match
    - side exact match (caller passes the *opposite* of current instruction)
    - ABS(price - :price) < 0.0001 (decision 7: strict exact)
    - order_id IS NOT NULL (decision 4: only tasks that submitted to broker)
    - created_at in (before - window_hours, before) — strict open interval

    Returns the matched task's `quantity`, or None if no row matches.
    """
    cutoff = before - timedelta(hours=window_hours)
    stmt = (
        select(TaskRow.quantity)
        .where(
            TaskRow.ticker == ticker,
            TaskRow.side == side.value,
            func.abs(TaskRow.price - price) < 0.0001,
            TaskRow.order_id.is_not(None),
            TaskRow.created_at < before,
            TaskRow.created_at >= cutoff,
        )
        .order_by(TaskRow.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_tasks(
    session: AsyncSession,
    *,
    limit: int = 50,
    cursor_created_at: datetime | None = None,
    status: Status | None = None,
    type_: str | None = None,
    symbol: str | None = None,
    ticker: str | None = None,
    statuses: list[Status] | None = None,
    urls: list[str] | None = None,
    posted_at_start: datetime | None = None,
    posted_at_end: datetime | None = None,
) -> list[Task]:
    """Return a paginated, filtered list of Tasks.

    Performance note: push_events is NOT loaded for list results.
    Use load_task(id) to access push_events for a specific Task.

    Pagination: cursor_created_at is a "less-than" cursor.
    First call: cursor_created_at=None (no filter, returns newest N).
    Next pages: pass the last item's created_at as cursor_created_at.

    ``ticker`` filters TaskRow.ticker (the user-facing equity symbol like
    "TSLA"), as opposed to ``symbol`` which matches the broker-canonical form
    (e.g. "TSLA.US"). Pass at most one of these. ``statuses`` accepts a list
    of allowed statuses (used by the /api/trades endpoint to capture both
    FILLED and PARTIAL with one query).

    ``urls``: filter to tasks whose ``message.url`` is in the list.
    None = no filter. Empty list = short-circuit to [] (match nothing).

    ``posted_at_start`` / ``posted_at_end``: half-open [start, end) window
    on ``message.posted_at``. Either bound is optional.
    """
    # Short-circuit BEFORE building any SQL — if the caller asked for "no
    # urls allowed", they should get nothing, not "no filter applied".
    if urls is not None and len(urls) == 0:
        return []

    stmt = select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit)

    if cursor_created_at is not None:
        # Strip timezone for comparison with SQLite's naive stored datetimes
        cursor_naive = cursor_created_at.replace(tzinfo=None)
        stmt = stmt.where(TaskRow.created_at < cursor_naive)

    if statuses is not None:
        stmt = stmt.where(TaskRow.status.in_([s.value for s in statuses]))
    elif status is not None:
        stmt = stmt.where(TaskRow.status == status.value)

    if type_ is not None:
        stmt = stmt.where(TaskRow.type == type_)

    if symbol is not None:
        stmt = stmt.where(TaskRow.symbol == symbol)

    if ticker is not None:
        stmt = stmt.where(TaskRow.ticker == ticker)

    # Join MessageRow only when needed — the per-task hydrate loop below
    # always re-fetches MessageRow individually anyway, so adding a join
    # at the WHERE level just gates which TaskRow ids come back.
    needs_msg_join = (
        urls is not None
        or posted_at_start is not None
        or posted_at_end is not None
    )
    if needs_msg_join:
        stmt = stmt.join(MessageRow, MessageRow.id == TaskRow.id)
        if urls is not None:
            stmt = stmt.where(MessageRow.url.in_(urls))
        if posted_at_start is not None:
            stmt = stmt.where(
                MessageRow.posted_at >= posted_at_start.replace(tzinfo=None)
            )
        if posted_at_end is not None:
            stmt = stmt.where(
                MessageRow.posted_at < posted_at_end.replace(tzinfo=None)
            )

    result = await session.execute(stmt)
    task_rows = list(result.scalars().all())

    tasks: list[Task] = []
    for task_row in task_rows:
        msg_row = await session.get(MessageRow, task_row.id)
        if msg_row is None:
            continue  # skip corrupt rows
        inst_row = await session.get(InstructionRow, task_row.id)
        tasks.append(_rows_to_task(task_row, msg_row, inst_row, []))

    # Hydrate the latest push event per task so task_to_summary can populate
    # the collapsed-card display fields (last_cum_qty / last_cum_avg_price /
    # last_submitted_*). Single batched query, indexed on (task_id, received_at).
    if tasks:
        latest = await latest_push_per_task(session, [t.id for t in tasks])
        for t in tasks:
            evt = latest.get(t.id)
            if evt is not None:
                t.push_events = [evt]

    return tasks


async def latest_push_per_task(
    session: AsyncSession, task_ids: list[str]
) -> dict[str, PushEvent]:
    """Return ``{task_id: latest_push_event}`` for the given task ids.

    Used by the /api/tasks list endpoint so the collapsed card can show
    real fill / post-modify state without fetching full per-task detail.
    Single query over the (task_id, received_at) index — no N+1.
    """
    if not task_ids:
        return {}
    stmt = (
        select(PushEventRow)
        .where(PushEventRow.task_id.in_(task_ids))
        .order_by(PushEventRow.task_id, PushEventRow.received_at.asc())
    )
    result = await session.execute(stmt)
    latest: dict[str, PushEvent] = {}
    for row in result.scalars().all():
        # ASC order means the last seen for each task_id is its latest push.
        latest[row.task_id] = _row_to_push_event(row)
    return latest


async def count_tasks(
    session: AsyncSession,
    *,
    status: Status | None = None,
    type_: str | None = None,
    symbol: str | None = None,
) -> int:
    """Return total task count for the same filters as list_tasks."""
    stmt = select(func.count(TaskRow.id))

    if status is not None:
        stmt = stmt.where(TaskRow.status == status.value)
    if type_ is not None:
        stmt = stmt.where(TaskRow.type == type_)
    if symbol is not None:
        stmt = stmt.where(TaskRow.symbol == symbol)

    result = await session.execute(stmt)
    return int(result.scalar_one())


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

    _parse_ok_statuses: frozenset[str] = frozenset(
        {
            Status.INSTRUCTION_READY.value,
            Status.SUBMITTING.value,
            Status.PENDING.value,
            Status.PARTIAL.value,
            Status.FILLED.value,
            Status.CANCELLED.value,
            Status.REJECTED.value,
            Status.SUBMIT_FAILED.value,
            Status.SKIPPED.value,
        }
    )
    _orders_statuses: frozenset[str] = frozenset(
        {
            Status.PENDING.value,
            Status.PARTIAL.value,
            Status.FILLED.value,
            Status.CANCELLED.value,
            Status.REJECTED.value,
        }
    )
    _rejected_statuses: frozenset[str] = frozenset(
        {
            Status.PARSE_ERROR.value,
            Status.SUBMIT_FAILED.value,
            Status.REJECTED.value,
        }
    )

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


async def list_positions_for_account(
    session: AsyncSession,
    *,
    account_id: str,
    include_zero_qty: bool = False,
) -> list[PositionRow]:
    """Return positions for ``account_id``. Sold-off rows (qty=0) are filtered
    by default — we keep them in the table so ``history_synced`` survives
    close/re-open cycles, but the dashboard only wants current holdings."""
    stmt = (
        select(PositionRow)
        .where(PositionRow.account_id == account_id)
        .order_by(PositionRow.symbol)
    )
    if not include_zero_qty:
        stmt = stmt.where(PositionRow.quantity > 0)
    result = await session.execute(stmt)
    return list(result.scalars())


async def upsert_positions(
    session: AsyncSession,
    *,
    account_id: str,
    rows: list[dict[str, Any]],
) -> int:
    """Upsert the broker's current positions for ``account_id``.

    Each row mirrors ``broker.stock_positions()`` output (broker emits
    both stock and option contracts under the same channel — option
    symbols carry OCC suffix). Symbols not present in ``rows`` are
    zeroed out (``quantity = 0``) rather than deleted so the
    ``history_synced`` flag survives close/re-open of the same ticker.

    Returns the number of rows the broker reported for this account.
    """
    from app.broker.symbol_classify import parse_option_symbol

    now = datetime.now(UTC)
    seen_symbols: set[str] = set()
    payloads: list[dict[str, Any]] = []
    for r in rows:
        symbol = str(r.get("symbol") or "")
        if not symbol:
            continue
        seen_symbols.add(symbol)
        option_leg = parse_option_symbol(symbol)
        if option_leg is not None:
            pos_type = "option"
            ticker = option_leg.ticker
            strike: float | None = option_leg.strike
            # ``OptionLeg.expiry`` is an ISO string ("YYYY-MM-DD"); the DB
            # column wants ``date``.
            expiry: date | None = date.fromisoformat(option_leg.expiry)
            cp: str | None = option_leg.cp
        else:
            pos_type = "stock"
            ticker = str(r.get("ticker") or "") or (
                symbol.split(".")[0] if "." in symbol else symbol
            )
            strike = None
            expiry = None
            cp = None
        avg_raw = r.get("avg_cost")
        try:
            avg_cost = float(avg_raw) if avg_raw is not None else None
        except (TypeError, ValueError):
            avg_cost = None
        payloads.append({
            "account_id": account_id,
            "symbol": symbol,
            "type": pos_type,
            "ticker": ticker,
            "quantity": int(r.get("quantity", 0) or 0),
            "avg_cost": avg_cost,
            "option_strike": strike,
            "option_expiry": expiry,
            "option_type": cp,
            "updated_at": now,
        })

    if payloads:
        stmt = sqlite_insert(PositionRow).values(payloads)
        stmt = stmt.on_conflict_do_update(
            index_elements=["account_id", "symbol"],
            set_={
                "type": stmt.excluded.type,
                "ticker": stmt.excluded.ticker,
                "quantity": stmt.excluded.quantity,
                "avg_cost": stmt.excluded.avg_cost,
                "option_strike": stmt.excluded.option_strike,
                "option_expiry": stmt.excluded.option_expiry,
                "option_type": stmt.excluded.option_type,
                "updated_at": stmt.excluded.updated_at,
                # NOTE: history_synced / restore_pair_tags intentionally NOT
                # in set_ — owned by the executions-sync / wipe paths;
                # refreshing the holdings snapshot must not reset them.
            },
        )
        await session.execute(stmt)

    # Zero out rows that the broker no longer reports for this account.
    zeroed_stmt = (
        PositionRow.__table__.update()
        .where(PositionRow.account_id == account_id)
        .where(PositionRow.quantity > 0)
    )
    if seen_symbols:
        zeroed_stmt = zeroed_stmt.where(~PositionRow.symbol.in_(seen_symbols))
    zeroed_stmt = zeroed_stmt.values(quantity=0, updated_at=now)
    await session.execute(zeroed_stmt)

    await session.commit()
    return len(payloads)


async def is_position_history_synced(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str,
) -> bool:
    """True iff any positions row for ``(account_id, ticker)`` carries
    ``history_synced = True``.

    Per-ticker rather than per-symbol: a backfill call covers both stock
    and option contracts on the same ticker in one broker request, so any
    matching row carrying the flag implies the whole ticker is synced.
    """
    stmt = (
        select(func.count())
        .select_from(PositionRow)
        .where(PositionRow.account_id == account_id)
        .where(PositionRow.ticker == ticker)
        .where(PositionRow.history_synced.is_(True))
    )
    result = await session.execute(stmt)
    return (result.scalar() or 0) > 0


async def position_needs_restore_pair_tags(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str,
) -> bool:
    """True iff any positions row for ``(account_id, ticker)`` requests
    a one-shot ``t_pair_tags`` rebuild after the next full backfill."""
    stmt = (
        select(func.count())
        .select_from(PositionRow)
        .where(PositionRow.account_id == account_id)
        .where(PositionRow.ticker == ticker)
        .where(PositionRow.restore_pair_tags.is_(True))
    )
    result = await session.execute(stmt)
    return (result.scalar() or 0) > 0


async def clear_restore_pair_tags(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str,
) -> int:
    """Clear ``restore_pair_tags`` on every row for ``(account_id, ticker)``."""
    stmt = (
        PositionRow.__table__.update()
        .where(PositionRow.account_id == account_id)
        .where(PositionRow.ticker == ticker)
        .values(restore_pair_tags=False)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def restore_pair_tags_from_pairs(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str,
) -> int:
    """Rebuild ``broker_executions.t_pair_tags`` from ``t_pairs`` allocations.

    Called after a full chunked backfill when ``restore_pair_tags`` was set
    by ``delete_broker_executions_for_ticker``. Returns the number of pairs
    reconciled. Clears the flag on success.
    """
    pairs = await list_pairs(session, ticker=ticker, account_id=account_id)
    for pair in pairs:
        await _sync_pair_tags(
            session,
            pair_id=pair.id,
            old_buys=[],
            old_sells=[],
            new_buys=list(pair.buys_json or []),
            new_sells=list(pair.sells_json or []),
        )
    await clear_restore_pair_tags(session, account_id=account_id, ticker=ticker)
    await session.commit()
    return len(pairs)


async def mark_position_history_synced(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str,
) -> int:
    """Set ``history_synced = True`` on every positions row matching
    ``(account_id, ticker)``. Returns the count of rows updated.

    Called by the executions-sync path after a full chunked backfill
    completes successfully for the ticker.
    """
    stmt = (
        PositionRow.__table__.update()
        .where(PositionRow.account_id == account_id)
        .where(PositionRow.ticker == ticker)
        .values(history_synced=True)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount or 0


def _canonicalize_url(url: str | None) -> str | None:
    """Normalize a Whop URL for case + trailing-slash insensitive comparison.

    Whop's routes are case-insensitive (``/joined/X`` and ``/Joined/X``
    resolve to the same page) and the user-typed URL may or may not carry
    a trailing slash. Lowercasing ``scheme`` + ``netloc`` covers protocol
    + host; lowercasing ``path`` covers the route segments; ``rstrip("/")``
    folds the trailing-slash variant. Query and fragment are dropped — the
    persisted "page URL" never carries them in our usage.
    """
    if url is None:
        return None
    s = str(url).strip()
    if not s:
        return None
    p = urlsplit(s)
    path = (p.path or "").lower().rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


async def load_seen_ids_for_url(session: AsyncSession, url: str) -> set[str]:
    """SELECT id FROM messages WHERE url=? — 用于 listener 启动时去重灌 _seen。

    返回该 url 对应所有已落库的 message id 集合（即 task id，因为 task.id = message.id）。
    """
    canonical = _canonicalize_url(url)
    if canonical is None:
        return set()
    result = await session.execute(select(MessageRow.id, MessageRow.url).where(MessageRow.url.is_not(None)))
    return {
        msg_id
        for msg_id, raw_url in result.all()
        if _canonicalize_url(raw_url) == canonical
    }


async def delete_tasks_by_url(session: AsyncSession, url: str | None) -> int:
    """Delete all tasks (and linked instructions/push_events/messages) for a given url.

    Returns the count of tasks deleted.

    url=None matches legacy rows where messages.url is NULL (pre-migration data).
    SQL `=` never matches NULL, so callers wanting to clean those up must pass
    None and we translate that into ``WHERE url IS NULL``.

    We intentionally delete ``messages`` explicitly (instead of relying solely on
    FK cascade) so cleanup remains correct even if SQLite FK enforcement is off.
    instructions and push_events also require explicit deletion.
    """
    # Find affected task ids (task.id == message.id)
    if url is None:
        result = await session.execute(select(MessageRow.id).where(MessageRow.url.is_(None)))
        task_ids = [r[0] for r in result.all()]
    else:
        canonical = _canonicalize_url(url)
        if canonical is None:
            return 0
        result = await session.execute(select(MessageRow.id, MessageRow.url).where(MessageRow.url.is_not(None)))
        task_ids = [
            msg_id
            for msg_id, raw_url in result.all()
            if _canonicalize_url(raw_url) == canonical
        ]
    if not task_ids:
        return 0

    # Delete push_events (no cascade)
    await session.execute(
        sa_delete(PushEventRow).where(PushEventRow.task_id.in_(task_ids))
    )
    # Delete instructions (no cascade)
    await session.execute(
        sa_delete(InstructionRow).where(InstructionRow.task_id.in_(task_ids))
    )
    # Delete tasks
    await session.execute(sa_delete(TaskRow).where(TaskRow.id.in_(task_ids)))
    # Delete messages explicitly (defensive against FK pragma being disabled).
    await session.execute(sa_delete(MessageRow).where(MessageRow.id.in_(task_ids)))
    await session.commit()
    return len(task_ids)


# ---------------------------------------------------------------------------
# t_pairs (做T 配对) CRUD + FIFO allocation helpers
# ---------------------------------------------------------------------------


def allocate_fifo(
    trade_ids: list[str],
    trade_qty: dict[str, int],
    already_allocated: dict[str, int],
    target: int,
) -> list[dict[str, Any]]:
    """Allocate up to ``target`` qty across trades, FIFO in the given order.

    Each trade contributes at most ``trade_qty[id] - already_allocated[id]``.
    Returns ``[{"trade_id", "qty"}, ...]`` skipping trades with zero
    availability and stops once ``target`` is satisfied.
    """
    out: list[dict[str, Any]] = []
    remaining = target
    for tid in trade_ids:
        if remaining <= 0:
            break
        avail = trade_qty.get(tid, 0) - already_allocated.get(tid, 0)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        out.append({"trade_id": tid, "qty": int(take)})
        remaining -= take
    return out


def aggregate_allocated(pairs: list[TPairRow]) -> dict[str, int]:
    """Sum allocated qty per trade_id across the given pairs (both sides)."""
    out: dict[str, int] = {}
    for p in pairs:
        for a in (p.buys_json or []):
            tid = a.get("trade_id")
            if tid is not None:
                out[tid] = out.get(tid, 0) + int(a.get("qty", 0))
        for a in (p.sells_json or []):
            tid = a.get("trade_id")
            if tid is not None:
                out[tid] = out.get(tid, 0) + int(a.get("qty", 0))
    return out


def _merge_allocations(
    existing: list[dict[str, Any]],
    additions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge additions into existing allocations, summing qty per trade_id.
    Preserves order: existing first, then any new trade_ids in addition order."""
    by_tid: dict[str, int] = {}
    order: list[str] = []
    for a in existing:
        tid = a["trade_id"]
        if tid not in by_tid:
            order.append(tid)
        by_tid[tid] = by_tid.get(tid, 0) + int(a["qty"])
    for a in additions:
        tid = a["trade_id"]
        if tid not in by_tid:
            order.append(tid)
        by_tid[tid] = by_tid.get(tid, 0) + int(a["qty"])
    return [{"trade_id": tid, "qty": by_tid[tid]} for tid in order]


async def get_task_filled_qty_map(
    session: AsyncSession,
    task_ids: list[str],
) -> dict[str, int]:
    """For each task_id, return the cumulative_qty of its latest push event.

    Tasks with no push events (e.g. PARSE_ERROR, SUBMIT_FAILED) are
    omitted from the returned map — callers should treat missing keys
    as "no filled qty available, ineligible for做T".
    """
    if not task_ids:
        return {}
    # Latest push per task via correlated subquery on received_at
    subq = (
        select(
            PushEventRow.task_id,
            func.max(PushEventRow.received_at).label("latest_ts"),
        )
        .where(PushEventRow.task_id.in_(task_ids))
        .group_by(PushEventRow.task_id)
        .subquery()
    )
    stmt = (
        select(PushEventRow)
        .join(
            subq,
            (PushEventRow.task_id == subq.c.task_id)
            & (PushEventRow.received_at == subq.c.latest_ts),
        )
    )
    result = await session.execute(stmt)
    out: dict[str, int] = {}
    for evt in result.scalars():
        if evt.cumulative_qty is not None and evt.cumulative_qty > 0:
            out[evt.task_id] = int(evt.cumulative_qty)
    return out


async def list_pairs(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    account_id: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> list[TPairRow]:
    """Return做T pairs, optionally filtered by ticker and/or account.

    Ordered by ``created_at ASC`` so the UI's T-1, T-2, ... numbering is
    stable across reloads. ``account_id=None`` returns all pairs (used by
    legacy / admin paths). UI callers should always pass the active
    broker's account_id to keep accounts isolated.

    ``offset`` / ``limit`` provide server-side pagination for the detail
    pane's pair list. Omit ``limit`` to return all rows (default, matches
    pre-pagination behavior so internal callers don't break).
    """
    stmt = select(TPairRow).order_by(TPairRow.created_at)
    if ticker is not None:
        stmt = stmt.where(TPairRow.ticker == ticker)
    if account_id is not None:
        stmt = stmt.where(TPairRow.account_id == account_id)
    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars())


async def count_pairs(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    account_id: str | None = None,
) -> int:
    """Total做T pair count matching the same filters as ``list_pairs``.
    Used by paginated /api/pairs to surface total/has_more to the UI."""
    stmt = select(func.count()).select_from(TPairRow)
    if ticker is not None:
        stmt = stmt.where(TPairRow.ticker == ticker)
    if account_id is not None:
        stmt = stmt.where(TPairRow.account_id == account_id)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def get_broker_executions_qty_map(
    session: AsyncSession,
    order_ids: list[str],
) -> dict[str, int]:
    """For each broker order_id, return its aggregated fill quantity from
    ``broker_executions``. Missing keys mean the order isn't in the synced
    table — ineligible for做T binding (treat as zero availability).

    This replaces ``get_task_filled_qty_map`` in the做T pair-binding path
    since pairs now reference broker order_ids instead of task ids.
    """
    if not order_ids:
        return {}
    stmt = select(BrokerExecutionRow.order_id, BrokerExecutionRow.qty).where(
        BrokerExecutionRow.order_id.in_(order_ids)
    )
    result = await session.execute(stmt)
    return {row.order_id: int(row.qty) for row in result.all() if row.qty > 0}


async def get_pair(session: AsyncSession, pair_id: int) -> TPairRow | None:
    return await session.get(TPairRow, pair_id)


async def delete_pair(session: AsyncSession, pair_id: int) -> bool:
    """Remove a pair. Also clears the pair's entries from each referenced
    trade's ``broker_executions.t_pair_tags``. Returns True if existed."""
    pair = await session.get(TPairRow, pair_id)
    if pair is None:
        return False
    # Strip [pair_id, *] from referenced fills BEFORE deleting the pair
    # so a follow-up "pending做T" SQL sees the freed qty immediately.
    await _sync_pair_tags(
        session,
        pair_id=pair_id,
        old_buys=list(pair.buys_json or []),
        old_sells=list(pair.sells_json or []),
        new_buys=[],
        new_sells=[],
    )
    await session.delete(pair)
    await session.commit()
    return True


async def delete_pairs_for_ticker(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str,
) -> int:
    """Bulk-delete every做T pair for ``(account_id, ticker)``. Each
    pair's tag cleanup runs against ``broker_executions.t_pair_tags``
    so the做T chip column flips empty atomically. Single commit at the
    end — cheaper than ``delete_pair`` in a loop.

    Returns the number of pairs removed.
    """
    stmt = select(TPairRow).where(
        TPairRow.account_id == account_id,
        TPairRow.ticker == ticker,
    )
    pairs = list((await session.execute(stmt)).scalars().all())
    for p in pairs:
        await _sync_pair_tags(
            session,
            pair_id=p.id,
            old_buys=list(p.buys_json or []),
            old_sells=list(p.sells_json or []),
            new_buys=[],
            new_sells=[],
        )
        await session.delete(p)
    if pairs:
        await session.commit()
    return len(pairs)


def _price_map(rows: list[BrokerExecutionRow]) -> dict[str, float]:
    """``order_id → price`` lookup used by profit computation."""
    return {r.order_id: float(r.price) for r in rows}


def _compute_pair_profit(
    buys: list[dict[str, Any]],
    sells: list[dict[str, Any]],
    price_by_trade_id: dict[str, float],
) -> float:
    """Realized profit on the matched portion of a pair.

    matched_qty = min(sum_buy_qty, sum_sell_qty)
    profit      = matched_qty × (avg_sell_price − avg_buy_price)

    Mirrors ``pairMath.ts::pairProfit`` so the stored value matches the
    frontend's expectations exactly. Returns 0 for one-sided pairs.
    """
    buy_qty_total = sum(int(b.get("qty", 0)) for b in buys)
    sell_qty_total = sum(int(s.get("qty", 0)) for s in sells)
    if buy_qty_total <= 0 or sell_qty_total <= 0:
        return 0.0
    buy_cost = sum(
        int(b.get("qty", 0)) * price_by_trade_id.get(str(b.get("trade_id", "")), 0.0)
        for b in buys
    )
    sell_rev = sum(
        int(s.get("qty", 0)) * price_by_trade_id.get(str(s.get("trade_id", "")), 0.0)
        for s in sells
    )
    avg_buy = buy_cost / buy_qty_total
    avg_sell = sell_rev / sell_qty_total
    return float(min(buy_qty_total, sell_qty_total) * (avg_sell - avg_buy))


async def _sync_pair_tags(
    session: AsyncSession,
    *,
    pair_id: int,
    old_buys: list[dict[str, Any]],
    old_sells: list[dict[str, Any]],
    new_buys: list[dict[str, Any]],
    new_sells: list[dict[str, Any]],
) -> None:
    """Reconcile ``broker_executions.t_pair_tags`` for the trades
    referenced by this pair, before/after a CRUD operation.

    Algorithm per affected trade_id:
      1. Strip any existing ``[pair_id, *]`` entry from the trade's tags.
      2. If the new allocation under this pair > 0, append ``[pair_id, qty]``.

    Affected set = ids in ``old_*`` ∪ ids in ``new_*`` — covers create
    (old empty), extend (overlap), and delete (new empty).
    """
    new_qty_by_trade: dict[str, int] = {}
    for entry in (new_buys or []) + (new_sells or []):
        tid = entry.get("trade_id")
        if tid is None:
            continue
        new_qty_by_trade[str(tid)] = new_qty_by_trade.get(str(tid), 0) + int(
            entry.get("qty", 0)
        )

    affected: set[str] = set(new_qty_by_trade.keys())
    for entry in (old_buys or []) + (old_sells or []):
        tid = entry.get("trade_id")
        if tid is not None:
            affected.add(str(tid))
    if not affected:
        return

    for tid in affected:
        trade_row = await session.get(BrokerExecutionRow, tid)
        if trade_row is None:
            # Trade not (yet) in broker_executions table — skip silently.
            # This shouldn't happen in practice since create_pair derives
            # buy/sell ids from ``get_broker_executions_qty_map``.
            continue
        tags = [
            list(t) for t in (trade_row.t_pair_tags or [])
            if not (isinstance(t, (list, tuple)) and len(t) >= 1 and int(t[0]) == pair_id)
        ]
        new_qty = new_qty_by_trade.get(tid, 0)
        if new_qty > 0:
            tags.append([pair_id, new_qty])
        trade_row.t_pair_tags = tags


async def _fetch_prices(
    session: AsyncSession, trade_ids: list[str]
) -> dict[str, float]:
    """Bulk ``order_id → price`` fetch for profit computation."""
    if not trade_ids:
        return {}
    stmt = select(BrokerExecutionRow.order_id, BrokerExecutionRow.price).where(
        BrokerExecutionRow.order_id.in_(trade_ids)
    )
    return {
        row.order_id: float(row.price)
        for row in (await session.execute(stmt)).all()
    }


async def create_pair(
    session: AsyncSession,
    *,
    ticker: str,
    symbol: str | None,
    buy_trade_ids: list[str],
    sell_trade_ids: list[str],
    trade_qty: dict[str, int],
    account_id: str,
) -> TPairRow | None:
    """Allocate a new pair using FIFO + min(BUY_avail, SELL_avail).

    ``trade_qty`` maps each candidate trade_id (broker order_id) to its
    aggregated qty. Existing pair allocations are loaded automatically to
    compute remaining availability. The pair's INTEGER id is assigned by
    SQLite (autoincrement); the caller doesn't supply it.

    On success:
      - ``profit`` is computed and stored.
      - Each referenced broker_executions row has its ``t_pair_tags``
        updated to include ``[new_pair_id, alloc_qty]``.

    Returns ``None`` if no allocation was possible.
    """
    existing_pairs = await list_pairs(session, ticker=ticker, account_id=account_id)
    allocated = aggregate_allocated(existing_pairs)
    buy_avail = sum(
        max(0, trade_qty.get(tid, 0) - allocated.get(tid, 0)) for tid in buy_trade_ids
    )
    sell_avail = sum(
        max(0, trade_qty.get(tid, 0) - allocated.get(tid, 0)) for tid in sell_trade_ids
    )
    matched = min(buy_avail, sell_avail)

    if matched > 0:
        buys = allocate_fifo(buy_trade_ids, trade_qty, allocated, matched)
        sells = allocate_fifo(sell_trade_ids, trade_qty, allocated, matched)
    elif buy_avail > 0:
        buys = allocate_fifo(buy_trade_ids, trade_qty, allocated, buy_avail)
        sells = []
    elif sell_avail > 0:
        buys = []
        sells = allocate_fifo(sell_trade_ids, trade_qty, allocated, sell_avail)
    else:
        return None

    prices = await _fetch_prices(
        session, [str(a["trade_id"]) for a in buys + sells]
    )
    profit = _compute_pair_profit(buys, sells, prices)

    now = datetime.now(UTC)
    row = TPairRow(
        account_id=account_id,
        ticker=ticker,
        symbol=symbol,
        buys_json=buys,
        sells_json=sells,
        profit=profit,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    # Flush so the autoincrement id is assigned BEFORE we propagate it
    # into broker_executions.t_pair_tags.
    await session.flush()

    await _sync_pair_tags(
        session,
        pair_id=row.id,
        old_buys=[],
        old_sells=[],
        new_buys=buys,
        new_sells=sells,
    )
    await session.commit()
    return row


async def extend_pair(
    session: AsyncSession,
    *,
    pair_id: int,
    buy_trade_ids: list[str],
    sell_trade_ids: list[str],
    trade_qty: dict[str, int],
    account_id: str | None = None,
) -> TPairRow | None:
    """Add more trades to an existing pair, balancing against current state.

    Allocation algorithm:
      1. Compute the pair's existing BUY/SELL totals.
      2. Compute new-side available qty (selection minus other-pair allocations).
      3. Target balanced total = min(existing_buy + new_buy_avail,
         existing_sell + new_sell_avail) — fill the smaller gap first.
      4. If both sides need 0 more (already balanced and selection was
         one-sided), fall through to a "raw extend" mode that adds the
         supplied side as available qty — this creates a pair-level
         mismatch which is intentional (UI labels it "部分做T").

    On success: ``profit`` is recomputed and stored, and
    ``broker_executions.t_pair_tags`` is resynced for every trade now
    referenced by this pair (additions append, existing entries' qty
    grow).

    Returns the updated pair, or ``None`` if the pair does not exist.
    """
    pair = await session.get(TPairRow, pair_id)
    if pair is None:
        return None

    ticker = pair.ticker
    # Scope to the pair's own account so cross-account allocations don't
    # interfere with availability calculations.
    scope_account = account_id if account_id is not None else pair.account_id
    all_pairs = await list_pairs(session, ticker=ticker, account_id=scope_account)
    # The pair we're extending should NOT count its own allocations as
    # "already used" against the trades being added — they may overlap
    # with trades already in this pair (the merge step folds them).
    other_pairs = [p for p in all_pairs if p.id != pair_id]
    other_alloc = aggregate_allocated(other_pairs)

    existing_buy = sum(int(a["qty"]) for a in (pair.buys_json or []))
    existing_sell = sum(int(a["qty"]) for a in (pair.sells_json or []))

    new_buy_avail = sum(
        max(0, trade_qty.get(tid, 0) - other_alloc.get(tid, 0)) for tid in buy_trade_ids
    )
    new_sell_avail = sum(
        max(0, trade_qty.get(tid, 0) - other_alloc.get(tid, 0)) for tid in sell_trade_ids
    )

    desired = min(existing_buy + new_buy_avail, existing_sell + new_sell_avail)
    need_buy = max(0, desired - existing_buy)
    need_sell = max(0, desired - existing_sell)

    new_buys = allocate_fifo(buy_trade_ids, trade_qty, other_alloc, need_buy)
    new_sells = allocate_fifo(sell_trade_ids, trade_qty, other_alloc, need_sell)

    # Fallback: one-sided extension that doesn't fill any gap → preserve
    # user intent by adding the supplied side's full availability.
    if not new_buys and not new_sells:
        if new_buy_avail > 0:
            new_buys = allocate_fifo(buy_trade_ids, trade_qty, other_alloc, new_buy_avail)
        if new_sell_avail > 0:
            new_sells = allocate_fifo(sell_trade_ids, trade_qty, other_alloc, new_sell_avail)

    if not new_buys and not new_sells:
        return pair  # nothing to add; leave pair unchanged

    old_buys = list(pair.buys_json or [])
    old_sells = list(pair.sells_json or [])
    merged_buys = _merge_allocations(old_buys, new_buys)
    merged_sells = _merge_allocations(old_sells, new_sells)

    prices = await _fetch_prices(
        session, [str(a["trade_id"]) for a in merged_buys + merged_sells]
    )
    pair.buys_json = merged_buys
    pair.sells_json = merged_sells
    pair.profit = _compute_pair_profit(merged_buys, merged_sells, prices)
    pair.updated_at = datetime.now(UTC)

    await _sync_pair_tags(
        session,
        pair_id=pair_id,
        old_buys=old_buys,
        old_sells=old_sells,
        new_buys=merged_buys,
        new_sells=merged_sells,
    )
    await session.commit()
    return pair


# ---------------------------------------------------------------------------
# broker_executions  — broker-synced fill mirror, account-scoped
# ---------------------------------------------------------------------------


async def upsert_broker_executions(
    session: AsyncSession,
    *,
    account_id: str,
    rows: list[dict[str, Any]],
) -> int:
    """Aggregate broker fills by ``order_id`` and upsert one row per
    order. Returns the number of orders persisted.

    ``rows`` are per-fill dicts as emitted by
    ``broker.history_executions`` (qty/price for each partial fill).
    Aggregation:
      - qty = sum of fill quantities
      - price = quantity-weighted average price
      - ts = latest fill's timestamp
      - symbol / ticker / side: taken from the first fill (constant
        within an order)

    Also attempts a best-effort link to ``tasks.task_id`` by matching on
    ``order_id`` — when a task in this account previously submitted this
    order, the row records that linkage. Manual fills (no originating
    task) get ``task_id = NULL``.
    """
    if not rows:
        return 0

    by_order: dict[str, dict[str, Any]] = {}
    for r in rows:
        oid = str(r.get("order_id") or "")
        if not oid:
            continue
        raw_ts = r.get("ts")
        if isinstance(raw_ts, datetime) and raw_ts.tzinfo is not None:
            raw_ts = raw_ts.astimezone(UTC).replace(tzinfo=None)
        qty_part = int(r.get("qty", 0) or 0)
        price_part = float(r.get("price", 0) or 0)
        agg = by_order.get(oid)
        if agg is None:
            by_order[oid] = {
                "order_id": oid,
                "account_id": account_id,
                "task_id": None,
                "symbol": str(r.get("symbol", "")),
                "ticker": str(r.get("ticker", "")),
                "side": str(r.get("side", "")),
                "qty": qty_part,
                "_weighted": qty_part * price_part,
                "ts": raw_ts,
            }
        else:
            agg["qty"] += qty_part
            agg["_weighted"] += qty_part * price_part
            # Keep the latest fill ts as the order's ts.
            if raw_ts is not None and (agg["ts"] is None or raw_ts > agg["ts"]):
                agg["ts"] = raw_ts

    if not by_order:
        return 0

    # Link to originating signal-station tasks where order_id matches.
    order_ids = list(by_order.keys())
    task_rows = await session.execute(
        select(TaskRow.id, TaskRow.order_id).where(TaskRow.order_id.in_(order_ids))
    )
    task_id_by_order = {r.order_id: r.id for r in task_rows.all()}

    payloads: list[dict[str, Any]] = []
    for oid, agg in by_order.items():
        total_qty = agg["qty"]
        avg_price = (agg["_weighted"] / total_qty) if total_qty > 0 else 0.0
        payloads.append({
            "order_id": oid,
            "account_id": agg["account_id"],
            "task_id": task_id_by_order.get(oid),
            "symbol": agg["symbol"],
            "ticker": agg["ticker"],
            "side": agg["side"],
            "qty": total_qty,
            "price": avg_price,
            "ts": agg["ts"],
        })

    stmt = sqlite_insert(BrokerExecutionRow).values(payloads)
    stmt = stmt.on_conflict_do_update(
        index_elements=["order_id"],
        set_={
            "account_id": stmt.excluded.account_id,
            "task_id": stmt.excluded.task_id,
            "symbol": stmt.excluded.symbol,
            "ticker": stmt.excluded.ticker,
            "side": stmt.excluded.side,
            "qty": stmt.excluded.qty,
            "price": stmt.excluded.price,
            "ts": stmt.excluded.ts,
            "synced_at": func.current_timestamp(),
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(payloads)


async def delete_broker_executions_for_ticker(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str,
) -> int:
    """Wipe ``broker_executions`` rows scoped to ``(account_id, ticker)``
    AND reset ``positions.history_synced`` back to False so the next
    detail-pane open re-triggers the full chunked backfill from scratch.
    Also sets ``restore_pair_tags = True`` so the full backfill replays
    ``t_pairs`` into ``broker_executions.t_pair_tags`` when it finishes.

    Returns the number of execution rows removed. ``t_pairs`` rows are
    not deleted — only the denormalized tags on executions are lost.
    """
    del_stmt = (
        BrokerExecutionRow.__table__.delete()
        .where(BrokerExecutionRow.account_id == account_id)
        .where(BrokerExecutionRow.ticker == ticker)
    )
    result = await session.execute(del_stmt)
    deleted = int(result.rowcount or 0)

    flag_stmt = (
        PositionRow.__table__.update()
        .where(PositionRow.account_id == account_id)
        .where(PositionRow.ticker == ticker)
        .values(history_synced=False, restore_pair_tags=True)
    )
    await session.execute(flag_stmt)
    await session.commit()
    return deleted


async def list_broker_executions(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str | None = None,
    since: datetime | None = None,
    offset: int = 0,
    limit: int = 500,
) -> list[BrokerExecutionRow]:
    """List fills for an account, optionally filtered by ticker and a
    lower-bound timestamp. Returned newest-first.

    ``offset`` enables server-side pagination for the detail pane's trade
    list. The frontend appends successive pages into a single ticker-scoped
    store so trades selected on prior pages remain available for cross-page
    做T binding without re-fetching them.
    """
    stmt = (
        select(BrokerExecutionRow)
        .where(BrokerExecutionRow.account_id == account_id)
        .order_by(BrokerExecutionRow.ts.desc())
        .offset(offset)
        .limit(limit)
    )
    if ticker is not None:
        stmt = stmt.where(BrokerExecutionRow.ticker == ticker)
    if since is not None:
        stmt = stmt.where(BrokerExecutionRow.ts >= since)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_broker_executions(
    session: AsyncSession,
    *,
    account_id: str,
    ticker: str | None = None,
    since: datetime | None = None,
) -> int:
    """Total fill count matching the same filters as
    ``list_broker_executions``. Used by paginated /api/broker/executions
    to surface total/has_more to the UI without re-fetching."""
    stmt = (
        select(func.count())
        .select_from(BrokerExecutionRow)
        .where(BrokerExecutionRow.account_id == account_id)
    )
    if ticker is not None:
        stmt = stmt.where(BrokerExecutionRow.ticker == ticker)
    if since is not None:
        stmt = stmt.where(BrokerExecutionRow.ts >= since)
    result = await session.execute(stmt)
    return int(result.scalar_one())


# ---------------------------------------------------------------------------
# TaskQueryRepo — injection seam for the trader's lot lookup.
# ---------------------------------------------------------------------------


class TaskQueryRepo(Protocol):
    """Read-only task lookups for components outside the storage layer.

    Decoupled from AsyncSession so the trader (which doesn't own a session)
    can depend on this interface and tests can substitute a fake.
    """

    async def find_recent_task_by_ref(
        self,
        *,
        ticker: str,
        side: InstructionType,
        price: float,
        before: datetime,
        window_hours: int = 24 * 7,
    ) -> int | None: ...


class SqlTaskQueryRepo:
    """Production implementation: opens a session from the factory per call."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def find_recent_task_by_ref(
        self,
        *,
        ticker: str,
        side: InstructionType,
        price: float,
        before: datetime,
        window_hours: int = 24 * 7,
    ) -> int | None:
        async with self._factory() as session:
            return await find_recent_task_by_ref(
                session,
                ticker=ticker,
                side=side,
                price=price,
                before=before,
                window_hours=window_hours,
            )


# ---------------------------------------------------------------------------
# chat_messages
# ---------------------------------------------------------------------------


async def upsert_chat_message(session: AsyncSession, row: ChatMessageRow) -> None:
    """Insert a chat message; ignore duplicates by ``id`` (idempotent on replay)."""
    stmt = sqlite_insert(ChatMessageRow).values(
        id=row.id,
        page_id=row.page_id,
        author=row.author,
        content=row.content,
        raw_content=row.raw_content,
        posted_at=row.posted_at,
        received_at=row.received_at,
        url=row.url,
        quoted_message_id=row.quoted_message_id,
        quoted_author=row.quoted_author,
        quoted_content=row.quoted_content,
        quoted_posted_at=row.quoted_posted_at,
        image_filename=row.image_filename,
    ).on_conflict_do_nothing(index_elements=["id"])
    await session.execute(stmt)


async def list_chat_messages(
    session: AsyncSession,
    page_id: str,
    week_start: datetime,
    week_end: datetime,
    senders: list[str] | None,
) -> list[ChatMessageRow]:
    """Return chat messages for *page_id* in ``[week_start, week_end)``,
    ordered by ``posted_at`` ASC.

    ``senders=None`` and ``senders=[]`` both mean "no filter".
    """
    stmt = (
        select(ChatMessageRow)
        .where(ChatMessageRow.page_id == page_id)
        .where(ChatMessageRow.posted_at >= week_start)
        .where(ChatMessageRow.posted_at < week_end)
        .order_by(ChatMessageRow.posted_at.asc())
    )
    if senders:
        stmt = stmt.where(ChatMessageRow.author.in_(senders))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_chat_authors(
    session: AsyncSession,
    page_id: str,
    week_start: datetime,
    week_end: datetime,
) -> list[tuple[str, int]]:
    """Return ``(author, count)`` pairs for chat messages in the week window,
    sorted by count DESC."""
    stmt = (
        select(ChatMessageRow.author, func.count(ChatMessageRow.id))
        .where(ChatMessageRow.page_id == page_id)
        .where(ChatMessageRow.posted_at >= week_start)
        .where(ChatMessageRow.posted_at < week_end)
        .group_by(ChatMessageRow.author)
        .order_by(func.count(ChatMessageRow.id).desc())
    )
    result = await session.execute(stmt)
    return [(author, count) for author, count in result.all()]


async def count_chat_messages_per_day(
    session: AsyncSession,
    page_id: str,
    range_start_utc: datetime,
    range_end_utc: datetime,
) -> list[tuple[str, int]]:
    """按北京日历日 (YYYY-MM-DD) 聚合返回 ``(day, count)``，仅 ``count > 0``，
    按 day 升序。

    SQLite 用 ``strftime("%Y-%m-%d", datetime(posted_at, "+8 hours"))`` 把
    UTC 时间投影到 Asia/Shanghai 日历日。若未来换 Postgres，需要把这段
    SQL 改成 ``to_char(posted_at AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD')``。

    ``range_start_utc`` / ``range_end_utc`` 是半开 UTC 区间，调用方应传入
    与 ``[北京月初 00:00, 次月初 00:00)`` 等价的 UTC 边界。
    """
    day_expr = func.strftime(
        "%Y-%m-%d", func.datetime(ChatMessageRow.posted_at, "+8 hours")
    )
    stmt = (
        select(day_expr.label("day"), func.count(ChatMessageRow.id))
        .where(ChatMessageRow.page_id == page_id)
        .where(ChatMessageRow.posted_at >= range_start_utc)
        .where(ChatMessageRow.posted_at < range_end_utc)
        .group_by(day_expr)
        .order_by(day_expr.asc())
    )
    result = await session.execute(stmt)
    return [(day, count) for day, count in result.all()]


async def delete_chat_messages_by_page(session: AsyncSession, page_id: str) -> int:
    """Delete all chat messages for *page_id*; returns the count removed.

    Called by the page-delete API route after removing the page from the
    whop registry (which lives in ``data/whop_pages.json``, not the DB — so
    no FK cascade is possible).
    """
    stmt = sa_delete(ChatMessageRow).where(ChatMessageRow.page_id == page_id)
    result = await session.execute(stmt)
    return result.rowcount or 0
