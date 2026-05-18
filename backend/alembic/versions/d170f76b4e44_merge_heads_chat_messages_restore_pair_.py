"""merge heads: chat_messages + restore_pair_tags

Revision ID: d170f76b4e44
Revises: e6f7a8b9c0d1, f0fb2079190e
Create Date: 2026-05-19 02:39:53.173009

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd170f76b4e44'
down_revision: Union[str, Sequence[str], None] = ('e6f7a8b9c0d1', 'f0fb2079190e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
