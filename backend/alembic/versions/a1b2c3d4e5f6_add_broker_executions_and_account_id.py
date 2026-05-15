"""add broker_executions table + account_id columns on tasks / t_pairs

Revision ID: a1b2c3d4e5f6
Revises: c4d7f2e91a3b
Create Date: 2026-05-16

Adds:
- ``broker_executions`` table — canonical mirror of broker.history_executions
  with account_id scope; backs the detail-pane trade list.
- ``tasks.account_id`` (nullable) — active OAuth account at submission time.
- ``t_pairs.account_id`` (nullable) — pair scope for multi-account isolation.

Both new columns are nullable so legacy rows continue to load. New writes
populate them with the active broker's ``account_id``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "c4d7f2e91a3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All steps below are idempotent — they only execute if the target
    # object doesn't already exist. In a dev environment ``Base.metadata.
    # create_all()`` runs on app startup and creates ``broker_executions``
    # (and its indexes) ahead of alembic, so this migration's job is
    # really just to advance the version stamp while making sure the
    # schema state matches whether the create_all ran first or not.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "broker_executions" not in tables:
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

    existing_indexes = {
        idx["name"] for idx in inspector.get_indexes("broker_executions")
    } if "broker_executions" in inspector.get_table_names() else set()
    if "idx_broker_exec_account_ts" not in existing_indexes:
        op.create_index(
            "idx_broker_exec_account_ts",
            "broker_executions",
            ["account_id", "ts"],
        )
    if "idx_broker_exec_account_ticker" not in existing_indexes:
        op.create_index(
            "idx_broker_exec_account_ticker",
            "broker_executions",
            ["account_id", "ticker"],
        )

    tasks_cols = {c["name"] for c in inspector.get_columns("tasks")}
    if "account_id" not in tasks_cols:
        op.add_column("tasks", sa.Column("account_id", sa.String(), nullable=True))

    # t_pairs is created lazily via Base.metadata.create_all() (no
    # original migration created it), so on a fresh upgrade-from-empty
    # the table doesn't exist yet. Add the column only when the table
    # is actually present AND doesn't already have it.
    if "t_pairs" in tables:
        tpair_cols = {c["name"] for c in inspector.get_columns("t_pairs")}
        if "account_id" not in tpair_cols:
            op.add_column("t_pairs", sa.Column("account_id", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "t_pairs" in inspector.get_table_names():
        op.drop_column("t_pairs", "account_id")
    op.drop_column("tasks", "account_id")
    op.drop_index("idx_broker_exec_account_ticker", table_name="broker_executions")
    op.drop_index("idx_broker_exec_account_ts", table_name="broker_executions")
    op.drop_table("broker_executions")
