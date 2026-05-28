"""add_messages_image_filename

Revision ID: a7c1image01
Revises: 0746c8880387
Create Date: 2026-05-29 00:00:00.000000

Adds the ``image_filename`` column to ``messages`` (stock/option messages),
mirroring the chat_messages column. Stores only the basename; the API
composes the proxy URL at response time. Nullable, no default.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c1image01"
down_revision: str | Sequence[str] | None = "0746c8880387"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "messages",
        sa.Column("image_filename", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("messages", "image_filename")
