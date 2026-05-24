"""SQLAlchemy 2.x ORM table definitions for Signal Station.

Six Row classes (using "Row" suffix to avoid collisions with domain classes):
  - TaskRow         → tasks
  - MessageRow      → messages
  - InstructionRow  → instructions
  - PushEventRow    → push_events
  - PositionRow     → positions
  - TPairRow        → t_pairs (做T 配对)

All classes inherit from ``Base`` in ``app.storage.db``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.storage.db import Base

# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
# Note on idx_tasks_created_at: SQLAlchemy's Index() supports descending
# columns via col.desc() when using the ORM column object.  SQLite honours
# DESC in index definitions since version 3.37.  If a plain ascending index is
# sufficient for your workload, remove the .desc() call.
# ---------------------------------------------------------------------------


class TaskRow(Base):
    """ORM mapping for the ``tasks`` table."""

    __tablename__ = "tasks"
    __table_args__ = (
        # DESC index on created_at — matches spec §6 idx_tasks_created_at.
        # SQLite ≥ 3.37 supports DESC indexes; for older SQLite builds this
        # degrades silently to an ascending index (still functional).
        Index("idx_tasks_created_at", "created_at", postgresql_using="btree"),
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_symbol", "symbol"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[str | None] = mapped_column(String, nullable=True)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    side: Mapped[str | None] = mapped_column(String, nullable=True)
    price: Mapped[float | None] = mapped_column(nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # JSON column: stores {"parse": 18, ...}; SQLAlchemy handles serialisation.
    stage_timings_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_historical: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    submit_order_type: Mapped[str | None] = mapped_column(String, nullable=True)
    submit_order_context: Mapped[str | None] = mapped_column(String, nullable=True)
    submit_quote_last_done: Mapped[float | None] = mapped_column(nullable=True)
    submit_price: Mapped[float | None] = mapped_column(nullable=True)
    # Active OAuth account at submission time. Nullable for backwards
    # compat — pre-multi-account tasks have NULL.
    account_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Origin of the order. "signal" = whop-driven via parser/trader pipeline;
    # "manual" = submitted by user via the trading panel (no Message /
    # Instruction rows). NULL for legacy rows (pre-migration); treated as
    # "signal" by code paths that branch on this.
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    # Most recent successful replace_order time. NULL until the order has
    # been modified at least once via PATCH /api/orders/{id}.
    last_replaced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# messages  (1:1 with tasks — shares PK, FK cascade on delete)
# ---------------------------------------------------------------------------


class MessageRow(Base):
    """ORM mapping for the ``messages`` table."""

    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_url", "url"),)

    # id is both PK and FK → tasks.id; ON DELETE CASCADE propagates task deletion.
    id: Mapped[str] = mapped_column(
        String,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    content: Mapped[str] = mapped_column(String, nullable=False)
    raw_content: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_message_id: Mapped[str | None] = mapped_column(String, nullable=True)


# ---------------------------------------------------------------------------
# chat_messages  (free-standing — no FK to tasks; page_id is a SOFT link
# because WhopPageEntry lives in data/whop_pages.json, not in DB)
# ---------------------------------------------------------------------------


class ChatMessageRow(Base):
    """ORM mapping for the ``chat_messages`` table.

    Rows are written directly by ``app.whop.chat_writer`` for pages whose
    ``WhopPageEntry.source == "chat"``; they never go through the task /
    instruction pipeline. The ``quoted_*`` columns are always denormalized
    so a row renders correctly even if the referenced message is missing
    (e.g., before scraping started, from a non-watched sender, or in a
    different week than the active view).
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("idx_chat_messages_page_posted", "page_id", "posted_at"),
        Index("idx_chat_messages_page_author_posted", "page_id", "author", "posted_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    page_id: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    raw_content: Mapped[str] = mapped_column(String, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_author: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_content: Mapped[str | None] = mapped_column(String, nullable=True)
    quoted_posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    image_filename: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


# ---------------------------------------------------------------------------
# instructions  (1:1 with tasks — task_id is PK + FK, no cascade per spec)
# ---------------------------------------------------------------------------


class InstructionRow(Base):
    """ORM mapping for the ``instructions`` table."""

    __tablename__ = "instructions"

    # task_id is PK (enforces 1:1) and FK to tasks.id.
    # Spec does not specify ON DELETE CASCADE for instructions.
    task_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("tasks.id"),
        primary_key=True,
    )
    instruction_type: Mapped[str] = mapped_column(String, nullable=False)
    context_source: Mapped[str | None] = mapped_column(String, nullable=True)
    # Full Instruction serialised as JSON.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# push_events  (many per task, append-only)
