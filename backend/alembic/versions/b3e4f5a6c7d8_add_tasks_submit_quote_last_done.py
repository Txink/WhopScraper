"""add tasks.submit_quote_last_done

Revision ID: b3e4f5a6c7d8
Revises: f8a1c2d3e4b5
Create Date: 2026-04-28

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b3e4f5a6c7d8"
down_revision = "f8a1c2d3e4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("submit_quote_last_done", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "submit_quote_last_done")
