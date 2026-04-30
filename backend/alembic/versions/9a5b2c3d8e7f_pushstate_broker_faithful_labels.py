"""push_events: broker-faithful state labels + submitted_price column

Two coupled changes that ship together because the new state-relabel logic
in ``PushListener._build_push_event`` reads ``submitted_price`` from prior
events to detect post-submit limit modifications:

1.  Add ``push_events.submitted_price`` (Float, nullable) — captures the
    LongPort ``submitted_price`` on every push so a later ``New`` push with
    a different limit can be reclassified as ``Replaced``.

2.  Convert legacy coarse-grained state labels (``NEW``/``FILLED``/...) to
    broker-faithful labels (``New``/``Filled``/...). The legacy enum
    collapsed every pre-routing/live/replace state into ``NEW`` and every
    cancel into ``CANCELLED``; the new enum keeps each broker label
    distinct so the UI can show the actual transition chain (e.g.
    ``WaitToNew → New → Filled``).

The legacy buckets contain only ``NEW`` / ``FILLED`` rows in any DB that
predates this migration — earlier runs never recorded the other coarse
labels because broker-faithful pushes (``WaitToNew``, ``Replaced``, ...)
were normalised away. We map ``NEW``→``New`` and ``FILLED``→``Filled`` in
the data step; the other legacy values get the same coarse-to-canonical
mapping used by ``_LEGACY_LABEL_MAP`` for defensive coverage of any
hand-edited rows.

Revision ID: 9a5b2c3d8e7f
Revises: 08c6b594d255
Create Date: 2026-04-30 19:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "9a5b2c3d8e7f"
down_revision: Union[str, Sequence[str], None] = "08c6b594d255"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Legacy → broker-faithful relabel map (upgrade direction).
_FORWARD_MAP: dict[str, str] = {
    "NEW": "New",
    "FILLED": "Filled",
    "SUBMITTED": "NotReported",
    "MODIFIED": "Replaced",
    "PARTIAL": "PartialFilled",
    "CANCELLED": "Canceled",
    # REJECTED + FAILED keep the same string in the new enum.
}

# Broker-faithful → legacy relabel map (downgrade direction). Loses
# information for rows that recorded a finer-grained state introduced by
# this migration (e.g. ``WaitToNew`` collapses back to ``NEW``).
_REVERSE_MAP: dict[str, str] = {
    # All pre-exchange + live + replace states collapse to legacy NEW.
    "WaitToNew": "NEW",
    "NotReported": "SUBMITTED",
    "WaitToReplace": "SUBMITTED",
    "PendingReplace": "SUBMITTED",
    "ReplacedNotReported": "SUBMITTED",
    "ProtectedNotReported": "SUBMITTED",
    "VarietiesNotReported": "SUBMITTED",
    "New": "NEW",
    "Replaced": "MODIFIED",
    "PendingCancel": "MODIFIED",
    "WaitToCancel": "MODIFIED",
    "PartialFilled": "PARTIAL",
    "PartialWithdrawal": "PARTIAL",
    "Filled": "FILLED",
    "Canceled": "CANCELLED",
    "Expired": "CANCELLED",
    "Unknown": "FAILED",
    # REJECTED + FAILED stay the same.
}


def upgrade() -> None:
    op.add_column("push_events", sa.Column("submitted_price", sa.Float(), nullable=True))
    bind = op.get_bind()
    for legacy, canonical in _FORWARD_MAP.items():
        bind.execute(
            sa.text("UPDATE push_events SET state = :new WHERE state = :old"),
            {"new": canonical, "old": legacy},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for canonical, legacy in _REVERSE_MAP.items():
        bind.execute(
            sa.text("UPDATE push_events SET state = :new WHERE state = :old"),
            {"new": legacy, "old": canonical},
        )
    op.drop_column("push_events", "submitted_price")
