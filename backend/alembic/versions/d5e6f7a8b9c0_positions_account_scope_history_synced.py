"""positions table: account_id composite PK + history_synced flag

Revision ID: d5e6f7a8b9c0
Revises: b2c3d4e5f6a7
Create Date: 2026-05-17

Reshapes ``positions`` so it can actually be persisted across multiple
broker accounts, and so the detail-pane backfill path has a definitive
"have we synced this ticker's full history yet?" anchor.

Schema change:
- PK becomes composite ``(account_id, symbol)``.
- New column ``history_synced BOOL NOT NULL DEFAULT 0``: set true after
  ``broker_executions`` is fully chunked-backfilled for this account+ticker.

Since the legacy ``positions`` table is currently un-written (the
``/api/positions`` endpoint reads live from the broker without
persisting), we drop-and-recreate rather than ALTER. Zero data loss
because there's no data to lose. Idempotent: skips the drop+create if
the new shape is already in place (``Base.metadata.create_all()`` runs
at app start and produces the new shape directly on fresh DBs).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_account_id_column(inspector: sa.Inspector) -> bool:
    if "positions" not in inspector.get_table_names():
        return False
    cols = {c["name"] for c in inspector.get_columns("positions")}
    return "account_id" in cols and "history_synced" in cols


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_account_id_column(inspector):
        # create_all already produced the new shape (fresh DB path).
        return

    if "positions" in inspector.get_table_names():
        op.drop_table("positions")

    op.create_table(
        "positions",
        sa.Column("account_id", sa.String(), primary_key=True),
        sa.Column("symbol", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Float(), nullable=True),
        sa.Column("option_strike", sa.Float(), nullable=True),
        sa.Column("option_expiry", sa.Date(), nullable=True),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column(
            "history_synced",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "positions" not in inspector.get_table_names():
        return
    op.drop_table("positions")
    # Restore legacy single-PK shape so older code can still boot.
    op.create_table(
        "positions",
        sa.Column("symbol", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_cost", sa.Float(), nullable=True),
        sa.Column("option_strike", sa.Float(), nullable=True),
        sa.Column("option_expiry", sa.Date(), nullable=True),
        sa.Column("option_type", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
