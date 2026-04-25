"""add messages.url + index

Revision ID: 947fff1b2fcd
Revises: 4d8877dc7b4f
Create Date: 2026-04-25 16:19:40.427521

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "947fff1b2fcd"
down_revision: str | Sequence[str] | None = "4d8877dc7b4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("url", sa.String(), nullable=True))
    op.create_index("idx_messages_url", "messages", ["url"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_messages_url", table_name="messages")
    op.drop_column("messages", "url")
