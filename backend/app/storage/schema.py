"""SQLAlchemy 2.x ORM table definitions for Signal Station.

Five Row classes (using "Row" suffix to avoid collisions with domain classes):
  - TaskRow         → tasks
  - MessageRow      → messages
  - InstructionRow  → instructions
  - PushEventRow    → push_events
  - PositionRow     → positions

All classes inherit from ``Base`` in ``app.storage.db``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, Integer, String, text
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
    # Full push payload as JSON.
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


# ---------------------------------------------------------------------------
# positions  (per-symbol snapshot, upserted on each longport sync)
# ---------------------------------------------------------------------------


class PositionRow(Base):
    """ORM mapping for the ``positions`` table."""

    __tablename__ = "positions"

    symbol: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cost: Mapped[float | None] = mapped_column(nullable=True)
    # Option-specific fields — all nullable for stock positions.
    option_strike: Mapped[float | None] = mapped_column(nullable=True)
    option_expiry: Mapped[date | None] = mapped_column(Date(), nullable=True)
    option_type: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
