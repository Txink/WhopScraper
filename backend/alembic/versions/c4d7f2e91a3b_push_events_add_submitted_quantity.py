"""push_events: add submitted_quantity column

Captures LongPort ``submitted_quantity`` on every push so qty-only
modifications (user changing 1 → 2 shares from the broker app) can be
detected against the prior live event — same broker label (``New``) but
different ``submitted_quantity``. Without this column the relabel logic
in ``PushListener._build_push_event`` only sees price changes, so a pure
qty modify slips through as another ``New`` and the UI shows nothing
about it.

Revision ID: c4d7f2e91a3b
Revises: 9a5b2c3d8e7f
Create Date: 2026-04-30 19:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "c4d7f2e91a3b"
down_revision: Union[str, Sequence[str], None] = "9a5b2c3d8e7f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("push_events", sa.Column("submitted_quantity", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("push_events", "submitted_quantity")
