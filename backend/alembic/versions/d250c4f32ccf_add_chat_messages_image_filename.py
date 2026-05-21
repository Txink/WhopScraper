"""add_chat_messages_image_filename

Revision ID: d250c4f32ccf
Revises: d170f76b4e44
Create Date: 2026-05-21 08:34:27.998343

Adds the ``image_filename`` column to ``chat_messages``.  Stores only the
basename (e.g. ``post_1CbE4.avif``) so the data directory remains portable;
the API composes the full URL at response time.  Nullable with no default —
rows without an image carry NULL.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd250c4f32ccf'
down_revision: str | Sequence[str] | None = 'd170f76b4e44'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "chat_messages",
        sa.Column("image_filename", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chat_messages", "image_filename")
