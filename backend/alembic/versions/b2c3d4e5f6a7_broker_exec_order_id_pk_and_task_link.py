"""broker_executions: PK = order_id, add task_id link

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-16

Architectural shift:
- One broker_executions row per order_id (was: per trade_id, multi-fill).
  Partial fills are aggregated at upsert time: qty = sum, price = weighted
  avg, ts = latest fill timestamp.
- New nullable ``task_id`` column links back to the signal-station ``tasks``
  row that originated the order (when one exists). Set at sync time by
  joining on ``tasks.order_id``.
- ``tasks.order_id`` continues to point to the broker order_id when the
  trader pipeline submitted it (nullable for tasks that never reached
  the broker — parse error, manual skip, etc.).

Two reciprocal nullable references, no FK enforcement (manual fills
have no task; aborted tasks have no order). Resilient and simple.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Detect which schema variant exists. If ``task_id`` is already
    # present (case: dev env where Base.metadata.create_all ran with the
    # current ORM definition before alembic caught up), the table is
    # already in its target shape — just ensure the task_id index is
    # there and advance the stamp without any data-destructive drop.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("broker_executions")}

    if "task_id" in cols:
        existing_indexes = {
            idx["name"] for idx in inspector.get_indexes("broker_executions")
        }
        if "idx_broker_exec_task_id" not in existing_indexes:
            op.create_index(
                "idx_broker_exec_task_id",
                "broker_executions",
                ["task_id"],
            )
        return

    # Otherwise the table is the post-a1b2c3d4e5f6 trade_id-PK shape; no
    # production data yet (the prior migration introduced it), so a drop
    # + recreate is safe and cheaper than per-row schema munging. SQLite
    # doesn't support ALTER COLUMN / DROP CONSTRAINT cleanly anyway.
    op.drop_index("idx_broker_exec_account_ticker", table_name="broker_executions")
    op.drop_index("idx_broker_exec_account_ts", table_name="broker_executions")
    op.drop_table("broker_executions")

    op.create_table(
        "broker_executions",
        sa.Column("order_id", sa.String(), primary_key=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "idx_broker_exec_account_ts",
        "broker_executions",
        ["account_id", "ts"],
    )
    op.create_index(
        "idx_broker_exec_account_ticker",
        "broker_executions",
        ["account_id", "ticker"],
    )
    op.create_index(
        "idx_broker_exec_task_id",
        "broker_executions",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_broker_exec_task_id", table_name="broker_executions")
    op.drop_index("idx_broker_exec_account_ticker", table_name="broker_executions")
    op.drop_index("idx_broker_exec_account_ts", table_name="broker_executions")
    op.drop_table("broker_executions")

    op.create_table(
        "broker_executions",
        sa.Column("trade_id", sa.String(), primary_key=True),
        sa.Column("account_id", sa.String(), nullable=False),
        sa.Column("order_id", sa.String(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "idx_broker_exec_account_ts",
        "broker_executions",
        ["account_id", "ts"],
    )
    op.create_index(
        "idx_broker_exec_account_ticker",
        "broker_executions",
        ["account_id", "ticker"],
    )
