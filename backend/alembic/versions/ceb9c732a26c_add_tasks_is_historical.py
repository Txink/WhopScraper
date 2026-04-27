"""add tasks.is_historical

Revision ID: ceb9c732a26c
Revises: 947fff1b2fcd
Create Date: 2026-04-28 02:06:32.219042

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ceb9c732a26c"
down_revision: str | Sequence[str] | None = "947fff1b2fcd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.add_column(
            sa.Column(
                "is_historical",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.drop_column("is_historical")
