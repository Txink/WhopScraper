"""shift messages.posted_at to real UTC

Until this migration, posted_at was stored as the Whop wall-clock
(Beijing) tagged with UTC tzinfo — i.e. every value was 8 hours ahead
of the true moment. The parser now returns real UTC, so existing rows
must be shifted back by 8 hours to preserve the correct instant.

Rows where ``posted_at == received_at`` are preserved as-is. Those represent
the parse-failure fallback path (``app/whop/extractor.py:_parse_timestamp``)
where the parser couldn't decode Whop's timestamp string and the listener
filled in ``posted_at`` with ``datetime.now(UTC)`` — i.e. real UTC, never
the Beijing-as-UTC convention. Shifting those would make them wrong.

Reversible: downgrade adds 8 hours back (with the same WHERE filter).

Revision ID: 2c15fa4a14ca
Revises: ceb9c732a26c
Create Date: 2026-04-28 22:03:06.290822

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2c15fa4a14ca'
down_revision: str | Sequence[str] | None = 'ceb9c732a26c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Shift posted_at: stored_value -= 8h to convert Beijing wall-clock to real UTC."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(
            "UPDATE messages SET posted_at = datetime(posted_at, '-8 hours') "
            "WHERE posted_at != received_at"
        )
    elif dialect == "postgresql":
        op.execute(
            "UPDATE messages SET posted_at = posted_at - INTERVAL '8 hours' "
            "WHERE posted_at != received_at"
        )
    else:
        raise NotImplementedError(
            f"shift migration not implemented for dialect {dialect!r}; "
            "add a branch above before running."
        )


def downgrade() -> None:
    """Reverse: stored_value += 8h (skipping fallback rows where posted_at == received_at)."""
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(
            "UPDATE messages SET posted_at = datetime(posted_at, '+8 hours') "
            "WHERE posted_at != received_at"
        )
    elif dialect == "postgresql":
        op.execute(
            "UPDATE messages SET posted_at = posted_at + INTERVAL '8 hours' "
            "WHERE posted_at != received_at"
        )
    else:
        raise NotImplementedError(
            f"shift migration not implemented for dialect {dialect!r}; "
            "add a branch above before running."
        )
