"""positions: restore_pair_tags flag for t_pair_tags rebuild after wipe

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-05-19

When broker_executions rows for a ticker are deleted, denormalised
``t_pair_tags`` are lost while ``t_pairs`` allocations remain. This flag
requests a one-shot rebuild from ``t_pairs`` after the next full
chunked backfill completes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "positions" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("positions")}
    if "restore_pair_tags" in cols:
        return
    with op.batch_alter_table("positions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "restore_pair_tags",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "positions" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("positions")}
    if "restore_pair_tags" not in cols:
        return
    with op.batch_alter_table("positions") as batch_op:
        batch_op.drop_column("restore_pair_tags")
