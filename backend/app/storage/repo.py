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
        url=row.url,
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
