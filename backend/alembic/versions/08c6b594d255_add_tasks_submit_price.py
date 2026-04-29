"""add tasks.submit_price

The actual broker LIMIT price (post quote-vs-signal decision in trader).
Distinct from ``submit_quote_last_done`` which records the raw quote that
fed the decision. Frontend uses ``submit_price`` for PRICE/TOTAL display
so the UI matches what was actually sent to the broker — not the parsed
signal price.

Revision ID: 08c6b594d255
Revises: 2c15fa4a14ca
Create Date: 2026-04-29 22:13:15.640970
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '08c6b594d255'
down_revision: Union[str, Sequence[str], None] = '2c15fa4a14ca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("submit_price", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "submit_price")