# ---------------------------------------------------------------------------


class PushEventRow(Base):
    """ORM mapping for the ``push_events`` table."""

    __tablename__ = "push_events"
    __table_args__ = (
        # Composite index on (task_id, received_at) — matches spec idx_push_task.
        Index("idx_push_task", "task_id", "received_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    # FK to tasks.id; spec does not request ON DELETE CASCADE for push_events.
    task_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("tasks.id"),
        nullable=False,
    )
    order_id: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delta_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delta_price: Mapped[float | None] = mapped_column(nullable=True)
    cumulative_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cumulative_avg_price: Mapped[float | None] = mapped_column(nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # Current limit price the order is sitting at on the broker side
    # (LongPort ``submitted_price``). Captured on every push so post-submit
    # limit modifications can be recovered from history without parsing
    # ``payload_json``.
    submitted_price: Mapped[float | None] = mapped_column(nullable=True)
    # Current ordered quantity (LongPort ``submitted_quantity``). Captured
    # so qty-only modifications can be detected against prior live events
    # without re-parsing payload_json.
    submitted_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Full push payload as JSON.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# positions  (per-symbol snapshot, upserted on each longport sync)
# ---------------------------------------------------------------------------


class PositionRow(Base):
    """ORM mapping for the ``positions`` table.

    Account-scoped: PK is ``(account_id, symbol)`` so multiple accounts can
    coexist in DB. ``history_synced`` is the per-ticker (per account)
    "we've fully backfilled broker_executions" anchor — set true after
    a full chunked backfill completes for the ticker; the detail-pane
    sync path uses it to decide between a full walk vs. a gap-only update.
    Surviving sells: rows with ``quantity = 0`` are kept so the
    ``history_synced`` flag persists across close/re-open cycles.
    """

    __tablename__ = "positions"

    account_id: Mapped[str] = mapped_column(String, primary_key=True)
    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost: Mapped[float | None] = mapped_column(nullable=True)
    # Option-specific fields — all nullable for stock positions.
    option_strike: Mapped[float | None] = mapped_column(nullable=True)
    option_expiry: Mapped[date | None] = mapped_column(Date(), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String, nullable=True)
    history_synced: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    # Set when broker_executions for this ticker are wiped but t_pairs
    # remain — the next full chunked backfill rebuilds t_pair_tags from pairs.
    restore_pair_tags: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# t_pairs (做T 配对) — explicit BUY/SELL allocations grouped into one trade
# round. Each allocation references a task.id and stores the qty consumed
# from that task. A single task may have allocations across multiple pairs
# (partial allocation); the sum of allocations across pairs must not exceed
# the task's filled qty. Enforced at the repo layer, not the DB.
# ---------------------------------------------------------------------------


class TPairRow(Base):
    """ORM mapping for the ``t_pairs`` table.

    ``buys_json`` / ``sells_json`` are JSON arrays of
    ``{"trade_id": str, "qty": int}``. We use JSON rather than a child
    allocations table to keep the schema light — pairs are a UI construct
    used for做T tracking, not a primary trading data source.

    ``id`` is a SQLite-native autoincrement integer (table-wide unique,
    never reused after delete). The UI labels each pair as "T-{id}". The
    pre-v2 schema used a UUID string id; the v2 migration assigns sequential
    integers in created_at order. See ``migrate_pairs_v2.py``.

    ``profit`` is computed at pair create / extend time from the matched
    qty × (avg_sell_price − avg_buy_price) and persisted so做T-summary
    queries can use simple SQL aggregates without joining trades.
    """

    __tablename__ = "t_pairs"
    __table_args__ = (
        # Compound index for the typical detail-pane filter
        # ``WHERE account_id=? AND ticker=?``.
        Index("idx_t_pairs_account_ticker", "account_id", "ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Account scope for multi-account isolation — required in v2 (pre-v2
    # legacy rows carrying NULL are dropped by the migration).
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    # Broker-canonical symbol (e.g. "TSLA.US"). Kept alongside ticker so we
    # can resolve back to a broker entity even when the ticker→symbol
    # mapping changes (rare, but happened with rebranded tickers).
    symbol: Mapped[str | None] = mapped_column(String, nullable=True)
    buys_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    sells_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # Realized做T profit for the matched portion. Snapshot taken at
    # create/extend; broker fills are immutable in practice so the value
    # doesn't drift.
    profit: Mapped[float] = mapped_column(nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# broker_executions  (canonical fill record, synced from broker.history_executions)
# ---------------------------------------------------------------------------


class BrokerExecutionRow(Base):
    """ORM mapping for the ``broker_executions`` table.

    One row per ``order_id`` — partial fills under the same order are
    aggregated at sync time (qty=sum, price=weighted-avg, ts=latest).
    Includes orders placed via the LongBridge app / web, not just those
    submitted by signal-station's trader pipeline.

    Cross-references:
      - ``account_id`` (= active OAuth client_id) scopes multi-account isolation.
      - ``task_id`` (nullable) links back to ``tasks`` when the order
        originated in signal-station's pipeline. Manual fills have NULL.

    The reciprocal ``tasks.order_id`` column is also nullable — tasks
    that never reached the broker (parse error, dry-run skip, etc.)
    have no order_id. Both references are convenience joins, NOT
    enforced foreign keys.
    """

    __tablename__ = "broker_executions"
    __table_args__ = (
        Index("idx_broker_exec_account_ts", "account_id", "ts"),
        Index("idx_broker_exec_account_ticker", "account_id", "ticker"),
        Index("idx_broker_exec_task_id", "task_id"),
    )

    order_id: Mapped[str] = mapped_column(String, primary_key=True)
    account_id: Mapped[str] = mapped_column(String, nullable=False)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    side: Mapped[str] = mapped_column(String, nullable=False)  # BUY | SELL
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    # Denormalized做T allocation list maintained by the pair CRUD layer.
    # Shape: ``[[pair_id, allocated_qty], ...]`` — each entry says how many
    # shares of this fill were allocated to the given pair. Lets SQL
    # cheaply identify "pending做T" trades:
    #   WHERE qty > COALESCE(
    #     (SELECT SUM(CAST(json_extract(t.value, '$[1]') AS INTEGER))
    #      FROM json_each(t_pair_tags) AS t),
    #     0)
    # The ``[]`` default keeps freshly-synced fills queryable before any
    # pair touches them.
    t_pair_tags: Mapped[list[list[Any]]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    )


# ---------------------------------------------------------------------------
# alerts — per-ticker user-defined price / pct_change / volume watchers
# evaluated by AlertEngine against LongPort quote pushes.
# ---------------------------------------------------------------------------


class AlertRow(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("idx_alerts_ticker_enabled", "ticker", "enabled"),
        Index("idx_alerts_symbol_enabled", "symbol", "enabled"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    condition_type: Mapped[str] = mapped_column(String, nullable=False)
    operator: Mapped[str] = mapped_column(String, nullable=False)
    threshold: Mapped[float] = mapped_column(nullable=False)
    pct_change_baseline: Mapped[str | None] = mapped_column(String, nullable=True)
    volume_window: Mapped[str | None] = mapped_column(String, nullable=True)
    repeat_mode: Mapped[str] = mapped_column(String, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("1")
    )
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AlertEventRow(Base):
    __tablename__ = "alert_events"
    __table_args__ = (
        Index("idx_alert_events_alert_ts", "alert_id", "triggered_at"),
        Index("idx_alert_events_ticker_ts", "ticker", "triggered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    symbol: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_price: Mapped[float] = mapped_column(nullable=False)
    snapshot_pct: Mapped[float | None] = mapped_column(nullable=True)
    snapshot_volume: Mapped[float | None] = mapped_column(nullable=True)
    message: Mapped[str] = mapped_column(String, nullable=False)
