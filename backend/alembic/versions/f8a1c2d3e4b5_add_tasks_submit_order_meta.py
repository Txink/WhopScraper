"""add tasks submit_order_type + submit_order_context

Revision ID: f8a1c2d3e4b5
Revises: ceb9c732a26c
Create Date: 2026-04-28

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f8a1c2d3e4b5"
down_revision = "ceb9c732a26c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("submit_order_type", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("submit_order_context", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "submit_order_context")
    op.drop_column("tasks", "submit_order_type")
